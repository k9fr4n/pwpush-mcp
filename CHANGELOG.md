# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/k9fr4n/pwpush-mcp/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/k9fr4n/pwpush-mcp/releases/tag/v0.2.0
