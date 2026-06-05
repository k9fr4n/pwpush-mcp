# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS build
WORKDIR /src
RUN pip install --no-cache-dir build
COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m build --wheel --outdir /dist

FROM python:3.12-slim
RUN useradd -r -u 1001 -m pwpush
WORKDIR /app
COPY --from=build /dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl && rm -f /tmp/*.whl

# Embed the Docker MCP Gateway catalog metadata so that self-configured
# deployments (docker:// references) expose correct tool argument schemas.
# Without this label the gateway uses empty schemas and strips all arguments
# before forwarding tool calls, causing "Field required" errors at runtime.
# The value is produced by scripts/gen_metadata.py and injected at build time:
#   --build-arg SERVER_METADATA="$(python scripts/gen_metadata.py)"
ARG SERVER_METADATA="{}"
LABEL io.docker.server.metadata="$SERVER_METADATA"

USER pwpush
ENV PYTHONUNBUFFERED=1
# Default = stdio transport (Docker MCP Gateway / Claude Desktop / Claude Code).
# For HTTP/Streamable-HTTP, override CMD: ["--listen", "8000"]
EXPOSE 8000
ENTRYPOINT ["pwpush-mcp"]
CMD []
