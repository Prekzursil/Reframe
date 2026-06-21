"""Extra handler tests — the error/edge paths + register_all closures.

Companion to ``test_handlers.py`` / ``test_handlers_captions_export.py`` (same
seam style: a tmp-dir ``Services`` injected with fake whisper/ffmpeg/provider
seams, no subprocess / heavy dep / network). This file targets the handler
methods' error branches, the lazy ``models.*`` translation seams, the small
module-level helpers, and the inner ``register_all`` closures that the existing
suites do not reach — driving ``media_studio.handlers`` to full line+branch
coverage with REAL tests.

ISOLATION: every test uses tmp dirs + the autouse ``_restore_methods`` fixture
(conftest) that snapshots/restores ``protocol.METHODS``. The only ``sys.modules``
manipulation is via ``monkeypatch.setattr`` on module attributes (auto-reverted)
and always sets the PARENT-PACKAGE attribute too (HARD RULE 3) so a real
``from media_studio.models import translation`` later in the suite still sees the
real module. No global state (env vars, cwd, registry) leaks.
"""

from __future__ import annotations

import threading
import types
from pathlib import Path
from typing import Any

import pytest
from media_studio import handlers
from media_studio import library as _library
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
        silence_run=lambda argv, **k: type("C", (), {"stderr": "", "returncode": 0})(),
        scene_detector=lambda p: [],
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


@pytest.fixture
def jobless_ctx() -> RpcContext:
    """An RpcContext with NO job registry (drives the ``ctx.jobs is None`` guards)."""
    return RpcContext(emit_notification=lambda obj: None, jobs=None)


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
# _require_str / _load_or_create_project / _find_project_for_track
# --------------------------------------------------------------------------- #
def test_load_or_create_project_unknown_video_raises(services: Services) -> None:
    # _load_or_create_project: video missing from the library -> INVALID_PARAMS (line 140).
    with pytest.raises(RpcError) as ei:
        services._load_or_create_project("ghost")
    assert ei.value.code == ErrorCode.INVALID_PARAMS


def test_find_project_for_track_unknown_track_raises(services: Services) -> None:
    # No projects dir yet -> the glob loop never runs -> raise (line 162).
    with pytest.raises(RpcError) as ei:
        services._find_project_for_track("nope")
    assert ei.value.code == ErrorCode.INVALID_PARAMS


def test_find_project_for_track_scans_dir_but_finds_nothing(services: Services) -> None:
    """projects_dir EXISTS with only non-matching manifests -> scan, then raise
    (the 154->162 branch + the final raise at 162)."""
    services.projects_dir.mkdir(parents=True, exist_ok=True)
    _library.Project(
        {"video": {"id": "p1"}, "tracks": [{"id": "other"}]},
        manifest_path=services.projects_dir / "0-p1.json",
    ).save()
    with pytest.raises(RpcError) as ei:
        services._find_project_for_track("absent")
    assert ei.value.code == ErrorCode.INVALID_PARAMS


def test_find_project_for_track_skips_unreadable_and_non_matching(services: Services) -> None:
    """Cover the manifest scan branches (157-158 unreadable; 159->154 / 160->159).

    Three manifests live in projects_dir, NAMED so they sort BEFORE the matching
    one (glob is sorted): a corrupt one (skipped via except 157-158), a valid one
    with a non-dict track entry (160->159) + a non-matching id (159->154), and
    finally the project that actually owns the wanted track id.
    """
    services.projects_dir.mkdir(parents=True, exist_ok=True)
    # A corrupt manifest -> Project.open raises -> the except continues (157-158).
    (services.projects_dir / "0-bad.json").write_text("{not json", encoding="utf-8")
    # A valid manifest whose tracks include a non-dict entry (160->159) and a
    # dict whose id does not match (159->154 loop-continue).
    _library.Project(
        {"video": {"id": "other-vid"}, "tracks": ["not-a-dict", {"id": "zzz"}]},
        manifest_path=services.projects_dir / "1-other.json",
    ).save()
    # The owning project, sorted last (prefix "2-").
    _library.Project(
        {"video": {"id": "owner-vid"}, "tracks": [{"id": "wanted"}]},
        manifest_path=services.projects_dir / "2-owner.json",
    ).save()
    found = services._find_project_for_track("wanted")
    assert found.data["video"]["id"] == "owner-vid"


