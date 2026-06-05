"""Tests for the low-level MCP server: tool filtering and call dispatch."""

from __future__ import annotations

import json

import httpx
import mcp.types as t
import pytest
import respx

from pwpush_mcp.config import Config
from pwpush_mcp.server import (
    TOOL_REGISTRY,
    WRITE_TOOLS,
    build_server,
)

BASE = "https://pwpush.test"


def _cfg(**kw) -> Config:
    kw.setdefault("base_url", BASE)
    kw.setdefault("api_token", "tok")
    kw.setdefault("api_version", "v2")
    kw.setdefault("audit_log", False)
    return Config(**kw)


async def _list_tool_names(srv) -> list[str]:
    res = await srv.request_handlers[t.ListToolsRequest](t.ListToolsRequest(method="tools/list"))
    return [tool.name for tool in res.root.tools]


async def _call(srv, name: str, arguments: dict):
    req = t.CallToolRequest(
        method="tools/call",
        params=t.CallToolRequestParams(name=name, arguments=arguments),
    )
    res = await srv.request_handlers[t.CallToolRequest](req)
    return res.root.content[0].text


# -- registry shape ----------------------------------------------------------


def test_write_tools_set():
    assert {"create_push", "expire_push"} == WRITE_TOOLS


def test_expire_is_marked_destructive():
    spec = next(s for s in TOOL_REGISTRY if s.name == "expire_push")
    assert spec.is_write and spec.destructive


def test_list_tools_have_annotations():
    spec = next(s for s in TOOL_REGISTRY if s.name == "preview_push")
    tool = spec.to_tool()
    assert tool.annotations.readOnlyHint is True
    assert tool.annotations.destructiveHint is False


# -- filtering ---------------------------------------------------------------


async def test_default_exposes_all_tools():
    srv = build_server(_cfg())
    assert set(await _list_tool_names(srv)) == {s.name for s in TOOL_REGISTRY}


async def test_read_only_removes_write_tools():
    srv = build_server(_cfg(read_only=True))
    names = set(await _list_tool_names(srv))
    assert names.isdisjoint(WRITE_TOOLS)
    assert "preview_push" in names


async def test_enabled_tools_allowlist():
    srv = build_server(_cfg(enabled_tools=("list_*", "get_version")))
    assert set(await _list_tool_names(srv)) == {
        "list_active_pushes",
        "list_expired_pushes",
        "get_version",
    }


async def test_read_only_blocks_write_call_defensively():
    # Even if a write tool were somehow addressed, read-only refuses it.
    srv = build_server(_cfg(read_only=True))
    text = await _call(srv, "expire_push", {"url_token": "abc"})
    assert "disabled" in text or "unknown or disabled" in text


# -- dispatch ----------------------------------------------------------------


@respx.mock
async def test_call_create_push_success():
    respx.post(f"{BASE}/api/v2/pushes.json").mock(
        return_value=httpx.Response(
            201, json={"url_token": "tok123", "html_url": f"{BASE}/p/tok123", "payload": "secret"}
        )
    )
    srv = build_server(_cfg())
    text = await _call(srv, "create_push", {"payload": "secret"})
    data = json.loads(text)
    assert data["url_token"] == "tok123"
    assert "payload" not in data  # secret stripped from the response


async def test_call_create_push_validation_message():
    srv = build_server(_cfg())
    text = await _call(srv, "create_push", {})  # neither payload nor file_paths
    assert "Error:" in text and "payload" in text


async def test_unknown_tool_returns_error_content():
    srv = build_server(_cfg())
    text = await _call(srv, "does_not_exist", {})
    assert "unknown or disabled tool" in text


@respx.mock
async def test_error_text_is_scrubbed():
    # An upstream error body echoing a bearer token must be masked in output.
    respx.post(f"{BASE}/api/v2/pushes.json").mock(
        return_value=httpx.Response(400, json={"error": "bad Authorization: Bearer leaked-token"})
    )
    srv = build_server(_cfg())
    text = await _call(srv, "create_push", {"payload": "x"})
    assert "leaked-token" not in text
    assert "***" in text


@pytest.mark.parametrize("name", [s.name for s in TOOL_REGISTRY])
def test_every_tool_schema_is_object(name):
    spec = next(s for s in TOOL_REGISTRY if s.name == name)
    assert spec.input_schema["type"] == "object"
    assert spec.input_schema.get("additionalProperties") is False
