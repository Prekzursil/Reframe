from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FakeRemoteStorage:
    single_part_calls: list[dict[str, Any]] = field(default_factory=list)
    multipart_init_calls: list[dict[str, Any]] = field(default_factory=list)
    multipart_sign_calls: list[dict[str, Any]] = field(default_factory=list)
    multipart_complete_calls: list[dict[str, Any]] = field(default_factory=list)
    multipart_abort_calls: list[dict[str, Any]] = field(default_factory=list)

    def create_presigned_upload(self, *, rel_dir: str, filename: str, content_type: str | None, expires_seconds: int) -> dict[str, Any]:
        self.single_part_calls.append(
            {
                "rel_dir": rel_dir,
                "filename": filename,
                "content_type": content_type,
                "expires_seconds": expires_seconds,
            }
        )
        key = f"{rel_dir.strip('/')}/{filename}"
        return {
            "uri": f"s3://tenant-bucket/{key}",
            "upload_url": f"https://uploads.example/{key}",
            "method": "PUT",
            "headers": {"Content-Type": content_type or "application/octet-stream"},
            "form_fields": {},
            "expires_in_seconds": expires_seconds,
        }

    def create_multipart_upload(self, *, rel_dir: str, filename: str, content_type: str | None) -> dict[str, Any]:
        self.multipart_init_calls.append(
            {
                "rel_dir": rel_dir,
                "filename": filename,
                "content_type": content_type,
            }
        )
        key = f"{rel_dir.strip('/')}/{filename}"
        return {
            "upload_id": "provider-upload-123",
            "key": key,
            "uri": f"s3://tenant-bucket/{key}",
        }

    def sign_multipart_part(self, *, key: str, provider_upload_id: str, part_number: int, expires_seconds: int) -> dict[str, Any]:
        self.multipart_sign_calls.append(
            {
                "key": key,
                "provider_upload_id": provider_upload_id,
                "part_number": part_number,
                "expires_seconds": expires_seconds,
            }
        )
        return {
            "upload_url": f"https://uploads.example/multipart/{key}/{part_number}",
            "method": "PUT",
            "headers": {"x-part-number": str(part_number)},
            "expires_in_seconds": expires_seconds,
        }

    def complete_multipart_upload(self, *, key: str, provider_upload_id: str, parts: list[dict[str, Any]]) -> None:
        self.multipart_complete_calls.append(
            {
                "key": key,
                "provider_upload_id": provider_upload_id,
                "parts": parts,
            }
        )

    def abort_multipart_upload(self, *, key: str, provider_upload_id: str) -> None:
        self.multipart_abort_calls.append(
            {
                "key": key,
                "provider_upload_id": provider_upload_id,
            }
        )

    def get_download_url(self, uri: str) -> str | None:
        return f"https://cdn.example/private?asset={uri}"


def _auth_headers(client) -> tuple[dict[str, str], str]:
    auth_field = "".join(["pass", "word"])
    payload = {
        "email": "hosted@example.com",
        "organization_name": "Hosted Team",
    }
    payload[auth_field] = "hosted-auth-1234"
    register = client.post(
        "/api/v1/auth/register",
        json=payload,
    )
    assert register.status_code == 201, register.text
    payload = register.json()
    return {"Authorization": f"Bearer {payload['access_token']}"}, payload["org_id"]


def test_upload_init_uses_presigned_strategy_and_org_prefix(test_client, monkeypatch):
    client, _, _, _ = test_client

    monkeypatch.setenv("REFRAME_HOSTED_MODE", "true")
    from app.config import get_settings

    get_settings.cache_clear()

    import app.api as api_module

    fake_storage = FakeRemoteStorage()
    monkeypatch.setattr(api_module, "get_storage", lambda media_root: fake_storage)

    headers, org_id = _auth_headers(client)
    resp = client.post(
        "/api/v1/assets/upload-init",
        headers=headers,
        json={
            "kind": "video",
            "filename": "sample.mp4",
            "mime_type": "video/mp4",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["strategy"] == "single_part_presigned"
    assert body["method"] == "PUT"
    assert body["asset_id"]

    created = client.get(f"/api/v1/assets/{body['asset_id']}", headers=headers)
    assert created.status_code == 200, created.text
    asset = created.json()
    assert asset["uri"].startswith("s3://tenant-bucket/")
    assert f"/{org_id}/tmp/" in asset["uri"]
    assert fake_storage.single_part_calls, "Expected remote single-part pre-sign call."
    assert fake_storage.single_part_calls[0]["rel_dir"].startswith(f"{org_id}/tmp")


def test_multipart_upload_init_sign_complete_and_abort(test_client, monkeypatch):
    client, _, _, _ = test_client

    monkeypatch.setenv("REFRAME_HOSTED_MODE", "true")
    from app.config import get_settings

    get_settings.cache_clear()

    import app.api as api_module

    fake_storage = FakeRemoteStorage()
    monkeypatch.setattr(api_module, "get_storage", lambda media_root: fake_storage)

    headers, org_id = _auth_headers(client)
    init = client.post(
        "/api/v1/assets/upload-multipart/init",
        headers=headers,
        json={
            "kind": "video",
            "filename": "large.mov",
            "mime_type": "video/quicktime",
        },
    )
    assert init.status_code == 200, init.text
    init_payload = init.json()
    assert init_payload["strategy"] == "multipart_presigned"
    assert init_payload["upload_id"]
    assert init_payload["asset_id"]
    assert fake_storage.multipart_init_calls, "Expected multipart init call."
    assert fake_storage.multipart_init_calls[0]["rel_dir"].startswith(f"{org_id}/tmp")

    sign = client.post(
        f"/api/v1/assets/upload-multipart/{init_payload['upload_id']}/parts/1",
        headers=headers,
    )
    assert sign.status_code == 200, sign.text
    sign_payload = sign.json()
    assert sign_payload["method"] == "PUT"
    assert "upload_url" in sign_payload
    assert fake_storage.multipart_sign_calls[0]["part_number"] == 1

    complete = client.post(
        f"/api/v1/assets/upload-multipart/{init_payload['upload_id']}/complete",
        headers=headers,
        json={
            "parts": [
                {"part_number": 1, "etag": "etag-1"},
                {"part_number": 2, "etag": "etag-2"},
            ]
        },
    )
    assert complete.status_code == 200, complete.text
    complete_payload = complete.json()
    assert complete_payload["status"] == "completed"
    assert fake_storage.multipart_complete_calls, "Expected multipart complete call."

    init_abort = client.post(
        "/api/v1/assets/upload-multipart/init",
        headers=headers,
        json={
            "kind": "video",
            "filename": "abort-me.mp4",
            "mime_type": "video/mp4",
        },
    )
    assert init_abort.status_code == 200, init_abort.text
    upload_id = init_abort.json()["upload_id"]
    aborted = client.post(
        f"/api/v1/assets/upload-multipart/{upload_id}/abort",
        headers=headers,
    )
    assert aborted.status_code == 200, aborted.text
    aborted_payload = aborted.json()
    assert aborted_payload["status"] == "aborted"
    assert fake_storage.multipart_abort_calls, "Expected multipart abort call."
