from pathlib import Path

import pytest

from parseo import assemble
from parseo.parser import parse


SCHEMA_DIR = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "parseo"
    / "schemas"
    / "copernicus"
    / "clms"
    / "euhydro"
)


@pytest.mark.parametrize(
    ("version", "filename", "subtheme", "data_type"),
    [
        ("0_0_0", "CLMS_EUHYDRO_NET_S2026_V10m_EU_03035_V02_R00_20261015.gpkg", "NET", "V"),
        ("0_0_1", "CLMS_EUHYDRO_WBO_IE_NIR_V02.gpkg", "WBO", None),
        ("0_0_1", "CLMS_EUHYDRO_DIR_IE_NIR_V02.tif", "DIR", None),
    ],
)
def test_euhydro_schema_round_trip(version, filename, subtheme, data_type):
    schema_path = SCHEMA_DIR / f"euhydro_filename_v{version}.json"
    result = parse(filename, schema_path=schema_path)

    assert result.valid
    assert result.fields["subtheme"] == subtheme
    assert result.fields.get("type") == data_type
    assert assemble(result.fields, schema_path=schema_path) == filename
