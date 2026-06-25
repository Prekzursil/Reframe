"""Short-maker orchestration: the star pipeline, run as Jobs.

This module is the *conductor*. It wires the proven stages together and runs
them as long-running :class:`~media_studio.jobs.Job` work:

    SELECT          (features.select)    prompt + transcript -> ranked candidates
    BOUNDARY-SNAP   (features.boundary)  snap start/end to sentence/silence/cut
      -- the two steps above are ``shortmaker.select`` --

    CUT             (ffmpeg, frame-accurate)  carve each approved clip out of the
                    source video; persist ``sourceStart`` on every clip
    REFRAME         (features.reframe)   verthor adapter -> 1080x1920 (9:16)
    CAPTION         (features.caption)   libass burn-in, cue times re-based
    EXPORT          (libx264)            the batch of approved clips
    MUX-AUDIO       (ffmpeg, optional)   when A2's optional ``audioTrackId`` is
                    given, map the chosen AudioTrack's [sourceStart, end) window
                    onto each exported clip (replacing the clip's own audio)
      -- the steps above are ``shortmaker.export`` --

CONTRACTS.md mapping:
  - §2  shortmaker.select({videoId, prompt, controls}) -> {jobId} -> {candidates}
        shortmaker.export({videoId, candidateIds})       -> {jobId} -> {clips:[{path}]}
  - A2  ``shortmaker.export`` gains OPTIONAL ``audioTrackId`` (carry the chosen
        audio track into clips); A3 AudioTrack {id, lang, name, kind, voice?, path}
  - §3  Candidate = {rank,start,end,durationSec,hook,why,score,sourceStart};
        ``sourceStart`` = the clip's start in the ORIGINAL video; captions must
        subtract it to re-base to the clip's local t=0.
  - §4  ReframeEngine (verthor) + CaptionEngine (libass) are the SOLE impls.
  - §5  selection recipe lives in ``features.select``; boundary-snap in
        ``features.boundary``.

Degenerate handling (all surfaced as a structured result, never a crash):
  - no-speech / empty transcript            -> {"candidates": [], "reason": "no clips"}
  - zero candidates from select             -> {"candidates": [], "reason": "no candidates"}
  - fewer survivors than requested          -> {"candidates": [...], "reason": "too few candidates"}
  - a candidate with no valid boundary       -> dropped, with a per-candidate reason
  - verthor finds no subject                  -> the verthor adapter's center-crop
                                                fallback runs (still ONE engine)

This module performs NO heavy-ML imports at module load. Each stage is reached
through an injectable :class:`Stages` seam (the default lazily binds the sibling
feature modules), so the pure orchestration logic is unit-testable with the
provider / whisper / verthor / scenedetect / ffmpeg all mocked.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..jobs import JobContext
from ..util import get_logger

log = get_logger("media_studio.shortmaker")

# Type aliases mirroring CONTRACTS.md §3 (plain dicts on the wire).
Candidate = dict[str, Any]
Transcript = dict[str, Any]
Cue = dict[str, Any]

# §5: every clip is a complete thought running 20-60 seconds (hard bounds).
MIN_CLIP_SEC = 20.0
MAX_CLIP_SEC = 60.0

# §4: verthor outputs 1080x1920 h264; captions are sized to match.
OUT_WIDTH = 1080
OUT_HEIGHT = 1920
DEFAULT_ASPECT = "9:16"


# ---------------------------------------------------------------------------
# stage seam
# ---------------------------------------------------------------------------
# CONTRACT-NOTE: §2/§3 freeze the RPC method names + the Candidate schema, but
# NOT the internal Python signatures of the sibling feature modules. The seam
# below is the orchestrator's own contract; the defaults ADAPT to the actual
# sibling APIs (verified against the as-built modules):
#
#   select.select(transcript, prompt, controls, provider) -> List[Candidate]
#       (provider = the LLM chat seam; built from models.provider by default)
#   boundary.snap_from_lists(candidates, words, *, silences, scene_cuts,
#       silence_provider, scene_provider, ...) -> (kept, dropped)
#   reframe.ReframeEngine(settings).reframe(in, out, aspect) -> out
#       (no-subject center-crop fallback lives INSIDE the verthor adapter)
#   caption.CaptionEngine(settings).render(clip, cues, out, burn, width,
#       height, source_start, ...) -> out   (re-bases cue times by source_start)
#   ffmpeg.run / ffmpeg.build_convert_argv for the frame-accurate CUT and the
#       final libx264 EXPORT (there is no separate cut/export module).
#
# The orchestrator-facing seam each default wraps:
#   select_candidates(transcript, prompt, controls, *, settings) -> List[Candidate]
#   snap_candidates(candidates, transcript, *, settings) -> (kept, dropped)
#       kept   = re-snapped+re-ranked candidates (sourceStart re-based)
#       dropped = [{candidate, reason}] for clips with no valid boundary
#   cut_clip(in_path, out_path, start, end, *, settings) -> out_path
#   reframe(in_path, out_path, aspect, *, settings) -> out_path
#   render_caption(clip_path, cues, out_path, *, source_start, burn,
#       width, height, settings) -> out_path
#   export_clip(in_path, out_path, *, settings) -> out_path

SelectStage = Callable[..., list[Candidate]]
SnapStage = Callable[..., tuple[list[Candidate], list[dict[str, Any]]]]
CutStage = Callable[..., str]
# remove_fillers(in_path, out_path, words, cues, *, lang, settings)
#   -> (out_path, remapped_cues, {"fillersRemoved", "fillerSeconds"})
RemoveFillersStage = Callable[..., tuple[str, list[Cue], dict[str, Any]]]
ReframeStage = Callable[..., str]
# apply_zoom(in_path, out_path, cues, *, source_start, duration_sec, settings)
#   -> out_path  (P4 §8b: subtle slow zoom + punch-in at sentence-start beats)
ZoomStage = Callable[..., str]
CaptionStage = Callable[..., str]
ExportStage = Callable[..., str]
# brand_overlay(in_path, out_path, logo_path, *, settings) -> out_path
#   (P4 §8d: composite the brand logo into a padded corner)
BrandOverlayStage = Callable[..., str]
# mux_audio(clip_path, audio_track, out_path, *, start, end, settings) -> out_path
MuxAudioStage = Callable[..., str]
# stabilize(in_path, out_path, *, settings, on_notice) -> out_path|in_path
#   (audio-stabilize group: ffmpeg vidstab 2-pass; pass-through when libvidstab
#    is missing — the unavailable notice is surfaced via on_notice, never skipped)
StabilizeStage = Callable[..., str]
# trim_silence(in_path, out_path, *, settings) -> (out_path|in_path, removedSec)
#   (audio-stabilize group: ffmpeg silencedetect -> dead-air re-cut)
SilenceTrimStage = Callable[..., tuple[str, float, list[tuple[float, float]]]]


# -- default stage adapters (bind to the real sibling APIs) -----------------
def _words_of(transcript: Transcript | None) -> list[dict[str, Any]]:
    """Flatten a transcript's word timings into the flat list boundary expects."""
    words: list[dict[str, Any]] = []
    if not transcript:
        return words
    for seg in transcript.get("segments", []) or []:
        for w in (seg or {}).get("words") or []:
            words.append(w)
    return words


