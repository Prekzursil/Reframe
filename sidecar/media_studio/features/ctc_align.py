"""Word-timing forced alignment — ctc-forced-aligner 2nd pass (Phase-8 WU6).

After ASR produces a §3 :class:`Transcript`, this module refines the *word*
timings of each segment by force-aligning the segment text against the audio with
a CTC model (``ctc-forced-aligner``, MahmoudAshraf). The result is karaoke-grade
word ``start``/``end`` boundaries that the caption builder consumes.

Design (the canonical Phase-8 seam pattern — see ``diarize`` / ``audio_saliency``
/ ``scene_transnet``):

  * **Pure half (fully covered, no heavy deps):** flattening a transcript's
    segments into an ordered token list (:func:`tokens_from_segments`), turning a
    backend's per-word span list into normalized word timings
    (:func:`emissions_to_word_timings`), and stitching those timings back into an
    IMMUTABLE copy of the transcript (:func:`merge_word_times_into_transcript`).
    Every line is unit-tested with hand-built transcripts + canned word spans.

  * **Heavy half (behind a seam, never imported at module load):** the real
    ctc-forced-aligner / torch pipeline lives in ``ctc_align_backend.py`` and is
    built LAZILY by :func:`_default_backend_factory`; the audio decode
    (ffmpeg -> numpy) is the injectable ``audio_loader`` seam. Tests inject a
    fake :class:`CtcAlignBackend` returning canned word spans and a fake loader
    returning synthetic samples — no torch, no aligner, no ffmpeg.

Decision #1 (license): the package DEFAULT model
``MahmoudAshraf/mms-300m-1130-forced-aligner`` is **CC-BY-NC-4.0** (non-commercial
only) — fine for the local desktop tool. A commercial build overrides it with an
**MIT** wav2vec2 model id via ``settings['ctcModelId']`` or the ``model_id`` arg
(see :data:`MIT_MODEL_IDS`). The default + override flow through one
``_resolve_model_id`` so a single switch picks the model everywhere.

Missing-modality / degrade contract: when the model is unavailable (offline AND
the asset is not installed) — or any backend failure occurs — :func:`align_words`
returns the input transcript UNCHANGED (its existing word timings preserved),
never raising. The same applies to an empty transcript or an empty audio buffer.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from ..util import clamp, get_logger
from . import offline as _offline

if TYPE_CHECKING:  # numpy IS in the venv; kept import-light for symmetry with peers.
    import numpy as np

log = get_logger("media_studio.features.ctc_align")

# Type aliases matching CONTRACTS.md §3 (plain JSON-able dicts both sides).
Word = dict[str, Any]
Segment = dict[str, Any]
Transcript = dict[str, Any]

# --------------------------------------------------------------------------- #
# model ids + asset (Decision #1: CC-BY-NC default, MIT override available)
# --------------------------------------------------------------------------- #
#: the package default — CC-BY-NC-4.0, 158-language, ungated. Local-tool default.
DEFAULT_MODEL_ID = "MahmoudAshraf/mms-300m-1130-forced-aligner"

#: commercial-safe MIT wav2vec2/HuBERT alternatives (the Decision #1 swap).
#: Keyed by a short alias the UI/settings can surface; values are the model ids.
MIT_MODEL_IDS: dict[str, str] = {
    "wav2vec2-960h-lv60": "facebook/wav2vec2-large-960h-lv60-self",
    "wav2vec2-960h": "facebook/wav2vec2-large-960h",
    "hubert-large": "facebook/hubert-large-ls960-ft",
}

#: the on-demand asset name for the DEFAULT model (Wave-2 manifest entry).
ASSET_NAME = "ctc-forced-aligner-mms"
#: the on-demand asset name for the MIT commercial-override model.
MIT_ASSET_NAME = "ctc-forced-aligner-wav2vec2"

#: a cooperative cancel probe + progress sink (match the rest of the codebase).
CancelProbe = Callable[[], bool]
ProgressCb = Callable[[float, str], None]


# --------------------------------------------------------------------------- #
# the heavy backend seam (ctc-forced-aligner) — never imported at module load
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class WordSpan:
    """One aligned word: its text + start/end in seconds on the audio timeline.

    The backend returns these in transcript order; the pure layer maps them back
    onto the segments. ``score`` carries the aligner's per-word confidence (0..1)
    when available, defaulting to 1.0.
    """

    text: str
    start: float
    end: float
    score: float = 1.0


class CtcAlignBackend(Protocol):
    """The slice of the ctc-forced-aligner pipeline the pure runner needs.

    A real impl (built lazily by :func:`_default_backend_factory`, never at
    import) force-aligns ``tokens`` against the mono ``samples`` and returns one
    :class:`WordSpan` per token in order. Tests inject a fake returning hand-built
    spans — no model, no weights, no torch.
    """

    def align(
        self,
        samples: np.ndarray,
        sr: int,
        tokens: Sequence[str],
        *,
        language: str | None = None,
        on_progress: ProgressCb | None = None,
        should_cancel: CancelProbe | None = None,
    ) -> list[WordSpan]:
        """Return one :class:`WordSpan` per token, in order."""
        ...  # pragma: no cover - Protocol method body is never executed


#: factory seam: default = lazy real impl; tests inject a fake.
BackendFactory = Callable[[dict[str, Any], str], CtcAlignBackend]
#: audio decode seam: path -> (mono samples float array, sample-rate). The
#: default lazily uses ffmpeg -> numpy (NO heavy-ML dep: ffmpeg + numpy only).
AudioLoader = Callable[[str], "tuple[np.ndarray, int]"]
#: availability probe seam: is the model asset installed? (drives degrade).
ModelsPresent = Callable[[dict[str, Any], str], bool]


# --------------------------------------------------------------------------- #
# pure: model-id resolution (Decision #1 switch)
# --------------------------------------------------------------------------- #
def _resolve_model_id(settings: dict[str, Any], model_id: str | None) -> str:
    """Pick the alignment model id: explicit arg > settings > package default.

    ``model_id`` (the call arg) wins so a caller can force a model per-job. Next
    is ``settings['ctcModelId']`` — which may be a full HF id OR one of the
    :data:`MIT_MODEL_IDS` aliases (resolved to its id). Absent both, the
    CC-BY-NC package default is used (fine for the local tool).
    """
    if model_id:
        return MIT_MODEL_IDS.get(model_id, model_id)
    configured = settings.get("ctcModelId")
    if isinstance(configured, str) and configured:
        return MIT_MODEL_IDS.get(configured, configured)
    return DEFAULT_MODEL_ID


def _asset_for_model(model_id: str) -> str:
    """The asset name guarding a model id (MIT override vs the default MMS)."""
    return ASSET_NAME if model_id == DEFAULT_MODEL_ID else MIT_ASSET_NAME


# --------------------------------------------------------------------------- #
# pure: transcript <-> token list
# --------------------------------------------------------------------------- #
def tokens_from_segments(transcript: Transcript) -> list[str]:
    """Flatten a transcript into an ordered list of word tokens.

    Prefers each segment's per-word ``text`` (already tokenized by the ASR); a
    segment lacking a ``words`` list is whitespace-split from its ``text`` so a
    word-less transcript can still be aligned. Empty/blank tokens are dropped so
    the backend never receives a phantom word. Order is transcript order.
    """
    tokens: list[str] = []
    for seg in transcript.get("segments") or []:
        words = seg.get("words") or []
        if words:
            for w in words:
                text = str(w.get("text") or "").strip()
                if text:
                    tokens.append(text)
        else:
            # str.split() (no sep) already drops whitespace runs and never yields
            # a blank piece, so every split token is a real word.
            tokens.extend(str(seg.get("text") or "").split())
    return tokens


def emissions_to_word_timings(
    spans: Sequence[WordSpan],
    *,
    duration: float | None = None,
) -> list[Word]:
    """Normalize a backend's word spans into §3 :class:`Word` dicts.

    Each span becomes ``{text, start, end, score}`` with times coerced to floats,
    clamped to ``[0, duration]`` when a ``duration`` is given (defensive — an
    aligner artifact must not place a word past the clip), and ``end`` floored at
    ``start`` so a degenerate span never goes backwards. Order is preserved.
    """
    hi = float(duration) if duration is not None and duration > 0.0 else None
    out: list[Word] = []
    for span in spans:
        start = float(span.start)
        end = float(span.end)
        if hi is not None:
            start = clamp(start, 0.0, hi)
            end = clamp(end, 0.0, hi)
        else:
            start = max(0.0, start)
            end = max(0.0, end)
        end = max(start, end)
        out.append(
            {
                "text": str(span.text),
                "start": round(start, 3),
                "end": round(end, 3),
                "score": float(clamp(span.score, 0.0, 1.0)),
            }
        )
    return out


def merge_word_times_into_transcript(
    transcript: Transcript,
    word_times: Sequence[Word],
) -> Transcript:
    """Stitch aligned ``word_times`` back onto the transcript's segments.

    Returns a NEW transcript (immutable copy — never mutates the input). The
    aligned words are consumed in transcript order: each segment takes as many
    words as it originally had (matched by its ``words`` count, or its
    whitespace-split word count when it had none), so the per-segment grouping is
    preserved while the timings are refreshed. Each refreshed segment's ``start``
    /``end`` is also widened to span its first/last refreshed word. When the
    aligned list runs short (fewer words than the transcript), the remaining
    segments are returned UNCHANGED — a partial alignment never drops text.
    """
    refreshed_segments: list[Segment] = []
    cursor = 0
    total = len(word_times)
    for seg in transcript.get("segments") or []:
        count = _segment_word_count(seg)
        if count <= 0 or cursor >= total:
            refreshed_segments.append({**seg})
            continue
        take = word_times[cursor : cursor + count]
        cursor += len(take)
        if len(take) < count:
            # Partial coverage of this segment: keep it unchanged (no half-retime).
            refreshed_segments.append({**seg})
            continue
        new_words = [dict(w) for w in take]
        new_seg: Segment = {
            **seg,
            "words": new_words,
            "start": new_words[0]["start"],
            "end": new_words[-1]["end"],
        }
        refreshed_segments.append(new_seg)
    return {**transcript, "segments": refreshed_segments}


def _segment_word_count(seg: Segment) -> int:
    """How many word tokens a segment contributed to :func:`tokens_from_segments`."""
    words = seg.get("words") or []
    if words:
        return sum(1 for w in words if str(w.get("text") or "").strip())
    return len(str(seg.get("text") or "").split())


# --------------------------------------------------------------------------- #
# default heavy seams (lazy real impls; tests inject fakes)
# --------------------------------------------------------------------------- #
def _default_backend_factory(
    settings: dict[str, Any],
    model_id: str,
) -> CtcAlignBackend:  # pragma: no cover - prod seam (imports the heavy native stack)
    """Build the real ctc-forced-aligner backend (LAZY import; runtime only)."""
    from .ctc_align_backend import RealCtcAlignBackend  # noqa: PLC0415 - heavy seam

    return RealCtcAlignBackend(settings, model_id)


def _default_audio_loader(media_path: str) -> tuple[np.ndarray, int]:  # pragma: no cover - needs ffmpeg + a real file
    """Decode ``media_path`` to mono float samples at 16 kHz via ffmpeg.

    Excluded from coverage: it spawns ffmpeg and reads a real media file (the
    pure logic + the seam branches are covered with a fake loader). Lives here
    (not the backend module) because it has NO heavy-ML dep — only ffmpeg+numpy.
    """
    import subprocess  # noqa: PLC0415, S404 - argv-list only, never shell=True

    import numpy as np  # noqa: PLC0415

    from .. import ffmpeg  # noqa: PLC0415 - avoids a top-level import cycle

    target_sr = 16000
    argv = [
        ffmpeg.ffmpeg_path(None),
        "-hide_banner",
        "-nostdin",
        "-i",
        media_path,
        "-ac",
        "1",
        "-ar",
        str(target_sr),
        "-f",
        "f32le",
        "-",
    ]
    completed = subprocess.run(argv, capture_output=True, check=False)  # noqa: S603 - argv list, no shell
    raw = completed.stdout or b""
    samples = np.frombuffer(raw, dtype=np.float32).astype(np.float64)
    return samples, target_sr


def default_models_present(
    settings: dict[str, Any],
    model_id: str,
) -> bool:  # pragma: no cover - probes the asset store at runtime
    """True when the alignment model asset is installed (no heavy import).

    Excluded from coverage: it reaches into the asset manager (a runtime
    concern). The pure runner is exercised with an injected ``models_present``.
    """
    try:
        from ..assets import manifest  # noqa: PLC0415
        from ..assets.manager import AssetManager  # noqa: PLC0415

        entry = manifest.get_asset(_asset_for_model(model_id))
        if entry is None:
            return False
        mgr = AssetManager(settings_provider=lambda: settings)
        return mgr.installed_path(entry) is not None
    except Exception:  # noqa: BLE001 - any probe failure -> treat as absent
        return False


# --------------------------------------------------------------------------- #
# the public runner
# --------------------------------------------------------------------------- #
def align_words(
    transcript: Transcript,
    audio_path: str,
    *,
    settings: dict[str, Any] | None = None,
    backend_factory: BackendFactory | None = None,
    audio_loader: AudioLoader | None = None,
    models_present: ModelsPresent | None = None,
    model_id: str | None = None,
    language: str | None = None,
    on_progress: ProgressCb | None = None,
    should_cancel: CancelProbe | None = None,
) -> Transcript:
    """Refine the word timings of ``transcript`` by force-aligning to ``audio_path``.

    Returns a NEW transcript with karaoke-grade word ``start``/``end`` (and a
    per-word ``score``); the input is never mutated. The CC-BY-NC default model is
    used unless ``model_id`` / ``settings['ctcModelId']`` selects an MIT override
    (Decision #1).

    Degrade rules (never raises for a missing modality, never drops text):
      * **Empty transcript** (no word tokens) -> the input is returned unchanged.
      * **Offline + model asset missing** -> a download would need the network;
        the input is returned unchanged.
      * **Cancelled** before alignment, or an **empty audio buffer** -> unchanged.
      * **Any backend failure** -> logged and the input returned unchanged.
    """
    settings = settings or {}
    factory = backend_factory or _default_backend_factory
    loader = audio_loader or _default_audio_loader
    present_probe = models_present or default_models_present
    resolved_model = _resolve_model_id(settings, model_id)

    def _progress(pct: float, msg: str) -> None:
        if on_progress is not None:
            on_progress(clamp(pct, 0.0, 100.0), msg)

    tokens = tokens_from_segments(transcript)
    if not tokens:
        log.info("ctc_align: transcript has no word tokens — returning unchanged")
        return {**transcript}

    # Offline gate: ONLY the network path (a missing-model download) degrades.
    if not present_probe(settings, resolved_model) and _offline.is_offline(settings):
        log.info("ctc_align: offline + model %s missing — returning unchanged", resolved_model)
        return {**transcript}

    if should_cancel is not None and should_cancel():
        return {**transcript}

    _progress(2.0, "decoding audio")
    samples, sr = loader(audio_path)

    import numpy as np  # noqa: PLC0415 - numpy is in the venv

    arr = np.asarray(samples, dtype=np.float64).reshape(-1)
    if arr.size == 0:
        log.info("ctc_align: no audio in %s — returning unchanged", audio_path)
        return {**transcript}

    duration = float(transcript.get("durationSec") or 0.0) or (arr.shape[0] / max(1, int(sr)))

    _progress(15.0, "aligning words")
    try:
        backend = factory(settings, resolved_model)
        spans = backend.align(
            arr,
            int(sr),
            tokens,
            language=language or transcript.get("language") or None,
            on_progress=lambda pct, msg: _progress(clamp(pct, 0.0, 90.0), msg),
            should_cancel=should_cancel,
        )
    except Exception as exc:  # noqa: BLE001 - an alignment failure must not crash the pipeline
        log.warning("ctc_align: alignment failed for %s: %s", audio_path, exc)
        return {**transcript}

    _progress(95.0, "merging word timings")
    word_times = emissions_to_word_timings(spans, duration=duration)
    result = merge_word_times_into_transcript(transcript, word_times)
    _progress(100.0, "done")
    return result


# --------------------------------------------------------------------------- #
# asset registration (mirrors diarize.register_diarize_assets)
# --------------------------------------------------------------------------- #
def register_ctc_align_assets() -> None:
    """Register the default (CC-BY-NC) + MIT-override models as on-demand assets.

    Idempotent (identical re-register is a no-op). The default MMS model is the
    local-tool default; the wav2vec2 entry is the commercial override (Decision
    #1). Both resolve from the standard HF cache.
    """
    from ..assets import manifest  # noqa: PLC0415 - lazy: avoids a cycle

    manifest.register_asset(
        manifest.AssetEntry(
            name=ASSET_NAME,
            kind="model",
            size_mb=1200,
            label="CTC forced aligner — MMS-300M (word timing, CC-BY-NC)",
            installer="hf",
            hf_repo=DEFAULT_MODEL_ID,
        )
    )
    manifest.register_asset(
        manifest.AssetEntry(
            name=MIT_ASSET_NAME,
            kind="model",
            size_mb=1300,
            label="CTC forced aligner — wav2vec2 (word timing, MIT commercial)",
            installer="hf",
            hf_repo=MIT_MODEL_IDS["wav2vec2-960h-lv60"],
        )
    )


# Register the assets at import (mirrors diarize / tools_resolver).
register_ctc_align_assets()


__all__ = [
    "ASSET_NAME",
    "DEFAULT_MODEL_ID",
    "MIT_ASSET_NAME",
    "MIT_MODEL_IDS",
    "AudioLoader",
    "BackendFactory",
    "CtcAlignBackend",
    "ModelsPresent",
    "WordSpan",
    "align_words",
    "default_models_present",
    "emissions_to_word_timings",
    "merge_word_times_into_transcript",
    "register_ctc_align_assets",
    "tokens_from_segments",
]
