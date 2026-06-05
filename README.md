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
| `PWPUSH_BASE_URL` | no | `https://pwpush.com` | EU: `https://eu.pwpush.com`. Self-hosted: your domain. |

`duration` accepts a human label (`15m`, `30m`, `45m`, `1h`, `6h`, `12h`, `1d`,
`2d`, `3d`, `4d`, `5d`, `6d`, `1w`, `2w`, `3w`, `1mo`, `2mo`, `3mo`) or the raw
enum index `0`–`17`.

## Install & run

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
pytest
```

## License

MIT — see [LICENSE](LICENSE).
