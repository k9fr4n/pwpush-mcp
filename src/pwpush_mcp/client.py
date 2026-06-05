"""Thin async wrapper around the Password Pusher API v2.

Design notes:
- The secret ``payload`` and ``files`` are never logged and are stripped from
  any object this client returns to callers, so a push secret can never leak
  back through the MCP layer.
- This client deliberately exposes no "retrieve" operation: retrieving a push
  consumes a view irreversibly, which is unsafe to perform from an agent.
- Authentication is optional. The bearer token is sent whenever it is
  configured; an operation only fails up-front for a missing token when the
  endpoint is inherently account-scoped (listing, audit). Some instances allow
  anonymous push creation, expiry (for deletable pushes), and preview.
"""

from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any

import httpx

from . import __version__
from .config import Config

# API fields that must never be returned to the model.
_SENSITIVE_FIELDS = ("payload", "files")

# Push kinds. File pushes are handled via multipart uploads (see create_push).
SUPPORTED_KINDS = ("text", "url", "qr", "file")


class PwpushError(Exception):
    """Raised for any API, authentication, or network failure."""


def _public(obj: Any) -> Any:
    """Return a copy of an API object with sensitive fields removed."""
    if isinstance(obj, list):
        return [_public(item) for item in obj]
    if isinstance(obj, dict):
        return {k: v for k, v in obj.items() if k not in _SENSITIVE_FIELDS}
    return obj


def _safe_detail(resp: httpx.Response) -> str:
    """Extract a human-readable error message without echoing secrets."""
    try:
        data = resp.json()
    except ValueError:
        text = resp.text.strip()
        return text[:200] if text else f"HTTP {resp.status_code}"
    if isinstance(data, dict):
        for key in ("error", "message", "errors"):
            if key in data:
                return str(data[key])
    return f"HTTP {resp.status_code}"


def _form_value(value: Any) -> str:
    """Render a value for a multipart form field."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


class PwpushClient:
    def __init__(self, config: Config, *, timeout: float = 30.0) -> None:
        self._config = config
        self._timeout = timeout

    def _headers(self, *, require_auth: bool) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "User-Agent": f"pwpush-mcp/{__version__}",
        }
        if self._config.api_token:
            headers["Authorization"] = f"Bearer {self._config.api_token}"
        elif require_auth:
            raise PwpushError(
                "This operation requires authentication, but PWPUSH_API_TOKEN "
                "is not set. Generate a token at "
                f"{self._config.base_url}/api_tokens and set the env var."
            )
        return headers

    async def _request(
        self,
        method: str,
        path: str,
        *,
        require_auth: bool,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        files: list[tuple[str, Any]] | None = None,
    ) -> Any:
        url = f"{self._config.base_url}/api/v2{path}"
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.request(
                    method,
                    url,
                    headers=self._headers(require_auth=require_auth),
                    json=json,
                    params=params,
                    data=data,
                    files=files,
                )
        except httpx.RequestError as exc:
            raise PwpushError(
                f"network error contacting {self._config.base_url}: {exc}"
            ) from exc

        if resp.status_code == 429:
            retry = resp.headers.get("Retry-After", "unknown")
            raise PwpushError(f"rate limited (429); retry after {retry}s")
        if resp.status_code == 401:
            raise PwpushError(
                "unauthorized (401): this instance/operation requires a valid "
                "PWPUSH_API_TOKEN"
            )
        if resp.status_code == 403:
            raise PwpushError("forbidden (403): the token lacks permission for this action")
        if resp.status_code == 404:
            raise PwpushError("not found (404): unknown url_token, or the push has expired")
        if resp.status_code >= 400:
            raise PwpushError(f"API error {resp.status_code}: {_safe_detail(resp)}")

        if not resp.content:
            return {}
        try:
            return resp.json()
        except ValueError as exc:
            raise PwpushError("API returned a non-JSON response") from exc

    # -- Operations ---------------------------------------------------------

    async def create_push(
        self,
        push: dict[str, Any],
        *,
        file_paths: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a push. Uses multipart upload when file_paths are given."""
        if not file_paths:
            data = await self._request("POST", "/pushes", require_auth=False, json={"push": push})
            return _public(data)

        form: dict[str, Any] = {f"push[{k}]": _form_value(v) for k, v in push.items()}
        form["push[kind]"] = "file"
        files: list[tuple[str, Any]] = []
        handles: list[Any] = []
        try:
            for raw in file_paths:
                path = Path(raw).expanduser()
                if not path.is_file():
                    raise PwpushError(f"file not found: {raw}")
                handle = path.open("rb")
                handles.append(handle)
                ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
                files.append(("push[files][]", (path.name, handle, ctype)))
            data = await self._request(
                "POST", "/pushes", require_auth=False, data=form, files=files
            )
        finally:
            for handle in handles:
                handle.close()
        return _public(data)

    async def preview_push(self, url_token: str) -> dict[str, Any]:
        # Preview returns only the secret URL and never consumes a view.
        return await self._request("GET", f"/pushes/{url_token}/preview", require_auth=False)

    async def expire_push(self, url_token: str) -> dict[str, Any]:
        data = await self._request("DELETE", f"/pushes/{url_token}", require_auth=False)
        return _public(data)

    async def push_audit(self, url_token: str, *, page: int = 1) -> Any:
        return await self._request(
            "GET", f"/pushes/{url_token}/audit", require_auth=True, params={"page": page}
        )

    async def list_pushes(self, state: str, *, page: int = 1) -> Any:
        if state not in ("active", "expired"):
            raise PwpushError("state must be 'active' or 'expired'")
        data = await self._request(
            "GET", f"/pushes/{state}", require_auth=True, params={"page": page}
        )
        return _public(data)

    async def version(self) -> dict[str, Any]:
        return await self._request("GET", "/version", require_auth=False)
