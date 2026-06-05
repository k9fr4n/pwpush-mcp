# pwpush-mcp — Docker MCP catalog

This directory holds the [Docker MCP Gateway](https://docs.docker.com/ai/mcp-gateway/)
catalog entry for **pwpush-mcp**.

| File | Purpose |
|------|---------|
| `server.yaml` | Catalog entry (image, secrets, env, description) for `docker mcp catalog add`. |
| `metadata.json` | Tool schemas baked into the image as the `io.docker.server.metadata` OCI label. **Generated** — do not edit by hand. |

## Why `metadata.json` matters

When the gateway spawns a `docker://` server it reads the tool list (names,
descriptions, argument schemas) from the `io.docker.server.metadata` label. If
that label is missing or stale, the gateway forwards calls with **empty schemas**
and strips every argument — clients then see `Tool not found` or `Field required`
errors even though the tool is implemented.

`metadata.json` is the source of truth for that label and is injected at build
time (see `Dockerfile` / `release.yml`).

## Regenerating after a tool change

```bash
python scripts/gen_metadata.py >/dev/null   # rewrites catalog/metadata.json
git add catalog/metadata.json
```

CI fails on drift between `TOOL_REGISTRY` and `metadata.json`
(see `tests/test_catalog_metadata.py`).

## Local install

```bash
docker mcp catalog create pwpush-private
docker mcp catalog add  pwpush-private pwpush-mcp ./catalog/server.yaml
docker mcp server  enable pwpush-mcp
docker mcp gateway run    --catalog pwpush-private
```
