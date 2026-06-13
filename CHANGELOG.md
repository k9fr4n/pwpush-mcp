# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- **HTTP transport migrated to Streamable HTTP** (MCP spec revision 2025-03-26+),
  exposed on a single `/mcp` endpoint. This replaces the deprecated HTTP+SSE
  transport (`/sse` + `/messages/`). **Breaking for HTTP clients only**: update
  the endpoint URL from `/sse` to `/mcp`. `stdio` mode (Claude Desktop / Claude
  Code / Docker MCP Gateway) and the tool surface are unchanged. `MCP_HTTP_TOKEN`,
  `MCP_HTTP_ALLOW_UNAUTHENTICATED` and `MCP_HTTP_ALLOWED_HOSTS` behave as before.

### Added

- **Multi-tenant mode** (`PWPUSH_PER_REQUEST_CREDENTIALS=true`, HTTP only): each
  client may send its own pwpush credentials via the `X-Pwpush-Token` /
  `X-Pwpush-Email` headers, and the server builds a per-request, per-tenant
  client from them. The credentials ride the transport — never a tool argument —
  so they are never exposed to the language model, and the header is added to the
  audit scrubber. Only credentials are per-request: `base_url`, `read_only`,
  `enabled_tools` and `file_root` stay operator-controlled, so a tenant can
  neither redirect the instance nor widen its permissions. Requests without the
  header fall back to the env token, so a pure multi-tenant server can run with
  no `PWPUSH_API_TOKEN` at all. Defaults to off (single-tenant, unchanged).

## [0.4.0] - 2026-06-10

Adds MCP prompts for the push lifecycle. `stdio` mode and all existing tools are
unaffected.

### Added

- **MCP prompts** for the push lifecycle: `create_push`, `preview_push`, and
  `expire_push`. These are user-controlled templates (slash-command style) that
  render a message guiding the assistant to call the matching tool — they never
  touch the API themselves. Prompts honour `PWPUSH_READ_ONLY` and
  `PWPUSH_ENABLED_TOOLS`: a prompt is advertised only when its underlying tool
  is, and the `expire_push` prompt asks for explicit confirmation first.

## [0.3.0] - 2026-06-06

A security-hardening release. **Note the behavioural changes**: file pushes are
now disabled unless `PWPUSH_FILE_ROOT` is set, and `--listen` requires
`MCP_HTTP_TOKEN` and binds loopback by default. `stdio` mode is unaffected.

### Security

