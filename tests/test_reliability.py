"""Tests for retry/backoff and concurrency limiting in the client."""

from __future__ import annotations

import asyncio

import httpx
import pytest
import respx

from pwpush_mcp.client import PwpushClient, PwpushError
from pwpush_mcp.config import Config

BASE = "https://pwpush.test"


def _client(**kw) -> PwpushClient:
    kw.setdefault("base_url", BASE)
    kw.setdefault("api_token", "tok")
    kw.setdefault("api_version", "v2")
    return PwpushClient(Config(**kw))


@pytest.fixture
def no_sleep(monkeypatch):
    """Record backoff delays and return immediately."""
    delays: list[float] = []

    async def fake_sleep(seconds):
        delays.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    return delays


@respx.mock
async def test_retries_5xx_then_succeeds(no_sleep):
    route = respx.get(f"{BASE}/api/v2/pushes/abc/preview.json").mock(
        side_effect=[
            httpx.Response(503),
            httpx.Response(503),
            httpx.Response(200, json={"url_token": "abc"}),
        ]
    )
    result = await _client(max_retries=2).preview_push("abc")
    assert result == {"url_token": "abc"}
    assert route.call_count == 3
    assert len(no_sleep) == 2  # two backoff waits between three attempts


@respx.mock
async def test_no_retry_when_disabled(no_sleep):
    route = respx.get(f"{BASE}/api/v2/pushes/abc/preview.json").mock(
        return_value=httpx.Response(503)
    )
    with pytest.raises(PwpushError, match="503"):
        await _client(max_retries=0).preview_push("abc")
    assert route.call_count == 1
    assert no_sleep == []


@respx.mock
async def test_429_honours_retry_after(no_sleep):
    respx.get(f"{BASE}/api/v2/pushes/abc/preview.json").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "7"}),
            httpx.Response(200, json={"url_token": "abc"}),
        ]
    )
    await _client(max_retries=2).preview_push("abc")
    assert no_sleep == [7.0]


@respx.mock
async def test_4xx_not_retried(no_sleep):
    route = respx.get(f"{BASE}/api/v2/pushes/abc/preview.json").mock(
        return_value=httpx.Response(404)
    )
    with pytest.raises(PwpushError, match="404"):
        await _client(max_retries=3).preview_push("abc")
    assert route.call_count == 1  # 404 is a caller error, never retried


def test_limiter_none_when_unlimited():
    assert _client(max_concurrent=0)._limiter() is None


def test_limiter_created_once():
    c = _client(max_concurrent=3)
    first = c._limiter()
    assert isinstance(first, asyncio.Semaphore)
    assert c._limiter() is first  # cached


@respx.mock
async def test_concurrency_limit_serialises_requests(no_sleep):
    in_flight = 0
    peak = 0

    def responder(request):
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        in_flight -= 1
        return httpx.Response(200, json={"ok": True})

    respx.get(f"{BASE}/api/v2/pushes/active.json").mock(side_effect=responder)
    client = _client(max_concurrent=1)
    await asyncio.gather(*(client.list_pushes("active") for _ in range(5)))
    assert peak == 1
