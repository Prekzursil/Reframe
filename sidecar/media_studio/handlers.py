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
from pathlib import Path
from typing import Any

from . import library as _library
from . import protocol
from .features import boundary as _boundary
from .features import convert as _convert
from .features import media_compat as _media_compat
from .features import shortmaker as _shortmaker
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
        """``subtitles.translate({trackId, targetLang})`` -> ``{jobId}`` (§2).

        Long job: returns ``{jobId}``, streams ``job.progress``, and its
        ``job.done.result`` is ``{track}``. The pure ``translate`` is synchronous;
        we run it in a job so the contract's ``{jobId}`` + progress shape holds.
        """
        track_id = _require_str(params, "trackId")
        target_lang = _require_str(params, "targetLang")
        if ctx.jobs is None:
            raise RpcError("no job registry available", ErrorCode.INTERNAL_ERROR)
        project = self._find_project_for_track(track_id)
        track = _tracks.find_track(project.data, track_id)
        translator = self._get_translator()  # None -> legacy injected provider
        provider = self._provider if translator is None else None
        save_path = project.manifest_path

        def job_body(job_ctx: Any) -> dict[str, Any]:
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
            # Persist the translated track back onto the project.
            project.data["tracks"] = [
                translated if (isinstance(t, dict) and t.get("id") == track_id) else t
                for t in project.data.get("tracks") or []
            ]
            if save_path is not None:
                project.save(save_path)
            return {"track": translated}

        job = ctx.jobs.start(job_body)
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

        def job_body(job_ctx: Any) -> dict[str, Any]:
            transcript = _transcribe.transcribe_file(
                audio_path,
                loader=loader,
                language=language,
                on_progress=lambda pct, msg: job_ctx.progress(pct, msg),
                should_cancel=lambda: job_ctx.cancelled,
            )
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
    from .features import caption_remotion  # noqa: F401
    from .models import translation as _translation_assets  # noqa: F401

    # job.list / job.retry (U5) are protocol.py built-ins — no wiring needed.

    log.info("registered %d feature methods", len(protocol.METHODS))
    return svc
