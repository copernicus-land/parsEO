"""Helpers for querying STAC APIs via the standard library.

The routines in this module intentionally rely only on :mod:`urllib` from the
Python standard library to avoid pulling in heavier dependencies.  For a
``pystac-client`` based alternative see :mod:`parseo.stac_scraper`.  All helper
functions require explicitly passing the ``base_url`` of the STAC service.
"""
from __future__ import annotations

from collections.abc import Iterable
from functools import lru_cache
import itertools
import json
from pathlib import Path
import re
from string import Template
from typing import Union
import urllib.error
from urllib.parse import urljoin
from urllib.parse import urlparse
import urllib.request


class StacClientError(IOError):
    """Raised when a STAC API request fails."""


def _norm_collection_id(collection_id: str, *, base_url: str) -> str:
    """Resolve ``collection_id`` to the official ID from the STAC API."""

    norm = re.sub(r"[^A-Za-z0-9]", "", collection_id).upper()
    for cid in _list_collections_cached(base_url):
        if re.sub(r"[^A-Za-z0-9]", "", cid).upper() == norm:
            return cid
    return collection_id


def _norm_base(base_url: str) -> str:
    """Return ``base_url`` with exactly one trailing slash."""
    return base_url.rstrip("/") + "/"


def _read_json(url: str) -> dict:
    try:
        with urllib.request.urlopen(url) as resp:  # type: ignore[call-arg]
            return json.load(resp)
    except urllib.error.URLError as err:
        raise StacClientError(f"Could not connect to {url}: {err.reason}") from err


def list_collections_http(base_url: str, *, deep: bool = False) -> list[str]:
    """Return available collection IDs from the STAC API using ``urllib``.

    This lightweight helper performs raw HTTP requests without requiring
    third-party libraries.  If ``deep`` is ``True`` the function follows
    ``rel='child'`` links and gathers collection IDs from nested catalogs as
    well.  For a variant powered by ``pystac-client`` see
    :func:`parseo.stac_scraper.list_collections_client`.
    """
    base = _norm_base(base_url)

    # First, fetch the standard ``/collections`` endpoint which should expose
    # top-level collections for STAC APIs.
    url = urljoin(base, "collections")
    try:
        data = _read_json(url)
    except urllib.error.HTTPError as err:
        raise StacClientError(f"HTTP error {err.code} for {err.geturl()}") from err

    collections = {c["id"] for c in data.get("collections", [])}

    if not deep:
        return sorted(collections)

    # Breadth-first traversal of child links starting from the catalog root.
    to_visit = [base]
    visited: set[str] = set()

    while to_visit:
        cur = to_visit.pop()
        if cur in visited:
            continue
        visited.add(cur)
        try:
            data = _read_json(cur)
        except urllib.error.HTTPError as err:
            raise StacClientError(f"HTTP error {err.code} for {err.geturl()}") from err

        # Collect IDs if this document represents a collection or includes
        # embedded collections.
        if data.get("type") == "Collection":
            cid = data.get("id")
            if cid:
                collections.add(cid)
        for coll in data.get("collections", []):
            cid = coll.get("id")
            if cid:
                collections.add(cid)

        # Queue any child links for further traversal.
        for link in data.get("links", []):
            if link.get("rel") == "child":
                href = link.get("href")
                if href:
                    base_cur = cur if cur.endswith("/") else cur + "/"
                    to_visit.append(urljoin(base_cur, href))

    return sorted(collections)


@lru_cache(maxsize=32)
def _list_collections_cached(base_url: str) -> tuple[str, ...]:
    """Cached helper returning collection IDs for ``base_url``."""
    # Use a deep listing to include collections nested in child catalogs.
    # This ensures that `_norm_collection_id` can resolve aliases for
    # collections not present at the top-level of the STAC service.
    return tuple(list_collections_http(base_url, deep=True))


