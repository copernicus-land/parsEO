"""Utilities for translating between schema tokens and STAC values."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from typing import Dict
from typing import Mapping
from typing import Optional

from ._epsg_lookup import landsat_path_row_to_epsg
from ._epsg_lookup import mgrs_tile_to_epsg
from ._tile_systems import TileSystem
from ._tile_systems import detect_tile_system
from ._tile_systems import normalize_tile


@dataclass(frozen=True)
class FieldMapping:
    """Represents a mapping between a filename token and STAC fields."""

    preserve_as: Optional[str]
    token_map: Dict[str, Dict[str, Any]]


def _normalize_mapping_values(values: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    normalized: Dict[str, Dict[str, Any]] = {}
    for token, targets in values.items():
        if not isinstance(targets, Mapping):
            continue
        normalized[str(token)] = {str(k): v for k, v in targets.items()}
    return normalized


def get_schema_field_mappings(schema: Mapping[str, Any]) -> Dict[str, FieldMapping]:
    """Extract field mappings declared in *schema*."""

    fields = schema.get("fields", {})
    if not isinstance(fields, Mapping):
        return {}

    mappings: Dict[str, FieldMapping] = {}
    for field_name, spec in fields.items():
        if not isinstance(spec, Mapping):
            continue
        raw_map = spec.get("stac_map")
        if not isinstance(raw_map, Mapping):
            continue

        has_explicit_values = "values" in raw_map
        preserve_raw = raw_map.get("preserve_original_as")
        preserve_as: Optional[str]

        if isinstance(preserve_raw, str):
            preserve_as = preserve_raw.strip() or None
        elif isinstance(preserve_raw, bool):
            preserve_as = f"{field_name}_code" if preserve_raw else None
        elif preserve_raw is not None:
            preserve_as = str(preserve_raw).strip() or None
        else:
            preserve_as = None if has_explicit_values else f"{field_name}_code"

        values: Any
        if "values" in raw_map:
            values = raw_map.get("values")
        else:
            values = raw_map
        if not isinstance(values, Mapping):
            continue

        normalized = _normalize_mapping_values(values)
        if not normalized:
            continue

        mappings[str(field_name)] = FieldMapping(preserve_as=preserve_as, token_map=normalized)

    return mappings


def _augment_with_tile_variants(fields: Dict[str, Any]) -> Dict[str, Any]:
    enriched = dict(fields)

    mgrs_value = enriched.get("mgrs_tile")
    if isinstance(mgrs_value, str) and mgrs_value and "tile_id" not in enriched:
        enriched["tile_id"] = mgrs_value

    for candidate in ("tile", "tile_id"):
        value = enriched.get(candidate)
        if not isinstance(value, str):
            continue

        system = detect_tile_system(value)
        if system is None:
            continue

        normalized = normalize_tile(value)
        enriched[candidate] = normalized

        if system is TileSystem.MGRS and "tile_id" not in enriched:
            enriched["tile_id"] = normalized
        if system is TileSystem.EEA:
            if "tile_id" not in enriched:
                enriched["tile_id"] = normalized
            if "epsg_code" not in enriched:
                enriched["epsg_code"] = "03035"

    enriched.pop("mgrs_tile", None)
    return enriched


def _backfill_tile_tokens(
    fields: Dict[str, Any], schema: Mapping[str, Any]
) -> Dict[str, Any]:
    translated = dict(fields)
    specs = schema.get("fields", {})

    if "tile" in specs and "tile" not in translated:
        for key in ("tile_id", "mgrs_tile"):
            value = translated.get(key)
            if isinstance(value, str) and value:
                translated["tile"] = normalize_tile(value)
                break

    if "tile_id" in specs and "tile_id" not in translated:
        for key in ("tile", "mgrs_tile"):
            value = translated.get(key)
            if isinstance(value, str) and value:
                translated["tile_id"] = normalize_tile(value)
                break

    translated.pop("mgrs_tile", None)
    return translated


def apply_schema_mappings(
    extracted: Dict[str, Any], schema: Mapping[str, Any]
) -> Dict[str, Any]:
    """Augment *extracted* fields with STAC values defined in *schema*."""

    mappings = get_schema_field_mappings(schema)

    enriched = _augment_with_tile_variants(extracted)
    for field_name, mapping in mappings.items():
        token = extracted.get(field_name)
        if token is None:
            continue

        if mapping.preserve_as:
            enriched[mapping.preserve_as] = token

        targets = mapping.token_map.get(str(token))
        if not isinstance(targets, Mapping):
            continue

        for target_field, target_value in targets.items():
            enriched[target_field] = target_value

    schema_id = str(schema.get("schema_id", "")).lower()

    if "epsg_code" not in enriched:
        tile = enriched.get("tile_id")
        if (
            tile
            and "sentinel:s2" in schema_id
            and detect_tile_system(str(tile)) is TileSystem.MGRS
        ):
            epsg = mgrs_tile_to_epsg(str(tile))
            if epsg:
                enriched["epsg_code"] = epsg

    if "epsg_code" not in enriched:
        path = enriched.get("wrs_path")
        row = enriched.get("wrs_row")
        if path and row and schema_id.startswith("usgs:landsat"):
            epsg = landsat_path_row_to_epsg(str(path), str(row))
            if epsg:
                enriched["epsg_code"] = epsg

    return enriched


def translate_fields_to_tokens(
    fields: Dict[str, Any], schema: Mapping[str, Any]
) -> Dict[str, Any]:
    """Translate STAC field values in *fields* back to schema tokens."""

    mappings = get_schema_field_mappings(schema)
    if not mappings:
        return fields

    translated = _augment_with_tile_variants(fields)
    for field_name, mapping in mappings.items():
        token: Any = None

        preserved = None
        if mapping.preserve_as:
            preserved = fields.get(mapping.preserve_as)
            if preserved not in (None, ""):
                token = str(preserved)

        if token is None:
            current_value = fields.get(field_name)
            if isinstance(current_value, str) and current_value in mapping.token_map:
                token = current_value

        if token is None:
            for candidate, targets in mapping.token_map.items():
                if all(fields.get(k) == v for k, v in targets.items()):
                    token = candidate
                    break

        if token is None:
            continue

        translated[field_name] = token

    translated = _backfill_tile_tokens(translated, schema)
    return translated

