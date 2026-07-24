"""Word-level OVERDUB (Descript-Overdub parity) + retake / best-take detection.

Two cohesive capabilities, both about *takes* — regenerating a span of speech
and choosing among repeated attempts of the same line — built on the canonical
Phase-8 seam pattern (see ``ctc_align`` / ``audio_saliency`` / ``vlm_backbone``):

  * **Word overdub** — edit a §3 :class:`Transcript` at the WORD level (replace /
    insert / delete words) and regenerate only the touched audio by diffusion
    inpainting, preserving the surrounding voice, tone, and prosody. The engine
    is **PlayDiffusion** (PlayHT, **Apache-2.0** — verified via HF/GitHub, June
    2026), the open speech-inpainting diffusion model that masks the changed
    region and denoises it conditioned on the edited text. The whole heavy half
    lives behind the :class:`OverdubBackend` seam; the PURE half — flattening
    words, applying the edit list to the token stream, computing the audio
    **mask spans** to inpaint, and re-estimating the edited transcript — is plain
    Python, fully unit-testable with hand-built transcripts and NO model.

  * **Retake / best-take detection** — pure-Python over the existing transcript
    seams: group near-duplicate consecutive segments (retakes of the same line)
    by text similarity, score each take (word confidence − filler penalty), and
    surface a keep/drop RECOMMENDATION. This is ADVISORY / observe-only (COUNCIL
    C5 shadow discipline): :func:`detect_retakes` returns a report and NEVER
    mutates the transcript, drops a take, or blocks — the editor decides.

Missing-modality / degrade contract (mirrors ``ctc_align``): the overdub runner
never raises for a missing modality. No edits -> nothing applied. Offline AND the
model asset missing, an audio-decode failure, an empty buffer, a cooperative
cancel, or ANY backend failure -> the computed PLAN is still returned (so the
caller can show the intended edit) but ``applied=False`` with a LOUD notice; the
original audio is never silently corrupted.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import TYPE_CHECKING, Any, Literal, Protocol, TypedDict

from ..util import clamp, get_logger
from . import offline as _offline

if TYPE_CHECKING:  # numpy IS in the venv; kept import-light for symmetry with peers.
    import numpy as np

log = get_logger("media_studio.features.overdub")

# §3 loose-dict shapes (same convention as ctc_align / semantic_index).
Word = dict[str, Any]
Segment = dict[str, Any]
Transcript = dict[str, Any]

#: an audio time span ``[start, end)`` in seconds on the ORIGINAL clip timeline.
Span = tuple[float, float]

#: the three word-level edit operations (Descript-Overdub parity).
EditOp = Literal["replace", "insert", "delete"]

#: LOUD notice when an overdub edit could not be rendered (vs a genuine no-op).
#: Surfaced as a ``job.progress`` message so a failed regenerate degrades LOUDLY.
OVERDUB_SKIPPED_NOTICE = "word overdub unavailable — edit not rendered (original audio kept)"

#: how much silence padding (s) to leave around each inpaint mask so the diffusion
#: seam has boundary context and the splice does not clip a neighbouring word.
DEFAULT_MASK_PAD_SEC = 0.06

#: default disfluency/filler tokens the take scorer penalizes (lowercased, punct-free).
DEFAULT_FILLERS: frozenset[str] = frozenset(
    {"um", "uh", "erm", "hmm", "like", "so", "well", "actually", "basically", "literally", "yeah"}
)

#: cooperative cancel probe + progress sink (match the rest of the codebase).
CancelProbe = Callable[[], bool]
ProgressCb = Callable[[float, str], None]


class OverdubError(RuntimeError):
    """Raised for a malformed edit list (out-of-range index / unknown op)."""


class WordEdit(TypedDict):
    """One word-level edit. ``op`` is :data:`EditOp`.

    ``index`` is a 0-based ORIGINAL word index. ``replace`` / ``delete`` target an
    existing word (``0 <= index < n``); ``insert`` places ``text`` BEFORE
    ``index`` (``0 <= index <= n``, so ``index == n`` appends). ``text`` is
    ignored for ``delete``.
    """

    op: EditOp
    index: int
    text: str


# --------------------------------------------------------------------------- #
# the heavy backend seam (PlayDiffusion) — never imported at module load
# --------------------------------------------------------------------------- #
class OverdubBackend(Protocol):
    """The slice of PlayDiffusion the pure runner needs.

    A real impl (built lazily by :func:`_default_backend_factory`, never at
    import) masks ``mask_spans`` in the clip audio and denoises them conditioned
    on ``edited_text``, returning the FULL new mono waveform. Tests inject a fake
    returning a hand-built array — no diffusion model, no torch, no network.
    """

    def inpaint(
        self,
        samples: np.ndarray,
        sr: int,
        *,
        edited_text: str,
        original_text: str,
        mask_spans: Sequence[Span],
        on_progress: ProgressCb | None = None,
        should_cancel: CancelProbe | None = None,
    ) -> np.ndarray:
        """Return the regenerated FULL-clip mono waveform (float, ``[-1, 1]``)."""
        ...  # pragma: no cover - Protocol method body is never executed


#: factory seam: default = lazy real impl; tests inject a fake.
BackendFactory = Callable[[dict[str, Any], str], OverdubBackend]
#: audio decode seam: path -> (mono samples float array, sample-rate).
AudioLoader = Callable[[str], "tuple[np.ndarray, int]"]
#: availability probe seam: is the model asset installed? (drives degrade).
ModelsPresent = Callable[[dict[str, Any], str], bool]
#: render sink: write (samples, sr) to a wav path.
SampleWriter = Callable[["np.ndarray", int, str], None]

#: the PlayDiffusion model (Apache-2.0). Real HF snapshot pin (git ls-remote, 2026-07-12).
DEFAULT_MODEL_ID = "PlayHT/PlayDiffusion"
DEFAULT_MODEL_REVISION = "9c5623830cb9c4632fd4d2f53b8e6c6ec27f4a1c"
ASSET_NAME = "playdiffusion-overdub"
OVERDUB_SIZE_MB = 2200


# --------------------------------------------------------------------------- #
# pure: transcript -> flat words
# --------------------------------------------------------------------------- #
def flatten_words(transcript: Transcript) -> list[Word]:
    """Flatten a §3 transcript into an ordered flat word list (with timings).

    Each yielded word carries ``{text, start, end, score, segmentIndex}``. A
    segment's per-word ``words`` are used when present; a word-less segment
    contributes ONE synthetic word spanning the whole segment (so a segment-only
    transcript still overdubs at segment granularity). Blank word tokens are
    dropped so the model never receives a phantom word.
    """
    out: list[Word] = []
    for seg_i, seg in enumerate(transcript.get("segments") or []):
        words = seg.get("words") or []
        if words:
            for w in words:
                text = str(w.get("text") or "").strip()
                if not text:
                    continue
                out.append(
                    {
                        "text": text,
                        "start": float(w.get("start", seg.get("start", 0.0)) or 0.0),
                        "end": float(w.get("end", seg.get("end", 0.0)) or 0.0),
                        "score": float(w.get("score", 1.0) or 0.0),
                        "segmentIndex": seg_i,
                    }
                )
        else:
            text = str(seg.get("text") or "").strip()
            if text:
                out.append(
                    {
                        "text": text,
                        "start": float(seg.get("start", 0.0) or 0.0),
                        "end": float(seg.get("end", 0.0) or 0.0),
                        "score": float(seg.get("score", 1.0) or 0.0),
                        "segmentIndex": seg_i,
                    }
                )
    return out


# --------------------------------------------------------------------------- #
# pure: normalize + apply the edit list
# --------------------------------------------------------------------------- #
def normalize_edits(edits: Sequence[dict[str, Any]], n_words: int) -> list[WordEdit]:
    """Validate + coerce a raw edit list against a word count ``n_words``.

    Each edit needs a known ``op`` and an in-range ``index`` (``replace`` /
    ``delete``: ``0..n-1``; ``insert``: ``0..n``). ``text`` is required for
    ``replace`` / ``insert`` (non-empty after strip). Raises :class:`OverdubError`
    on anything malformed — an overdub edit is a user boundary, so it fails LOUD
    rather than silently dropping the user's intent.
    """
    normalized: list[WordEdit] = []
    for raw in edits or []:
        op = str(raw.get("op") or "").strip().lower()
        if op not in ("replace", "insert", "delete"):
            raise OverdubError(f"unknown overdub op: {raw.get('op')!r}")
        raw_index: Any = raw.get("index")
        try:
            index = int(raw_index)
        except (TypeError, ValueError):
            raise OverdubError(f"overdub edit index must be an int, got {raw_index!r}") from None
        hi = n_words if op == "insert" else n_words - 1
        if index < 0 or index > max(hi, -1) or (op != "insert" and n_words == 0):
            raise OverdubError(f"overdub {op} index {index} out of range (0..{hi})")
        text = str(raw.get("text") or "").strip()
        if op in ("replace", "insert") and not text:
            raise OverdubError(f"overdub {op} at {index} requires non-empty text")
        normalized.append({"op": op, "index": index, "text": text})  # type: ignore[typeddict-item]
    return normalized


def apply_edits_to_tokens(tokens: Sequence[str], edits: Sequence[WordEdit]) -> list[str]:
    """Apply normalized ``edits`` to the token stream -> the edited token list.

    ``insert`` texts land BEFORE their index (index ``n`` appends at the end);
    ``replace`` swaps the token; ``delete`` drops it. Pure — order preserved, no
    mutation of the input.
    """
    inserts_before: dict[int, list[str]] = {}
    replaced: dict[int, str] = {}
    deleted: set[int] = set()
    for e in edits:
        if e["op"] == "insert":
            inserts_before.setdefault(e["index"], []).append(e["text"])
        elif e["op"] == "replace":
            replaced[e["index"]] = e["text"]
        else:  # delete
            deleted.add(e["index"])
    out: list[str] = []
    for i, tok in enumerate(tokens):
        out.extend(inserts_before.get(i, []))
        if i in deleted:
            continue
        out.append(replaced.get(i, tok))
    out.extend(inserts_before.get(len(tokens), []))
    return out


def compute_mask_spans(
    words: Sequence[Word],
    edits: Sequence[WordEdit],
    *,
    pad_sec: float = DEFAULT_MASK_PAD_SEC,
) -> list[Span]:
    """The ORIGINAL-audio time spans the diffusion seam must inpaint.

    ``replace`` / ``delete`` mask the target word's ``[start, end]``; ``insert``
    masks a zero-width point at the insertion boundary (the model grows audio
    there). Each mask is padded by ``pad_sec`` on both edges (never below 0), then
    overlapping / touching spans are merged so the model regenerates each changed
    region once. Returns sorted, non-overlapping, rounded spans.
    """
    pad = max(0.0, float(pad_sec))
    raw: list[Span] = []
    n = len(words)
    for e in edits:
        idx = e["index"]
        if e["op"] == "insert":
            at = float(words[idx]["start"]) if idx < n else (float(words[-1]["end"]) if n else 0.0)
            raw.append((at, at))
        else:  # replace / delete target an existing word
            w = words[idx]
            raw.append((float(w["start"]), float(w["end"])))
    padded = sorted((max(0.0, a - pad), max(0.0, b + pad)) for a, b in raw)
    merged: list[Span] = []
    for start, end in padded:
        if merged and start <= merged[-1][1] + 1e-6:
            prev = merged[-1]
            merged[-1] = (prev[0], max(prev[1], end))
        else:
            merged.append((start, end))
    return [(round(a, 3), round(b, 3)) for a, b in merged]


# --------------------------------------------------------------------------- #
# pure: the overdub plan
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class OverdubPlan:
    """The pure, model-free description of a word-overdub edit.

    ``edited_text`` is the full target transcript text after the edits;
    ``mask_spans`` are the ORIGINAL-audio regions to inpaint; ``changed_indices``
    are the original word indices the edits touched (for the UI to highlight).
    """

    original_text: str
    edited_text: str
    mask_spans: tuple[Span, ...]
    changed_indices: tuple[int, ...]

    def is_noop(self) -> bool:
        """True when the plan changes nothing (no edits -> nothing to render)."""
        return not self.mask_spans and self.original_text == self.edited_text


def build_overdub_plan(
    transcript: Transcript,
    edits: Sequence[dict[str, Any]],
    *,
    pad_sec: float = DEFAULT_MASK_PAD_SEC,
) -> OverdubPlan:
    """Compute the :class:`OverdubPlan` for ``edits`` over ``transcript`` (pure).

    Flattens the transcript to words, validates the edits, and derives the edited
    text + audio mask spans. Raises :class:`OverdubError` for a malformed edit.
    """
    words = flatten_words(transcript)
    tokens = [str(w["text"]) for w in words]
    normalized = normalize_edits(edits, len(tokens))
    edited_tokens = apply_edits_to_tokens(tokens, normalized)
    spans = compute_mask_spans(words, normalized, pad_sec=pad_sec)
    changed = tuple(sorted({e["index"] for e in normalized if e["op"] != "insert"}))
    return OverdubPlan(
        original_text=" ".join(tokens),
        edited_text=" ".join(edited_tokens),
        mask_spans=tuple(spans),
        changed_indices=changed,
    )


# --------------------------------------------------------------------------- #
# default heavy seams (lazy real impls; tests inject fakes)
# --------------------------------------------------------------------------- #
def _default_backend_factory(
    settings: dict[str, Any],
    model_id: str,
) -> OverdubBackend:  # pragma: no cover - prod seam (imports the heavy diffusion stack)
    """Build the real PlayDiffusion backend (LAZY import; runtime only)."""
    from .overdub_backend import RealOverdubBackend  # noqa: PLC0415 - heavy seam

    return RealOverdubBackend(settings, model_id)


def _default_audio_loader(media_path: str) -> tuple[np.ndarray, int]:  # pragma: no cover - needs ffmpeg + a real file
    """Decode ``media_path`` to mono float samples at 24 kHz via ffmpeg.

    Reuses ``ctc_align``'s decode helper (ffmpeg -> f32le -> numpy, no heavy-ML
    dep). Excluded from coverage: it spawns ffmpeg and reads a real media file.
    """
    import subprocess  # noqa: PLC0415, S404 - argv-list only, never shell=True

    from .. import ffmpeg  # noqa: PLC0415 - avoids a top-level import cycle
    from .ctc_align import _decode_pcm_or_raise  # noqa: PLC0415 - reuse the tested decoder

    target_sr = 24000
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
    return _decode_pcm_or_raise(completed.returncode, completed.stdout, completed.stderr, target_sr=target_sr)


def default_models_present(
    settings: dict[str, Any],
    model_id: str,
) -> bool:  # pragma: no cover - probes the asset store at runtime
    """True when the PlayDiffusion model asset is installed (no heavy import)."""
    try:
        from ..assets import manifest  # noqa: PLC0415
        from ..assets.manager import AssetManager  # noqa: PLC0415

        entry = manifest.get_asset(ASSET_NAME)
        if entry is None:
            return False
        mgr = AssetManager(settings_provider=lambda: settings)
        return mgr.installed_path(entry) is not None
    except Exception:  # noqa: BLE001 - any probe failure -> treat as absent
        return False


def _default_sample_writer(samples: np.ndarray, sr: int, path: str) -> None:
    """Write mono float samples to a 16-bit PCM WAV (stdlib ``wave``; no dep)."""
    import wave  # noqa: PLC0415 - stdlib

    import numpy as np  # noqa: PLC0415 - numpy is in the venv

    arr = np.clip(np.asarray(samples, dtype=np.float64).reshape(-1), -1.0, 1.0)
    pcm = (arr * 32767.0).astype(np.int16)
    with wave.open(path, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(int(sr))
        wav.writeframes(pcm.tobytes())


# --------------------------------------------------------------------------- #
# the public overdub runner
# --------------------------------------------------------------------------- #
class OverdubResult(TypedDict):
    """The overdub result surfaced to the job layer (JSON-able)."""

    applied: bool
    path: str | None
    editedText: str
    originalText: str
    maskSpans: list[list[float]]
    changedIndices: list[int]
    notice: str | None


def _result(plan: OverdubPlan, *, applied: bool, path: str | None, notice: str | None) -> OverdubResult:
    return {
        "applied": applied,
        "path": path,
        "editedText": plan.edited_text,
        "originalText": plan.original_text,
        "maskSpans": [[a, b] for a, b in plan.mask_spans],
        "changedIndices": list(plan.changed_indices),
        "notice": notice,
    }


def overdub(
    transcript: Transcript,
    audio_path: str,
    edits: Sequence[dict[str, Any]],
    out_wav_path: str,
    *,
    settings: dict[str, Any] | None = None,
    backend_factory: BackendFactory | None = None,
    audio_loader: AudioLoader | None = None,
    models_present: ModelsPresent | None = None,
    sample_writer: SampleWriter | None = None,
    model_id: str | None = None,
    pad_sec: float = DEFAULT_MASK_PAD_SEC,
    on_progress: ProgressCb | None = None,
    should_cancel: CancelProbe | None = None,
) -> OverdubResult:
    """Regenerate the edited words of ``transcript`` in ``audio_path`` -> a new WAV.

    Returns an :class:`OverdubResult`. The PLAN (edited text + mask spans) is
    ALWAYS computed and returned even when rendering is skipped, so the UI can
    preview the intended edit. Degrade rules (never raise for a missing modality):
      * **No effective edit** (empty edit list / a no-op plan) -> ``applied=False``,
        ``path=None``, no notice (nothing to do).
      * **Offline + model asset missing** -> ``applied=False`` + LOUD notice.
      * **Audio-decode failure / empty buffer / cancel / any backend failure** ->
        ``applied=False`` + LOUD notice; the original audio is never touched.
    A malformed edit list raises :class:`OverdubError` (a user boundary).
    """
    settings = settings or {}
    factory = backend_factory or _default_backend_factory
    loader = audio_loader or _default_audio_loader
    present_probe = models_present or default_models_present
    writer = sample_writer or _default_sample_writer
    resolved_model = model_id or str(settings.get("overdubModelId") or "") or DEFAULT_MODEL_ID

    def _progress(pct: float, msg: str) -> None:
        if on_progress is not None:
            on_progress(clamp(pct, 0.0, 100.0), msg)

    plan = build_overdub_plan(transcript, edits, pad_sec=pad_sec)
    if plan.is_noop():
        log.info("overdub: no effective edit — nothing to render")
        return _result(plan, applied=False, path=None, notice=None)

    if not present_probe(settings, resolved_model) and _offline.is_offline(settings):
        log.info("overdub: offline + model %s missing — plan only", resolved_model)
        return _result(plan, applied=False, path=None, notice=OVERDUB_SKIPPED_NOTICE)

    if should_cancel is not None and should_cancel():
        return _result(plan, applied=False, path=None, notice=OVERDUB_SKIPPED_NOTICE)

    _progress(5.0, "decoding audio")
    try:
        samples, sr = loader(audio_path)
    except Exception as exc:  # noqa: BLE001 - a decode failure must not crash the pipeline
        log.warning("overdub: audio decode failed for %s: %s", audio_path, exc)
        _progress(100.0, OVERDUB_SKIPPED_NOTICE)
        return _result(plan, applied=False, path=None, notice=OVERDUB_SKIPPED_NOTICE)

    import numpy as np  # noqa: PLC0415 - numpy is in the venv

    arr = np.asarray(samples, dtype=np.float64).reshape(-1)
    if arr.size == 0:
        log.info("overdub: no audio in %s — plan only", audio_path)
        return _result(plan, applied=False, path=None, notice=OVERDUB_SKIPPED_NOTICE)

    _progress(20.0, "inpainting edited words (PlayDiffusion)")
    try:
        backend = factory(settings, resolved_model)
        new_samples = backend.inpaint(
            arr,
            int(sr),
            edited_text=plan.edited_text,
            original_text=plan.original_text,
            mask_spans=list(plan.mask_spans),
            on_progress=lambda pct, msg: _progress(clamp(pct, 20.0, 90.0), msg),
            should_cancel=should_cancel,
        )
    except Exception as exc:  # noqa: BLE001 - an inpaint failure must not crash the pipeline
        log.warning("overdub: inpaint failed for %s: %s", audio_path, exc)
        _progress(100.0, OVERDUB_SKIPPED_NOTICE)
        return _result(plan, applied=False, path=None, notice=OVERDUB_SKIPPED_NOTICE)

    out_arr = np.asarray(new_samples, dtype=np.float64).reshape(-1)
    if out_arr.size == 0:
        log.warning("overdub: backend returned empty audio for %s", audio_path)
        _progress(100.0, OVERDUB_SKIPPED_NOTICE)
        return _result(plan, applied=False, path=None, notice=OVERDUB_SKIPPED_NOTICE)

    _progress(95.0, "writing wav")
    writer(out_arr, int(sr), out_wav_path)
    _progress(100.0, "done")
    return _result(plan, applied=True, path=out_wav_path, notice=None)


# --------------------------------------------------------------------------- #
# retake / best-take detection (pure-Python, ADVISORY / observe-only)
# --------------------------------------------------------------------------- #
def normalize_take_text(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace (for take comparison)."""
    cleaned = "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in str(text).lower())
    return " ".join(cleaned.split())


