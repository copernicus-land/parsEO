"""parsEO — FastAPI web API.

Exposes parsEO core functions (assemble, parse, validate, schema registry)
over HTTP. Start with::

    parseo serve
    # or
    uvicorn parseo.web:app

Requires the ``web`` extra: ``pip install parseo[web]``.
"""

from __future__ import annotations

import json
import os
import tempfile
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from parseo import (
    __version__,
    assemble,
    assemble_auto,
    clear_schema_cache,
    get_schema_path,
    info,
    list_schema_families,
    list_schema_versions,
    parse,
    parse_auto,
    validate_schema,
)
from parseo.parser import ParseError, describe_schema

__all__ = ["app", "start"]

app = FastAPI(
    title="parsEO API",
    description="CLMS Filename Assembly & Parsing API",
    version=__version__,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── health / info ──────────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    return {"status": "ok", "version": __version__}


@app.get("/api/info")
def api_info():
    return info()


# ── schema registry ────────────────────────────────────────────────────────

@app.get("/api/families")
def api_families():
    """List all schema families."""
    return {"families": list(list_schema_families())}


@app.get("/api/families/{family}/versions")
def api_family_versions(family: str):
    """List schema versions for a family."""
    try:
        versions = list(list_schema_versions(family))
        return {"family": family, "versions": versions}
    except Exception as e:
        raise HTTPException(404, str(e))


@app.get("/api/families/{family}/schemas/{version}")
def api_schema(family: str, version: str):
    """Get a schema JSON by family + version path."""
    try:
        schema_path = get_schema_path(family, version)
        schema = json.loads(schema_path.read_text())
        return schema
    except Exception as e:
        raise HTTPException(404, str(e))


@app.get("/api/families/{family}/describe")
def api_describe(family: str, version: Optional[str] = None):
    """Describe a schema — get field names, types, constraints."""
    try:
        desc = describe_schema(family, version)
        return {"family": family, "version": version or "latest", "schema": desc}
    except Exception as e:
        raise HTTPException(404, str(e))


# ── assemble ───────────────────────────────────────────────────────────────

class AssembleRequest(BaseModel):
    family: Optional[str] = None
    version: Optional[str] = None
    fields: dict[str, Any]
    template: Optional[str] = None


class AssembleResponse(BaseModel):
    filename: str
    family: Optional[str] = None
    version: Optional[str] = None


@app.post("/api/assemble", response_model=AssembleResponse)
def api_assemble(req: AssembleRequest):
    """Assemble a filename from field values."""
    try:
        if req.template:
            from parseo.assembler import _assemble_from_template

            result = _assemble_from_template(req.template, req.fields)
            family = None
            ver = None
        elif req.family:
            result = assemble(req.fields, family=req.family, version=req.version)
            family = req.family
            ver = req.version
        else:
            result = assemble_auto(req.fields)
            family = None
            ver = None
        return AssembleResponse(filename=result, family=family, version=ver)
    except Exception as e:
        raise HTTPException(400, str(e))


# ── parse ──────────────────────────────────────────────────────────────────

class ParseRequest(BaseModel):
    filename: str
    family: Optional[str] = None
    version: Optional[str] = None


@app.post("/api/parse")
def api_parse(req: ParseRequest):
    """Parse a filename into field values."""
    try:
        if req.family:
            result = parse(req.filename, req.family, version=req.version)
        else:
            result = parse_auto(req.filename)
        return {"parsed": result}
    except ParseError as e:
        raise HTTPException(422, str(e))
    except Exception as e:
        raise HTTPException(400, str(e))


# ── validate ───────────────────────────────────────────────────────────────

class ValidateRequest(BaseModel):
    schema_data: dict[str, Any] = Field(
        ..., alias="schema", description="A parsEO schema JSON object"
    )


class ValidateResponse(BaseModel):
    valid: bool
    errors: list[str]
    warnings: list[str]


@app.post("/api/validate", response_model=ValidateResponse)
def api_validate(req: ValidateRequest):
    """Validate a parsEO schema JSON."""
    errors: list[str] = []
    warnings: list[str] = []
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(req.schema_data, f)
            tmp_path = f.name
        try:
            validate_schema(tmp_path)
        except ValueError as ve:
            errors.append(str(ve))
        except Exception as ex:
            errors.append(str(ex))
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        return ValidateResponse(valid=len(errors) == 0, errors=errors, warnings=warnings)
    except Exception as e:
        raise HTTPException(400, str(e))


# ── cache control ──────────────────────────────────────────────────────────

@app.post("/api/cache/clear")
def api_clear_cache():
    """Clear parsEO's internal schema cache."""
    clear_schema_cache()
    return {"status": "cache cleared"}


# ── run ────────────────────────────────────────────────────────────────────

def start(host: str = "0.0.0.0", port: int = 8000) -> None:
    """Start the uvicorn server (convenience for CLI)."""
    import uvicorn

    uvicorn.run("parseo.web:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8000))
    host = os.environ.get("HOST", "0.0.0.0")
    uvicorn.run("parseo.web:app", host=host, port=port, reload=True)