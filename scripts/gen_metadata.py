#!/usr/bin/env python3
"""Generate catalog/metadata.json for the Docker MCP Gateway label.

The gateway reads a server's tool list from the ``io.docker.server.metadata``
OCI label, which is built from ``catalog/metadata.json``. This script builds the
server, enumerates its enabled tools, and writes a compact JSON document. It
also prints the document to stdout so it can be injected at image-build time:

    --build-arg SERVER_METADATA="$(python scripts/gen_metadata.py)"

Re-run after adding/removing a tool and commit the resulting metadata.json
(CI fails on drift — see tests/test_catalog_metadata.py).
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# Minimal env so Config.from_env() inside build_server() never raises.
os.environ.setdefault("PWPUSH_BASE_URL", "https://pwpush.com")
os.environ.setdefault("PWPUSH_AUDIT_LOG", "false")

from pwpush_mcp.server import TOOL_REGISTRY  # noqa: E402


def schema_to_arguments(input_schema: dict) -> list:
    props = input_schema.get("properties", {})
    required = set(input_schema.get("required", []))
    args = []
    for name, prop in props.items():
        ptype = prop.get("type", "string")
        if isinstance(ptype, list):  # e.g. ["string", "null"]
            non_null = [t for t in ptype if t != "null"]
            ptype = non_null[0] if non_null else "string"
        type_map = {
            "integer": "integer",
            "number": "number",
            "boolean": "boolean",
            "array": "array",
            "object": "object",
        }
        arg = {
            "name": name,
            "type": type_map.get(ptype, "string"),
            "desc": prop.get("description", ""),
        }
        if name not in required:
            arg["optional"] = True
        args.append(arg)
    return args


def main() -> None:
    tools = []
    for spec in TOOL_REGISTRY:
        tool = {"name": spec.name, "description": " ".join(spec.description.split())}
        arguments = schema_to_arguments(spec.input_schema)
        if arguments:
            tool["arguments"] = arguments
        tools.append(tool)

    metadata = {
        "name": "pwpush-mcp",
        "type": "server",
        "title": "Password Pusher MCP Server",
        "description": (
            "MCP server for Password Pusher: create and manage self-destructing "
            "secret links. Never retrieves a payload (that consumes a view)."
        ),
        "secrets": [{"name": "pwpush-mcp.api_token", "env": "PWPUSH_API_TOKEN"}],
        "env": [
            {"name": "PWPUSH_BASE_URL", "value": "{{pwpush-mcp.base_url}}"},
            {"name": "PWPUSH_API_VERSION", "value": "{{pwpush-mcp.api_version}}"},
            {"name": "PWPUSH_READ_ONLY", "value": "{{pwpush-mcp.read_only}}"},
        ],
        "tools": tools,
    }

    out = os.path.join(os.path.dirname(__file__), "..", "catalog", "metadata.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(metadata, fh, separators=(",", ":"))
        fh.write("\n")
    print(f"Wrote {len(tools)} tools to catalog/metadata.json", file=sys.stderr)
    print(json.dumps(metadata, separators=(",", ":")))


if __name__ == "__main__":
    main()
