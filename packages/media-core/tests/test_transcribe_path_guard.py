from __future__ import annotations

from pathlib import Path

import pytest

from media_core.transcribe.path_guard import validate_media_input_path


def test_validate_media_input_path_allows_existing_file_in_root(tmp_path: Path):
    media_root = tmp_path / "media"
    media_root.mkdir()
    source = media_root / "sample.wav"
    source.write_bytes(b"audio")

    resolved = validate_media_input_path(source, allowed_roots=[media_root])

    assert resolved == source.resolve()


def test_validate_media_input_path_rejects_outside_allowed_roots(tmp_path: Path):
    media_root = tmp_path / "media"
    media_root.mkdir()
    outside = tmp_path / "outside.wav"
    outside.write_bytes(b"audio")

    with pytest.raises(ValueError):
        validate_media_input_path(outside, allowed_roots=[media_root])


def test_validate_media_input_path_rejects_missing_file(tmp_path: Path):
    missing = tmp_path / "missing.wav"
    with pytest.raises(FileNotFoundError):
        validate_media_input_path(missing, allowed_roots=[tmp_path])


def test_validate_media_input_path_rejects_directory(tmp_path: Path):
    with pytest.raises(IsADirectoryError):
        validate_media_input_path(tmp_path, allowed_roots=[tmp_path])
