"""Handler tests for the captions-export RPC surface.

Covers the new wiring added to handlers.Services:
  * subtitles.translate with ``bilingual: true`` -> a NEW stacked track
  * nle.export -> {path, clipCount} (EDL + CSV, fps + reel)
  * package.export -> {path, manifest} (+ path-traversal guard)

Kept separate from test_handlers.py (foundation-owned). Reuses the same seam
style: a tmp-dir Services with a FakeProvider + stub ffmpeg/whisper seams so no
subprocess / heavy dep is touched. The heavy ``models`` package is absent in a
fresh worktree, so these tests call the Services methods directly rather than
through register_all's side-effect imports.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

import pytest
from media_studio import library as _library
from media_studio.features import shorts as _shorts
from media_studio.handlers import Services
from media_studio.jobs import JobRegistry
from media_studio.protocol import ErrorCode, RpcContext, RpcError


# --------------------------------------------------------------------------- #
# seams + fixtures (mirror test_handlers.py)
# --------------------------------------------------------------------------- #
class FakeWhisperModel:
    def transcribe(self, audio: str, **_k: Any) -> tuple[Any, dict[str, Any]]:
        seg = {
            "start": 0.0,
            "end": 2.0,
            "text": "Hello world.",
            "words": [
                {"word": "Hello", "start": 0.0, "end": 1.0},
                {"word": "world.", "start": 1.0, "end": 2.0},
            ],
        }
        return iter([seg]), {"duration": 2.0, "language": "en"}


class FakeWhisperLoader:
    def load(self, model: str, device: str, compute_type: str) -> FakeWhisperModel:
        return FakeWhisperModel()


class FakeProvider:
    """Translation seam: upper-cases the line (so output != input is observable)."""

    def chat(self, messages: list[dict[str, str]], **_k: Any) -> str:
        return str(messages[-1]["content"]).upper()


def fake_run(*_a: Any, **_k: Any) -> int:
    return 0


def fake_probe(*_a: Any, **_k: Any) -> float:
    return 12.0


@pytest.fixture
def video_file(tmp_path: Path) -> Path:
    p = tmp_path / "talk.mp4"
    p.write_bytes(b"\x00fake")
    return p


@pytest.fixture
def services(tmp_path: Path) -> Services:
    return Services(
        data_dir=tmp_path / "data",
        whisper_loader=FakeWhisperLoader(),
        ffmpeg_run=fake_run,
        ffprobe_duration=fake_probe,
        provider=FakeProvider(),
    )


@pytest.fixture
def ctx(services: Services) -> RpcContext:
    events: list[Any] = []
    jobs = JobRegistry(
        emit_progress=lambda jid, pct, msg: events.append(("progress", jid, pct, msg)),
        emit_done=lambda jid, result: events.append(("done", jid, result)),
    )
    context = RpcContext(emit_notification=lambda obj: None, jobs=jobs)
    context.events = events  # type: ignore[attr-defined]
    return context


def _add_video(services: Services, video_file: Path) -> str:
    services.library = _library.Library(services.data_dir / "library.json", probe_duration=lambda _p: 12.0)
    return services.library.add(str(video_file))["id"]


def _make_track(services: Services, ctx: RpcContext, video_file: Path) -> tuple[str, str]:
    vid = _add_video(services, video_file)
    services.transcribe_start({"videoId": vid}, ctx)
    ctx.jobs.join(timeout=5)
    track_id = services.subtitles_generate({"videoId": vid}, ctx)["track"]["id"]
    return vid, track_id


# --------------------------------------------------------------------------- #
# subtitles.translate bilingual
# --------------------------------------------------------------------------- #
def test_translate_bilingual_adds_stacked_track(services: Services, ctx: RpcContext, video_file: Path) -> None:
    vid, track_id = _make_track(services, ctx, video_file)
    res = services.subtitles_translate({"trackId": track_id, "targetLang": "es", "bilingual": True}, ctx)
    assert "jobId" in res
    ctx.jobs.join(timeout=5)
    done = [e for e in ctx.events if e[0] == "done"]  # type: ignore[attr-defined]
    track = done[-1][2]["track"]
    assert track["lang"] == "en+es"  # bilingual marker
    # Original on top, translation (upper-cased by FakeProvider) below.
    assert track["cues"][0]["text"] == "Hello world.\nHELLO WORLD."
    # Source track is preserved + the stacked track was added (2 tracks now).
    project = services._load_or_create_project(vid)
    assert len(project.data["tracks"]) == 2


def test_translate_bilingual_translation_first_order(services: Services, ctx: RpcContext, video_file: Path) -> None:
    _vid, track_id = _make_track(services, ctx, video_file)
    services.subtitles_translate(
        {"trackId": track_id, "targetLang": "es", "bilingual": True, "order": "translation-first"}, ctx
    )
    ctx.jobs.join(timeout=5)
    done = [e for e in ctx.events if e[0] == "done"]  # type: ignore[attr-defined]
    track = done[-1][2]["track"]
    assert track["cues"][0]["text"] == "HELLO WORLD.\nHello world."


def test_translate_monolingual_still_replaces_in_place(services: Services, ctx: RpcContext, video_file: Path) -> None:
    vid, track_id = _make_track(services, ctx, video_file)
    services.subtitles_translate({"trackId": track_id, "targetLang": "es"}, ctx)
    ctx.jobs.join(timeout=5)
    project = services._load_or_create_project(vid)
    assert len(project.data["tracks"]) == 1  # replaced, not added
    assert project.data["tracks"][0]["lang"] == "es"


# --------------------------------------------------------------------------- #
# nle.export
# --------------------------------------------------------------------------- #
def _seed_clips(services: Services, vid: str) -> None:
    """Persist two approved clips onto the video's project manifest."""
    project = services._load_or_create_project(vid)
    project.data["clips"] = [
        {"candidate": {"rank": 1, "sourceStart": 10.0, "end": 25.0, "hook": "Hook one"}, "path": "/f/a.mp4"},
        {
            "candidate": {"rank": 2, "sourceStart": 40.0, "end": 52.0, "hook": "Hook two", "reel": "tape-02"},
            "path": "/f/b.mp4",
        },
    ]
    project.save()


