# The only inter-module cycle is the TYPE_CHECKING-only Services ref below
# (no runtime cycle); silence the type-only back-edge warning.
# pyright: reportImportCycles=false
"""Composition-root handlers (F4b split): Subtitles / tracks / convert / transcribe handlers.

Each function is a Services method body extracted verbatim from the former
monolithic handlers.py; `self` is typed against the composed `Services` (bound
in services.py). Behaviour + the RPC surface are byte-identical to pre-split.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .. import library as _library
from ..features import convert as _convert
from ..features import offline as _offline
from ..features import subtitles as _subtitles
from ..features import tracks as _tracks
from ..features import transcribe as _transcribe
from ..protocol import ErrorCode, RpcContext, RpcError
from ._shared import (
    _invalid,
    _require_str,
    log,
)
from ._wire import (
    _self_ffmpeg_run,
    _self_ffprobe,
)

if TYPE_CHECKING:  # pragma: no cover - typing-only import, never executed at runtime
    from ._services import Services


def subtitles_generate(self: Services, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
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
    # WU-5 wiring: settings['captionSpeakerLabels'] prefixes each diarized cue's
    # text with "<speaker>: " (mirrors the captionPolish gate above). Off/absent
    # -> the cues are unchanged (back-compat). Non-diarized cues carry no
    # speaker, so the prefix is a no-op even when the flag is on.
    if settings.get("captionSpeakerLabels"):
        labelled = _subtitles.format_speaker_prefix(track.get("cues") or [], on=True)
        track = _subtitles.edit(track, labelled)
    _tracks.add_track(project.data, track)
    project.save()
    return {"track": track}


def subtitles_edit(self: Services, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
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
        updated if (isinstance(t, dict) and t.get("id") == track_id) else t for t in project.data.get("tracks") or []
    ]
    project.save()
    return {"track": updated}


def subtitles_export(self: Services, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
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


def subtitles_translate(self: Services, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
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
    # WU-presets: the translation seam honors routing.perFunction["translation"]
    # (its tier3 hosted pool tries the routed provider first); falls back to the
    # legacy injected provider when one is set (existing tests).
    translator = None if self._provider is not None else self._translator_for_function("translation")
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
        ack=params.get("confirmBudget") if isinstance(params.get("confirmBudget"), str) else None,
    )
    return {"jobId": job.id}


def tracks_list(self: Services, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
    """``tracks.list({videoId})`` -> ``{tracks}`` (§2). Direct-return."""
    video_id = _require_str(params, "videoId")
    project = self._load_or_create_project(video_id)
    return {"tracks": _tracks.list_tracks(project.data)}


def tracks_rename(self: Services, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
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


def tracks_relabel(self: Services, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
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


def tracks_add(self: Services, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
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
        # Resolve the full track object from the project that owns the id, and
        # COPY it with a FRESH id (bug-sweep fix): a cross-video tracks.add would
        # otherwise duplicate the same id across two manifests, so a later
        # trackId-only op (rename/relabel/subtitles.edit/export) resolves to
        # whichever manifest sorts first — the WRONG video. A fresh id keeps the
        # target's copy independently addressable (via tracks.list).
        source = _tracks.find_track(self._find_project_for_track(track_id).data, track_id)
        track = {**source, "id": _library._new_id()}
    project = self._load_or_create_project(video_id)
    try:
        _tracks.add_track(project.data, track)
    except _tracks.TrackError as exc:
        raise _invalid(str(exc)) from exc
    project.save()
    return {"ok": True}


def tracks_remove(self: Services, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
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


def tracks_strip(self: Services, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
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


def tracks_burn(self: Services, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
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


def convert_start(self: Services, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
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


def convert_batch(self: Services, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
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


def transcribe_start(self: Services, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
    """``transcribe.start({videoId, language?})`` -> ``{jobId}`` (§2). Job-based.

    Long job: returns ``{jobId}``, streams progress, ``job.done.result`` is
    ``{transcript}``. On completion the transcript is PERSISTED onto the
    video's project manifest (so subtitles.generate / shortmaker can read it)
    and the library's ``hasTranscript`` flag is flipped.

    CONTRACT-NOTE: we don't call ``_transcribe.make_transcribe_handler``
    directly because its job body only returns ``{transcript}`` — it can't
    persist onto our project store. We reuse ``transcribe.transcribe_file``
    (the pure transcription seam) via the shared ``_transcribe_and_persist``
    helper (also driven by the Make-Shorts auto-transcribe) inside our own job.
    """
    if ctx.jobs is None:
        raise RpcError("no job registry available", ErrorCode.INTERNAL_ERROR)
    video_id = _require_str(params, "videoId")
    language = params.get("language")
    if language is not None and not isinstance(language, str):
        raise _invalid("language must be a string when given")
    # Fail fast (synchronously, before returning a jobId) on an unknown video.
    if not self._resolve_video_path(video_id):
        raise _invalid(f"unknown video: {video_id}")

    def job_body(job_ctx: Any) -> dict[str, Any]:
        return {"transcript": self._transcribe_and_persist(video_id, job_ctx, language=language)}

    job = ctx.jobs.start(job_body)
    return {"jobId": job.id}


def _transcribe_and_persist(
    self: Services,
    video_id: str,
    job_ctx: Any,
    *,
    language: str | None = None,
) -> dict[str, Any]:
    """Transcribe ``video_id`` and persist the transcript onto its project.

    The shared job body behind ``transcribe.start`` AND the Make-Shorts auto-
    transcribe (``shortmaker._ensure_transcript``): resolves the audio, runs the
    selected ASR engine (whisper default / parakeet — WU7 ``settings['asrEngine']``,
    with the duration probe letting parakeet chunk under the hard 6 GB rule),
    refines word timings when karaoke is on, then — unless the job was cancelled —
    persists the transcript onto the project manifest and flips the library
    ``hasTranscript`` flag so every downstream consumer (subtitles / shortmaker /
    index) reuses it. Returns the produced transcript. Raises on an unresolvable
    ``video_id`` (the shorts auto-transcribe reaches this inside the select job).
    """
    audio_path = self._resolve_video_path(video_id)
    if not audio_path:
        raise _invalid(f"unknown video: {video_id}")
    loader = self._whisper_loader or _transcribe.FasterWhisperLoader()
    settings = self.settings.get()
    probe = self._ffprobe_duration or _self_ffprobe()
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
    return transcript


def _diarize_backend_factory(self: Services, settings: dict[str, Any]) -> Any:
    """Phase-8: build the diarizer backend selected by settings['diarizeBackend'].

    Delegates to ``pyannote_backend.select_backend_factory`` closed over the
    SpeechBrain default factory: an unknown value keeps the safe speechbrain
    default; ``"pyannote"`` validates the env HF token eagerly (typed refusal,
    no deep 401) before any heavy import.
    """
    from ..features import diarize as _diarize  # local: import-light
    from ..features import pyannote_backend as _pyannote  # local: import-light

    return _pyannote.select_backend_factory(
        settings,
        speechbrain_factory=_diarize._default_backend_factory,
    )


def _diarize_models_present(self: Services, settings: dict[str, Any]) -> bool:
    """Phase-8: probe the installed-state of whichever diarize backend is selected.

    Pyannote checks its two gated repos; speechbrain checks the VAD + ECAPA
    assets. Drives the offline gate so a missing-model download is refused for
    the right backend.
    """
    from ..features import diarize as _diarize  # local: import-light
    from ..features import pyannote_backend as _pyannote  # local: import-light

    if _pyannote.selected_backend_name(settings) == _pyannote.PYANNOTE_BACKEND:
        return _pyannote.default_models_present(settings)
    return _diarize.default_models_present(settings)


def _maybe_align_words(
    self: Services,
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
    from ..features import ctc_align as _ctc_align  # local: import-light seam

    return _ctc_align.align_words(transcript, audio_path, settings=settings)