def _default_provider(settings: dict[str, Any]) -> Any:
    """Build the LLM chat provider for selection (lazy, heavy import isolated)."""
    from ..models import provider as _provider  # local import keeps seam mockable

    # CONTRACT-NOTE: §4/§7 — a managed llama.cpp server (OpenAI /v1). The provider
    # module owns construction via its get_provider factory (settings routes
    # local-vs-cloud; Phase-0 fix: the old probe guessed a nonexistent
    # "from_settings" name and fell back to a positional ctor call -> TypeError).
    return _provider.get_provider(settings)


def _lazy_select(transcript, prompt, controls, *, settings=None) -> list[Candidate]:
    from . import select as _select  # local import keeps the seam mockable

    provider = _default_provider(settings or {})
    # select.select returns its own ``Candidate`` TypedDict; the shortmaker
    # pipeline treats candidates as plain ``dict[str, Any]`` (see module alias),
    # so normalize each row to a real dict at the seam.
    return [dict(c) for c in _select.select(transcript, prompt, controls, provider)]


def _lazy_snap(candidates, transcript, *, settings=None) -> tuple[list[Candidate], list[dict[str, Any]]]:
    from . import boundary as _boundary

    words = _words_of(transcript)
    # CONTRACT-NOTE: silence/scene detection lives behind the boundary seam; the
    # real detectors (ffmpeg silencedetect / PySceneDetect) are wired here in
    # production. Passing empty lists makes snapping rely on sentence-end timing
    # only — still a valid boundary source per §5 — until the detectors land.
    return _boundary.snap_from_lists(
        candidates,
        words,
        silences=(settings or {}).get("silences"),
        scene_cuts=(settings or {}).get("sceneCuts"),
    )


def _lazy_cut(in_path, out_path, start, end, *, settings=None) -> str:
    """Frame-accurate ffmpeg carve of [start, end) (libx264, argv-list, no shell)."""
    from .. import ffmpeg as _ffmpeg

    argv = [
        _ffmpeg.ffmpeg_path(settings),
        "-hide_banner",
        "-nostdin",
        "-y",
        # accurate seek: -ss/-to AFTER -i forces frame-accurate (decode-then-trim).
        "-i",
        in_path,
        "-ss",
        f"{float(start):.3f}",
        "-to",
        f"{float(end):.3f}",
        "-c:v",
        "libx264",
        "-c:a",
        "aac",
        "-progress",
        "pipe:1",
        "-nostats",
        out_path,
    ]
    code = _ffmpeg.run(argv)
    if code != 0:  # pragma: no cover - prod seam
        raise RuntimeError(f"ffmpeg cut failed (exit {code}) for {out_path}")
    return out_path


def _lazy_remove_fillers(
    in_path, out_path, words, cues, *, lang=None, settings=None
) -> tuple[str, list[Cue], dict[str, Any]]:
    """Filler-removal stage (P3-B): de-fill a cut clip + remap its cues.

    ``words``/``cues`` are CLIP-LOCAL (re-based to the cut clip's t=0 by the
    orchestrator). Builds the keep-list + per-clip stats from the words, carves
    the kept spans out of ``in_path`` (frame-accurate ``filter_complex``, argv
    LIST, drained via the shared ``ffmpeg.run``), and remaps the cues onto the
    compressed timeline so captions stay in sync.

    Returns ``(out_path, remapped_cues, {"fillersRemoved", "fillerSeconds"})``.
    When the keep-list is a single full-window span (no filler removed) the cut
    is still run for shape uniformity, and the cues map through unchanged.
    """
    from .. import ffmpeg as _ffmpeg
    from . import fillers as _fillers

    keeps, stats = _fillers.build_cutlist_with_stats(words, lang)
    if not keeps:
        # Degenerate guard (build_cutlist_with_stats already keeps the window
        # whole rather than emptying it, but stay defensive): no cut to make.
        return in_path, list(cues or []), {"fillersRemoved": 0, "fillerSeconds": 0.0}
    argv = _fillers.build_segment_cut_argv(in_path, out_path, keeps, settings)
    code = _ffmpeg.run(argv)
    if code != 0:  # pragma: no cover - prod seam
        raise RuntimeError(f"ffmpeg filler cut failed (exit {code}) for {out_path}")
    remapped = _fillers.remap_cues(cues or [], keeps)
    return out_path, remapped, stats


def _lazy_reframe(in_path, out_path, aspect, *, settings=None) -> str:
    from . import reframe as _reframe

    # T4b: settings["reframeEngine"] is the CONCRETE name run_export resolved
    # ("verthor" | "claudeshorts"); "auto" (direct callers) re-resolves here.
    engine, _notice = _reframe.get_engine((settings or {}).get("reframeEngine", "auto"), settings or {})
    return engine.reframe(in_path, out_path, aspect)


def _lazy_stabilize(in_path, out_path, *, settings=None, on_notice=None) -> str:
    """Camera-shake stabilization pre-step (audio-stabilize group).

    Delegates to ``features.stabilize.stabilize_clip``: runs the vidstab 2-pass
    flow when libvidstab is present, else returns ``in_path`` unchanged AND emits
    the typed unavailable notice through ``on_notice`` (the orchestrator surfaces
    it via job.progress — the "do NOT silently skip" contract).
    """
    from . import stabilize as _stabilize

    return _stabilize.stabilize_clip(in_path, out_path, settings=settings, on_notice=on_notice)


def _lazy_trim_silence(in_path, out_path, *, settings=None) -> tuple[str, float, list[tuple[float, float]]]:
    """Dead-air removal pre-step (audio-stabilize group).

    Delegates to ``features.silencetrim.trim_clip``: detects silent spans via
    ffmpeg silencedetect, re-cuts the keeps, and returns
    ``(path, removedSec, keeps)``. The ``keeps`` (clip-local kept spans) let the
    orchestrator remap caption cues onto the compacted timeline. Returns
    ``(in_path, 0.0, [(0, total)])`` when there is no dead air to remove (an
    identity remap, so cues map through unchanged).
    """
    from . import silencetrim as _silencetrim

    return _silencetrim.trim_clip(in_path, out_path, settings=settings)


def _lazy_zoom(in_path, out_path, cues, *, source_start, duration_sec, settings=None) -> str:
    """Auto punch-in zoom stage (P4 §8b): build the zoompan filter + run it.

    Beats are sentence-starts from the clip's ``cues`` (v1 — PLAN-P4 C16),
    re-based to the reframed clip's t=0 by subtracting ``source_start``. The
    filter targets the §4 vertical output size and is run through the proven
    drained ``ffmpeg.run`` seam (C16 — no re-implemented drain).
    """
    from .. import ffmpeg as _ffmpeg
    from . import zoom as _zoom

    argv = _zoom.build_zoom_argv(
        in_path,
        out_path,
        width=OUT_WIDTH,
        height=OUT_HEIGHT,
        duration_sec=float(duration_sec or 0.0),
        cues=cues,
        source_start=float(source_start or 0.0),
        settings=settings,
    )
    code = _ffmpeg.run(argv)
    if code != 0:  # pragma: no cover - prod seam
        raise RuntimeError(f"ffmpeg zoom failed (exit {code}) for {out_path}")
    return out_path