def take_similarity(a: str, b: str) -> float:
    """0..1 text similarity of two takes (difflib ratio over normalized text).

    Two empty strings are identical (1.0); one empty vs non-empty is 0.0.
    Deterministic (``difflib.SequenceMatcher``) — no model, no randomness.
    """
    na, nb = normalize_take_text(a), normalize_take_text(b)
    if not na and not nb:
        return 1.0
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


def _segment_text(seg: Segment) -> str:
    words = seg.get("words") or []
    if words:
        return " ".join(str(w.get("text") or "").strip() for w in words if str(w.get("text") or "").strip())
    return str(seg.get("text") or "").strip()


def group_takes(segments: Sequence[Segment], *, threshold: float = 0.8) -> list[list[int]]:
    """Group CONSECUTIVE segments that are retakes of the same line.

    Two consecutive segments join the same group when their normalized text
    similarity is ``>= threshold``. A run of length 1 (a unique line) is its own
    singleton group. Returns groups of ORIGINAL segment indices, in order. Only
    consecutive segments are grouped — a repeated phrase far later in the video is
    a deliberate callback, not a retake.
    """
    thr = clamp(float(threshold), 0.0, 1.0)
    groups: list[list[int]] = []
    current: list[int] = []
    prev_text: str | None = None
    for i, seg in enumerate(segments or []):
        text = _segment_text(seg)
        if prev_text is not None and take_similarity(prev_text, text) >= thr:
            current.append(i)
        else:
            if current:
                groups.append(current)
            current = [i]
        prev_text = text
    if current:
        groups.append(current)
    return groups


