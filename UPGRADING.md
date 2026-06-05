# Upgrading

Migration notes between releases. See [`CHANGELOG.md`](CHANGELOG.md) for the full
list of changes.

## 0.1.0 → 0.2.0

No breaking changes to the **tool surface**: the seven tools, their names, and
their arguments are unchanged. Existing `mcpServers` configurations keep working.

### What changed under the hood

- **Server backend** moved from FastMCP to the low-level MCP SDK. If you imported
  internals (e.g. `from pwpush_mcp.server import mcp`), note that `mcp` no longer
  exists — use `build_server()` which returns a `PwpushMCPServer`. The tool
  surface over the wire is identical.
- **Dependencies**: `fastmcp` was replaced by `mcp[cli]`, plus `uvicorn` and
  `starlette` for the HTTP transport. A fresh install picks these up automatically.

### New, opt-in capabilities (no action required)

- **HTTP transport**: add `--listen 8000` to run over Streamable-HTTP/SSE instead
  of stdio.
- **Security knobs**: `PWPUSH_READ_ONLY`, `PWPUSH_ENABLED_TOOLS`,
  `PWPUSH_AUDIT_LOG` (audit is **on by default**; one JSON line per write tool on
  stderr — set `PWPUSH_AUDIT_LOG=false` to silence).
- **Reliability knobs**: `PWPUSH_MAX_CONCURRENT`, `PWPUSH_MAX_RETRIES`,
  `PWPUSH_TIMEOUT`. Defaults retry transient 429/5xx twice with backoff; set
  `PWPUSH_MAX_RETRIES=0` to restore the previous fail-fast behaviour.

### Distribution

Once `v0.2.0` is released, the image is available at
`ghcr.io/k9fr4n/pwpush-mcp:latest` and the package at `pip install pwpush-mcp`
(`uvx pwpush-mcp`). Before the first release, install from source.