def _lazy_brand_overlay(in_path, out_path, logo_path, *, settings=None) -> str:
    """Brand-logo overlay stage (P4 §8d): composite the logo into a corner.

    Follows the second-input pattern (clip + logo) via the shared drained
    ``ffmpeg.run`` seam (C16). Only invoked by the orchestrator when a
    ``brandLogoPath`` is configured.
    """
    from .. import ffmpeg as _ffmpeg
    from . import brandkit as _brandkit

    argv = _brandkit.build_logo_overlay_argv(in_path, logo_path, out_path, settings=settings)
    code = _ffmpeg.run(argv)
    if code != 0:  # pragma: no cover - prod seam
        raise RuntimeError(f"ffmpeg brand overlay failed (exit {code}) for {out_path}")
    return out_path


def _lazy_caption(
    clip_path,
    cues,
    out_path,
    *,
    source_start,
    burn,
    width,
    height,
    settings=None,
    hook_title=None,
) -> str:
    """Caption-stage router (A4): style picks the engine.

    settings["captionStyle"]:
      - a Remotion style (bold/bounce/clean/karaoke) -> RemotionCaptionEngine
      - "none"                                       -> skip captioning entirely
      - anything else / unset                        -> libass (the default)

    P3-A: ``hook_title`` (the candidate's hook headline, or None to skip) is
    threaded into BOTH engines so the overlay rides whichever caption engine the
    style selects.
    """
    style = str((settings or {}).get("captionStyle") or "").strip().lower()
    if style == "none":
        return clip_path  # pass-through: the export stage encodes the bare clip

    if style:
        from . import caption_remotion as _remotion

        if style in _remotion.STYLES:
            engine = _remotion.RemotionCaptionEngine(settings or {})
            return engine.render(
                clip_path,
                cues,
                out_path,
                style=style,
                burn=burn,
                width=width,
                height=height,
                source_start=source_start,
                hook_title=hook_title,
            )

    from . import caption as _caption

    engine = _caption.CaptionEngine(settings or {})
    return engine.render(
        clip_path,
        cues,
        out_path,
        burn=burn,
        width=width,
        height=height,
        source_start=source_start,
        hook_title=hook_title,
    )


def _lazy_export(in_path, out_path, *, settings=None) -> str:
    """Final libx264 encode of the captioned clip (argv-list, no shell)."""
    from .. import ffmpeg as _ffmpeg

    argv = _ffmpeg.build_convert_argv(in_path, out_path, {"vcodec": "libx264", "acodec": "aac"}, settings)
    code = _ffmpeg.run(argv)
    if code != 0:  # pragma: no cover - prod seam
        raise RuntimeError(f"ffmpeg export failed (exit {code}) for {out_path}")
    return out_path


def build_audio_mux_argv(
    clip_path: str,
    audio_src: str,
    out_path: str,
    *,
    start: float,
    end: float,
    stream_index: int = 0,
    settings: dict[str, Any] | None = None,
) -> list[str]:
    """argv mapping an AudioTrack's [start, end) window onto an exported clip.

    Input 0 = the finished clip (its video kept under stream copy, its own
    audio DROPPED — for kind="dub" this is the "replace the original audio"
    semantic); input 1 = the chosen track's audio source, input-seeked with
    ``-ss``/``-to`` so the window [start, end) (the candidate's sourceStart→end
    in ORIGINAL-video time) lands at the clip's local t=0. ``stream_index``
    picks ``1:a:<n>`` for container sources (kind="original"); a standalone dub
    file uses its only stream (n=0). argv LIST only (A6.4); reuses ffmpeg.py's
    resolver + the drained ``run`` seam.
    """
    if end <= start:
        raise ValueError("audio mux window requires end > start")
    if stream_index < 0:
        raise ValueError("stream_index must be >= 0")
    from .. import ffmpeg as _ffmpeg  # lazy: keeps module import-light

    return [
        _ffmpeg.ffmpeg_path(settings),
        "-hide_banner",
        "-nostdin",
        "-y",
        "-i",
        clip_path,
        # input-side seek on the AUDIO source: aligns the track's window with
        # the clip's t=0 (the clip was cut from the same [start, end) span).
        "-ss",
        f"{float(start):.3f}",
        "-to",
        f"{float(end):.3f}",
        "-i",
        audio_src,
        "-map",
        "0:v",
        "-map",
        f"1:a:{int(stream_index)}",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-progress",
        "pipe:1",
        "-nostats",
        out_path,
    ]


def _lazy_mux_audio(clip_path, audio_track, out_path, *, start, end, settings=None) -> str:
    """Default MUX-AUDIO stage: swap the clip's audio for the chosen track's.

    ``audio_track`` is the resolved A3 AudioTrack dict (plus the internal
    ``streamIndex`` computed by :func:`_resolve_audio_track`).
    """
    from .. import ffmpeg as _ffmpeg

    audio_src = str((audio_track or {}).get("path") or "")
    if not audio_src:
        raise ValueError("audio track has no path to mux")
    argv = build_audio_mux_argv(
        clip_path,
        audio_src,
        out_path,
        start=start,
        end=end,
        stream_index=int((audio_track or {}).get("streamIndex", 0) or 0),
        settings=settings,
    )
    code = _ffmpeg.run(argv)
    if code != 0:  # pragma: no cover - prod seam
        raise RuntimeError(f"ffmpeg audio mux failed (exit {code}) for {out_path}")
    return out_path


@dataclass
class Stages:
    """The injectable pipeline seam (one callable per stage).

    The defaults adapt to the sibling feature modules + ffmpeg, importing them
    lazily so importing *this* module never drags in heavy-ML / ffmpeg deps.
    Tests pass their own callables to assert order + propagation without any real
    provider/verthor/ffmpeg.
    """

    select_candidates: SelectStage = _lazy_select
    snap_candidates: SnapStage = _lazy_snap
    cut_clip: CutStage = _lazy_cut
    trim_silence: SilenceTrimStage = _lazy_trim_silence
    stabilize: StabilizeStage = _lazy_stabilize
    remove_fillers: RemoveFillersStage = _lazy_remove_fillers
    reframe: ReframeStage = _lazy_reframe
    apply_zoom: ZoomStage = _lazy_zoom
    render_caption: CaptionStage = _lazy_caption
    export_clip: ExportStage = _lazy_export
    brand_overlay: BrandOverlayStage = _lazy_brand_overlay
    mux_audio: MuxAudioStage = _lazy_mux_audio


# A loader for a video's transcript + source path, given a videoId. Injected so
# the orchestrator never imports library/whisper directly in tests.
#   load_context(video_id) -> {"path": str, "transcript": Transcript}
ContextLoader = Callable[[str], dict[str, Any]]


