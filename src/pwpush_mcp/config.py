"""Runtime configuration, sourced exclusively from environment variables.

The API token is never accepted as a tool parameter: it must come from the
environment so it can never be supplied (or logged) by the language model.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

__all__ = ["DEFAULT_BASE_URL", "VALID_API_VERSIONS", "Config"]

DEFAULT_BASE_URL = "https://pwpush.com"

# Sentinel values injected by orchestrators (e.g. the Docker MCP Gateway) when
# an optional secret declared in the catalog is left unbound by the operator.
# Treat them as "not set" so defaults apply instead of leaking a placeholder.
_PLACEHOLDERS: frozenset[str] = frozenset({"<UNKNOWN>", "<unknown>"})


def _raw_env(name: str) -> str | None:
    raw = os.environ.get(name)
    if raw is None or raw in _PLACEHOLDERS or raw.strip() == "":
        return None
    return raw


def _env_bool(name: str, default: bool) -> bool:
    raw = _raw_env(name)
    if raw is None:
        return default
    return raw.strip().lower() not in ("0", "false", "no", "off")


def _env_int(name: str, default: int) -> int:
    raw = _raw_env(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = _raw_env(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _split_csv(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ()
    return tuple(p.strip() for p in raw.split(",") if p.strip())


VALID_API_VERSIONS = ("auto", "v1", "v2")


@dataclass(frozen=True)
class Config:
    base_url: str
    api_token: str | None
    api_email: str | None = None
    api_version: str = "auto"
    verify_ssl: bool = True
    ca_bundle: str | None = None

    # --- Reliability knobs ------------------------------------------------
    timeout: float = 30.0
    # Number of httpx transport-level retries for connection errors, plus the
    # ceiling on application-level backoff retries for 429 / 5xx responses.
    max_retries: int = 2
    # Max number of concurrent HTTP requests. 0 = unlimited. Protects the
    # upstream instance from an LLM that loops on tools.
    max_concurrent: int = 0

    # --- Security / multi-tenant knobs ------------------------------------
    # When True, write tools (create_push, expire_push) are removed from the
    # server registry. Preview / list / audit / version remain available.
    read_only: bool = False
    # Optional allowlist of tool names (fnmatch globs, e.g. "list_*").
    # Empty tuple = no filter (all tools enabled).
    enabled_tools: tuple[str, ...] = field(default_factory=tuple)
    # When True, every WRITE tool invocation emits one JSON audit line on the
    # `pwpush_mcp.audit` logger (stderr by default).
    audit_log: bool = True

    @classmethod
    def from_env(cls) -> Config:
        base = (_raw_env("PWPUSH_BASE_URL") or DEFAULT_BASE_URL).strip().rstrip("/")
        if not base:
            base = DEFAULT_BASE_URL
        version = (_raw_env("PWPUSH_API_VERSION") or "auto").strip().lower()
        if version not in VALID_API_VERSIONS:
            version = "auto"
        return cls(
            base_url=base,
            api_token=_raw_env("PWPUSH_API_TOKEN"),
            api_email=_raw_env("PWPUSH_API_EMAIL"),
            api_version=version,
            verify_ssl=_env_bool("PWPUSH_VERIFY_SSL", True),
            ca_bundle=_raw_env("PWPUSH_CA_BUNDLE"),
            timeout=_env_float("PWPUSH_TIMEOUT", 30.0),
            max_retries=max(0, _env_int("PWPUSH_MAX_RETRIES", 2)),
            max_concurrent=max(0, _env_int("PWPUSH_MAX_CONCURRENT", 0)),
            read_only=_env_bool("PWPUSH_READ_ONLY", False),
            enabled_tools=_split_csv(_raw_env("PWPUSH_ENABLED_TOOLS")),
            audit_log=_env_bool("PWPUSH_AUDIT_LOG", True),
        )

    @property
    def verify(self) -> bool | str:
        """Value for httpx's ``verify`` parameter (CA bundle path wins)."""
        if self.ca_bundle:
            return self.ca_bundle
        return self.verify_ssl

    def __repr__(self) -> str:
        """Safe representation that never exposes the api_token value.

        The auto-generated dataclass ``__repr__`` would include ``api_token``
        verbatim, which risks leaking the credential into log aggregators,
        tracebacks, and debug output. We redact it unconditionally.
        """
        token = "'***'" if self.api_token else "None"
        return (
            f"Config(base_url={self.base_url!r}, api_token={token}, "
            f"api_email={self.api_email!r}, api_version={self.api_version!r}, "
            f"verify_ssl={self.verify_ssl!r}, ca_bundle={self.ca_bundle!r}, "
            f"timeout={self.timeout!r}, max_retries={self.max_retries!r}, "
            f"max_concurrent={self.max_concurrent!r}, read_only={self.read_only!r}, "
            f"enabled_tools={self.enabled_tools!r}, audit_log={self.audit_log!r})"
        )

    def __str__(self) -> str:
        """Delegate to __repr__ so f-string interpolation is equally safe."""
        return self.__repr__()
