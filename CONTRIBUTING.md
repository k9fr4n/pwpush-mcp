# Contributing to pwpush-mcp

Thanks for your interest! This is a small, focused MCP server — contributions
that keep it simple and secure are very welcome.

## Development setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pre-commit install        # optional but recommended
```

## Before opening a PR

Run the same checks CI runs:

```bash
ruff check src tests
ruff format --check src tests
mypy src
pytest -q --cov=pwpush_mcp --cov-fail-under=80
python scripts/gen_metadata.py >/dev/null   # if you touched the tool surface
```

`pre-commit run --all-files` runs the lint/format/type subset automatically.

## Design invariants (please preserve)

- **Never retrieve a push payload.** Retrieving consumes a view irreversibly; it
  must stay a human action via the secret URL. There is intentionally no
  `retrieve` tool.
- **The API token is never a tool argument.** It comes only from
  `PWPUSH_API_TOKEN` so the model can neither supply nor log it.
- **Secrets never reach logs.** `payload` / `passphrase` / file contents are
  stripped from returned objects (`client._public`) and from audit lines
  (`audit._redact` / `audit.scrub`). `Config.__repr__` redacts the token.

## Adding a tool

1. Add an async handler and a `ToolSpec` to `TOOL_REGISTRY` in
   `src/pwpush_mcp/server.py` (set `is_write` / `destructive` correctly).
2. Regenerate the catalog: `python scripts/gen_metadata.py >/dev/null` and commit
   `catalog/metadata.json` (CI fails on drift).
3. Add tests under `tests/`.

## Adding an env var

1. Add the field + parsing in `src/pwpush_mcp/config.py`.
2. Document it in `.env.example` and the README configuration table.
3. If it is operator-facing, add it to `catalog/server.yaml`.

## Commit / PR conventions

- Conventional-commit style prefixes (`feat:`, `fix:`, `chore:`, `docs:`, `ci:`).
- One logical change per PR; update `CHANGELOG.md` under `[Unreleased]`.

## Releasing (maintainers)

1. Move `[Unreleased]` notes to a new `[X.Y.Z]` section in `CHANGELOG.md`.
2. Bump `version` in `pyproject.toml` and `__version__` in
   `src/pwpush_mcp/__init__.py`.
3. Tag and push: `git tag vX.Y.Z && git push origin vX.Y.Z`.
4. `release.yml` builds/pushes the multi-arch image, creates the GitHub Release,
   and publishes to PyPI (OIDC). No manual token handling.