# ---------------------------------------------------------------------------
# small helpers (pure)
# ---------------------------------------------------------------------------
def _is_empty_transcript(transcript: Transcript | None) -> bool:
    """True when there is no usable speech to select clips from."""
    if not transcript:
        return True
    segments = transcript.get("segments")
    if not segments:
        return True
    # Any segment with non-blank text counts as speech.
    return not any((seg or {}).get("text", "").strip() for seg in segments)


def _coerce_candidate(raw: Candidate, fallback_rank: int) -> Candidate:
    """Normalize a raw selection dict into a full §3 Candidate.

    Guarantees every §3 field exists with a sane type. ``sourceStart`` defaults
    to the candidate ``start`` until boundary-snap re-bases it. This keeps the
    contract shape stable even if an upstream stage omits an optional field.
    """
    start = float(raw.get("start", 0.0) or 0.0)
    end = float(raw.get("end", 0.0) or 0.0)
    duration = raw.get("durationSec")
    if duration is None:
        duration = max(0.0, end - start)
    out: Candidate = {
        "rank": int(raw.get("rank", fallback_rank) or fallback_rank),
        "start": start,
        "end": end,
        "durationSec": float(duration),
        "hook": str(raw.get("hook", "") or ""),
        "why": str(raw.get("why", "") or ""),
        "score": int(raw.get("score", 0) or 0),
        # §3: sourceStart = the clip's start in the ORIGINAL video.
        "sourceStart": float(raw.get("sourceStart", start) or start),
    }
    # P4 §3: carry the select-stamped scoring fields through coercion when present
    # so EXPORT can persist the clip's viralityPct into its <clip>.json metadata
    # (select() stamps viralityPct; feedback calibration may replace it with
    # calibratedPct). Absent fields stay absent — the SELECT-phase shape is
    # unchanged when upstream didn't set them.
    for key in ("viralityPct", "calibratedPct"):
        if raw.get(key) is not None:
            out[key] = raw[key]
    return out


def _cues_for_clip(transcript: Transcript | None, candidate: Candidate) -> list[Cue]:
    """Build caption cues (in ORIGINAL-video time) overlapping the candidate.

    Cue times stay in original-video time here; the caption stage re-bases them
    to the clip by subtracting ``sourceStart`` (§4). A cue is included when its
    word/segment window overlaps the candidate's [sourceStart, end) span.
    """
    if not transcript:
        return []
    clip_start = float(candidate.get("sourceStart", candidate.get("start", 0.0)))
    clip_end = float(candidate.get("end", 0.0))
    cues: list[Cue] = []
    index = 1
    for seg in transcript.get("segments", []) or []:
        words = (seg or {}).get("words") or []
        # Prefer word-level timing; fall back to the segment span.
        spans = (
            [(float(w["start"]), float(w["end"]), str(w.get("text", ""))) for w in words]
            if words
            else [
                (
                    float((seg or {}).get("start", 0.0)),
                    float((seg or {}).get("end", 0.0)),
                    str((seg or {}).get("text", "")),
                )
            ]
        )
        for s, e, text in spans:
            if e <= clip_start or s >= clip_end:
                continue  # no overlap with the clip window
            if not text.strip():
                continue
            cues.append({"index": index, "start": s, "end": e, "text": text})
            index += 1
    return cues


def _clip_local_words(transcript: Transcript | None, source_start: float, end: float) -> list[dict[str, Any]]:
    """Words within ``[source_start, end)`` re-based to the cut clip's t=0.

    The fillers unit consumes §3 Words on the CLIP-LOCAL timeline (the cut clip
    starts at t=0 via the CUT's ``-ss source_start``), so each kept word's
    ``start``/``end`` has ``source_start`` subtracted (clamped to >= 0). A word
    is kept when it overlaps the clip window. Words without numeric timing are
    skipped (the fillers unit also revalidates).
    """
    out: list[dict[str, Any]] = []
    for w in _words_of(transcript):
        try:
            # float(None) deliberately raises TypeError -> skip untimed words
            # (same idiom as fillers.py); the arg-type ignore documents intent.
            ws = float(w.get("start"))  # type: ignore[arg-type]
            we = float(w.get("end"))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        if we <= source_start or ws >= end:
            continue  # no overlap with the clip window
        out.append(
            {
                "text": str(w.get("text", "") or ""),
                "start": max(0.0, ws - source_start),
                "end": max(0.0, we - source_start),
            }
        )
    return out


def _rebase_cues(cues: list[Cue], source_start: float) -> list[Cue]:
    """Re-base cue times (original-video seconds) to the cut clip's t=0.

    Used only on the filler path: the de-fill stage works in clip-local time, so
    the cues handed to ``remap_cues`` must already be clip-local. Cues that end
    at/before the clip in-point are dropped; indexes renumbered 1..N.
    """
    out: list[Cue] = []
    for cue in cues or []:
        start = max(0.0, float(cue.get("start", 0.0)) - source_start)
        end = max(0.0, float(cue.get("end", 0.0)) - source_start)
        if end <= start:
            continue
        out.append({"index": len(out) + 1, "start": start, "end": end, "text": str(cue.get("text", "") or "")})
    return out


def _ensure_source_start(candidate: Candidate) -> Candidate:
    """Return a copy whose ``sourceStart`` is set (defaults to ``start``)."""
    out = _coerce_candidate(candidate, fallback_rank=candidate.get("rank", 1))
    return out


def _resolve_audio_track(context: dict[str, Any], audio_track_id: str) -> dict[str, Any] | None:
    """Resolve an A2 ``audioTrackId`` against the context's manifest tracks.

    The context loader exposes the video's ``Project.audioTracks`` (A3) under
    ``"audioTracks"``. Returns a copy of the matching track with an internal
    ``streamIndex`` added, or ``None`` when the id is unknown.

    CONTRACT-NOTE (stream index): per tracks_audio's frozen convention, the
    manifest list mirrors container audio-stream order with "original" rows
    seeded FIRST (dubs are appended after). So for kind="original" the track's
    position in the list IS its ``a:<n>`` index in the source container; a
    kind="dub" track's ``path`` is a standalone audio file whose only audio
    stream is ``a:0``.
    """
    tracks = context.get("audioTracks") or []
    if not isinstance(tracks, list):
        return None
    for i, track in enumerate(tracks):
        if isinstance(track, dict) and track.get("id") == audio_track_id:
            resolved = dict(track)
            resolved["streamIndex"] = i if track.get("kind") == "original" else 0
            return resolved
    return None


