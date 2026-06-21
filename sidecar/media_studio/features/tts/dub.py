"""The dub pipeline — ``tts.dub.start`` (CONTRACTS.md A2/A4, T2).

A BATCHED long job (A4, frozen): **translate ALL cues -> free the MT model ->
synth ALL cues** (never interleave model swaps) **-> align (the frozen ±15%
recipe) -> concat WAV -> encode AAC -> mux as an AudioTrack** via
:mod:`..tracks_audio` (which also persists ``Project.audioTracks``).

Wire shape (A2, frozen)::

    tts.dub.start({videoId, trackId, engine, voice?, sampleId?, targetLang?})
        -> {jobId} -> job.done {audioTrack, path}

Seams (everything heavy is injected; tests run the pipeline with fakes):

* ``translator_factory`` — the **models.translation seam** (T3's module).
  CONTRACT-NOTE: T3's public API is not frozen by the addendum; we depend on
  a small protocol (``translate(texts, target_lang, source_lang) -> texts`` +
  ``free()``) and the wiring agent adapts T3's real surface to it (see
  WIRING-T2.md). When no translator is wired and a ``targetLang`` is asked,
  the job fails with a clear error (A6 lesson 3 — surfaced, never swallowed).
* ``engines`` — engine-id -> factory map (engines built lazily INSIDE the
  job so constructing the service never loads a backend).
* ffmpeg ``run`` / ``duration`` — the drained runner + probe (A6 lesson 2).
* ``audio_tracks`` — the :class:`..tracks_audio.AudioTracksService` that
  muxes the result into the container and persists the manifest entry.

CONTRACT-NOTE (result ``path``): A2 types the done payload as
``{audioTrack, path}``. We return the **dub WAV** as ``path`` (the plan has
the UI audition the WAV directly); the AAC actually muxed into the container
is recorded on ``audioTrack.path``.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import (
    Any,
    Protocol,
)

from ... import ffmpeg
from ...jobs import JobContext
from ...protocol import ErrorCode, RpcContext, RpcError
from ...util import get_logger
from . import align as _align
from .engine import Cue, TtsEngine, TtsError, wav_duration_sec
from .voices import VoiceStore

log = get_logger("media_studio.tts.dub")

#: progress band per stage (translate / synth / align / assemble)
_PCT_TRANSLATE = (0.0, 20.0)
_PCT_SYNTH = (20.0, 60.0)
_PCT_ALIGN = (60.0, 85.0)
_PCT_ASSEMBLE = (85.0, 100.0)


class DubError(TtsError):
    """A dub pipeline failure; surfaces via the job.done error payload (A6.3)."""


class Translator(Protocol):
    """The models.translation seam the pipeline consumes (see module note)."""

    def translate(self, texts: Sequence[str], target_lang: str, source_lang: str | None = None) -> list[str]:
        """Translate ALL texts in one batched call (order-preserving)."""
        ...  # pragma: no cover - protocol

    def free(self) -> None:
        """Unload/release the MT model (the 'free MT' stage)."""
        ...  # pragma: no cover - protocol


# videoId -> absolute media path (or None when unknown).
Resolver = Callable[[str], str | None]
# Engine factories: built lazily inside the job body.
EngineFactories = dict[str, Callable[[], TtsEngine]]
RunFn = Callable[..., int]
DurationFn = Callable[[str], float]


def _default_translator_factory() -> Translator:
    """Adapt :mod:`media_studio.models.translation` (T3) to the seam, lazily.

    CONTRACT-NOTE: built in parallel by T3 — we look for a ``get_translator``
    factory there and duck-type the result; the wiring agent replaces this
    with an explicit adapter if T3's surface differs (WIRING-T2.md).
    """
    try:
        from ...models import translation as _translation  # noqa: PLC0415 - lazy seam
    except ImportError as exc:
        raise DubError(
            "translation backend unavailable (models.translation not present); "
            "dub without targetLang or wire a translator"
        ) from exc
    factory = getattr(_translation, "get_translator", None)
    if factory is None:
        raise DubError(
            "models.translation has no get_translator(); the wiring agent "
            "must inject a translator_factory adapter (see WIRING-T2.md)"
        )
    return factory()  # type: ignore[no-any-return]


def _band(job_ctx: JobContext, band: tuple, frac: float, message: str) -> None:
    lo, hi = band
    job_ctx.progress(lo + (hi - lo) * max(0.0, min(1.0, frac)), message)


# --------------------------------------------------------------------------- #
# the pipeline (stage ORDER is the frozen A4 contract — tested directly)
# --------------------------------------------------------------------------- #
def run_dub_pipeline(
    job_ctx: JobContext,
    *,
    cues: Sequence[Cue],
    engine: TtsEngine,
    voice: str,
    lang: str,
    work_dir: str,
    out_wav: str,
    target_lang: str | None = None,
    source_lang: str | None = None,
    translator: Translator | None = None,
    run: RunFn = ffmpeg.run,
    duration: DurationFn = wav_duration_sec,
    total_sec: float | None = None,
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run translate-all -> free MT -> synth-all -> align -> concat (BATCHED).

    Returns ``{"path": out_wav, "cues": <the (translated) cues>}``. Raises
    :class:`DubError` on any failure — including the degenerate empty track —
    so the job framework emits the A3 error payload.
    """
    cues = [dict(c) for c in cues]
    if not cues:
        raise DubError("track has no cues — nothing to dub")

    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)

    # -- stage 1: translate ALL cues (batched), then FREE the MT model --------
    if target_lang:
        if translator is None:
            translator = _default_translator_factory()
        _band(job_ctx, _PCT_TRANSLATE, 0.0, f"translating {len(cues)} cues -> {target_lang}")
        job_ctx.raise_if_cancelled()
        texts = [str(c.get("text", "")) for c in cues]
        try:
            translated = translator.translate(texts, target_lang, source_lang)
        except DubError:
            raise
        except Exception as exc:  # noqa: BLE001 - surface MT failures (A6.3)
            raise DubError(f"translation failed: {exc}") from exc
        finally:
            # A4: free the MT model BEFORE any synthesis (never interleave
            # model swaps) — even on failure, so a retry starts clean.
            try:
                translator.free()
            except Exception:  # noqa: BLE001 - freeing is best-effort
                log.warning("translator.free() failed (continuing)")
        if not isinstance(translated, (list, tuple)) or len(translated) != len(cues):
            raise DubError("translator returned a mismatched cue count")
        for cue, new_text in zip(cues, translated, strict=False):
            cue["text"] = str(new_text)
        lang = target_lang
        _band(job_ctx, _PCT_TRANSLATE, 1.0, "translation done (MT freed)")

    # -- stage 2: synth ALL cues (batched; one engine session) ----------------
    raw_wavs: list[str] = []
    for i, cue in enumerate(cues):
        job_ctx.raise_if_cancelled()
        _band(job_ctx, _PCT_SYNTH, i / len(cues), f"synthesizing cue {i + 1}/{len(cues)}")
        raw = str(work / f"cue-{i:04d}-raw.wav")
        engine.synth([cue], voice, lang, raw)
        raw_wavs.append(raw)
    _band(job_ctx, _PCT_SYNTH, 1.0, "synthesis done")

    # -- stage 3: align each cue (the frozen recipe: target -> re-synth ->
    #    atempo ±15% -> pad) ---------------------------------------------------
    aligned: list[str] = []
    out_secs: list[float] = []
    for i, cue in enumerate(cues):
        job_ctx.raise_if_cancelled()
        _band(job_ctx, _PCT_ALIGN, i / len(cues), f"aligning cue {i + 1}/{len(cues)}")
        target = _align.target_duration(cue)
        aligned_path = str(work / f"cue-{i:04d}.wav")

        def _resynth(rate: float, path: str, _cue: Cue = cue) -> str:
            return engine.synth([_cue], voice, lang, path, rate=rate)

        result = _align.align_cue_wav(
            raw_wavs[i],
            target,
            aligned_path,
            resynth=_resynth,
            run=run,
            duration=duration,
            settings=settings,
        )
        aligned.append(result["path"])
        out_secs.append(float(result["outSec"]))
    _band(job_ctx, _PCT_ALIGN, 1.0, "alignment done")

    # -- stage 4: concat into the full-length dub WAV --------------------------
    job_ctx.raise_if_cancelled()
    _band(job_ctx, _PCT_ASSEMBLE, 0.0, "assembling dub track")
    plan = _align.concat_plan(cues, out_secs, total_sec=total_sec)
    _align.concat_wavs(plan, aligned, out_wav)
    return {"path": out_wav, "cues": cues}


