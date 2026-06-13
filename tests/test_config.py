"""Tests for the environment-driven Config, including the new knobs."""

from __future__ import annotations

import pytest

from pwpush_mcp.config import Config

ENV_VARS = [
    "PWPUSH_API_TOKEN",
    "PWPUSH_API_EMAIL",
    "PWPUSH_BASE_URL",
    "PWPUSH_API_VERSION",
    "PWPUSH_VERIFY_SSL",
    "PWPUSH_CA_BUNDLE",
    "PWPUSH_TIMEOUT",
    "PWPUSH_MAX_RETRIES",
    "PWPUSH_MAX_CONCURRENT",
    "PWPUSH_READ_ONLY",
    "PWPUSH_ENABLED_TOOLS",
    "PWPUSH_AUDIT_LOG",
    "PWPUSH_PER_REQUEST_CREDENTIALS",
]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in ENV_VARS:
        monkeypatch.delenv(var, raising=False)


def test_defaults():
    cfg = Config.from_env()
    assert cfg.base_url == "https://pwpush.com"
    assert cfg.api_token is None
    assert cfg.api_version == "auto"
    assert cfg.verify_ssl is True
    assert cfg.timeout == 30.0
    assert cfg.max_retries == 2
    assert cfg.max_concurrent == 0
    assert cfg.read_only is False
    assert cfg.enabled_tools == ()
    assert cfg.audit_log is True
    assert cfg.per_request_credentials is False


def test_security_and_reliability_knobs(monkeypatch):
    monkeypatch.setenv("PWPUSH_READ_ONLY", "true")
    monkeypatch.setenv("PWPUSH_ENABLED_TOOLS", "list_*, get_version ,preview_push")
    monkeypatch.setenv("PWPUSH_AUDIT_LOG", "off")
    monkeypatch.setenv("PWPUSH_MAX_CONCURRENT", "5")
    monkeypatch.setenv("PWPUSH_MAX_RETRIES", "4")
    monkeypatch.setenv("PWPUSH_TIMEOUT", "12.5")
    cfg = Config.from_env()
    assert cfg.read_only is True
    assert cfg.enabled_tools == ("list_*", "get_version", "preview_push")
    assert cfg.audit_log is False
    assert cfg.max_concurrent == 5
    assert cfg.max_retries == 4
    assert cfg.timeout == 12.5


def test_invalid_numbers_fall_back_to_defaults(monkeypatch):
    monkeypatch.setenv("PWPUSH_MAX_RETRIES", "notanint")
    monkeypatch.setenv("PWPUSH_TIMEOUT", "abc")
    cfg = Config.from_env()
    assert cfg.max_retries == 2
    assert cfg.timeout == 30.0


def test_negative_values_clamped_to_zero(monkeypatch):
    monkeypatch.setenv("PWPUSH_MAX_RETRIES", "-3")
    monkeypatch.setenv("PWPUSH_MAX_CONCURRENT", "-1")
    cfg = Config.from_env()
    assert cfg.max_retries == 0
    assert cfg.max_concurrent == 0


def test_placeholder_treated_as_unset(monkeypatch):
    monkeypatch.setenv("PWPUSH_API_TOKEN", "<UNKNOWN>")
    assert Config.from_env().api_token is None


def test_repr_and_str_redact_token():
    cfg = Config(base_url="https://x", api_token="super-secret-token")
    assert "super-secret-token" not in repr(cfg)
    assert "super-secret-token" not in str(cfg)
    assert "***" in repr(cfg)


def test_repr_shows_none_when_no_token():
    cfg = Config(base_url="https://x", api_token=None)
    assert "api_token=None" in repr(cfg)


def test_verify_prefers_ca_bundle():
    assert Config(base_url="x", api_token=None, ca_bundle="/ca.pem").verify == "/ca.pem"
    assert Config(base_url="x", api_token=None, verify_ssl=False).verify is False


def test_per_request_credentials_flag(monkeypatch):
    monkeypatch.setenv("PWPUSH_PER_REQUEST_CREDENTIALS", "true")
    assert Config.from_env().per_request_credentials is True


def test_with_credentials_overrides_only_creds():
    cfg = Config(
        base_url="https://x",
        api_token="orig",
        api_email="o@x.io",
        read_only=True,
        file_root="/srv",
        per_request_credentials=True,
    )
    out = cfg.with_credentials("new-tok", "n@x.io")
    assert out.api_token == "new-tok"
    assert out.api_email == "n@x.io"
    # Operator-controlled settings are preserved untouched.
    assert out.base_url == "https://x"
    assert out.read_only is True
    assert out.file_root == "/srv"
    assert out.per_request_credentials is True


def test_with_credentials_keeps_token_redacted():
    out = Config(base_url="x", api_token=None).with_credentials("super-secret-token", None)
    assert "super-secret-token" not in repr(out)
    assert "***" in repr(out)
