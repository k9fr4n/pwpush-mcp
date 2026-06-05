"""MCP server definition: Password Pusher "push" operations.

Uses the **low-level MCP SDK** (``mcp.server.Server``) rather than FastMCP.

Rationale: the Docker MCP Gateway strips arguments from tool calls when the
schemas it receives are empty. Defining ``inputSchema`` explicitly (no
annotation introspection) and receiving ``arguments`` as a raw ``dict`` in the
``call_tool`` handler keeps the server compatible with the gateway's stdio
transport without any catalog-label gymnastics.

Exposed tools (Pushes scope only):
    create_push, preview_push, expire_push, get_push_audit,
    list_active_pushes, list_expired_pushes, get_version

Deliberately NOT exposed:
    Retrieving a push payload. A retrieval consumes a view irreversibly, so it
    must remain a human action performed via the secret URL — never something
    an agent triggers. ``preview_push`` returns the URL without consuming a view.
"""

from __future__ import annotations

import fnmatch
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from mcp.server import Server
from mcp.types import TextContent, Tool, ToolAnnotations

from . import audit
from .client import PwpushClient, PwpushError
from .config import Config
from .durations import DEFAULT_LABEL, INDEX_TO_LABEL

__all__ = ["TOOL_REGISTRY", "WRITE_TOOLS", "PwpushMCPServer", "build_server"]

log = logging.getLogger("pwpush_mcp.server")

_DURATION_HELP = (
    "Time before the push expires. Accepts a label "
    "(" + ", ".join(INDEX_TO_LABEL[i] for i in range(18)) + ") "
    "or the raw enum index 0..17."
)

_PAGE_PROP = {
    "type": "integer",
    "minimum": 1,
    "maximum": 200,
    "default": 1,
    "description": "Page number (50 per page).",
}

_URL_TOKEN_PROP = {"type": "string", "description": "The url_token of the push."}


# ---------------------------------------------------------------------------
# Tool handlers — each takes (client, arguments) and returns a JSON-able object.
# Defaults are applied here because JSON-schema validation does not fill them.
# ---------------------------------------------------------------------------


async def _create_push(client: PwpushClient, args: dict[str, Any]) -> Any:
    payload = args.get("payload")
    file_paths = args.get("file_paths")
    kind = args.get("kind", "text")
    if not payload and not file_paths:
        raise PwpushError("provide a payload, file_paths, or both")
    if not file_paths and kind not in ("text", "url", "qr"):
        raise PwpushError("kind must be 'text', 'url', or 'qr' (use file_paths for file pushes)")
    return await client.create_push(
        payload=payload,
        kind=kind,
        duration=args.get("duration", DEFAULT_LABEL),
        expire_after_views=args.get("expire_after_views", 1),
        passphrase=args.get("passphrase"),
        name=args.get("name"),
        note=args.get("note"),
        deletable_by_viewer=args.get("deletable_by_viewer", False),
        retrieval_step=args.get("retrieval_step", True),
        file_paths=file_paths,
    )


async def _preview_push(client: PwpushClient, args: dict[str, Any]) -> Any:
    return await client.preview_push(args["url_token"])


async def _expire_push(client: PwpushClient, args: dict[str, Any]) -> Any:
    return await client.expire_push(args["url_token"])


async def _get_push_audit(client: PwpushClient, args: dict[str, Any]) -> Any:
    return await client.push_audit(args["url_token"], page=args.get("page", 1))


async def _list_active(client: PwpushClient, args: dict[str, Any]) -> Any:
    return await client.list_pushes("active", page=args.get("page", 1))


async def _list_expired(client: PwpushClient, args: dict[str, Any]) -> Any:
    return await client.list_pushes("expired", page=args.get("page", 1))


async def _get_version(client: PwpushClient, args: dict[str, Any]) -> Any:
    return await client.version()


# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolSpec:
    name: str
    title: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[[PwpushClient, dict[str, Any]], Awaitable[Any]]
    is_write: bool = False
    destructive: bool = False

    def to_tool(self) -> Tool:
        return Tool(
            name=self.name,
            description=self.description,
            inputSchema=self.input_schema,
            annotations=ToolAnnotations(
                title=self.title,
                readOnlyHint=not self.is_write,
                destructiveHint=self.destructive,
            ),
        )


