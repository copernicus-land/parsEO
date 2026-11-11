import pytest
import urllib.error
import parseo.stac_http as sd


@pytest.mark.parametrize(
    "alias, expected",
    [
        ("SENTINEL2_L2A", "sentinel-2-l2a"),
        ("SENTINEL2_L1C", "sentinel-2-l1c"),
        ("SENTINEL-2-L1C", "sentinel-2-l1c"),
    ],
)
def test_norm_collection_id_aliases(monkeypatch, alias, expected):
    monkeypatch.setattr(
        sd,
        "_list_collections_cached",
        lambda base_url: ("sentinel-2-l2a", "sentinel-2-l1c"),
    )
    assert sd._norm_collection_id(alias, base_url="http://x") == expected


def test_list_collections_custom_base_url(monkeypatch):
    urls = []

    def fake_read_json(url):
        urls.append(url)
        return {"collections": [{"id": "abc"}]}

    monkeypatch.setattr(sd, "_read_json", fake_read_json)
    out = sd.list_collections_http(base_url="http://x")
    assert urls == ["http://x/collections"]
    assert out == ["abc"]


def test_list_collections_deep(monkeypatch):
    calls = []

    responses = {
        "http://x/collections": {"collections": [{"id": "top"}]},
        "http://x/": {
            "links": [
                {"rel": "child", "href": "A"},
                {"rel": "child", "href": "cat"},
            ]
        },
        "http://x/A": {"type": "Collection", "id": "A"},
        "http://x/cat": {"links": [{"rel": "child", "href": "B"}]},
        "http://x/cat/B": {"type": "Collection", "id": "B"},
    }

    def fake_read_json(url):
        calls.append(url)
        return responses[url]

    monkeypatch.setattr(sd, "_read_json", fake_read_json)

    out = sd.list_collections_http(base_url="http://x", deep=True)
    assert set(out) == {"top", "A", "B"}
    assert set(calls) == set(responses)


def test_iter_asset_filenames_custom_base_url(monkeypatch):
    urls = []

    def fake_read_json(url):
        urls.append(url)
        if url == "http://y/collections/C1/items?limit=2":
            return {
                "features": [
                    {"assets": {"a": {"href": "http://files/file1.tif"}}}
                ],
                "links": [
                    {
                        "rel": "next",
                        "href": "http://y/collections/C1/items?page=2",
                    }
                ],
            }
        if url == "http://y/collections/C1/items?page=2":
            return {
                "features": [
                    {"assets": {"b": {"href": "http://files/file2.tif"}}}
                ],
                "links": [],
            }
        raise AssertionError(f"Unexpected URL {url}")

    monkeypatch.setattr(sd, "_read_json", fake_read_json)
    monkeypatch.setattr(sd, "_list_collections_cached", lambda base_url: ("C1",))
    out = list(sd.iter_asset_filenames("C1", base_url="http://y", limit=2))
    assert urls == [
        "http://y/collections/C1/items?limit=2",
        "http://y/collections/C1/items?page=2",
    ]
    assert out == ["file1.tif", "file2.tif"]


def test_iter_asset_filenames_resolves_templates(monkeypatch):
    def fake_read_json(url):
        return {
            "features": [
                {
                    "properties": {"name": "F", "suffix": "tif"},
                    "assets": {
                        "templated": {"href": "http://files/$name.$suffix"},
                        "missing": {"href": "http://files/$missing.$suffix"},
                        "plain": {"href": "http://files/plain.tif"},
                    },
                }
            ]
        }

    monkeypatch.setattr(sd, "_read_json", fake_read_json)
    out = list(sd.iter_asset_filenames("C1", base_url="http://y"))
    assert out == ["F.tif", "plain.tif"]


def test_iter_asset_filenames_uses_title(monkeypatch):
    def fake_read_json(url):
        return {
            "features": [
                {
                    "assets": {
                        "a": {
                            "title": "from-title.tif",
                            "href": "http://files/Products('from-href')/$value",
                        }
                    }
                }
            ]
        }

    monkeypatch.setattr(sd, "_read_json", fake_read_json)
    out = list(sd.iter_asset_filenames("C1", base_url="http://y"))
    assert out == ["from-title.tif"]


