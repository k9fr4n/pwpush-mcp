# Support

## Support matrix

| Component | Supported |
|-----------|-----------|
| Python | 3.10, 3.11, 3.12, 3.13 |
| Password Pusher API | v2 (pwpush.com, eu.pwpush.com, recent self-hosted) and legacy v1 |
| MCP clients | Claude Desktop, Claude Code, Docker MCP Gateway, LibreChat, and any MCP-compatible client (stdio or Streamable-HTTP/SSE) |
| Transports | stdio (default), HTTP/SSE via `--listen PORT` |

## Getting help

- **Questions / usage**: open a [GitHub Discussion or Issue](https://github.com/k9fr4n/pwpush-mcp/issues).
- **Bug reports**: include the pwpush-mcp version (`pip show pwpush-mcp`), the
  Password Pusher instance type (v1/v2, hosted/self-hosted), the MCP client, and
  the (scrubbed) error output. **Never paste an API token or a secret payload.**

## Security issues

Please do **not** open a public issue for a vulnerability. Report it privately
via [GitHub Security Advisories](https://github.com/k9fr4n/pwpush-mcp/security/advisories/new).

This server is designed to keep secrets out of the model and out of logs:

- The API token is read only from `PWPUSH_API_TOKEN`, never a tool argument.
- Push payloads are never retrieved or returned.
- `payload` / `passphrase` / file contents are stripped from responses and audit
  lines; the token is redacted from `Config` reprs and error text.

If you find a path where a secret could leak, that is in scope.

## Versioning & releases

Semantic Versioning. Breaking changes bump MAJOR and are described in
[`UPGRADING.md`](UPGRADING.md); all changes are logged in
[`CHANGELOG.md`](CHANGELOG.md).
