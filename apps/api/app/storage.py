from __future__ import annotations

from dataclasses import dataclass
import os
import shutil
from pathlib import Path
from typing import Optional, Protocol


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
        presign_expires_seconds: int = 604800,
    ) -> None:
        if not bucket:
            raise ValueError("S3 bucket is required (set REFRAME_S3_BUCKET)")
        self.bucket = bucket
        self.prefix = prefix
        self.public_base_url = public_base_url.rstrip("/") if public_base_url else None
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
        if self.public_base_url:
            return f"{self.public_base_url}/{key}"
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=self.presign_expires_seconds,
        )

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
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=self.presign_expires_seconds,
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
            presign_expires_seconds=int(_env("S3_PRESIGN_EXPIRES_SECONDS") or 604800),
        )

    raise ValueError(f"Unknown storage backend: {backend}")