def test_iter_asset_filenames_odata_href(monkeypatch):
    def fake_read_json(url):
        return {
            "features": [
                {
                    "assets": {
                        "a": {
                            "href": "http://host/odata/v1/Products('NAME')/$value"
                        }
                    }
                }
            ]
        }

    monkeypatch.setattr(sd, "_read_json", fake_read_json)
    out = list(sd.iter_asset_filenames("C1", base_url="http://y"))
    assert out == ["NAME"]


def test_iter_asset_filenames_strips_query_and_fragment(monkeypatch):
    def fake_read_json(url):
        return {
            "features": [
                {
                    "assets": {
                        "a": {
                            "href": "http://host/path/file.tif?token=1#frag"
                        },
                        "b": {
                            "href": "http://host/path/file?token=1#frag"
                        },
                    }
                }
            ]
        }

    monkeypatch.setattr(sd, "_read_json", fake_read_json)
    out = list(sd.iter_asset_filenames("C1", base_url="http://y"))
    assert out == ["file.tif", "file.dat"]


def test_iter_asset_filenames_sanitizes(monkeypatch):
    def fake_read_json(url):
        return {
            "features": [
                {
                    "assets": {
                        "a": {"href": "http://host/path/../evil/fi*le.tif"},
                        "b": {"title": "../weird?name"},
                    }
                }
            ]
        }

    monkeypatch.setattr(sd, "_read_json", fake_read_json)
    out = list(sd.iter_asset_filenames("C1", base_url="http://y"))
    assert out == ["fi_le.tif", "weird_name"]


def test_iter_asset_filenames_generic_title_uses_href(monkeypatch):
    """Assets with a generic title should fall back to the href."""

    def fake_read_json(url):
        return {
            "features": [
                {
                    "assets": {
                        "a": {
                            "title": "Product",
                            "href": "http://host/odata/v1/Products('NAME')/$value",
                        }
                    }
                }
            ]
        }

    monkeypatch.setattr(sd, "_read_json", fake_read_json)
    out = list(sd.iter_asset_filenames("C1", base_url="http://y"))
    assert out == ["NAME"]


def test_iter_asset_filenames_skips_value_href(monkeypatch):
    def fake_read_json(url):
        return {
            "features": [
                {
                    "assets": {
                        "skip": {"href": "http://host/path/$value"},
                        "keep": {"href": "http://host/path/file.tif"},
                    }
                }
            ]
        }

    monkeypatch.setattr(sd, "_read_json", fake_read_json)
    out = list(sd.iter_asset_filenames("C1", base_url="http://y"))
    assert out == ["file.tif"]


def test_sample_collection_filenames_custom_base_url(monkeypatch):
    called = {}

    def fake_iter_tree(collection_id, *, base_url, limit, asset_role=None):
        called["collection"] = collection_id
        called["base_url"] = base_url
        called["limit"] = limit
        called["asset_role"] = asset_role
        yield (collection_id, "f1")
        yield (collection_id, "f2")
        yield (collection_id, "f3")

    monkeypatch.setattr(sd, "iter_collection_tree", fake_iter_tree)
    res = sd.sample_collection_filenames(
        "COL", 2, base_url="http://z", asset_role="data"
    )
    assert called == {
        "collection": "COL",
        "base_url": "http://z",
        "limit": 2,
        "asset_role": "data",
    }
    assert res == {"COL": ["f1", "f2"]}


def test_sample_collection_filenames_alias(monkeypatch):
    monkeypatch.setattr(
        sd,
        "_list_collections_cached",
        lambda base_url: ("sentinel-2-l2a",),
    )

    def fake_read_json(url):
        return {"links": []}

    monkeypatch.setattr(sd, "_read_json", fake_read_json)

    def fake_iter_asset(collection_id, *, base_url, limit, asset_role=None):
        yield from ["a", "b"]

    monkeypatch.setattr(sd, "iter_asset_filenames", fake_iter_asset)

    alias_res = sd.sample_collection_filenames(
        "SENTINEL2_L2A", base_url="http://z"
    )
    official_res = sd.sample_collection_filenames(
        "sentinel-2-l2a", base_url="http://z"
    )
    assert alias_res == official_res == {"sentinel-2-l2a": ["a", "b"]}


