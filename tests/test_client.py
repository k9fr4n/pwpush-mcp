import httpx
import pytest
import respx

from pwpush_mcp.client import FeatureDisabledError, PwpushClient, PwpushError, _public
from pwpush_mcp.config import Config

BASE = "https://pwpush.test"


def make_client(token="tok", version="v2", email=None, file_root=None) -> PwpushClient:
    return PwpushClient(
        Config(
            base_url=BASE,
            api_token=token,
            api_email=email,
            api_version=version,
            file_root=file_root,
        )
    )


CREATE_DEFAULTS = dict(
    payload="s",
    kind="text",
    duration="7d",
    expire_after_views=1,
    passphrase=None,
    name=None,
    note=None,
    deletable_by_viewer=False,
    retrieval_step=True,
)


async def create(client, **overrides):
    return await client.create_push(**{**CREATE_DEFAULTS, **overrides})


def test_public_strips_sensitive():
    obj = {"url_token": "abc", "payload": "secret", "files": [1], "name": "x"}
    assert _public(obj) == {"url_token": "abc", "name": "x"}
    assert _public([obj]) == [{"url_token": "abc", "name": "x"}]


# -- v2 ---------------------------------------------------------------------


@respx.mock
async def test_v2_create_strips_payload_and_maps_duration():
    route = respx.post(f"{BASE}/api/v2/pushes.json").mock(
        return_value=httpx.Response(
            201, json={"url_token": "abc", "html_url": f"{BASE}/p/abc", "payload": "leak"}
        )
    )
    result = await create(make_client(), duration="1d")
    assert result == {"url_token": "abc", "html_url": f"{BASE}/p/abc"}
    body = route.calls.last.request.read()
    assert b'"expire_after_duration":6' in body  # 1d -> enum 6
    assert b'"push"' in body


@respx.mock
async def test_v2_create_works_without_token():
    route = respx.post(f"{BASE}/api/v2/pushes.json").mock(
        return_value=httpx.Response(201, json={"url_token": "abc"})
    )
    await create(make_client(token=None))
    assert "Authorization" not in route.calls.last.request.headers


@respx.mock
async def test_v2_bearer_sent_on_expire():
    route = respx.delete(f"{BASE}/api/v2/pushes/abc.json").mock(
        return_value=httpx.Response(200, json={"expired": True})
    )
    await make_client("mytoken").expire_push("abc")
    assert route.calls.last.request.headers["Authorization"] == "Bearer mytoken"


@respx.mock
async def test_v2_file_push_multipart(tmp_path):
    f = tmp_path / "creds.txt"
    f.write_text("hello")
    route = respx.post(f"{BASE}/api/v2/pushes.json").mock(
        return_value=httpx.Response(201, json={"url_token": "abc", "payload": "leak"})
    )
    result = await create(make_client(file_root=str(tmp_path)), payload=None, file_paths=[str(f)])
    assert result == {"url_token": "abc"}
    req = route.calls.last.request
    assert req.headers["content-type"].startswith("multipart/form-data")
    body = req.content.decode("utf-8", "replace")
    assert 'name="push[files][]"' in body
    assert 'name="push[kind]"' in body and "file" in body


# -- v1 ---------------------------------------------------------------------


@respx.mock
async def test_v1_create_uses_password_wrapper_and_days():
    route = respx.post(f"{BASE}/p.json").mock(
        return_value=httpx.Response(201, json={"url_token": "n82", "payload": "leak"})
    )
    result = await create(make_client(version="v1"), duration="7d")
    assert result == {"url_token": "n82"}
    body = route.calls.last.request.read()
    assert b'"password"' in body
    assert b'"expire_after_days":7' in body  # 7d -> 7 days
    assert b"expire_after_duration" not in body


@respx.mock
async def test_v1_create_forwards_name_and_note():
    route = respx.post(f"{BASE}/p.json").mock(
        return_value=httpx.Response(201, json={"url_token": "n82", "payload": "leak"})
    )
    await create(make_client(version="v1"), name="MY-NAME", note="MY-NOTE")
    body = route.calls.last.request.read()
    assert b'"name":"MY-NAME"' in body
    assert b'"note":"MY-NOTE"' in body


