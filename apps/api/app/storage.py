from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Protocol


def is_remote_uri(uri: str) -> bool:
    lowered = (uri or "").strip().lower()
    return lowered.startswith(("http://", "https://", "s3://", "gs://"))


class StorageBackend(Protocol):
    def write_bytes(self, *, rel_dir: str, filename: str, data: bytes) -> str:
        """Store bytes and return a URI suitable for clients."""

    def resolve_local_path(self, uri: str) -> Path:
        """Resolve a local filesystem path for a non-remote URI."""


@dataclass(frozen=True)
class LocalStorageBackend:
    media_root: Path
    public_prefix: str = "/media"

    def write_bytes(self, *, rel_dir: str, filename: str, data: bytes) -> str:
        rel_dir = rel_dir.strip("/") if rel_dir else ""
        target_dir = self.media_root / rel_dir if rel_dir else self.media_root
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / filename
        target_path.write_bytes(data)
        prefix = self.public_prefix.rstrip("/")
        return f"{prefix}/{rel_dir}/{filename}" if rel_dir else f"{prefix}/{filename}"

    def resolve_local_path(self, uri: str) -> Path:
        if is_remote_uri(uri):
            raise ValueError(f"Cannot resolve remote uri: {uri}")
        uri_path = Path((uri or "").lstrip("/"))
        if uri_path.parts and uri_path.parts[0] == self.public_prefix.strip("/"):
            uri_path = Path(*uri_path.parts[1:])
        return self.media_root / uri_path


def get_storage(*, media_root: str | Path) -> StorageBackend:
    return LocalStorageBackend(media_root=Path(media_root))

