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
| `create_push` | Create a secret link (text / url / qr). Returns the share URL, never the secret. | token |
| `preview_push` | Get a push's share URL **without consuming a view**. | none |
| `expire_push` | Permanently expire a push. **Irreversible.** | token |
| `get_push_audit` | View access log (IPs, user agents, events). | token |
| `list_active_pushes` | List active pushes for the account. | token |
| `list_expired_pushes` | List expired pushes for the account. | token |
| `get_version` | Report the instance version and feature flags. | none |

> File pushes (multipart uploads) are not supported in this version.

## Configuration

Set via environment variables — **the API token is never a tool argument**:

| Variable | Required | Default | Notes |
|----------|----------|---------|-------|
| `PWPUSH_API_TOKEN` | for create/expire/audit/list | — | Generate at `<base-url>/api_tokens`. |
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
