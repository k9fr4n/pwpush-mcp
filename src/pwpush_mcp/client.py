"""Thin async wrapper around the Password Pusher API v2.

Design notes:
- The secret ``payload`` and ``files`` are never logged and are stripped from
  any object this client returns to callers, so a push secret can never leak
  back through the MCP layer.
- This client deliberately exposes no "retrieve" operation: retrieving a push
  consumes a view irreversibly, which is unsafe to perform from an agent.
"""

from __future__ import annotations

from typing import Any

import httpx

from . import __version__
from .config import Config

# API fields that must never be returned to the model.
_SENSITIVE_FIELDS = ("payload", "files")

# Push kinds the server can create. File pushes require multipart uploads and
# are intentionally not supported in this version.
SUPPORTED_KINDS = ("text", "url", "qr")


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


class PwpushClient:
    def __init__(self, config: Config, *, timeout: float = 30.0) -> None:
        self._config = config
        self._timeout = timeout

    def _headers(self, *, auth: bool) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "User-Agent": f"pwpush-mcp/{__version__}",
        }
        if auth:
            if not self._config.api_token:
                raise PwpushError(
                    "This operation requires authentication, but PWPUSH_API_TOKEN "
                    "is not set. Generate a token at "
                    f"{self._config.base_url}/api_tokens and set the env var."
                )
            headers["Authorization"] = f"Bearer {self._config.api_token}"
        return headers

    async def _request(
        self,
        method: str,
        path: str,
        *,
        auth: bool,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        url = f"{self._config.base_url}/api/v2{path}"
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.request(
                    method,
                    url,
                    headers=self._headers(auth=auth),
                    json=json,
                    params=params,
                )
        except httpx.RequestError as exc:
            raise PwpushError(
                f"network error contacting {self._config.base_url}: {exc}"
            ) from exc

        if resp.status_code == 429:
            retry = resp.headers.get("Retry-After", "unknown")
            raise PwpushError(f"rate limited (429); retry after {retry}s")
        if resp.status_code == 401:
            raise PwpushError("unauthorized (401): check that PWPUSH_API_TOKEN is valid")
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

    async def create_push(self, push: dict[str, Any]) -> dict[str, Any]:
        data = await self._request("POST", "/pushes", auth=True, json={"push": push})
        return _public(data)

    async def preview_push(self, url_token: str) -> dict[str, Any]:
        # Preview returns only the secret URL and never consumes a view.
        return await self._request("GET", f"/pushes/{url_token}/preview", auth=False)

    async def expire_push(self, url_token: str) -> dict[str, Any]:
        data = await self._request("DELETE", f"/pushes/{url_token}", auth=True)
        return _public(data)

    async def push_audit(self, url_token: str, *, page: int = 1) -> Any:
        return await self._request(
            "GET", f"/pushes/{url_token}/audit", auth=True, params={"page": page}
        )

    async def list_pushes(self, state: str, *, page: int = 1) -> Any:
        if state not in ("active", "expired"):
            raise PwpushError("state must be 'active' or 'expired'")
        data = await self._request("GET", f"/pushes/{state}", auth=True, params={"page": page})
        return _public(data)

    async def version(self) -> dict[str, Any]:
        return await self._request("GET", "/version", auth=False)
