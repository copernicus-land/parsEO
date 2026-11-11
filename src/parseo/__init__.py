"""Top level package for parseo."""

from importlib import metadata
from .assembler import assemble
from .assembler import assemble_auto
from .assembler import clear_schema_cache
from .parser import parse
from .parser import parse_auto
from .parser import validate_schema
from .schema_registry import get_schema_path
from .schema_registry import list_schema_families
from .schema_registry import list_schema_versions

try:  # pragma: no cover - import failure handled for graceful degradation
    from . import parser  # noqa: F401  # import for side effect and re-export
except Exception:  # ImportError and others
    parser = None


try:  # pragma: no cover - gracefully handle missing distribution
    __version__ = metadata.version("parseo")
except metadata.PackageNotFoundError:  # pragma: no cover - defensive
    __version__ = "unknown"


def info() -> dict[str, str]:
    """Return information about the installed :mod:`parseo` package.

    Returns
    -------
    dict[str, str]
        A dictionary containing the installed version under the ``"version"`` key.
    """

    return {"version": __version__}


__all__ = [
    "parse",
    "parse_auto",
    "assemble",
    "assemble_auto",
    "clear_schema_cache",
    "validate_schema",
    "list_schema_families",
    "list_schema_versions",
    "get_schema_path",
    "info",
    "__version__",
]

if parser is not None:
    __all__.append("parser")
