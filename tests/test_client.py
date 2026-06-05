import httpx
import pytest
import respx

from pwpush_mcp.client import PwpushClient, PwpushError, _public
from pwpush_mcp.config import Config

BASE = "https://pwpush.test"


def make_client(token="tok") -> PwpushClient:
    return PwpushClient(Config(base_url=BASE, api_token=token))


def test_public_strips_sensitive():
    obj = {"url_token": "abc", "payload": "secret", "files": [1], "name": "x"}
    assert _public(obj) == {"url_token": "abc", "name": "x"}
    assert _public([obj]) == [{"url_token": "abc", "name": "x"}]


@respx.mock
async def test_create_push_strips_payload():
    respx.post(f"{BASE}/api/v2/pushes").mock(
        return_value=httpx.Response(
            201,
            json={"url_token": "abc", "html_url": f"{BASE}/p/abc", "payload": "leak"},
        )
    )
    result = await make_client().create_push({"payload": "s", "kind": "text"})
    assert result["url_token"] == "abc"
    assert "payload" not in result


@respx.mock
async def test_preview_no_auth_header_required():
    route = respx.get(f"{BASE}/api/v2/pushes/abc/preview").mock(
        return_value=httpx.Response(200, json={"url": f"{BASE}/p/abc"})
    )
    result = await make_client(token=None).preview_push("abc")
    assert result["url"] == f"{BASE}/p/abc"
    assert "Authorization" not in route.calls.last.request.headers


@respx.mock
async def test_create_works_without_token():
    route = respx.post(f"{BASE}/api/v2/pushes").mock(
        return_value=httpx.Response(201, json={"url_token": "abc"})
    )
    await make_client(token=None).create_push({"payload": "s"})
    assert "Authorization" not in route.calls.last.request.headers


async def test_listing_requires_token():
    client = make_client(token=None)
    with pytest.raises(PwpushError, match="PWPUSH_API_TOKEN"):
        await client.list_pushes("active")


@respx.mock
async def test_file_push_multipart(tmp_path):
    f = tmp_path / "creds.txt"
    f.write_text("hello")
    route = respx.post(f"{BASE}/api/v2/pushes").mock(
        return_value=httpx.Response(201, json={"url_token": "abc", "payload": "leak"})
    )
    result = await make_client().create_push(
        {"expire_after_views": 1}, file_paths=[str(f)]
    )
    assert result == {"url_token": "abc"}
    req = route.calls.last.request
    assert req.headers["content-type"].startswith("multipart/form-data")
    body = req.content.decode("utf-8", "replace")
    assert 'name="push[files][]"' in body
    assert 'name="push[kind]"' in body and "file" in body


async def test_file_push_missing_file():
    with pytest.raises(PwpushError, match="file not found"):
        await make_client().create_push({}, file_paths=["/no/such/file.txt"])


@respx.mock
async def test_rate_limit_surfaced():
    respx.post(f"{BASE}/api/v2/pushes").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "30"})
    )
    with pytest.raises(PwpushError, match="429.*30"):
        await make_client().create_push({"payload": "s"})


@respx.mock
async def test_404_message():
    respx.get(f"{BASE}/api/v2/pushes/x/preview").mock(return_value=httpx.Response(404))
    with pytest.raises(PwpushError, match="not found"):
        await make_client().preview_push("x")


@respx.mock
async def test_bearer_token_sent():
    route = respx.delete(f"{BASE}/api/v2/pushes/abc").mock(
        return_value=httpx.Response(200, json={"expired": True, "deleted": True})
    )
    await make_client("mytoken").expire_push("abc")
    assert route.calls.last.request.headers["Authorization"] == "Bearer mytoken"
