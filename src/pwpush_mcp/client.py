"""Thin async wrapper around the Password Pusher API (v1 and v2).

Two API generations exist in the wild:

- **v2** (pwpush.com, eu.pwpush.com, recent self-hosted): JSON under
  ``/api/v2/pushes``, a ``push`` wrapper, ``expire_after_duration`` as an enum
  index 0..17, and ``Authorization: Bearer`` auth.
- **v1** (older self-hosted instances): the classic ``/p.json`` endpoints, a
  ``password`` wrapper, ``expire_after_days`` (whole days), and
  ``X-User-Token`` / ``X-User-Email`` auth.

The client auto-detects the generation (overridable via ``PWPUSH_API_VERSION``)
and presents a single normalized interface to the tools.

Design invariants (both versions):
- The secret ``payload``/``files`` are never logged and are stripped from any
  object returned to callers.
- No "retrieve" operation is exposed: retrieving a push consumes a view.
- Authentication is sent when configured; an operation only fails up-front for
  a missing token when the endpoint is inherently account-scoped (list, audit).
"""

from __future__ import annotations

import asyncio
import mimetypes
import random
from pathlib import Path
from typing import Any

import httpx

from . import __version__
from .config import Config
from .durations import resolve_days, resolve_duration

# API fields that must never be returned to the model.
_SENSITIVE_FIELDS = ("payload", "files")

SUPPORTED_KINDS = ("text", "url", "qr", "file")


class PwpushError(Exception):
    """Raised for any API, authentication, or network failure."""


class FeatureDisabledError(PwpushError):
    """Raised when an instance does not enable a requested push type."""


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
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _open_files(file_paths: list[str], field: str) -> tuple[list, list]:
    """Open local files for multipart upload. Caller must close the handles."""
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
            files.append((field, (path.name, handle, ctype)))
    except Exception:
        for handle in handles:
            handle.close()
        raise
    return files, handles


# Status codes worth retrying with backoff: rate limiting and transient
# upstream/server errors. 4xx other than 429 are caller errors — never retried.
_RETRYABLE_STATUS: frozenset[int] = frozenset({429, 500, 502, 503, 504})


