from parseo import assemble
from parseo import parse
from parseo import parse_auto


def test_current_urban_atlas_stl_vector_round_trip():
    filename = "CLMS_UA-STL_S2021_V025ha_DK004L3_AALBORG_3035_V01-R00_20240212"
    result = parse(filename, family="UA-STL", version="1.0.0")

    assert result.fields["type"] == "V"
    assert result.fields["resolution"] == "025ha"
    assert result.fields["representation"] == "vector"
    assert parse_auto(filename).match_family == "UA-STL"
    assert assemble(result.fields, family="UA-STL", version="1.0.0") == filename

    fields = dict(result.fields)
    del fields["type"]
    assert assemble(fields, family="UA-STL", version="1.0.0") == filename


def test_legacy_urban_atlas_stl_round_trip():
    filename = "CLMS_UA_STL_S2021_VEC_AT001L3_WIEN_03035_V01_R01_20251030.gpkg"
    result = parse(filename, family="UA-STL", version="0.0.0")
    assert result.fields["type"] == "VEC"
    assert assemble(result.fields, family="UA-STL", version="0.0.0") == filename
