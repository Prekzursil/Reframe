"""Unit tests for the local and S3 storage backends in :mod:`app.storage`."""

from __future__ import annotations

from pathlib import Path

import pytest

from app import storage as storage_module
from app.storage import (
    LocalStorageBackend,
    S3StorageBackend,
    get_storage,
    is_remote_uri,
)


# ---------------------------------------------------------------------------
# is_remote_uri
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "uri,expected",
    [
        ("http://example.com/a", True),
        ("https://example.com/a", True),
        ("s3://bucket/key", True),
        ("gs://bucket/key", True),
        ("/media/file.mp4", False),
        ("file.mp4", False),
        ("", False),
        (None, False),  # type: ignore[arg-type]
    ],
)
def test_is_remote_uri(uri, expected):
    assert is_remote_uri(uri) is expected


# ---------------------------------------------------------------------------
# LocalStorageBackend
# ---------------------------------------------------------------------------


def test_local_write_bytes_with_rel_dir(tmp_path: Path):
    backend = LocalStorageBackend(media_root=tmp_path)
    uri = backend.write_bytes(rel_dir="sub/dir", filename="a.bin", data=b"hello")
    assert uri == "/media/sub/dir/a.bin"
    assert (tmp_path / "sub" / "dir" / "a.bin").read_bytes() == b"hello"


def test_local_write_bytes_without_rel_dir(tmp_path: Path):
    backend = LocalStorageBackend(media_root=tmp_path)
    uri = backend.write_bytes(rel_dir="", filename="root.bin", data=b"x")
    assert uri == "/media/root.bin"
    assert (tmp_path / "root.bin").read_bytes() == b"x"


def test_local_write_file_copies_and_returns_uri(tmp_path: Path):
    src = tmp_path / "source.txt"
    src.write_bytes(b"payload")
    backend = LocalStorageBackend(media_root=tmp_path / "store")
    uri = backend.write_file(rel_dir="d", filename="copy.txt", source_path=src)
    assert uri == "/media/d/copy.txt"
    assert (tmp_path / "store" / "d" / "copy.txt").read_bytes() == b"payload"


def test_local_write_file_without_rel_dir(tmp_path: Path):
    src = tmp_path / "source2.txt"
    src.write_bytes(b"p2")
    backend = LocalStorageBackend(media_root=tmp_path / "store2")
    uri = backend.write_file(rel_dir="", filename="r.txt", source_path=src)
    assert uri == "/media/r.txt"


def test_local_write_file_same_source_and_target_skips_copy(tmp_path: Path):
    backend = LocalStorageBackend(media_root=tmp_path)
    target = tmp_path / "same.bin"
    target.write_bytes(b"original")
    # source_path resolves to the same path as the target -> copy is skipped.
    uri = backend.write_file(rel_dir="", filename="same.bin", source_path=target)
    assert uri == "/media/same.bin"
    assert target.read_bytes() == b"original"


def test_local_resolve_local_path_strips_public_prefix(tmp_path: Path):
    backend = LocalStorageBackend(media_root=tmp_path)
    resolved = backend.resolve_local_path("/media/sub/file.mp4")
    assert resolved == (tmp_path / "sub" / "file.mp4").resolve()


def test_local_resolve_local_path_without_prefix(tmp_path: Path):
    backend = LocalStorageBackend(media_root=tmp_path)
    resolved = backend.resolve_local_path("sub/other.mp4")
    assert resolved == (tmp_path / "sub" / "other.mp4").resolve()


def test_local_resolve_local_path_rejects_remote(tmp_path: Path):
    backend = LocalStorageBackend(media_root=tmp_path)
    with pytest.raises(ValueError, match="Cannot resolve remote uri"):
        backend.resolve_local_path("s3://bucket/key")


def test_local_resolve_local_path_rejects_escape(tmp_path: Path):
    backend = LocalStorageBackend(media_root=tmp_path / "root")
    with pytest.raises(ValueError, match="escapes media root"):
        backend.resolve_local_path("/media/../../etc/passwd")


def test_local_get_download_url(tmp_path: Path):
    backend = LocalStorageBackend(media_root=tmp_path)
    assert backend.get_download_url("/media/a.mp4") == "/media/a.mp4"
    assert backend.get_download_url("") is None


