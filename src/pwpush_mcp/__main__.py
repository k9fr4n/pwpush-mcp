"""Entry point: ``python -m pwpush_mcp`` or the ``pwpush-mcp`` console script.

Default transport is stdio (Claude Desktop / Claude Code / Docker MCP Gateway).
Pass ``--listen PORT`` to expose the server over Streamable HTTP (single
``/mcp`` endpoint, MCP spec revision 2025-03-26+) behind a network gateway. The
legacy HTTP+SSE transport (``/sse`` + ``/messages/``) it replaced is deprecated.
"""

from __future__ import annotations

import argparse
import asyncio
import hmac
import logging
import sys
from typing import Any

from .config import Config, _env_bool, _raw_env, _split_csv
from .server import build_server

log = logging.getLogger("pwpush_mcp")

_SSL_WARNING = (
    "SECURITY WARNING: PWPUSH_VERIFY_SSL=false — TLS certificate verification is "
    "DISABLED. All HTTPS connections are vulnerable to MITM attacks. Set "
    "PWPUSH_VERIFY_SSL=true (or PWPUSH_CA_BUNDLE) for production use."
)

_UNAUTH_WARNING = (
    "SECURITY WARNING: HTTP transport is running WITHOUT authentication "
    "(MCP_HTTP_ALLOW_UNAUTHENTICATED=true). The server holds PWPUSH_API_TOKEN — "
    "ensure a TLS + auth reverse proxy sits in front and the port is not exposed."
)

_PER_REQUEST_WARNING = (
    "Multi-tenant mode is ON (PWPUSH_PER_REQUEST_CREDENTIALS=true): clients may "
    "send their own pwpush credentials via the X-Pwpush-Token / X-Pwpush-Email "
    "headers. These travel in clear text — serve ONLY behind TLS. The header "
    "values are never logged."
)


class _BearerAuthMiddleware:
    """Pure-ASGI bearer-token gate for the HTTP transport.

    Implemented as raw ASGI (not BaseHTTPMiddleware) so it does not buffer or
    break the SSE streaming response. When ``token`` is None the gate is a
    pass-through (unauthenticated mode, guarded by an explicit opt-in upstream).
    """

    def __init__(self, app: Any, *, token: str | None) -> None:
        self.app = app
        self._expected = b"Bearer " + token.encode() if token else None

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if self._expected is None or scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        provided = dict(scope.get("headers") or []).get(b"authorization", b"")
        if not hmac.compare_digest(provided, self._expected):
            await send(
                {
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [
                        (b"content-type", b"text/plain; charset=utf-8"),
                        (b"www-authenticate", b"Bearer"),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": b"401 Unauthorized"})
            return
        await self.app(scope, receive, send)


async def _run_stdio() -> None:
    from mcp.server.stdio import stdio_server

    server = build_server()
    if not server._cfg.verify_ssl:
        log.warning(_SSL_WARNING)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


async def _run_http(
    host: str,
    port: int,
    log_level: str,
    *,
    token: str | None,
    allowed_hosts: tuple[str, ...],
) -> None:
    """Run as a Streamable HTTP server on a single ``/mcp`` endpoint.

    The endpoint is guarded by a bearer-token gate (``token``) and a TrustedHost
    check (``allowed_hosts``) that blocks DNS-rebinding. Both are wired by
    :func:`main`, which fails closed when no token is configured. When the
    server runs in multi-tenant mode (``PWPUSH_PER_REQUEST_CREDENTIALS=true``),
    each request's own credentials are read from its headers in the tool
    handler — see :meth:`PwpushMCPServer._client_for_request`.
    """
    import contextlib
    from collections.abc import AsyncIterator

    import uvicorn
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
    from starlette.applications import Starlette
    from starlette.middleware import Middleware
    from starlette.middleware.trustedhost import TrustedHostMiddleware
    from starlette.routing import Mount

    server = build_server()
    if not server._cfg.verify_ssl:
        log.warning(_SSL_WARNING)
    if token is None:
        log.warning(_UNAUTH_WARNING)
    if server._cfg.per_request_credentials:
        log.warning(_PER_REQUEST_WARNING)

    # stateless=True: no server-side session affinity, so any node can serve any
    # request — the natural fit for a multi-tenant deployment where each request
    # carries its own credentials. Request headers are attached per message in
    # both stateful and stateless modes, so credential resolution is unaffected.
    session_manager = StreamableHTTPSessionManager(app=server, json_response=False, stateless=True)

    async def handle_mcp(scope: Any, receive: Any, send: Any) -> None:
        await session_manager.handle_request(scope, receive, send)

    @contextlib.asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[None]:
        # The session manager's task group must wrap the whole server lifetime.
        async with session_manager.run():
            yield

    app = Starlette(
        routes=[Mount("/mcp", app=handle_mcp)],
        # Outermost first: reject untrusted Host headers before auth runs.
        middleware=[
            Middleware(TrustedHostMiddleware, allowed_hosts=list(allowed_hosts)),
            Middleware(_BearerAuthMiddleware, token=token),
        ],
        lifespan=lifespan,
    )
    config = uvicorn.Config(app, host=host, port=port, log_level=log_level.lower())
    await uvicorn.Server(config).serve()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pwpush-mcp", description="Password Pusher MCP server.")
    parser.add_argument(
        "--listen",
        type=int,
        metavar="PORT",
        help="Run as a Streamable HTTP server (/mcp) on this port. Default: stdio mode.",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Bind host for --listen mode. Defaults to loopback; the transport "
        "has no TLS, so only bind a public interface behind a TLS+auth proxy.",
    )
    parser.add_argument(
        "--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"]
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=args.log_level,
        stream=sys.stderr,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    # Fail fast on a missing base URL / malformed config before opening transport.
    Config.from_env()

    if args.listen:
        # Fail closed: --listen exposes account-scoped, token-bearing tools over
        # the network. Require a bearer token unless the operator explicitly
        # opts out (e.g. when fronting the server with their own auth proxy).
        token = _raw_env("MCP_HTTP_TOKEN")
        if token is None and not _env_bool("MCP_HTTP_ALLOW_UNAUTHENTICATED", False):
            parser.error(
                "--listen requires MCP_HTTP_TOKEN to be set (clients must send "
                "'Authorization: Bearer <token>'). To run unauthenticated behind "
                "your own auth proxy, set MCP_HTTP_ALLOW_UNAUTHENTICATED=true."
            )
        # TrustedHost allowlist guards against DNS-rebinding. Defaults to
        # loopback names; override via MCP_HTTP_ALLOWED_HOSTS (CSV, '*' to allow
        # any) when terminating a real hostname at a reverse proxy.
        allowed_hosts = _split_csv(_raw_env("MCP_HTTP_ALLOWED_HOSTS"))
        if not allowed_hosts:
            allowed_hosts = ("localhost", "127.0.0.1", "[::1]")
            if args.host not in ("0.0.0.0", "::"):
                allowed_hosts = (*allowed_hosts, args.host)
        asyncio.run(
            _run_http(
                args.host,
                args.listen,
                args.log_level,
                token=token,
                allowed_hosts=allowed_hosts,
            )
        )
    else:
        asyncio.run(_run_stdio())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
