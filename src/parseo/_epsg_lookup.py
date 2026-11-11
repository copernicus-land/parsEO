"""Lookup helpers for deriving EPSG codes from tile identifiers."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Optional


_MGRS_LATITUDE_BANDS = {
    "C": "south",
    "D": "south",
    "E": "south",
    "F": "south",
    "G": "south",
    "H": "south",
    "J": "south",
    "K": "south",
    "L": "south",
    "M": "south",
    "N": "north",
    "P": "north",
    "Q": "north",
    "R": "north",
    "S": "north",
    "T": "north",
    "U": "north",
    "V": "north",
    "W": "north",
    "X": "north",
}


def mgrs_tile_to_epsg(tile: str) -> Optional[str]:
    """Return the EPSG code associated with a Sentinel-2 MGRS tile.

    Parameters
    ----------
    tile:
        The tile identifier (e.g. ``"T32TNS"``).
    """

    if not isinstance(tile, str) or len(tile) < 4:
        return None

    tile = tile.strip().upper()
    if not tile.startswith("T"):
        return None

    zone_part = tile[1:3]
    try:
        zone = int(zone_part)
    except ValueError:
        return None
    if not 1 <= zone <= 60:
        return None

    band = tile[3]
    hemisphere = _MGRS_LATITUDE_BANDS.get(band)
    if hemisphere is None:
        return None

    if hemisphere == "north":
        epsg = 32600 + zone
    else:
        epsg = 32700 + zone

    return f"{epsg:05d}"


@dataclass(frozen=True)
class _WRSOrbitConstants:
    """Constants derived from the WRS-2 orbital configuration."""

    orbital_period_days: float = 16.0
    paths: int = 233
    rows: int = 248
    inclination_deg: float = 98.2


_WRS_CONSTANTS = _WRSOrbitConstants()


def _path_to_longitude(path: int) -> float:
    """Approximate the longitude of the descending node for *path* (degrees)."""

    fraction = (path - 1) / _WRS_CONSTANTS.paths
    longitude = (fraction * 360.0) % 360.0
    if longitude > 180.0:
        longitude -= 360.0
    return longitude


def _row_to_latitude(row: int) -> float:
    """Approximate the latitude of the scene centre for *row* (degrees)."""

    # Rows increase from north to south. We approximate the relationship using
    # a linear fit anchored at the documented WRS limits (81°N and 81°S).
    total_rows = _WRS_CONSTANTS.rows
    span = 162.0  # 81°N to 81°S
    step = span / (total_rows - 1)
    return 81.0 - (row - 1) * step


def landsat_path_row_to_epsg(path: str, row: str) -> Optional[str]:
    """Return the EPSG code inferred from a Landsat WRS path/row pair."""

    try:
        path_num = int(path)
        row_num = int(row)
    except (TypeError, ValueError):
        return None

    if not 1 <= path_num <= _WRS_CONSTANTS.paths:
        return None
    if not 1 <= row_num <= _WRS_CONSTANTS.rows:
        return None

    longitude = _path_to_longitude(path_num)
    latitude = _row_to_latitude(row_num)

    zone = int(math.floor((longitude + 180.0) / 6.0)) + 1
    zone = max(1, min(zone, 60))

    # Special handling for Norway and Svalbard following the UTM specification.
    if 56.0 <= latitude < 64.0 and 3.0 <= longitude < 12.0:
        zone = 32
    if 72.0 <= latitude <= 84.0:
        if 0.0 <= longitude < 9.0:
            zone = 31
        elif 9.0 <= longitude < 21.0:
            zone = 33
        elif 21.0 <= longitude < 33.0:
            zone = 35
        elif 33.0 <= longitude < 42.0:
            zone = 37

    hemisphere = "north" if latitude >= 0.0 else "south"
    if hemisphere == "north":
        epsg = 32600 + zone
    else:
        epsg = 32700 + zone

    return f"{epsg:05d}"

