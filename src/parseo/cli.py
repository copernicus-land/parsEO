# src/parseo/cli.py
from __future__ import annotations

import argparse
import json
import sys
from typing import Any
from typing import Dict
from typing import List
from typing import Union

from parseo import __version__
from parseo.assembler import assemble
from parseo.assembler import assemble_auto
from parseo.parser import ParseError
from parseo.parser import describe_schema  # parser helpers
from parseo.parser import parse
from parseo.parser import parse_auto
from parseo.schema_registry import discover_families
from parseo.stac_http import StacClientError
from parseo.stac_http import list_collections_http
from parseo.stac_http import sample_collection_filenames


# ---------- small utilities ----------

def _build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="parseo", description="parsEO CLI")
    ap.add_argument(
        "--version",
        action="version",
        version=f"parseo version {__version__}",
        help="Show the installed parseo version and exit",
    )
    sp = ap.add_subparsers(dest="cmd", required=True)

    # parse
    p_parse = sp.add_parser("parse", help="Parse a filename")
    p_parse.add_argument("filename")
    p_parse.add_argument(
        "--output",
        help="Write the JSON result to this file instead of stdout. Use '-' for stdout.",
    )
    p_parse.add_argument(
        "--schema",
        help="Path to a schema JSON file to parse with instead of auto-detection.",
    )
    p_parse.add_argument(
        "--family",
        help="Schema family to use for parsing (e.g. 'S2', 'LANDSAT'). When omitted, auto-detection is used.",
    )
    p_parse.add_argument(
        "--ignore-case",
        action="store_true",
        help="Perform case-insensitive matching (default is case-sensitive).",
    )

    # list-schemas
    p_list = sp.add_parser("list-schemas", help="List available schema families")
    p_list.add_argument(
        "--family",
        help="Only include schemas belonging to this mission family (e.g. 'S2').",
    )
    p_list.add_argument(
        "--status",
        help="Only include schemas whose lifecycle status matches this value (case-insensitive).",
    )

    # schema-info
    p_info = sp.add_parser("schema-info", help="Show details for a mission family")
    p_info.add_argument("family", help="Mission family name, e.g. 'S2'")
    p_info.add_argument(
        "--version",
        help="Inspect a specific schema version (defaults to the current version).",
    )

    # stac-sample
    p_stac = sp.add_parser(
        "stac-sample",
        help="Print sample asset filenames from a STAC collection",
    )
    p_stac.add_argument("collection", help="STAC collection ID")
    p_stac.add_argument(
        "--samples", type=int, default=5, help="Number of filenames to list"
    )
    p_stac.add_argument(
        "--stac-url",
        required=True,
        help="Base URL of the STAC API",
    )
    p_stac.add_argument(
        "--asset-role",
        help="Only include assets whose roles contain this value",
    )

    # list-stac-collections
    p_stac_list = sp.add_parser(
        "list-stac-collections",
        help="List collection IDs available in a STAC API",
    )
    p_stac_list.add_argument(
        "--stac-url",
        required=True,
        help="Base URL of the STAC API",
    )
    p_stac_list.add_argument(
        "--deep",
        action="store_true",
        help="Recursively follow child catalogs to list nested collections",
    )

    # assemble
    p_asm = sp.add_parser(
        "assemble",
        help=(
            "Assemble a filename from fields. "
            "Provide key=value pairs OR pipe a JSON object to stdin. "
            "Schema is auto-selected using the schema's first compulsory field as defined by the template."
        ),
    )
    p_asm.add_argument(
        "fields",
        nargs="*",
        help="key=value pairs (optional if you pipe a JSON object to stdin).",
    )
    p_asm.add_argument(
        "--fields-json",
        help="JSON string with fields, or '-' to read JSON from stdin.",
    )
    p_asm.add_argument(
        "--family",
        help="Schema family to use when assembling the filename.",
    )
    p_asm.add_argument(
        "--version",
        help="Schema version to use (requires --family).",
    )

    # serve
    p_serve = sp.add_parser(
        "serve",
        help="Start the parsEO web API server (requires parseo[web])",
    )
    p_serve.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host to bind to (default: 0.0.0.0)",
    )
    p_serve.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to listen on (default: 8000)",
    )

    return ap