# --------------------------------------------------------------------------- #
# library.add file-not-found (177-178)
# --------------------------------------------------------------------------- #
def test_library_add_missing_file_raises(services: Services, ctx: RpcContext, tmp_path: Path) -> None:
    """library.add of a non-existent path surfaces FileNotFoundError -> INVALID_PARAMS."""
    services.library = _library.Library(services.data_dir / "library.json", probe_duration=lambda _p: 1.0)
    with pytest.raises(RpcError) as ei:
        services.library_add({"path": str(tmp_path / "nope.mp4")}, ctx)
    assert ei.value.code == ErrorCode.INVALID_PARAMS


# --------------------------------------------------------------------------- #
# project.save  (line 203-212)
# --------------------------------------------------------------------------- #
def test_project_save_requires_object(services: Services, jobless_ctx: RpcContext) -> None:
    with pytest.raises(RpcError) as ei:
        services.project_save({"project": "nope"}, jobless_ctx)  # not a dict (line 204-205)
    assert ei.value.code == ErrorCode.INVALID_PARAMS


def test_project_save_requires_video_id(services: Services, jobless_ctx: RpcContext) -> None:
    with pytest.raises(RpcError) as ei:
        services.project_save({"project": {"video": {}}}, jobless_ctx)  # no id (line 208-209)
    assert ei.value.code == ErrorCode.INVALID_PARAMS


def test_project_save_writes_manifest(services: Services, jobless_ctx: RpcContext, video_file: Path) -> None:
    vid = _add_video(services, video_file)
    data = {"video": {"id": vid}, "tracks": []}
    assert services.project_save({"project": data}, jobless_ctx) == {"ok": True}  # line 210-212
    assert services._project_path(vid).exists()


# --------------------------------------------------------------------------- #
# subtitles.edit / export error branches
# --------------------------------------------------------------------------- #
def test_subtitles_edit_requires_cues_list(services: Services, ctx: RpcContext, video_file: Path) -> None:
    _vid, track_id = _make_track(services, ctx, video_file)
    with pytest.raises(RpcError) as ei:  # cues not a list (line 258)
        services.subtitles_edit({"trackId": track_id, "cues": "no"}, ctx)
    assert ei.value.code == ErrorCode.INVALID_PARAMS


def test_subtitles_export_bad_format_raises(services: Services, ctx: RpcContext, video_file: Path) -> None:
    _vid, track_id = _make_track(services, ctx, video_file)
    with pytest.raises(RpcError) as ei:  # _subtitles.export raises ValueError -> 279-280
        services.subtitles_export({"trackId": track_id, "format": "bogus"}, ctx)
    assert ei.value.code == ErrorCode.INVALID_PARAMS


# --------------------------------------------------------------------------- #
# subtitles.translate guards + save_path-None branches (303, 308, 337->339, 345->347)
# --------------------------------------------------------------------------- #
def test_subtitles_translate_requires_jobs(services: Services, jobless_ctx: RpcContext, video_file: Path) -> None:
    # No job registry -> INTERNAL_ERROR (line 302-303). The guard fires before any
    # track lookup, so a fabricated trackId is fine here.
    with pytest.raises(RpcError) as ei:
        services.subtitles_translate({"trackId": "t", "targetLang": "es"}, jobless_ctx)
    assert ei.value.code == ErrorCode.INTERNAL_ERROR


def test_subtitles_translate_cloud_offline_refused(services: Services, ctx: RpcContext, video_file: Path) -> None:
    # useCloud + offline -> _offline.guard_network raises (line 307-308) BEFORE the
    # track lookup. OfflineError is an RpcError (INVALID_PARAMS).
    _vid, track_id = _make_track(services, ctx, video_file)
    services.settings.set({"useCloud": True, "offline": True})
    with pytest.raises(RpcError) as ei:
        services.subtitles_translate({"trackId": track_id, "targetLang": "es"}, ctx)
    assert ei.value.code == ErrorCode.INVALID_PARAMS