def build_encode_aac_argv(in_wav: str, out_m4a: str, settings: dict[str, Any] | None = None) -> list[str]:
    """ffmpeg argv encoding the dub WAV to AAC for muxing (argv list, A6.4)."""
    return [
        ffmpeg.ffmpeg_path(settings),
        "-hide_banner",
        "-nostdin",
        "-y",
        "-i",
        in_wav,
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        out_m4a,
    ]


# --------------------------------------------------------------------------- #
# the service + tts.dub.start handler
# --------------------------------------------------------------------------- #
class DubService:
    """Owns the ``tts.dub.start`` wiring around :func:`run_dub_pipeline`."""

    def __init__(
        self,
        *,
        resolver: Resolver,
        load_track: Callable[[str, str], dict[str, Any]],
        engines: EngineFactories,
        voice_store: VoiceStore,
        audio_tracks: Any,
        translator_factory: Callable[[], Translator] | None = None,
        settings_provider: Callable[[], dict[str, Any]] | None = None,
        run: RunFn = ffmpeg.run,
        duration: DurationFn = wav_duration_sec,
        media_duration: Callable[[str], float] | None = None,
        out_dir: str | None = None,
    ) -> None:
        self._resolver = resolver
        self._load_track = load_track
        self._engines = engines
        self._voice_store = voice_store
        self._audio_tracks = audio_tracks
        self._translator_factory = translator_factory
        self._settings_provider = settings_provider or (lambda: {})
        self._run = run
        self._duration = duration
        self._media_duration = media_duration
        self._out_dir = out_dir

    # -- helpers ----------------------------------------------------------------
    def _settings(self) -> dict[str, Any]:
        try:
            return dict(self._settings_provider() or {})
        except Exception:  # noqa: BLE001 - settings must never break a dub
            return {}

    def _out_dir_for(self, video_id: str) -> Path:
        if self._out_dir is not None:
            return Path(self._out_dir) / video_id
        from ...settings_store import default_config_dir  # noqa: PLC0415 - lazy

        return default_config_dir() / "dubs" / video_id

    def _resolve_voice(self, engine_id: str, voice: str | None, sample_id: str | None) -> str:
        """Map the wire's voice?/sampleId? onto the engine's ``voice`` arg."""
        if engine_id == "chatterbox":
            if not sample_id:
                raise RpcError(
                    "sampleId is required for the chatterbox engine (add one via tts.sample.add)",
                    ErrorCode.INVALID_PARAMS,
                )
            sample = self._voice_store.get(sample_id)
            if sample is None:
                raise RpcError(f"unknown sampleId: {sample_id}", ErrorCode.INVALID_PARAMS)
            return str(sample["path"])
        if not voice or not isinstance(voice, str):
            raise RpcError(
                f"voice is required for the {engine_id} engine",
                ErrorCode.INVALID_PARAMS,
            )
        return voice

    # -- the A2 handler -----------------------------------------------------------
    def dub_start(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``tts.dub.start({...})`` -> ``{jobId}`` -> ``{audioTrack, path}`` (A2)."""
        video_id = _require_str(params, "videoId")
        track_id = _require_str(params, "trackId")
        engine_id = _require_str(params, "engine")
        if ctx.jobs is None:
            raise RpcError("no job registry available", ErrorCode.INTERNAL_ERROR)
        factory = self._engines.get(engine_id)
        if factory is None:
            raise RpcError(
                f"unknown engine: {engine_id} (expected one of {', '.join(sorted(self._engines))})",
                ErrorCode.INVALID_PARAMS,
            )
        in_path = self._resolver(video_id)
        if not in_path:
            raise RpcError(f"unknown video: {video_id}", ErrorCode.INVALID_PARAMS)
        track = self._load_track(video_id, track_id)
        voice = self._resolve_voice(engine_id, params.get("voice"), params.get("sampleId"))
        target_lang = params.get("targetLang")
        if target_lang is not None and not isinstance(target_lang, str):
            raise RpcError("targetLang must be a string", ErrorCode.INVALID_PARAMS)
        settings = self._settings()
        source_lang = track.get("lang") if isinstance(track.get("lang"), str) else None
        cues = list(track.get("cues") or [])
        sample_id = params.get("sampleId")

        def job_body(job_ctx: JobContext) -> dict[str, Any]:
            engine = factory()
            out_base = self._out_dir_for(video_id)
            stamp = int(time.time())
            out_wav = str(out_base / f"dub-{track_id}-{stamp}.wav")
            work_dir = str(out_base / f"work-{track_id}-{stamp}")
            translator = self._translator_factory() if self._translator_factory else None
            total = None
            if self._media_duration is not None:
                try:
                    total = float(self._media_duration(in_path))
                except Exception:  # noqa: BLE001 - probe is best-effort
                    total = None
            run_dub_pipeline(
                job_ctx,
                cues=cues,
                engine=engine,
                voice=voice,
                lang=str(track.get("lang") or ""),
                work_dir=work_dir,
                out_wav=out_wav,
                target_lang=target_lang,
                source_lang=source_lang,
                translator=translator,
                run=self._run,
                duration=self._duration,
                total_sec=total,
                settings=settings,
            )
            # encode AAC + mux as an AudioTrack (persists Project.audioTracks)
            job_ctx.raise_if_cancelled()
            job_ctx.progress(90.0, "encoding AAC")
            out_m4a = str(Path(out_wav).with_suffix(".m4a"))
            code = self._run(build_encode_aac_argv(out_wav, out_m4a, settings))
            if code != 0:
                raise DubError(f"AAC encode failed (ffmpeg exit {code})")
            job_ctx.progress(95.0, "muxing audio track")
            dub_lang = target_lang or str(track.get("lang") or "und")
            voice_label = sample_id if engine_id == "chatterbox" else voice
            audio_track = self._audio_tracks.mux_for_dub(
                video_id,
                out_m4a,
                lang=dub_lang,
                name=f"Dub ({engine_id}, {dub_lang})",
                voice=voice_label,
            )
            job_ctx.progress(100.0, "dub ready")
            return {"audioTrack": audio_track, "path": out_wav}

        job = ctx.jobs.start(job_body)
        return {"jobId": job.id}


def _require_str(params: dict[str, Any], key: str) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value:
        raise RpcError(f"{key} (str) is required", ErrorCode.INVALID_PARAMS)
    return value


__all__ = [
    "DubError",
    "DubService",
    "Translator",
    "build_encode_aac_argv",
    "run_dub_pipeline",
]