def _kv_pairs_to_dict(pairs: List[str]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for p in pairs:
        if "=" not in p:
            raise SystemExit(f"Invalid field '{p}'. Use key=value.")
        k, v = p.split("=", 1)
        k = k.strip()
        v = v.strip()
        if not k:
            raise SystemExit(f"Invalid field '{p}': empty key.")
        if k in out:
            raise SystemExit(f"Duplicate field '{k}'.")
        out[k] = v
    return out


def _stdin_text() -> str:
    if sys.stdin and not sys.stdin.closed and not sys.stdin.isatty():
        return sys.stdin.read()
    return ""


def _normalize_fields_payload(payload: Any, *, source: str) -> Dict[str, Any]:
    """Return a dictionary of fields from an arbitrary JSON payload."""
    if isinstance(payload, dict):
        if "fields" in payload:
            fields = payload["fields"]
            if not isinstance(fields, dict):
                raise SystemExit(
                    f"{source} contains 'fields' but it is not a JSON object."
                )
            return fields
        return payload
    raise SystemExit(f"{source} must decode to a JSON object.")


def _resolve_fields(args) -> Dict[str, Any]:
    """
    Merge sources in priority:
      1) --fields-json if provided (string or '-')
      2) JSON from stdin if available and no positional fields
      3) positional key=value pairs
    """
    # 1) --fields-json
    if args.fields_json:
        if args.fields_json == "-":
            raw = _stdin_text()
            if not raw.strip():
                raise SystemExit("--fields-json '-' set but stdin is empty.")
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError as e:
                raise SystemExit(f"--fields-json '-' is not valid JSON: {e}")
            return _normalize_fields_payload(payload, source="--fields-json '-'")
        else:
            try:
                payload = json.loads(args.fields_json)
            except json.JSONDecodeError as e:
                raise SystemExit(f"--fields-json is not valid JSON: {e}")
            return _normalize_fields_payload(payload, source="--fields-json")

    # 2) stdin JSON (only if no positional fields were given)
    if not args.fields:
        raw = _stdin_text()
        if raw.strip():
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError as e:
                raise SystemExit(f"Stdin is not valid JSON: {e}")
            return _normalize_fields_payload(payload, source="Stdin")

    # 3) positional k=v pairs
    if args.fields:
        return _kv_pairs_to_dict(args.fields)

    raise SystemExit(
        "No fields provided. Supply key=value pairs, "
        "or pass --fields-json, or pipe a JSON object via stdin."
    )


# ---------- main ----------

def main(argv: Union[List[str], None] = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    ap = _build_arg_parser()
    args = ap.parse_args(argv)

    if args.cmd == "parse":
        try:
            if args.schema:
                res = parse(args.filename, schema_path=args.schema, ignore_case=args.ignore_case)
            elif args.family:
                res = parse(args.filename, family=args.family, ignore_case=args.ignore_case)
            else:
                res = parse_auto(args.filename, ignore_case=args.ignore_case)
        except ParseError as exc:
            hint = ""
            family = getattr(exc, "match_family", None)
            if family:
                hint = (
                    f"\nHint: use `parseo schema-info {family}` to inspect the schema."
                )
            raise SystemExit(f"{exc}{hint}")
        out = {
            "valid": bool(getattr(res, "valid", False)),
            "fields": getattr(res, "fields", None),
        }
        version = getattr(res, "version", None)
        if version:
            out["version"] = version
        status = getattr(res, "status", None)
        if status:
            out["status"] = status
        mfam = getattr(res, "match_family", None)
        if mfam:
            out["match_family"] = mfam
        payload = json.dumps(out, indent=2, ensure_ascii=False)
        if args.output and args.output != "-":
            try:
                with open(args.output, "w", encoding="utf-8") as fh:
                    fh.write(f"{payload}\n")
            except OSError as exc:
                raise SystemExit(f"Failed to write to '{args.output}': {exc}") from exc
        else:
            print(payload)
        return 0

    if args.cmd == "list-schemas":
        rows: list[tuple[str, str, str, str]] = []
        catalog = discover_families()
        status_filter = args.status.lower() if args.status else None
        prefix_filter: str | None = None
        exact_family: str | None = None
        if args.family:
            if ":" in args.family:
                prefix_filter = args.family.lower()
            else:
                fam_upper = args.family.upper()
                if fam_upper in catalog:
                    exact_family = fam_upper
                else:
                    prefix_filter = args.family.lower()
        for fam in sorted(catalog):
            meta = catalog[fam]
            schema_id = meta.get("schema_id")
            if not isinstance(schema_id, str):
                continue
            if prefix_filter and not schema_id.lower().startswith(prefix_filter):
                continue
            if exact_family and fam != exact_family:
                continue
            versions = meta.get("versions", {})
            if not isinstance(versions, dict):
                continue
            for ver in sorted(versions):
                data = versions[ver]
                status = ""
                path_str = ""
                if isinstance(data, dict):
                    status = str(data.get("status") or "")
                    path = data.get("path")
                    path_str = str(path) if path is not None else ""
                elif isinstance(data, tuple) and len(data) == 2:
                    path, status_val = data
                    status = status_val or ""
                    path_str = str(path)
                if status_filter and status.lower() != status_filter:
                    continue
                rows.append((schema_id, ver, status, path_str))
        if rows:
            rows.sort(key=lambda r: (r[0], r[1]))
            headers = ("SCHEMA_ID", "VERSION", "STATUS", "FILE")
            widths = [len(h) for h in headers]
            for row in rows:
                for i in range(3):
                    widths[i] = max(widths[i], len(row[i]))
            line_fmt = f"{{:{widths[0]}}} {{:{widths[1]}}} {{:{widths[2]}}} {{}}"
            print(line_fmt.format(*headers))
            for row in rows:
                print(line_fmt.format(*row))
        else:
            if args.family and not status_filter:
                target = "family" if exact_family else "prefix"
                print(f"No schemas found for {target} '{args.family}'.")
            elif args.family and status_filter:
                target = "family" if exact_family else "prefix"
                print(
                    f"No schemas found for {target} '{args.family}' with status '{args.status}'."
                )
            elif status_filter:
                print(f"No schemas found with status '{args.status}'.")
            else:
                print("No schemas found.")
        return 0

    if args.cmd == "schema-info":
        try:
            info = describe_schema(args.family, version=args.version)
        except KeyError as e:
            raise SystemExit(str(e))
        print(json.dumps(info, indent=2, ensure_ascii=False))
        return 0

    if args.cmd == "list-stac-collections":
        for cid in list_collections_http(base_url=args.stac_url, deep=args.deep):
            print(cid)
        return 0

    if args.cmd == "stac-sample":
        samples = sample_collection_filenames(
            args.collection,
            args.samples,
            base_url=args.stac_url,
            asset_role=args.asset_role,
        )
        for cid in sorted(samples):
            print(f"{cid}:")
            for fn in samples[cid]:
                print(f"  {fn}")
        return 0

    if args.cmd == "assemble":
        fields = _resolve_fields(args)
        if args.version and not args.family:
            raise SystemExit("--version requires --family to be set.")
        if args.family:
            out = assemble(fields, family=args.family, version=args.version)
        else:
            out = assemble_auto(fields)
        print(out)
        return 0

    if args.cmd == "serve":
        try:
            from parseo.web import start
        except ImportError as e:
            raise SystemExit(
                f"web extra not installed. Run: pip install parseo[web]\n{e}"
            )
        host = getattr(args, "host", "0.0.0.0")
        port = getattr(args, "port", 8000)
        start(host=host, port=port)
        return 0

    ap.print_help()
    return 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except StacClientError as e:
        raise SystemExit(str(e)) from e