def _pathless_project_translate(
    services: Services, ctx: RpcContext, video_file: Path, *, bilingual: bool
) -> dict[str, Any]:
    """Run translate where the resolved project has manifest_path=None.

    Drives the ``if save_path is not None`` FALSE branch (337->339 bilingual /
    345->347 monolingual): the in-memory project is never saved.
    """
    vid, track_id = _make_track(services, ctx, video_file)
    real = services._find_project_for_track(track_id)
    pathless = _library.Project(real.data, manifest_path=None)
    services._find_project_for_track = lambda _tid: pathless  # type: ignore[method-assign]
    params: dict[str, Any] = {"trackId": track_id, "targetLang": "es"}
    if bilingual:
        params["bilingual"] = True
    services.subtitles_translate(params, ctx)
    ctx.jobs.join(timeout=5)
    done = [e for e in ctx.events if e[0] == "done"]  # type: ignore[attr-defined]
    return done[-1][2]


def test_translate_monolingual_pathless_project_not_saved(
    services: Services, ctx: RpcContext, video_file: Path
) -> None:
    result = _pathless_project_translate(services, ctx, video_file, bilingual=False)
    assert result["track"]["lang"] == "es"  # 345->347 false branch (no save)


def test_translate_bilingual_pathless_project_not_saved(services: Services, ctx: RpcContext, video_file: Path) -> None:
    result = _pathless_project_translate(services, ctx, video_file, bilingual=True)
    assert result["track"]["lang"] == "en+es"  # 337->339 false branch (no save)


