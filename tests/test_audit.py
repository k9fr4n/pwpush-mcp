"""Tests for the structured audit log and secret scrubbing."""

from __future__ import annotations

import hashlib
import json
import logging

import httpx
import mcp.types as t
import respx

from pwpush_mcp import audit
from pwpush_mcp.config import Config
from pwpush_mcp.server import build_server

BASE = "https://pwpush.test"


def _cfg(**kw) -> Config:
    kw.setdefault("base_url", BASE)
    kw.setdefault("api_token", "tok")
    kw.setdefault("api_version", "v2")
    kw.setdefault("audit_log", True)
    return Config(**kw)


async def _call(srv, name, arguments):
    req = t.CallToolRequest(
        method="tools/call", params=t.CallToolRequestParams(name=name, arguments=arguments)
    )
    res = await srv.request_handlers[t.CallToolRequest](req)
    return res.root.content[0].text


# -- scrub -------------------------------------------------------------------


def test_scrub_masks_bearer_token():
    assert audit.scrub("Authorization: Bearer abc123") == "Authorization: Bearer ***"


def test_scrub_masks_v1_user_token():
    assert "secret" not in audit.scrub("X-User-Token: secret")


def test_scrub_is_idempotent():
    once = audit.scrub("Authorization: Bearer x")
    assert audit.scrub(once) == once


# -- redaction ---------------------------------------------------------------


def test_log_call_redacts_secret_args(caplog):
    audit.configure(enabled=True)
    with caplog.at_level(logging.INFO, logger="pwpush_mcp.audit"):
        audit.log_call(
            "create_push",
            {
                "payload": "s3cret",
                "passphrase": "p",
                "name": "release-key",
                "note": "private-note",
                "duration": "1d",
            },
        )
    raw = caplog.records[-1].message
    record = json.loads(raw)
    assert record["tool"] == "create_push"
    assert record["args"]["payload"] == "***"
    assert record["args"]["passphrase"] == "***"
    assert record["args"]["name"] == "***"  # name redacted in args
    assert record["args"]["note"] == "***"  # creator-private note redacted
    assert record["args"]["duration"] == "1d"  # non-secret kept
    # name is hashed (not verbatim) in target for grep-ability
    digest = hashlib.sha256(b"release-key").hexdigest()[:12]
    assert record["target"] == f"name:sha256:{digest}"
    assert "release-key" not in raw
    assert "private-note" not in raw
    assert record["status"] == "ok"


def test_configure_disabled_silences(caplog):
    audit.configure(enabled=False)
    with caplog.at_level(logging.INFO, logger="pwpush_mcp.audit"):
        audit.log_call("expire_push", {"url_token": "t"})
    assert not [r for r in caplog.records if r.name == "pwpush_mcp.audit"]


# -- integration through the server -----------------------------------------


@respx.mock
async def test_write_tool_emits_audit_line(caplog):
    respx.delete(f"{BASE}/api/v2/pushes/tok123.json").mock(
        return_value=httpx.Response(200, json={"url_token": "tok123", "expired": True})
    )
    srv = build_server(_cfg())
    with caplog.at_level(logging.INFO, logger="pwpush_mcp.audit"):
        await _call(srv, "expire_push", {"url_token": "tok123"})
    lines = [json.loads(r.message) for r in caplog.records if r.name == "pwpush_mcp.audit"]
    assert any(line["tool"] == "expire_push" and line["target"] == "tok123" for line in lines)


@respx.mock
async def test_read_tool_does_not_audit(caplog):
    respx.get(f"{BASE}/api/v2/pushes/tok123/preview.json").mock(
        return_value=httpx.Response(200, json={"url_token": "tok123"})
    )
    srv = build_server(_cfg())
    with caplog.at_level(logging.INFO, logger="pwpush_mcp.audit"):
        await _call(srv, "preview_push", {"url_token": "tok123"})
    assert not [r for r in caplog.records if r.name == "pwpush_mcp.audit"]