def score_take(seg: Segment, *, fillers: frozenset[str] = DEFAULT_FILLERS) -> float:
    """Score one take 0..1 — higher is a better keeper.

    Combines mean per-word confidence (the transcript's ``score``) with a filler
    penalty (fraction of tokens that are disfluencies). A take with no words
    scores 0.0. Pure over the transcript dict — no audio, no model.
    """
    words = seg.get("words") or []
    tokens = [str(w.get("text") or "").strip().lower() for w in words if str(w.get("text") or "").strip()]
    if not tokens:
        # word-less segment: fall back to whitespace tokens of the text.
        tokens = [t.lower() for t in _segment_text(seg).split()]
    if not tokens:
        return 0.0
    scores = [float(w.get("score", 1.0) or 0.0) for w in words if str(w.get("text") or "").strip()]
    confidence = sum(scores) / len(scores) if scores else 1.0
    stripped = ["".join(ch for ch in t if ch.isalnum()) for t in tokens]
    filler_count = sum(1 for t in stripped if t in fillers)
    filler_ratio = filler_count / len(tokens)
    return clamp(0.85 * clamp(confidence, 0.0, 1.0) + 0.15 * (1.0 - filler_ratio), 0.0, 1.0)


def best_take_index(group: Sequence[int], segments: Sequence[Segment], *, fillers: frozenset[str] = DEFAULT_FILLERS) -> int:
    """The index (into ``segments``) of the best take in ``group``.

    Ranks by :func:`score_take` (desc); ties break toward the LATER take (the
    latest retake is usually the intended keeper). Returns the group's sole member
    for a singleton.
    """
    best = group[0]
    best_score = score_take(segments[best], fillers=fillers)
    for idx in group[1:]:
        s = score_take(segments[idx], fillers=fillers)
        if s >= best_score:  # >= so a tie prefers the later take
            best, best_score = idx, s
    return best


