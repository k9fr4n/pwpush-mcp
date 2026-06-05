"""FastMCP server exposing Password Pusher's "push" operations.

Exposed tools (Pushes scope only):
    create_push, preview_push, expire_push, get_push_audit,
    list_active_pushes, list_expired_pushes, get_version

Deliberately NOT exposed:
    Retrieving a push payload. A retrieval consumes a view irreversibly, so it
    must remain a human action performed via the secret URL — never something
    an agent triggers. ``preview_push`` returns the URL without consuming a view.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field

from .client import SUPPORTED_KINDS, PwpushClient, PwpushError
from .config import Config
from .durations import DEFAULT_LABEL, INDEX_TO_LABEL, resolve_duration

mcp = FastMCP(
    name="pwpush",
    instructions=(
        "Create and manage Password Pusher secret links (pushes). Share the "
        "returned secret URL with the recipient; the secret itself is never "
        "read back through this server. Expiring a push is irreversible."
    ),
)

_client: PwpushClient | None = None


def _get_client() -> PwpushClient:
    global _client
    if _client is None:
        _client = PwpushClient(Config.from_env())
    return _client


_DURATION_HELP = (
    "Time before the push expires. Accepts a label "
    "(" + ", ".join(INDEX_TO_LABEL[i] for i in range(18)) + ") "
    "or the raw enum index 0..17."
)


@mcp.tool(
    annotations={"title": "Create push", "readOnlyHint": False, "destructiveHint": False},
)
async def create_push(
    payload: Annotated[str, Field(description="The secret to push (text, a URL, or QR content).")],
    kind: Annotated[
        str,
        Field(description=f"Push type, one of {SUPPORTED_KINDS}. Default 'text'."),
    ] = "text",
    duration: Annotated[str, Field(description=_DURATION_HELP)] = DEFAULT_LABEL,
    expire_after_views: Annotated[
        int, Field(ge=1, le=100, description="Number of views before expiry (1-100).")
    ] = 5,
    passphrase: Annotated[
        str | None, Field(description="Optional passphrase required to view the secret.")
    ] = None,
    name: Annotated[str | None, Field(description="Optional name for the push.")] = None,
    note: Annotated[
        str | None, Field(description="Optional private note, visible only to the creator.")
    ] = None,
    deletable_by_viewer: Annotated[
        bool, Field(description="Allow the recipient to delete the push.")
    ] = False,
    retrieval_step: Annotated[
        bool, Field(description="Require an extra click before the secret is revealed.")
    ] = True,
) -> dict[str, Any]:
    """Create a Password Pusher secret link and return its sharing URL.

    The secret payload is NOT echoed back. Share the returned `html_url` with
    the recipient. Requires PWPUSH_API_TOKEN.
    """
    if kind not in SUPPORTED_KINDS:
        raise PwpushError(f"kind must be one of {SUPPORTED_KINDS}; file pushes are not supported")

    push: dict[str, Any] = {
        "payload": payload,
        "kind": kind,
        "expire_after_duration": resolve_duration(duration),
        "expire_after_views": expire_after_views,
        "deletable_by_viewer": deletable_by_viewer,
        "retrieval_step": retrieval_step,
    }
    if passphrase:
        push["passphrase"] = passphrase
    if name:
        push["name"] = name
    if note:
        push["note"] = note

    return await _get_client().create_push(push)


@mcp.tool(
    annotations={"title": "Preview push URL", "readOnlyHint": True, "destructiveHint": False},
)
async def preview_push(
    url_token: Annotated[str, Field(description="The url_token of an existing push.")],
) -> dict[str, Any]:
    """Return the shareable secret URL for a push WITHOUT consuming a view."""
    return await _get_client().preview_push(url_token)


@mcp.tool(
    annotations={"title": "Expire push", "readOnlyHint": False, "destructiveHint": True},
)
async def expire_push(
    url_token: Annotated[str, Field(description="The url_token of the push to expire.")],
) -> dict[str, Any]:
    """Permanently expire (delete) a push. IRREVERSIBLE.

    This destroys the payload and any attached files for good. Requires
    PWPUSH_API_TOKEN (or a push created with deletable_by_viewer).
    """
    return await _get_client().expire_push(url_token)


@mcp.tool(
    annotations={"title": "Push audit log", "readOnlyHint": True, "destructiveHint": False},
)
async def get_push_audit(
    url_token: Annotated[str, Field(description="The url_token of the push.")],
    page: Annotated[int, Field(ge=1, le=200, description="Page number (50 per page).")] = 1,
) -> Any:
    """Return the audit log (views, IPs, user agents) for a push. Requires auth."""
    return await _get_client().push_audit(url_token, page=page)


@mcp.tool(
    annotations={"title": "List active pushes", "readOnlyHint": True, "destructiveHint": False},
)
async def list_active_pushes(
    page: Annotated[int, Field(ge=1, le=200, description="Page number (50 per page).")] = 1,
) -> Any:
    """List the authenticated account's active (not yet expired) pushes."""
    return await _get_client().list_pushes("active", page=page)


@mcp.tool(
    annotations={"title": "List expired pushes", "readOnlyHint": True, "destructiveHint": False},
)
async def list_expired_pushes(
    page: Annotated[int, Field(ge=1, le=200, description="Page number (50 per page).")] = 1,
) -> Any:
    """List the authenticated account's expired pushes."""
    return await _get_client().list_pushes("expired", page=page)


@mcp.tool(
    annotations={"title": "Get instance version", "readOnlyHint": True, "destructiveHint": False},
)
async def get_version() -> dict[str, Any]:
    """Return the target instance's version and enabled feature flags (no auth)."""
    return await _get_client().version()
