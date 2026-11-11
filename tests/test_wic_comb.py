from pathlib import Path

from parseo import assemble
from parseo import parse
from parseo import parse_auto


def test_current_wic_comb_example_round_trip():
    schema = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "parseo"
        / "schemas"
        / "copernicus"
        / "clms"
        / "hr-wsi"
        / "wic_comb_filename_v1_0_0.json"
    )
    filename = "CLMS_WSI-WIC-WIC-COMB_20160720T105547_R20m_T31TCH_V01-R00.tif"
    result = parse(filename, schema_path=schema)

    assert result.fields["sensor"] == "COMB"
    assert parse_auto(filename).match_family == "WIC-COMB"
    assert assemble(result.fields, schema_path=schema) == filename
