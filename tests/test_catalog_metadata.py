"""Guard against drift between TOOL_REGISTRY and catalog/metadata.json.

The Docker MCP Gateway discovers a server's tool list from the
``io.docker.server.metadata`` OCI label, which is built from
``catalog/metadata.json``. If a tool is added to ``TOOL_REGISTRY`` but the
catalog is not regenerated, the gateway will not forward calls to it.

Refresh after adding/removing a tool::

    python scripts/gen_metadata.py >/dev/null
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pwpush_mcp.server import TOOL_REGISTRY

CATALOG = Path(__file__).parent.parent / "catalog" / "metadata.json"

_REGEN_HINT = (
    "Run `python scripts/gen_metadata.py >/dev/null` and commit the updated "
    "catalog/metadata.json (source of truth for the io.docker.server.metadata label)."
)


@pytest.fixture(scope="module")
def metadata() -> dict:
    assert CATALOG.is_file(), f"missing {CATALOG}"
    with CATALOG.open(encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture(scope="module")
def catalog_names(metadata) -> set[str]:
    tools = metadata.get("tools")
    assert isinstance(tools, list)
    return {tool["name"] for tool in tools}


@pytest.fixture(scope="module")
def registry_names() -> set[str]:
    return {spec.name for spec in TOOL_REGISTRY}


def test_no_tool_missing_from_catalog(registry_names, catalog_names):
    missing = registry_names - catalog_names
    assert not missing, f"missing from catalog: {sorted(missing)}.\n{_REGEN_HINT}"


def test_no_stale_tool_in_catalog(registry_names, catalog_names):
    stale = catalog_names - registry_names
    assert not stale, f"stale catalog entries: {sorted(stale)}.\n{_REGEN_HINT}"


def test_every_tool_has_a_description(metadata):
    empty = [t["name"] for t in metadata["tools"] if not (t.get("description") or "").strip()]
    assert not empty, f"tools with empty description: {empty}"


def test_server_identity(metadata):
    assert metadata.get("name") == "pwpush-mcp"
    assert metadata.get("type") == "server"
