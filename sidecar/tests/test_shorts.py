"""Tests for features/shorts.py (P4 §2/§3: persisted exports + shorts.* RPCs).

Everything heavy is mocked at the documented seams: the ffmpeg thumbnail extract
is a recording fake (``run`` seam) that writes the output file, the ffprobe dims
sniff is a fabricated value (``probe`` seam), and binaries resolve from a tmp
dir of stub ffmpeg/ffprobe files. No subprocess is ever spawned, no network.

Mirrors the test style of test_media_compat.py / test_feedback.py.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from media_studio import protocol
from media_studio.features import shorts as sh
from media_studio.protocol import RpcContext, RpcError


# --------------------------------------------------------------------------- #
# fixtures + seams
# --------------------------------------------------------------------------- #
@pytest.fixture()
def bin_dir(tmp_path: Path) -> Path:
    """A fake ffmpeg/ffprobe install dir (both plain + .exe for cross-OS)."""
    d = tmp_path / "bin"
    d.mkdir()
    for name in ("ffmpeg", "ffprobe", "ffmpeg.exe", "ffprobe.exe"):
        (d / name).write_text("", encoding="utf-8")
    return d


@pytest.fixture()
def settings(bin_dir: Path) -> dict[str, Any]:
    return {"ffmpegPath": str(bin_dir)}


@pytest.fixture()
def exports_dir(tmp_path: Path) -> Path:
    d = tmp_path / "exports"
    d.mkdir()
    return d


def ctx() -> RpcContext:
    return RpcContext(emit_notification=lambda obj: None, jobs=None)


def make_clip(directory: Path, stem: str, *, meta: dict[str, Any] | None = None) -> Path:
    """Write a fake <stem>.mp4 (+ optional <stem>.mp4.json) into ``directory``."""
    directory.mkdir(parents=True, exist_ok=True)
    clip = directory / f"{stem}.mp4"
    clip.write_bytes(b"\x00fake-mp4")
    if meta is not None:
        sh.metadata_path(clip).write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return clip


class RecordingRun:
    """A drained-run fake: records argv and writes the output (last argv arg)."""

    def __init__(self, code: int = 0, write_output: bool = True) -> None:
        self.code = code
        self.write_output = write_output
        self.calls: list[list[str]] = []

    def __call__(self, argv, *, total_sec: float = 0.0, on_progress=None, should_cancel=None) -> int:
        self.calls.append(list(argv))
        if self.write_output and self.code == 0:
            Path(argv[-1]).write_bytes(b"\xff\xd8jpeg")
        if on_progress is not None:
            on_progress(100.0, "done")
        return self.code


def fake_probe(in_path: str, settings=None) -> tuple[int, int]:
    return 1080, 1920


def service(
    exports_dir: Path,
    *,
    settings: dict[str, Any] | None = None,
    run=None,
    probe=fake_probe,
) -> sh.Shorts:
    return sh.Shorts(
        exports_dir=exports_dir,
        settings_provider=(lambda: settings or {}),
        run=run or RecordingRun(),
        probe=probe,
    )


# --------------------------------------------------------------------------- #
# pure: metadata shaping + sidecar paths
# --------------------------------------------------------------------------- #
def test_build_metadata_normalizes_to_frozen_types():
    meta = sh.build_metadata(
        video_id="v1",
        source_title="My Talk",
        template="hormozi",
        virality_pct="87",  # str coerced to int
        duration_sec=42,  # int coerced to float
        hook="Big claim",
        created_at=123.0,
    )
    assert meta == {
        "videoId": "v1",
        "sourceTitle": "My Talk",
        "template": "hormozi",
        "viralityPct": 87,
        "durationSec": 42.0,
        "hook": "Big claim",
        "createdAt": 123.0,
    }
    assert set(meta) == set(sh.META_FIELDS)


def test_build_metadata_null_virality_stays_none():
    meta = sh.build_metadata(
        video_id="",
        source_title="",
        template="",
        virality_pct=None,
        duration_sec=0.0,
        hook="",
        created_at=1.0,
    )
    assert meta["viralityPct"] is None


def test_build_metadata_bad_virality_becomes_none():
    meta = sh.build_metadata(
        video_id="v",
        source_title="t",
        template="bold",
        virality_pct="NaN",
        duration_sec=1.0,
        hook="h",
        created_at=1.0,
    )
    assert meta["viralityPct"] is None


def test_metadata_and_thumbnail_paths_are_siblings(tmp_path):
    clip = tmp_path / "src-1.mp4"
    assert sh.metadata_path(clip) == tmp_path / "src-1.mp4.json"
    assert sh.thumbnail_path(clip) == tmp_path / "src-1.mp4.thumb.jpg"


def test_short_id_is_stable_and_path_derived(tmp_path):
    clip = tmp_path / "src-1.mp4"
    assert sh.short_id(clip) == sh.short_id(str(clip))
    assert sh.short_id(clip) != sh.short_id(tmp_path / "src-2.mp4")


def test_write_then_read_metadata_round_trips(tmp_path):
    clip = tmp_path / "src-1.mp4"
    meta = sh.build_metadata(
        video_id="v1",
        source_title="T",
        template="neon",
        virality_pct=50,
        duration_sec=30.0,
        hook="hook",
        created_at=9.0,
    )
    json_path = sh.write_export_metadata(clip, meta)
    assert json_path == tmp_path / "src-1.mp4.json"
    assert sh.read_metadata(clip) == meta


def test_read_metadata_absent_is_none(tmp_path):
    assert sh.read_metadata(tmp_path / "missing.mp4") is None


def test_read_metadata_corrupt_is_none(tmp_path):
    clip = tmp_path / "src-1.mp4"
    sh.metadata_path(clip).write_text("{not json", encoding="utf-8")
    assert sh.read_metadata(clip) is None


def test_read_metadata_non_object_is_none(tmp_path):
    clip = tmp_path / "src-1.mp4"
    sh.metadata_path(clip).write_text("[1, 2]", encoding="utf-8")
    assert sh.read_metadata(clip) is None


# --------------------------------------------------------------------------- #
# pure: ShortInfo reconstruction (§3 schema EXACTLY)
# --------------------------------------------------------------------------- #
SHORT_INFO_KEYS = {
    "id",
    "path",
    "videoId",
    "sourceTitle",
    "template",
    "viralityPct",
    "durationSec",
    "width",
    "height",
    "createdAt",
    "thumbnailPath",
    "hook",
}


def test_short_info_has_exactly_the_section3_fields(tmp_path):
    clip = make_clip(tmp_path, "src-1")
    info = sh.short_info(clip, None)
    assert set(info) == SHORT_INFO_KEYS


def test_short_info_from_meta_carries_export_fields(tmp_path):
    meta = sh.build_metadata(
        video_id="v1",
        source_title="My Talk",
        template="hormozi",
        virality_pct=91,
        duration_sec=33.0,
        hook="A hook",
        created_at=100.0,
    )
    clip = make_clip(tmp_path, "src-1", meta=meta)
    info = sh.short_info(clip, sh.read_metadata(clip), width=1080, height=1920)
    assert info["videoId"] == "v1"
    assert info["sourceTitle"] == "My Talk"
    assert info["template"] == "hormozi"
    assert info["viralityPct"] == 91
    assert info["durationSec"] == pytest.approx(33.0)
    assert info["hook"] == "A hook"
    assert info["createdAt"] == pytest.approx(100.0)
    assert info["width"] == 1080 and info["height"] == 1920
    assert info["path"] == str(clip)


def test_short_info_no_meta_defaults_blank_and_uses_mtime(tmp_path):
    clip = make_clip(tmp_path, "src-1")
    info = sh.short_info(clip, None, width=720, height=1280)
    assert info["videoId"] == "" and info["sourceTitle"] == ""
    assert info["template"] == "" and info["hook"] == ""
    assert info["viralityPct"] is None
    assert info["durationSec"] == 0.0
    assert info["width"] == 720 and info["height"] == 1280
    # createdAt falls back to file mtime (a real positive epoch).
    assert info["createdAt"] > 0.0


def test_short_info_thumbnail_path_set_only_when_present(tmp_path):
    clip = make_clip(tmp_path, "src-1")
    assert sh.short_info(clip, None)["thumbnailPath"] == ""
    sh.thumbnail_path(clip).write_bytes(b"\xff\xd8jpeg")
    assert sh.short_info(clip, None)["thumbnailPath"] == str(sh.thumbnail_path(clip))


# --------------------------------------------------------------------------- #
# pure: argv builders
# --------------------------------------------------------------------------- #
def test_thumbnail_argv_extracts_one_frame(settings):
    argv = sh.build_thumbnail_argv("in.mp4", "out.jpg", settings)
    assert argv[0].endswith(("ffmpeg", "ffmpeg.exe"))
    assert "-frames:v" in argv and argv[argv.index("-frames:v") + 1] == "1"
    assert argv[-1] == "out.jpg"
    assert "-progress" in argv and "pipe:1" in argv  # run() can drain stdout


def test_probe_dims_argv_selects_first_video_stream(settings):
    argv = sh.build_probe_dims_argv("in.mp4", settings)
    assert argv[0].endswith(("ffprobe", "ffprobe.exe"))
    assert "-select_streams" in argv and argv[argv.index("-select_streams") + 1] == "v:0"


def test_probe_dims_parses_json(settings):
    def runner(argv, capture_output, text, check):
        return type("C", (), {"returncode": 0, "stdout": '{"streams":[{"width":1080,"height":1920}]}'})()

    assert sh.probe_dims("in.mp4", settings, runner=runner) == (1080, 1920)


def test_probe_dims_returns_zero_on_probe_failure(settings):
    def runner(argv, capture_output, text, check):
        return type("C", (), {"returncode": 1, "stdout": ""})()

    assert sh.probe_dims("in.mp4", settings, runner=runner) == (0, 0)


def test_probe_dims_returns_zero_on_garbled_json(settings):
    def runner(argv, capture_output, text, check):
        return type("C", (), {"returncode": 0, "stdout": "not json"})()

    assert sh.probe_dims("in.mp4", settings, runner=runner) == (0, 0)


# --------------------------------------------------------------------------- #
# shorts.list
# --------------------------------------------------------------------------- #
def test_list_one_video_reads_metadata(exports_dir):
    d = exports_dir / "shorts-v1"
    meta = sh.build_metadata(
        video_id="v1",
        source_title="T",
        template="bold",
        virality_pct=80,
        duration_sec=20.0,
        hook="h",
        created_at=5.0,
    )
    make_clip(d, "src-1", meta=meta)
    svc = service(exports_dir)
    out = svc.list({"videoId": "v1"}, ctx())
    assert len(out["shorts"]) == 1
    assert out["shorts"][0]["videoId"] == "v1"
    assert out["shorts"][0]["template"] == "bold"


def test_list_uses_json_dims_without_probing(exports_dir):
    d = exports_dir / "shorts-v1"
    meta = sh.build_metadata(
        video_id="v1",
        source_title="",
        template="",
        virality_pct=None,
        duration_sec=20.0,
        hook="",
        created_at=5.0,
    )
    meta["width"] = 1080
    meta["height"] = 1920
    make_clip(d, "src-1", meta=meta)
    RecordingRun()  # NOT a probe; use a sentinel that records calls

    def boom_probe(in_path, settings=None):  # must NOT be called
        raise AssertionError("ffprobe should not run when json carries dims")

    svc = service(exports_dir, probe=boom_probe)
    out = svc.list({"videoId": "v1"}, ctx())
    assert out["shorts"][0]["width"] == 1080
    assert out["shorts"][0]["height"] == 1920


def test_list_ffprobe_fallback_when_json_absent(exports_dir):
    d = exports_dir / "shorts-v1"
    make_clip(d, "src-1")  # no .json
    svc = service(exports_dir, probe=fake_probe)
    out = svc.list({"videoId": "v1"}, ctx())
    assert out["shorts"][0]["width"] == 1080  # came from the probe fallback
    assert out["shorts"][0]["height"] == 1920


def test_list_all_videos_scans_every_shorts_dir(exports_dir):
    make_clip(
        exports_dir / "shorts-v1",
        "a",
        meta=sh.build_metadata(
            video_id="v1", source_title="", template="", virality_pct=None, duration_sec=1.0, hook="", created_at=1.0
        ),
    )
    make_clip(
        exports_dir / "shorts-v2",
        "b",
        meta=sh.build_metadata(
            video_id="v2", source_title="", template="", virality_pct=None, duration_sec=1.0, hook="", created_at=2.0
        ),
    )
    svc = service(exports_dir)
    out = svc.list({}, ctx())
    ids = {s["videoId"] for s in out["shorts"]}
    assert ids == {"v1", "v2"}


def test_list_sorts_created_at_desc(exports_dir):
    d = exports_dir / "shorts-v1"
    make_clip(
        d,
        "old",
        meta=sh.build_metadata(
            video_id="v1", source_title="", template="", virality_pct=None, duration_sec=1.0, hook="", created_at=10.0
        ),
    )
    make_clip(
        d,
        "new",
        meta=sh.build_metadata(
            video_id="v1", source_title="", template="", virality_pct=None, duration_sec=1.0, hook="", created_at=99.0
        ),
    )
    svc = service(exports_dir)
    out = svc.list({"videoId": "v1"}, ctx())
    createds = [s["createdAt"] for s in out["shorts"]]
    assert createds == sorted(createds, reverse=True)
    assert createds[0] == pytest.approx(99.0)


def test_list_empty_when_no_exports(exports_dir):
    svc = service(exports_dir)
    assert svc.list({}, ctx()) == {"shorts": []}


def test_list_missing_video_dir_is_empty(exports_dir):
    svc = service(exports_dir)
    assert svc.list({"videoId": "nope"}, ctx()) == {"shorts": []}


def test_list_rejects_non_string_video_id(exports_dir):
    svc = service(exports_dir)
    with pytest.raises(RpcError):
        svc.list({"videoId": 5}, ctx())


# --------------------------------------------------------------------------- #
# shorts.thumbnail
# --------------------------------------------------------------------------- #
def test_thumbnail_extracts_a_frame(exports_dir, settings):
    clip = make_clip(exports_dir / "shorts-v1", "src-1")
    run = RecordingRun()
    svc = service(exports_dir, settings=settings, run=run)
    out = svc.thumbnail({"path": str(clip)}, ctx())
    assert out["thumbnailPath"] == str(sh.thumbnail_path(clip))
    assert sh.thumbnail_path(clip).exists()
    assert len(run.calls) == 1  # ffmpeg invoked once


def test_thumbnail_is_idempotent(exports_dir, settings):
    clip = make_clip(exports_dir / "shorts-v1", "src-1")
    sh.thumbnail_path(clip).write_bytes(b"\xff\xd8existing")
    run = RecordingRun()
    svc = service(exports_dir, settings=settings, run=run)
    out = svc.thumbnail({"path": str(clip)}, ctx())
    assert out["thumbnailPath"] == str(sh.thumbnail_path(clip))
    assert run.calls == []  # cached -> no ffmpeg run


def test_thumbnail_raises_on_ffmpeg_failure(exports_dir, settings):
    clip = make_clip(exports_dir / "shorts-v1", "src-1")
    run = RecordingRun(code=1, write_output=False)
    svc = service(exports_dir, settings=settings, run=run)
    with pytest.raises(RpcError):
        svc.thumbnail({"path": str(clip)}, ctx())


def test_thumbnail_rejects_path_outside_root(exports_dir, settings, tmp_path):
    outside = tmp_path / "evil.mp4"
    outside.write_bytes(b"\x00")
    svc = service(exports_dir, settings=settings)
    with pytest.raises(RpcError):
        svc.thumbnail({"path": str(outside)}, ctx())


def test_thumbnail_rejects_traversal(exports_dir, settings):
    svc = service(exports_dir, settings=settings)
    sneaky = str(exports_dir / "shorts-v1" / ".." / ".." / "secret.mp4")
    with pytest.raises(RpcError):
        svc.thumbnail({"path": sneaky}, ctx())


def test_thumbnail_missing_clip_raises(exports_dir, settings):
    svc = service(exports_dir, settings=settings)
    missing = str(exports_dir / "shorts-v1" / "ghost.mp4")
    with pytest.raises(RpcError):
        svc.thumbnail({"path": missing}, ctx())


def test_thumbnail_requires_path(exports_dir):
    svc = service(exports_dir)
    with pytest.raises(RpcError):
        svc.thumbnail({}, ctx())


# --------------------------------------------------------------------------- #
# shorts.delete
# --------------------------------------------------------------------------- #
def test_delete_removes_mp4_thumb_and_json(exports_dir):
    d = exports_dir / "shorts-v1"
    clip = make_clip(
        d,
        "src-1",
        meta=sh.build_metadata(
            video_id="v1", source_title="", template="", virality_pct=None, duration_sec=1.0, hook="", created_at=1.0
        ),
    )
    sh.thumbnail_path(clip).write_bytes(b"\xff\xd8jpeg")
    svc = service(exports_dir)
    out = svc.delete({"path": str(clip)}, ctx())
    assert out == {"ok": True}
    assert not clip.exists()
    assert not sh.thumbnail_path(clip).exists()
    assert not sh.metadata_path(clip).exists()


def test_delete_is_ok_when_sidecars_absent(exports_dir):
    clip = make_clip(exports_dir / "shorts-v1", "src-1")  # no thumb / json
    svc = service(exports_dir)
    assert svc.delete({"path": str(clip)}, ctx()) == {"ok": True}
    assert not clip.exists()


def test_delete_rejects_path_outside_root(exports_dir, tmp_path):
    outside = tmp_path / "keepme.mp4"
    outside.write_bytes(b"\x00")
    svc = service(exports_dir)
    with pytest.raises(RpcError):
        svc.delete({"path": str(outside)}, ctx())
    assert outside.exists()  # never touched


def test_delete_requires_path(exports_dir):
    svc = service(exports_dir)
    with pytest.raises(RpcError):
        svc.delete({}, ctx())


# --------------------------------------------------------------------------- #
# shorts.reexport
# --------------------------------------------------------------------------- #
def test_reexport_returns_source_video_and_candidate(exports_dir):
    d = exports_dir / "shorts-v1"
    meta = sh.build_metadata(
        video_id="v1",
        source_title="T",
        template="neon",
        virality_pct=70,
        duration_sec=25.0,
        hook="re-open me",
        created_at=1.0,
    )
    clip = make_clip(d, "src-1", meta=meta)
    svc = service(exports_dir)
    out = svc.reexport({"path": str(clip)}, ctx())
    assert out["videoId"] == "v1"
    assert out["candidate"]["hook"] == "re-open me"
    assert out["candidate"]["template"] == "neon"
    assert out["candidate"]["viralityPct"] == 70
    assert out["candidate"]["durationSec"] == pytest.approx(25.0)


def test_reexport_without_meta_returns_blanks(exports_dir):
    clip = make_clip(exports_dir / "shorts-v1", "src-1")  # no .json
    svc = service(exports_dir)
    out = svc.reexport({"path": str(clip)}, ctx())
    assert out["videoId"] == ""
    assert out["candidate"]["hook"] == ""


def test_reexport_rejects_path_outside_root(exports_dir, tmp_path):
    outside = tmp_path / "evil.mp4"
    outside.write_bytes(b"\x00")
    svc = service(exports_dir)
    with pytest.raises(RpcError):
        svc.reexport({"path": str(outside)}, ctx())


def test_reexport_missing_clip_raises(exports_dir):
    svc = service(exports_dir)
    with pytest.raises(RpcError):
        svc.reexport({"path": str(exports_dir / "shorts-v1" / "ghost.mp4")}, ctx())


# --------------------------------------------------------------------------- #
# registration (C6)
# --------------------------------------------------------------------------- #
def test_register_wires_all_four_methods(exports_dir):
    registered: dict[str, Any] = {}
    svc = sh.register(
        exports_dir=exports_dir,
        register_fn=lambda name, fn: registered.__setitem__(name, fn),
    )
    assert set(registered) == {
        "shorts.list",
        "shorts.thumbnail",
        "shorts.delete",
        "shorts.reexport",
    }
    assert registered["shorts.list"] == svc.list
    assert registered["shorts.thumbnail"] == svc.thumbnail
    assert registered["shorts.delete"] == svc.delete
    assert registered["shorts.reexport"] == svc.reexport


def test_register_defaults_to_protocol_register(exports_dir):
    # conftest's autouse fixture snapshots/restores METHODS around this.
    sh.register(exports_dir=exports_dir)
    for name in ("shorts.list", "shorts.thumbnail", "shorts.delete", "shorts.reexport"):
        assert name in protocol.METHODS


# --------------------------------------------------------------------------- #
# probe_dims — empty/non-list streams + non-numeric dims branches
# --------------------------------------------------------------------------- #
def test_probe_dims_zero_when_streams_empty_or_not_a_list(settings):
    def empty_streams(argv, capture_output, text, check):
        return type("C", (), {"returncode": 0, "stdout": '{"streams":[]}'})()

    def non_list_streams(argv, capture_output, text, check):
        return type("C", (), {"returncode": 0, "stdout": '{"streams":"oops"}'})()

    assert sh.probe_dims("in.mp4", settings, runner=empty_streams) == (0, 0)
    assert sh.probe_dims("in.mp4", settings, runner=non_list_streams) == (0, 0)


def test_probe_dims_zero_when_dims_non_numeric(settings):
    def bad_dims(argv, capture_output, text, check):
        return type("C", (), {"returncode": 0, "stdout": '{"streams":[{"width":"x","height":"y"}]}'})()

    assert sh.probe_dims("in.mp4", settings, runner=bad_dims) == (0, 0)


def test_probe_dims_zero_when_first_stream_not_a_dict(settings):
    def non_dict_first(argv, capture_output, text, check):
        # streams[0] is not a dict -> first becomes {} -> width/height 0.
        return type("C", (), {"returncode": 0, "stdout": '{"streams":["junk"]}'})()

    assert sh.probe_dims("in.mp4", settings, runner=non_dict_first) == (0, 0)


# --------------------------------------------------------------------------- #
# short_info — non-numeric createdAt + stat() failure fallbacks
# --------------------------------------------------------------------------- #
def test_short_info_non_numeric_created_at_falls_back_to_mtime(tmp_path):
    clip = make_clip(tmp_path, "src-1")
    # A malformed createdAt in meta -> float() raises -> fall back to mtime.
    info = sh.short_info(clip, {"createdAt": "not-a-number"})
    assert info["createdAt"] > 0.0  # the file's real mtime


def test_short_info_created_at_zero_when_stat_fails(monkeypatch):
    # No real file on disk (path never created) AND meta has no createdAt: the
    # p.stat() fallback raises OSError -> createdAt degrades to 0.0.
    info = sh.short_info("Z:/does/not/exist/ghost.mp4", None)
    assert info["createdAt"] == 0.0


# --------------------------------------------------------------------------- #
# Shorts._settings — a broken settings_provider must never break a listing
# --------------------------------------------------------------------------- #
def test_settings_provider_exception_degrades_to_empty(exports_dir):
    def boom() -> dict[str, Any]:
        raise RuntimeError("settings store down")

    svc = sh.Shorts(exports_dir=exports_dir, settings_provider=boom)
    assert svc._settings() == {}


# --------------------------------------------------------------------------- #
# Shorts._scan_dir — a probe failure during dims fallback is non-fatal
# --------------------------------------------------------------------------- #
def test_scan_dir_probe_failure_degrades_dims_to_zero(exports_dir):
    # A clip with NO .json (so the dims fallback path runs) + a probe that
    # raises -> the ShortInfo is still produced with width/height 0.
    make_clip(exports_dir / "shorts-v1", "src-1")  # no meta -> triggers probe

    def boom_probe(in_path, settings=None):
        raise RuntimeError("ffprobe crashed")

    svc = service(exports_dir, probe=boom_probe)
    result = svc.list({"videoId": "v1"}, ctx())
    assert len(result["shorts"]) == 1
    info = result["shorts"][0]
    assert info["width"] == 0 and info["height"] == 0


# --------------------------------------------------------------------------- #
# write_thumbnail_metadata (WU-C3): records thumbnailFrameSec onto <clip>.json
# --------------------------------------------------------------------------- #
def test_write_thumbnail_metadata_merges_into_existing(exports_dir):
    # An existing .json (export-time fields) is preserved; thumbnailFrameSec added.
    clip = make_clip(
        exports_dir / "shorts-v1",
        "src-1",
        meta={"videoId": "v1", "hook": "keep me", "durationSec": 9.0},
    )
    merged = sh.write_thumbnail_metadata(clip, 7.25)
    assert merged["thumbnailFrameSec"] == 7.25
    assert merged["hook"] == "keep me"  # untouched
    on_disk = sh.read_metadata(clip)
    assert on_disk["thumbnailFrameSec"] == 7.25
    assert on_disk["videoId"] == "v1" and on_disk["durationSec"] == 9.0


def test_write_thumbnail_metadata_creates_record_when_absent(exports_dir):
    # No .json yet -> a minimal record carrying only thumbnailFrameSec is created.
    clip = make_clip(exports_dir / "shorts-v1", "src-2")  # no meta
    assert sh.read_metadata(clip) is None
    merged = sh.write_thumbnail_metadata(clip, 3.0)
    assert merged == {"thumbnailFrameSec": 3.0}
    assert sh.read_metadata(clip) == {"thumbnailFrameSec": 3.0}
