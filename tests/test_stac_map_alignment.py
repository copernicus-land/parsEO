"""Test that stac_map target field names align with STAC common metadata."""
from __future__ import annotations

import json
import os
import pathlib
from collections import defaultdict

import pytest

SCHEMAS_ROOT = pathlib.Path(__file__).resolve().parent.parent / "src" / "parseo" / "schemas"

# Known valid STAC 1.1.0 common metadata property names that stac_map may target.
# Sources:
#   https://github.com/radiantearth/stac-spec/blob/v1.1.0/item-spec/common-metadata.md
#   https://stac-extensions.github.io/ (sat, eo, projection, raster, processing, etc.)
#
# NOTE: 'representation' is not a STAC common metadata property — it encodes product
# classification (vector vs raster) from filename tokens. It appears in parsed fields
# only, not in STAC Item properties.
# Keep it listed here as intentional; revisit if stac_map output is ever directly merged
# into STAC Item properties.
#
# Add new entries here when new stac_map targets appear in schema files.
# This is a positive list — entries not in it will be flagged.
VALID_STAC_PROPERTIES: set[str] = {
    # Common metadata (STAC 1.1.0)
    "platform",
    "instruments",
    "constellation",
    "mission",
    "gsd",
    "created",
    "updated",
    "start_datetime",
    "end_datetime",
    "datetime",
    # Product classification (non-STAC, but intentional — see note above)
    "representation",
    # sat extension
    "sat:orbit_state",
    "sat:absolute_orbit",
    "sat:relative_orbit",
    "sat:platform_international_designator",
    # eo extension
    "eo:cloud_cover",
    "eo:bands",
    # projection extension
    "proj:code",
    "proj:shape",
    "proj:bbox",
    "proj:epsg",
    "proj:wkt2",
    # raster extension
    "raster:bands",
    # processing extension
    "processing:level",
    "processing:facility",
    "processing:software",
    # view extension
    "view:off_nadir",
    "view:incidence_angle",
    "view:azimuth",
    "view:sun_azimuth",
    "view:sun_elevation",
    # grid extension
    "grid:code",
}


def iter_schema_files() -> list[pathlib.Path]:
    """Yield all parsEO schema JSON files."""
    files = []
    for root, _dirs, fnames in os.walk(SCHEMAS_ROOT):
        for f in fnames:
            if f.endswith(".json") and "filename_v" in f:
                files.append(pathlib.Path(root) / f)
    return files


def get_stac_map_targets(schema: dict) -> dict[str, set[str]]:
    """Extract stac_map target field names from a schema, grouped by source field.

    Returns {stac_field_name: {source_field_names, ...}}
    """
    targets: dict[str, set[str]] = defaultdict(set)
    fields = schema.get("fields", {})
    for field_name, spec in fields.items():
        if not isinstance(spec, dict):
            continue
        raw_map = spec.get("stac_map")
        if not isinstance(raw_map, dict):
            continue
        values = raw_map.get("values", raw_map)
        if not isinstance(values, dict):
            continue
        for token, mapping in values.items():
            if not isinstance(mapping, dict):
                continue
            for target_key in mapping:
                targets[target_key].add(field_name)
    return dict(targets)


def test_all_stac_map_targets_are_valid():
    """Every stac_map target field name must be a known STAC property.

    Adding a new property to a schema's stac_map requires adding it to
    VALID_STAC_PROPERTIES in this test file — this is intentional so that
    new mappings are reviewed for STAC compliance.
    """
    unknown: dict[str, list[str]] = {}
    known: dict[str, list[str]] = {}

    for schema_path in iter_schema_files():
        with open(schema_path) as fh:
            schema = json.load(fh)
        targets = get_stac_map_targets(schema)
        if not targets:
            continue
        sid = schema.get("schema_id", str(schema_path))
        for target, sources in targets.items():
            entry = f"{sid} (field: {', '.join(sorted(sources))})"
            if target in VALID_STAC_PROPERTIES:
                known.setdefault(target, []).append(entry)
            else:
                unknown.setdefault(target, []).append(entry)

    # Report known mappings for visibility
    if known:
        print("\n=== Known STAC property mappings ===")
        for prop in sorted(known):
            print(f"  {prop}:")
            for loc in known[prop]:
                print(f"    - {loc}")

    # Fail on unknown mappings
    if unknown:
        lines = ["\n=== Unknown/Invalid STAC property names ==="]
        for prop in sorted(unknown):
            lines.append(f"  '{prop}' is not in VALID_STAC_PROPERTIES. Used in:")
            for loc in unknown[prop]:
                lines.append(f"    - {loc}")
        pytest.fail("\n".join(lines), pytrace=False)