def test_local_delete_uri_removes_file(tmp_path: Path):
    backend = LocalStorageBackend(media_root=tmp_path)
    backend.write_bytes(rel_dir="", filename="del.bin", data=b"z")
    target = tmp_path / "del.bin"
    assert target.exists()
    backend.delete_uri("/media/del.bin")
    assert not target.exists()


def test_local_delete_uri_noop_for_empty(tmp_path: Path):
    backend = LocalStorageBackend(media_root=tmp_path)
    # Should not raise even though no file exists.
    backend.delete_uri("")
    backend.delete_uri("/media/missing.bin")


def test_local_presigned_and_multipart_unsupported(tmp_path: Path):
    backend = LocalStorageBackend(media_root=tmp_path)
    with pytest.raises(ValueError, match="presigned uploads are not supported"):
        backend.create_presigned_upload(
            rel_dir="d", filename="f", content_type=None, expires_seconds=60
        )
    with pytest.raises(ValueError, match="Multipart uploads are not supported"):
        backend.create_multipart_upload(rel_dir="d", filename="f", content_type=None)
    with pytest.raises(ValueError, match="Multipart uploads are not supported"):
        backend.sign_multipart_part(
            key="k", provider_upload_id="u", part_number=1, expires_seconds=60
        )
    with pytest.raises(ValueError, match="Multipart uploads are not supported"):
        backend.complete_multipart_upload(key="k", provider_upload_id="u", parts=[])
    with pytest.raises(ValueError, match="Multipart uploads are not supported"):
        backend.abort_multipart_upload(key="k", provider_upload_id="u")


# ---------------------------------------------------------------------------
# S3StorageBackend with a fake boto3 client
# ---------------------------------------------------------------------------


