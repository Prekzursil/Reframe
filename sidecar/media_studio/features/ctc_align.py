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

Decision #1 (license), as REVISED by v1.5 WU-T0/B1: the *upstream package* default
``MahmoudAshraf/mms-300m-1130-forced-aligner`` is **CC-BY-NC-4.0**, so it is NO
LONGER Reframe's packaged default — ``docs/plans/v1.5/flagship-transcript-editing.md:94``
("must NOT be the packaged default") and ``:150`` ("gate MMS behind
``allowNonCommercialAligner``"). Reframe now defaults to
``facebook/wav2vec2-large-960h-lv60-self`` (**Apache-2.0**, English) and reaches the
MMS model ONLY when ``settings['allowNonCommercialAligner']`` is truthy — an explicit
opt-in that also has to be set before an explicit ``ctcModelId``/``model_id`` naming
MMS is honoured. Everything flows through one :func:`_resolve_model_id`, so a single
switch picks the model everywhere and the gate cannot be routed around.

LICENCE FACTS VERIFIED 2026-08-09 by an HF Hub metadata probe (a probe mechanically
independent of this file's own comments, which is how the pre-existing "MIT"
mislabel — plan B3 — was caught): MMS = ``cc-by-nc-4.0``; all three of
:data:`PERMISSIVE_MODEL_IDS` and ``gigant/romanian-wav2vec2`` = ``apache-2.0``,
NOT MIT. The user-facing attribution lives in
``app/renderer/src/features/ThirdPartyNotices.tsx`` (``ALIGNER_MODEL_NOTICES``) and
``docs/THIRD-PARTY-LICENSES.md``.

NOT done here (disclosed, not silently skipped): the per-language permissive-CTC
map (XLSR-53 family) and the typed ``spec.py`` Settings keys that the same plan
section asks for. Non-English alignment therefore degrades to the ASR's own word
timings unless the user picks RO or opts into MMS.

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

#: F3b user-facing notice when word-level alignment is SKIPPED due to a backend
#: or audio-decode failure (vs a genuinely empty transcript, which is silent).
#: Surfaced as a ``job.progress`` message so karaoke timing degrades LOUDLY.
ALIGN_SKIPPED_NOTICE = "word-level alignment unavailable — using segment timings"

#: how many trailing chars of ffmpeg stderr to fold into an :class:`AudioDecodeError`.
_FFMPEG_STDERR_TAIL = 500


class AudioDecodeError(RuntimeError):
    """F3b: raised when ffmpeg fails to decode the audio (non-zero exit code).

    Previously the default loader ignored ffmpeg's returncode and handed back an
    empty/garbage buffer — a silent failure. Now a non-zero exit raises this with
    the stderr tail so the caller can degrade with a LOUD notice.
    """


def _decode_pcm_or_raise(
    returncode: int,
    raw: bytes | None,
    stderr: bytes | None,
    *,
    target_sr: int,
) -> tuple[np.ndarray, int]:
    """Turn an ffmpeg result into ``(samples, sr)`` — or raise on a bad exit.

    The PURE, fully-tested core of :func:`_default_audio_loader`: on a non-zero
    ``returncode`` it raises :class:`AudioDecodeError` with the stderr tail (F3b);
    otherwise it reads the f32le PCM bytes into a float64 array.
    """
    import numpy as _np  # noqa: PLC0415 - numpy is in the venv; kept lazy for symmetry

    if returncode != 0:
        tail = (stderr or b"").decode("utf-8", errors="replace").strip()[-_FFMPEG_STDERR_TAIL:]
        raise AudioDecodeError(f"ffmpeg audio decode failed (exit {returncode}): {tail}")
    samples = _np.frombuffer(raw or b"", dtype=_np.float32).astype(_np.float64)
    return samples, target_sr


# --------------------------------------------------------------------------- #
# model ids + assets (Decision #1 as revised by WU-T0/B1: permissive default,
# CC-BY-NC MMS behind an explicit opt-in)
# --------------------------------------------------------------------------- #
#: The 158-language MMS forced aligner — **CC-BY-NC-4.0**, so NON-COMMERCIAL only
#: (HF Hub tag ``license:cc-by-nc-4.0``, probed 2026-08-09). It is the upstream
#: ``ctc-forced-aligner`` package default but NOT Reframe's: it is reachable only
#: via ``settings['allowNonCommercialAligner']``. Attribution: © Mahmoud Ashraf
#: (MahmoudAshraf/mms-300m-1130-forced-aligner), built on Meta AI's MMS-300M.
NON_COMMERCIAL_MODEL_ID = "MahmoudAshraf/mms-300m-1130-forced-aligner"
#: The settings key that gates :data:`NON_COMMERCIAL_MODEL_IDS`. Absent/falsy =
#: commercial-safe; a user must turn it on knowing what it means.
ALLOW_NON_COMMERCIAL_SETTING = "allowNonCommercialAligner"
#: Every model id this module refuses to use without that opt-in. A frozenset so
#: adding a second NC model is a one-line change that the gate picks up for free.
NON_COMMERCIAL_MODEL_IDS: frozenset[str] = frozenset({NON_COMMERCIAL_MODEL_ID})

# F3c: pin the HF snapshot revisions to commit hashes (verified 2026-06-28).
NON_COMMERCIAL_MODEL_REVISION = "49402e9577b1158620820667c218cd494cc44486"
WAV2VEC2_REVISION = "54074b1c16f4de6a5ad59affb4caa8f2ea03a119"

#: Commercial-safe **Apache-2.0** wav2vec2/HuBERT alternatives, keyed by the short
#: alias the UI/settings surface. Named ``MIT_MODEL_IDS`` until 2026-08-09: an HF
#: Hub probe showed all three carry ``license:apache-2.0``, never MIT (plan B3).
PERMISSIVE_MODEL_IDS: dict[str, str] = {
    "wav2vec2-960h-lv60": "facebook/wav2vec2-large-960h-lv60-self",
    "wav2vec2-960h": "facebook/wav2vec2-large-960h",
    "hubert-large": "facebook/hubert-large-ls960-ft",
}

#: Reframe's PACKAGED default aligner (WU-T0/B1 flip): Apache-2.0, English.
#: Non-English clips degrade to the ASR's own word timings unless the user picks
#: the RO model or opts into MMS — the per-language permissive map is NOT built.
DEFAULT_MODEL_ID = PERMISSIVE_MODEL_IDS["wav2vec2-960h-lv60"]

#: M5 — Romanian-language alignment opt-in. A wav2vec2 CTC model fine-tuned on
#: Romanian (Apache-2.0, HF-probed 2026-08-09); selected via ``settings['ctcModelId']``
#: (this alias or its full HF id). Keyed by the alias the UI surfaces.
RO_MODEL_IDS: dict[str, str] = {
    "romanian-wav2vec2": "gigant/romanian-wav2vec2",
}
# F3c: pin the HF snapshot revision to a commit hash (git ls-remote, 2026-06-29).
RO_MODEL_REVISION = "79cf603aac59501d02bfeb37f615efc3ac4ce1b3"

#: every short alias -> full HF id (permissive swaps + RO opt-in + the gated MMS).
#: ``mms-300m`` is listed so the UI can name the NC model explicitly rather than
#: reaching it by an unlabelled fallback — the gate still governs whether it wins.
_MODEL_ALIASES: dict[str, str] = {
    **PERMISSIVE_MODEL_IDS,
    **RO_MODEL_IDS,
    "mms-300m": NON_COMMERCIAL_MODEL_ID,
}

#: the on-demand asset name for the gated CC-BY-NC MMS model (Wave-2 manifest).
ASSET_NAME = "ctc-forced-aligner-mms"
#: the on-demand asset name for the Apache-2.0 wav2vec2 packaged default.
WAV2VEC2_ASSET_NAME = "ctc-forced-aligner-wav2vec2"
#: the on-demand asset name for the Romanian (M5) alignment opt-in.
RO_ASSET_NAME = "ctc-forced-aligner-romanian"

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
    """Pick the alignment model id: explicit arg > settings > packaged default.

    ``model_id`` (the call arg) wins so a caller can force a model per-job. Next
    is ``settings['ctcModelId']`` — which may be a full HF id OR one of the
    :data:`PERMISSIVE_MODEL_IDS` / :data:`RO_MODEL_IDS` aliases (resolved to its
    id), or ``mms-300m``. Absent both, the packaged Apache-2.0
    :data:`DEFAULT_MODEL_ID` is used.

    **The licence gate is applied LAST, to the resolved id**, so no request shape
    can route around it: a :data:`NON_COMMERCIAL_MODEL_IDS` member is downgraded
    to :data:`DEFAULT_MODEL_ID` unless ``settings['allowNonCommercialAligner']``
    is truthy. Placing it after resolution (rather than only on the fallback) is
    what makes the alias, the full-id and the per-job-arg paths all covered by one
    check — the flaw in gating only the default would be an explicit
    ``ctcModelId`` silently re-enabling a CC-BY-NC model in a commercial build.
    """
    allow_non_commercial = bool(settings.get(ALLOW_NON_COMMERCIAL_SETTING))
    configured = settings.get("ctcModelId")
    requested = model_id or (configured if isinstance(configured, str) and configured else None)
    if requested:
        resolved = _MODEL_ALIASES.get(requested, requested)
    elif allow_non_commercial:
        # Explicitly opted in and nothing selected: the 158-language MMS model is
        # the best default available, and it is what pre-T0 builds used.
        resolved = NON_COMMERCIAL_MODEL_ID
    else:
        resolved = DEFAULT_MODEL_ID
    if resolved in NON_COMMERCIAL_MODEL_IDS and not allow_non_commercial:
        log.warning(
            "ctc_align: %s is non-commercial (CC-BY-NC-4.0) and %s is off — using %s instead",
            resolved,
            ALLOW_NON_COMMERCIAL_SETTING,
            DEFAULT_MODEL_ID,
        )
        return DEFAULT_MODEL_ID
    return resolved


def _asset_for_model(model_id: str) -> str:
    """The asset name guarding a model id (gated MMS / RO opt-in / wav2vec2)."""
    if model_id == NON_COMMERCIAL_MODEL_ID:
        return ASSET_NAME
    if model_id == RO_MODEL_IDS["romanian-wav2vec2"]:
        return RO_ASSET_NAME
    return WAV2VEC2_ASSET_NAME


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
    # F3b: honour the returncode — a non-zero exit raises (with the stderr tail)
    # instead of silently returning an empty/garbage buffer.
    return _decode_pcm_or_raise(completed.returncode, completed.stdout, completed.stderr, target_sr=target_sr)


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
    per-word ``score``); the input is never mutated. The Apache-2.0
    :data:`DEFAULT_MODEL_ID` is used unless ``model_id`` /
    ``settings['ctcModelId']`` selects another; the CC-BY-NC MMS model is reached
    only with ``settings['allowNonCommercialAligner']`` (WU-T0/B1).

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
    try:
        samples, sr = loader(audio_path)
    except Exception as exc:  # noqa: BLE001 - an audio-decode failure must not crash the pipeline
        log.warning("ctc_align: audio decode failed for %s: %s", audio_path, exc)
        _progress(100.0, ALIGN_SKIPPED_NOTICE)
        return {**transcript}

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
        _progress(100.0, ALIGN_SKIPPED_NOTICE)
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
    """Register the packaged Apache-2.0 default + the gated MMS model as assets.

    Idempotent (identical re-register is a no-op). The wav2vec2 entry is the
    PACKAGED default (Apache-2.0); the MMS entry stays registered because a user
    who sets ``allowNonCommercialAligner`` must still be able to install it.
    Both resolve from the standard HF cache.
    """
    from ..assets import manifest  # noqa: PLC0415 - lazy: avoids a cycle

    manifest.register_asset(
        manifest.AssetEntry(
            name=ASSET_NAME,
            kind="model",
            size_mb=1200,
            label="CTC forced aligner — MMS-300M (word timing, CC-BY-NC-4.0, opt-in)",
            installer="hf",
            hf_repo=NON_COMMERCIAL_MODEL_ID,
            hf_revision=NON_COMMERCIAL_MODEL_REVISION,
        )
    )
    manifest.register_asset(
        manifest.AssetEntry(
            name=WAV2VEC2_ASSET_NAME,
            kind="model",
            size_mb=1300,
            label="CTC forced aligner — wav2vec2 (word timing, Apache-2.0, default)",
            installer="hf",
            hf_repo=DEFAULT_MODEL_ID,
            hf_revision=WAV2VEC2_REVISION,
        )
    )
    manifest.register_asset(
        manifest.AssetEntry(
            name=RO_ASSET_NAME,
            kind="model",
            size_mb=1300,
            label="CTC forced aligner — Romanian wav2vec2 (word timing, RO opt-in)",
            installer="hf",
            hf_repo=RO_MODEL_IDS["romanian-wav2vec2"],
            hf_revision=RO_MODEL_REVISION,
        )
    )


# Register the assets at import (mirrors diarize / tools_resolver).
register_ctc_align_assets()


__all__ = [
    "ALLOW_NON_COMMERCIAL_SETTING",
    "ASSET_NAME",
    "DEFAULT_MODEL_ID",
    "NON_COMMERCIAL_MODEL_ID",
    "NON_COMMERCIAL_MODEL_IDS",
    "PERMISSIVE_MODEL_IDS",
    "RO_ASSET_NAME",
    "RO_MODEL_IDS",
    "WAV2VEC2_ASSET_NAME",
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