- **HTTP transport hardened** ([#10](https://github.com/k9fr4n/pwpush-mcp/issues/10)):
  `--listen` now binds `127.0.0.1` by default (was `0.0.0.0`), **requires a
  bearer token** via `MCP_HTTP_TOKEN` on `/sse` and `/messages/` (refuses to
  start otherwise, override with `MCP_HTTP_ALLOW_UNAUTHENTICATED=true`), and
  validates the `Host` header (`MCP_HTTP_ALLOWED_HOSTS`) to block DNS-rebinding.
  `stdio` mode is unaffected.
- **File pushes gated by an allowlist** ([#11](https://github.com/k9fr4n/pwpush-mcp/issues/11)):
  `create_push(file_paths=…)` previously opened any local path, allowing
  arbitrary file read/exfiltration. File uploads are now **disabled unless
  `PWPUSH_FILE_ROOT` is set**, and every path is `~`-expanded and symlink-resolved
  before a containment check against that root, rejecting `../` traversal and
  symlink escapes.
- **Audit log no longer leaks `name`/`note`** ([#12](https://github.com/k9fr4n/pwpush-mcp/issues/12)):
  both fields (`note` is creator-private) are redacted from the audit `args`,
  and `name` is emitted as a short `sha256` digest in the audit `target` rather
  than verbatim.
- **Compose runtime hardening** ([#13](https://github.com/k9fr4n/pwpush-mcp/issues/13)):
  `read_only`, `cap_drop: [ALL]`, `no-new-privileges`, a `/tmp` tmpfs, and the
  published port bound to `127.0.0.1` only.

### Fixed

- **v1 `create_push` dropped `name`/`note`** ([#8](https://github.com/k9fr4n/pwpush-mcp/issues/8)):
  on legacy (v1) instances the `name` and `note` parameters were accepted but
  never sent to the API, so pushes came back with empty values. Both are now
  forwarded into the v1 password/url/file request body. Instances predating the
  `name`/`note` columns ignore the extra params, preserving prior behaviour.

### Changed

- The `kind` tool description now notes that `qr` is created as a text push on
  v1 (legacy) instances, which expose no distinct QR endpoint.

## [0.2.0] - 2026-06-05

First packaged, distributable release. The server moves to the low-level MCP
SDK, gains an HTTP transport, security/multi-tenant knobs, and a full
distribution + governance setup inspired by
[thruk-mcp](https://github.com/k9fr4n/thruk-mcp).

### Added

- **HTTP transport**: `pwpush-mcp --listen PORT` exposes the server over
  Streamable-HTTP/SSE (Starlette + uvicorn). `--host` / `--log-level` flags.
  stdio remains the default.
- **Docker image**: multi-stage `Dockerfile` (non-root user, wheel build) and
  `compose.yml`. Published to `ghcr.io/k9fr4n/pwpush-mcp` on each `vX.Y.Z` tag.
- **Docker MCP Gateway**: `catalog/server.yaml` + generated `catalog/metadata.json`
  and the `io.docker.server.metadata` OCI label so the gateway forwards tool
  arguments correctly. `scripts/gen_metadata.py` regenerates the catalog.
- **Release automation**: `release.yml` builds multi-arch (amd64/arm64) images
  with SBOM + provenance, creates the GitHub Release, and publishes to PyPI via
  OIDC trusted publishing. `pypi.yml` is a manual fallback. `dependabot.yml`
  keeps Actions (SHA-pinned) and Python deps current.
- **Security / multi-tenant knobs**:
  - `PWPUSH_READ_ONLY=true` removes write tools (`create_push`, `expire_push`).
  - `PWPUSH_ENABLED_TOOLS=list_*,get_version` restricts the exposed tool surface
    via fnmatch globs.
  - `PWPUSH_AUDIT_LOG=true` (default) emits one JSON line per write-tool
    invocation on the `pwpush_mcp.audit` logger; secrets are redacted.
- **Reliability knobs**: `PWPUSH_MAX_CONCURRENT` (concurrency cap),
  `PWPUSH_MAX_RETRIES` (transport retries + 429/5xx backoff honouring
  `Retry-After`), `PWPUSH_TIMEOUT`.
- **Governance**: `CONTRIBUTING.md`, `SUPPORT.md`, `UPGRADING.md`,
  `.pre-commit-config.yaml`, this `CHANGELOG.md`.
- New tests for config knobs, tool filtering, audit logging, retries/concurrency,
  catalog drift, and dependency bounds.

### Changed

- **Server rewritten on the low-level MCP SDK** (`mcp.server.Server`) instead of
  FastMCP, with explicit `inputSchema` per tool. Dependency `fastmcp` replaced by
  `mcp[cli]` (+ `uvicorn`, `starlette`).
- `Config.__repr__` / `__str__` now redact the API token unconditionally.
- CI gained `ruff format --check`, `mypy src`, a 80% coverage gate, a catalog
  drift check, and a Docker build job; Actions are pinned to commit SHAs.
- Dependency upper bounds added for `mcp` (`<2.0`) and `httpx` (`<1.0`).

[Unreleased]: https://github.com/k9fr4n/pwpush-mcp/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/k9fr4n/pwpush-mcp/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/k9fr4n/pwpush-mcp/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/k9fr4n/pwpush-mcp/releases/tag/v0.2.0
