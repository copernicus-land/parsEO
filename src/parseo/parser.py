# src/parseo/parser.py
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import as_file
from importlib.resources import files
from pathlib import Path
import re
from typing import Any
from typing import Dict
from typing import Iterable
from typing import Optional
from typing import Union

from ._field_mappings import apply_schema_mappings
from .schema_registry import _discover_family_info
from .schema_registry import _get_schema_paths
from .schema_registry import _load_json_from_path
from .schema_registry import get_schema_path
from .schema_registry import list_schema_families
from .schema_registry import SCHEMAS_ROOT
from .schema_registry import to_display_family
from .template import _field_regex
from .template import compile_template



@dataclass(frozen=True)
class ParseResult:
    """Result of a parsing attempt."""
    valid: bool
    fields: Dict[str, str]
    version: Optional[str] = None
    status: Optional[str] = None
    match_family: Optional[str] = None  # e.g., "S1", "S2", "LANDSAT"


@dataclass
class ParseError(Exception):
    """Raised when a filename nearly matches a schema but fails on a field."""

    field: str
    expected: str
    value: str
    schema_id: Optional[str] = None
    match_family: Optional[str] = None

    def __post_init__(self) -> None:
        super().__init__(str(self))

    def __str__(self) -> str:  # pragma: no cover - trivial
        base = (
            f"Invalid value '{self.value}' for field '{self.field}': expected {self.expected}"
        )
        extras = []
        if self.match_family:
            extras.append(f"schema family '{self.match_family}'")
        if self.schema_id:
            extras.append(f"schema '{self.schema_id}'")
        if extras:
            base = f"{base} (nearest match: {', '.join(extras)})"
        return base


# ---------------------------
# Core helpers
# ---------------------------

# Per-schema caches — avoid mutating lru_cache'd schema dicts
_SCHEMA_PATTERN_CACHE: dict[int, str] = {}
_SCHEMA_ORDER_CACHE: dict[int, list[str]] = {}


@lru_cache(maxsize=512)
def _compile_pattern(pattern: str, ignore_case: bool = False) -> re.Pattern:
    flags = re.IGNORECASE if ignore_case else 0
    return re.compile(pattern, flags)


def _pattern_from_schema(schema: Dict) -> Optional[str]:
    """Return a compiled regex pattern derived from a schema's template.

    The compiled pattern and field order are cached in module-level dicts
    keyed by ``id(schema)`` to avoid mutating the lru_cache'd schema object,
    which would be thread-unsafe.
    """

    sid = id(schema)
    cached = _SCHEMA_PATTERN_CACHE.get(sid)
    if cached is not None:
        return cached

    template = schema.get("template")
    if isinstance(template, str):
        fields = schema.get("fields", {})
        pattern, order = compile_template(template, fields)
        _SCHEMA_PATTERN_CACHE[sid] = pattern
        if order:
            _SCHEMA_ORDER_CACHE.setdefault(sid, order)
        return pattern

    return None


def _get_fields_order(schema: Dict) -> list[str]:
    """Return the field order for *schema*, from cache or the schema itself."""
    return _SCHEMA_ORDER_CACHE.get(id(schema)) or schema.get("fields_order", [])


def _match_filename(name: str, schema: Dict, ignore_case: bool = False) -> Optional[re.Match]:
    patt = _pattern_from_schema(schema)
    if not isinstance(patt, str) or not patt:
        return None
    rx = _compile_pattern(patt, ignore_case=ignore_case)
    return rx.match(name)


def _family_from_path(path: Path, info: Dict[str, Any]) -> Optional[str]:
    for fam_name, meta in info.items():
        if getattr(meta, "schema_path", None) == path:
            return fam_name
        versions = getattr(meta, "versions", {})
        for ver_path, _status in getattr(versions, "values", lambda: [])():
            if ver_path == path:
                return fam_name
    return None


