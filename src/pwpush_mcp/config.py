"""Runtime configuration, sourced exclusively from environment variables.

The API token is never accepted as a tool parameter: it must come from the
environment so it can never be supplied (or logged) by the language model.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_BASE_URL = "https://pwpush.com"


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() not in ("0", "false", "no", "off")


VALID_API_VERSIONS = ("auto", "v1", "v2")


@dataclass(frozen=True)
class Config:
    base_url: str
    api_token: str | None
    api_email: str | None = None
    api_version: str = "auto"
    verify_ssl: bool = True
    ca_bundle: str | None = None

    @classmethod
    def from_env(cls) -> "Config":
        base = os.environ.get("PWPUSH_BASE_URL", DEFAULT_BASE_URL).strip().rstrip("/")
        if not base:
            base = DEFAULT_BASE_URL
        token = os.environ.get("PWPUSH_API_TOKEN") or None
        email = os.environ.get("PWPUSH_API_EMAIL") or None
        ca_bundle = os.environ.get("PWPUSH_CA_BUNDLE") or None
        verify_ssl = _env_bool("PWPUSH_VERIFY_SSL", True)
        version = (os.environ.get("PWPUSH_API_VERSION") or "auto").strip().lower()
        if version not in VALID_API_VERSIONS:
            version = "auto"
        return cls(
            base_url=base,
            api_token=token,
            api_email=email,
            api_version=version,
            verify_ssl=verify_ssl,
            ca_bundle=ca_bundle,
        )

    @property
    def verify(self) -> bool | str:
        """Value for httpx's ``verify`` parameter (CA bundle path wins)."""
        if self.ca_bundle:
            return self.ca_bundle
        return self.verify_ssl
