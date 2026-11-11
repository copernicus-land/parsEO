from pathlib import Path

from parseo import assemble
from parseo import parse
from parseo import parse_auto


SCHEMA_DIR = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "parseo"
    / "schemas"
    / "copernicus"
    / "clms"
    / "urban-atlas"
)


def test_current_urban_atlas_dhm_round_trip():
    filename = "CLMS_UA-DHM_S2021_R10m_DK004L3_AALBORG_3035_V01-R00_20240212"
    schema = SCHEMA_DIR / "ua_dhm_filename_v1_0_0.json"
    result = parse_auto(filename)

    assert result.match_family == "UA-DHM"
    assert result.version == "1.0.0"
    assert result.fields["epsg_code"] == "03035"
    assert assemble(result.fields, schema_path=schema) == filename
    assert assemble(result.fields, family="UA-DHM") == filename


def test_legacy_urban_atlas_dhm_round_trip():
    filename = "DE074Lx_GÖRLITZ_UA2021_DHM.shp"
    result = parse(filename, family="UA-DHM", version="0.0.0")

    assert assemble(result.fields, family="UA-DHM", version="0.0.0") == filename
