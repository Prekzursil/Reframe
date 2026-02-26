from __future__ import annotations

from dataclasses import dataclass
import os
import shutil
from pathlib import Path
from typing import Any, Optional, Protocol


def is_remote_uri(uri: str) -> bool:
    lowered = (uri or "").strip().lower()
    return lowered.startswith(("http://", "https://", "s3://", "gs://"))


class StorageBackend(Protocol):
    def write_bytes(self, *, rel_dir: str, filename: str, data: bytes, content_type: str | None = None) -> str:
        """Store bytes and return a URI suitable for clients."""

    def write_file(self, *, rel_dir: str, filename: str, source_path: Path, content_type: str | None = None) -> str:
        """Store a file and return a URI suitable for clients."""

    def resolve_local_path(self, uri: str) -> Path:
        """Resolve a local filesystem path for a non-remote URI."""

    def get_download_url(self, uri: str) -> str | None:
        """Return a direct download URL for the given URI, if available."""

    def delete_uri(self, uri: str) -> None:
        """Delete a stored object for the given URI if it exists."""

    def create_presigned_upload(
        self,
        *,
        rel_dir: str,
        filename: str,
        content_type: str | None,
        expires_seconds: int,
    ) -> dict[str, Any]:
        """Create a single-part direct upload target."""

    def create_multipart_upload(self, *, rel_dir: str, filename: str, content_type: str | None) -> dict[str, str]:
        """Initialize multipart upload and return provider upload id and URI metadata."""

    def sign_multipart_part(
        self,
        *,
        key: str,
        provider_upload_id: str,
        part_number: int,
        expires_seconds: int,
    ) -> dict[str, Any]:
        """Return upload URL metadata for a multipart part."""

    def complete_multipart_upload(self, *, key: str, provider_upload_id: str, parts: list[dict[str, Any]]) -> None:
        """Complete multipart upload with uploaded parts metadata."""

    def abort_multipart_upload(self, *, key: str, provider_upload_id: str) -> None:
        """Abort multipart upload."""


@dataclass(frozen=True)
class LocalStorageBackend:
    media_root: Path
    public_prefix: str = "/media"

    def write_bytes(self, *, rel_dir: str, filename: str, data: bytes, content_type: str | None = None) -> str:
        rel_dir = rel_dir.strip("/") if rel_dir else ""
        target_dir = self.media_root / rel_dir if rel_dir else self.media_root
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / filename
        target_path.write_bytes(data)
        prefix = self.public_prefix.rstrip("/")
        return f"{prefix}/{rel_dir}/{filename}" if rel_dir else f"{prefix}/{filename}"

    def write_file(self, *, rel_dir: str, filename: str, source_path: Path, content_type: str | None = None) -> str:
        rel_dir = rel_dir.strip("/") if rel_dir else ""
        target_dir = self.media_root / rel_dir if rel_dir else self.media_root
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / filename
        if source_path.resolve() != target_path.resolve():
            shutil.copy2(source_path, target_path)
        prefix = self.public_prefix.rstrip("/")
        return f"{prefix}/{rel_dir}/{filename}" if rel_dir else f"{prefix}/{filename}"

    def resolve_local_path(self, uri: str) -> Path:
        if is_remote_uri(uri):
            raise ValueError(f"Cannot resolve remote uri: {uri}")
        uri_path = Path((uri or "").lstrip("/"))
        if uri_path.parts and uri_path.parts[0] == self.public_prefix.strip("/"):
            uri_path = Path(*uri_path.parts[1:])
        return self.media_root / uri_path

    def get_download_url(self, uri: str) -> str | None:
        return uri or None

    def delete_uri(self, uri: str) -> None:
        if not uri:
            return
        path = self.resolve_local_path(uri)
        path.unlink(missing_ok=True)

    def create_presigned_upload(
        self,
        *,
        rel_dir: str,
        filename: str,
        content_type: str | None,
        expires_seconds: int,
    ) -> dict[str, Any]:
        raise ValueError("Direct presigned uploads are not supported for local storage backend.")

    def create_multipart_upload(self, *, rel_dir: str, filename: str, content_type: str | None) -> dict[str, str]:
        raise ValueError("Multipart uploads are not supported for local storage backend.")

    def sign_multipart_part(
        self,
        *,
        key: str,
        provider_upload_id: str,
        part_number: int,
        expires_seconds: int,
    ) -> dict[str, Any]:
        raise ValueError("Multipart uploads are not supported for local storage backend.")

    def complete_multipart_upload(self, *, key: str, provider_upload_id: str, parts: list[dict[str, Any]]) -> None:
        raise ValueError("Multipart uploads are not supported for local storage backend.")

    def abort_multipart_upload(self, *, key: str, provider_upload_id: str) -> None:
        raise ValueError("Multipart uploads are not supported for local storage backend.")


