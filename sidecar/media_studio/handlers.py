"""Composition root — wire every §2 method's handler onto ``protocol.METHODS``.

The feature modules ship correct pure functions but register NOTHING. This module
is the assembly seam the build was missing (INTEGRATION-REPORT §CRITICAL-1):

  * it owns the runtime services — a :class:`~media_studio.library.Library`, a
    :class:`~media_studio.settings_store.SettingsStore`, a per-video Project
    manifest store, and a short-maker selection cache;
  * it authors thin ``(params, ctx) -> result`` handlers that ADAPT the wire
    params (``videoId``/``trackId``/``id``/``path``) onto each pure function and
    return the EXACT §3 result dict; long-running ones run on ``ctx.jobs`` and
    return ``{jobId}``;
  * :func:`register_all` calls ``protocol.register`` (and the feature modules'
    own ``register`` helpers) for all ~30 methods.

``media_studio/__main__.py`` imports this, calls :func:`register_all`, then runs
``rpc.main`` — so the registrations land in ``METHODS`` before the loop serves.

Heavy deps stay behind the same seams the features already use: this module does
NOT import faster-whisper / scenedetect / verthor / a provider at module load.
The transcribe/select/translate handlers reach those only inside a job body.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from . import library as _library
from . import protocol
from .features import boundary as _boundary
from .features import convert as _convert
from .features import media_compat as _media_compat
from .features import nle_export as _nle_export
from .features import offline as _offline
from .features import package_export as _package_export
from .features import shortmaker as _shortmaker
from .features import shorts as _shorts_meta
from .features import subtitles as _subtitles
from .features import timeline as _timeline
from .features import tracks as _tracks
from .features import transcribe as _transcribe
from .protocol import ErrorCode, RpcContext, RpcError
from .settings_store import SettingsStore, default_config_dir
from .util import get_logger

log = get_logger("media_studio.handlers")

Video = dict[str, Any]
SubtitleTrack = dict[str, Any]
Candidate = dict[str, Any]


@dataclass(frozen=True)
class _BudgetRequest:
    """A wire-coerced budget request (satisfies ``budget.BudgetRequest`` duck-type).

    ``target_size`` is the discrete output count (``None`` -> the budget default);
    the two byte fields are the per-request egress split by data kind.
    """

    target_size: int | None
    text_bytes: int
    frame_bytes: int


@dataclass(frozen=True)
class _LocalPoolEntry:
    """A single local backstop pool entry (satisfies ``budget.PoolEntry``)."""

    provider: str = "local"
    local: bool = True


@dataclass(frozen=True)
class _LocalOnlyPool:
    """A local-only fallback pool used when the provider module is a test stub.

    Satisfies :func:`budget.estimate`'s pool shape (``.entries`` of provider/local
    items); the budget then reports local-only with zero cloud egress.
    """

    entries: tuple[_LocalPoolEntry, ...] = (_LocalPoolEntry(),)


def _invalid(message: str) -> RpcError:
    return RpcError(message, ErrorCode.INVALID_PARAMS)


def _require_str(params: dict[str, Any], key: str) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value:
        raise _invalid(f"{key} (str) is required")
    return value


class Services:
    """The runtime services + per-method handlers (the composition root).

    Owns the on-disk locations (all under a single per-user **data dir**, never a
    project folder): the library index, the per-video project manifests, the
    short-maker export output, and the settings file. Tests construct it with an
    injected ``data_dir`` (a tmp path) and injected seams (whisper loader, scene
    detector, ffmpeg ``run``) so no heavy dep / real subprocess is touched.
    """

    def __init__(
        self,
        *,
        data_dir: str | os.PathLike | None = None,
        settings_store: SettingsStore | None = None,
        library: _library.Library | None = None,
        whisper_loader: Any | None = None,
        ffmpeg_run: Callable[..., int] | None = None,
        ffprobe_duration: Callable[..., float] | None = None,
        reframe_runner: Callable[..., Any] | None = None,
        silence_run: Callable[..., Any] | None = None,
        scene_detector: Callable[[str], Any] | None = None,
        provider: Any | None = None,
        hardware_probe: Any | None = None,
        phase8_runner: Callable[..., dict[str, Any]] | None = None,
    ) -> None:
        base = Path(data_dir) if data_dir is not None else default_config_dir()
        self.data_dir = base
        self.projects_dir = base / "projects"
        self.exports_dir = base / "exports"
        self.settings = settings_store or SettingsStore(base / "settings.json")
        self.library = library or _library.Library(base / "library.json")

        # Injectable seams (default to the real, lazily-resolved impls).
        self._whisper_loader = whisper_loader
        self._ffmpeg_run = ffmpeg_run
        self._ffprobe_duration = ffprobe_duration
        self._reframe_runner = reframe_runner
        self._silence_run = silence_run
        self._scene_detector = scene_detector
        self._provider = provider
        # Phase-8 seams: a HardwareProbe (VRAM/RAM/CPU) for system.probe/advisor and
        # a signal-compute runner for phase8.signals/select. Defaults are the real
        # (heavy) impls, resolved lazily; tests inject fakes so no GPU / no torch.
        self._hardware_probe = hardware_probe
        self._phase8_runner = phase8_runner

        # T3: the shared llama.cpp ModelRunner (built lazily; model-identity-aware,
        # so the tiered translator can swap MT GGUFs on the one server lane).
        self._model_runner: Any | None = None

        # short-maker selection cache: selectionId -> {candidateId -> Candidate}.
        # CONTRACT-NOTE (INTEGRATION-REPORT HIGH-3): the UI builds candidate ids as
        # "rank@sourceStart" and sends only candidateIds to shortmaker.export. We
        # cache the select result server-side under those same ids so export can
        # resolve real clips; the loader exposes the cache as the context's
        # "candidates" map that _resolve_candidates already consults.
        self._selection_cache: dict[str, dict[str, Candidate]] = {}

    # ===================================================================== #
    # resolvers
    # ===================================================================== #
    def _resolve_video_path(self, video_id: str) -> str | None:
        """videoId -> absolute media path (or None if unknown)."""
        video = self.library.get(video_id)
        if video is None:
            return None
        return video.get("path") or None

    def _project_path(self, video_id: str) -> Path:
        """The manifest path for a video's project (one project per video)."""
        return self.projects_dir / f"{video_id}.json"

    def _load_or_create_project(self, video_id: str) -> _library.Project:
        """Open the video's project manifest, creating a fresh one if absent."""
        path = self._project_path(video_id)
        if path.exists():
            return _library.Project.open(path)
        video = self.library.get(video_id)
        if video is None:
            raise _invalid(f"unknown video: {video_id}")
        project = _library.Project.new(video, settings=self.settings.get())
        project.save(path)
        return project

    def _find_project_for_track(self, track_id: str) -> _library.Project:
        """Find the project whose tracks contain ``track_id`` (scan manifests).

        CONTRACT-NOTE: tracks.rename / tracks.relabel send only a ``trackId`` (no
        ``videoId``), so we locate the owning project by scanning the per-video
        manifests. Other tracks.* methods carry ``videoId`` and use the direct
        path. Raises INVALID_PARAMS when no project owns the id.
        """
        if self.projects_dir.exists():
            for manifest in sorted(self.projects_dir.glob("*.json")):
                try:
                    project = _library.Project.open(manifest)
                except Exception:  # noqa: BLE001 - skip an unreadable manifest
                    continue
                for track in project.data.get("tracks") or []:
                    if isinstance(track, dict) and track.get("id") == track_id:
                        return project
        raise _invalid(f"unknown track: {track_id}")

    # ===================================================================== #
    # library.*
    # ===================================================================== #
    def library_list(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``library.list`` -> ``{videos:[Video]}`` (§2). Direct-return."""
        return {"videos": self.library.list()}

    def library_add(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``library.add({path})`` -> ``{video}`` (§2). Direct-return."""
        path = _require_str(params, "path")
        title = params.get("title")
        try:
            video = self.library.add(path, title if isinstance(title, str) else None)
        except FileNotFoundError as exc:
            raise _invalid(str(exc)) from exc
        return {"video": video}

    def library_remove(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``library.remove({id})`` -> ``{ok:true}`` (§2). Direct-return."""
        video_id = _require_str(params, "id")
        ok = self.library.remove(video_id)
        return {"ok": bool(ok)}

    # ===================================================================== #
    # project.*
    # ===================================================================== #
    def project_open(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``project.open({id})`` -> ``{project}`` (§2). Direct-return.

        CONTRACT-NOTE: the UI sends a video ``id``; ``library.Project.open`` takes
        a *manifest path*. We resolve id -> the per-video manifest, creating a
        fresh project on first open so the Workspace always has a project.
        """
        video_id = _require_str(params, "id")
        project = self._load_or_create_project(video_id)
        return {"project": project.data}

    def project_save(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``project.save({project})`` -> ``{ok}`` (§2). Direct-return."""
        project_data = params.get("project")
        if not isinstance(project_data, dict):
            raise _invalid("project (object) is required")
        video = project_data.get("video") or {}
        video_id = video.get("id") if isinstance(video, dict) else None
        if not isinstance(video_id, str) or not video_id:
            raise _invalid("project.video.id is required to save")
        proj = _library.Project(dict(project_data), manifest_path=self._project_path(video_id))
        proj.save()
        return {"ok": True}

    def project_consolidate(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``project.consolidate({id})`` -> ``{ok, folder}`` (§2). Direct-return."""
        video_id = _require_str(params, "id")
        project = self._load_or_create_project(video_id)
        folder = self.projects_dir / f"{video_id}-consolidated"
        out = project.consolidate(folder)
        return {"ok": True, "folder": out}

    # ===================================================================== #
    # settings.*
    # ===================================================================== #
    def settings_get(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``settings.get()`` -> §2 settings object. Direct-return."""
        return self.settings.get()

    def settings_set(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``settings.set({...})`` -> merged §2 settings object. Direct-return."""
        return self.settings.set(dict(params))

    # ===================================================================== #
    # subtitles.* (generate/edit/export direct; translate = job)
    # ===================================================================== #
    def subtitles_generate(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``subtitles.generate({videoId})`` -> ``{track}`` (§2). Direct-return.

        CONTRACT-NOTE: the pure ``subtitles.generate`` takes a *transcript*; the
        wire sends ``{videoId}``. We load the video's project transcript, generate
        the track, persist it onto the project, and return ``{track}``.
        """
        video_id = _require_str(params, "videoId")
        project = self._load_or_create_project(video_id)
        transcript = project.data.get("transcript")
        if not transcript:
            raise _invalid(f"video {video_id} has no transcript yet (run transcribe.start first)")
        # WU9 wiring: settings['captionPolish'] runs the Netflix CPS/CPL + punct/
        # casing/emphasis/profanity polish over the cues (degrade-safe — model
        # stages skip when their backends are absent). Off -> the plain generate.
        settings = self.settings.get()
        if settings.get("captionPolish"):
            track = _subtitles.generate_polished(transcript, settings=settings)
        else:
            track = _subtitles.generate(transcript)
        _tracks.add_track(project.data, track)
        project.save()
        return {"track": track}

    def subtitles_edit(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``subtitles.edit({trackId, cues})`` -> ``{track}`` (§2). Direct-return."""
        track_id = _require_str(params, "trackId")
        cues = params.get("cues")
        if not isinstance(cues, list):
            raise _invalid("cues (array) is required")
        project = self._find_project_for_track(track_id)
        existing = _tracks.find_track(project.data, track_id)
        updated = _subtitles.edit(existing, cues)
        # Persist the edit back onto the project's track list (immutable replace).
        project.data["tracks"] = [
            updated if (isinstance(t, dict) and t.get("id") == track_id) else t
            for t in project.data.get("tracks") or []
        ]
        project.save()
        return {"track": updated}

    def subtitles_export(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``subtitles.export({trackId, format})`` -> ``{path}`` (§2). Direct-return."""
        track_id = _require_str(params, "trackId")
        fmt = _require_str(params, "format")
        project = self._find_project_for_track(track_id)
        track = _tracks.find_track(project.data, track_id)
        out_path = self.exports_dir / f"{track_id}.{fmt.lower().lstrip('.')}"
        try:
            path = _subtitles.export(track, fmt, out_path)
        except ValueError as exc:
            raise _invalid(str(exc)) from exc
        return {"path": path}

    def subtitles_translate(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``subtitles.translate({trackId, targetLang, bilingual?, order?})`` -> ``{jobId}`` (§2).

        Long job: returns ``{jobId}``, streams ``job.progress``, and its
        ``job.done.result`` is ``{track}``. The pure ``translate`` is synchronous;
        we run it in a job so the contract's ``{jobId}`` + progress shape holds.

        BILINGUAL (captions-export): when ``bilingual`` is truthy the translated
        cues are STACKED with the originals into one track (original + translation
        on two lines per cue, via :func:`subtitles.stack_bilingual`). ``order``
        ("original-first" | "translation-first") picks which line sits on top. The
        stacked track is added as a NEW track on the project (the source track is
        left intact); a monolingual translate still replaces in place as before.
        """
        track_id = _require_str(params, "trackId")
        target_lang = _require_str(params, "targetLang")
        bilingual = bool(params.get("bilingual"))
        order = params.get("order")
        order = order if order in _subtitles.BILINGUAL_ORDERS else "original-first"
        if ctx.jobs is None:
            raise RpcError("no job registry available", ErrorCode.INTERNAL_ERROR)
        # Offline gate: the cloud translation path goes to a remote API; refuse
        # it (typed) when offline. Local (llama) translation stays offline-safe.
        settings_now = self.settings.get()
        if settings_now.get("useCloud"):
            _offline.guard_network(settings_now, "cloud translation")
        project = self._find_project_for_track(track_id)
        track = _tracks.find_track(project.data, track_id)
        translator = self._get_translator()  # None -> legacy injected provider
        legacy_provider = self._provider if translator is None else None
        save_path = project.manifest_path

        def work(job_ctx: Any, _envelope: Any, provider: Any) -> dict[str, Any]:
            if translator is not None:
                # T3 tiered path: language-aware tier routing + fallback chain;
                # tier failures surface via job.done error payload (A6.3).
                translated = translator.translate_track(
                    track,
                    target_lang,
                    progress=lambda pct, msg: job_ctx.progress(pct, msg),
                    cancelled=lambda: job_ctx.cancelled,
                )
            else:
                translated = _subtitles.translate(
                    track,
                    target_lang,
                    provider=provider,
                    progress=lambda pct, msg: job_ctx.progress(pct, msg),
                    cancelled=lambda: job_ctx.cancelled,
                )
            if bilingual:
                # Stack original + translation into a NEW track; keep the source.
                stacked = _subtitles.stack_bilingual(track, translated, order=order)
                _tracks.add_track(project.data, stacked)
                if save_path is not None:
                    project.save(save_path)
                return {"track": stacked}
            # Monolingual: replace the source track in place (legacy behaviour).
            project.data["tracks"] = [
                translated if (isinstance(t, dict) and t.get("id") == track_id) else t
                for t in project.data.get("tracks") or []
            ]
            if save_path is not None:
                project.save(save_path)
            return {"track": translated}

        # WU-envelope: subtitle translation rides the AiJob substrate (shared
        # cancel-check + degrade-aware provider) while keeping the {jobId} shape
        # and the {track} done payload. The legacy injected provider (tests) is
        # passed through; the T3 tiered path ignores the work's provider arg.
        job = self._run_ai_job(
            ctx,
            messages=[{"role": "user", "content": target_lang}],
            model=str(settings_now.get("cloudModel") or ""),
            provider=legacy_provider,
            work=work,
            feature="subtitles",
            label="subtitles.translate",
            videoId=None,
        )
        return {"jobId": job.id}

    # ===================================================================== #
    # tracks.* (list/rename/relabel/add/remove/strip direct; burn = job)
    # ===================================================================== #
    def tracks_list(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``tracks.list({videoId})`` -> ``{tracks}`` (§2). Direct-return."""
        video_id = _require_str(params, "videoId")
        project = self._load_or_create_project(video_id)
        return {"tracks": _tracks.list_tracks(project.data)}

    def tracks_rename(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``tracks.rename({trackId, name})`` -> ``{track}`` (§2). Direct-return."""
        track_id = _require_str(params, "trackId")
        name = _require_str(params, "name")
        project = self._find_project_for_track(track_id)
        try:
            track = _tracks.rename_track(project.data, track_id, name)
        except _tracks.TrackError as exc:
            raise _invalid(str(exc)) from exc
        project.save()
        return {"track": track}

    def tracks_relabel(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``tracks.relabel({trackId, lang})`` -> ``{track}`` (§2). Direct-return."""
        track_id = _require_str(params, "trackId")
        lang = _require_str(params, "lang")
        project = self._find_project_for_track(track_id)
        try:
            track = _tracks.relabel_track(project.data, track_id, lang)
        except _tracks.TrackError as exc:
            raise _invalid(str(exc)) from exc
        project.save()
        return {"track": track}

    def tracks_add(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``tracks.add({videoId, trackId})`` -> ``{ok}`` (§2). Direct-return.

        CONTRACT-NOTE: the wire sends ``{videoId, trackId}`` but the pure
        ``add_track`` needs a *track object*. We locate the track in whatever
        project currently owns it (the available-tracks source) and copy it onto
        the target video's project.
        """
        video_id = _require_str(params, "videoId")
        track_id = _require_str(params, "trackId")
        track = params.get("track")
        if not isinstance(track, dict):
            # Resolve the full track object from the project that owns the id.
            track = _tracks.find_track(self._find_project_for_track(track_id).data, track_id)
        project = self._load_or_create_project(video_id)
        try:
            _tracks.add_track(project.data, track)
        except _tracks.TrackError as exc:
            raise _invalid(str(exc)) from exc
        project.save()
        return {"ok": True}

    def tracks_remove(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``tracks.remove({videoId, trackId})`` -> ``{ok}`` (§2). Direct-return."""
        video_id = _require_str(params, "videoId")
        track_id = _require_str(params, "trackId")
        project = self._load_or_create_project(video_id)
        try:
            _tracks.remove_track(project.data, track_id)
        except _tracks.HardSubtitleError as exc:
            raise _invalid(str(exc)) from exc
        except _tracks.TrackNotFoundError as exc:
            raise _invalid(str(exc)) from exc
        project.save()
        return {"ok": True}

    def tracks_strip(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``tracks.strip({videoId, trackId})`` -> ``{path}`` (§2). Direct-return.

        CONTRACT-NOTE: §2 types strip as a plain ``{path}`` (not a job). We re-mux
        the source omitting the track's subtitle stream via ``strip_track`` (its
        ffmpeg ``run`` seam is injectable for tests).
        """
        video_id = _require_str(params, "videoId")
        _require_str(params, "trackId")
        in_path = self._resolve_video_path(video_id)
        if not in_path:
            raise _invalid(f"unknown video: {video_id}")
        settings = self.settings.get()
        run = self._ffmpeg_run or _self_ffmpeg_run()
        probe = self._ffprobe_duration or _self_ffprobe()
        try:
            path = _tracks.strip_track(in_path, settings=settings, run=run, duration=probe)
        except _tracks.TrackError as exc:
            raise RpcError(str(exc), ErrorCode.INTERNAL_ERROR) from exc
        return {"path": path}

    def tracks_burn(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``tracks.burn({videoId, trackId})`` -> ``{jobId}`` (§2). Job-based.

        Long job: returns ``{jobId}``, streams progress, ``job.done.result`` is
        ``{path}``. Burning re-encodes the video, so it must run as a job.
        """
        video_id = _require_str(params, "videoId")
        track_id = _require_str(params, "trackId")
        if ctx.jobs is None:
            raise RpcError("no job registry available", ErrorCode.INTERNAL_ERROR)
        in_path = self._resolve_video_path(video_id)
        if not in_path:
            raise _invalid(f"unknown video: {video_id}")
        project = self._load_or_create_project(video_id)
        track = _tracks.find_track(project.data, track_id)
        settings = self.settings.get()
        run = self._ffmpeg_run or _self_ffmpeg_run()
        probe = self._ffprobe_duration or _self_ffprobe()

        def job_body(job_ctx: Any) -> dict[str, Any]:
            path = _tracks.burn_track(
                in_path,
                track,
                settings=settings,
                ctx=job_ctx,
                run=run,
                duration=probe,
            )
            return {"path": path}

        job = ctx.jobs.start(job_body)
        return {"jobId": job.id}

    # ===================================================================== #
    # convert.* (both jobs — adapt the factory handlers)
    # ===================================================================== #
    def convert_start(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``convert.start({videoId|path, options})`` -> ``{jobId}`` (§2). Job-based.

        CONTRACT-NOTE (INTEGRATION-REPORT HIGH-1): ``convert.start_handler`` is a
        FACTORY returning a ``(JobContext)->{path}`` body, not a ``(params,ctx)``
        handler. We build the body, start it on ``ctx.jobs``, and return ``{jobId}``.
        """
        if ctx.jobs is None:
            raise RpcError("no job registry available", ErrorCode.INTERNAL_ERROR)
        body = _convert.start_handler(
            params,
            settings=self.settings.get(),
            resolver=self._resolve_video_path,
            run=self._ffmpeg_run or _self_ffmpeg_run(),
            probe=self._ffprobe_duration or _self_ffprobe(),
        )
        job = ctx.jobs.start(body)
        return {"jobId": job.id}

    def convert_batch(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``convert.batch({items})`` -> ``{jobId}`` (§2). Job-based.

        ``job.done.result`` is ``{paths}``. Same factory-adaptation as start.
        """
        if ctx.jobs is None:
            raise RpcError("no job registry available", ErrorCode.INTERNAL_ERROR)
        body = _convert.batch_handler(
            params,
            settings=self.settings.get(),
            resolver=self._resolve_video_path,
            run=self._ffmpeg_run or _self_ffmpeg_run(),
            probe=self._ffprobe_duration or _self_ffprobe(),
        )
        job = ctx.jobs.start(body)
        return {"jobId": job.id}

    # ===================================================================== #
    # transcribe.start (job — handled via transcribe.make_transcribe_handler)
    # ===================================================================== #
    def transcribe_start(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``transcribe.start({videoId, language?})`` -> ``{jobId}`` (§2). Job-based.

        Long job: returns ``{jobId}``, streams progress, ``job.done.result`` is
        ``{transcript}``. On completion the transcript is PERSISTED onto the
        video's project manifest (so subtitles.generate / shortmaker can read it)
        and the library's ``hasTranscript`` flag is flipped.

        CONTRACT-NOTE: we don't call ``_transcribe.make_transcribe_handler``
        directly because its job body only returns ``{transcript}`` — it can't
        persist onto our project store. We reuse ``transcribe.transcribe_file``
        (the pure transcription seam) inside our own job body instead.
        """
        if ctx.jobs is None:
            raise RpcError("no job registry available", ErrorCode.INTERNAL_ERROR)
        video_id = _require_str(params, "videoId")
        language = params.get("language")
        if language is not None and not isinstance(language, str):
            raise _invalid("language must be a string when given")
        audio_path = self._resolve_video_path(video_id)
        if not audio_path:
            raise _invalid(f"unknown video: {video_id}")
        loader = self._whisper_loader or _transcribe.FasterWhisperLoader()
        # WU7 wiring: settings['asrEngine'] picks whisper (default) or parakeet;
        # the duration probe lets parakeet chunk the audio (the hard 6 GB rule).
        settings = self.settings.get()
        probe = self._ffprobe_duration or _self_ffprobe()

        def job_body(job_ctx: Any) -> dict[str, Any]:
            transcript = _transcribe.transcribe_with_engine(
                audio_path,
                loader=loader,
                settings=settings,
                language=language,
                duration_probe=probe,
                on_progress=lambda pct, msg: job_ctx.progress(pct, msg),
                should_cancel=lambda: job_ctx.cancelled,
            )
            transcript = self._maybe_align_words(transcript, audio_path, settings)
            if not job_ctx.cancelled:
                # Persist the transcript onto the project + flip the library flag.
                project = self._load_or_create_project(video_id)
                project.data["transcript"] = transcript
                project.save()
                try:
                    self.library.set_has_transcript(video_id, True)
                except Exception:  # noqa: BLE001 - flag bookkeeping is non-fatal
                    log.warning("set_has_transcript failed for %s", video_id)
            return {"transcript": transcript}

        job = ctx.jobs.start(job_body)
        return {"jobId": job.id}

    def _diarize_backend_factory(self, settings: dict[str, Any]) -> Any:
        """Phase-8: build the diarizer backend selected by settings['diarizeBackend'].

        Delegates to ``pyannote_backend.select_backend_factory`` closed over the
        SpeechBrain default factory: an unknown value keeps the safe speechbrain
        default; ``"pyannote"`` validates the env HF token eagerly (typed refusal,
        no deep 401) before any heavy import.
        """
        from .features import diarize as _diarize  # local: import-light
        from .features import pyannote_backend as _pyannote  # local: import-light

        return _pyannote.select_backend_factory(
            settings,
            speechbrain_factory=_diarize._default_backend_factory,
        )

    def _diarize_models_present(self, settings: dict[str, Any]) -> bool:
        """Phase-8: probe the installed-state of whichever diarize backend is selected.

        Pyannote checks its two gated repos; speechbrain checks the VAD + ECAPA
        assets. Drives the offline gate so a missing-model download is refused for
        the right backend.
        """
        from .features import diarize as _diarize  # local: import-light
        from .features import pyannote_backend as _pyannote  # local: import-light

        if _pyannote.selected_backend_name(settings) == _pyannote.PYANNOTE_BACKEND:
            return _pyannote.default_models_present(settings)
        return _diarize.default_models_present(settings)

    def _maybe_align_words(
        self,
        transcript: dict[str, Any],
        audio_path: str,
        settings: dict[str, Any],
    ) -> dict[str, Any]:
        """WU6 wiring: refine word timings via ctc-forced-aligner when karaoke is on.

        Runs the ctc-forced-aligner 2nd pass on the freshly produced transcript
        when ``settings['karaoke']`` is truthy, giving karaoke-grade per-word
        boundaries the caption builder consumes. ``ctc_align.align_words`` is
        degrade-safe (returns the input unchanged when the model is unavailable
        offline or any backend step fails), so this never crashes the transcribe
        job. No-op (input returned unchanged) when karaoke is off.
        """
        if not settings.get("karaoke"):
            return transcript
        from .features import ctc_align as _ctc_align  # local: import-light seam

        return _ctc_align.align_words(transcript, audio_path, settings=settings)

    # ===================================================================== #
    # system.* + phase8.* (Phase-8 moment-finding tier controls)
    # ===================================================================== #
    def system_probe(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``system.probe()`` -> ``{vramMb, ramMb, cpuCount, gpuPresent}``. Direct-return.

        Probes the host hardware (GPU VRAM / RAM / CPU count) via the injectable
        :class:`~media_studio.features.system_advisor.HardwareProbe` seam. Every
        probe is fail-open (a missing dep degrades to ``None``), so this never
        raises. The default seam lazily tries pynvml -> nvidia-smi -> torch.cuda
        for VRAM and psutil -> os for RAM; tests inject a fake probe.
        """
        probe = self._hardware_probe or self._default_hardware_probe()
        hw = probe.detect()
        return {
            "vramMb": hw.vram_mb,
            "ramMb": hw.ram_mb,
            "cpuCount": hw.cpu_count,
            "gpuPresent": hw.gpu_present,
        }

    def system_advisor(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``system.advisor({commercial?})`` -> AdvisorReport JSON. Direct-return.

        The "Models & System" panel brain: probes hardware + dependency
        availability, checks which model weights are already installed (the asset
        manager), and returns each component's quality-vs-cost verdict + the rolled
        -up runnable tiers + the recommended preset. Honors Offline mode (a missing
        weight that would need a download counts as unavailable). Pure decision
        logic; nothing heavy is imported.
        """
        from .features import system_advisor as _sa  # local: import-light

        settings = self.settings.get()
        commercial = bool(params.get("commercial", settings.get("commercial")))
        probe = self._hardware_probe or self._default_hardware_probe()
        report = _sa.advise_for_hardware(
            probe=probe,
            commercial=commercial,
            models_present=self._models_present_map(settings),
            offline=_offline.is_offline(settings),
        )
        return _advisor_report_to_wire(report)

    def asr_engines(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``asr.engines()`` -> ``{engines:[{id, label, installed}]}``. Direct-return.

        Lists the selectable ASR engines (whisper default / parakeet opt-in) with
        an installed flag per engine (drives the ASR picker UI). Whisper is treated
        as always available (the always-installed default); parakeet's installed
        flag reflects whether its weights are cached.
        """
        settings = self.settings.get()
        installed = self._models_present_map(settings)
        return {
            "engines": [
                {"id": "whisper", "label": "Whisper large-v3-turbo", "installed": True},
                {
                    "id": "parakeet",
                    "label": "Parakeet-TDT-0.6b-v3 (multilingual)",
                    "installed": bool(installed.get("parakeet", False)),
                },
            ]
        }

    def phase8_signals(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``phase8.signals({videoId, tier?})`` -> ``{jobId}``. Job-based.

        Runs the enabled Wave-1 signal modules at the chosen tier over the video's
        media and returns a per-channel summary + a present map. Heavy (loads ML
        models), so it runs on ``ctx.jobs`` and the heavy compute lives behind the
        injectable :func:`phase8_runner` seam (tests inject a fake that returns
        canned tracks). ``job.done.result`` is ``{tracks, present}``.
        """
        if ctx.jobs is None:
            raise RpcError("no job registry available", ErrorCode.INTERNAL_ERROR)
        video_id = _require_str(params, "videoId")
        path = self._resolve_video_path(video_id)
        if not path:
            raise _invalid(f"unknown video: {video_id}")
        settings = self.settings.get()
        tier = _coerce_tier(params.get("tier"), settings)
        runner = self._phase8_runner or self._default_phase8_runner()
        probe = self._ffprobe_duration or _self_ffprobe()

        def job_body(job_ctx: Any) -> dict[str, Any]:
            tracks = runner(
                path,
                tier=tier,
                settings=settings,
                duration_probe=probe,
                on_progress=lambda pct, msg: job_ctx.progress(pct, msg),
                should_cancel=lambda: job_ctx.cancelled,
            )
            return _signals_summary(tracks)

        job = ctx.jobs.start(job_body)
        return {"jobId": job.id}

    def phase8_select(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``phase8.select({videoId, prompt?, controls?, tier?})`` -> ``{jobId}``. Job-based.

        The unified tri-modal selector: computes the Wave-1 signal tracks (via the
        phase8 runner seam), then calls :func:`select.select_unified` with those
        tracks + the persisted transcript + the chosen tier. Caches the resulting
        candidates server-side (the same "rank@sourceStart" cache shortmaker.export
        consults) and returns ``{candidates}`` on done. Coexists with the legacy
        transcript-only ``shortmaker.select``.
        """
        if ctx.jobs is None:
            raise RpcError("no job registry available", ErrorCode.INTERNAL_ERROR)
        video_id = _require_str(params, "videoId")
        path = self._resolve_video_path(video_id)
        if not path:
            raise _invalid(f"unknown video: {video_id}")
        settings = self.settings.get()
        tier = _coerce_tier(params.get("tier"), settings)
        prompt = str(params.get("prompt") or "")
        controls = params.get("controls") or {}
        transcript = self._load_or_create_project(video_id).data.get("transcript")
        runner = self._phase8_runner or self._default_phase8_runner()
        probe = self._ffprobe_duration or _self_ffprobe()

        def work(job_ctx: Any, _envelope: Any, provider: Any) -> dict[str, Any]:
            from .features import select as _select  # local: import-light

            tracks = runner(
                path,
                tier=tier,
                settings=settings,
                duration_probe=probe,
                on_progress=lambda pct, msg: job_ctx.progress(pct, msg),
                should_cancel=lambda: job_ctx.cancelled,
            )
            candidates = _select.select_unified(
                transcript,
                prompt,
                cast("Any", controls),
                provider,
                tracks=tracks,
                tier=tier,
            )
            resolved = cast("list[Candidate]", list(candidates))
            self._cache_candidates(video_id, resolved)
            return {"candidates": resolved}

        # WU-envelope: the AI re-rank/select rides the AiJob substrate so it gets
        # the shared cancel-check + degrade-aware provider + (later) cost/cache
        # while preserving the {jobId} shape and the {candidates} done payload.
        job = self._run_ai_job(
            ctx,
            messages=[{"role": "user", "content": prompt}],
            model=str(settings.get("cloudModel") or ""),
            provider=self._provider,
            work=work,
            feature="phase8",
            label="phase8.select",
            videoId=video_id,
        )
        return {"jobId": job.id}

    def _models_present_map(self, settings: dict[str, Any]) -> dict[str, bool]:
        """Map each model-backed advisor component -> is its weight installed.

        Probes the asset manager for each Phase-8 component's pinned asset so the
        advisor (and the ASR picker) can report installed-state + degrade an
        offline-missing model. Components with no registered asset are omitted
        (the advisor then treats them as not-installed). Fail-open: a probe error
        for one component marks it absent, never crashes the report.
        """
        from .assets import manifest as _manifest  # local: import-light
        from .assets.manager import AssetManager  # local: import-light

        mgr = AssetManager(root=self.data_dir, settings_provider=lambda: settings)
        present: dict[str, bool] = {}
        for component, asset_name in _COMPONENT_ASSETS.items():
            entry = _manifest.get_asset(asset_name)
            if entry is None:
                continue
            try:
                present[component] = mgr.installed_path(entry) is not None
            except Exception:  # noqa: BLE001 - one bad probe must not sink the report
                present[component] = False
        return present

    def _default_hardware_probe(self) -> Any:  # pragma: no cover - lazy heavy seam (pynvml/torch); tests inject a fake
        """Build the real :class:`HardwareProbe` (lazy import; runtime only)."""
        from .features import system_advisor as _sa  # noqa: PLC0415 - lazy

        return _sa.HardwareProbe()

    def _default_phase8_runner(self) -> Callable[..., dict[str, Any]]:
        """Resolve the real Wave-1 signal-compute runner (lazy; runtime only).

        Returns the module-level :func:`_run_phase8_signals` which loads + runs the
        heavy Wave-1 signal modules. Kept behind a method so tests can inject a fake
        ``phase8_runner`` instead and never touch torch / transformers / cv2.
        """
        return _run_phase8_signals

    # ===================================================================== #
    # shortmaker.* (both jobs — via ShortMaker with selection caching)
    # ===================================================================== #
    def _shortmaker(self) -> _shortmaker.ShortMaker:
        """Build a ShortMaker bound to our context loader + selection cache."""
        return _shortmaker.ShortMaker(
            load_context=self._shortmaker_context,
            out_dir_for=lambda vid: str(self.exports_dir / f"shorts-{vid}"),
            stages=_shortmaker.Stages(),
            settings_provider=self.settings.get,
        )

    def _detect_boundaries(self, video_id: str) -> dict[str, Any]:
        """Run the silence + scene-cut detectors for a video's path.

        CONTRACT-NOTE: ``_lazy_snap`` reads ``settings["silences"]`` /
        ``settings["sceneCuts"]`` which nothing fills. We detect them here (ffmpeg
        silencedetect + PySceneDetect, both behind the boundary seams) and inject
        them into the settings dict the select job uses, so boundary-snap has real
        silence + scene targets — not just sentence ends. Detection failures fall
        back to empty lists (snap then uses sentence ends only).
        """
        path = self._resolve_video_path(video_id)
        if not path:
            return {"silences": [], "sceneCuts": []}
        silences = _boundary.detect_silences(path, settings=self.settings.get(), run=self._silence_run)
        scene_cuts = _boundary.detect_scene_cuts(path, detector=self._scene_detector)
        return {"silences": list(silences), "sceneCuts": list(scene_cuts)}

    def _shortmaker_context(self, video_id: str) -> dict[str, Any]:
        """Load a video's path + transcript + the cached candidate map.

        CONTRACT-NOTE (HIGH-3): exposes the cached select result under
        ``"candidates"`` (id -> Candidate), which ``ShortMaker._resolve_candidates``
        consults when the UI sends only ``candidateIds``.

        CONTRACT-NOTE (A2 audioTrackId): also exposes the manifest's A3
        ``Project.audioTracks`` under ``"audioTracks"`` so the export pipeline
        can resolve ``shortmaker.export``'s optional ``audioTrackId`` and mux
        the chosen track onto each exported clip.
        """
        path = self._resolve_video_path(video_id) or ""
        transcript = None
        audio_tracks: list[dict[str, Any]] = []
        manifest = self._project_path(video_id)
        if manifest.exists():
            try:
                data = _library.Project.open(manifest).data
                transcript = data.get("transcript")
                audio_tracks = list(data.get("audioTracks") or [])
            except Exception:  # noqa: BLE001 - a bad manifest just means no transcript
                transcript = None
                audio_tracks = []
        # P4 §3: the source video title for the persisted ShortInfo metadata.
        video = self.library.get(video_id)
        source_title = str((video or {}).get("title") or "")
        return {
            "path": path,
            "transcript": transcript,
            "sourceTitle": source_title,
            "candidates": self._selection_cache.get(video_id, {}),
            "audioTracks": audio_tracks,
        }

    def shortmaker_select(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``shortmaker.select({videoId, prompt, controls})`` -> ``{jobId}`` (§2).

        Wraps the feature pipeline so (a) boundary detectors feed the snap stage
        and (b) the produced candidates are cached server-side (keyed by
        "rank@sourceStart") for a later ``shortmaker.export``.
        """
        if ctx.jobs is None:
            raise RpcError("no job registry available", ErrorCode.INTERNAL_ERROR)
        video_id = _require_str(params, "videoId")
        sm = self._shortmaker()

        def handler(job_ctx: Any) -> dict[str, Any]:
            settings = dict(self.settings.get())
            # Feed the real silence + scene-cut detectors into the snap settings.
            settings.update(self._detect_boundaries(video_id))
            result = _shortmaker.run_select(
                job_ctx,
                video_id=video_id,
                prompt=str(params.get("prompt") or ""),
                controls=params.get("controls") or {},
                load_context=self._shortmaker_context,
                stages=sm.stages,
                settings=settings,
            )
            self._cache_candidates(video_id, result.get("candidates") or [])
            return result

        job = ctx.jobs.start(handler)
        return {"jobId": job.id}

    def shortmaker_export(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``shortmaker.export({videoId, candidateIds})`` -> ``{jobId}`` (§2).

        Resolution uses the cached select result (HIGH-3): the UI's
        ``candidateIds`` ("rank@sourceStart") index into the per-video cache, so
        export carves the real clips. The UI may also forward full ``candidates``.
        A2's optional ``audioTrackId`` (plus T4b's ``captionStyle`` /
        ``reframeEngine``) flows through ``params`` into ``ShortMaker.export``;
        the AudioTrack itself is resolved against ``_shortmaker_context``'s
        ``audioTracks``.
        """
        if ctx.jobs is None:
            raise RpcError("no job registry available", ErrorCode.INTERNAL_ERROR)
        sm = self._shortmaker()
        return sm.export(params, ctx)

    # ===================================================================== #
    # nle.* — EDL / CSV timeline export (captions-export)
    # ===================================================================== #
    def _approved_clips(self, video_id: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        """Resolve the approved clips to export for ``video_id``.

        Prefers an explicit ``clips`` array on ``params`` (so the UI can export the
        just-produced batch before manifest persistence); otherwise reads the
        project manifest's persisted ``clips`` (the ``{candidate, path}`` records
        the short-maker export carved). Returns ``[]`` when neither has clips.
        """
        explicit = params.get("clips")
        if isinstance(explicit, list) and explicit:
            return [c for c in explicit if isinstance(c, dict)]
        project = self._load_or_create_project(video_id)
        return [c for c in (project.data.get("clips") or []) if isinstance(c, dict)]

    def nle_export(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``nle.export({videoId, format?, fps?, title?, clips?})`` -> ``{path}`` (captions-export).

        Export the approved clips of a video as an editable NLE timeline: a
        CMX3600 ``.edl`` (default) or a ``.csv`` for Premiere / DaVinci Resolve.
        ``fps`` is one of 24/25/30/60 (default 30); ``title`` names the sequence.
        Per-clip reel names come from each candidate's optional ``reel``. Direct-
        return ``{path}`` (the build is fast, pure-Python — no job needed).
        """
        video_id = _require_str(params, "videoId")
        fmt = str(params.get("format") or "edl")
        fps = params.get("fps", 30)
        title = params.get("title")
        if not isinstance(title, str) or not title:
            video = self.library.get(video_id)
            title = str((video or {}).get("title") or "Media Studio Timeline")
        clips = self._approved_clips(video_id, params)
        try:
            out_path = self.exports_dir / f"{video_id}-timeline.{_nle_export.normalize_format(fmt)}"
            path = _nle_export.export(clips, out_path, fmt=fmt, fps=fps, title=title)
        except ValueError as exc:
            raise _invalid(str(exc)) from exc
        return {"path": path, "clipCount": len(clips)}

    # ===================================================================== #
    # package.* — ZIP "package for upload" (captions-export)
    # ===================================================================== #
    def package_export(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``package.export({path, suggestion?})`` -> ``{path, manifest}`` (captions-export).

        Bundle ONE produced short (its rendered ``<clip>.mp4`` + thumbnail + a
        suggested title/description/tags ``upload.json``) into a ``.zip`` for
        manual posting. ``path`` is the exported clip; the clip's sidecar
        ``<clip>.json`` metadata drives the suggested copy (an optional
        ``suggestion`` override wins per-field). The clip MUST live inside the
        exports root (path-traversal guard). Direct-return.
        """
        clip_path = _require_str(params, "path")
        resolved = Path(clip_path).resolve()
        root = self.exports_dir.resolve()
        try:
            resolved.relative_to(root)
        except ValueError:
            raise _invalid(f"path is outside the exports root: {clip_path}") from None
        if not resolved.exists():
            raise _invalid(f"short not found: {clip_path}")
        meta = _shorts_meta.read_metadata(resolved) or {}
        thumb = _shorts_meta.thumbnail_path(resolved)
        suggestion = params.get("suggestion")
        suggestion = suggestion if isinstance(suggestion, dict) else None
        out_zip = resolved.with_name(resolved.stem + ".package.zip")
        try:
            result = _package_export.package(
                resolved,
                out_zip,
                meta=meta,
                thumbnail_path=thumb if thumb.exists() else None,
                suggestion=suggestion,
            )
        except FileNotFoundError as exc:
            raise _invalid(str(exc)) from exc
        return result

    def _cache_candidates(self, video_id: str, candidates: list[Candidate]) -> None:
        """Cache select candidates keyed by "rank@sourceStart" (the UI's id form)."""
        by_id: dict[str, Candidate] = {}
        for cand in candidates:
            cid = self.candidate_id(cand)
            by_id[cid] = cand
        self._selection_cache[video_id] = by_id

    @staticmethod
    def candidate_id(candidate: Candidate) -> str:
        """Stable candidate id matching ShortMaker.tsx's ``candidateId`` ("rank@sourceStart").

        CONTRACT-NOTE: the renderer builds ``${rank}@${sourceStart}``; we mirror it
        exactly. ``sourceStart`` is rendered the way JS ``String(number)`` would
        (an integer-valued float prints without a trailing ".0").
        """
        rank = candidate.get("rank")
        src = candidate.get("sourceStart", candidate.get("start", 0.0))
        return f"{rank}@{_js_number(src)}"

    # ===================================================================== #
    # provider seam
    # ===================================================================== #
    def _get_provider(self) -> Any:
        """Return the LLM provider for translation (cached test seam or real)."""
        if self._provider is not None:
            return self._provider
        from .models import provider as _provider_mod  # local import: heavy seam

        return _provider_mod.get_provider(self.settings.get())

    def _ai_cache(self) -> Any:
        """The shared AI-call content cache (WU-cache), under the data dir.

        Honors ``settings.aiCacheDir`` (absolute path) when set, else
        ``data_dir/ai-cache``. The cache is local-only; nothing leaves the box.
        """
        from .models.ai_cache import DEFAULT_CACHE_DIRNAME, AiCache  # local: import-light

        configured = self.settings.get().get("aiCacheDir")
        store_dir = Path(configured) if configured else self.data_dir / DEFAULT_CACHE_DIRNAME
        return AiCache(store_dir=store_dir)

    def _ai_pool(self) -> Any:
        """Build the rotation pool (WU-pool) from settings for budget/route reads.

        Returns an object whose ``.entries`` (each carrying ``.provider`` /
        ``.local``) satisfy :func:`budget.estimate`'s pool shape. The real path
        builds a :class:`RotatingProvider` with detection OFF (planning only reads
        the catalog-shaped entries; skipping the live ``GET /models`` probe keeps
        ai.planJob / the plan step socket-free — PLAN: ZERO provider calls). When
        the provider module is a test stub WITHOUT ``build_pool_provider`` we fall
        back to a local-only pool (the budget then reports local-only, no egress).
        """
        from .models import provider as _provider_mod  # local: heavy seam

        builder = getattr(_provider_mod, "build_pool_provider", None)
        if builder is None:
            return _LocalOnlyPool()
        return builder(self.settings.get(), detect_local=False)

    def plan_ai_job_envelope(self, inputs: Any) -> Any:
        """Assemble an :class:`ai_job.AiJob` envelope for ``inputs`` (PURE, no calls).

        Shared by ``ai.planJob`` (pre-flight) and the AI-bearing job handlers so
        cost/route/cacheKey are derived from ONE place. Performs ZERO provider
        calls — the pool is built only to read its catalog-shaped ``.entries``.
        """
        from .models import ai_job as _ai_job  # local: import-light

        return _ai_job.plan_ai_job(
            inputs,
            pool=self._ai_pool(),
            catalog=_ai_job.CatalogFreeCapAdapter(),
            cache=self._ai_cache(),
        )

    def _run_ai_job(
        self,
        ctx: RpcContext,
        *,
        messages: list[dict[str, str]],
        model: str,
        provider: Any,
        work: Any,
        feature: str,
        label: str,
        videoId: str | None = None,  # noqa: N803 - wire-name kwarg (matches JobRegistry)
    ) -> Any:
        """Plan + run an :class:`ai_job.AiJob` on ``ctx.jobs`` with a custom ``work``.

        ``provider`` is the resolved provider the work consumes; when ``None`` the
        pool-aware ``get_provider`` is built lazily (so rotation + degrade tracking
        apply). The envelope's cost/route/cacheKey come from
        :meth:`plan_ai_job_envelope`. Returns the created job (the ``{jobId}``
        source). The work's own result dict is the ``job.done`` payload.
        """
        from .models import ai_job as _ai_job  # local: import-light

        inputs = _ai_job.AiInputs(
            messages=tuple({str(k): str(v) for k, v in m.items()} for m in messages),
            model=model,
        )
        envelope = self.plan_ai_job_envelope(inputs)

        def _factory() -> Any:
            if provider is not None:
                return provider
            from .models import provider as _provider_mod  # local: heavy seam

            return _provider_mod.get_provider(self.settings.get())

        return _ai_job.run_ai_job(
            envelope,
            jobs=ctx.jobs,
            provider_factory=_factory,
            cache=self._ai_cache(),
            work=work,
            feature=feature,
            label=label,
            videoId=videoId,
        )

    def ai_plan_job(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``ai.planJob({messages?, model?, params?, request?, capability?})`` -> pre-flight.

        Returns ``{route, costEst, cacheHit, willEgress, budget, preview, cacheKey}``
        WITHOUT executing any AI call (PLAN acceptance: ZERO provider calls). The
        request shape is the budget request (``target_size`` / ``text_bytes`` /
        ``frame_bytes``); ``messages`` feed the cache key so the pre-flight knows
        whether a real run would be a cache hit.
        """
        from .models import ai_job as _ai_job  # local: import-light

        raw_messages = params.get("messages")
        messages = tuple(
            {str(k): str(v) for k, v in m.items()}
            for m in raw_messages
            if isinstance(m, dict)
        ) if isinstance(raw_messages, list) else ()
        request = self._budget_request(params.get("request"))
        inputs = _ai_job.AiInputs(
            messages=messages,
            model=str(params.get("model") or ""),
            params=dict(params.get("params") or {}),
            request=request,
            capability=str(params.get("capability") or "text"),
        )
        return self.plan_ai_job_envelope(inputs).planned()

    @staticmethod
    def _budget_request(raw: Any) -> Any:
        """Coerce a wire ``request`` dict into a budget request (or ``None``).

        The returned :class:`_BudgetRequest` satisfies the duck-typed
        ``budget.BudgetRequest`` protocol (``target_size`` / ``text_bytes`` /
        ``frame_bytes``). A non-dict ``raw`` yields ``None`` (an unsized request).
        """
        if not isinstance(raw, dict):
            return None
        size = raw.get("targetSize")
        return _BudgetRequest(
            target_size=int(size) if isinstance(size, int) else None,
            text_bytes=int(raw.get("textBytes") or 0),
            frame_bytes=int(raw.get("frameBytes") or 0),
        )

    def _get_model_runner(self) -> Any:
        """The shared ModelRunner (lazily built from settings; T3)."""
        if self._model_runner is None:
            from .models import runner as _runner_mod  # local import: heavy seam

            self._model_runner = _runner_mod.ModelRunner(self.settings.get())
        return self._model_runner

    def _get_translator(self) -> Any | None:
        """TieredTranslator for subtitles.translate (T3).

        Returns ``None`` when a legacy ``provider`` seam was injected (tests):
        the caller then keeps the original single-provider path, so every
        existing handler test stays green.
        """
        if self._provider is not None:
            return None
        from .models import translation as _translation_mod  # local import

        return _translation_mod.get_translator(self.settings.get(), runner=self._get_model_runner())

    def _dub_translator(self) -> Any:
        """Adapt T3's TieredTranslator to dub's text-based Translator seam.

        CONTRACT-NOTE (WIRING-T2 §2): ``tts.dub.Translator`` is
        ``translate(texts, target_lang, source_lang) -> texts`` + ``free()``;
        T3's TieredTranslator is cue-based and exposes no ``free``. This
        adapter wraps texts into cue dicts (timings unused by MT) and frees the
        MT model by stopping the shared llama server — the batched 'free MT'
        stage between translate-ALL and synth-ALL (A4).
        """
        from .models import translation as _translation_mod  # local: heavy seam

        runner = self._get_model_runner()
        tiered = _translation_mod.get_translator(self.settings.get(), runner=runner)

        class _DubTranslator:
            def translate(
                self,
                texts: list[str],
                target_lang: str,
                source_lang: str | None = None,
            ) -> list[str]:
                cues = [{"index": i + 1, "start": 0.0, "end": 0.0, "text": str(t)} for i, t in enumerate(texts)]
                out = tiered.translate(cues, target_lang, source_lang=source_lang)
                return [str(c.get("text", "")) for c in out]

            def free(self) -> None:
                try:
                    runner.stop_server()
                except Exception:  # noqa: BLE001 - freeing is best-effort
                    log.warning("MT free: stop_server failed")

        return _DubTranslator()


# --------------------------------------------------------------------------- #
# small helpers (kept module-level so the seams stay import-light)
# --------------------------------------------------------------------------- #
def _self_ffmpeg_run() -> Callable[..., int]:
    """The default ffmpeg ``run`` (imported lazily to keep this module light)."""
    from . import ffmpeg as _ffmpeg

    return _ffmpeg.run


def _self_ffprobe() -> Callable[..., float]:
    """The default ffprobe duration probe (lazy import)."""
    from . import ffmpeg as _ffmpeg

    return _ffmpeg.ffprobe_duration


def _js_number(value: Any) -> str:
    """Render a number the way JavaScript ``String(n)`` would (for candidate ids).

    JS prints ``5`` for ``5.0`` and ``5.5`` for ``5.5``. Python's ``str(5.0)`` is
    ``"5.0"``, so an integer-valued float must drop the ``.0`` to match the UI's
    ``${c.sourceStart}`` template, otherwise the cached id never matches.
    """
    try:
        num = float(value)
    except (TypeError, ValueError):
        return str(value)
    if num.is_integer():
        return str(int(num))
    return repr(num)


# --------------------------------------------------------------------------- #
# Phase-8 wiring helpers (pure; the heavy runner stays pragma-excluded)
# --------------------------------------------------------------------------- #
#: advisor component name -> its registered manifest asset name (the installed
#: -state probe key). Components with no own asset (motion/diversity/ranker are
#: zero-download floors) are absent; ``aesthetic`` shares the SigLIP-2 backbone.
_COMPONENT_ASSETS: dict[str, str] = {
    "saliency": "vinet-s-saliency",
    "audio_saliency": "panns-cnn14",
    "scene_transnet": "transnetv2-pytorch",
    "vlm_backbone": "siglip2-so400m",
    "aesthetic": "siglip2-so400m",
    "quality_gate": "dover-mobile-quality",
    "emotion": "hsemotion-onnx",
    "ocr": "rapidocr-onnx",
    "parakeet": "parakeet-tdt-0.6b-v3",
    "ctc_aligner": "ctc-forced-aligner-mms",
    "pyannote": "pyannote-speaker-diarization-31",
    "smolvlm2": "smolvlm2-2.2b",
}

#: settings key picking the Phase-8 moment-finding tier (0/1/2).
PHASE8_TIER_KEY = "phase8Tier"


def _coerce_tier(value: Any, settings: dict[str, Any]) -> int:
    """Resolve the Phase-8 tier: explicit ``value`` wins, else settings, else 1.

    Clamped to 0..2 (the three runnable presets). Any non-integer / out-of-range
    input falls back to the Tier-1 default so a typo never breaks a select.
    """
    raw = value if value is not None else settings.get(PHASE8_TIER_KEY, 1)
    try:
        tier = int(raw)
    except (TypeError, ValueError):
        return 1
    return min(2, max(0, tier))


def _signals_summary(tracks: dict[str, Any]) -> dict[str, Any]:
    """Summarize computed signal tracks -> ``{tracks:{ch:count}, present:{ch:bool}}``.

    A JSON-safe digest of the per-channel :class:`SignalTrack` map (the heavy
    runner's output): per-channel signal count + present flag. Keeps the wire
    payload small (the raw signals stay server-side for the select path).
    """
    counts: dict[str, int] = {}
    present: dict[str, bool] = {}
    for channel, track in tracks.items():
        counts[channel] = len(getattr(track, "signals", ()) or ())
        present[channel] = bool(getattr(track, "present", False))
    return {"tracks": counts, "present": present}


def _advisor_report_to_wire(report: Any) -> dict[str, Any]:
    """Convert an :class:`AdvisorReport` frozen tree to the camelCase wire dict.

    Mirrors the renderer's ``AdvisorReport`` TS type (components/tiers/
    recommendedPreset/vramBudgetMb/notes), so the panel maps it 1:1 without a
    snake_case shim.
    """
    return {
        "components": [
            {
                "name": c.name,
                "present": c.present,
                "verdict": c.verdict,
                "vramMb": c.vram_mb,
                "licenseCommercialOk": c.license_commercial_ok,
                "reason": c.reason,
            }
            for c in report.components
        ],
        "tiers": [
            {"tier": t.tier, "label": t.label, "verdict": t.verdict, "components": list(t.components)}
            for t in report.tiers
        ],
        "recommendedPreset": report.recommended_preset,
        "vramBudgetMb": report.vram_budget_mb,
        "notes": list(report.notes),
    }


def _run_phase8_signals(  # pragma: no cover - heavy Wave-1 signal compute (torch/cv2/transformers); tests inject a fake runner
    media_path: str,
    *,
    tier: int,
    settings: dict[str, Any],
    duration_probe: Callable[[str], float],
    on_progress: Callable[[float, str], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Run the enabled Wave-1 signal modules for ``media_path`` at ``tier``.

    The real (heavy) signal-compute path: motion always (Tier-0 floor), plus the
    Tier-1 visual/audio model tracks. Each module degrades to ``present=False``
    when its weights are missing offline (the §-signal rule), so this returns a
    partial map on any machine. Excluded from coverage — it imports the heavy ML
    backends; the pure shaping (:func:`_signals_summary`) and the select wiring are
    covered with an injected fake runner.
    """
    from .features import (  # noqa: PLC0415 - lazy heavy seam
        audio_saliency as _audio_saliency,
    )
    from .features import (
        motion as _motion,
    )

    duration = duration_probe(media_path)
    tracks: dict[str, Any] = {}
    # motion / saliency / scene_transnet each return a SINGLE SignalTrack (keyed by
    # its ``.channel``); audio_saliency / vlm_backbone return a dict[channel,track].
    motion_track = _motion.compute_motion_signals(media_path, duration, settings=settings)
    tracks[motion_track.channel] = motion_track
    if tier >= 1:
        from .features import saliency as _saliency  # noqa: PLC0415
        from .features import scene_transnet as _scene_transnet  # noqa: PLC0415
        from .features import vlm_backbone as _vlm_backbone  # noqa: PLC0415

        tracks.update(_audio_saliency.compute_audio_signals(media_path, duration, settings=settings))
        sal = _saliency.compute_saliency_signals(media_path, duration, settings=settings)
        tracks[sal.channel] = sal
        scene = _scene_transnet.compute_scene_signals(media_path, duration, settings=settings)
        tracks[scene.channel] = scene
        tracks.update(_vlm_backbone.compute_backbone_signals(media_path, duration, settings=settings))
    if on_progress is not None:
        on_progress(100.0, "signals done")
    _ = should_cancel
    return tracks


# --------------------------------------------------------------------------- #
# registration
# --------------------------------------------------------------------------- #
def register_all(
    services: Services | None = None,
    *,
    register: Callable[[str, Any], None] | None = None,
) -> Services:
    """Register every §2 method handler on ``protocol.METHODS``; return the Services.

    Idempotent only across a fresh registry: ``protocol.register`` raises on a
    duplicate name (a typo/double-wire fails loudly at startup). ``services`` and
    ``register`` are injectable for tests (a tmp-dir Services + a fake registrar).
    """
    svc = services or Services()
    reg = register if register is not None else protocol.register

    reg("library.list", svc.library_list)
    reg("library.add", svc.library_add)
    reg("library.remove", svc.library_remove)

    reg("project.open", svc.project_open)
    reg("project.save", svc.project_save)
    reg("project.consolidate", svc.project_consolidate)

    reg("settings.get", svc.settings_get)
    reg("settings.set", svc.settings_set)

    reg("transcribe.start", svc.transcribe_start)

    reg("subtitles.generate", svc.subtitles_generate)
    reg("subtitles.edit", svc.subtitles_edit)
    reg("subtitles.translate", svc.subtitles_translate)
    reg("subtitles.export", svc.subtitles_export)

    reg("tracks.list", svc.tracks_list)
    reg("tracks.rename", svc.tracks_rename)
    reg("tracks.relabel", svc.tracks_relabel)
    reg("tracks.add", svc.tracks_add)
    reg("tracks.remove", svc.tracks_remove)
    reg("tracks.burn", svc.tracks_burn)
    reg("tracks.strip", svc.tracks_strip)

    reg("convert.start", svc.convert_start)
    reg("convert.batch", svc.convert_batch)

    reg("shortmaker.select", svc.shortmaker_select)
    reg("shortmaker.export", svc.shortmaker_export)

    # Phase-8 moment-finding: system probe/advisor + ASR-engine list + the unified
    # tri-modal signals/select. system.* + asr.engines are direct (cheap probes);
    # phase8.* are long jobs (load heavy models behind the phase8 runner seam).
    reg("system.probe", svc.system_probe)
    reg("system.advisor", svc.system_advisor)
    reg("asr.engines", svc.asr_engines)
    reg("phase8.signals", svc.phase8_signals)
    reg("phase8.select", svc.phase8_select)

    # WU-envelope: AI-Job pre-flight. ai.planJob returns the route + cost/egress
    # budget + cacheHit/willEgress with ZERO provider calls (the pure planner).
    reg("ai.planJob", svc.ai_plan_job)

    # captions-export: EDL/CSV NLE timeline export + ZIP package-for-upload.
    reg("nle.export", svc.nle_export)
    reg("package.export", svc.package_export)

    # ---------------------------------------------------------------------- #
    # P2 addendum methods (A2) — feature modules ship their own register()
    # ---------------------------------------------------------------------- #
    # media.* (U1): playable verdict + playback proxy.
    _media_compat.register(
        resolver=svc._resolve_video_path,
        settings_provider=svc.settings.get,
        register_fn=reg,
    )

    # timeline.peaks (T1): direct-return waveform peaks (cached on disk).
    _timeline.register(
        resolver=svc._resolve_video_path,
        settings_provider=svc.settings.get,
        register_fn=reg,
    )

    # tracks.audio.* + tts.* (A2): registered via the modules' own register()
    # so they bind to the services' library/projects/settings (T2).
    from .features import tracks_audio as _tracks_audio  # local: import-light
    from .features import tts as _tts

    def _load_project_data(video_id: str) -> dict[str, Any]:
        return svc._load_or_create_project(video_id).data

    def _save_project_data(video_id: str, data: dict[str, Any]) -> None:
        _library.Project(dict(data), manifest_path=svc._project_path(video_id)).save()

    def _load_subtitle_track(video_id: str, track_id: str) -> dict[str, Any]:
        project = svc._load_or_create_project(video_id)
        try:
            return _tracks.find_track(project.data, track_id)
        except _tracks.TrackError as exc:
            raise _invalid(str(exc)) from exc

    audio_tracks_svc = _tracks_audio.register(
        resolver=svc._resolve_video_path,
        load_project=_load_project_data,
        save_project=_save_project_data,
        settings_provider=svc.settings.get,
        run=svc._ffmpeg_run,  # None -> the real drained ffmpeg.run
        duration=svc._ffprobe_duration,
        register_fn=reg,
    )
    _tts.register(
        resolver=svc._resolve_video_path,
        load_track=_load_subtitle_track,
        audio_tracks=audio_tracks_svc,
        settings_provider=svc.settings.get,
        translator_factory=svc._dub_translator,  # T3 seam adapter (WIRING-T2 §2)
        media_duration=(svc._ffprobe_duration or _self_ffprobe()),
        out_dir=str(svc.data_dir / "dubs"),
        register_fn=reg,
    )

    # feedback.* (P3-D): the flywheel store registers its own two methods.
    from .features import feedback as _feedback  # local: import-light

    _feedback.register(register_fn=reg)

    # shorts.* (P4 §2/C6): the shorts library registers its own four methods,
    # bound to the same exports root + per-video out-dir layout the short-maker
    # export uses (Services.exports_dir / "shorts-<videoId>").
    from .features import shorts as _shorts  # local: import-light

    _shorts.register(
        exports_dir=svc.exports_dir,
        out_dir_for=lambda vid: str(svc.exports_dir / f"shorts-{vid}"),
        settings_provider=svc.settings.get,
        run=svc._ffmpeg_run,  # None -> the real drained ffmpeg.run
        register_fn=reg,
    )

    # captions.cues (P4 §2/C6/C7): NET-NEW WORD-level cues for the live preview
    # overlay, built from the persisted transcript via the SAME context loader
    # the short-maker uses. The module owns its own register() (mirrors shorts).
    from .features import cues as _cues  # local: import-light

    _cues.register(load_context=svc._shortmaker_context, register_fn=reg)

    # audio-stabilize group (NET-NEW): the three transport-agnostic engine
    # features each own their own register() (mirrors shorts/tracks_audio):
    #   stabilize.run        camera-shake stabilization (ffmpeg vidstab 2-pass)
    #   audiomix.merge       A/V merge + sidechain DUCK + EBU R128 loudnorm
    #   audiomix.normalize   EBU R128 loudnorm only (no bed)
    #   silence.trim         dead-air removal (ffmpeg silencedetect -> re-cut)
    # All resolve media via the library + write derivatives under the exports
    # root, reusing the same injectable ffmpeg seams the sibling features use.
    from .features import audiomix as _audiomix  # local: import-light
    from .features import silencetrim as _silencetrim  # local: import-light
    from .features import stabilize as _stabilize  # local: import-light

    _stabilize.register(
        resolver=svc._resolve_video_path,
        out_dir=svc.exports_dir / "stabilized",
        settings_provider=svc.settings.get,
        run=svc._ffmpeg_run,  # None -> the real drained ffmpeg.run
        duration=svc._ffprobe_duration,
        register_fn=reg,
    )
    _audiomix.register(
        resolver=svc._resolve_video_path,
        out_dir=svc.exports_dir / "audiomix",
        settings_provider=svc.settings.get,
        run=svc._ffmpeg_run,
        duration=svc._ffprobe_duration,
        register_fn=reg,
    )
    _silencetrim.register(
        resolver=svc._resolve_video_path,
        out_dir=svc.exports_dir / "trimmed",
        settings_provider=svc.settings.get,
        run=svc._ffmpeg_run,
        duration=svc._ffprobe_duration,
        register_fn=reg,
    )

    # ---------------------------------------------------------------------- #
    # system-advanced group (this build) — health / recipes / diarize.
    # Each module owns its own register() (mirrors shorts / cues / assets).
    # ---------------------------------------------------------------------- #
    from .features import diarize as _diarize  # local: import-light
    from .features import health as _health  # local: import-light
    from .features import recipes as _recipes  # local: import-light

    # system.health (feature 1): the single "is my setup OK?" diagnostic. Reads
    # the same settings + tools_resolver chains the rest of the sidecar uses.
    _health.register(
        settings_provider=svc.settings.get,
        root=svc.data_dir,
        register_fn=reg,
    )

    # recipes.* (feature 3): saved multi-step pipelines run in one shot. The
    # runner invokes the live METHODS registry, so it must register AFTER the
    # methods its steps reference (transcribe/subtitles/shortmaker/etc.) — i.e.
    # here, near the end of register_all.
    _recipes.register(
        path=svc.data_dir / "recipes.json",
        register_fn=reg,
    )

    # diarize.start (feature 4): token-free speaker labelling. Reuses the same
    # project load/save helpers tracks_audio uses, plus the offline-gated assets.
    #
    # Phase-8 wiring: settings['diarizeBackend'] selects the SpeechBrain default
    # OR the opt-in pyannote 3.1 backend (gated HF weights + env HF token). The
    # selector validates the token eagerly (typed refusal, no deep 401) BEFORE any
    # heavy import; an unknown value keeps the safe speechbrain default. The
    # offline-gate models_present likewise checks whichever backend is selected.
    # Both seams are bound Services methods (testable in isolation).
    _diarize.register(
        resolver=svc._resolve_video_path,
        load_project=_load_project_data,
        save_project=_save_project_data,
        settings_provider=svc.settings.get,
        backend_factory=svc._diarize_backend_factory,
        models_present=svc._diarize_models_present,
        register_fn=reg,
    )

    # assets.* (A2): registered via the assets package's own register() so the
    # manager binds to the services' data dir + settings (U4).
    from .assets import rpc as _assets_rpc  # local import keeps handlers import-light

    _assets_rpc.register(
        root=svc.data_dir,
        settings_provider=svc.settings.get,
        register_fn=reg,
    )

    # Imports for side effect — U4 manifest entries only, NO new RPC methods:
    # T3 (TranslateGemma GGUF tiers), T4a (Chrome Headless Shell + exposes
    # RemotionCaptionEngine/STYLES), T5 (llama-server tool builds + the
    # resolve_tool() chains).
    from . import tools_resolver  # noqa: F401

    # Phase-8 model modules — imported for their asset-registration side effects
    # (each registers its on-demand AssetEntry at import, mirroring diarize /
    # tools_resolver). No new RPC methods: parakeet plugs into transcribe via the
    # ASR-engine seam, ctc_align into the transcribe karaoke tail, caption_polish
    # into subtitles.generate, pyannote into diarize's backend selector (above).
    from .features import (
        audio_saliency,  # noqa: F401
        caption_polish,  # noqa: F401
        caption_remotion,  # noqa: F401
        ctc_align,  # noqa: F401
        parakeet_asr,  # noqa: F401
        quality_gate,  # noqa: F401
        saliency,  # noqa: F401
        scene_transnet,  # noqa: F401
        smolvlm2,  # noqa: F401
        vlm_backbone,  # noqa: F401
    )
    from .models import translation as _translation_assets  # noqa: F401

    # job.list / job.retry (U5) are protocol.py built-ins — no wiring needed.

    log.info("registered %d feature methods", len(protocol.METHODS))
    return svc