TOOL_REGISTRY: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="create_push",
        title="Create push",
        description=(
            "Create a Password Pusher secret link and return its sharing URL. "
            "The secret payload is NOT echoed back. Share the returned `html_url` "
            "with the recipient. A token is sent if PWPUSH_API_TOKEN is set; some "
            "instances also allow anonymous push creation. Pass `file_paths` to "
            "attach one or more local files (a file push). For a text/url/qr push, "
            "set `payload` and `kind`."
        ),
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "payload": {
                    "type": ["string", "null"],
                    "default": None,
                    "description": (
                        "The secret to push (text, a URL, or QR content). "
                        "Optional when file_paths are given."
                    ),
                },
                "kind": {
                    "type": "string",
                    "default": "text",
                    "description": (
                        "Push type: 'text', 'url', or 'qr'. Ignored when "
                        "file_paths are given (forced to 'file')."
                    ),
                },
                "file_paths": {
                    "type": ["array", "null"],
                    "items": {"type": "string"},
                    "default": None,
                    "description": (
                        "Local file path(s) to attach as a file push (multipart upload)."
                    ),
                },
                "duration": {
                    "type": "string",
                    "default": DEFAULT_LABEL,
                    "description": _DURATION_HELP,
                },
                "expire_after_views": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                    "default": 1,
                    "description": "Number of views before expiry (1-100).",
                },
                "passphrase": {
                    "type": ["string", "null"],
                    "default": None,
                    "description": "Optional passphrase required to view the secret.",
                },
                "name": {
                    "type": ["string", "null"],
                    "default": None,
                    "description": "Optional name for the push.",
                },
                "note": {
                    "type": ["string", "null"],
                    "default": None,
                    "description": "Optional private note, visible only to the creator.",
                },
                "deletable_by_viewer": {
                    "type": "boolean",
                    "default": False,
                    "description": "Allow the recipient to delete the push.",
                },
                "retrieval_step": {
                    "type": "boolean",
                    "default": True,
                    "description": "Require an extra click before the secret is revealed.",
                },
            },
        },
        handler=_create_push,
        is_write=True,
        destructive=False,
    ),
    ToolSpec(
        name="preview_push",
        title="Preview push URL",
        description="Return the shareable secret URL for a push WITHOUT consuming a view.",
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["url_token"],
            "properties": {
                "url_token": {"type": "string", "description": "The url_token of an existing push."}
            },
        },
        handler=_preview_push,
        is_write=False,
    ),
    ToolSpec(
        name="expire_push",
        title="Expire push",
        description=(
            "Permanently expire (delete) a push. IRREVERSIBLE. This destroys the "
            "payload and any attached files for good. Requires PWPUSH_API_TOKEN "
            "(or a push created with deletable_by_viewer)."
        ),
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["url_token"],
            "properties": {
                "url_token": {
                    "type": "string",
                    "description": "The url_token of the push to expire.",
                }
            },
        },
        handler=_expire_push,
        is_write=True,
        destructive=True,
    ),
    ToolSpec(
        name="get_push_audit",
        title="Push audit log",
        description="Return the audit log (views, IPs, user agents) for a push. Requires auth.",
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["url_token"],
            "properties": {"url_token": _URL_TOKEN_PROP, "page": _PAGE_PROP},
        },
        handler=_get_push_audit,
        is_write=False,
    ),
    ToolSpec(
        name="list_active_pushes",
        title="List active pushes",
        description="List the authenticated account's active (not yet expired) pushes.",
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {"page": _PAGE_PROP},
        },
        handler=_list_active,
        is_write=False,
    ),
    ToolSpec(
        name="list_expired_pushes",
        title="List expired pushes",
        description="List the authenticated account's expired pushes.",
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {"page": _PAGE_PROP},
        },
        handler=_list_expired,
        is_write=False,
    ),
    ToolSpec(
        name="get_version",
        title="Get instance version",
        description="Return the target instance's version and enabled feature flags (no auth).",
        input_schema={"type": "object", "additionalProperties": False, "properties": {}},
        handler=_get_version,
        is_write=False,
    ),
)

# Tools that mutate state — used by read_only mode and the audit log.
WRITE_TOOLS: frozenset[str] = frozenset(spec.name for spec in TOOL_REGISTRY if spec.is_write)


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------


class PwpushMCPServer(Server):
    """Low-level MCP server carrying its config and a shared client."""

    def __init__(self, cfg: Config, enabled: dict[str, ToolSpec]) -> None:
        super().__init__(name="pwpush")
        self._cfg = cfg
        self._enabled = enabled
        self._client = PwpushClient(cfg)
        self._register_handlers()

    def _register_handlers(self) -> None:
        specs = self._enabled
        cfg = self._cfg
        client = self._client

        @self.list_tools()
        async def _list_tools() -> list[Tool]:
            return [spec.to_tool() for spec in specs.values()]

        @self.call_tool()
        async def _call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
            spec = specs.get(name)
            if spec is None:
                return _error(f"unknown or disabled tool: {name}")
            # Defense in depth: write tools are already filtered out of `specs`
            # under read_only, but enforce explicitly in case of misconfiguration.
            if cfg.read_only and spec.is_write:
                return _error(f"tool '{name}' is disabled (server is read-only)")
            try:
                result = await spec.handler(client, arguments)
            except PwpushError as exc:
                if cfg.audit_log and spec.is_write:
                    audit.log_call(name, arguments, status="error", error=str(exc))
                return _error(str(exc))
            except Exception as exc:  # never leak a raw traceback to the client
                if cfg.audit_log and spec.is_write:
                    audit.log_call(name, arguments, status="error", error=repr(exc))
                return _error(f"unexpected error: {type(exc).__name__}")
            if cfg.audit_log and spec.is_write:
                audit.log_call(name, arguments, status="ok")
            return [TextContent(type="text", text=json.dumps(result, default=str))]


def _error(message: str) -> list[TextContent]:
    return [TextContent(type="text", text=audit.scrub(f"Error: {message}"))]


def _resolve_enabled(cfg: Config) -> dict[str, ToolSpec]:
    """Apply read_only + enabled_tools filtering to the tool registry."""
    enabled: dict[str, ToolSpec] = {}
    for spec in TOOL_REGISTRY:
        if cfg.read_only and spec.name in WRITE_TOOLS:
            continue
        if cfg.enabled_tools and not any(
            fnmatch.fnmatch(spec.name, pat) for pat in cfg.enabled_tools
        ):
            continue
        enabled[spec.name] = spec
    return enabled


def build_server(cfg: Config | None = None) -> PwpushMCPServer:
    """Build the MCP server with the enabled tools registered."""
    cfg = cfg or Config.from_env()
    audit.configure(enabled=cfg.audit_log)
    enabled = _resolve_enabled(cfg)
    log.debug("pwpush-mcp: %d tool(s) enabled: %s", len(enabled), sorted(enabled))
    return PwpushMCPServer(cfg, enabled)
