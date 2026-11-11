from pathlib import Path

import pytest

from parseo import assemble
from parseo import parse
from parseo import parse_auto
from parseo.parser import ParseError


SCHEMA_DIR = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "parseo"
    / "schemas"
    / "copernicus"
    / "clms"
    / "hr-vpp"
)


@pytest.mark.parametrize(
    ("schema_name", "filename"),
    [
        ("vi", "CLMS_VI-NDVI_A20200101P10D_R10m_T33UVS_V01-R00.tif"),
        ("vpp", "CLMS_VPP-SOSD_A20200101P1Y_R10m_T33UVS_V01-R00.tif"),
    ],
)
def test_current_hr_vpp_schema_round_trip(schema_name, filename):
    schema = SCHEMA_DIR / f"{schema_name}_filename_v1_0_0.json"
    result = parse(filename, schema_path=schema)

    assert parse_auto(filename).valid
    assert assemble(result.fields, schema_path=schema) == filename
    for invalid in (
        filename.replace("_A20200101", "_20200101"),
        filename.replace("_R10m_", "_10m_"),
    ):
        with pytest.raises(ParseError):
            parse(invalid, schema_path=schema)
