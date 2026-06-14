"""Tests for media_studio.handlers — the composition root (the missing wiring).

This is the integration regression guard the reports asked for: it registers
EVERY §2 feature handler and asserts each resolves (no METHOD_NOT_FOUND) and
adapts the wire params (videoId/trackId/id/path) onto the pure functions, matching
the §3 result shapes EXACTLY.

Every heavy seam is mocked: no faster-whisper / scenedetect / verthor / real
ffmpeg / network. The Services is built over a tmp ``data_dir`` and injected with
a fake whisper loader, a fake ffmpeg ``run``/``probe``, a fake provider, and fake
silence/scene detectors.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import pytest

from media_studio import handlers, protocol
from media_studio.handlers import Services
from media_studio.jobs import JobRegistry
from media_studio.protocol import ErrorCode, RpcContext, RpcError


# --------------------------------------------------------------------------- #
# §2 method registry — the EXACT public surface that must be wired.
# --------------------------------------------------------------------------- #
SECTION2_METHODS = [
    "library.list", "library.add", "library.remove",
    "project.open", "project.save", "project.consolidate",
    "transcribe.start",
    "subtitles.generate", "subtitles.edit", "subtitles.translate", "subtitles.export",
    "tracks.list", "tracks.rename", "tracks.relabel", "tracks.add",
    "tracks.remove", "tracks.burn", "tracks.strip",
    "convert.start", "convert.batch",
    "shortmaker.select", "shortmaker.export",
    "settings.get", "settings.set",
]


# --------------------------------------------------------------------------- #
# fakes / seams (no heavy imports, no subprocess, no network)
# --------------------------------------------------------------------------- #
class FakeWhisperModel:
    def transcribe(self, audio: str, **kwargs: Any):
        seg = {
            "start": 0.0,
            "end": 2.0,
            "text": "Hello world.",
            "words": [
                {"word": "Hello", "start": 0.0, "end": 1.0},
                {"word": "world.", "start": 1.0, "end": 2.0},
            ],
        }
        info = {"duration": 2.0, "language": "en"}
        return iter([seg]), info


class FakeWhisperLoader:
    def load(self, model: str, device: str, compute_type: str) -> FakeWhisperModel:
        return FakeWhisperModel()


class FakeProvider:
    """A provider whose chat just upper-cases — exercises translate cue-mapping."""

    def chat(self, messages: List[Dict[str, str]], **kwargs: Any) -> str:
        return messages[-1]["content"].upper()


def fake_run(argv, *, total_sec: float = 0.0, on_progress=None, should_cancel=None) -> int:
    if on_progress is not None:
        on_progress(100.0, "done")
    return 0  # success, no real ffmpeg


def fake_probe(in_path: str, settings=None) -> float:
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
        silence_run=lambda argv, **k: type("C", (), {"stderr": "", "returncode": 0})(),
        scene_detector=lambda p: [],
        provider=FakeProvider(),
        # library probes duration via the default ffmpeg seam; override to a stub
        # so no ffprobe subprocess runs when adding a video.
        library=None,
    )


@pytest.fixture
def ctx(services: Services) -> RpcContext:
    # A real JobRegistry that records emitted progress/done (so jobs run on threads).
    events: List[Any] = []
    jobs = JobRegistry(
        emit_progress=lambda jid, pct, msg: events.append(("progress", jid, pct, msg)),
        emit_done=lambda jid, result: events.append(("done", jid, result)),
    )
    context = RpcContext(emit_notification=lambda obj: None, jobs=jobs)
    context.events = events  # type: ignore[attr-defined]
    return context


def _add_video(services: Services, video_file: Path) -> str:
    """Add a video via the library handler and return its id."""
    # Library.add probes duration via the default ffmpeg seam; stub the prober so
    # no subprocess runs. We reach the library directly with an injected prober.
    from media_studio import library as _library

    services.library = _library.Library(
        services.data_dir / "library.json", probe_duration=lambda _p: 12.0
    )
    video = services.library.add(str(video_file))
    return video["id"]


# --------------------------------------------------------------------------- #
# registration surface
# --------------------------------------------------------------------------- #
def test_register_all_wires_every_section2_method(tmp_path: Path) -> None:
    registered: Dict[str, Any] = {}
    handlers.register_all(
        services=Services(data_dir=tmp_path / "d"),
        register=lambda name, fn: registered.__setitem__(name, fn),
    )
    for method in SECTION2_METHODS:
        assert method in registered, f"{method} was not registered"


def test_no_section2_method_returns_method_not_found(tmp_path: Path) -> None:
    # Build a fresh registry view via register_all onto the real protocol.METHODS
    # (the conftest autouse fixture restores it afterwards).
    svc = handlers.register_all(services=Services(data_dir=tmp_path / "d"))
    for method in SECTION2_METHODS:
        assert method in protocol.METHODS
    assert isinstance(svc, Services)


def test_register_all_wires_the_p4_shorts_methods(tmp_path: Path) -> None:
    """C6: the four shorts.* methods are registered explicitly in register_all."""
    registered: Dict[str, Any] = {}
    handlers.register_all(
        services=Services(data_dir=tmp_path / "d"),
        register=lambda name, fn: registered.__setitem__(name, fn),
    )
    for method in (
        "shorts.list", "shorts.thumbnail", "shorts.delete", "shorts.reexport",
    ):
        assert method in registered, f"{method} was not registered"


def test_shorts_list_bound_to_exports_root_returns_empty(tmp_path: Path) -> None:
    """The registered shorts.list is bound to Services.exports_dir and returns a
    well-formed empty result before any export has run."""
    registered: Dict[str, Any] = {}
    svc = handlers.register_all(
        services=Services(data_dir=tmp_path / "d"),
        register=lambda name, fn: registered.__setitem__(name, fn),
    )
    assert svc.exports_dir == (tmp_path / "d" / "exports")
    ctx = RpcContext(emit_notification=lambda obj: None, jobs=None)
    assert registered["shorts.list"]({}, ctx) == {"shorts": []}


def test_register_all_wires_captions_cues(tmp_path: Path) -> None:
    """C6/C7: captions.cues is registered explicitly in register_all."""
    registered: Dict[str, Any] = {}
    handlers.register_all(
        services=Services(data_dir=tmp_path / "d"),
        register=lambda name, fn: registered.__setitem__(name, fn),
    )
    assert "captions.cues" in registered


def test_captions_cues_bound_to_shortmaker_context(
    services: Services, ctx: RpcContext, video_file: Path
) -> None:
    """The registered captions.cues is bound to Services._shortmaker_context, so a
    transcribed video yields WORD-level cues from its persisted transcript (C7)."""
    registered: Dict[str, Any] = {}
    handlers.register_all(
        services=services,
        register=lambda name, fn: registered.__setitem__(name, fn),
    )
    vid = _add_video(services, video_file)
    _transcribe_sync(services, ctx, vid)
    direct = RpcContext(emit_notification=lambda obj: None, jobs=None)
    out = registered["captions.cues"]({"videoId": vid}, direct)
    # WORD-level: the FakeWhisperModel emits "Hello" + "world." with word timing.
    assert [c["text"] for c in out["cues"]] == ["Hello", "world."]
    assert out["cues"][0] == {"index": 1, "start": 0.0, "end": 1.0, "text": "Hello"}


# --------------------------------------------------------------------------- #
# library.* / project.* / settings.*  (direct-return)
# --------------------------------------------------------------------------- #
def test_library_list_add_remove_roundtrip(services: Services, ctx: RpcContext, video_file: Path) -> None:
    vid = _add_video(services, video_file)
    listed = services.library_list({}, ctx)
    assert "videos" in listed and any(v["id"] == vid for v in listed["videos"])

    added = services.library_add({"path": str(video_file)}, ctx)  # idempotent re-add
    assert "video" in added and added["video"]["id"] == vid  # §3 {video} wrapper

    removed = services.library_remove({"id": vid}, ctx)
    assert removed == {"ok": True}  # §2 {ok:true}


def test_library_add_requires_path(services: Services, ctx: RpcContext) -> None:
    with pytest.raises(RpcError) as ei:
        services.library_add({}, ctx)
    assert ei.value.code == ErrorCode.INVALID_PARAMS


def test_project_open_creates_and_returns_project(services: Services, ctx: RpcContext, video_file: Path) -> None:
    vid = _add_video(services, video_file)
    out = services.project_open({"id": vid}, ctx)
    assert "project" in out  # §3 {project}
    assert out["project"]["video"]["id"] == vid
    assert out["project"]["tracks"] == []


def test_project_consolidate_returns_ok_and_folder(services: Services, ctx: RpcContext, video_file: Path) -> None:
    vid = _add_video(services, video_file)
    out = services.project_consolidate({"id": vid}, ctx)
    assert out["ok"] is True and isinstance(out["folder"], str)  # §2 {ok, folder}


def test_settings_get_set(services: Services, ctx: RpcContext) -> None:
    assert services.settings_get({}, ctx)["useCloud"] is False
    out = services.settings_set({"useCloud": True}, ctx)
    assert out["useCloud"] is True
    assert services.settings_get({}, ctx)["useCloud"] is True


# --------------------------------------------------------------------------- #
# transcribe.start (job) -> persists transcript onto the project
# --------------------------------------------------------------------------- #
def test_transcribe_start_returns_jobid_then_persists_transcript(
    services: Services, ctx: RpcContext, video_file: Path
) -> None:
    vid = _add_video(services, video_file)
    res = services.transcribe_start({"videoId": vid}, ctx)
    assert "jobId" in res and "transcript" not in res  # §2 {jobId} immediate
    ctx.jobs.join(timeout=5)
    done = [e for e in ctx.events if e[0] == "done"]  # type: ignore[attr-defined]
    assert done, "transcribe job never emitted job.done"
    result = done[-1][2]
    assert "transcript" in result  # §2 job.done.result == {transcript}
    assert result["transcript"]["language"] == "en"
    # transcript persisted onto the project + hasTranscript flipped
    assert services.library.get(vid)["hasTranscript"] is True
    project = services.project_open({"id": vid}, ctx)["project"]
    assert project["transcript"]["language"] == "en"


def test_transcribe_start_unknown_video(services: Services, ctx: RpcContext) -> None:
    with pytest.raises(RpcError) as ei:
        services.transcribe_start({"videoId": "ghost"}, ctx)
    assert ei.value.code == ErrorCode.INVALID_PARAMS


# --------------------------------------------------------------------------- #
# subtitles.* (generate/edit/export direct; translate job)
# --------------------------------------------------------------------------- #
def _transcribe_sync(services: Services, ctx: RpcContext, vid: str) -> None:
    services.transcribe_start({"videoId": vid}, ctx)
    ctx.jobs.join(timeout=5)


def test_subtitles_generate_then_edit_then_export(
    services: Services, ctx: RpcContext, video_file: Path, tmp_path: Path
) -> None:
    vid = _add_video(services, video_file)
    _transcribe_sync(services, ctx, vid)

    gen = services.subtitles_generate({"videoId": vid}, ctx)
    assert "track" in gen  # §2 {track}
    track = gen["track"]
    assert track["cues"], "generate produced no cues"
    track_id = track["id"]

    new_cues = [{"index": 1, "start": 0.0, "end": 2.0, "text": "edited"}]
    edited = services.subtitles_edit({"trackId": track_id, "cues": new_cues}, ctx)
    assert edited["track"]["cues"][0]["text"] == "edited"  # §2 {track}

    exported = services.subtitles_export({"trackId": track_id, "format": "srt"}, ctx)
    assert "path" in exported and exported["path"].endswith(".srt")  # §2 {path}
    assert Path(exported["path"]).exists()


def test_subtitles_generate_without_transcript_errors(
    services: Services, ctx: RpcContext, video_file: Path
) -> None:
    vid = _add_video(services, video_file)
    with pytest.raises(RpcError) as ei:
        services.subtitles_generate({"videoId": vid}, ctx)
    assert ei.value.code == ErrorCode.INVALID_PARAMS


def test_subtitles_translate_is_a_job_resolving_to_track(
    services: Services, ctx: RpcContext, video_file: Path
) -> None:
    vid = _add_video(services, video_file)
    _transcribe_sync(services, ctx, vid)
    track_id = services.subtitles_generate({"videoId": vid}, ctx)["track"]["id"]

    res = services.subtitles_translate({"trackId": track_id, "targetLang": "es"}, ctx)
    assert "jobId" in res  # §2 {jobId} immediate
    ctx.jobs.join(timeout=5)
    done = [e for e in ctx.events if e[0] == "done"]  # type: ignore[attr-defined]
    result = done[-1][2]
    assert result["track"]["lang"] == "es"  # §2 job.done.result == {track}
    # provider upper-cased the cue text
    assert result["track"]["cues"][0]["text"] == "HELLO WORLD."


# --------------------------------------------------------------------------- #
# tracks.* (list/rename/relabel/add/remove/strip direct; burn job)
# --------------------------------------------------------------------------- #
def _make_track(services: Services, ctx: RpcContext, video_file: Path) -> tuple[str, str]:
    vid = _add_video(services, video_file)
    _transcribe_sync(services, ctx, vid)
    track_id = services.subtitles_generate({"videoId": vid}, ctx)["track"]["id"]
    return vid, track_id


def test_tracks_list_rename_relabel(services: Services, ctx: RpcContext, video_file: Path) -> None:
    vid, track_id = _make_track(services, ctx, video_file)
    listed = services.tracks_list({"videoId": vid}, ctx)
    assert any(t["id"] == track_id for t in listed["tracks"])  # §2 {tracks}

    renamed = services.tracks_rename({"trackId": track_id, "name": "Mine"}, ctx)
    assert renamed["track"]["name"] == "Mine"  # §2 {track}
    relabel = services.tracks_relabel({"trackId": track_id, "lang": "fr"}, ctx)
    assert relabel["track"]["lang"] == "fr"


def test_tracks_add_remove(services: Services, ctx: RpcContext, video_file: Path) -> None:
    vid, track_id = _make_track(services, ctx, video_file)
    # add the same track (idempotent) -> {ok}
    assert services.tracks_add({"videoId": vid, "trackId": track_id}, ctx) == {"ok": True}
    assert services.tracks_remove({"videoId": vid, "trackId": track_id}, ctx) == {"ok": True}
    # gone now
    listed = services.tracks_list({"videoId": vid}, ctx)
    assert not any(t["id"] == track_id for t in listed["tracks"])


def test_tracks_strip_returns_path(services: Services, ctx: RpcContext, video_file: Path) -> None:
    vid, track_id = _make_track(services, ctx, video_file)
    out = services.tracks_strip({"videoId": vid, "trackId": track_id}, ctx)
    assert "path" in out  # §2 {path}, ran via the fake ffmpeg run (exit 0)


def test_tracks_burn_is_a_job_resolving_to_path(
    services: Services, ctx: RpcContext, video_file: Path
) -> None:
    vid, track_id = _make_track(services, ctx, video_file)
    res = services.tracks_burn({"videoId": vid, "trackId": track_id}, ctx)
    assert "jobId" in res  # §2 {jobId}
    ctx.jobs.join(timeout=5)
    done = [e for e in ctx.events if e[0] == "done"]  # type: ignore[attr-defined]
    assert "path" in done[-1][2]  # §2 job.done.result == {path}


# --------------------------------------------------------------------------- #
# convert.* (both jobs — factory handlers adapted)
# --------------------------------------------------------------------------- #
def test_convert_start_adapts_factory_to_jobid(
    services: Services, ctx: RpcContext, video_file: Path
) -> None:
    vid = _add_video(services, video_file)
    res = services.convert_start({"videoId": vid, "options": {"container": "mkv"}}, ctx)
    assert "jobId" in res  # §2 {jobId} (NOT a factory callable)
    ctx.jobs.join(timeout=5)
    done = [e for e in ctx.events if e[0] == "done"]  # type: ignore[attr-defined]
    assert done[-1][2]["path"].endswith(".mkv")  # §2 job.done.result == {path}


def test_convert_batch_resolves_to_paths(
    services: Services, ctx: RpcContext, video_file: Path
) -> None:
    vid = _add_video(services, video_file)
    res = services.convert_batch(
        {"items": [{"videoId": vid, "options": {"container": "webm"}}]}, ctx
    )
    assert "jobId" in res
    ctx.jobs.join(timeout=5)
    done = [e for e in ctx.events if e[0] == "done"]  # type: ignore[attr-defined]
    assert isinstance(done[-1][2]["paths"], list)  # §2 job.done.result == {paths}


# --------------------------------------------------------------------------- #
# shortmaker.* — selection caching + export candidate resolution (HIGH-3)
# --------------------------------------------------------------------------- #
def test_candidate_id_matches_renderer_format() -> None:
    # ShortMaker.tsx: candidateId(c) = `${c.rank}@${c.sourceStart}`.
    assert Services.candidate_id({"rank": 1, "sourceStart": 12.0}) == "1@12"
    assert Services.candidate_id({"rank": 2, "sourceStart": 12.5}) == "2@12.5"


def test_shortmaker_export_resolves_cached_candidates(
    services: Services, ctx: RpcContext, video_file: Path
) -> None:
    vid = _add_video(services, video_file)
    # Seed the selection cache the way shortmaker.select would.
    cand = {
        "rank": 1, "start": 10.0, "end": 40.0, "durationSec": 30.0,
        "hook": "h", "why": "w", "score": 90, "sourceStart": 10.0,
    }
    services._cache_candidates(vid, [cand])
    cid = Services.candidate_id(cand)  # "1@10"

    # Mock the export stages so no real cut/reframe/caption/ffmpeg runs.
    from media_studio.features import shortmaker as sm

    recorded: List[Any] = []

    def fake_cut(in_path, out_path, start, end, *, settings=None):
        recorded.append(("cut", start, end))
        return out_path

    services._shortmaker = lambda: sm.ShortMaker(  # type: ignore[method-assign]
        load_context=services._shortmaker_context,
        out_dir_for=lambda v: str(services.exports_dir / f"shorts-{v}"),
        stages=sm.Stages(
            select_candidates=lambda *a, **k: [],
            snap_candidates=lambda *a, **k: ([], []),
            cut_clip=fake_cut,
            reframe=lambda i, o, a, *, settings=None: o,
            render_caption=lambda *a, **k: a[2],
            export_clip=lambda i, o, *, settings=None: o,
        ),
        settings_provider=services.settings.get,
    )

    res = services.shortmaker_export({"videoId": vid, "candidateIds": [cid]}, ctx)
    assert "jobId" in res  # §2 {jobId}
    ctx.jobs.join(timeout=5)
    done = [e for e in ctx.events if e[0] == "done"]  # type: ignore[attr-defined]
    result = done[-1][2]
    # The cached candidate resolved -> one real clip exported (§2 {clips:[{path}]}).
    assert "clips" in result and len(result["clips"]) == 1
    assert recorded and recorded[0] == ("cut", 10.0, 40.0)


def test_shortmaker_export_with_no_cache_and_no_inline_yields_no_clips(
    services: Services, ctx: RpcContext, video_file: Path
) -> None:
    vid = _add_video(services, video_file)
    res = services.shortmaker_export({"videoId": vid, "candidateIds": ["9@99"]}, ctx)
    assert "jobId" in res
    ctx.jobs.join(timeout=5)
    done = [e for e in ctx.events if e[0] == "done"]  # type: ignore[attr-defined]
    assert done[-1][2]["clips"] == []  # unknown ids resolve to nothing


def test_shortmaker_select_caches_candidates(
    services: Services, ctx: RpcContext, video_file: Path
) -> None:
    vid = _add_video(services, video_file)
    _transcribe_sync(services, ctx, vid)
    from media_studio.features import shortmaker as sm

    cand = {
        "rank": 1, "start": 5.0, "end": 30.0, "durationSec": 25.0,
        "hook": "hook", "why": "why", "score": 88, "sourceStart": 5.0,
    }
    services._shortmaker = lambda: sm.ShortMaker(  # type: ignore[method-assign]
        load_context=services._shortmaker_context,
        out_dir_for=lambda v: str(services.exports_dir / f"shorts-{v}"),
        stages=sm.Stages(
            select_candidates=lambda *a, **k: [cand],
            snap_candidates=lambda cands, *a, **k: (list(cands), []),
            cut_clip=lambda *a, **k: a[1],
            reframe=lambda i, o, a, *, settings=None: o,
            render_caption=lambda *a, **k: a[2],
            export_clip=lambda i, o, *, settings=None: o,
        ),
        settings_provider=services.settings.get,
    )
    services.shortmaker_select({"videoId": vid, "prompt": "best bits", "controls": {}}, ctx)
    ctx.jobs.join(timeout=5)
    # Candidate cached under its renderer id.
    assert Services.candidate_id(cand) in services._selection_cache.get(vid, {})


def test_shortmaker_select_requires_videoid(services: Services, ctx: RpcContext) -> None:
    with pytest.raises(RpcError) as ei:
        services.shortmaker_select({}, ctx)
    assert ei.value.code == ErrorCode.INVALID_PARAMS