@dataclass(frozen=True)
class TakeGroup:
    """One retake group: its member indices + the recommended keep/drop split."""

    indices: tuple[int, ...]
    best_index: int
    drop_indices: tuple[int, ...]
    best_score: float


@dataclass(frozen=True)
class RetakeReport:
    """ADVISORY retake analysis (never mutates the transcript or blocks).

    ``groups`` holds every run (including singletons). ``keep_indices`` /
    ``drop_indices`` are the flattened recommendation across all multi-take
    groups; a singleton is always kept. The editor decides — this is observe-only.
    """

    groups: tuple[TakeGroup, ...]
    keep_indices: tuple[int, ...]
    drop_indices: tuple[int, ...]
    advisory: bool = field(default=True)


def detect_retakes(
    transcript: Transcript,
    *,
    threshold: float = 0.8,
    fillers: frozenset[str] = DEFAULT_FILLERS,
) -> RetakeReport:
    """Detect retakes and RECOMMEND a best-take keep/drop split (advisory).

    Groups consecutive near-duplicate segments (:func:`group_takes`), picks the
    best take per group (:func:`best_take_index`), and reports the drops. NEVER
    mutates ``transcript`` and NEVER drops anything itself — COUNCIL C5 shadow
    discipline: it returns a report the editor may act on, and nothing more.
    """
    segments = list(transcript.get("segments") or [])
    groups_raw = group_takes(segments, threshold=threshold)
    groups: list[TakeGroup] = []
    keep: list[int] = []
    drop: list[int] = []
    for grp in groups_raw:
        best = best_take_index(grp, segments, fillers=fillers)
        drops = tuple(i for i in grp if i != best)
        groups.append(
            TakeGroup(
                indices=tuple(grp),
                best_index=best,
                drop_indices=drops,
                best_score=round(score_take(segments[best], fillers=fillers), 4),
            )
        )
        keep.append(best)
        drop.extend(drops)
    return RetakeReport(
        groups=tuple(groups),
        keep_indices=tuple(sorted(keep)),
        drop_indices=tuple(sorted(drop)),
    )


