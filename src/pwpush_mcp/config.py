"""Runtime configuration, sourced exclusively from environment variables.

The API token is never accepted as a tool parameter: it must come from the
environment so it can never be supplied (or logged) by the language model.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_BASE_URL = "https://pwpush.com"


@dataclass(frozen=True)
class Config:
    base_url: str
    api_token: str | None

    @classmethod
    def from_env(cls) -> "Config":
        base = os.environ.get("PWPUSH_BASE_URL", DEFAULT_BASE_URL).strip().rstrip("/")
        if not base:
            base = DEFAULT_BASE_URL
        token = os.environ.get("PWPUSH_API_TOKEN") or None
        return cls(base_url=base, api_token=token)
