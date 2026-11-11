import os
from pathlib import Path

import pytest

from parseo import (
    assemble,
    assemble_auto,
    clear_schema_cache,
    list_schema_versions,
)


def test_assemble_missing_field_template_schema():
    schema = (
        Path(__file__).resolve().parents[1]
        / "src/parseo/schemas/copernicus/clms/hr-wsi/fsc_filename_v0_0_0.json"
    )
    fields = {
        "programme": "CLMS",
        "project": "WSI",
        "product": "FSC",
        "pixel_spacing": "020m",
        "tile_id": "T32TNS",
        "sensing_datetime": "20211018T103021",
        # "platform" is intentionally omitted
        "version": "V100",
        "variable": "FSCOG",
        "extension": "tif",
    }
    msg = r"Missing field 'platform' for schema .*fsc_filename_v0_0_0\.json"
    with pytest.raises(ValueError, match=msg):
        assemble(fields, schema_path=schema)


def test_assemble_auto_missing_optional_fields():
    fields = {
        "programme": "CLMS",
        "project": "WSI",
        "product": "WIC",
        "pixel_spacing": "020m",
        "tile_id": "T33WXP",
        "sensing_datetime": "20201024T103021",
        "platform": "S2B",
        "version": "V100",
        "variable": "WIC",
    }
    name = assemble_auto(fields)
    assert name == "CLMS_WSI_WIC_020m_T33WXP_20201024T103021_S2B_V100_WIC"


def test_clear_schema_cache(tmp_path):
    clear_schema_cache()
    schema = tmp_path / "schema.json"
    schema.write_text('{"template": "{a}_{b}"}')
    fields = {"a": "x", "b": "y"}

    assert assemble(fields, schema_path=schema) == "x_y"

    schema.write_text('{"template": "{a}-{b}"}')

    # Cached schema remains in effect
    assert assemble(fields, schema_path=schema) == "x_y"

    clear_schema_cache()
    assert assemble(fields, schema_path=schema) == "x-y"


def test_list_schema_versions():
    versions = list_schema_versions("S2")
    assert any(v["version"] == "1.0.0" for v in versions)
    assert any(v["status"] == "current" for v in versions)


def test_assemble_with_family_s2():
    fields = {
        "platform": "S2B",
        "instrument": "MSI",
        "processing_level": "L2A",
        "sensing_datetime": "20241123T224759",
        "processing_baseline": "N0511",
        "relative_orbit": "R101",
        "tile_id": "T03VUL",
        "generation_datetime": "20241123T230829",
        "extension": "SAFE",
    }
    name = assemble(fields, family="S2")
    assert (
        name
        == "S2B_MSIL2A_20241123T224759_N0511_R101_T03VUL_20241123T230829.SAFE"
    )


def test_assemble_clms_hrl_imperviousness():
    fields = {
        "variable": "IMD",
        "reference_year": "2021",
        "tile_id": "E042N018",
        "resolution": "010m",
        "version": "V100",
        "extension": "tif",
    }

    name = assemble(fields, family="IMPERVIOUSNESS")
    assert name == "IMD_2021_E042N018_010m_V100.tif"


def test_assemble_clms_n2k():
    fields = {
        "theme": "N2K",
        "reference": "2018",
        "epsg_code": "03035",
        "version": "V1_0",
        "extension": "gpkg",
    }

    name = assemble(fields, family="N2K")
    assert name == "N2K_2018_EPSG3035_V1_0.gpkg"


def test_assemble_clms_urban_atlas_with_canonical_type():
    fields = {
        "programme": "CLMS",
        "product": "UA",
        "variable": "LCU",
        "survey": "S2021",
        "representation": "vector",
        "resolution": "025ha",
        "area_code": "DK004L3",
        "city": "AALBORG",
        "epsg_code": "03035",
        "version": "V01",
        "revision": "R00",
        "production_date": "20240212",
    }

    name = assemble(fields, family="UA-LCU")
    assert name == "CLMS_UA_LCU_S2021_V025ha_DK004L3_AALBORG_03035_V01_R00_20240212"


def test_assemble_clms_clcplus_with_canonical_type():
    schema = (
        Path(__file__).resolve().parents[1]
        / "src/parseo/schemas/copernicus/clms/clcplus/ras/clcplus_filename_v0_0_1.json"
    )
    fields = {
        "programme": "CLMS",
        "product": "CLCPLUS",
        "representation": "raster",
        "season": "S2023",
        "resolution": "R10m",
        "tile_id": "E48N37",
        "epsg_code": "03035",
        "version": "V01",
        "revision": "R00",
        "extension": "tif",
    }

    name = assemble(fields, schema_path=schema)
    assert name == "CLMS_CLCPLUS_RAS_S2023_R10m_E48N37_03035_V01_R00.tif"


def test_assemble_modis_from_stac_fields():
    schema = (
        Path(__file__).resolve().parents[1]
        / "src/parseo/schemas/nasa/modis_filename_v1_0_0.json"
    )
    fields = {
        "platform": "Terra",
        "instruments": ["MODIS"],
        "product": "09",
        "variant": "GA",
        "acq_date": "2021123",
        "tile_id": "h18v04",
        "collection": "006",
        "proc_date": "2021132234506",
        "extension": "hdf",
    }

    assembled = assemble(fields, schema_path=schema)
    assert assembled == "MOD09GA.A2021123.h18v04.006.2021132234506.hdf"


def test_assemble_landsat_from_stac_fields():
    schema = (
        Path(__file__).resolve().parents[1]
        / "src/parseo/schemas/usgs/landsat/landsat_filename_v1_0_0.json"
    )
    fields = {
        "platform": "landsat-8",
        "instruments": ["OLI_TIRS"],
        "processing_level": "L1TP",
        "wrs_path": "190",
        "wrs_row": "026",
        "acq_date": "20200101",
        "proc_date": "20200114",
        "collection_number": "02",
        "tier": "T1",
        "extension": "tar",
    }

    assembled = assemble(fields, schema_path=schema)
    assert assembled == "LC08_L1TP_190026_20200101_20200114_02_T1.tar"




def test_assemble_clms_hr_vpp_from_tile_id_mgrs():
    fields = {
        "product": "VPP",
        "reference_year": "2017",
        "platform": "Sentinel-2",
        "constellation": "Sentinel-2",
        "instruments": ["MSI"],
        "tile_id": "T32TPR",
        "resolution": "010m",
        "version": "V101",
        "season": "s1",
        "variable": "AMPL",
        "extension": "tif",
    }

    name = assemble(fields, family="VPP")
    assert name == "VPP_2017_S2_T32TPR-010m_V101_s1_AMPL.tif"


def test_assemble_clms_hr_vpp_from_tile_id():
    fields = {
        "product": "VPP",
        "reference_year": "2017",
        "platform": "Sentinel-2",
        "constellation": "Sentinel-2",
        "instruments": ["MSI"],
        "tile_id": "E45N28",
        "epsg_code": "03035",
        "resolution": "010m",
        "version": "V101",
        "season": "s1",
        "variable": "EOSD",
        "extension": "tif",
    }

    name = assemble(fields, family="VPP")
    assert name == "VPP_2017_S2_E45N28-03035-010m_V101_s1_EOSD.tif"

