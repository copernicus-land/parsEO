from pathlib import Path

import pytest

from parseo import assemble
import parseo.schema_registry as schema_registry
from parseo.parser import ParseError
from parseo.parser import parse
from parseo.parser import parse_auto


SCHEMA_PATH = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "parseo"
    / "schemas"
    / "copernicus"
    / "clms"
    / "hrl"
    / "nvlcc_filename_v0_0_2.json"
)


def test_nvlcc_schema_accepts_only_nvlcc_theme():
    filename = "CLMS_NVLCC_IMCCS_C2018-2021_R20m_E09N27_03035_V01_R01.tif"
    result = parse(filename, schema_path=SCHEMA_PATH)
    assert result.fields["theme"] == "NVLCC"
    assert assemble(result.fields, schema_path=SCHEMA_PATH) == filename

    with pytest.raises(ParseError) as exc:
        parse(filename.replace("_NVLCC_", "_VLCC_"), schema_path=SCHEMA_PATH)
    assert exc.value.field == "theme"


@pytest.mark.parametrize(
    ("versions", "expected_version"),
    [
        (("0_0_1", "0_0_2", "0_0_0"), "0.0.1"),
        (("0_0_0", "0_0_2", "0_0_1"), "0.0.0"),
    ],
)
def test_nvlcc_metadata_is_independent_of_discovery_order(
    monkeypatch, versions, expected_version
):
    paths = [
        SCHEMA_PATH.with_name(f"nvlcc_filename_v{version}.json")
        for version in versions
    ]
    monkeypatch.setattr(schema_registry, "_iter_schema_paths", lambda pkg: iter(paths))
    schema_registry.clear_cache()
    try:
        info = schema_registry.discover_families()["NVLCC"]
        assert info["current"] == "0.0.2"
        assert set(info["versions"]) == {"0.0.0", "0.0.1", "0.0.2"}
        result = parse_auto("CLMS_HRLNVLCC_IMD_S2021_R10m_E09N27_03035_V01_R01.tif")
        assert result.match_family == "NVLCC"
        assert result.version == expected_version
        assert result.status == "deprecated"
    finally:
        schema_registry.clear_cache()