# --------------------------------------------------------------------------- #
# asset registration (mirrors ctc_align.register_ctc_align_assets)
# --------------------------------------------------------------------------- #
def register_overdub_assets() -> None:
    """Register PlayDiffusion as an on-demand model asset (idempotent).

    Apache-2.0 (commercial OK) — the open speech-inpainting diffusion engine. The
    HF snapshot revision is a real pinned commit (F3c: no floating ``main``).
    Identical re-registration is a no-op (re-import safe).
    """
    from ..assets import manifest  # noqa: PLC0415 - lazy: avoids an import cycle

    manifest.register_asset(
        manifest.AssetEntry(
            name=ASSET_NAME,
            kind="model",
            size_mb=OVERDUB_SIZE_MB,
            label="PlayDiffusion (word-level overdub / speech inpainting, Apache-2.0)",
            tier="optional",
            why="Regenerates edited words in-place while preserving the original voice (Descript-Overdub parity).",
            installer="hf",
            hf_repo=DEFAULT_MODEL_ID,
            hf_revision=DEFAULT_MODEL_REVISION,
        )
    )


# Register the asset at import (mirrors ctc_align / vlm_backbone).
register_overdub_assets()


__all__ = [
    "ASSET_NAME",
    "DEFAULT_FILLERS",
    "DEFAULT_MASK_PAD_SEC",
    "DEFAULT_MODEL_ID",
    "OVERDUB_SIZE_MB",
    "OVERDUB_SKIPPED_NOTICE",
    "AudioLoader",
    "BackendFactory",
    "ModelsPresent",
    "OverdubBackend",
    "OverdubError",
    "OverdubPlan",
    "OverdubResult",
    "RetakeReport",
    "SampleWriter",
    "TakeGroup",
    "WordEdit",
    "apply_edits_to_tokens",
    "best_take_index",
    "build_overdub_plan",
    "compute_mask_spans",
    "default_models_present",
    "detect_retakes",
    "flatten_words",
    "group_takes",
    "normalize_edits",
    "normalize_take_text",
    "overdub",
    "register_overdub_assets",
    "score_take",
    "take_similarity",
]
