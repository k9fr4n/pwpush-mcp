"""Tests for the CLI entry point (transport selection, arg parsing)."""

from __future__ import annotations

import pytest

from pwpush_mcp import __main__ as cli


@pytest.fixture
def captured_run(monkeypatch):
    """Capture the coroutine handed to asyncio.run instead of running it."""
    seen: dict[str, object] = {}

    def fake_run(coro):
        seen["name"] = coro.cr_code.co_name
        coro.close()  # avoid "coroutine was never awaited" warnings

    monkeypatch.setattr(cli.asyncio, "run", fake_run)
    # from_env must not fail in the minimal test env.
    monkeypatch.setenv("PWPUSH_BASE_URL", "https://pwpush.test")
    return seen


def test_help_exits_zero():
    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])
    assert exc.value.code == 0


def test_default_selects_stdio(captured_run):
    assert cli.main([]) == 0
    assert captured_run["name"] == "_run_stdio"


def test_listen_selects_http(captured_run):
    assert cli.main(["--listen", "8123"]) == 0
    assert captured_run["name"] == "_run_http"


def test_invalid_log_level_rejected():
    with pytest.raises(SystemExit):
        cli.main(["--log-level", "TRACE"])


async def test_run_stdio_builds_server(monkeypatch):
    """_run_stdio wires build_server() to a stdio transport without real I/O."""
    monkeypatch.setenv("PWPUSH_BASE_URL", "https://pwpush.test")
    ran: dict[str, bool] = {}

    class _FakeServer:
        _cfg = type("C", (), {"verify_ssl": True})()

        def create_initialization_options(self):
            return {}

        async def run(self, r, w, opts):
            ran["run"] = True

    class _FakeStdio:
        async def __aenter__(self):
            return ("r", "w")

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(cli, "build_server", lambda: _FakeServer())
    import mcp.server.stdio as stdio

    monkeypatch.setattr(stdio, "stdio_server", lambda: _FakeStdio())
    await cli._run_stdio()
    assert ran.get("run") is True
