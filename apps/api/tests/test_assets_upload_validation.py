from __future__ import annotations


def test_upload_rejects_invalid_kind(test_client):
    client, _, _, _ = test_client

    resp = client.post(
        "/api/v1/assets/upload",
        files={"file": ("hello.txt", b"hello", "text/plain")},
        data={"kind": "not-a-kind"},
    )
    assert resp.status_code == 400, resp.text


def test_upload_rejects_invalid_content_type_for_video(test_client):
    client, _, _, _ = test_client

    resp = client.post(
        "/api/v1/assets/upload",
        files={"file": ("hello.txt", b"hello", "text/plain")},
        data={"kind": "video"},
    )
    assert resp.status_code == 400, resp.text


def test_upload_enforces_max_upload_bytes(test_client, monkeypatch):
    client, _, _, _ = test_client

    monkeypatch.setenv("REFRAME_MAX_UPLOAD_BYTES", "4")
    from app.config import get_settings

    get_settings.cache_clear()

    resp = client.post(
        "/api/v1/assets/upload",
        files={"file": ("hello.txt", b"hello", "text/plain")},
        data={"kind": "subtitle"},
    )
    assert resp.status_code == 413, resp.text

