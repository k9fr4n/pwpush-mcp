# pwpush-mcp

A [Model Context Protocol](https://modelcontextprotocol.io) (MCP) server for
[Password Pusher](https://pwpush.com) — create and manage self-destructing
secret links from any MCP-compatible client (Claude Desktop, Claude Code, etc.).

## Why a "preview but never retrieve" design?

Retrieving a push **consumes a view** and is irreversible. To keep secrets
safe, this server **never retrieves a push payload**. It can create pushes and
hand back the shareable URL, preview that URL (without consuming a view), and
manage the lifecycle (expire, audit, list). The secret is only ever read by the
human who opens the link.

## Tools

| Tool | Description | Auth |
|------|-------------|------|
| `create_push` | Create a secret link (text / url / qr / file). Returns the share URL, never the secret. | optional* |
| `preview_push` | Get a push's share URL **without consuming a view**. | optional* |
| `expire_push` | Permanently expire a push. **Irreversible.** | optional* |
| `get_push_audit` | View access log (IPs, user agents, events). | token |
| `list_active_pushes` | List active pushes for the account. | token |
| `list_expired_pushes` | List expired pushes for the account. | token |
| `get_version` | Report the instance version and feature flags. | none |

\* The bearer token is sent whenever `PWPUSH_API_TOKEN` is set. Whether it is
*required* depends on the instance: some allow anonymous push creation, preview,
and expiry (for pushes created with `deletable_by_viewer`). Listing and audit
are always account-scoped and need a token.

### Defaults

New pushes expire after **1 view** or **7 days** (whichever comes first), with a
retrieval step enabled. Override per call via `expire_after_views` and `duration`.

### File pushes

Attach one or more local files by passing `file_paths`; `kind` is forced to
`file` and the upload is sent as multipart. `payload` is optional in that case.

## Configuration

Set via environment variables — **the API token is never a tool argument**:

| Variable | Required | Default | Notes |
|----------|----------|---------|-------|
| `PWPUSH_API_TOKEN` | depends on instance | — | Generate at `<base-url>/api_tokens`. Always needed for listing/audit. |
| `PWPUSH_API_EMAIL` | v1 auth only | — | Email tied to the token; legacy (v1) instances auth via `X-User-Email` + `X-User-Token`. |
| `PWPUSH_BASE_URL` | no | `https://pwpush.com` | EU: `https://eu.pwpush.com`. Self-hosted: your domain. |
| `PWPUSH_API_VERSION` | no | `auto` | `auto` \| `v1` \| `v2`. Auto-detects the API generation. |
| `PWPUSH_VERIFY_SSL` | no | `true` | Set `false` only for internal instances with an untrusted cert. |
| `PWPUSH_CA_BUNDLE` | no | — | Path to a CA bundle (preferred over disabling verification). |
| `PWPUSH_READ_ONLY` | no | `false` | Remove write tools (`create_push`, `expire_push`). |
| `PWPUSH_ENABLED_TOOLS` | no | — | Comma-separated `fnmatch` allowlist (e.g. `list_*,get_version`). Empty = all. |
| `PWPUSH_AUDIT_LOG` | no | `true` | Emit one redacted JSON line per write-tool call on stderr. |
| `PWPUSH_MAX_CONCURRENT` | no | `0` | Cap concurrent HTTP requests. `0` = unlimited. |
| `PWPUSH_MAX_RETRIES` | no | `2` | Retries for connection errors / `429` / `5xx` (backoff honours `Retry-After`). |
| `PWPUSH_TIMEOUT` | no | `30` | Per-request HTTP timeout, in seconds. |

### Security & multi-tenant

- **`PWPUSH_READ_ONLY=true`** strips the write tools entirely — only
  `preview_push`, `get_push_audit`, `list_*` and `get_version` remain. `expire_push`
  is the one **destructive** tool (`destructiveHint`), so clients can warn on it.
- **`PWPUSH_ENABLED_TOOLS`** narrows the exposed surface to an allowlist of
  `fnmatch` globs, e.g. expose only listing/preview to an auditor.
- **`PWPUSH_AUDIT_LOG`** (on by default) writes one JSON line per write call to
  the `pwpush_mcp.audit` logger on stderr — ship it to Loki/CloudWatch/journald
  via your runtime. Secrets (`payload`, `passphrase`, file contents, token) are
  redacted; the token is also redacted from `Config` reprs and error text.

### API v1 / v2

The server speaks both the modern **v2** API (`pwpush.com`, `eu.pwpush.com`,
recent self-hosted) and the legacy **v1** API (older self-hosted instances).
It auto-detects which one the instance exposes. Note for v1: expiry is
day-granular, so sub-day `duration` values round up to one day, and file/URL
pushes are only available if the instance enables them.

Both paths are exercised end-to-end: **v1** against a live legacy instance,
**v2** against `pwpush.com` (API 2.1). v2 calls target the `.json` endpoints
deliberately — the suffix-less paths issue a cross-host redirect, so they are
avoided to keep the payload from leaking to another host.

`duration` accepts a human label (`15m`, `30m`, `45m`, `1h`, `6h`, `12h`, `1d`,
`2d`, `3d`, `4d`, `5d`, `6d`, `1w`, `2w`, `3w`, `1mo`, `2mo`, `3mo`) or the raw
enum index `0`–`17`.

## Install & run

> Published artifacts (`pwpush-mcp` on PyPI, `ghcr.io/k9fr4n/pwpush-mcp` on GHCR)
> are produced by the release workflow on the first `v0.2.0` tag. Until then,
> install from source.

With [`uv`](https://docs.astral.sh/uv/) (recommended):

```bash
uvx pwpush-mcp
```

Or with `pipx`:

```bash
pipx run pwpush-mcp
```

From source:

```bash
pip install -e ".[dev]"
python -m pwpush_mcp
```

### Transports

`stdio` is the default (Claude Desktop / Claude Code / Docker MCP Gateway). To
expose the server over the network as Streamable-HTTP/SSE:

```bash
pwpush-mcp --listen 8000           # binds 0.0.0.0:8000, SSE at /sse
pwpush-mcp --listen 8000 --host 127.0.0.1 --log-level DEBUG
```

### Docker

```bash
docker run --rm -i \
  -e PWPUSH_BASE_URL="https://pwpush.com" \
  -e PWPUSH_API_TOKEN="your-token-here" \
  ghcr.io/k9fr4n/pwpush-mcp:latest          # stdio (default)
```

HTTP mode via `compose.yml` (override the entrypoint with `--listen`):

```bash
cp .env.example .env && $EDITOR .env
docker compose up        # serves SSE on http://localhost:8000/sse
```

For v1 (legacy self-hosted) instances also pass `-e PWPUSH_API_EMAIL=...`.

### Docker MCP Gateway

The image ships the `io.docker.server.metadata` label and a catalog entry so the
[Docker MCP Gateway](https://docs.docker.com/ai/mcp-gateway/) can spawn it
natively. See [`catalog/readme.md`](catalog/readme.md):

```bash
docker mcp catalog create pwpush-private
docker mcp catalog add  pwpush-private pwpush-mcp ./catalog/server.yaml
docker mcp server  enable pwpush-mcp
docker mcp gateway run    --catalog pwpush-private
```

## Client configuration

### Claude Desktop / Claude Code (`mcp` config)

```json
{
  "mcpServers": {
    "pwpush": {
      "command": "uvx",
      "args": ["pwpush-mcp"],
      "env": {
        "PWPUSH_API_TOKEN": "your-token-here",
        "PWPUSH_BASE_URL": "https://eu.pwpush.com"
      }
    }
  }
}
```

## Development

```bash
pip install -e ".[dev]"
ruff check src tests && ruff format --check src tests
mypy src
pytest -q --cov=pwpush_mcp --cov-fail-under=80
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the tool/env-var checklists and the
release process, and [CHANGELOG.md](CHANGELOG.md) / [UPGRADING.md](UPGRADING.md)
for version history.

## License

MIT — see [LICENSE](LICENSE).
