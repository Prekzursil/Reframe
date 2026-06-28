"""Shared SigLIP-2 vision-language BACKBONE (Phase 8 WU4 — Tier-1).

ONE backbone load, THREE scorers. The pinned model is **SigLIP-2 SoViT-400M**
(``google/siglip2-so400m-patch16-384``, Apache-2.0 — commercial OK, ~2.3 GB
fp16; PHASE8-SOTA-MANIFEST.md component #2). It is loaded ONCE behind an
injectable :class:`BackboneBackend` seam and its image embeddings are reused by
all three pure-numpy scorers:

  * :func:`aesthetic_score`          — a tiny MLP head over the image embeds
    (reimplemented on the SigLIP-2 backbone, sidestepping the AGPL wrapper of
    Aesthetic-Predictor-V2.5 per manifest #3 — the head is ~KB of math);
  * :func:`zero_shot_interestingness` — cosine of each frame embed against an
    "interesting" / "boring" text-prompt pair, softmaxed to 0..1;
  * :func:`novelty_scores`           — ``1 - max cosine to prior frames``,
    pure numpy, also the embedding vector :mod:`diversity` consumes.

The WU4 acceptance: **one** ``embed_images`` call serves all three sub-scores
(no second SigLIP load). :func:`compute_backbone_signals` performs that single
embed and emits a ``dict[str, SignalTrack]`` keyed ``aesthetic`` / ``zeroShot``
/ ``novelty`` on the shared Wave-1 :class:`Signal` contract.

Heavy-ML discipline (the proven seam pattern — see ``diarize`` /
``reframe_claudeshorts`` / ``stabilize``):

  * the PURE half (normalization, cosine, softmax, the MLP head, windowing,
    track assembly) is plain numpy and is unit-tested with hand-built arrays;
  * the HEAVY half lives behind the :class:`BackboneBackend` Protocol, built
    lazily by :func:`_default_backbone_factory` (the real ``transformers`` /
    ``torch`` import lives in the sibling ``vlm_backbone_backend.py``, which is
    excluded from coverage). Tests inject a FAKE backend returning canned
    embeddings — no model, no weights, no network;
  * ``frame_loader`` mirrors ``reframe_claudeshorts``'s ``Detector`` seam
    (``cv2`` imported only inside the default loader);
  * the gated/offline path reuses :func:`features.offline.guard_network` + a
    ``models_present`` seam: offline AND model-missing -> ``present=False``
    tracks (graceful degrade), never a hang, never fabricated zeros.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

from ..util import clamp, get_logger
from . import offline as _offline

if TYPE_CHECKING:
    import numpy as np

log = get_logger("media_studio.features.vlm_backbone")

# --------------------------------------------------------------------------- #
# pinned model (PHASE8-SOTA-MANIFEST.md component #2 — SigLIP-2 SoViT-400M)
# --------------------------------------------------------------------------- #
#: HF model id of the shared backbone (patch16, NOT patch14 — patch14 404s).
SIGLIP2_MODEL_ID = "google/siglip2-so400m-patch16-384"
#: F3c: pin the HF snapshot revision to a commit hash (verified 2026-06-28).
SIGLIP2_REVISION = "dd658faac399427308559e2c3ac1e99cbe43845d"
#: the on-demand asset name (Wave-2 registers the manifest entry).
BACKBONE_ASSET_NAME = "siglip2-so400m"
#: resident VRAM at fp16 inference (manifest VRAM table) — diagnostics only.
BACKBONE_VRAM_MB = 2300

#: the channels this module emits (frozen vocabulary; Wave-2 scorer keys here).
CHANNEL_AESTHETIC = "aesthetic"
CHANNEL_ZERO_SHOT = "zeroShot"
CHANNEL_NOVELTY = "novelty"
BACKBONE_CHANNELS: tuple[str, ...] = (CHANNEL_AESTHETIC, CHANNEL_ZERO_SHOT, CHANNEL_NOVELTY)

#: default zero-shot prompt pair (interesting vs boring). ``prompts=`` overrides.
DEFAULT_PROMPTS: tuple[str, str] = (
    "an interesting, exciting, dynamic moment",
    "a boring, dull, static moment",
)

#: shared windowing grid (mirror reframe_claudeshorts) — one sample per second.
DEFAULT_WIN_SEC = 1.0
DEFAULT_HOP_SEC = 1.0

#: cooperative cancel probe + progress sink (match the rest of the codebase).
CancelProbe = Callable[[], bool]
ProgressCb = Callable[[float, str], None]


# --------------------------------------------------------------------------- #
# the shared Wave-1 Signal contract (frozen; Wave-2 unified scorer consumes it)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Signal:
    """One scored observation on the shared timeline (seconds, ORIGINAL video).

    ``value`` is ALWAYS normalized to 0.0..1.0 (1.0 = maximally interesting on
    this channel); raw model outputs are squashed inside the module BEFORE
    emission so the scorer never sees an un-normalized number.
    """

    channel: str
    start: float
    end: float
    value: float
    confidence: float = 1.0
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SignalTrack:
    """All :class:`Signal`\\ s from ONE channel + a modality-presence flag.

    ``present=False`` is the degrade signal: the Wave-2 scorer drops this
    channel's weight and re-normalizes the survivors (so a clip the backbone
    could not score is judged on the remaining channels, never on fake zeros).
    """

    channel: str
    signals: tuple[Signal, ...]
    present: bool
    fps_hint: float | None = None


# --------------------------------------------------------------------------- #
# shared windowing grid (mirrors reframe_claudeshorts.window_timestamps)
# --------------------------------------------------------------------------- #
def sample_windows(
    duration: float,
    win_sec: float = DEFAULT_WIN_SEC,
    hop_sec: float = DEFAULT_HOP_SEC,
) -> tuple[tuple[float, float], ...]:
    """Shared ``[start, end)`` window grid so every module aligns by index.

    Walks ``[0, duration)`` in ``hop_sec`` strides emitting ``win_sec``-wide
    windows (the last window is clamped to ``duration``). A non-positive
    duration yields a single ``(0.0, 0.0)`` instantaneous window so a degenerate
    clip still produces one aligned slot. ``hop_sec`` is floored at a tiny
    positive value so a zero hop can never spin.
    """
    d = max(0.0, float(duration))
    if d <= 0.0:
        return ((0.0, 0.0),)
    win = max(1e-6, float(win_sec))
    hop = max(1e-6, float(hop_sec))
    windows: list[tuple[float, float]] = []
    start = 0.0
    while start < d:
        end = min(start + win, d)
        windows.append((round(start, 3), round(end, 3)))
        start += hop
    return tuple(windows)


# --------------------------------------------------------------------------- #
# pure numpy helpers (no heavy imports — fully covered with hand-built arrays)
# --------------------------------------------------------------------------- #
def _l2_normalize(matrix: np.ndarray) -> np.ndarray:
    """Row-wise L2-normalize a 2-D array (zero rows stay zero)."""
    import numpy as np  # noqa: PLC0415 - numpy is in the venv; lazy keeps surface light

    arr = np.asarray(matrix, dtype=np.float64)
    if arr.ndim != 2:
        # a single vector (or scalar) -> one row of shape (1, D)
        arr = arr.reshape(1, -1)
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    safe = np.where(norms == 0.0, 1.0, norms)
    return arr / safe


def _sigmoid(values: np.ndarray) -> np.ndarray:
    """Numerically-stable logistic squash to (0, 1)."""
    import numpy as np  # noqa: PLC0415 - numpy is in the venv

    arr = np.asarray(values, dtype=np.float64)
    return np.where(
        arr >= 0,
        1.0 / (1.0 + np.exp(-np.clip(arr, -60.0, 60.0))),
        np.exp(np.clip(arr, -60.0, 60.0)) / (1.0 + np.exp(np.clip(arr, -60.0, 60.0))),
    )


def aesthetic_score(image_embeds: np.ndarray, head_weights: np.ndarray | None = None) -> list[float]:
    """Per-frame aesthetic score (0..1) from a tiny MLP head over SigLIP-2 embeds.

    Reimplements Aesthetic-Predictor-V2.5's head as a single linear layer
    (``w`` of shape ``(D,)`` or ``(D, 1)``, optional trailing bias row) applied
    to L2-normalized image embeddings, then sigmoid-squashed to 0..1. This is
    the AGPL-free path (manifest #3: the licence is in the wrapper, not the
    math). When ``head_weights`` is ``None`` (the backend exposes no head), the
    score falls back to the L2 norm of each raw embed, min-max scaled — a
    monotone "richer embedding = more aesthetic" proxy that is still 0..1.
    """
    import numpy as np  # noqa: PLC0415 - numpy is in the venv

    embeds = np.asarray(image_embeds, dtype=np.float64)
    if embeds.ndim != 2 or embeds.shape[0] == 0:
        return []
    if head_weights is None:
        raw = np.linalg.norm(embeds, axis=1)
        lo, hi = float(raw.min()), float(raw.max())
        if hi <= lo:
            return [clamp(0.5, 0.0, 1.0)] * embeds.shape[0]
        scaled = (raw - lo) / (hi - lo)
        return [clamp(float(v), 0.0, 1.0) for v in scaled]
    weights = np.asarray(head_weights, dtype=np.float64).reshape(-1)
    normed = _l2_normalize(embeds)
    dim = normed.shape[1]
    if weights.shape[0] == dim + 1:  # trailing bias term
        logits = normed @ weights[:dim] + weights[dim]
    elif weights.shape[0] == dim:
        logits = normed @ weights
    else:
        raise ValueError(f"head_weights length {weights.shape[0]} != embed dim {dim} (+1 bias)")
    squashed = _sigmoid(logits)
    return [clamp(float(v), 0.0, 1.0) for v in squashed]


def zero_shot_interestingness(image_embeds: np.ndarray, text_embeds: np.ndarray) -> list[float]:
    """Per-frame interestingness (0..1) = softmax(cosine vs the prompt PAIR).

    ``text_embeds`` is the two-row "interesting" / "boring" prompt-embedding
    pair (row 0 = interesting). For each frame the two cosine similarities are
    softmaxed and the interesting-class probability is returned — a temperature
    of 100 (SigLIP/CLIP's logit scale) sharpens the contrast. Returns ``[]`` for
    no frames.
    """
    import numpy as np  # noqa: PLC0415 - numpy is in the venv

    embeds = np.asarray(image_embeds, dtype=np.float64)
    texts = np.asarray(text_embeds, dtype=np.float64)
    if embeds.ndim != 2 or embeds.shape[0] == 0:
        return []
    if texts.ndim != 2 or texts.shape[0] < 2:
        raise ValueError("text_embeds must hold the (interesting, boring) prompt pair (>=2 rows)")
    img = _l2_normalize(embeds)
    txt = _l2_normalize(texts[:2])
    sims = img @ txt.T  # (N, 2) cosine similarities
    logits = sims * 100.0
    logits -= logits.max(axis=1, keepdims=True)  # stabilize
    exp = np.exp(logits)
    probs = exp[:, 0] / exp.sum(axis=1)
    return [clamp(float(v), 0.0, 1.0) for v in probs]


def novelty_scores(image_embeds: np.ndarray) -> list[float]:
    """Per-frame embedding novelty (0..1) = ``1 - max cosine to PRIOR frames``.

    The first frame is maximally novel (1.0 — no prior). Each later frame's
    novelty is one minus its greatest cosine similarity to any earlier frame, so
    a frame that closely repeats an earlier one scores near 0 and an outlier
    scores near 1. Pure numpy — this is also the embedding signal
    :mod:`diversity` consumes. Returns ``[]`` for no frames.
    """
    import numpy as np  # noqa: PLC0415 - numpy is in the venv

    embeds = np.asarray(image_embeds, dtype=np.float64)
    if embeds.ndim != 2 or embeds.shape[0] == 0:
        return []
    normed = _l2_normalize(embeds)
    out: list[float] = [1.0]  # first frame: nothing prior -> maximally novel
    for i in range(1, normed.shape[0]):
        sims = normed[:i] @ normed[i]
        novelty = 1.0 - float(sims.max())
        out.append(clamp(novelty, 0.0, 1.0))
    return out


def _curve_to_signals(
    channel: str,
    values: Sequence[float],
    windows: Sequence[tuple[float, float]],
    *,
    confidence: float = 1.0,
) -> tuple[Signal, ...]:
    """Pair a per-frame 0..1 curve with the shared window grid into Signals.

    Values and windows are aligned by index; extra values past the window count
    (or extra windows) are ignored so a mismatch never raises. Each value is
    clamped to 0..1 at the boundary (the frozen contract rule).
    """
    conf = clamp(float(confidence), 0.0, 1.0)
    return tuple(
        Signal(
            channel=channel,
            start=float(w0),
            end=float(w1),
            value=clamp(float(v), 0.0, 1.0),
            confidence=conf,
        )
        for v, (w0, w1) in zip(values, windows, strict=False)
    )


# --------------------------------------------------------------------------- #
# the heavy backbone seam (SigLIP-2) — never imported at module load
# --------------------------------------------------------------------------- #
class BackboneBackend(Protocol):
    """The slice of SigLIP-2 the pure scorers need.

    A real impl is built lazily by :func:`_default_backbone_factory` (never at
    import). Tests inject a FAKE returning hand-built arrays — no model, no
    weights. The whole point of WU4: ``embed_images`` is called ONCE and its
    output feeds aesthetic + zeroShot + novelty.
    """

    def embed_images(self, frames: np.ndarray) -> np.ndarray:
        """Embed N frames -> ``(N, D)`` image embeddings."""
        ...  # pragma: no cover - Protocol stub

    def embed_texts(self, texts: Sequence[str]) -> np.ndarray:
        """Embed M prompt strings -> ``(M, D)`` text embeddings."""
        ...  # pragma: no cover - Protocol stub

    def head_weights(self) -> np.ndarray | None:
        """The tiny aesthetic-MLP head weights, or ``None`` if unavailable."""
        ...  # pragma: no cover - Protocol stub


BackboneFactory = Callable[[dict[str, Any]], BackboneBackend]
FrameLoader = Callable[[str, Sequence[float]], "list[np.ndarray]"]
ModelsPresent = Callable[[dict[str, Any]], bool]


def _default_backbone_factory(settings: dict[str, Any]) -> BackboneBackend:
    """Build the real SigLIP-2 backbone (LAZY import inside the function)."""
    from .vlm_backbone_backend import RealBackboneBackend  # noqa: PLC0415 - heavy seam

    return RealBackboneBackend(settings)


def _default_frame_loader(media_path: str, timestamps: Sequence[float]) -> list[np.ndarray]:
    """Default frame extraction (cv2 imported INSIDE — runtime only).

    Mirrors ``reframe_claudeshorts.detect_subject_centers``: seeks each
    timestamp with ``cv2.VideoCapture`` and grabs one BGR frame. Tests inject a
    fake loader returning synthetic arrays, so cv2 is never imported under test.
    """
    import cv2  # noqa: PLC0415 - job-time native (pre-imported by __main__)

    cap = cv2.VideoCapture(media_path)
    frames: list[np.ndarray] = []
    try:
        for ts in timestamps:
            cap.set(cv2.CAP_PROP_POS_MSEC, float(ts) * 1000.0)
            ok, frame = cap.read()
            if ok and frame is not None:
                frames.append(frame)
    finally:
        cap.release()
    return frames


def _default_models_present(settings: dict[str, Any]) -> bool:
    """True when the SigLIP-2 backbone asset is installed (no heavy import)."""
    from ..assets import manifest  # noqa: PLC0415 - lazy: avoids an import cycle
    from ..assets.manager import AssetManager  # noqa: PLC0415

    entry = manifest.get_asset(BACKBONE_ASSET_NAME)
    if entry is None:
        return False
    mgr = AssetManager(settings_provider=lambda: settings)
    return mgr.installed_path(entry) is not None


def _absent_tracks() -> dict[str, SignalTrack]:
    """The degrade result: every channel present=False with no signals."""
    return {ch: SignalTrack(channel=ch, signals=(), present=False) for ch in BACKBONE_CHANNELS}


# --------------------------------------------------------------------------- #
# the public runner (one backbone load -> three channels)
# --------------------------------------------------------------------------- #
def compute_backbone_signals(
    media_path: str,
    duration: float,
    *,
    settings: dict[str, Any] | None = None,
    backend_factory: BackboneFactory | None = None,
    frame_loader: FrameLoader | None = None,
    models_present: ModelsPresent | None = None,
    prompts: tuple[str, str] | None = None,
    on_progress: ProgressCb | None = None,
    should_cancel: CancelProbe | None = None,
) -> dict[str, SignalTrack]:
    """Embed the clip ONCE with SigLIP-2 -> aesthetic + zeroShot + novelty tracks.

    Returns a ``dict[channel -> SignalTrack]`` over the three backbone channels.
    The WU4 acceptance: a SINGLE ``backend.embed_images`` call serves all three
    sub-scores (no second SigLIP load).

    Degrade paths (each returns three ``present=False`` tracks, never raises):
      * offline AND the backbone asset is not installed (a download would need
        the network — :func:`offline.guard_network` is consulted via the
        ``models_present`` seam);
      * the frame loader returns no frames (unreadable / empty clip).
    A cooperative cancel before embedding also yields the absent tracks.
    """
    settings = dict(settings or {})
    factory = backend_factory or _default_backbone_factory
    loader = frame_loader or _default_frame_loader
    present = models_present or _default_models_present
    prompt_pair = prompts or DEFAULT_PROMPTS

    # Offline gate: only the network path (a missing-model download) degrades.
    if not present(settings) and _offline.is_offline(settings):
        log.info("siglip2 backbone unavailable offline; emitting present=False tracks")
        return _absent_tracks()

    windows = sample_windows(duration)
    timestamps = [round((w0 + w1) / 2.0, 3) for w0, w1 in windows]
    if on_progress is not None:
        on_progress(5.0, "extracting frames")
    if should_cancel is not None and should_cancel():
        return _absent_tracks()

    frames = list(loader(media_path, timestamps) or [])
    if not frames:
        log.info("no frames extracted from %s; backbone tracks present=False", media_path)
        return _absent_tracks()

    import numpy as np  # noqa: PLC0415 - numpy is in the venv

    backend = factory(settings)
    if on_progress is not None:
        on_progress(40.0, "embedding frames (SigLIP-2)")
    image_embeds = np.asarray(backend.embed_images(np.asarray(frames)), dtype=np.float64)
    if image_embeds.ndim != 2 or image_embeds.shape[0] == 0:
        return _absent_tracks()

    text_embeds = np.asarray(backend.embed_texts(list(prompt_pair)), dtype=np.float64)
    head = backend.head_weights()
    head_arr = None if head is None else np.asarray(head, dtype=np.float64)
    if on_progress is not None:
        on_progress(80.0, "scoring (aesthetic / zero-shot / novelty)")

    aesthetic = aesthetic_score(image_embeds, head_arr)
    zero_shot = zero_shot_interestingness(image_embeds, text_embeds)
    novelty = novelty_scores(image_embeds)

    # Align curves to the windows that actually produced a frame.
    used_windows = windows[: image_embeds.shape[0]]
    tracks = {
        CHANNEL_AESTHETIC: SignalTrack(
            channel=CHANNEL_AESTHETIC,
            signals=_curve_to_signals(CHANNEL_AESTHETIC, aesthetic, used_windows),
            present=True,
            fps_hint=DEFAULT_WIN_SEC,
        ),
        CHANNEL_ZERO_SHOT: SignalTrack(
            channel=CHANNEL_ZERO_SHOT,
            signals=_curve_to_signals(CHANNEL_ZERO_SHOT, zero_shot, used_windows),
            present=True,
            fps_hint=DEFAULT_WIN_SEC,
        ),
        CHANNEL_NOVELTY: SignalTrack(
            channel=CHANNEL_NOVELTY,
            signals=_curve_to_signals(CHANNEL_NOVELTY, novelty, used_windows),
            present=True,
            fps_hint=DEFAULT_WIN_SEC,
        ),
    }
    if on_progress is not None:
        on_progress(100.0, "done")
    return tracks


# --------------------------------------------------------------------------- #
# asset registration (mirrors diarize / parakeet_asr / ctc_align)
# --------------------------------------------------------------------------- #
BACKBONE_SIZE_MB = 4540


def register_backbone_assets() -> None:
    """Register the SigLIP-2 SoViT-400M backbone as an on-demand asset (idempotent).

    Apache-2.0 (commercial OK), ~4.54 GB on disk / ~2.3 GB fp16 resident — the
    shared backbone serving aesthetic + zero-shot + novelty in one load. The asset
    name matches :data:`BACKBONE_ASSET_NAME` (and ``system_advisor.ComponentSpec``'s
    ``vlm_backbone`` lookup key) so :func:`_default_models_present` detects an
    already-cached snapshot. Identical re-registration is a no-op (re-import safe).
    """
    from ..assets import manifest  # noqa: PLC0415 - lazy: avoids an import cycle

    manifest.register_asset(
        manifest.AssetEntry(
            name=BACKBONE_ASSET_NAME,
            kind="model",
            size_mb=BACKBONE_SIZE_MB,
            label="SigLIP-2 SoViT-400M (shared vision backbone, Apache-2.0)",
            installer="hf",
            hf_repo=SIGLIP2_MODEL_ID,
            hf_revision=SIGLIP2_REVISION,
        )
    )


# Register the asset at import (mirrors diarize.register_diarize_assets()).
register_backbone_assets()


__all__ = [
    "BACKBONE_ASSET_NAME",
    "BACKBONE_CHANNELS",
    "BACKBONE_SIZE_MB",
    "BACKBONE_VRAM_MB",
    "CHANNEL_AESTHETIC",
    "CHANNEL_NOVELTY",
    "CHANNEL_ZERO_SHOT",
    "DEFAULT_PROMPTS",
    "SIGLIP2_MODEL_ID",
    "BackboneBackend",
    "BackboneFactory",
    "FrameLoader",
    "ModelsPresent",
    "Signal",
    "SignalTrack",
    "aesthetic_score",
    "compute_backbone_signals",
    "novelty_scores",
    "register_backbone_assets",
    "sample_windows",
    "zero_shot_interestingness",
]