@respx.mock
async def test_v1_preview_and_expire_paths():
    respx.get(f"{BASE}/p/n82/preview.json").mock(
        return_value=httpx.Response(200, json={"url": f"{BASE}/fr/p/n82"})
    )
    respx.delete(f"{BASE}/p/n82.json").mock(
        return_value=httpx.Response(200, json={"expired": True, "deleted": True})
    )
    c = make_client(version="v1", token=None)
    assert (await c.preview_push("n82"))["url"].endswith("/p/n82")
    assert (await c.expire_push("n82"))["expired"] is True


@respx.mock
async def test_v1_auth_headers():
    route = respx.get(f"{BASE}/p/active.json").mock(return_value=httpx.Response(200, json=[]))
    await make_client(version="v1", token="tk", email="me@x.io").list_pushes("active")
    headers = route.calls.last.request.headers
    assert headers["X-User-Token"] == "tk"
    assert headers["X-User-Email"] == "me@x.io"
    assert "Authorization" not in headers


@respx.mock
async def test_v1_file_push_disabled_maps_to_feature_error(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("x")
    respx.post(f"{BASE}/f.json").mock(return_value=httpx.Response(404))
    with pytest.raises(FeatureDisabledError, match="file pushes are not enabled"):
        await create(
            make_client(version="v1", file_root=str(tmp_path)),
            payload=None,
            file_paths=[str(f)],
        )


# -- auto-detection & shared behaviour --------------------------------------


@respx.mock
async def test_autodetect_v1_when_v2_version_404():
    respx.get(f"{BASE}/api/v2/version.json").mock(return_value=httpx.Response(404))
    route = respx.post(f"{BASE}/p.json").mock(
        return_value=httpx.Response(201, json={"url_token": "x"})
    )
    await create(make_client(version="auto"))
    assert route.called


@respx.mock
async def test_autodetect_v2_when_version_present():
    respx.get(f"{BASE}/api/v2/version.json").mock(
        return_value=httpx.Response(200, json={"version": "2.0"})
    )
    route = respx.post(f"{BASE}/api/v2/pushes.json").mock(
        return_value=httpx.Response(201, json={"url_token": "x"})
    )
    await create(make_client(version="auto"))
    assert route.called


async def test_listing_requires_token():
    with pytest.raises(PwpushError, match="PWPUSH_API_TOKEN"):
        await make_client(token=None, version="v2").list_pushes("active")


@respx.mock
async def test_rate_limit_surfaced():
    # max_retries=0 isolates the surfacing behaviour from the backoff loop
    # (retry/backoff is exercised separately in test_reliability.py).
    respx.post(f"{BASE}/api/v2/pushes.json").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "30"})
    )
    client = PwpushClient(Config(base_url=BASE, api_token="tok", api_version="v2", max_retries=0))
    with pytest.raises(PwpushError, match=r"429.*30"):
        await create(client)


async def test_file_push_missing_file(tmp_path):
    missing = tmp_path / "nope.txt"
    with pytest.raises(PwpushError, match="file not found"):
        await create(
            make_client(version="v2", file_root=str(tmp_path)),
            payload=None,
            file_paths=[str(missing)],
        )


# -- file-push allowlist (#11) ----------------------------------------------


async def test_file_push_disabled_without_root(tmp_path):
    f = tmp_path / "creds.txt"
    f.write_text("x")
    with pytest.raises(PwpushError, match="file pushes are disabled"):
        await create(make_client(version="v2"), payload=None, file_paths=[str(f)])


async def test_file_push_rejects_path_outside_root(tmp_path):
    root = tmp_path / "allowed"
    root.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("top-secret")
    with pytest.raises(PwpushError, match="outside allowed root"):
        await create(
            make_client(version="v2", file_root=str(root)),
            payload=None,
            file_paths=[str(outside)],
        )


async def test_file_push_rejects_traversal(tmp_path):
    root = tmp_path / "allowed"
    root.mkdir()
    (tmp_path / "secret.txt").write_text("top-secret")
    traversal = root / ".." / "secret.txt"
    with pytest.raises(PwpushError, match="outside allowed root"):
        await create(
            make_client(version="v2", file_root=str(root)),
            payload=None,
            file_paths=[str(traversal)],
        )


async def test_file_push_rejects_symlink_escape(tmp_path):
    import os

    root = tmp_path / "allowed"
    root.mkdir()
    target = tmp_path / "secret.txt"
    target.write_text("top-secret")
    link = root / "link.txt"
    os.symlink(target, link)  # symlink inside root pointing outside
    with pytest.raises(PwpushError, match="outside allowed root"):
        await create(
            make_client(version="v2", file_root=str(root)),
            payload=None,
            file_paths=[str(link)],
        )