def iter_asset_filenames(
    collection_id: str,
    *,
    base_url: str,
    limit: int = 100,
    asset_role: Union[str, None] = None,
) -> Iterable[str]:
    """Yield asset filenames from items of a collection.

    Pagination links (``rel="next"``) are followed until all pages are
    exhausted or ``limit`` filenames have been yielded.  When ``asset_role`` is
    provided, only assets declaring that role are considered.  Resulting
    filenames are sanitized: directory components are stripped and any
    characters outside ``[A-Za-z0-9._-]`` are replaced with ``_``.
    """
    base = _norm_base(base_url)
    collection_id = _norm_collection_id(collection_id, base_url=base)
    url = urljoin(base, f"collections/{collection_id}/items?limit={limit}")
    remaining = limit
    first_request = True
    while url and remaining > 0:
        try:
            data = _read_json(url)
        except urllib.error.HTTPError as err:
            if first_request and err.code == 404:
                raise StacClientError(
                    f"Collection '{collection_id}' not found at {base}. "
                    "Use `parseo stac-sample <collection> --stac-url <url>` with a valid collection ID."
                ) from err
            raise StacClientError(f"HTTP error {err.code} for {err.geturl()}") from err
        first_request = False
        for feat in data.get("features", []):
            props = feat.get("properties", {})
            assets = feat.get("assets", {})
            for asset in assets.values():
                if asset_role and asset_role not in (asset.get("roles") or []):
                    continue
                title = asset.get("title")
                href = asset.get("href")
                filename = None
                # Many assets use a generic title like "Product" which does not
                # convey the actual filename.  In such cases prefer extracting
                # the name from the href.  Only fall back to the title if it is
                # present and not the generic "Product".
                if title and title.strip().lower() != "product":
                    filename = title
                elif href:
                    if "$" in href:
                        href_sub = Template(href).safe_substitute(props)
                        if re.search(r"\$(?!value\b)\w+", href_sub):
                            continue
                        href = href_sub
                    m = re.search(r"Products\('([^']+)'\)", href)
                    if m:
                        filename = m.group(1)
                    else:
                        parsed_url = urlparse(href)
                        path = Path(parsed_url.path)
                        filename = path.name
                        if not path.suffix:
                            filename += ".dat"
                else:
                    continue
                if filename.startswith("$"):
                    continue
                filename = Path(filename).name
                filename = re.sub(r"[^A-Za-z0-9._-]", "_", filename)
                yield filename
                remaining -= 1
                if remaining == 0:
                    return
        url = None
        for link in data.get("links", []):
            if link.get("rel") == "next":
                url = link.get("href")
                break

def iter_collection_tree(
    collection_id: str,
    *,
    base_url: str,
    limit: int = 100,
    asset_role: Union[str, None] = None,
) -> Iterable[tuple[str, str]]:
    """Yield ``(collection_id, filename)`` pairs for all leaf collections.

    The function follows ``links`` with ``rel="child"`` starting from
    ``collection_id`` until it reaches leaf collections.  For each leaf it
    yields filenames from :func:`iter_asset_filenames`.  The ``asset_role``
    parameter is forwarded to :func:`iter_asset_filenames`.
    """
    base = _norm_base(base_url)
    collection_id = _norm_collection_id(collection_id, base_url=base)
    url = urljoin(base, f"collections/{collection_id}")
    try:
        data = _read_json(url)
    except urllib.error.HTTPError as err:
        if err.code == 404:
            raise StacClientError(
                f"Collection '{collection_id}' not found at {base}. "
                "Use `parseo stac-sample <collection> --stac-url <url>` with a valid collection ID."
            ) from err
        raise StacClientError(f"HTTP error {err.code} for {err.geturl()}") from err

    children = [
        link.get("href", "").rstrip("/").split("/")[-1]
        for link in data.get("links", [])
        if link.get("rel") == "child"
    ]

    if children:
        for child in children:
            yield from iter_collection_tree(
                child, base_url=base, limit=limit, asset_role=asset_role
            )
    else:
        for fn in itertools.islice(
            iter_asset_filenames(
                collection_id, base_url=base, limit=limit, asset_role=asset_role
            ),
            limit,
        ):
            yield collection_id, fn


def sample_collection_filenames(
    collection_id: str,
    samples: int = 5,
    *,
    base_url: str,
    asset_role: Union[str, None] = None,
) -> dict[str, list[str]]:
    """Return ``samples`` filenames for each leaf collection.

    ``collection_id`` may be the official STAC ID or any case/format variant
    resolvable via :func:`list_collections_http`.  When ``collection_id`` has
    child collections, a sample is collected from each leaf.  Only assets whose
    ``roles`` include ``asset_role`` are returned when the parameter is
    supplied.
    """
    out: dict[str, list[str]] = {}
    for cid, fn in iter_collection_tree(
        collection_id, base_url=base_url, limit=samples, asset_role=asset_role
    ):
        lst = out.setdefault(cid, [])
        if len(lst) < samples:
            lst.append(fn)
    return out
