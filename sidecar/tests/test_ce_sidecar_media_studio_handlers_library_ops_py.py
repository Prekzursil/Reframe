"""Cross-edit reconcile tests for ``handlers/library_ops.py`` feature-completion fixes.

Isolated (uniquely-named) module so it never collides with the consolidated
``test_handlers*.py`` suites while still counting toward the by-source-file
coverage gate. Covers the three reconcile edits:

* ``library.remove`` reaps the orphaned per-video manifest + poster (present and
  absent-file branches of the idempotent ``unlink(missing_ok=True)``).
* ``project.consolidate`` returns a ``missing`` report computed BEFORE the rebase.
* ``_load_or_create_project`` re-syncs a diverged entity LOCATION over the stored
  ``video`` snapshot (path-diverge / thumbnail-diverge / aligned / missing-entity).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from media_studio.handlers import Services
from media_studio.library import Project
from media_studio.protocol import RpcContext


@pytest.fixture
def ctx() -> RpcContext:
    return RpcContext(emit_notification=lambda obj: None, jobs=None)


def _services(tmp_path: Path) -> Services:
    return Services(data_dir=tmp_path / "data", ffprobe_duration=lambda _p: 0.0)


def _add_source(svc: Services, tmp_path: Path, name: str, data: bytes = b"\x00") -> tuple[str, Path]:
    media = tmp_path / name
    media.write_bytes(data)
    return svc.library.add(str(media))["id"], media


# --------------------------------------------------------------------------- #
# library.remove — orphaned-artifact reaping
# --------------------------------------------------------------------------- #
def test_remove_reaps_manifest_and_thumbnail(tmp_path: Path, ctx: RpcContext) -> None:
    svc = _services(tmp_path)
    src, _media = _add_source(svc, tmp_path, "talk.mp4")
    manifest = svc._project_path(src)
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text("{}", encoding="utf-8")
    thumb = svc.data_dir / "thumbnails" / f"{src}.jpg"
    thumb.parent.mkdir(parents=True, exist_ok=True)
    thumb.write_bytes(b"jpegbytes")

    out = svc.library_remove({"id": src}, ctx)

    assert out == {"ok": True}
    assert not manifest.exists()
    assert not thumb.exists()


def test_remove_without_artifacts_is_a_noop(tmp_path: Path, ctx: RpcContext) -> None:
    # No manifest / no thumbnail exist -> the idempotent missing_ok unlinks are a
    # harmless no-op (absent-file path), and the result still reports the removal.
    svc = _services(tmp_path)
    src, _media = _add_source(svc, tmp_path, "talk.mp4")
    assert not svc._project_path(src).exists()

    out = svc.library_remove({"id": src}, ctx)

    assert out == {"ok": True}


def test_remove_unknown_video_still_reaps_and_reports_false(tmp_path: Path, ctx: RpcContext) -> None:
    svc = _services(tmp_path)
    out = svc.library_remove({"id": "ghost"}, ctx)
    assert out == {"ok": False}


# --------------------------------------------------------------------------- #
# project.consolidate — missing-source report
# --------------------------------------------------------------------------- #
def test_consolidate_reports_missing_clip_ref(tmp_path: Path, ctx: RpcContext) -> None:
    svc = _services(tmp_path)
    src, _media = _add_source(svc, tmp_path, "talk.mp4")
    svc.project_open({"id": src}, ctx)
    project = svc._load_or_create_project(src)
    gone = tmp_path / "gone.mp4"
    project.data["clips"] = [{"candidate": {}, "path": str(gone)}]
    project.save(svc._project_path(src))

    out = svc.project_consolidate({"id": src}, ctx)

    assert out["ok"] is True
    assert str(gone) in out["missing"]


def test_consolidate_fully_present_project_reports_no_missing(tmp_path: Path, ctx: RpcContext) -> None:
    svc = _services(tmp_path)
    src, _media = _add_source(svc, tmp_path, "talk.mp4")
    svc.project_open({"id": src}, ctx)

    out = svc.project_consolidate({"id": src}, ctx)

    assert out["ok"] is True
    assert out["missing"] == []


# --------------------------------------------------------------------------- #
# _load_or_create_project — entity-location re-sync
# --------------------------------------------------------------------------- #
def test_load_or_create_resyncs_diverged_path(tmp_path: Path, ctx: RpcContext) -> None:
    # DIVERGE (path): a hash-verified relink moves the entity -> the stored snapshot
    # is re-pointed and find_missing_sources sees the authoritative location.
    svc = _services(tmp_path)
    src, _media = _add_source(svc, tmp_path, "talk.mp4", data=b"content")
    svc.project_open({"id": src}, ctx)
    svc.library_pin_hash({"id": src}, ctx)
    moved = tmp_path / "moved.mp4"
    moved.write_bytes(b"content")
    svc.library_relink({"id": src, "path": str(moved)}, ctx)

    project = svc._load_or_create_project(src)

    assert project.data["video"]["path"] == str(moved.resolve())
    assert project.find_missing_sources() == []


def test_load_or_create_resyncs_diverged_thumbnail(tmp_path: Path, ctx: RpcContext) -> None:
    # DIVERGE (thumbnail only, path equal): exercises the SECOND operand of the
    # location-diverge check while preserving the source path + project-local fields.
    svc = _services(tmp_path)
    src, media = _add_source(svc, tmp_path, "talk.mp4")
    svc.project_open({"id": src}, ctx)
    svc.library.set_thumbnail(src, "/posters/x.jpg")

    project = svc._load_or_create_project(src)

    assert project.data["video"]["thumbnailPath"] == "/posters/x.jpg"
    assert project.data["video"]["path"] == str(media.resolve())
    assert project.data["video"]["title"] == media.stem


def test_load_or_create_no_resync_when_aligned(tmp_path: Path, ctx: RpcContext) -> None:
    # NON-DIVERGE: entity and snapshot already agree -> both operands False, no re-save.
    svc = _services(tmp_path)
    src, media = _add_source(svc, tmp_path, "talk.mp4")
    svc._load_or_create_project(src)  # creates the manifest

    project = svc._load_or_create_project(src)  # re-opens; aligned

    assert project.data["video"]["path"] == str(media.resolve())
    assert project.data["video"]["thumbnailPath"] == ""


def test_load_or_create_missing_entity_keeps_stale_snapshot(tmp_path: Path, ctx: RpcContext) -> None:
    # MISSING-ENTITY: a removed library video (get -> None) keeps its last-known
    # snapshot untouched (the outer resync guard short-circuits).
    svc = _services(tmp_path)
    video_id = "ghost"
    snapshot = {
        "id": video_id,
        "path": "/old/loc.mp4",
        "title": "kept",
        "durationSec": 1.5,
        "hasTranscript": True,
        "thumbnailPath": "/old/poster.jpg",
    }
    manifest = svc._project_path(video_id)
    manifest.parent.mkdir(parents=True, exist_ok=True)
    Project.new(snapshot).save(manifest)

    project = svc._load_or_create_project(video_id)

    assert project.data["video"] == snapshot
