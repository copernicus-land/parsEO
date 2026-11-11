"""Helpers for recognizing spatial tile identifier systems."""

from __future__ import annotations

import re
from enum import Enum
from typing import Optional


class TileSystem(str, Enum):
    """Known spatial tiling systems."""

    MGRS = "mgrs"
    EEA = "eea"


_MGRS_PATTERN = re.compile(r"^T\d{2}[C-HJ-NP-X][A-Z]{2}$")
_EEA_PATTERN = re.compile(r"^[EW]\d{2,3}[NS]\d{2,3}$")


def detect_tile_system(tile: str) -> Optional[TileSystem]:
    """Return the :class:`TileSystem` matching *tile*, if any."""

    if not isinstance(tile, str):
        return None

    candidate = tile.strip().upper()
    if not candidate:
        return None

    if _MGRS_PATTERN.fullmatch(candidate):
        return TileSystem.MGRS

    if _EEA_PATTERN.fullmatch(candidate):
        return TileSystem.EEA

    return None


def normalize_tile(tile: str) -> str:
    """Return a normalised representation of *tile*.

    MGRS and EEA tiles are uppercased.  Tiles from unrecognised systems
    (e.g., MODIS sinusoidal ``h18v04``) are returned as-is.
    """

    t = tile.strip()
    if detect_tile_system(t):
        return t.upper()
    return t