def test_sample_collection_filenames_nested(monkeypatch):
    """Ensure nested child collections are sampled."""

    collections = {
        "ROOT": [{"rel": "child", "href": "collections/C1"}, {"rel": "child", "href": "collections/C2"}],
        "C1": [],
        "C2": [{"rel": "child", "href": "collections/C3"}],
        "C3": [],
    }

    def fake_read_json(url):
        cid = url.split("/")[-1]
        return {"links": collections[cid]}

    monkeypatch.setattr(sd, "_read_json", fake_read_json)
    monkeypatch.setattr(sd, "_list_collections_cached", lambda base_url: ("ROOT", "C1", "C2", "C3"))

    def fake_iter_asset(collection_id, *, base_url, limit=100):
        return iter({
            "C1": ["a1", "a2"],
            "C3": ["c1", "c2"],
        }[collection_id])

    def fake_iter_asset_role(collection_id, *, base_url, limit=100, asset_role=None):
        return fake_iter_asset(collection_id, base_url=base_url, limit=limit)

    monkeypatch.setattr(sd, "iter_asset_filenames", fake_iter_asset_role)
    res = sd.sample_collection_filenames("ROOT", 1, base_url="http://x")
    assert res == {"C1": ["a1"], "C3": ["c1"]}


def test_iter_asset_filenames_filters_role(monkeypatch):
    def fake_read_json(url):
        return {
            "features": [
                {
                    "assets": {
                        "a": {"href": "http://files/a.tif", "roles": ["data"]},
                        "b": {"href": "http://files/b.tif", "roles": ["metadata"]},
                    }
                }
            ]
        }

    monkeypatch.setattr(sd, "_read_json", fake_read_json)
    out = list(
        sd.iter_asset_filenames("C1", base_url="http://y", asset_role="data")
    )
    assert out == ["a.tif"]


def test_sample_collection_filenames_forwards_asset_role(monkeypatch):
    called = {}

    def fake_iter_tree(collection_id, *, base_url, limit, asset_role=None):
        called["asset_role"] = asset_role
        yield (collection_id, "f")

    monkeypatch.setattr(sd, "iter_collection_tree", fake_iter_tree)
    sd.sample_collection_filenames("COL", base_url="http://x", asset_role="data")
    assert called["asset_role"] == "data"


def test_list_collections_requires_base_url():
    with pytest.raises(TypeError):
        sd.list_collections_http()


def test_iter_asset_filenames_bad_collection(monkeypatch):
    def fake_read_json(url):
        raise urllib.error.HTTPError(url, 404, "Not Found", None, None)

    monkeypatch.setattr(sd, "_read_json", fake_read_json)
    monkeypatch.setattr(sd, "_list_collections_cached", lambda base_url: ())
    with pytest.raises(sd.StacClientError) as exc:
        list(sd.iter_asset_filenames("BAD", base_url="http://u"))
    assert (
        str(exc.value)
        == "Collection 'BAD' not found at http://u/. Use `parseo stac-sample <collection> --stac-url <url>` with a valid collection ID."
    )


def test_sample_collection_filenames_url_error(monkeypatch):
    """Connection issues should result in a clear error message."""

    def fake_urlopen(url):
        raise urllib.error.URLError("fail")

    monkeypatch.setattr(sd.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(sd.StacClientError) as exc:
        sd.sample_collection_filenames("C1", base_url="http://bad")
    assert str(exc.value).startswith(
        "Could not connect to http://bad/collections"
    )


def test_list_collections_cached_deep(monkeypatch):
    """Cached collection listing should include nested catalogs."""

    called = {}

    def fake_list_collections_http(base_url, *, deep=False):
        called["deep"] = deep
        return ["A"]

    sd._list_collections_cached.cache_clear()
    monkeypatch.setattr(sd, "list_collections_http", fake_list_collections_http)
    sd._list_collections_cached("http://x")
    assert called["deep"] is True

