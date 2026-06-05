"""Structured audit logging for write operations.

Every invocation of a WRITE tool (``create_push``, ``expire_push``) emits one
JSON line on the ``pwpush_mcp.audit`` logger. The default destination is
stderr, which makes it trivial to ship to Loki / CloudWatch / journald via the
container runtime.

The payload contains:
- ts:      ISO-8601 timestamp (UTC, second precision)
- tool:    MCP tool name
- args:    redacted call arguments (secret-bearing keys stripped)
- target:  best-effort identifier (url_token / name) for grep-ability
- status:  "ok" | "error"
- error:   scrubbed exception text (only when status=error)

The secret ``payload`` / ``passphrase`` / file contents are NEVER logged.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime, timezone
from typing import Any

__all__ = ["configure", "log_call", "scrub"]

log = logging.getLogger("pwpush_mcp.audit")

# Argument keys whose values must never appear in the audit log.
_REDACT: frozenset[str] = frozenset({"payload", "passphrase", "token", "api_token", "file_paths"})

# Free-text secret patterns applied by :func:`scrub` to any string about to be
# logged or surfaced to the operator. Each pattern keeps the *label* (group 1)
# so the scrubbed string stays diagnosable (e.g. ``Authorization: Bearer ***``).
_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(authorization\s*:\s*bearer\s+)\S+", re.IGNORECASE),
    re.compile(r"(X-User-Token\s*[:=]\s*)[^&\s\"']+", re.IGNORECASE),
    re.compile(r"(\bapi[_-]?token\s*=\s*)[^&\s\"']+", re.IGNORECASE),
)


def scrub(text: str) -> str:
    """Return *text* with known secret-bearing substrings masked.

    Idempotent and safe to call on already-scrubbed strings.
    """
    for pat in _SECRET_PATTERNS:
        text = pat.sub(r"\1***", text)
    return text


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: ("***" if k in _REDACT else _redact(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v) for v in value]
    return value


def _target(args: dict[str, Any]) -> str | None:
    token = args.get("url_token")
    if token:
        return str(token)
    name = args.get("name")
    if name:
        return f"name:{name}"
    return None


def log_call(
    tool_name: str,
    arguments: dict[str, Any],
    *,
    status: str = "ok",
    error: str | None = None,
) -> None:
    """Emit one audit JSON line. Called from the call_tool handler."""
    record: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tool": tool_name,
        "args": _redact(arguments),
        "target": _target(arguments),
        "status": status,
    }
    if error:
        record["error"] = scrub(error)
    log.info(json.dumps(record, default=str))


def configure(enabled: bool = True) -> None:
    """Idempotently configure the audit logger.

    When enabled, emit one JSON line per record on stderr. ``enabled=False``
    silences it via a NullHandler.
    """
    log.handlers.clear()
    if not enabled:
        log.addHandler(logging.NullHandler())
        log.propagate = False
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(message)s"))
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    # propagate=True so pytest's caplog can intercept; the root logger is
    # unconfigured by default, so this does not duplicate output in production.
    log.propagate = True
