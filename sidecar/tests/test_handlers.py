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
from typing import Any

import pytest
from media_studio import handlers, protocol
from media_studio.handlers import Services
from media_studio.jobs import JobRegistry
from media_studio.protocol import ErrorCode, RpcContext, RpcError

# --------------------------------------------------------------------------- #
# §2 method registry — the EXACT public surface that must be wired.
# --------------------------------------------------------------------------- #
SECTION2_METHODS = [
    "library.list",
    "library.add",
    "library.remove",
    "project.open",
    "project.save",
    "project.consolidate",
    "transcribe.start",
    "subtitles.generate",
    "subtitles.edit",
    "subtitles.translate",
    "subtitles.export",
    "tracks.list",
    "tracks.rename",
    "tracks.relabel",
    "tracks.add",
    "tracks.remove",
    "tracks.burn",
    "tracks.strip",
    "convert.start",
    "convert.batch",
    "shortmaker.select",
    "shortmaker.export",
    "settings.get",
    "settings.set",
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

    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
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
    events: list[Any] = []
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

    services.library = _library.Library(services.data_dir / "library.json", probe_duration=lambda _p: 12.0)
    video = services.library.add(str(video_file))
    return video["id"]


# --------------------------------------------------------------------------- #
# registration surface
# --------------------------------------------------------------------------- #
def test_register_all_wires_every_section2_method(tmp_path: Path) -> None:
    registered: dict[str, Any] = {}
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
    registered: dict[str, Any] = {}
    handlers.register_all(
        services=Services(data_dir=tmp_path / "d"),
        register=lambda name, fn: registered.__setitem__(name, fn),
    )
    for method in (
        "shorts.list",
        "shorts.thumbnail",
        "shorts.delete",
        "shorts.reexport",
    ):
        assert method in registered, f"{method} was not registered"


def test_shorts_list_bound_to_exports_root_returns_empty(tmp_path: Path) -> None:
    """The registered shorts.list is bound to Services.exports_dir and returns a
    well-formed empty result before any export has run."""
    registered: dict[str, Any] = {}
    svc = handlers.register_all(
        services=Services(data_dir=tmp_path / "d"),
        register=lambda name, fn: registered.__setitem__(name, fn),
    )
    assert svc.exports_dir == (tmp_path / "d" / "exports")
    ctx = RpcContext(emit_notification=lambda obj: None, jobs=None)
    assert registered["shorts.list"]({}, ctx) == {"shorts": []}


def test_register_all_wires_captions_cues(tmp_path: Path) -> None:
    """C6/C7: captions.cues is registered explicitly in register_all."""
    registered: dict[str, Any] = {}
    handlers.register_all(
        services=Services(data_dir=tmp_path / "d"),
        register=lambda name, fn: registered.__setitem__(name, fn),
    )
    assert "captions.cues" in registered


def test_register_all_wires_audio_stabilize_group(tmp_path: Path) -> None:
    """audio-stabilize group: stabilize.run + audiomix.* + silence.trim wired."""
    registered: dict[str, Any] = {}
    handlers.register_all(
        services=Services(data_dir=tmp_path / "d"),
        register=lambda name, fn: registered.__setitem__(name, fn),
    )
    for method in (
        "stabilize.run",
        "audiomix.merge",
        "audiomix.normalize",
        "silence.trim",
    ):
        assert method in registered, f"{method} was not registered"


def test_captions_cues_bound_to_shortmaker_context(services: Services, ctx: RpcContext, video_file: Path) -> None:
    """The registered captions.cues is bound to Services._shortmaker_context, so a
    transcribed video yields WORD-level cues from its persisted transcript (C7)."""
    registered: dict[str, Any] = {}
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


def test_captions_cues_empty_before_transcribe_nonempty_after(
    services: Services, ctx: RpcContext, video_file: Path
) -> None:
    """G1 caption-PERSIST regression (the latent 2nd subtitle bug).

    captions.cues is non-empty ONLY because the transcribe job PERSISTS the ASR
    transcript onto the project manifest that ``_shortmaker_context`` reads. This
    locks the cause->effect: a video that was added but NOT transcribed yields
    ``{"cues": []}`` (no persisted transcript), and the SAME video yields
    word-level cues immediately after a transcribe run persists onto the manifest
    ``_shortmaker_context`` loads. If persistence ever regresses (e.g. the job
    saves to a different path than _shortmaker_context reads), the second
    assertion fails — the overlay would silently show no captions even though the
    video plays.
    """
    registered: dict[str, Any] = {}
    handlers.register_all(
        services=services,
        register=lambda name, fn: registered.__setitem__(name, fn),
    )
    vid = _add_video(services, video_file)
    direct = RpcContext(emit_notification=lambda obj: None, jobs=None)

    # No transcript persisted yet -> the context loader finds none -> empty cues.
    before = registered["captions.cues"]({"videoId": vid}, direct)
    assert before == {"cues": []}
    # _shortmaker_context itself reports no transcript on the fresh manifest.
    assert services._shortmaker_context(vid)["transcript"] is None

    # Transcribe -> the job persists the transcript onto the project manifest.
    _transcribe_sync(services, ctx, vid)

    # The SAME context loader now finds the persisted transcript -> non-empty cues.
    assert services._shortmaker_context(vid)["transcript"] is not None
    after = registered["captions.cues"]({"videoId": vid}, direct)
    assert after["cues"], "captions.cues empty AFTER transcribe -> transcript not persisted"
    assert [c["text"] for c in after["cues"]] == ["Hello", "world."]


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


def test_subtitles_generate_without_transcript_errors(services: Services, ctx: RpcContext, video_file: Path) -> None:
    vid = _add_video(services, video_file)
    with pytest.raises(RpcError) as ei:
        services.subtitles_generate({"videoId": vid}, ctx)
    assert ei.value.code == ErrorCode.INVALID_PARAMS


# --------------------------------------------------------------------------- #
# Phase-8 wiring: caption polish / ctc karaoke / parakeet ASR / pyannote diarize
# --------------------------------------------------------------------------- #
def test_subtitles_generate_uses_polish_when_setting_enabled(
    services: Services, ctx: RpcContext, video_file: Path
) -> None:
    """WU9 wiring: settings['captionPolish'] routes through generate_polished
    (the degrade-safe Netflix CPS/CPL gate runs with no model backends)."""
    vid = _add_video(services, video_file)
    _transcribe_sync(services, ctx, vid)
    services.settings.set({"captionPolish": True})
    gen = services.subtitles_generate({"videoId": vid}, ctx)
    assert gen["track"]["cues"], "polished generate produced no cues"
    # the captions text survives the polish gate
    assert "Hello world." in " ".join(c["text"] for c in gen["track"]["cues"])


def test_transcribe_start_karaoke_runs_ctc_align(
    services: Services, ctx: RpcContext, video_file: Path, monkeypatch
) -> None:
    """WU6 wiring: settings['karaoke'] runs the ctc-forced-aligner 2nd pass on the
    transcript tail (mocked seam — no torch/aligner)."""
    from media_studio.features import ctc_align

    called: dict[str, Any] = {}

    def fake_align(transcript, audio_path, *, settings=None, **kwargs):
        called["audio"] = audio_path
        return {**transcript, "aligned": True}

    monkeypatch.setattr(ctc_align, "align_words", fake_align)
    vid = _add_video(services, video_file)
    services.settings.set({"karaoke": True})
    services.transcribe_start({"videoId": vid}, ctx)
    ctx.jobs.join(timeout=5)
    done = [e for e in ctx.events if e[0] == "done"]  # type: ignore[attr-defined]
    assert done[-1][2]["transcript"]["aligned"] is True
    assert called["audio"]


def test_transcribe_start_parakeet_engine_falls_back_to_whisper_offline(
    services: Services, ctx: RpcContext, video_file: Path
) -> None:
    """WU7 wiring: settings['asrEngine']='parakeet' is selected, but offline +
    no weights degrades parakeet to empty -> whisper fallback still transcribes."""
    vid = _add_video(services, video_file)
    services.settings.set({"asrEngine": "parakeet", "offline": True})
    services.transcribe_start({"videoId": vid}, ctx)
    ctx.jobs.join(timeout=5)
    done = [e for e in ctx.events if e[0] == "done"]  # type: ignore[attr-defined]
    transcript = done[-1][2]["transcript"]
    # whisper fallback produced the english transcript
    assert transcript["language"] == "en"
    assert transcript["segments"]


def test_maybe_align_words_noop_when_karaoke_off(services: Services) -> None:
    t = {"language": "en", "segments": [], "durationSec": 0.0}
    assert services._maybe_align_words(t, "/x.mp4", {}) is t


def test_register_all_wires_diarize_backend_selector(tmp_path: Path) -> None:
    """Phase-8: diarize.start is registered with the pyannote-aware selector seams."""
    registered: dict[str, Any] = {}
    svc = handlers.register_all(
        services=Services(data_dir=tmp_path / "d"),
        register=lambda name, fn: registered.__setitem__(name, fn),
    )
    assert "diarize.start" in registered
    assert isinstance(svc, Services)


def test_diarize_backend_factory_speechbrain_default(services: Services, monkeypatch) -> None:
    """The default (no setting) builds the SpeechBrain backend via its factory."""
    from media_studio.features import diarize as _diarize

    sentinel = object()
    monkeypatch.setattr(_diarize, "_default_backend_factory", lambda s: sentinel)
    assert services._diarize_backend_factory({}) is sentinel


def test_diarize_backend_factory_pyannote_requires_token(services: Services, monkeypatch) -> None:
    """Selecting pyannote validates the env HF token eagerly (typed refusal)."""
    from media_studio.features import pyannote_backend as _pyannote

    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("HUGGING_FACE_HUB_TOKEN", raising=False)
    with pytest.raises(_pyannote.PyannoteConfigError):
        services._diarize_backend_factory({"diarizeBackend": "pyannote"})


def test_diarize_models_present_routes_by_backend(services: Services, monkeypatch) -> None:
    from media_studio.features import diarize as _diarize
    from media_studio.features import pyannote_backend as _pyannote

    monkeypatch.setattr(_diarize, "default_models_present", lambda s: "speechbrain-probe")
    monkeypatch.setattr(_pyannote, "default_models_present", lambda s: "pyannote-probe")
    assert services._diarize_models_present({}) == "speechbrain-probe"
    assert services._diarize_models_present({"diarizeBackend": "pyannote"}) == "pyannote-probe"


def test_subtitles_translate_is_a_job_resolving_to_track(services: Services, ctx: RpcContext, video_file: Path) -> None:
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


def test_tracks_burn_is_a_job_resolving_to_path(services: Services, ctx: RpcContext, video_file: Path) -> None:
    vid, track_id = _make_track(services, ctx, video_file)
    res = services.tracks_burn({"videoId": vid, "trackId": track_id}, ctx)
    assert "jobId" in res  # §2 {jobId}
    ctx.jobs.join(timeout=5)
    done = [e for e in ctx.events if e[0] == "done"]  # type: ignore[attr-defined]
    assert "path" in done[-1][2]  # §2 job.done.result == {path}


# --------------------------------------------------------------------------- #
# convert.* (both jobs — factory handlers adapted)
# --------------------------------------------------------------------------- #
def test_convert_start_adapts_factory_to_jobid(services: Services, ctx: RpcContext, video_file: Path) -> None:
    vid = _add_video(services, video_file)
    res = services.convert_start({"videoId": vid, "options": {"container": "mkv"}}, ctx)
    assert "jobId" in res  # §2 {jobId} (NOT a factory callable)
    ctx.jobs.join(timeout=5)
    done = [e for e in ctx.events if e[0] == "done"]  # type: ignore[attr-defined]
    assert done[-1][2]["path"].endswith(".mkv")  # §2 job.done.result == {path}


def test_convert_batch_resolves_to_paths(services: Services, ctx: RpcContext, video_file: Path) -> None:
    vid = _add_video(services, video_file)
    res = services.convert_batch({"items": [{"videoId": vid, "options": {"container": "webm"}}]}, ctx)
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


def test_shortmaker_export_resolves_cached_candidates(services: Services, ctx: RpcContext, video_file: Path) -> None:
    vid = _add_video(services, video_file)
    # Seed the selection cache the way shortmaker.select would.
    cand = {
        "rank": 1,
        "start": 10.0,
        "end": 40.0,
        "durationSec": 30.0,
        "hook": "h",
        "why": "w",
        "score": 90,
        "sourceStart": 10.0,
    }
    services._cache_candidates(vid, [cand])
    cid = Services.candidate_id(cand)  # "1@10"

    # Mock the export stages so no real cut/reframe/caption/ffmpeg runs.
    from media_studio.features import shortmaker as sm

    recorded: list[Any] = []

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
            # stabilize is DEFAULT-ON in the reframe path; stub it so no real
            # vidstab/ffmpeg runs (warp-only pass-through for this handler test).
            stabilize=lambda i, o, *, settings=None, on_notice=None: i,
            reframe=lambda i, o, a, *, settings=None, on_notice=None: o,
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


def test_shortmaker_select_caches_candidates(services: Services, ctx: RpcContext, video_file: Path) -> None:
    vid = _add_video(services, video_file)
    _transcribe_sync(services, ctx, vid)
    from media_studio.features import shortmaker as sm

    cand = {
        "rank": 1,
        "start": 5.0,
        "end": 30.0,
        "durationSec": 25.0,
        "hook": "hook",
        "why": "why",
        "score": 88,
        "sourceStart": 5.0,
    }
    services._shortmaker = lambda: sm.ShortMaker(  # type: ignore[method-assign]
        load_context=services._shortmaker_context,
        out_dir_for=lambda v: str(services.exports_dir / f"shorts-{v}"),
        stages=sm.Stages(
            select_candidates=lambda *a, **k: [cand],
            snap_candidates=lambda cands, *a, **k: (list(cands), []),
            cut_clip=lambda *a, **k: a[1],
            reframe=lambda i, o, a, *, settings=None, on_notice=None: o,
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


# --------------------------------------------------------------------------- #
# WU-5: refine.* + diarize.rename registration + subtitles speaker gate
# --------------------------------------------------------------------------- #
def test_register_all_wires_refine_and_rename(tmp_path: Path) -> None:
    """WU-5 acceptance 1: register_all wires refine.preview, refine.apply, and
    diarize.rename exactly once, and leaves every pre-existing §2 name in place."""
    registered: dict[str, Any] = {}
    handlers.register_all(
        services=Services(data_dir=tmp_path / "d"),
        register=lambda name, fn: registered.__setitem__(name, fn),
    )
    for method in ("refine.preview", "refine.apply", "diarize.rename"):
        assert method in registered, f"{method} was not registered"
    # no displacement of the existing surface
    for method in SECTION2_METHODS:
        assert method in registered, f"{method} disappeared after WU-5 wiring"


def test_refine_apply_is_job_preview_is_direct(
    services: Services, ctx: RpcContext, video_file: Path, monkeypatch
) -> None:
    """WU-5 acceptance 3: refine.apply runs as a job (needs ctx.jobs), refine.preview
    is a direct handler (works with no job registry)."""
    from media_studio.features import refine as _refine
    from media_studio.features import silencetrim as _silencetrim

    monkeypatch.setattr(_silencetrim, "detect_silence_spans", lambda *a, **k: [])
    registered: dict[str, Any] = {}
    handlers.register_all(services=services, register=lambda name, fn: registered.__setitem__(name, fn))
    vid = _add_video(services, video_file)
    _transcribe_sync(services, ctx, vid)

    # preview: direct (no job registry) returns {plan} immediately.
    direct = RpcContext(emit_notification=lambda obj: None, jobs=None)
    out = registered["refine.preview"]({"videoId": vid}, direct)
    assert "plan" in out and "keeps" in out["plan"]

    # apply: a job (returns {jobId}) over the real registry.
    monkeypatch.setattr(_refine, "_default_run", lambda: fake_run)
    res = registered["refine.apply"]({"videoId": vid}, ctx)
    assert "jobId" in res
    ctx.jobs.join(timeout=5)


def test_refine_fillerSets_setting_reaches_plan_refine(
    services: Services, ctx: RpcContext, video_file: Path, monkeypatch
) -> None:
    """WU-5 acceptance 4: a refine.fillerSets value reaches plan_refine as
    filler_sets (not dropped); absent -> None (the DEFAULT_SETS fallback)."""
    from media_studio.features import refine as _refine
    from media_studio.features import silencetrim as _silencetrim

    monkeypatch.setattr(_silencetrim, "detect_silence_spans", lambda *a, **k: [])
    captured: dict[str, Any] = {}

    def fake_plan_refine(words, lang, total, silences, **kwargs):
        captured["filler_sets"] = kwargs.get("filler_sets")
        return _refine.RefinePlan(keeps=[[0.0, total]], stats=_refine._zero_stats())

    monkeypatch.setattr(_refine, "plan_refine", fake_plan_refine)
    registered: dict[str, Any] = {}
    handlers.register_all(services=services, register=lambda name, fn: registered.__setitem__(name, fn))
    vid = _add_video(services, video_file)
    _transcribe_sync(services, ctx, vid)
    direct = RpcContext(emit_notification=lambda obj: None, jobs=None)

    override = {"en": {"always": frozenset({"basically"})}}
    registered["refine.preview"]({"videoId": vid, "fillerSets": override}, direct)
    assert captured["filler_sets"] == override

    captured.clear()
    registered["refine.preview"]({"videoId": vid}, direct)
    assert captured["filler_sets"] is None


def _persist_diarized_transcript(services: Services, vid: str) -> None:
    """Persist a two-segment transcript carrying a SPEAKER_00 label onto the project."""
    project = services._load_or_create_project(vid)
    project.data["transcript"] = {
        "language": "en",
        "durationSec": 4.0,
        "speakers": ["SPEAKER_00"],
        "segments": [
            {"start": 0.0, "end": 2.0, "text": "Hello there.", "speaker": "SPEAKER_00"},
            {"start": 2.0, "end": 4.0, "text": "General Kenobi.", "speaker": "SPEAKER_00"},
        ],
    }
    project.save()


def test_subtitles_generate_speaker_labels_on(services: Services, ctx: RpcContext, video_file: Path) -> None:
    """WU-5 acceptance 2: captionSpeakerLabels=True on a diarized transcript
    prefixes each speaker-bearing cue's text with '<speaker>: '."""
    vid = _add_video(services, video_file)
    _persist_diarized_transcript(services, vid)
    services.settings.set({"captionSpeakerLabels": True})
    gen = services.subtitles_generate({"videoId": vid}, ctx)
    cues = gen["track"]["cues"]
    assert cues, "generate produced no cues"
    assert all(c["text"].startswith("SPEAKER_00: ") for c in cues)
    # speaker carry survives onto the cues (WU-3 contract)
    assert all(c.get("speaker") == "SPEAKER_00" for c in cues)


def test_subtitles_generate_speaker_labels_off_unchanged(services: Services, ctx: RpcContext, video_file: Path) -> None:
    """WU-5 acceptance 2: flag off/absent -> UNPREFIXED text (back-compat); {track}
    shape unchanged."""
    vid = _add_video(services, video_file)
    _persist_diarized_transcript(services, vid)
    gen = services.subtitles_generate({"videoId": vid}, ctx)
    cues = gen["track"]["cues"]
    assert cues
    assert not any(c["text"].startswith("SPEAKER_00: ") for c in cues)
    assert {"id", "lang", "name", "format", "kind", "cues"} <= set(gen["track"])


def test_subtitles_generate_speaker_labels_on_non_diarized(
    services: Services, ctx: RpcContext, video_file: Path
) -> None:
    """WU-5 acceptance 2: captionSpeakerLabels=True on a NON-diarized transcript is
    a no-op (no speaker -> no prefix)."""
    vid = _add_video(services, video_file)
    _transcribe_sync(services, ctx, vid)
    services.settings.set({"captionSpeakerLabels": True})
    gen = services.subtitles_generate({"videoId": vid}, ctx)
    cues = gen["track"]["cues"]
    assert cues
    assert not any(": " in c["text"] and c["text"].startswith("SPEAKER") for c in cues)
    assert all("speaker" not in c for c in cues)


def test_subtitles_generate_speaker_labels_with_polish(services: Services, ctx: RpcContext, video_file: Path) -> None:
    """WU-5: the speaker gate composes with the captionPolish gate (both on)."""
    vid = _add_video(services, video_file)
    _persist_diarized_transcript(services, vid)
    services.settings.set({"captionSpeakerLabels": True, "captionPolish": True})
    gen = services.subtitles_generate({"videoId": vid}, ctx)
    cues = gen["track"]["cues"]
    assert cues
    assert all(c["text"].startswith("SPEAKER_00: ") for c in cues)