# ---------------------------------------------------------------------------
# SELECT phase (select + boundary-snap)  ->  shortmaker.select
# ---------------------------------------------------------------------------
def run_select(
    ctx: JobContext,
    *,
    video_id: str,
    prompt: str,
    controls: dict[str, Any] | None,
    load_context: ContextLoader,
    stages: Stages | None = None,
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run SELECT then BOUNDARY-SNAP; return ``{"candidates", "reason"?}``.

    Pipeline (§5):
      1. select.select -> ranked raw candidates
      2. boundary.snap (batch) -> (kept, dropped); dropped clips had no valid
         boundary and carry a per-candidate reason

    Degenerate paths are surfaced in the result, never raised:
      - empty / no-speech transcript -> ``{"candidates": [], "reason": "no clips"}``
      - zero candidates from select  -> reason "no candidates"
      - every candidate dropped at snap -> reason "no clips"
      - fewer survivors than requested  -> reason "too few candidates"
    """
    stages = stages or Stages()
    controls = controls or {}
    settings = settings or {}

    ctx.progress(2, "loading transcript")
    context = load_context(video_id)
    transcript: Transcript | None = context.get("transcript")

    # -- degenerate: no speech -------------------------------------------------
    if _is_empty_transcript(transcript):
        ctx.progress(100, "no clips")
        return {
            "candidates": [],
            "reason": "no clips",
            "detail": "transcript is empty or contains no speech",
        }

    # -- SELECT ----------------------------------------------------------------
    ctx.progress(10, "selecting candidates")
    ctx.raise_if_cancelled()
    raw = stages.select_candidates(transcript, prompt, controls, settings=settings)
    raw = [_coerce_candidate(c, i + 1) for i, c in enumerate(raw or [])]

    # -- degenerate: zero candidates ------------------------------------------
    if not raw:
        ctx.progress(100, "no candidates")
        return {
            "candidates": [],
            "reason": "no candidates",
            "detail": "selection produced zero candidates for this prompt",
        }

    # -- BOUNDARY-SNAP (batch) -------------------------------------------------
    ctx.progress(55, "snapping boundaries")
    ctx.raise_if_cancelled()
    kept, dropped = stages.snap_candidates(raw, transcript, settings=settings)
    kept = [_coerce_candidate(c, i + 1) for i, c in enumerate(kept or [])]

    requested = int(controls.get("count", len(raw)) or len(raw))
    out: dict[str, Any] = {"candidates": kept}
    if dropped:
        # Normalize each dropped entry to a compact {rank, hook, reason} record.
        out["dropped"] = [_drop_record(d) for d in dropped]

    # -- degenerate: too few / none survived ----------------------------------
    if not kept:
        out["reason"] = "no clips"
        out["detail"] = "every candidate was dropped at boundary-snap"
    elif len(kept) < requested:
        out["reason"] = "too few candidates"
        out["detail"] = f"{len(kept)} of {requested} requested clips survived"

    ctx.progress(100, f"{len(kept)} candidate(s)")
    return out


def _drop_record(dropped: Any) -> dict[str, Any]:
    """Normalize a boundary-drop entry into ``{rank, hook, reason}``.

    The boundary unit returns ``{"candidate", "reason"}``; we surface the
    candidate's rank/hook alongside the reason so the UI can explain the drop.
    """
    if not isinstance(dropped, dict):
        return {"reason": str(dropped)}
    cand = dropped.get("candidate") or {}
    return {
        "rank": cand.get("rank"),
        "hook": cand.get("hook"),
        "reason": dropped.get("reason", "no valid boundary"),
    }


# ---------------------------------------------------------------------------
# EXPORT phase (cut -> reframe -> caption -> export)  ->  shortmaker.export
# ---------------------------------------------------------------------------
def _candidate_virality(candidate: Candidate) -> int | None:
    """The clip's score for the §3 ``viralityPct`` field, or None when absent.

    ``calibratedPct`` (when feedback calibration is active) REPLACES
    ``viralityPct`` in the candidate payload (features.feedback), so prefer it.
    """
    for key in ("calibratedPct", "viralityPct"):
        value = candidate.get(key)
        if value is not None:
            try:
                return int(value)
            except (TypeError, ValueError):
                return None
    return None


def _write_short_metadata(
    final_path: str,
    *,
    candidate: Candidate,
    settings: dict[str, Any],
    video_id: str,
    source_title: str,
    hook: str | None,
) -> None:
    """Persist the §3 ``<clip>.json`` for a finished export (P4 C5, PRIMARY path).

    The template id is the per-export ``captionStyle`` (T4b); the hook is the
    rendered ``hook`` title when present, else the candidate's own hook text.
    Duration comes from the candidate's ``durationSec`` (clamped at select time).
    Delegated to ``features.shorts`` so the ShortInfo schema lives in one place.
    """
    from . import shorts as _shorts  # lazy: keep shortmaker import-light

    hook_text = (hook or str(candidate.get("hook", "") or "")).strip()
    meta = _shorts.build_metadata(
        video_id=video_id,
        source_title=source_title,
        template=str(settings.get("captionStyle") or ""),
        virality_pct=_candidate_virality(candidate),
        duration_sec=float(candidate.get("durationSec", 0.0) or 0.0),
        hook=hook_text,
    )
    _shorts.write_export_metadata(final_path, meta)


def _export_one(
    candidate: Candidate,
    *,
    source_path: str,
    transcript: Transcript | None,
    out_dir: Path,
    stem: str,
    stages: Stages,
    aspect: str,
    settings: dict[str, Any],
    audio_track: dict[str, Any] | None = None,
    video_id: str = "",
    source_title: str = "",
    on_notice: Callable[[dict[str, str]], None] | None = None,
) -> dict[str, Any]:
    """Run CUT (-> SILENCE-TRIM -> STABILIZE -> REMOVE-FILLERS) -> REFRAME -> CAPTION -> EXPORT (-> MUX-AUDIO).

    Returns ``{"candidate", "path"[, "fillersRemoved", "fillerSeconds"]}`` (the
    §3 Project.clips shape + the P3-B per-clip stats when filler removal ran).
    Each stage writes its own intermediate so a failure is localized.

    audio-stabilize group (after the CUT, before REFRAME):
      - ``settings["silenceTrim"]``: remove dead air (ffmpeg silencedetect ->
        keep-span re-cut). This CHANGES the clip timeline, so it is mutually
        exclusive with REMOVE-FILLERS (which derives clip-local cues from the
        ORIGINAL timings) — when both are set, silence-trim wins and de-fill is
        skipped (avoids a cue desync).
      - ``settings["stabilize"]``: camera-shake stabilization (vidstab 2-pass).
        Warp-only — it does NOT change the timeline, so it always composes with
        the other stages. A missing libvidstab passes the clip through and emits
        the typed notice via ``on_notice`` (never a silent skip).

    P3-B (``settings["removeFillers"]`` truthy): AFTER the CUT (which re-bases the
    clip to t=0 via ``-ss source_start``) the clip's words/cues are taken on the
    clip-local timeline, de-filled (frame-accurate concat of the kept spans), and
    the cues remapped onto the compressed timeline. The de-filled clip feeds
    REFRAME and the remapped (clip-local) cues feed CAPTION with ``source_start=0``
    (already re-based). When OFF, behavior is byte-identical to the base pipeline.

    P3-A (``settings["hookTitle"]`` truthy, the DEFAULT): the candidate's ``hook``
    is rendered as a top-of-frame headline by the CAPTION stage.

    When ``audio_track`` is given (A2 ``audioTrackId``), the chosen track's
    [sourceStart, end) window is muxed onto the exported clip as a final stage.

    ``on_notice`` (optional): a sink for typed stage notices (e.g. the stabilize
    libvidstab-unavailable notice) the orchestrator routes to ``job.progress``.
    """
    # CUT — frame-accurate carve; persist sourceStart on the clip record (§3).
    source_start = float(candidate.get("sourceStart", candidate.get("start", 0.0)))
    end = float(candidate.get("end", 0.0))
    cut_path = str(out_dir / f"{stem}.cut.mp4")
    stages.cut_clip(source_path, cut_path, source_start, end, settings=settings)

    # The clip the rest of the pipeline operates on, the cues handed to CAPTION,
    # and the source_start CAPTION re-bases by. Defaults = the base (OFF) path:
    # cues in ORIGINAL-video time, re-based by the real sourceStart in CAPTION.
    stage_clip = cut_path
    caption_cues: list[Cue] = _cues_for_clip(transcript, candidate)
    caption_source_start = source_start
    filler_stats: dict[str, Any] | None = None
    silence_removed: float = 0.0

    # SILENCE-TRIM (audio-stabilize group) — dead-air removal, ON when the
    # ``silenceTrim`` toggle is set. Runs on the cut clip (clip-local t=0). It
    # CHANGES the clip's timeline, so it is mutually exclusive with REMOVE-FILLERS
    # (whose clip-local cues are derived from the ORIGINAL timings); when both are
    # set, silence-trim wins and de-fill is skipped below.
    #
    # CUE REMAP (bug fix): the trim drops INTERIOR silence between/within spoken
    # cues, so every cue AFTER a removed gap shifts earlier on the compacted
    # timeline. The cues MUST be re-timed onto that timeline or captions drift late
    # by the removed duration. Mirror the REMOVE-FILLERS path exactly: re-base the
    # cues to clip-local, remap them across the kept spans the trim returned, and
    # tell CAPTION the clip is already re-based (``source_start = 0``). A
    # pass-through (nothing removed) returns the full-length keeps -> identity remap.
    silence_trim_on = bool((settings or {}).get("silenceTrim"))
    if silence_trim_on:
        from . import fillers as _fillers  # local: shared cue-remap, import-light

        trimmed_path = str(out_dir / f"{stem}.trimmed.mp4")
        stage_clip, silence_removed, silence_keeps = stages.trim_silence(cut_path, trimmed_path, settings=settings)
        local_cues = _rebase_cues(caption_cues, source_start)
        caption_cues = _fillers.remap_cues(local_cues, silence_keeps)
        caption_source_start = 0.0

    # STABILIZE (audio-stabilize group, the DIFFERENTIATOR) — camera-shake
    # stabilization via ffmpeg vidstab 2-pass, DEFAULT-ON in the reframe/shorts
    # path (steadier vertical clips out of the box) and only disabled by an
    # EXPLICIT ``stabilize: False`` toggle. It does NOT change the timeline (warp
    # only), so captions stay in sync and it can run on whatever the trim
    # produced. The stage's own ``stabilize_clip`` is the libvidstab gate: when
    # libvidstab is missing it passes the clip through unchanged and surfaces a
    # typed notice via the ``on_notice`` sink (the orchestrator routes it to
    # job.progress) — never a silent skip, so default-on degrades gracefully.
    if (settings or {}).get("stabilize", True):
        stabilized_path = str(out_dir / f"{stem}.stabilized.mp4")
        stage_clip = stages.stabilize(
            stage_clip,
            stabilized_path,
            settings=settings,
            on_notice=on_notice,
        )

    # REMOVE-FILLERS (P3-B) — only when the toggle is ON AND silence-trim did not
    # already alter the timeline (mutually exclusive — see the silence-trim note
    # above). Runs on the STAGED clip (so a prior stabilize composes — stabilize
    # is warp-only and preserves the clip-local timeline the de-fill words assume)
    # and produces a de-filled clip + remapped clip-local cues.
    if (settings or {}).get("removeFillers") and not silence_trim_on:
        lang = (transcript or {}).get("language")
        local_words = _clip_local_words(transcript, source_start, end)
        local_cues = _rebase_cues(caption_cues, source_start)
        defilled_path = str(out_dir / f"{stem}.defilled.mp4")
        stage_clip, caption_cues, filler_stats = stages.remove_fillers(
            stage_clip,
            defilled_path,
            local_words,
            local_cues,
            lang=lang,
            settings=settings,
        )
        # The de-filled clip is already clip-local; cues are remapped clip-local.
        caption_source_start = 0.0

    # REFRAME — verthor adapter (center-crop fallback handled INSIDE the engine).
    reframed_path = str(out_dir / f"{stem}.reframed.mp4")
    stages.reframe(stage_clip, reframed_path, aspect, settings=settings)
    caption_clip = reframed_path

    # P4 §8b / C16: AUTO PUNCH-IN ZOOM — inserted BETWEEN reframe and caption
    # (the proven order: reframe -> zoom -> captions) so the zoom rides the framed
    # video and captions land on top of it. OFF by default (``autoZoom``). Beats
    # are sentence-starts from the clip's cues (v1); the de-filled path already
    # remapped them to t=0, so the zoom stage re-bases by ``caption_source_start``.
    if (settings or {}).get("autoZoom"):
        zoomed_path = str(out_dir / f"{stem}.zoomed.mp4")
        zoom_duration = max(0.0, float(end) - float(source_start))
        stages.apply_zoom(
            reframed_path,
            zoomed_path,
            caption_cues,
            source_start=caption_source_start,
            duration_sec=zoom_duration,
            settings=settings,
        )
        caption_clip = zoomed_path

    # P4 §8a: annotate the cues with deterministic emphasis spans + a trailing
    # emoji when the export's ``emphasis`` flag resolves ON (explicit setting or
    # the per-style default — ON for OpusClip-style templates, OFF for
    # clean/minimal/none). The annotated cues flow into BOTH caption engines
    # (libass build_ass + remotion build_job consume ``emphasis``/``emoji``); the
    # live overlay mirrors the same deterministic annotation client-side.
    from . import emphasis as _emphasis  # lazy: keep shortmaker import-light

    caption_cues = _emphasis.annotate(caption_cues, enable=_emphasis.resolve_emphasis(settings))

    # CAPTION — libass burn-in; cue times re-based by subtracting source_start.
    # P3-A: render the candidate's hook as a top title when hookTitle is set
    # (default ON; absent in settings counts as ON per the P3 mini-contract).
    hook_title = None
    if (settings or {}).get("hookTitle", True):
        hook_text = str(candidate.get("hook", "") or "").strip()
        hook_title = hook_text or None
    captioned_path = str(out_dir / f"{stem}.captioned.mp4")
    stages.render_caption(
        caption_clip,
        caption_cues,
        captioned_path,
        source_start=caption_source_start,
        burn=True,
        width=OUT_WIDTH,
        height=OUT_HEIGHT,
        settings=settings,
        hook_title=hook_title,
    )

    # P4 §8d: BRAND-LOGO OVERLAY — composite the configured brand logo into a
    # padded corner ON the captioned frame (so the watermark sits above captions),
    # only when ``brandLogoPath`` is set. Reuses the second-input pattern via the
    # drained ffmpeg.run seam (C16). The final {stem}.mp4 path is unchanged.
    from . import brandkit as _brandkit  # lazy: keep shortmaker import-light

    export_input = captioned_path
    if _brandkit.has_brand_logo(settings):
        branded_path = str(out_dir / f"{stem}.branded.mp4")
        stages.brand_overlay(
            captioned_path,
            branded_path,
            _brandkit.brand_logo_path(settings),
            settings=settings,
        )
        export_input = branded_path

    # EXPORT — final libx264 encode.
    final_path = str(out_dir / f"{stem}.mp4")
    if audio_track is None:
        stages.export_clip(export_input, final_path, settings=settings)
    else:
        # MUX-AUDIO (A2 audioTrackId): encode to an intermediate, then swap the
        # clip's audio for the chosen track's [sourceStart, end) window. The
        # final contract path ({stem}.mp4) stays identical either way.
        encoded_path = str(out_dir / f"{stem}.encoded.mp4")
        stages.export_clip(export_input, encoded_path, settings=settings)
        stages.mux_audio(
            encoded_path,
            audio_track,
            final_path,
            start=source_start,
            end=end,
            settings=settings,
        )

    # P4 §3/C5: write the PRIMARY ``<clip>.json`` metadata next to the mp4 so
    # ``shorts.list`` reconstructs ShortInfo without re-probing. hook / template /
    # viralityPct / duration are all still in scope here.
    _write_short_metadata(
        final_path,
        candidate=candidate,
        settings=settings,
        video_id=video_id,
        source_title=source_title,
        hook=hook_title,
    )

    # CONTRACT-NOTE: §3 Project.clips entries are {candidate, path}; the export
    # result list is {path} per §2, so we carry both — callers pick what they need.
    clip_candidate = dict(candidate)
    clip_candidate["sourceStart"] = source_start
    item: dict[str, Any] = {"candidate": clip_candidate, "path": final_path}
    # P3-B: surface the per-clip filler stats on the clip payload (frozen P3
    # mini-contract: {fillersRemoved:int, fillerSeconds:float} per clip).
    if filler_stats is not None:
        item["fillersRemoved"] = int(filler_stats.get("fillersRemoved", 0) or 0)
        item["fillerSeconds"] = float(filler_stats.get("fillerSeconds", 0.0) or 0.0)
    # audio-stabilize group: surface the per-clip dead-air-removed seconds when
    # silence-trim actually cut something (absent when the toggle was off or there
    # was nothing to trim — mirrors the optional P3-B filler stats shape).
    if silence_removed > 0.0:
        item["silenceRemovedSec"] = round(float(silence_removed), 3)
    return item


def run_export(
    ctx: JobContext,
    *,
    video_id: str,
    candidates: list[Candidate],
    load_context: ContextLoader,
    out_dir: str,
    stages: Stages | None = None,
    settings: dict[str, Any] | None = None,
    audio_track_id: str | None = None,
) -> dict[str, Any]:
    """Export the approved ``candidates`` to finished vertical shorts.

    For each candidate runs CUT -> REFRAME -> CAPTION -> EXPORT (plus the
    MUX-AUDIO stage when A2's optional ``audio_track_id`` is given), streaming
    progress, and returns ``{"clips": [{"path"}, ...]}`` (§2). The full
    ``{candidate, path}`` records are returned under ``"items"`` for callers that
    persist them into the Project manifest (§3).

    Degenerate: an empty ``candidates`` batch yields ``{"clips": [],
    "reason": "no clips"}`` rather than doing work. An UNKNOWN ``audio_track_id``
    raises — the failure surfaces via the job.done error payload (A6.3), never
    silently exports the wrong audio.
    """
    stages = stages or Stages()
    settings = settings or {}
    candidates = list(candidates or [])

    # P4 §8d: apply the brand kit's default caption template/font when the user
    # did not override them on this export (immutable — returns a new dict; the
    # user's explicit captionStyle/captionFontFamily always wins).
    from . import brandkit as _brandkit  # lazy: keep module import-light

    settings = _brandkit.resolve_brand_defaults(settings)

    if not candidates:
        ctx.progress(100, "no clips")
        return {"clips": [], "reason": "no clips", "detail": "no candidates to export"}

    ctx.progress(2, "loading source")
    context = load_context(video_id)
    source_path = context.get("path", "")
    transcript: Transcript | None = context.get("transcript")
    # P4 §3: the source video title for the persisted ShortInfo (blank if the
    # context loader doesn't expose it — back-compat).
    source_title = str(context.get("sourceTitle", "") or "")
    aspect = str(settings.get("aspect") or DEFAULT_ASPECT)

    # A2 audioTrackId: resolve the AudioTrack against the project manifest's
    # audioTracks (exposed by the context loader) BEFORE any stage runs.
    audio_track: dict[str, Any] | None = None
    if audio_track_id:
        audio_track = _resolve_audio_track(context, audio_track_id)
        if audio_track is None:
            raise ValueError(f"unknown audio track: {audio_track_id}")

    # T4b/P3: resolve the reframe engine ONCE per export. "auto" now resolves to
    # the in-sidecar claudeshorts engine (no WSL); an explicit "verthor" on a
    # host without WSL raises (handled by the job's error path).
    from . import reframe as _reframe_mod  # lazy: keeps module import-light

    engine_name, _notice = _reframe_mod.resolve_engine_name(str(settings.get("reframeEngine") or "auto"), settings)
    settings = {**settings, "reframeEngine": engine_name}

    dest = Path(out_dir)
    dest.mkdir(parents=True, exist_ok=True)

    # audio-stabilize group: a per-export sink for typed stage notices (e.g. the
    # stabilize libvidstab-unavailable notice). Surfaced via job.progress and
    # de-duplicated so the same notice across N clips is announced once (the skip
    # is REPORTED, never silently swallowed — the "do NOT silently skip" rule).
    _seen_notices: set[str] = set()

    def _emit_notice(notice: dict[str, str]) -> None:
        key = str(notice.get("type") or notice.get("message") or "")
        if key in _seen_notices:
            return
        _seen_notices.add(key)
        ctx.progress(4, notice.get("message", "stabilize: notice"))

    items: list[dict[str, Any]] = []
    total = len(candidates)
    for i, candidate in enumerate(candidates):
        ctx.raise_if_cancelled()
        candidate = _ensure_source_start(candidate)
        rank = candidate.get("rank", i + 1)
        stem = f"{Path(source_path).stem or 'clip'}-{rank}"
        ctx.progress(int(100 * i / total), f"exporting clip {i + 1}/{total}")
        item = _export_one(
            candidate,
            source_path=source_path,
            transcript=transcript,
            out_dir=dest,
            stem=stem,
            stages=stages,
            aspect=aspect,
            settings=settings,
            audio_track=audio_track,
            video_id=video_id,
            source_title=source_title,
            on_notice=_emit_notice,
        )
        items.append(item)

    ctx.progress(100, f"exported {len(items)} clip(s)")
    # §2: shortmaker.export -> {clips:[{path}]}; P3-B adds the OPTIONAL per-clip
    # {fillersRemoved, fillerSeconds} when filler removal ran for that clip (the
    # base {path}-only shape is preserved when it did not — UI annotates only
    # when present).
    return {"clips": [_clip_payload(it) for it in items], "items": items}


def _clip_payload(item: dict[str, Any]) -> dict[str, Any]:
    """Build the §2 ``clips`` entry: ``{path}`` plus P3-B filler stats if set."""
    clip: dict[str, Any] = {"path": item["path"]}
    if "fillersRemoved" in item:
        clip["fillersRemoved"] = int(item["fillersRemoved"])
        clip["fillerSeconds"] = float(item.get("fillerSeconds", 0.0))
    return clip


# ---------------------------------------------------------------------------
# RPC registration (shortmaker.select / shortmaker.export)
# ---------------------------------------------------------------------------
@dataclass
class ShortMaker:
    """Binds the orchestration to a JobRegistry + context/output providers.

    The RPC handlers (registered via :meth:`register`) start a Job for each
    long-running operation and return ``{"jobId"}`` immediately (§2); progress
    streams as ``job.progress`` and the terminal payload arrives via ``job.done``.
    """

    load_context: ContextLoader
    out_dir_for: Callable[[str], str]
    stages: Stages = field(default_factory=Stages)
    settings_provider: Callable[[], dict[str, Any]] = lambda: {}

    # -- handlers ----------------------------------------------------------
    def select(self, params: dict[str, Any], ctx: Any) -> dict[str, Any]:
        """``shortmaker.select`` -> ``{jobId}`` (streams to ``{candidates}``)."""
        video_id = params.get("videoId")
        prompt = params.get("prompt", "")
        controls = params.get("controls") or {}
        if not isinstance(video_id, str) or not video_id:
            raise _invalid_params("videoId (str) is required")
        settings = self.settings_provider()

        def handler(job_ctx: JobContext) -> dict[str, Any]:
            return run_select(
                job_ctx,
                video_id=video_id,
                prompt=str(prompt or ""),
                controls=controls,
                load_context=self.load_context,
                stages=self.stages,
                settings=settings,
            )

        job = ctx.jobs.start(handler)
        return {"jobId": job.id}

    def export(self, params: dict[str, Any], ctx: Any) -> dict[str, Any]:
        """``shortmaker.export`` -> ``{jobId}`` (streams to ``{clips:[{path}]}``)."""
        video_id = params.get("videoId")
        candidate_ids = params.get("candidateIds") or []
        candidates = params.get("candidates") or []
        if not isinstance(video_id, str) or not video_id:
            raise _invalid_params("videoId (str) is required")
        settings = dict(self.settings_provider())
        # T4b: optional per-export string overrides (renderer ShortMaker controls).
        for key in ("reframeEngine", "captionStyle"):
            value = params.get(key)
            if isinstance(value, str) and value:
                settings[key] = value
        # P3/P4: optional per-export BOOLEAN toggles (frozen mini-contract):
        #   hookTitle (default true)  -> render the candidate's hook as a top
        #                                title in the CAPTION stage (P3-A);
        #   removeFillers (default false) -> de-fill each clip after the CUT,
        #                                    remapping cues to stay in sync (P3-B);
        #   emphasis (default per-style: ON for OpusClip-style templates, OFF for
        #             clean/minimal/none) -> §8a keyword highlight + trailing emoji
        #             in BOTH caption engines. Absent -> the per-style default
        #             (features.emphasis.resolve_emphasis on captionStyle).
        #   autoZoom (default false) -> §8b auto punch-in zoom stage between
        #             reframe and caption (the run_export gate reads settings
        #             ["autoZoom"]). Absent -> OFF.
        # Booleans flow exactly like the string overrides above, but through a
        # dedicated extraction (a string loop would coerce/skip a real bool).
        #   silenceTrim (default false) -> audio-stabilize group: dead-air removal
        #             pre-step (ffmpeg silencedetect -> keep-span re-cut), run on
        #             each cut clip before reframe; mutually exclusive with
        #             removeFillers (silence-trim wins).
        #   stabilize (DEFAULT TRUE in the reframe/shorts path) -> audio-stabilize
        #             group: camera-shake stabilization pre-step (ffmpeg vidstab
        #             2-pass), warp-only so it composes with every other stage; a
        #             missing libvidstab is reported via job.progress, never
        #             silently skipped (so default-on degrades gracefully). An
        #             explicit ``stabilize: false`` from the caller disables it.
        for key in ("hookTitle", "removeFillers", "emphasis", "autoZoom", "silenceTrim", "stabilize"):
            value = params.get(key)
            if isinstance(value, bool):
                settings[key] = value
        # A2: optional audioTrackId — carry the chosen audio track into clips.
        audio_track_id = params.get("audioTrackId")
        if audio_track_id is not None and not isinstance(audio_track_id, str):
            raise _invalid_params("audioTrackId must be a string when given")
        audio_track_id = audio_track_id or None  # "" == absent (UI "Original")
        out_dir = self.out_dir_for(video_id)

        # CONTRACT-NOTE: §2 passes ``candidateIds`` (references to a prior
        # shortmaker.select result). The renderer typically also forwards the
        # Candidate objects as ``candidates``; when only ids are given we resolve
        # them via the context loader's ``candidates`` map (id -> Candidate).
        resolved = self._resolve_candidates(video_id, candidate_ids, candidates)

        def handler(job_ctx: JobContext) -> dict[str, Any]:
            return run_export(
                job_ctx,
                video_id=video_id,
                candidates=resolved,
                load_context=self.load_context,
                out_dir=out_dir,
                stages=self.stages,
                settings=settings,
                audio_track_id=audio_track_id,
            )

        job = ctx.jobs.start(handler)
        return {"jobId": job.id}

    def _resolve_candidates(
        self,
        video_id: str,
        candidate_ids: list[Any],
        inline: list[Candidate],
    ) -> list[Candidate]:
        """Resolve candidate ids to Candidate dicts.

        Prefers an explicit inline ``candidates`` list (the renderer typically
        forwards the select result). When only ids are supplied, asks the
        context loader for a ``candidates`` map (id -> Candidate) and selects the
        requested ids; unknown ids are skipped.
        """
        if inline:
            return list(inline)
        if not candidate_ids:
            return []
        context = self.load_context(video_id)
        by_id = context.get("candidates") or {}
        out: list[Candidate] = []
        for cid in candidate_ids:
            cand = by_id.get(cid) if isinstance(by_id, dict) else None
            if cand is not None:
                out.append(cand)
        return out

    # -- registration ------------------------------------------------------
    def register(self, registrar: Callable[[str, Callable[..., Any]], None]) -> None:
        """Register both handlers with a ``register(name, handler)`` callable.

        ``registrar`` is typically ``protocol.register``; kept injectable so the
        RPC wiring stays a one-liner and tests can use a fake registrar.
        """
        registrar("shortmaker.select", self.select)
        registrar("shortmaker.export", self.export)


def _invalid_params(message: str) -> Exception:
    """Build an INVALID_PARAMS RpcError, importing protocol lazily.

    Lazy import keeps this module free of an import cycle with ``protocol`` and
    avoids pulling protocol into pure-logic tests that exercise the run_* fns.
    """
    from ..protocol import ErrorCode, RpcError

    return RpcError(message, ErrorCode.INVALID_PARAMS)