def _guess_product_family(name: str, info: Dict[str, Any]) -> Optional[str]:
    """Return a schema family hint derived from *name*."""

    upper_name = name.upper()
    for fam, meta in info.items():
        tokens = getattr(meta, "tokens", ())
        if any(upper_name.startswith(tok) for tok in tokens):
            return fam
    return None


def _normalize_epsg_fields(fields: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize EPSG-related fields to consistently use 5-digit codes."""

    normalized = {k: v for k, v in fields.items() if v is not None}
    for key, value in list(normalized.items()):
        if not isinstance(key, str):
            continue
        key_lower = key.lower()
        if "epsg" not in key_lower and key_lower not in {"tile", "tile_id"}:
            continue
        if isinstance(value, str) and value.isdigit() and len(value) in {4, 5}:
            normalized[key] = value.zfill(5)
    return normalized


def _extract_fields(name: str, schema: Dict, ignore_case: bool = False) -> Dict[str, str]:
    """
    Extract named groups as fields from 'name' using the schema's regex.
    If the regex doesn't match, return an empty dict.
    """
    m = _match_filename(name, schema, ignore_case=ignore_case)
    if not m:
        return {}
    extracted = m.groupdict()
    enriched = apply_schema_mappings(extracted, schema)
    return _normalize_epsg_fields(enriched)


def _try_validate(name: str, schema: Dict, ignore_case: bool = False) -> bool:
    return _match_filename(name, schema, ignore_case=ignore_case) is not None


def _attempt_parse(
    name: str,
    info: Dict[str, Any],
    candidates: Iterable[Path],
    product_hint: Optional[str],
    ignore_case: bool = False,
) -> tuple[Optional[ParseResult], Optional[ParseError], Optional[Exception]]:
    """Attempt to parse *name* once and return result with diagnostics."""

    near_miss: Optional[ParseError] = None
    near_miss_prefix = -1
    first_error: Optional[Exception] = None

    hinted_meta = info.get(product_hint) if product_hint else None
    hinted = hinted_meta.schema_path if hinted_meta else None
    if hinted and hinted.exists():
        try:
            schema = _load_json_from_path(hinted)
            canonical_family = product_hint or _family_from_path(hinted, info)
            if _try_validate(name, schema, ignore_case=ignore_case):
                display_family = to_display_family(canonical_family)
                return (
                    ParseResult(
                        valid=True,
                        fields=_extract_fields(name, schema, ignore_case=ignore_case),
                        version=hinted_meta.version if hinted_meta else None,
                        status=hinted_meta.status if hinted_meta else None,
                        match_family=display_family,
                    ),
                    None,
                    None,
                )
            mismatch = _explain_match_failure(name, schema, ignore_case=ignore_case)
            if mismatch:
                field, expected, value = mismatch
                display_family = to_display_family(canonical_family)
                near_miss = ParseError(
                    field,
                    expected,
                    value,
                    schema_id=schema.get("schema_id"),
                    match_family=display_family,
                )
                near_miss_prefix = _matching_prefix_length(
                    name, schema, field, ignore_case=ignore_case
                )
        except ParseError as err:
            near_miss = err
        except Exception:
            # Schema loading/parsing can raise OSError (I/O), ValueError
            # (JSON), or re.error (bad pattern).  Skip and try next schema.
            pass

    for p in candidates:
        try:
            schema = _load_json_from_path(p)
        except Exception as exc:
            if first_error is None:
                first_error = exc
            continue
        if _try_validate(name, schema, ignore_case=ignore_case):
            matched_family = None
            version = None
            status = None
            for fam_name, meta in info.items():
                if meta.schema_path == p:
                    matched_family = fam_name
                    version = meta.version
                    status = meta.status
                    break
                for ver, (path, st) in meta.versions.items():
                    if path == p:
                        matched_family = fam_name
                        version = ver
                        status = st
                        break
                if matched_family:
                    break
            display_family = to_display_family(matched_family or product_hint)
            return (
                ParseResult(
                    valid=True,
                    fields=_extract_fields(name, schema, ignore_case=ignore_case),
                    version=version,
                    status=status,
                    match_family=display_family,
                ),
                None,
                None,
            )
        mismatch = _explain_match_failure(name, schema, ignore_case=ignore_case)
        if mismatch:
            field, expected, value = mismatch
            prefix_length = _matching_prefix_length(
                name, schema, field, ignore_case=ignore_case
            )
            if prefix_length > near_miss_prefix:
                canonical_family = _family_from_path(p, info)
                display_family = to_display_family(canonical_family or product_hint)
                near_miss = ParseError(
                    field,
                    expected,
                    value,
                    schema_id=schema.get("schema_id"),
                    match_family=display_family,
                )
                near_miss_prefix = prefix_length

    return None, near_miss, first_error


def _named_group_spans(pattern: str) -> Dict[str, tuple[int, int]]:
    spans: Dict[str, tuple[int, int]] = {}
    stack: list[tuple[Optional[str], int]] = []
    i = 0
    in_class = False
    while i < len(pattern):
        ch = pattern[i]
        if ch == "\\":
            i += 2
            continue
        if in_class:
            if ch == "]":
                in_class = False
            i += 1
            continue
        if ch == "[":
            in_class = True
            i += 1
            continue
        if ch == "(":
            if pattern.startswith("(?P<", i):
                j = i + 4
                k = pattern.index(">", j)
                name = pattern[j:k]
                stack.append((name, i))
                i = k + 1
            else:
                stack.append((None, i))
                i += 1
            continue
        if ch == ")":
            name, start = stack.pop()
            if name:
                spans[name] = (start, i + 1)
            i += 1
            continue
        i += 1
    return spans


def _balanced_prefix(pattern: str, index: int) -> str:
    """Return the longest balanced prefix of *pattern* up to *index*."""

    index = min(index, len(pattern))
    in_class = False
    depth = 0
    last_balanced = 0
    i = 0
    while i < index:
        ch = pattern[i]
        if ch == "\\":
            i += 2
            if depth == 0:
                last_balanced = min(i, index)
            continue
        if in_class:
            if ch == "]":
                in_class = False
            i += 1
            if depth == 0:
                last_balanced = min(i, index)
            continue
        if ch == "[":
            in_class = True
            i += 1
            continue
        if ch == "(":
            depth += 1
            i += 1
            continue
        if ch == ")":
            if depth > 0:
                depth -= 1
            i += 1
            if depth == 0:
                last_balanced = min(i, index)
            continue
        i += 1
        if depth == 0:
            last_balanced = min(i, index)

    return pattern[:last_balanced]


def _balanced_slice(pattern: str, end: int) -> str:
    """Return a balanced slice of *pattern* that includes *end*."""

    end = min(end, len(pattern))
    # Track parenthesis depth up to ``end``.
    stack: list[str] = []
    in_class = False
    i = 0
    while i < end:
        ch = pattern[i]
        if ch == "\\":
            i += 2
            continue
        if in_class:
            if ch == "]":
                in_class = False
            i += 1
            continue
        if ch == "[":
            in_class = True
            i += 1
            continue
        if ch == "(":
            stack.append("(")
            i += 1
            continue
        if ch == ")":
            if stack:
                stack.pop()
            i += 1
            continue
        i += 1

    j = end
    in_class_after = in_class
    stack_after = list(stack)
    while stack_after and j < len(pattern):
        ch = pattern[j]
        if ch == "\\":
            j += 2
            continue
        if in_class_after:
            if ch == "]":
                in_class_after = False
            j += 1
            continue
        if ch == "[":
            in_class_after = True
            j += 1
            continue
        if ch == "(":
            stack_after.append("(")
            j += 1
            continue
        if ch == ")":
            stack_after.pop()
            j += 1
            continue
        j += 1

    # Include trailing quantifiers that modify the just-closed group.
    while j < len(pattern):
        ch = pattern[j]
        if ch in "?*+":
            j += 1
            continue
        if ch == "{":
            depth = 1
            k = j + 1
            while k < len(pattern) and depth:
                nxt = pattern[k]
                if nxt == "\\":
                    k += 2
                    continue
                if nxt == "{":
                    depth += 1
                    k += 1
                    continue
                if nxt == "}":
                    depth -= 1
                    k += 1
                    continue
                k += 1
            j = k
            if j < len(pattern) and pattern[j] == "?":
                j += 1
            continue
        break

    return pattern[:j]


def _matching_prefix_length(
    name: str, schema: Dict, field: str, ignore_case: bool = False
) -> int:
    pattern = _pattern_from_schema(schema)
    if not pattern:
        return 0
    spans = _named_group_spans(pattern)
    if field not in spans:
        return 0
    prefix = _balanced_prefix(pattern, spans[field][0])
    match = _compile_pattern(prefix, ignore_case=ignore_case).match(name)
    return match.end() if match else 0


def _explain_match_failure(name: str, schema: Dict, ignore_case: bool = False) -> Optional[tuple[str, str, str]]:
    pattern = _pattern_from_schema(schema)
    fields = schema.get("fields", {})
    order = _get_fields_order(schema)
    if not pattern or not order:
        return None
    spans = _named_group_spans(pattern)
    for i, field in enumerate(order):
        next_end = spans[order[i + 1]][1] if i + 1 < len(order) else len(pattern)
        prefix_pat = _balanced_slice(pattern, next_end) + ".*$"
        if not _compile_pattern(prefix_pat, ignore_case=ignore_case).match(name):
            before_pat = _balanced_prefix(pattern, spans[field][0])
            m_before = _compile_pattern(before_pat, ignore_case=ignore_case).match(name)
            start_pos = len(m_before.group(0)) if m_before else 0
            target_field = field
            spec = fields.get(target_field, {})
            field_rx = re.compile(_field_regex(spec))
            m_field = field_rx.match(name[start_pos:])
            if m_field and i + 1 < len(order):
                next_field = order[i + 1]
                next_spec = fields.get(next_field, {})
                before_next = _balanced_prefix(pattern, spans[next_field][0])
                m_before_next = _compile_pattern(before_next, ignore_case=ignore_case).match(name)
                if m_before_next:
                    start_pos = len(m_before_next.group(0))
                else:
                    current_end = _balanced_slice(pattern, spans[field][1])
                    m_current_end = _compile_pattern(current_end, ignore_case=ignore_case).match(name)
                    start_pos = len(m_current_end.group(0)) if m_current_end else start_pos
                target_field = next_field
                spec = next_spec
                field_rx = re.compile(_field_regex(spec))
                m_field = field_rx.match(name[start_pos:])
                if m_field:
                    # Both the current and subsequent field values satisfy
                    # their specifications; defer to later iterations.
                    continue
            if m_field:
                # No informative mismatch could be identified.
                continue
            end_pos = len(name)
            for sep in ["_", ".", "-"]:
                idx = name.find(sep, start_pos)
                if idx != -1:
                    boundary = idx if idx > start_pos else idx + 1
                    end_pos = min(end_pos, boundary)
            value = name[start_pos:end_pos]
            if "enum" in spec:
                expected = f"one of {spec['enum']}"
            elif "pattern" in spec:
                expected = f"pattern {spec['pattern']}"
            else:
                expected = "a different value"
            return target_field, expected, value
    return None


# ---------------------------
# Public API
# ---------------------------


def list_schemas(pkg: str = __package__) -> list[str]:
    """Return a list of available mission family names."""
    return list_schema_families(pkg)


def describe_schema(
    family: str, version: Optional[str] = None, pkg: str = __package__
) -> dict[str, Any]:
    """Return schema metadata and field descriptions for ``family``.

    Parameters
    ----------
    family:
        Mission family name (case-insensitive).
    version:
        Optional semantic version. When omitted, the schema marked as
        ``"current"`` for the family is used.
    pkg:
        Package that hosts the schemas. Defaults to the installed
        :mod:`parseo` package.
    """

    try:
        schema_path = get_schema_path(family, version=version, pkg=pkg)
    except KeyError:
        raise

    schema = _load_json_from_path(schema_path)
    fields: Dict[str, Dict[str, Any]] = {}
    for name, spec in schema.get("fields", {}).items():
        if isinstance(spec, dict):
            fields[name] = {
                k: spec[k]
                for k in ("type", "enum", "pattern", "description")
                if k in spec
            }

    out: Dict[str, Any] = {
        "schema_id": schema.get("schema_id"),
        "schema_version": schema.get("schema_version"),
        "status": schema.get("status"),
        "description": schema.get("description"),
        "fields": fields,
    }

    template = schema.get("template")
    if isinstance(template, str):
        out["template"] = template

    examples = schema.get("examples")
    if isinstance(examples, list):
        out["examples"] = [e for e in examples if isinstance(e, str)]

    return out


def parse(
    name: str,
    schema_path: Union[str, Path, None] = None,
    *,
    family: Optional[str] = None,
    version: Optional[str] = None,
    pkg: str = __package__,
    ignore_case: bool = False,
) -> ParseResult:
    """Parse ``name`` using a specific schema.

    Parameters
    ----------
    name:
        Filename to parse.
    schema_path:
        Path to the schema JSON file. Optional when ``family`` is provided.
    family:
        Schema family identifier (e.g. ``"S2"``). Ignored when
        ``schema_path`` is given.
    version:
        Semantic version string to resolve together with ``family``.
    pkg:
        Package that hosts the schemas. Defaults to the installed
        :mod:`parseo` package.
    ignore_case:
        When ``True``, perform case-insensitive matching. Defaults to ``False``.
    """

    if schema_path is None:
        if not family:
            raise ValueError("Provide either 'schema_path' or 'family'.")
        schema_path = get_schema_path(family, version=version, pkg=pkg)

    resolved_path = Path(schema_path)
    schema = _load_json_from_path(resolved_path)

    if not _try_validate(name, schema, ignore_case=ignore_case):
        schema_id = schema.get("schema_id") if isinstance(schema.get("schema_id"), str) else None
        family_hint = None
        if schema_id:
            family_hint = schema_id.split(":")[-1]
        elif family:
            family_hint = family
        display_family = to_display_family(family_hint) if family_hint else None
        mismatch = _explain_match_failure(name, schema, ignore_case=ignore_case)
        if mismatch:
            field, expected, value = mismatch
            raise ParseError(
                field=field,
                expected=expected,
                value=value,
                schema_id=schema_id,
                match_family=display_family,
            )
        raise ParseError(
            field="filename",
            expected=f"pattern defined by schema {schema_id or resolved_path}",
            value=name,
            schema_id=schema_id,
            match_family=display_family,
        )

    fields = _extract_fields(name, schema, ignore_case=ignore_case)
    version_info = schema.get("schema_version")
    status_info = schema.get("status")
    schema_id = schema.get("schema_id") if isinstance(schema.get("schema_id"), str) else None
    family_hint = None
    if schema_id:
        family_hint = schema_id.split(":")[-1]
    elif family:
        family_hint = family
    display_family = to_display_family(family_hint) if family_hint else None

    return ParseResult(
        valid=True,
        fields=fields,
        version=version_info if isinstance(version_info, str) else None,
        status=status_info if isinstance(status_info, str) else None,
        match_family=display_family,
    )


def parse_auto(name: str, ignore_case: bool = False) -> ParseResult:
    """
    Try to parse `name` by matching it against any schema under schemas/**.json.
    A quick 'family' hint is derived from the filename prefix by dynamically
    inspecting available schema files. Returns a ParseResult on success;
    raises RuntimeError if nothing matches.
    
    Parameters
    ----------
    name:
        Filename to parse.
    ignore_case:
        When ``True``, perform case-insensitive matching. Defaults to ``False``.
    """
    pkg = __package__  # e.g., "parseo"
    info = _discover_family_info(pkg)
    candidates = _get_schema_paths(pkg)
    if not candidates:
        # No schema files packaged at all
        raise FileNotFoundError(f"No schemas packaged under {pkg}/{SCHEMAS_ROOT}.")

    near_miss: Optional[ParseError] = None
    first_error: Optional[Exception] = None

    product_hint = _guess_product_family(name, info)
    result, attempt_near_miss, attempt_first_error = _attempt_parse(
        name, info, candidates, product_hint, ignore_case=ignore_case
    )
    if result is not None:
        return result
    if near_miss is None and attempt_near_miss is not None:
        near_miss = attempt_near_miss
    if first_error is None and attempt_first_error is not None:
        first_error = attempt_first_error

    # Nothing matched — provide a helpful error listing what we saw
    with as_file(files(pkg).joinpath(SCHEMAS_ROOT)) as rp:
        base = Path(rp)
        seen = [str(q.relative_to(base)) for q in base.rglob("*filename_v*.json")] if base.exists() else []
    msg = (
        "No schema matched the provided name. "
        f"Looked recursively under {pkg}/{SCHEMAS_ROOT}/ and found "
        f"{len(seen)} file(s): {seen[:8]}{'…' if len(seen) > 8 else ''}"
    )
    if near_miss is not None:
        raise near_miss
    if first_error is not None:
        msg += f". First error while reading schemas: {first_error}"
        raise RuntimeError(msg) from first_error
    raise RuntimeError(msg)


def validate_schema(
    paths: Union[str, Path, Iterable[Union[str, Path]], None] = None,
    pkg: str = __package__,
    verbose: bool = False,
) -> None:
    """Validate example filenames declared in schema files.

    Parameters
    ----------
    paths: Union[str, Path, Iterable[Union[str, Path]]], optional
        Specific schema JSON file(s) to validate. Accepts either a single path
        or an iterable of paths. When omitted, all bundled schemas for *pkg*
        are checked.
    pkg: str, optional
        Package name from which to discover schemas when *paths* is ``None``.
    verbose: bool, optional
        When ``True``, print each schema path and example as they are validated,
        along with a summary count of successful validations.

    Raises
    ------
    ValueError
        If an example cannot be parsed or fails to reassemble to the original
        string.
    """

    _get_schema_paths.cache_clear()
    if paths is None:
        schema_paths = _get_schema_paths(pkg)
    elif isinstance(paths, (str, Path)):
        schema_paths = [Path(paths)]
    else:
        schema_paths = [Path(p) for p in paths]

    from .assembler import assemble  # local import to avoid cycle

    validated = 0
    for schema_path in schema_paths:
        if verbose:
            print(schema_path)
        schema = _load_json_from_path(schema_path)
        examples = schema.get("examples")
        if not isinstance(examples, list):
            continue
        for example in examples:
            if not isinstance(example, str):
                continue
            res = parse_auto(example)
            if not res.valid:
                raise ValueError(f"Parsing failed for {example}")
            fields = {
                k: v
                for k, v in _extract_fields(example, schema).items()
                if v is not None
            }
            if not fields:
                raise ValueError(
                    "Example parsed globally but not by its declared schema: "
                    f"{schema_path} -> {example}"
                )
            assembled = assemble(fields, schema_path=schema_path)
            if assembled != example:
                raise ValueError(f"Round trip failed for {example}")
            validated += 1
            if verbose:
                print(f"  {example}")
        counter_examples = schema.get("counter_examples")
        if isinstance(counter_examples, list):
            for bad in counter_examples:
                if not isinstance(bad, str):
                    continue
                if _match_filename(bad, schema):
                    raise ValueError(
                        f"Counter-example was unexpectedly matched by its "
                        f"schema: {schema_path} -> {bad}"
                    )
    if verbose:
        print(f"Validated {validated} examples")