def _truthy_env(name: str) -> bool:
    value = os.getenv(name, os.getenv(f"REFRAME_{name}", "")).strip().lower()
    return value in {"1", "true", "yes", "on"}


def _env(name: str) -> str:
    return os.getenv(f"REFRAME_{name}", os.getenv(name, "")).strip()


def _ensure_boto3():
    try:
        import boto3  # type: ignore
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("boto3 is required for S3 storage. Install with: pip install boto3") from exc
    return boto3


def _join_key(*parts: str) -> str:
    cleaned = [p.strip("/") for p in parts if p and p.strip("/")]
    return "/".join(cleaned)


class S3StorageBackend:
    def __init__(
        self,
        *,
        bucket: str,
        prefix: str = "",
        region: str | None = None,
        endpoint_url: str | None = None,
        public_base_url: str | None = None,
        public_downloads: bool = False,
        presign_expires_seconds: int = 604800,
    ) -> None:
        if not bucket:
            raise ValueError("S3 bucket is required (set REFRAME_S3_BUCKET)")
        self.bucket = bucket
        self.prefix = prefix
        self.public_base_url = public_base_url.rstrip("/") if public_base_url else None
        self.public_downloads = bool(public_downloads)
        self.presign_expires_seconds = max(60, int(presign_expires_seconds))

        boto3 = _ensure_boto3()
        access_key = _env("S3_ACCESS_KEY_ID") or os.getenv("AWS_ACCESS_KEY_ID", "").strip()
        secret_key = _env("S3_SECRET_ACCESS_KEY") or os.getenv("AWS_SECRET_ACCESS_KEY", "").strip()
        session_token = _env("S3_SESSION_TOKEN") or os.getenv("AWS_SESSION_TOKEN", "").strip() or None
        if access_key and secret_key:
            session = boto3.session.Session(aws_access_key_id=access_key, aws_secret_access_key=secret_key, aws_session_token=session_token)
        else:
            session = boto3.session.Session()
        self.client = session.client("s3", region_name=region or None, endpoint_url=endpoint_url or None)

    def _make_key(self, *, rel_dir: str, filename: str) -> str:
        return _join_key(self.prefix, rel_dir, filename)

    def _make_uri(self, *, key: str) -> str:
        return f"s3://{self.bucket}/{key}"

    def _public_url(self, key: str) -> str | None:
        if not self.public_base_url:
            return None
        return f"{self.public_base_url}/{key}"

    def _key_from_uri(self, uri: str) -> str | None:
        if not uri:
            return None
        if uri.startswith("s3://"):
            without_scheme = uri[5:]
            bucket, _, key = without_scheme.partition("/")
            if bucket != self.bucket or not key:
                return None
            return key
        if self.public_base_url and uri.startswith(self.public_base_url):
            remainder = uri[len(self.public_base_url) :].lstrip("/")
            return remainder or None
        return None

    def write_bytes(self, *, rel_dir: str, filename: str, data: bytes, content_type: str | None = None) -> str:
        key = self._make_key(rel_dir=rel_dir, filename=filename)
        kwargs = {"Bucket": self.bucket, "Key": key, "Body": data}
        if content_type:
            kwargs["ContentType"] = content_type
        self.client.put_object(**kwargs)
        return self._make_uri(key=key)

    def write_file(self, *, rel_dir: str, filename: str, source_path: Path, content_type: str | None = None) -> str:
        key = self._make_key(rel_dir=rel_dir, filename=filename)
        extra_args = {"ContentType": content_type} if content_type else None
        if extra_args:
            self.client.upload_file(str(source_path), self.bucket, key, ExtraArgs=extra_args)
        else:
            self.client.upload_file(str(source_path), self.bucket, key)
        return self._make_uri(key=key)

    def resolve_local_path(self, uri: str) -> Path:
        raise ValueError("S3 storage does not support resolving a local path.")

    def get_download_url(self, uri: str) -> str | None:
        key = self._key_from_uri(uri)
        if not key:
            return None
        if self.public_downloads:
            public_url = self._public_url(key)
            if public_url:
                return public_url
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=self.presign_expires_seconds,
        )

    def delete_uri(self, uri: str) -> None:
        key = self._key_from_uri(uri)
        if not key:
            return
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def create_presigned_upload(
        self,
        *,
        rel_dir: str,
        filename: str,
        content_type: str | None,
        expires_seconds: int,
    ) -> dict[str, Any]:
        key = self._make_key(rel_dir=rel_dir, filename=filename)
        params = {"Bucket": self.bucket, "Key": key}
        if content_type:
            params["ContentType"] = content_type
        upload_url = self.client.generate_presigned_url(
            "put_object",
            Params=params,
            ExpiresIn=max(60, int(expires_seconds)),
        )
        headers: dict[str, str] = {}
        if content_type:
            headers["Content-Type"] = content_type
        return {
            "uri": self._make_uri(key=key),
            "upload_url": upload_url,
            "method": "PUT",
            "headers": headers,
            "form_fields": {},
            "expires_in_seconds": max(60, int(expires_seconds)),
        }

    def create_multipart_upload(self, *, rel_dir: str, filename: str, content_type: str | None) -> dict[str, str]:
        key = self._make_key(rel_dir=rel_dir, filename=filename)
        kwargs: dict[str, Any] = {"Bucket": self.bucket, "Key": key}
        if content_type:
            kwargs["ContentType"] = content_type
        result = self.client.create_multipart_upload(**kwargs)
        return {
            "upload_id": str(result["UploadId"]),
            "key": key,
            "uri": self._make_uri(key=key),
        }

    def sign_multipart_part(
        self,
        *,
        key: str,
        provider_upload_id: str,
        part_number: int,
        expires_seconds: int,
    ) -> dict[str, Any]:
        upload_url = self.client.generate_presigned_url(
            "upload_part",
            Params={
                "Bucket": self.bucket,
                "Key": key,
                "UploadId": provider_upload_id,
                "PartNumber": int(part_number),
            },
            ExpiresIn=max(60, int(expires_seconds)),
        )
        return {
            "upload_url": upload_url,
            "method": "PUT",
            "headers": {},
            "expires_in_seconds": max(60, int(expires_seconds)),
        }

    def complete_multipart_upload(self, *, key: str, provider_upload_id: str, parts: list[dict[str, Any]]) -> None:
        normalized_parts: list[dict[str, Any]] = []
        for part in parts:
            etag = str(part.get("etag") or "").strip()
            number = int(part.get("part_number") or 0)
            if number <= 0 or not etag:
                continue
            normalized_parts.append({"ETag": etag, "PartNumber": number})
        if not normalized_parts:
            raise ValueError("No multipart upload parts supplied.")
        normalized_parts.sort(key=lambda p: p["PartNumber"])
        self.client.complete_multipart_upload(
            Bucket=self.bucket,
            Key=key,
            UploadId=provider_upload_id,
            MultipartUpload={"Parts": normalized_parts},
        )

    def abort_multipart_upload(self, *, key: str, provider_upload_id: str) -> None:
        self.client.abort_multipart_upload(
            Bucket=self.bucket,
            Key=key,
            UploadId=provider_upload_id,
        )


def get_storage(*, media_root: str | Path) -> StorageBackend:
    backend = _env("STORAGE_BACKEND").lower() or "local"
    if _truthy_env("OFFLINE_MODE") and backend not in {"local", "filesystem", "fs"}:
        raise RuntimeError("REFRAME_OFFLINE_MODE is enabled; refusing to use remote storage backend.")

    if backend in {"local", "filesystem", "fs"}:
        return LocalStorageBackend(media_root=Path(media_root))

    if backend in {"s3", "r2"}:
        return S3StorageBackend(
            bucket=_env("S3_BUCKET"),
            prefix=_env("S3_PREFIX"),
            region=_env("S3_REGION") or os.getenv("AWS_REGION", "").strip() or os.getenv("AWS_DEFAULT_REGION", "").strip() or None,
            endpoint_url=_env("S3_ENDPOINT_URL") or None,
            public_base_url=_env("S3_PUBLIC_BASE_URL") or None,
            public_downloads=_truthy_env("S3_PUBLIC_DOWNLOADS"),
            presign_expires_seconds=int(_env("S3_PRESIGN_EXPIRES_SECONDS") or 604800),
        )

    raise ValueError(f"Unknown storage backend: {backend}")