class PwpushClient:
    def __init__(self, config: Config, *, timeout: float | None = None) -> None:
        self._config = config
        self._timeout = timeout if timeout is not None else config.timeout
        self._verify = config.verify
        self._max_retries = config.max_retries
        self._version: str | None = (
            config.api_version if config.api_version in ("v1", "v2") else None
        )
        # Lazily created on first use so it is bound to the running event loop.
        self._semaphore: asyncio.Semaphore | None = None

    def _limiter(self) -> asyncio.Semaphore | None:
        """Return the concurrency semaphore, creating it on first use.

        ``max_concurrent == 0`` means unlimited, so no semaphore is used.
        """
        if self._config.max_concurrent <= 0:
            return None
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self._config.max_concurrent)
        return self._semaphore

    def _new_client(self) -> httpx.AsyncClient:
        """Build an AsyncClient with transport-level connection retries.

        ``httpx`` retries only connection establishment errors here; HTTP-level
        retries (429 / 5xx) are handled explicitly in :meth:`_send` so we can
        honour ``Retry-After`` and apply jittered backoff.
        """
        transport = httpx.AsyncHTTPTransport(retries=self._max_retries)
        return httpx.AsyncClient(timeout=self._timeout, verify=self._verify, transport=transport)

    @staticmethod
    def _backoff_seconds(resp: httpx.Response, attempt: int) -> float:
        """Backoff delay: honour ``Retry-After`` on 429, else jittered expo."""
        if resp.status_code == 429:
            raw = resp.headers.get("Retry-After")
            if raw:
                try:
                    return min(float(raw), 30.0)
                except ValueError:
                    pass
        return min(2.0**attempt + random.random(), 30.0)

    # -- Version detection --------------------------------------------------

    async def _detect_version(self) -> str:
        if self._version:
            return self._version
        url = f"{self._config.base_url}/api/v2/version.json"
        try:
            async with self._new_client() as client:
                resp = await client.get(url, headers={"Accept": "application/json"})
        except httpx.RequestError as exc:
            raise PwpushError(f"network error contacting {self._config.base_url}: {exc}") from exc
        # v2 instances serve this route (200, no auth); v1 instances 404 it.
        self._version = "v2" if resp.status_code != 404 else "v1"
        return self._version

    # -- Low-level transport ------------------------------------------------

    def _headers(self, version: str, *, require_auth: bool) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "User-Agent": f"pwpush-mcp/{__version__}",
        }
        token = self._config.api_token
        if version == "v2":
            if token:
                headers["Authorization"] = f"Bearer {token}"
            elif require_auth:
                raise PwpushError(self._auth_hint())
        else:  # v1
            if token:
                headers["X-User-Token"] = token
                if self._config.api_email:
                    headers["X-User-Email"] = self._config.api_email
            elif require_auth:
                raise PwpushError(self._auth_hint())
        return headers

    def _auth_hint(self) -> str:
        return (
            "This operation requires authentication, but PWPUSH_API_TOKEN is not "
            "set. Generate a token at "
            f"{self._config.base_url}/api_tokens and set the env var "
            "(v1 instances also need PWPUSH_API_EMAIL)."
        )

    async def _send(
        self,
        method: str,
        path: str,
        version: str,
        *,
        require_auth: bool,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        files: list[tuple[str, Any]] | None = None,
    ) -> Any:
        url = f"{self._config.base_url}{path}"
        headers = self._headers(version, require_auth=require_auth)
        limiter = self._limiter()

        # Application-level retry loop for 429 / 5xx. Multipart uploads carry
        # open file handles positioned at EOF after the first send, so they are
        # not retried (file pushes are rare and one-shot by nature).
        attempts = 1 if files else self._max_retries + 1
        resp: httpx.Response | None = None
        for attempt in range(attempts):
            try:
                if limiter is not None:
                    async with limiter, self._new_client() as client:
                        resp = await client.request(
                            method,
                            url,
                            headers=headers,
                            json=json,
                            params=params,
                            data=data,
                            files=files,
                        )
                else:
                    async with self._new_client() as client:
                        resp = await client.request(
                            method,
                            url,
                            headers=headers,
                            json=json,
                            params=params,
                            data=data,
                            files=files,
                        )
            except httpx.RequestError as exc:
                raise PwpushError(
                    f"network error contacting {self._config.base_url}: {exc}"
                ) from exc

            if resp.status_code in _RETRYABLE_STATUS and attempt < attempts - 1:
                await asyncio.sleep(self._backoff_seconds(resp, attempt))
                continue
            break

        assert resp is not None  # loop always assigns or raises

        if resp.status_code == 429:
            retry = resp.headers.get("Retry-After", "unknown")
            raise PwpushError(f"rate limited (429); retry after {retry}s")
        if resp.status_code == 401:
            raise PwpushError(
                "unauthorized (401): this instance/operation requires valid "
                "credentials (PWPUSH_API_TOKEN, plus PWPUSH_API_EMAIL on v1)"
            )
        if resp.status_code == 403:
            raise PwpushError("forbidden (403): the credentials lack permission for this action")
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
        *,
        payload: str | None,
        kind: str,
        duration: str,
        expire_after_views: int,
        passphrase: str | None,
        name: str | None,
        note: str | None,
        deletable_by_viewer: bool,
        retrieval_step: bool,
        file_paths: list[str] | None = None,
    ) -> dict[str, Any]:
        version = await self._detect_version()
        if version == "v2":
            return await self._create_v2(
                payload=payload,
                kind=kind,
                duration=duration,
                expire_after_views=expire_after_views,
                passphrase=passphrase,
                name=name,
                note=note,
                deletable_by_viewer=deletable_by_viewer,
                retrieval_step=retrieval_step,
                file_paths=file_paths,
            )
        return await self._create_v1(
            payload=payload,
            kind=kind,
            duration=duration,
            expire_after_views=expire_after_views,
            passphrase=passphrase,
            deletable_by_viewer=deletable_by_viewer,
            retrieval_step=retrieval_step,
            file_paths=file_paths,
        )

    async def _create_v2(self, **k: Any) -> dict[str, Any]:
        push: dict[str, Any] = {
            "expire_after_duration": resolve_duration(k["duration"]),
            "expire_after_views": k["expire_after_views"],
            "deletable_by_viewer": k["deletable_by_viewer"],
            "retrieval_step": k["retrieval_step"],
        }
        if k["payload"]:
            push["payload"] = k["payload"]
        if k["passphrase"]:
            push["passphrase"] = k["passphrase"]
        if k["name"]:
            push["name"] = k["name"]
        if k["note"]:
            push["note"] = k["note"]

        if k["file_paths"]:
            form = {f"push[{key}]": _form_value(val) for key, val in push.items()}
            form["push[kind]"] = "file"
            files, handles = _open_files(k["file_paths"], "push[files][]")
            try:
                data = await self._send(
                    "POST", "/api/v2/pushes.json", "v2", require_auth=False, data=form, files=files
                )
            finally:
                for handle in handles:
                    handle.close()
        else:
            push["kind"] = k["kind"]
            data = await self._send(
                "POST", "/api/v2/pushes.json", "v2", require_auth=False, json={"push": push}
            )
        return _public(data)

    async def _create_v1(self, **k: Any) -> dict[str, Any]:
        days = resolve_days(k["duration"])
        common = {
            "expire_after_views": k["expire_after_views"],
            "expire_after_days": days,
            "deletable_by_viewer": k["deletable_by_viewer"],
            "retrieval_step": k["retrieval_step"],
        }
        if k["passphrase"]:
            common["passphrase"] = k["passphrase"]

        if k["file_paths"]:
            form = {f"file[{key}]": _form_value(val) for key, val in common.items()}
            if k["payload"]:
                form["file[payload]"] = k["payload"]
            files, handles = _open_files(k["file_paths"], "file[files][]")
            try:
                data = await self._send_v1_typed(
                    "/f.json", "file pushes", require_auth=False, data=form, files=files
                )
            finally:
                for handle in handles:
                    handle.close()
        elif k["kind"] == "url":
            body = {"url": {"payload": k["payload"], **common}}
            data = await self._send_v1_typed("/r.json", "URL pushes", require_auth=False, json=body)
        else:  # text (qr is not a distinct v1 endpoint; treated as text)
            body = {"password": {"payload": k["payload"], **common}}
            data = await self._send("POST", "/p.json", "v1", require_auth=False, json=body)
        return _public(data)

    async def _send_v1_typed(self, path: str, feature: str, **kw: Any) -> Any:
        """POST to a v1 typed-push endpoint, mapping 404 to a feature hint."""
        try:
            return await self._send("POST", path, "v1", **kw)
        except PwpushError as exc:
            if "404" in str(exc):
                raise FeatureDisabledError(
                    f"{feature} are not enabled on this instance ({path} returned 404)"
                ) from exc
            raise

    async def preview_push(self, url_token: str) -> dict[str, Any]:
        version = await self._detect_version()
        if version == "v2":
            return await self._send(
                "GET", f"/api/v2/pushes/{url_token}/preview.json", "v2", require_auth=False
            )
        return await self._send("GET", f"/p/{url_token}/preview.json", "v1", require_auth=False)

    async def expire_push(self, url_token: str) -> dict[str, Any]:
        version = await self._detect_version()
        if version == "v2":
            data = await self._send(
                "DELETE", f"/api/v2/pushes/{url_token}.json", "v2", require_auth=False
            )
        else:
            data = await self._send("DELETE", f"/p/{url_token}.json", "v1", require_auth=False)
        return _public(data)

    async def push_audit(self, url_token: str, *, page: int = 1) -> Any:
        version = await self._detect_version()
        if version == "v2":
            return await self._send(
                "GET",
                f"/api/v2/pushes/{url_token}/audit.json",
                "v2",
                require_auth=True,
                params={"page": page},
            )
        return await self._send("GET", f"/p/{url_token}/audit.json", "v1", require_auth=True)

    async def list_pushes(self, state: str, *, page: int = 1) -> Any:
        if state not in ("active", "expired"):
            raise PwpushError("state must be 'active' or 'expired'")
        version = await self._detect_version()
        if version == "v2":
            data = await self._send(
                "GET",
                f"/api/v2/pushes/{state}.json",
                "v2",
                require_auth=True,
                params={"page": page},
            )
        else:
            data = await self._send("GET", f"/p/{state}.json", "v1", require_auth=True)
        return _public(data)

    async def version(self) -> dict[str, Any]:
        detected = await self._detect_version()
        if detected == "v2":
            data = await self._send("GET", "/api/v2/version.json", "v2", require_auth=False)
            if isinstance(data, dict):
                data.setdefault("detected_api_version", "v2")
            return data
        # v1 instances expose no version endpoint.
        return {
            "detected_api_version": "v1",
            "note": "legacy instance; no /version endpoint is exposed",
        }