class _FakeS3Client:
    """Records calls and returns canned responses for the S3 API surface used."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def put_object(self, **kwargs):
        self.calls.append(("put_object", kwargs))
        return {}

    def upload_file(self, *args, **kwargs):
        self.calls.append(("upload_file", {"args": args, "kwargs": kwargs}))
        return {}

    def generate_presigned_url(self, operation, *, Params, ExpiresIn):  # noqa: N803
        self.calls.append(
            ("generate_presigned_url", {"op": operation, "Params": Params, "ExpiresIn": ExpiresIn})
        )
        return f"https://signed/{operation}/{Params.get('Key', '')}?e={ExpiresIn}"

    def delete_object(self, **kwargs):
        self.calls.append(("delete_object", kwargs))
        return {}

    def create_multipart_upload(self, **kwargs):
        self.calls.append(("create_multipart_upload", kwargs))
        return {"UploadId": "upload-123"}

    def complete_multipart_upload(self, **kwargs):
        self.calls.append(("complete_multipart_upload", kwargs))
        return {}

    def abort_multipart_upload(self, **kwargs):
        self.calls.append(("abort_multipart_upload", kwargs))
        return {}


class _FakeSession:
    def __init__(self, client: _FakeS3Client, recorder: dict) -> None:
        self._client = client
        self._recorder = recorder

    def client(self, service, *, region_name=None, endpoint_url=None):
        self._recorder["client"] = {
            "service": service,
            "region_name": region_name,
            "endpoint_url": endpoint_url,
        }
        return self._client


class _FakeBoto3:
    def __init__(self, client: _FakeS3Client, recorder: dict) -> None:
        self._client = client
        self._recorder = recorder

        outer = self

        class _SessionFactory:
            @staticmethod
            def Session(**kwargs):  # noqa: N802
                outer._recorder["session_kwargs"] = kwargs
                return _FakeSession(outer._client, outer._recorder)

        self.session = _SessionFactory()


@pytest.fixture()
def fake_boto3(monkeypatch: pytest.MonkeyPatch):
    client = _FakeS3Client()
    recorder: dict = {}
    fake = _FakeBoto3(client, recorder)
    monkeypatch.setattr(storage_module, "_ensure_boto3", lambda: fake)
    # Clear any credential env vars so the no-credentials branch is deterministic
    # unless a test sets them explicitly.
    for key in (
        "REFRAME_S3_ACCESS_KEY_ID",
        "S3_ACCESS_KEY_ID",
        "REFRAME_S3_SECRET_ACCESS_KEY",
        "S3_SECRET_ACCESS_KEY",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "REFRAME_S3_SESSION_TOKEN",
        "S3_SESSION_TOKEN",
        "AWS_SESSION_TOKEN",
    ):
        monkeypatch.delenv(key, raising=False)
    return client, recorder


def _make_s3(**overrides) -> S3StorageBackend:
    params = {"bucket": "my-bucket", "prefix": "media"}
    params.update(overrides)
    return S3StorageBackend(**params)


def test_s3_requires_bucket(fake_boto3):
    with pytest.raises(ValueError, match="S3 bucket is required"):
        _make_s3(bucket="")


def test_s3_uses_explicit_credentials(fake_boto3, monkeypatch: pytest.MonkeyPatch):
    _client, recorder = fake_boto3
    monkeypatch.setenv("REFRAME_S3_ACCESS_KEY_ID", "AKIA")
    monkeypatch.setenv("REFRAME_S3_SECRET_ACCESS_KEY", "SECRET")
    monkeypatch.setenv("REFRAME_S3_SESSION_TOKEN", "TOKEN")
    _make_s3(region="us-east-1", endpoint_url="https://r2.example.com")
    assert recorder["session_kwargs"]["aws_access_key_id"] == "AKIA"
    assert recorder["session_kwargs"]["aws_secret_access_key"] == "SECRET"
    assert recorder["session_kwargs"]["aws_session_token"] == "TOKEN"
    assert recorder["client"]["region_name"] == "us-east-1"
    assert recorder["client"]["endpoint_url"] == "https://r2.example.com"


def test_s3_uses_default_session_without_credentials(fake_boto3):
    _client, recorder = fake_boto3
    _make_s3()
    # Default Session() called with no credential kwargs.
    assert recorder["session_kwargs"] == {}


def test_s3_presign_expiry_floor(fake_boto3):
    backend = _make_s3(presign_expires_seconds=1)
    assert backend.presign_expires_seconds == 60


def test_s3_write_bytes_with_and_without_content_type(fake_boto3):
    client, _ = fake_boto3
    backend = _make_s3()
    uri = backend.write_bytes(rel_dir="d", filename="f.bin", data=b"hi", content_type="text/plain")
    assert uri == "s3://my-bucket/media/d/f.bin"
    op, kwargs = client.calls[-1]
    assert op == "put_object"
    assert kwargs["ContentType"] == "text/plain"
    assert kwargs["Key"] == "media/d/f.bin"

    backend.write_bytes(rel_dir="d", filename="g.bin", data=b"hi")
    op, kwargs = client.calls[-1]
    assert "ContentType" not in kwargs


def test_s3_write_file_with_and_without_content_type(fake_boto3, tmp_path: Path):
    client, _ = fake_boto3
    src = tmp_path / "up.bin"
    src.write_bytes(b"data")
    backend = _make_s3()
    uri = backend.write_file(
        rel_dir="d", filename="f.bin", source_path=src, content_type="video/mp4"
    )
    assert uri == "s3://my-bucket/media/d/f.bin"
    op, payload = client.calls[-1]
    assert op == "upload_file"
    assert payload["kwargs"]["ExtraArgs"] == {"ContentType": "video/mp4"}

    backend.write_file(rel_dir="d", filename="g.bin", source_path=src)
    op, payload = client.calls[-1]
    assert "ExtraArgs" not in payload["kwargs"]


def test_s3_resolve_local_path_unsupported(fake_boto3):
    backend = _make_s3()
    with pytest.raises(ValueError, match="does not support resolving a local path"):
        backend.resolve_local_path("s3://my-bucket/media/x")


def test_s3_get_download_url_returns_none_for_unknown_uri(fake_boto3):
    backend = _make_s3()
    assert backend.get_download_url("") is None
    assert backend.get_download_url("s3://other-bucket/key") is None
    # Non-s3 uri with no public_base_url configured -> falls through to None.
    assert backend.get_download_url("https://random.example/file") is None


def test_s3_get_download_url_non_matching_public_base(fake_boto3):
    backend = _make_s3(public_base_url="https://cdn.example.com")
    # Non-s3 uri that does not start with the configured base -> None.
    assert backend.get_download_url("https://other.example.com/file") is None


def test_ensure_boto3_returns_real_module():
    # boto3 is installed in the test environment, so this exercises the happy path.
    boto3 = storage_module._ensure_boto3()
    assert hasattr(boto3, "session")


def test_s3_get_download_url_public_when_enabled(fake_boto3):
    backend = _make_s3(public_downloads=True, public_base_url="https://cdn.example.com")
    url = backend.get_download_url("s3://my-bucket/media/d/f.bin")
    assert url == "https://cdn.example.com/media/d/f.bin"


def test_s3_get_download_url_public_enabled_but_no_base_falls_back_to_presigned(fake_boto3):
    backend = _make_s3(public_downloads=True, public_base_url=None)
    url = backend.get_download_url("s3://my-bucket/media/d/f.bin")
    assert url.startswith("https://signed/get_object/media/d/f.bin")


def test_s3_get_download_url_presigned_when_not_public(fake_boto3):
    backend = _make_s3(public_downloads=False)
    url = backend.get_download_url("s3://my-bucket/media/d/f.bin")
    assert url.startswith("https://signed/get_object/")


def test_s3_key_from_uri_via_public_base_url(fake_boto3):
    backend = _make_s3(public_base_url="https://cdn.example.com", public_downloads=True)
    url = backend.get_download_url("https://cdn.example.com/media/d/f.bin")
    assert url == "https://cdn.example.com/media/d/f.bin"


def test_s3_key_from_uri_public_base_empty_remainder(fake_boto3):
    backend = _make_s3(public_base_url="https://cdn.example.com")
    # URL equal to base (no remainder) -> no key -> no download url.
    assert backend.get_download_url("https://cdn.example.com") is None


def test_s3_key_from_uri_s3_wrong_bucket_or_missing_key(fake_boto3):
    backend = _make_s3()
    assert backend.get_download_url("s3://my-bucket/") is None  # empty key
    assert backend.get_download_url("s3://wrong/key") is None  # wrong bucket


def test_s3_delete_uri(fake_boto3):
    client, _ = fake_boto3
    backend = _make_s3()
    backend.delete_uri("")  # no-op, key None
    backend.delete_uri("s3://my-bucket/media/d/f.bin")
    op, kwargs = client.calls[-1]
    assert op == "delete_object"
    assert kwargs == {"Bucket": "my-bucket", "Key": "media/d/f.bin"}


def test_s3_create_presigned_upload_with_content_type(fake_boto3):
    backend = _make_s3()
    result = backend.create_presigned_upload(
        rel_dir="d", filename="f.bin", content_type="image/png", expires_seconds=10
    )
    assert result["uri"] == "s3://my-bucket/media/d/f.bin"
    assert result["method"] == "PUT"
    assert result["headers"] == {"Content-Type": "image/png"}
    assert result["expires_in_seconds"] == 60  # floor of 60


def test_s3_create_presigned_upload_without_content_type(fake_boto3):
    backend = _make_s3()
    result = backend.create_presigned_upload(
        rel_dir="d", filename="f.bin", content_type=None, expires_seconds=120
    )
    assert result["headers"] == {}
    assert result["expires_in_seconds"] == 120


def test_s3_create_multipart_upload_with_and_without_content_type(fake_boto3):
    client, _ = fake_boto3
    backend = _make_s3()
    result = backend.create_multipart_upload(
        rel_dir="d", filename="f.bin", content_type="video/mp4"
    )
    assert result == {
        "upload_id": "upload-123",
        "key": "media/d/f.bin",
        "uri": "s3://my-bucket/media/d/f.bin",
    }
    op, kwargs = client.calls[-1]
    assert kwargs["ContentType"] == "video/mp4"

    backend.create_multipart_upload(rel_dir="d", filename="g.bin", content_type=None)
    op, kwargs = client.calls[-1]
    assert "ContentType" not in kwargs


def test_s3_sign_multipart_part(fake_boto3):
    backend = _make_s3()
    result = backend.sign_multipart_part(
        key="media/d/f.bin", provider_upload_id="up", part_number=2, expires_seconds=30
    )
    assert result["method"] == "PUT"
    assert result["headers"] == {}
    assert result["expires_in_seconds"] == 60
    assert result["upload_url"].startswith("https://signed/upload_part/")


def test_s3_complete_multipart_upload_sorts_and_filters_parts(fake_boto3):
    client, _ = fake_boto3
    backend = _make_s3()
    parts = [
        {"part_number": 2, "etag": "etag-2"},
        {"part_number": 0, "etag": "bad"},  # filtered (number <= 0)
        {"part_number": 3, "etag": ""},  # filtered (no etag)
        {"part_number": 1, "etag": "etag-1"},
    ]
    backend.complete_multipart_upload(key="media/d/f.bin", provider_upload_id="up", parts=parts)
    op, kwargs = client.calls[-1]
    assert op == "complete_multipart_upload"
    assert kwargs["MultipartUpload"]["Parts"] == [
        {"ETag": "etag-1", "PartNumber": 1},
        {"ETag": "etag-2", "PartNumber": 2},
    ]


def test_s3_complete_multipart_upload_rejects_empty(fake_boto3):
    backend = _make_s3()
    with pytest.raises(ValueError, match="No multipart upload parts supplied"):
        backend.complete_multipart_upload(
            key="k", provider_upload_id="up", parts=[{"part_number": 0, "etag": ""}]
        )


def test_s3_abort_multipart_upload(fake_boto3):
    client, _ = fake_boto3
    backend = _make_s3()
    backend.abort_multipart_upload(key="media/d/f.bin", provider_upload_id="up")
    op, kwargs = client.calls[-1]
    assert op == "abort_multipart_upload"
    assert kwargs == {"Bucket": "my-bucket", "Key": "media/d/f.bin", "UploadId": "up"}


# ---------------------------------------------------------------------------
# get_storage factory
# ---------------------------------------------------------------------------


@pytest.fixture()
def clean_storage_env(monkeypatch: pytest.MonkeyPatch):
    for key in (
        "REFRAME_STORAGE_BACKEND",
        "STORAGE_BACKEND",
        "REFRAME_OFFLINE_MODE",
        "OFFLINE_MODE",
        "REFRAME_S3_BUCKET",
        "S3_BUCKET",
        "REFRAME_S3_PREFIX",
        "S3_PREFIX",
        "REFRAME_S3_REGION",
        "S3_REGION",
        "AWS_REGION",
        "AWS_DEFAULT_REGION",
        "REFRAME_S3_ENDPOINT_URL",
        "S3_ENDPOINT_URL",
        "REFRAME_S3_PUBLIC_BASE_URL",
        "S3_PUBLIC_BASE_URL",
        "REFRAME_S3_PUBLIC_DOWNLOADS",
        "S3_PUBLIC_DOWNLOADS",
        "REFRAME_S3_PRESIGN_EXPIRES_SECONDS",
        "S3_PRESIGN_EXPIRES_SECONDS",
    ):
        monkeypatch.delenv(key, raising=False)


def test_get_storage_defaults_to_local(clean_storage_env, tmp_path: Path):
    backend = get_storage(media_root=tmp_path)
    assert isinstance(backend, LocalStorageBackend)
    assert backend.media_root == Path(tmp_path)


def test_get_storage_local_aliases(clean_storage_env, monkeypatch: pytest.MonkeyPatch, tmp_path):
    for alias in ("filesystem", "fs", "LOCAL"):
        monkeypatch.setenv("REFRAME_STORAGE_BACKEND", alias)
        assert isinstance(get_storage(media_root=tmp_path), LocalStorageBackend)


def test_get_storage_offline_blocks_remote(clean_storage_env, monkeypatch, tmp_path):
    monkeypatch.setenv("REFRAME_STORAGE_BACKEND", "s3")
    monkeypatch.setenv("REFRAME_OFFLINE_MODE", "1")
    with pytest.raises(RuntimeError, match="OFFLINE_MODE is enabled"):
        get_storage(media_root=tmp_path)


def test_get_storage_offline_allows_local(clean_storage_env, monkeypatch, tmp_path):
    monkeypatch.setenv("REFRAME_OFFLINE_MODE", "1")
    monkeypatch.setenv("REFRAME_STORAGE_BACKEND", "local")
    assert isinstance(get_storage(media_root=tmp_path), LocalStorageBackend)


def test_get_storage_s3(clean_storage_env, monkeypatch, fake_boto3, tmp_path):
    monkeypatch.setenv("REFRAME_STORAGE_BACKEND", "s3")
    monkeypatch.setenv("REFRAME_S3_BUCKET", "factory-bucket")
    monkeypatch.setenv("REFRAME_S3_PREFIX", "p")
    monkeypatch.setenv("REFRAME_S3_REGION", "eu-west-1")
    monkeypatch.setenv("REFRAME_S3_ENDPOINT_URL", "https://r2")
    monkeypatch.setenv("REFRAME_S3_PUBLIC_BASE_URL", "https://cdn")
    monkeypatch.setenv("REFRAME_S3_PUBLIC_DOWNLOADS", "true")
    monkeypatch.setenv("REFRAME_S3_PRESIGN_EXPIRES_SECONDS", "120")
    backend = get_storage(media_root=tmp_path)
    assert isinstance(backend, S3StorageBackend)
    assert backend.bucket == "factory-bucket"
    assert backend.prefix == "p"
    assert backend.public_base_url == "https://cdn"
    assert backend.public_downloads is True
    assert backend.presign_expires_seconds == 120


def test_get_storage_r2_alias(clean_storage_env, monkeypatch, fake_boto3, tmp_path):
    monkeypatch.setenv("REFRAME_STORAGE_BACKEND", "r2")
    monkeypatch.setenv("REFRAME_S3_BUCKET", "r2-bucket")
    backend = get_storage(media_root=tmp_path)
    assert isinstance(backend, S3StorageBackend)


def test_get_storage_s3_region_falls_back_to_aws_env(
    clean_storage_env, monkeypatch, fake_boto3, tmp_path
):
    _client, recorder = fake_boto3
    monkeypatch.setenv("REFRAME_STORAGE_BACKEND", "s3")
    monkeypatch.setenv("REFRAME_S3_BUCKET", "b")
    monkeypatch.setenv("AWS_REGION", "ap-south-1")
    get_storage(media_root=tmp_path)
    assert recorder["client"]["region_name"] == "ap-south-1"


def test_get_storage_unknown_backend(clean_storage_env, monkeypatch, tmp_path):
    monkeypatch.setenv("REFRAME_STORAGE_BACKEND", "azure")
    with pytest.raises(ValueError, match="Unknown storage backend: azure"):
        get_storage(media_root=tmp_path)


# ---------------------------------------------------------------------------
# Internal env helpers
# ---------------------------------------------------------------------------


def test_truthy_env_helper(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("REFRAME_FLAG_X", raising=False)
    monkeypatch.delenv("FLAG_X", raising=False)
    assert storage_module._truthy_env("FLAG_X") is False
    # The bare name takes precedence over the REFRAME_-prefixed fallback.
    monkeypatch.setenv("FLAG_X", "YES")
    assert storage_module._truthy_env("FLAG_X") is True
    monkeypatch.setenv("FLAG_X", "off")
    assert storage_module._truthy_env("FLAG_X") is False
    # Falls back to the REFRAME_-prefixed value when the bare name is unset.
    monkeypatch.delenv("FLAG_X", raising=False)
    monkeypatch.setenv("REFRAME_FLAG_X", "on")
    assert storage_module._truthy_env("FLAG_X") is True


def test_env_helper_prefers_reframe_prefix(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("REFRAME_SOME_VALUE", "  reframe  ")
    monkeypatch.setenv("SOME_VALUE", "plain")
    assert storage_module._env("SOME_VALUE") == "reframe"
    monkeypatch.delenv("REFRAME_SOME_VALUE", raising=False)
    assert storage_module._env("SOME_VALUE") == "plain"


def test_join_key_strips_and_skips_empty():
    assert storage_module._join_key("a/", "/b/", "", "c") == "a/b/c"
    # Empty and slash-only parts are dropped; only the bare "/" and "" vanish here.
    assert storage_module._join_key("", "/", "x") == "x"
    assert storage_module._join_key("", "/") == ""