def test_translate_tiered_path_when_no_provider(
    ctx: RpcContext, video_file: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With NO injected provider, _get_translator returns a (fake) TieredTranslator
    so the job body takes the T3 ``translator.translate_track`` branch (line 319).
    """
    svc = Services(
        data_dir=tmp_path / "data",
        whisper_loader=FakeWhisperLoader(),
        ffmpeg_run=fake_run,
        ffprobe_duration=fake_probe,
    )  # NB: provider=None on purpose
    _install_fake_models(monkeypatch)
    vid, track_id = _make_track(svc, ctx, video_file)

    res = svc.subtitles_translate({"trackId": track_id, "targetLang": "es"}, ctx)
    assert "jobId" in res
    ctx.jobs.join(timeout=5)
    done = [e for e in ctx.events if e[0] == "done"]  # type: ignore[attr-defined]
    # The fake tiered translator updated lang to the target (translate_track path).
    assert done[-1][2]["track"]["lang"] == "es"


# --------------------------------------------------------------------------- #
# tracks.* error branches (368-369, 380-381, 396->399, 402-403, 414-417, 432,
# 438-439, 451, 454)
# --------------------------------------------------------------------------- #
def test_tracks_rename_bad_name_raises(services: Services, ctx: RpcContext, video_file: Path) -> None:
    _vid, track_id = _make_track(services, ctx, video_file)
    # A blank/dup-style name surfaces _tracks.TrackError -> 368-369. Use a name the
    # rename validator rejects; if rename accepts any non-empty name, monkeypatch.
    from media_studio.features import tracks as _tracks

    def _boom(*_a: Any, **_k: Any) -> Any:
        raise _tracks.TrackError("bad name")

    services_tracks_rename = _tracks.rename_track
    try:
        _tracks.rename_track = _boom  # type: ignore[assignment]
        with pytest.raises(RpcError) as ei:
            services.tracks_rename({"trackId": track_id, "name": "X"}, ctx)
        assert ei.value.code == ErrorCode.INVALID_PARAMS
    finally:
        _tracks.rename_track = services_tracks_rename  # type: ignore[assignment]


def test_tracks_relabel_error_raises(services: Services, ctx: RpcContext, video_file: Path) -> None:
    _vid, track_id = _make_track(services, ctx, video_file)
    from media_studio.features import tracks as _tracks

    def _boom(*_a: Any, **_k: Any) -> Any:
        raise _tracks.TrackError("bad lang")

    saved = _tracks.relabel_track
    try:
        _tracks.relabel_track = _boom  # type: ignore[assignment]
        with pytest.raises(RpcError) as ei:  # 380-381
            services.tracks_relabel({"trackId": track_id, "lang": "xx"}, ctx)
        assert ei.value.code == ErrorCode.INVALID_PARAMS
    finally:
        _tracks.relabel_track = saved  # type: ignore[assignment]


def test_tracks_add_with_inline_track_object(services: Services, ctx: RpcContext, video_file: Path) -> None:
    """A full ``track`` object on params skips the find-by-id resolve (396->399)."""
    vid = _add_video(services, video_file)
    track = {"id": "inline-1", "kind": "soft", "lang": "en", "name": "Inline", "cues": []}
    assert services.tracks_add({"videoId": vid, "trackId": "inline-1", "track": track}, ctx) == {"ok": True}
    listed = services.tracks_list({"videoId": vid}, ctx)
    assert any(t["id"] == "inline-1" for t in listed["tracks"])


def test_tracks_add_duplicate_raises(services: Services, ctx: RpcContext, video_file: Path) -> None:
    """Adding a track id that already exists surfaces TrackError (402-403)."""
    vid, track_id = _make_track(services, ctx, video_file)
    from media_studio.features import tracks as _tracks

    def _boom(*_a: Any, **_k: Any) -> Any:
        raise _tracks.TrackError("dup")

    saved = _tracks.add_track
    try:
        _tracks.add_track = _boom  # type: ignore[assignment]
        with pytest.raises(RpcError) as ei:
            services.tracks_add({"videoId": vid, "trackId": track_id}, ctx)
        assert ei.value.code == ErrorCode.INVALID_PARAMS
    finally:
        _tracks.add_track = saved  # type: ignore[assignment]


def test_tracks_remove_hardsub_raises(services: Services, ctx: RpcContext, video_file: Path) -> None:
    vid, track_id = _make_track(services, ctx, video_file)
    from media_studio.features import tracks as _tracks

    def _boom(*_a: Any, **_k: Any) -> Any:
        raise _tracks.HardSubtitleError("hard")

    saved = _tracks.remove_track
    try:
        _tracks.remove_track = _boom  # type: ignore[assignment]
        with pytest.raises(RpcError) as ei:  # 414-415
            services.tracks_remove({"videoId": vid, "trackId": track_id}, ctx)
        assert ei.value.code == ErrorCode.INVALID_PARAMS
    finally:
        _tracks.remove_track = saved  # type: ignore[assignment]


def test_tracks_remove_not_found_raises(services: Services, ctx: RpcContext, video_file: Path) -> None:
    vid, track_id = _make_track(services, ctx, video_file)
    from media_studio.features import tracks as _tracks

    def _boom(*_a: Any, **_k: Any) -> Any:
        raise _tracks.TrackNotFoundError("missing")

    saved = _tracks.remove_track
    try:
        _tracks.remove_track = _boom  # type: ignore[assignment]
        with pytest.raises(RpcError) as ei:  # 416-417
            services.tracks_remove({"videoId": vid, "trackId": track_id}, ctx)
        assert ei.value.code == ErrorCode.INVALID_PARAMS
    finally:
        _tracks.remove_track = saved  # type: ignore[assignment]


def test_tracks_strip_unknown_video_raises(services: Services, ctx: RpcContext) -> None:
    # _resolve_video_path returns None -> INVALID_PARAMS (line 431-432).
    with pytest.raises(RpcError) as ei:
        services.tracks_strip({"videoId": "ghost", "trackId": "t"}, ctx)
    assert ei.value.code == ErrorCode.INVALID_PARAMS


def test_tracks_strip_track_error_is_internal(services: Services, ctx: RpcContext, video_file: Path) -> None:
    vid, track_id = _make_track(services, ctx, video_file)
    from media_studio.features import tracks as _tracks

    def _boom(*_a: Any, **_k: Any) -> Any:
        raise _tracks.TrackError("ffmpeg")

    saved = _tracks.strip_track
    try:
        _tracks.strip_track = _boom  # type: ignore[assignment]
        with pytest.raises(RpcError) as ei:  # 438-439 -> INTERNAL_ERROR
            services.tracks_strip({"videoId": vid, "trackId": track_id}, ctx)
        assert ei.value.code == ErrorCode.INTERNAL_ERROR
    finally:
        _tracks.strip_track = saved  # type: ignore[assignment]


def test_tracks_burn_requires_jobs(services: Services, jobless_ctx: RpcContext) -> None:
    with pytest.raises(RpcError) as ei:  # 450-451
        services.tracks_burn({"videoId": "v", "trackId": "t"}, jobless_ctx)
    assert ei.value.code == ErrorCode.INTERNAL_ERROR


def test_tracks_burn_unknown_video_raises(services: Services, ctx: RpcContext) -> None:
    with pytest.raises(RpcError) as ei:  # 453-454
        services.tracks_burn({"videoId": "ghost", "trackId": "t"}, ctx)
    assert ei.value.code == ErrorCode.INVALID_PARAMS


# --------------------------------------------------------------------------- #
# convert.* + transcribe.start jobless guards (486, 503, 531)
# --------------------------------------------------------------------------- #
def test_convert_start_requires_jobs(services: Services, jobless_ctx: RpcContext) -> None:
    with pytest.raises(RpcError) as ei:  # 485-486
        services.convert_start({"videoId": "v", "options": {}}, jobless_ctx)
    assert ei.value.code == ErrorCode.INTERNAL_ERROR


def test_convert_batch_requires_jobs(services: Services, jobless_ctx: RpcContext) -> None:
    with pytest.raises(RpcError) as ei:  # 502-503
        services.convert_batch({"items": []}, jobless_ctx)
    assert ei.value.code == ErrorCode.INTERNAL_ERROR


def test_transcribe_start_requires_jobs(services: Services, jobless_ctx: RpcContext) -> None:
    with pytest.raises(RpcError) as ei:  # 530-531
        services.transcribe_start({"videoId": "v"}, jobless_ctx)
    assert ei.value.code == ErrorCode.INTERNAL_ERROR


def test_transcribe_start_bad_language_type(services: Services, ctx: RpcContext, video_file: Path) -> None:
    vid = _add_video(services, video_file)
    with pytest.raises(RpcError) as ei:  # 534-535 (language not a str)
        services.transcribe_start({"videoId": vid, "language": 7}, ctx)
    assert ei.value.code == ErrorCode.INVALID_PARAMS


def test_transcribe_start_cancelled_skips_persist(services: Services, ctx: RpcContext, video_file: Path) -> None:
    """A job cancelled mid-transcribe skips the persist branch (549->558).

    DETERMINISTIC (no race): the fake model blocks inside ``transcribe`` until the
    test has cancelled the job, so ``job_ctx.cancelled`` is guaranteed True by the
    time the body reaches the persist check -> the transcript is NOT persisted
    (hasTranscript stays False, no project saved). Previously this raced the empty
    transcribe against the cancel and flaked ~1/3 of runs.
    """
    vid = _add_video(services, video_file)
    started = threading.Event()
    released = threading.Event()

    class CancellingModel:
        def transcribe(self, audio: str, **_k: Any) -> tuple[Any, dict[str, Any]]:
            started.set()  # the job body is now inside transcribe
            released.wait(timeout=5)  # block until the test has cancelled
            return iter([]), {"duration": 0.0, "language": "en"}

    class CancellingLoader:
        def load(self, *_a: Any, **_k: Any) -> CancellingModel:
            return CancellingModel()

    services._whisper_loader = CancellingLoader()
    res = services.transcribe_start({"videoId": vid}, ctx)
    assert started.wait(timeout=5), "transcribe never entered the job body"
    ctx.jobs.cancel(res["jobId"])  # cancel WHILE transcribe is blocked
    released.set()  # let transcribe return; cancelled is already True
    ctx.jobs.join(timeout=5)
    # Cancelled -> transcript not persisted onto the library flag.
    assert services.library.get(vid).get("hasTranscript") in (False, None)


def test_transcribe_persist_handles_set_flag_failure(services: Services, ctx: RpcContext, video_file: Path) -> None:
    """set_has_transcript failure is swallowed (556-557): the warning path runs
    but the job still completes with the transcript result."""
    vid = _add_video(services, video_file)

    def _boom(*_a: Any, **_k: Any) -> None:
        raise RuntimeError("flag write failed")

    services.library.set_has_transcript = _boom  # type: ignore[method-assign]
    services.transcribe_start({"videoId": vid}, ctx)
    ctx.jobs.join(timeout=5)
    done = [e for e in ctx.events if e[0] == "done"]  # type: ignore[attr-defined]
    assert "transcript" in done[-1][2]
    # The transcript is still persisted onto the project despite the flag failure.
    assert services._load_or_create_project(vid).data["transcript"]["language"] == "en"


# --------------------------------------------------------------------------- #
# _detect_boundaries / _shortmaker_context / shortmaker guards (587, 613-615,
# 635, 670)
# --------------------------------------------------------------------------- #
def test_detect_boundaries_unknown_video_returns_empty(services: Services) -> None:
    assert services._detect_boundaries("ghost") == {"silences": [], "sceneCuts": []}  # 587


def test_shortmaker_context_bad_manifest_yields_no_transcript(services: Services, video_file: Path) -> None:
    """A corrupt project manifest -> the except resets transcript/audio (613-615)."""
    vid = _add_video(services, video_file)
    services._project_path(vid).parent.mkdir(parents=True, exist_ok=True)
    services._project_path(vid).write_text("{broken", encoding="utf-8")
    out = services._shortmaker_context(vid)
    assert out["transcript"] is None
    assert out["audioTracks"] == []


def test_shortmaker_select_requires_jobs(services: Services, jobless_ctx: RpcContext) -> None:
    with pytest.raises(RpcError) as ei:  # 634-635
        services.shortmaker_select({"videoId": "v"}, jobless_ctx)
    assert ei.value.code == ErrorCode.INTERNAL_ERROR


def test_shortmaker_export_requires_jobs(services: Services, jobless_ctx: RpcContext) -> None:
    with pytest.raises(RpcError) as ei:  # 669-670
        services.shortmaker_export({"videoId": "v", "candidateIds": []}, jobless_ctx)
    assert ei.value.code == ErrorCode.INTERNAL_ERROR


# --------------------------------------------------------------------------- #
# nle.export explicit title (704->707) + package.export FileNotFound (750-751)
# --------------------------------------------------------------------------- #
def test_nle_export_with_explicit_title(services: Services, ctx: RpcContext, video_file: Path) -> None:
    vid = _add_video(services, video_file)
    services._load_or_create_project(vid)  # ensure project exists (empty clips ok)
    res = services.nle_export({"videoId": vid, "title": "My Title", "clips": []}, ctx)
    body = Path(res["path"]).read_text(encoding="utf-8")
    assert "TITLE: My Title" in body  # explicit title skips the fallback (704->707)


def test_package_export_package_raises_filenotfound(
    services: Services, ctx: RpcContext, video_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If _package_export.package raises FileNotFoundError it maps to INVALID_PARAMS
    (750-751). The clip exists + lives in the exports root, so the guards pass and
    only the (monkeypatched) package() raises."""
    vid = _add_video(services, video_file)
    out = services.exports_dir / f"shorts-{vid}"
    out.mkdir(parents=True, exist_ok=True)
    clip = out / "clip.mp4"
    clip.write_bytes(b"\x00mp4")

    from media_studio.features import package_export as _pkg

    def _boom(*_a: Any, **_k: Any) -> Any:
        raise FileNotFoundError("gone mid-zip")

    monkeypatch.setattr(_pkg, "package", _boom)
    with pytest.raises(RpcError) as ei:
        services.package_export({"path": str(clip)}, ctx)
    assert ei.value.code == ErrorCode.INVALID_PARAMS


# --------------------------------------------------------------------------- #
# the lazy models.* seams: _get_provider / _get_model_runner / _get_translator /
# _dub_translator (779-783, 787-791, 802-804, 816-838)
# --------------------------------------------------------------------------- #
def _install_fake_models(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Install fake provider/runner/translation modules.

    HARD RULE 3: set BOTH sys.modules AND the parent-package (media_studio.models)
    attribute, because handlers does ``from .models import provider`` which reads
    the package attribute. monkeypatch reverts all of it after the test.
    Returns recorders so a test can assert which seam ran.
    """
    import media_studio.models as _models_pkg

    rec: dict[str, Any] = {"provider_args": None, "runner_args": None, "translator_args": None}

    class FakeRunner:
        def __init__(self, settings: Any) -> None:
            rec["runner_args"] = settings
            self.stopped = False

        def stop_server(self) -> None:
            self.stopped = True
            rec["stopped"] = True

    class FakeTieredTranslator:
        def __init__(self) -> None:
            self._free_calls = 0

        def translate(self, cues: list[dict[str, Any]], target_lang: str, *, source_lang: Any = None):
            # echo: prefix each line so the dub adapter's mapping is observable.
            return [dict(c, text=f"{target_lang}:{c.get('text', '')}") for c in cues]

        def translate_track(self, track: dict[str, Any], target_lang: str, **_k: Any):
            out = dict(track)
            out["lang"] = target_lang
            return out

    fake_provider_mod = types.ModuleType("media_studio.models.provider")

    def _get_provider(settings: Any = None, **_k: Any) -> Any:
        rec["provider_args"] = settings
        return FakeProvider()

    fake_provider_mod.get_provider = _get_provider  # type: ignore[attr-defined]

    fake_runner_mod = types.ModuleType("media_studio.models.runner")
    fake_runner_mod.ModelRunner = FakeRunner  # type: ignore[attr-defined]

    fake_translation_mod = types.ModuleType("media_studio.models.translation")

    def _get_translator(settings: Any = None, *, runner: Any = None, **_k: Any) -> Any:
        rec["translator_args"] = (settings, runner)
        return FakeTieredTranslator()

    fake_translation_mod.get_translator = _get_translator  # type: ignore[attr-defined]

    for name, mod in (
        ("provider", fake_provider_mod),
        ("runner", fake_runner_mod),
        ("translation", fake_translation_mod),
    ):
        monkeypatch.setitem(__import__("sys").modules, f"media_studio.models.{name}", mod)
        monkeypatch.setattr(_models_pkg, name, mod, raising=False)
    return rec


def test_get_provider_lazy_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # No injected provider -> the lazy ``from .models import provider`` path (781-783).
    svc = Services(data_dir=tmp_path / "d")
    rec = _install_fake_models(monkeypatch)
    prov = svc._get_provider()
    assert isinstance(prov, FakeProvider)
    assert rec["provider_args"] is not None  # settings forwarded


def test_get_provider_returns_injected(tmp_path: Path) -> None:
    inj = FakeProvider()
    svc = Services(data_dir=tmp_path / "d", provider=inj)
    assert svc._get_provider() is inj  # 779-780 short-circuit


def test_get_model_runner_lazy_and_cached(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    svc = Services(data_dir=tmp_path / "d")
    _install_fake_models(monkeypatch)
    runner1 = svc._get_model_runner()  # 787-791
    runner2 = svc._get_model_runner()  # cached -> same object
    assert runner1 is runner2


def test_get_translator_none_when_provider_injected(tmp_path: Path) -> None:
    svc = Services(data_dir=tmp_path / "d", provider=FakeProvider())
    assert svc._get_translator() is None  # 800-801


def test_get_translator_lazy_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    svc = Services(data_dir=tmp_path / "d")  # no provider -> tiered path
    rec = _install_fake_models(monkeypatch)
    translator = svc._get_translator()  # 802-804
    assert translator is not None
    assert rec["translator_args"] is not None


def test_dub_translator_adapter(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """_dub_translator wraps the tiered translator (816-838): translate maps
    texts<->cues, and free() stops the shared runner."""
    svc = Services(data_dir=tmp_path / "d")
    rec = _install_fake_models(monkeypatch)
    dub = svc._dub_translator()
    out = dub.translate(["hi", "there"], "es", "en")
    assert out == ["es:hi", "es:there"]  # _DubTranslator.translate cue-mapping
    dub.free()  # free() -> runner.stop_server() (832-834)
    assert rec.get("stopped") is True


def test_dub_translator_free_swallows_stop_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """free() best-effort: a stop_server failure is logged, not raised (835-836)."""
    import media_studio.models as _models_pkg

    svc = Services(data_dir=tmp_path / "d")

    class BoomRunner:
        def __init__(self, settings: Any) -> None:
            pass

        def stop_server(self) -> None:
            raise RuntimeError("stop failed")

    class FakeTieredTranslator:
        def translate(self, cues: list[dict[str, Any]], target_lang: str, *, source_lang: Any = None):
            return cues

    fake_runner_mod = types.ModuleType("media_studio.models.runner")
    fake_runner_mod.ModelRunner = BoomRunner  # type: ignore[attr-defined]
    fake_translation_mod = types.ModuleType("media_studio.models.translation")
    fake_translation_mod.get_translator = lambda *a, **k: FakeTieredTranslator()  # type: ignore[attr-defined]

    import sys

    for name, mod in (("runner", fake_runner_mod), ("translation", fake_translation_mod)):
        monkeypatch.setitem(sys.modules, f"media_studio.models.{name}", mod)
        monkeypatch.setattr(_models_pkg, name, mod, raising=False)

    dub = svc._dub_translator()
    dub.free()  # must not raise


# --------------------------------------------------------------------------- #
# module-level helpers: _self_ffmpeg_run / _self_ffprobe / _js_number
# (846-848, 867-868)
# --------------------------------------------------------------------------- #
def test_self_ffmpeg_run_and_probe_resolve_callables() -> None:
    run = handlers._self_ffmpeg_run()  # 846-848 (lazy ffmpeg import)
    probe = handlers._self_ffprobe()  # 855 -> ffmpeg.ffprobe_duration
    assert callable(run) and callable(probe)


def test_js_number_integer_float_and_non_numeric() -> None:
    assert handlers._js_number(5.0) == "5"  # integer-valued float drops .0
    assert handlers._js_number(5.5) == "5.5"
    assert handlers._js_number("abc") == "abc"  # 867-868 (TypeError/ValueError)
    assert handlers._js_number(None) == "None"


def test_candidate_id_non_numeric_source_start() -> None:
    # Exercises candidate_id -> _js_number non-numeric branch end-to-end.
    assert Services.candidate_id({"rank": 3, "sourceStart": "x"}) == "3@x"


# --------------------------------------------------------------------------- #
# register_all inner closures: _load_project_data / _save_project_data /
# _load_subtitle_track (950, 953, 956-960)
# --------------------------------------------------------------------------- #
def _capture_register_closures(services: Services, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Run register_all but capture the closures handed to tracks_audio + tts.

    register_all builds three inner closures (``_load_project_data``,
    ``_save_project_data``, ``_load_subtitle_track``) and passes them as kwargs to
    the feature modules' register(). We replace those two register() functions
    with capturers so we can invoke the closures directly and cover their bodies.
    """
    from media_studio.features import tracks_audio as _ta
    from media_studio.features import tts as _tts

    captured: dict[str, Any] = {}

    def fake_ta_register(*, load_project, save_project, **_k: Any) -> Any:
        captured["load_project"] = load_project
        captured["save_project"] = save_project
        return object()  # stand-in audio_tracks svc handed to tts.register

    def fake_tts_register(*, load_track, **_k: Any) -> None:
        captured["load_track"] = load_track

    monkeypatch.setattr(_ta, "register", fake_ta_register)
    monkeypatch.setattr(_tts, "register", fake_tts_register)
    handlers.register_all(
        services=services,
        register=lambda name, fn: None,  # swallow registrations
    )
    return captured


def test_register_all_closures_load_save_and_load_track(
    services: Services, ctx: RpcContext, video_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vid, track_id = _make_track(services, ctx, video_file)
    captured = _capture_register_closures(services, monkeypatch)

    # _load_project_data (950): returns the project's data dict.
    data = captured["load_project"](vid)
    assert data["video"]["id"] == vid

    # _load_subtitle_track (955-958): returns the named track. Done BEFORE the
    # save below, which deliberately overwrites the manifest with empty tracks.
    track = captured["load_track"](vid, track_id)
    assert track["id"] == track_id

    # _save_project_data (952-953): writes a manifest for the video (overwrites it
    # with a tracks-less project — the closure's job is just to persist).
    captured["save_project"](vid, {"video": {"id": vid}, "tracks": []})
    assert services._project_path(vid).exists()
    assert captured["load_project"](vid)["tracks"] == []


def test_register_all_load_subtitle_track_unknown_raises(
    services: Services, ctx: RpcContext, video_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vid, _track_id = _make_track(services, ctx, video_file)
    captured = _capture_register_closures(services, monkeypatch)
    with pytest.raises(RpcError) as ei:  # _load_subtitle_track except -> 959-960
        captured["load_track"](vid, "no-such-track")
    assert ei.value.code == ErrorCode.INVALID_PARAMS
