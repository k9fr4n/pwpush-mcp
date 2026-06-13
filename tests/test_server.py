"""Tests for the low-level MCP server: tool filtering and call dispatch."""

from __future__ import annotations

import json
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import PropertyMock, patch

import httpx
import mcp.types as t
import pytest
import respx

from pwpush_mcp.config import Config
from pwpush_mcp.server import (
    PROMPT_REGISTRY,
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


async def _list_prompt_names(srv) -> list[str]:
    res = await srv.request_handlers[t.ListPromptsRequest](
        t.ListPromptsRequest(method="prompts/list")
    )
    return [p.name for p in res.root.prompts]


@contextmanager
def _with_request_headers(srv, headers: dict[str, str]):
    """Patch ``request_context`` to mimic a Streamable HTTP request.

    Starlette lowercases header keys; the server reads them lowercased, so the
    test passes lowercase keys directly.
    """
    request = SimpleNamespace(headers=headers)
    ctx = SimpleNamespace(request=request)
    with patch.object(type(srv), "request_context", new_callable=PropertyMock, return_value=ctx):
        yield


async def _get_prompt(srv, name: str, arguments: dict):
    req = t.GetPromptRequest(
        method="prompts/get",
        params=t.GetPromptRequestParams(name=name, arguments=arguments),
    )
    res = await srv.request_handlers[t.GetPromptRequest](req)
    return res.root


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


# -- multi-tenant per-request credentials ------------------------------------


async def test_per_request_credentials_builds_tenant_client():
    srv = build_server(_cfg(api_token="server-token", per_request_credentials=True))
    with _with_request_headers(srv, {"x-pwpush-token": "tenant-tok", "x-pwpush-email": "t@x.io"}):
        client = srv._client_for_request(srv._client)
    assert client is not srv._client
    assert client._config.api_token == "tenant-tok"
    assert client._config.api_email == "t@x.io"
    # Operator-controlled settings come from the server config, not the tenant.
    assert client._config.base_url == BASE


async def test_per_request_disabled_ignores_headers():
    srv = build_server(_cfg(api_token="server-token", per_request_credentials=False))
    with _with_request_headers(srv, {"x-pwpush-token": "tenant-tok"}):
        client = srv._client_for_request(srv._client)
    assert client is srv._client  # mode off -> header ignored


async def test_per_request_missing_header_falls_back_to_env_client():
    srv = build_server(_cfg(per_request_credentials=True))
    with _with_request_headers(srv, {}):
        client = srv._client_for_request(srv._client)
    assert client is srv._client


async def test_per_request_without_request_context_falls_back():
    # stdio transport: no HTTP request in scope -> env client.
    srv = build_server(_cfg(per_request_credentials=True))
    assert srv._client_for_request(srv._client) is srv._client


async def test_per_request_clients_are_isolated():
    srv = build_server(_cfg(per_request_credentials=True))
    with _with_request_headers(srv, {"x-pwpush-token": "alice"}):
        a = srv._client_for_request(srv._client)
    with _with_request_headers(srv, {"x-pwpush-token": "bob"}):
        b = srv._client_for_request(srv._client)
    assert a is not b
    assert a._config.api_token == "alice"
    assert b._config.api_token == "bob"


@respx.mock
async def test_per_request_token_reaches_the_wire():
    # End-to-end: the tenant's header token (not the server token) is sent.
    route = respx.post(f"{BASE}/api/v2/pushes.json").mock(
        return_value=httpx.Response(201, json={"url_token": "x", "html_url": f"{BASE}/p/x"})
    )
    srv = build_server(_cfg(api_token="server-token", per_request_credentials=True))
    with _with_request_headers(srv, {"x-pwpush-token": "tenant-tok"}):
        await _call(srv, "create_push", {"payload": "s"})
    assert route.calls.last.request.headers["Authorization"] == "Bearer tenant-tok"


@pytest.mark.parametrize("name", [s.name for s in TOOL_REGISTRY])
def test_every_tool_schema_is_object(name):
    spec = next(s for s in TOOL_REGISTRY if s.name == name)
    assert spec.input_schema["type"] == "object"
    assert spec.input_schema.get("additionalProperties") is False


# -- prompts -----------------------------------------------------------------


async def test_default_exposes_all_prompts():
    srv = build_server(_cfg())
    assert set(await _list_prompt_names(srv)) == {s.name for s in PROMPT_REGISTRY}


async def test_read_only_removes_write_prompts():
    srv = build_server(_cfg(read_only=True))
    names = set(await _list_prompt_names(srv))
    assert names == {"preview_push"}  # create_push / expire_push are write prompts


async def test_enabled_tools_allowlist_filters_prompts():
    srv = build_server(_cfg(enabled_tools=("preview_*",)))
    assert set(await _list_prompt_names(srv)) == {"preview_push"}


async def test_get_prompt_create_push_builds_message():
    srv = build_server(_cfg())
    res = await _get_prompt(srv, "create_push", {"payload": "hunter2", "duration": "1h"})
    text = res.messages[0].content.text
    assert res.messages[0].role == "user"
    assert "hunter2" in text and "1h" in text
    assert "create_push" in text


async def test_get_prompt_missing_required_arg_raises():
    srv = build_server(_cfg())
    with pytest.raises(ValueError, match="url_token"):
        await _get_prompt(srv, "preview_push", {})


async def test_get_prompt_expire_requires_confirmation():
    srv = build_server(_cfg())
    res = await _get_prompt(srv, "expire_push", {"url_token": "tok123"})
    text = res.messages[0].content.text
    assert "tok123" in text
    assert "IRREVERSIBLE" in text and "Confirm" in text


async def test_get_unknown_prompt_raises():
    srv = build_server(_cfg())
    with pytest.raises(ValueError, match="unknown or disabled prompt"):
        await _get_prompt(srv, "does_not_exist", {})
