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

## Prompts

User-controlled templates (slash-command style in clients that support MCP
prompts). A prompt renders a message that guides the assistant to call the
matching tool — it never touches the API itself.

| Prompt | Arguments | Drives |
|--------|-----------|--------|
| `create_push` | `payload` (required); `duration`, `expire_after_views`, `passphrase`, `name`, `note` (optional) | `create_push` |
| `preview_push` | `url_token` (required) | `preview_push` |
| `expire_push` | `url_token` (required) | `expire_push` (asks to confirm first) |

Prompts follow the same gating as tools: `PWPUSH_READ_ONLY=true` hides the
write prompts (`create_push`, `expire_push`), and `PWPUSH_ENABLED_TOOLS`
filters prompts by name too — a prompt is offered only when its tool is.

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
| `PWPUSH_FILE_ROOT` | no | — | Allowlist root for file pushes. Unset = file uploads **disabled**. When set, `create_push(file_paths=…)` may only read files under this directory (traversal/symlink escapes rejected). |
| `MCP_HTTP_TOKEN` | `--listen` only | — | Bearer token required on `/sse` and `/messages/`. `--listen` refuses to start without it (see below). |
| `MCP_HTTP_ALLOW_UNAUTHENTICATED` | no | `false` | Opt out of the bearer requirement when fronting the server with your own auth proxy. |
| `MCP_HTTP_ALLOWED_HOSTS` | no | loopback | Comma-separated `Host` allowlist (anti-DNS-rebinding). Defaults to `localhost,127.0.0.1,[::1]` + `--host`. Use `*` to allow any. |
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
  via your runtime. Secrets (`payload`, `passphrase`, `note`, `name`, file
  contents, token) are redacted; `name` is hashed in the audit `target` for
  grep-ability. The token is also redacted from `Config` reprs and error text.
- **`PWPUSH_FILE_ROOT`** gates file pushes. File uploads are **disabled by
  default** because their bytes become retrievable via the returned share URL —
  an exfiltration vector for an over-eager or malicious client. Set it to a
  directory to enable uploads from that subtree only; `~` expansion and symlink
  resolution are applied before the containment check, so `../` traversal and
  symlink escapes are rejected.

> **HTTP transport (`--listen`) is sensitive.** The server holds
> `PWPUSH_API_TOKEN` and exposes account-scoped tools. The transport has **no
> TLS** and the legacy SSE protocol has no built-in auth, so:
> - it binds **`127.0.0.1` by default** — only bind a public interface behind a
>   TLS + auth reverse proxy;
> - it **requires `MCP_HTTP_TOKEN`** (clients send `Authorization: Bearer
>   <token>`) and refuses to start without it, unless you set
>   `MCP_HTTP_ALLOW_UNAUTHENTICATED=true`;
> - it validates the `Host` header (`MCP_HTTP_ALLOWED_HOSTS`) to block
>   DNS-rebinding from a browser.
>
> `stdio` mode is unaffected by all of the above.

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

> Published as `pwpush-mcp` on PyPI and `ghcr.io/k9fr4n/pwpush-mcp` on GHCR,
> produced by the release workflow on each version tag (latest: `v0.4.0`).

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
# Requires MCP_HTTP_TOKEN; binds 127.0.0.1:8000 by default, SSE at /sse.
MCP_HTTP_TOKEN=$(openssl rand -hex 32) pwpush-mcp --listen 8000
# Clients then send:  Authorization: Bearer <MCP_HTTP_TOKEN>
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
