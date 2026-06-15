"""Edge-case coverage for media input path validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from media_core.transcribe import path_guard
from media_core.transcribe.path_guard import (
    _env_roots,
    _normalize_roots,
    validate_media_input_path,
)


def test_normalize_roots_skips_blank_entries(tmp_path):
    # A whitespace-only candidate str-strips to "" and is skipped (empty-value branch);
    # a real path resolves normally so we know the loop kept iterating.
    real = tmp_path / "media"
    roots = _normalize_roots([Path("   "), real])
    assert roots == [real.resolve()]


def test_normalize_roots_skips_unresolvable_paths(monkeypatch):
    # Force resolve() to raise OSError so the except branch is exercised.
    def boom(self, *_args, **_kwargs):
        raise OSError("cannot resolve")

    monkeypatch.setattr(Path, "resolve", boom)
    roots = _normalize_roots([Path("some/path")])
    assert roots == []


def test_env_roots_reads_environment(monkeypatch, tmp_path):
    media_root = tmp_path / "media"
    media_root.mkdir()
    monkeypatch.setenv("REFRAME_MEDIA_ROOT", str(media_root))
    monkeypatch.delenv("MEDIA_ROOT", raising=False)

    roots = _env_roots()
    assert media_root.resolve() in roots


def test_validate_uses_env_roots_when_allowed_roots_none(monkeypatch, tmp_path):
    media_root = tmp_path / "media"
    media_root.mkdir()
    source = media_root / "clip.wav"
    source.write_bytes(b"audio")
    monkeypatch.setenv("REFRAME_MEDIA_ROOT", str(media_root))
    monkeypatch.delenv("MEDIA_ROOT", raising=False)

    # allowed_roots omitted -> _env_roots() branch is taken and accepts the file.
    resolved = validate_media_input_path(source)
    assert resolved == source.resolve()


def test_validate_rejects_file_outside_env_roots(monkeypatch, tmp_path):
    media_root = tmp_path / "media"
    media_root.mkdir()
    outside = tmp_path / "outside.wav"
    outside.write_bytes(b"audio")
    monkeypatch.setenv("REFRAME_MEDIA_ROOT", str(media_root))
    monkeypatch.delenv("MEDIA_ROOT", raising=False)

    with pytest.raises(ValueError, match="outside allowed roots"):
        validate_media_input_path(outside)


def test_validate_raises_file_not_found_for_non_regular(monkeypatch, tmp_path):
    """A resolved path that is neither a regular file nor a directory raises."""
    fake = tmp_path / "special"

    real_resolve = Path.resolve

    def fake_resolve(self, *args, **kwargs):
        # Pretend the target resolves fine (skip the strict=True existence gate).
        if self == fake.expanduser():
            return fake
        return real_resolve(self, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", fake_resolve)
    monkeypatch.setattr(Path, "is_file", lambda self: False)
    monkeypatch.setattr(Path, "is_dir", lambda self: False)

    with pytest.raises(FileNotFoundError):
        validate_media_input_path(fake)


def test_validate_raises_file_not_found_when_missing(tmp_path):
    missing = tmp_path / "nope.wav"
    with pytest.raises(FileNotFoundError):
        # No allowed_roots -> still fails on the strict resolve (FileNotFoundError path).
        validate_media_input_path(missing, allowed_roots=[tmp_path])


def test_env_roots_module_symbol_present():
    # Guard against accidental removal of the helper the CLI relies on.
    assert hasattr(path_guard, "validate_media_input_path")