def test_nle_export_edl_from_project_clips(services: Services, ctx: RpcContext, video_file: Path) -> None:
    vid = _add_video(services, video_file)
    _seed_clips(services, vid)
    res = services.nle_export({"videoId": vid, "format": "edl", "fps": 30}, ctx)
    assert res["clipCount"] == 2
    assert res["path"].endswith(".edl")
    body = Path(res["path"]).read_text(encoding="utf-8")
    assert "TITLE:" in body and "TAPE02" in body


def test_nle_export_csv_with_explicit_clips(services: Services, ctx: RpcContext, video_file: Path) -> None:
    vid = _add_video(services, video_file)
    clips = [{"candidate": {"rank": 1, "sourceStart": 0.0, "end": 5.0, "hook": "h"}, "path": "/f/x.mp4"}]
    res = services.nle_export({"videoId": vid, "format": "csv", "fps": 25, "clips": clips}, ctx)
    assert res["clipCount"] == 1
    assert res["path"].endswith(".csv")
    assert Path(res["path"]).read_text(encoding="utf-8").startswith("index,")


def test_nle_export_default_fps_and_title(services: Services, ctx: RpcContext, video_file: Path) -> None:
    vid = _add_video(services, video_file)
    _seed_clips(services, vid)
    res = services.nle_export({"videoId": vid}, ctx)  # defaults: edl, 30fps
    body = Path(res["path"]).read_text(encoding="utf-8")
    assert body.startswith("TITLE: talk")  # video title used as sequence title


def test_nle_export_rejects_bad_format(services: Services, ctx: RpcContext, video_file: Path) -> None:
    vid = _add_video(services, video_file)
    _seed_clips(services, vid)
    with pytest.raises(RpcError) as ei:
        services.nle_export({"videoId": vid, "format": "xml"}, ctx)
    assert ei.value.code == ErrorCode.INVALID_PARAMS


def test_nle_export_requires_videoid(services: Services, ctx: RpcContext) -> None:
    with pytest.raises(RpcError):
        services.nle_export({}, ctx)


# --------------------------------------------------------------------------- #
# package.export
# --------------------------------------------------------------------------- #
def _seed_short(services: Services, vid: str) -> Path:
    """Write a fake exported clip (+ meta + thumb) inside the exports root."""
    out = services.exports_dir / f"shorts-{vid}"
    out.mkdir(parents=True, exist_ok=True)
    clip = out / "clip.mp4"
    clip.write_bytes(b"\x00mp4")
    _shorts.write_export_metadata(
        clip,
        {
            "videoId": vid,
            "sourceTitle": "Talk",
            "template": "karaoke",
            "viralityPct": 80,
            "durationSec": 12.0,
            "hook": "Wow amazing trick",
        },
    )
    _shorts.thumbnail_path(clip).write_bytes(b"\xff\xd8jpg")
    return clip


def test_package_export_bundles_zip(services: Services, ctx: RpcContext, video_file: Path) -> None:
    vid = _add_video(services, video_file)
    clip = _seed_short(services, vid)
    res = services.package_export({"path": str(clip)}, ctx)
    assert res["path"].endswith(".package.zip")
    with zipfile.ZipFile(res["path"]) as zf:
        names = set(zf.namelist())
        assert names == {"short.mp4", "thumbnail.jpg", "upload.json"}
        manifest = json.loads(zf.read("upload.json"))
    assert manifest["title"] == "Wow amazing trick"
    assert manifest["source"]["videoId"] == vid
    assert "amazing" in manifest["tags"]


def test_package_export_override_suggestion(services: Services, ctx: RpcContext, video_file: Path) -> None:
    vid = _add_video(services, video_file)
    clip = _seed_short(services, vid)
    res = services.package_export({"path": str(clip), "suggestion": {"title": "Custom Title"}}, ctx)
    assert res["manifest"]["title"] == "Custom Title"


def test_package_export_path_traversal_guard(services: Services, ctx: RpcContext, tmp_path: Path) -> None:
    outside = tmp_path / "secret.txt"
    outside.write_text("nope")
    with pytest.raises(RpcError) as ei:
        services.package_export({"path": str(outside)}, ctx)
    assert ei.value.code == ErrorCode.INVALID_PARAMS


def test_package_export_missing_clip(services: Services, ctx: RpcContext) -> None:
    missing = services.exports_dir / "shorts-x" / "nope.mp4"
    with pytest.raises(RpcError):
        services.package_export({"path": str(missing)}, ctx)


def test_package_export_requires_path(services: Services, ctx: RpcContext) -> None:
    with pytest.raises(RpcError):
        services.package_export({}, ctx)
