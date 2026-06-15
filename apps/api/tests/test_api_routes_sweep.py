"""Closing branch-coverage sweep for remaining :mod:`app.api` routes and helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlmodel import Session

from app import api as api_module
from app.config import get_settings
from app.database import get_engine
from app.models import MediaAsset
from app.share_links import build_share_token_with_ttl


def _register(client, *, email: str, organization_name: str = "Sweep Org") -> dict:
    resp = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "Password123!", "organization_name": organization_name},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    body.setdefault("email", email)
    return body


def _create_project(client, headers, name="SweepP") -> dict:
    resp = client.post("/api/v1/projects", headers=headers, json={"name": name})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _upload(client, headers, *, kind, filename, content, ctype, project_id=None):
    data = {"kind": kind}
    if project_id:
        data["project_id"] = project_id
    resp = client.post(
        "/api/v1/assets/upload",
        headers=headers,
        data=data,
        files={"file": (filename, content, ctype)},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# dispatch-arg helpers (pure)
# ---------------------------------------------------------------------------


def test_style_subtitles_dispatch_args():
    args = api_module._style_subtitles_dispatch_args(
        {"subtitle_asset_id": "abc", "style": {"font": "Inter"}, "preview_seconds": 2}
    )
    assert args[0] == "abc"
    assert args[1] == {"font": "Inter"}
    assert args[2] == {"preview_seconds": 2}
    # non-dict style -> {}
    assert api_module._style_subtitles_dispatch_args({"style": "x"})[1] == {}


def test_merge_av_dispatch_args():
    payload = {"audio_asset_id": "aud"}
    args = api_module._merge_av_dispatch_args(payload)
    assert args == ("aud", payload)


def test_cut_clip_dispatch_args():
    assert api_module._cut_clip_dispatch_args({"start": 5, "end": 10})[:2] == (5.0, 10.0)
    # end < start -> clamped to start; negative start -> 0
    s, e, _ = api_module._cut_clip_dispatch_args({"start": -3, "end": -10})
    assert s == 0.0 and e == 0.0


# ---------------------------------------------------------------------------
# system_status worker diagnostics (mock celery)
# ---------------------------------------------------------------------------


class _FakeControl:
    def __init__(self, pongs):
        self._pongs = pongs

    def ping(self, timeout=1.0):
        return self._pongs


class _FakeAsyncResult:
    def get(self, timeout=None):
        return {"cpu": "ok"}


class _FakeCeleryApp:
    def __init__(self, pongs):
        self.control = _FakeControl(pongs)

    def send_task(self, name):
        return _FakeAsyncResult()


def test_system_status_with_healthy_worker(test_client, monkeypatch):
    client, *_ = test_client
    monkeypatch.setattr(
        api_module, "get_celery_app", lambda: _FakeCeleryApp([{"worker-1@host": {"ok": 1}}])
    )
    resp = client.get("/api/v1/system/status")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["worker"]["ping_ok"] is True
    assert "worker-1@host" in body["worker"]["workers"]
    assert body["worker"]["system_info"] == {"cpu": "ok"}


def test_system_status_worker_diagnostics_task_fails(test_client, monkeypatch):
    client, *_ = test_client

    class _BadApp(_FakeCeleryApp):
        def send_task(self, name):
            raise RuntimeError("task boom")

    monkeypatch.setattr(
        api_module, "get_celery_app", lambda: _BadApp([{"worker-1@host": {}}])
    )
    resp = client.get("/api/v1/system/status")
    assert resp.status_code == 200, resp.text
    assert "diagnostics task failed" in resp.json()["worker"]["error"]


def test_system_status_no_workers(test_client, monkeypatch):
    client, *_ = test_client
    monkeypatch.setattr(api_module, "get_celery_app", lambda: _FakeCeleryApp([]))
    resp = client.get("/api/v1/system/status")
    assert resp.status_code == 200, resp.text
    assert resp.json()["worker"]["ping_ok"] is False


# ---------------------------------------------------------------------------
# cancel_job
# ---------------------------------------------------------------------------


def test_cancel_job_flows(test_client):
    client, *_ = test_client
    user = _register(client, email="cancel@test.dev")
    headers = {"Authorization": f"Bearer {user['access_token']}"}
    video = _upload(client, headers, kind="video", filename="c.mp4", content=b"v", ctype="video/mp4")
    job = client.post(
        "/api/v1/captions/jobs",
        headers=headers,
        json={"video_asset_id": video["id"], "options": {"formats": ["vtt"]}},
    ).json()
    ok = client.post(f"/api/v1/jobs/{job['id']}/cancel", headers=headers)
    assert ok.status_code == 200, ok.text
    # cancelling again -> already finished 409
    again = client.post(f"/api/v1/jobs/{job['id']}/cancel", headers=headers)
    assert again.status_code == 409, again.text
    # unknown job -> 404
    assert client.post(f"/api/v1/jobs/{uuid4()}/cancel", headers=headers).status_code == 404


# ---------------------------------------------------------------------------
# translate-subtitle tool + idempotency
# ---------------------------------------------------------------------------


def test_translate_subtitle_tool_and_idempotency(test_client):
    client, *_ = test_client
    user = _register(client, email="trans@test.dev")
    headers = {"Authorization": f"Bearer {user['access_token']}"}
    project = _create_project(client, headers)
    subtitle = _upload(
        client,
        headers,
        kind="subtitle",
        filename="t.vtt",
        content=b"WEBVTT",
        ctype="text/vtt",
        project_id=project["id"],
    )
    body = {
        "subtitle_asset_id": subtitle["id"],
        "project_id": project["id"],
        "target_language": "es",
        "idempotency_key": "trans-key-1",
    }
    first = client.post("/api/v1/utilities/translate-subtitle", headers=headers, json=body)
    assert first.status_code == 201, first.text
    # same idempotency key -> returns existing with 200
    second = client.post("/api/v1/utilities/translate-subtitle", headers=headers, json=body)
    assert second.status_code == 200, second.text
    assert second.json()["id"] == first.json()["id"]


# ---------------------------------------------------------------------------
# share-links + download_shared_asset
# ---------------------------------------------------------------------------


def test_create_share_links_and_download(test_client):
    client, *_ = test_client
    user = _register(client, email="share@test.dev")
    headers = {"Authorization": f"Bearer {user['access_token']}"}
    project = _create_project(client, headers)
    asset = _upload(
        client,
        headers,
        kind="subtitle",
        filename="sh.vtt",
        content=b"WEBVTT shared",
        ctype="text/vtt",
        project_id=project["id"],
    )
    created = client.post(
        f"/api/v1/projects/{project['id']}/share-links",
        headers=headers,
        json={"asset_ids": [asset["id"]], "expires_in_hours": 5},
    )
    assert created.status_code == 200, created.text
    link = created.json()["links"][0]["url"]
    # follow the share link (no auth needed)
    dl = client.get(link)
    assert dl.status_code == 200, dl.text
    assert dl.content


def test_create_share_links_asset_not_in_project(test_client):
    client, *_ = test_client
    user = _register(client, email="share2@test.dev")
    headers = {"Authorization": f"Bearer {user['access_token']}"}
    project = _create_project(client, headers)
    # asset uploaded without the project -> conflict when sharing under the project.
    asset = _upload(
        client, headers, kind="subtitle", filename="np.vtt", content=b"WEBVTT", ctype="text/vtt"
    )
    resp = client.post(
        f"/api/v1/projects/{project['id']}/share-links",
        headers=headers,
        json={"asset_ids": [asset["id"]]},
    )
    assert resp.status_code == 409, resp.text


def test_create_share_links_asset_not_found(test_client):
    client, *_ = test_client
    user = _register(client, email="share3@test.dev")
    headers = {"Authorization": f"Bearer {user['access_token']}"}
    project = _create_project(client, headers)
    resp = client.post(
        f"/api/v1/projects/{project['id']}/share-links",
        headers=headers,
        json={"asset_ids": [str(uuid4())]},
    )
    assert resp.status_code == 404, resp.text


def test_download_shared_asset_invalid_token(test_client):
    client, *_ = test_client
    user = _register(client, email="badshare@test.dev")
    headers = {"Authorization": f"Bearer {user['access_token']}"}
    project = _create_project(client, headers)
    asset = _upload(
        client,
        headers,
        kind="subtitle",
        filename="bt.vtt",
        content=b"WEBVTT",
        ctype="text/vtt",
        project_id=project["id"],
    )
    # invalid token -> 403
    bad = client.get(f"/api/v1/share/assets/{asset['id']}?token=not-a-token")
    assert bad.status_code == 403, bad.text
    # valid token but wrong asset id -> 403 (asset mismatch)
    settings = get_settings()
    token, _ = build_share_token_with_ttl(
        secret=settings.share_link_secret,
        asset_id=UUID(asset["id"]),
        project_id=UUID(project["id"]),
        ttl_hours=5,
    )
    mismatch = client.get(f"/api/v1/share/assets/{uuid4()}?token={token}")
    assert mismatch.status_code == 403, mismatch.text


# ---------------------------------------------------------------------------
# complete_asset_upload (single-part finalize via _pending_uploads)
# ---------------------------------------------------------------------------


def test_complete_asset_upload_flows(test_client, monkeypatch):
    client, *_ = test_client
    user = _register(client, email="complete@test.dev")
    headers = {"Authorization": f"Bearer {user['access_token']}"}
    asset = _upload(
        client, headers, kind="subtitle", filename="cu.vtt", content=b"WEBVTT", ctype="text/vtt"
    )

    # unknown upload session -> 404
    nf = client.post(
        "/api/v1/assets/upload-complete",
        headers=headers,
        json={"upload_id": "missing", "asset_id": asset["id"]},
    )
    assert nf.status_code == 404, nf.text

    # seed a valid pending upload entry, then finalize it.
    api_module._pending_uploads["sess-ok"] = {
        "asset_id": asset["id"],
        "project_id": None,
        "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    ok = client.post(
        "/api/v1/assets/upload-complete",
        headers=headers,
        json={"upload_id": "sess-ok", "asset_id": asset["id"]},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["asset_id"] == asset["id"]

    # expired session -> 409
    api_module._pending_uploads["sess-exp"] = {
        "asset_id": asset["id"],
        "expires_at": datetime.now(timezone.utc) - timedelta(hours=1),
    }
    exp = client.post(
        "/api/v1/assets/upload-complete",
        headers=headers,
        json={"upload_id": "sess-exp", "asset_id": asset["id"]},
    )
    assert exp.status_code == 409, exp.text

    # asset mismatch -> 409
    api_module._pending_uploads["sess-mm"] = {
        "asset_id": str(uuid4()),
        "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    mm = client.post(
        "/api/v1/assets/upload-complete",
        headers=headers,
        json={"upload_id": "sess-mm", "asset_id": asset["id"]},
    )
    assert mm.status_code == 409, mm.text
    api_module._pending_uploads.pop("sess-mm", None)


# ---------------------------------------------------------------------------
# presigned upload init via mocked S3 backend
# ---------------------------------------------------------------------------


def test_presigned_upload_init_with_s3(test_client, monkeypatch):
    client, *_ = test_client
    user = _register(client, email="presign@test.dev")
    headers = {"Authorization": f"Bearer {user['access_token']}"}

    from app import storage as storage_module

    class _FakeS3Client:
        def generate_presigned_url(self, op, *, Params, ExpiresIn):  # noqa: N803
            return f"https://signed/{op}/{Params.get('Key', '')}"

    class _FakeSession:
        def client(self, service, *, region_name=None, endpoint_url=None):
            return _FakeS3Client()

    class _FakeBoto3:
        class session:  # noqa: N801
            @staticmethod
            def Session(**kwargs):  # noqa: N802
                return _FakeSession()

    monkeypatch.setattr(storage_module, "_ensure_boto3", lambda: _FakeBoto3())
    monkeypatch.setenv("REFRAME_STORAGE_BACKEND", "s3")
    monkeypatch.setenv("REFRAME_S3_BUCKET", "presign-bucket")
    get_settings.cache_clear()

    resp = client.post(
        "/api/v1/assets/upload-init",
        headers=headers,
        json={"kind": "video", "filename": "big.mp4", "mime_type": "video/mp4"},
    )
    # The S3 backend supports presigned uploads -> a direct upload target is returned.
    assert resp.status_code in (200, 201), resp.text
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# _stream_remote_download (mock httpx)
# ---------------------------------------------------------------------------


def test_stream_remote_download_success(monkeypatch):
    class _Resp:
        headers = {"content-type": "video/mp4; charset=utf-8"}

        def raise_for_status(self):
            return None

        def iter_bytes(self, chunk_size=0):
            yield b"chunk-1"
            yield b""  # skipped
            yield b"chunk-2"

    class _Stream:
        def __init__(self, resp):
            self._resp = resp

        def __enter__(self):
            return self._resp

        def __exit__(self, *args):
            return False

    class _Client:
        def __init__(self, **kwargs):
            self._resp = _Resp()

        def stream(self, method, url):
            return _Stream(self._resp)

        def close(self):
            return None

    monkeypatch.setattr(api_module.httpx, "Client", _Client)
    resp = api_module._stream_remote_download(
        url="https://example.com/v.mp4", filename="v.mp4", mime_type=None
    )
    # media type derived from the upstream content-type header.
    assert resp.media_type == "video/mp4"
    iterator = resp.body_iterator
    if hasattr(iterator, "__anext__"):
        import asyncio

        async def _collect():
            return [chunk async for chunk in iterator]

        collected = asyncio.run(_collect())
    else:
        collected = list(iterator)
    body = b"".join(c if isinstance(c, bytes) else c.encode() for c in collected)
    assert body == b"chunk-1chunk-2"
