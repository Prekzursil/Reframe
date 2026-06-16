"""Tier-1 scene-cut detection — TransNetV2 shot boundaries (WU3).

TransNetV2 (``soCzech/TransNetV2``, MIT) predicts a *per-frame* shot-change
probability; a rising edge over a threshold is a cut. Its strength over the
CPU ``PySceneDetect`` fallback already in ``boundary.py`` is that it catches
**dissolves / soft transitions** the histogram-difference ``ContentDetector``
misses (the WU3 acceptance). PySceneDetect stays the CPU fallback: when the
heavy model is unavailable (offline + not installed, or torch/tf absent), this
module degrades to an injected ``scene_provider`` whose timestamps are merged
with — never replaced by — the model's, so the existing stack keeps working.

Design follows the canonical Phase-8 seam pattern (see ``diarize`` /
``reframe_claudeshorts``):

* **Pure half** (top of module, fully covered with hand-built numpy arrays):
  rising-edge thresholding (``predictions_to_cuts``), eps-merge with
  PySceneDetect (``merge_with_pyscenedetect``), the shared windowing grid
  (``sample_windows``), and the :class:`Signal` track assembly
  (``emit_scene_signals``).
* **Heavy half** behind a Protocol :class:`TransNetBackend` that is NEVER
  imported at module load. A real impl is built lazily by
  :func:`_default_backend_factory` (which imports the sibling
  ``scene_transnet_backend`` only at runtime); tests inject a fake whose
  ``predict`` returns a canned per-frame probability array — no torch/tf, no
  model, no weights.

The public :func:`compute_scene_cuts` returns ``tuple[float, ...]`` cut
timestamps (the exact shape ``boundary.build_boundary_set``'s ``scene_cuts``
consumes); :func:`emit_scene_signals` adapts those cuts into the shared
``SignalTrack(channel="sceneCut")`` the Wave-2 unified scorer reads.

Pure numpy + stdlib at import time — no heavy-ML imports.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

from ..util import get_logger
from . import offline as _offline

if TYPE_CHECKING:
    import numpy as np

log = get_logger("media_studio.features.scene_transnet")

# --- Tunables ---------------------------------------------------------------
#: rising-edge probability over which a frame is declared a shot change.
DEFAULT_THRESHOLD: float = 0.5
#: cuts within this many seconds of each other are treated as the same cut when
#: merging TransNetV2 output with PySceneDetect (dedup window).
DEFAULT_MERGE_EPS: float = 0.25
#: the asset name + HF repo for the converted PyTorch weights (Wave-2 wires the
#: actual asset entry; named here so ``models_present`` can look it up).
ASSET_NAME: str = "transnetv2-pytorch"
HF_REPO: str = "soCzech/TransNetV2"

#: cooperative cancel probe + progress sink (match the rest of the codebase).
CancelProbe = Callable[[], bool]
ProgressCb = Callable[[float, str], None]


# --- The shared Signal contract (every Phase-8 module emits this) -----------
@dataclass(frozen=True)
class Signal:
    """One scored observation on the shared timeline (seconds, ORIGINAL video).

    ``value`` is ALWAYS normalized to 0.0..1.0 (1.0 = maximally interesting on
    this channel) and clamped at the boundary so the Wave-2 scorer never sees an
    un-normalized number.
    """

    channel: str
    start: float
    end: float
    value: float
    confidence: float = 1.0
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SignalTrack:
    """All Signals from ONE module + a modality-present flag for graceful degrade.

    ``present=False`` is the degrade signal: the Wave-2 scorer drops this
    channel's weight and re-normalizes the survivors. This module returns
    ``present=False`` only when no cut source is available at all (no model AND
    no fallback provider), never fabricated zeros.
    """

    channel: str
    signals: tuple[Signal, ...]
    present: bool
    fps_hint: float | None = None


# --- The heavy backend seam (TransNetV2) — never imported here --------------
class TransNetBackend(Protocol):
    """The slice of TransNetV2 the pure cut-extractor needs.

    A real impl is built lazily by :func:`_default_backend_factory`, never at
    import. Tests inject a FAKE whose ``predict`` returns a hand-built per-frame
    probability array — no model, no weights, no torch/tf.
    """

    def predict(
        self,
        frames: np.ndarray,
        *,
        on_progress: ProgressCb | None = None,
        should_cancel: CancelProbe | None = None,
    ) -> np.ndarray:
        """Return a 1-D per-frame shot-change probability array for ``frames``."""
        ...  # pragma: no cover - Protocol stub


# Seam types (mirror reframe_claudeshorts's Detector / diarize's factory).
BackendFactory = Callable[[dict[str, Any]], TransNetBackend]
#: path, fps -> stacked frames (TransNetV2 wants a 48x27 RGB stream). cv2 is
#: imported INSIDE the default loader; tests inject synthetic numpy frames.
FrameLoader = Callable[[str, float], "np.ndarray"]
#: PySceneDetect CPU fallback: () -> cut timestamps in seconds (boundary seam).
SceneProvider = Callable[[], Sequence[float]]
#: are the gated weights installed? (drives the offline degrade).
ModelsPresent = Callable[[dict[str, Any]], bool]


# --- Pure: rising-edge cut extraction ---------------------------------------
def predictions_to_cuts(
    frame_probs: np.ndarray,
    *,
    threshold: float = DEFAULT_THRESHOLD,
    fps: float,
) -> tuple[float, ...]:
    """Convert per-frame shot-change probabilities into cut timestamps (seconds).

    A *cut* is a rising edge: the first frame index where the probability
    crosses from ``<= threshold`` up to ``> threshold``. The timestamp is that
    frame index divided by ``fps``. A run that stays above threshold yields a
    single cut at its leading edge (so a multi-frame *dissolve* ramp produces
    one cut, not one per frame — the WU3 acceptance). Returns sorted ascending.

    ``frame_probs`` is flattened to 1-D so an ``Nx1`` model output also works.
    """
    if fps <= 0.0:
        raise ValueError(f"fps must be positive, got {fps}")
    probs = _as_1d(frame_probs)
    cuts: list[float] = []
    prev_above = False
    for i, p in enumerate(probs):
        above = float(p) > threshold
        if above and not prev_above:
            cuts.append(round(i / float(fps), 3))
        prev_above = above
    return tuple(cuts)


def merge_with_pyscenedetect(
    transnet_cuts: Sequence[float],
    pyscene_cuts: Sequence[float],
    *,
    eps: float = DEFAULT_MERGE_EPS,
) -> tuple[float, ...]:
    """Union TransNetV2 cuts with PySceneDetect cuts, de-duping within ``eps``.

    Keeps the PySceneDetect CPU fallback fully working: a cut present in EITHER
    source survives, but two cuts within ``eps`` seconds (the same boundary
    found by both detectors) collapse to one (the earlier timestamp, for
    determinism). Returns sorted ascending, de-duplicated.
    """
    merged = sorted(float(c) for c in (*transnet_cuts, *pyscene_cuts) if isinstance(c, (int, float)))
    out: list[float] = []
    for c in merged:
        if not out or c - out[-1] > eps:
            out.append(c)
    return tuple(out)


def sample_windows(
    duration: float,
    win_sec: float = 1.0,
    hop_sec: float = 1.0,
) -> tuple[tuple[float, float], ...]:
    """The shared windowing grid (mirrors ``reframe_claudeshorts.window_timestamps``).

    Returns ``(start, end)`` windows of ``win_sec`` stepped by ``hop_sec`` over
    ``[0, duration)`` on the ORIGINAL timeline, so every Phase-8 module aligns
    by window index and the Wave-2 scorer can co-index tracks. The final window
    is clamped to ``duration``. A non-positive duration yields no windows.
    """
    if win_sec <= 0.0 or hop_sec <= 0.0:
        raise ValueError(f"win_sec/hop_sec must be positive, got {win_sec}/{hop_sec}")
    d = max(0.0, float(duration))
    if d <= 0.0:
        return ()
    windows: list[tuple[float, float]] = []
    start = 0.0
    while start < d - 1e-9:
        end = min(start + win_sec, d)
        windows.append((round(start, 3), round(end, 3)))
        start += hop_sec
    return tuple(windows)


def emit_scene_signals(cuts: Sequence[float], duration: float) -> SignalTrack:
    """Adapt cut timestamps into a ``SignalTrack(channel="sceneCut")``.

    Each cut becomes an instantaneous ``Signal`` (``start == end == cut``) with
    ``value=1.0`` (a cut is a maximally certain scene boundary). Cuts outside
    ``[0, duration]`` are dropped (defensive — a model artifact must not place a
    cut past the clip). An empty cut list with a valid clip still yields
    ``present=True`` (the clip simply has no scene changes — a real, non-degrade
    answer); ``present=False`` is reserved for the no-source degrade in
    :func:`compute_scene_cuts`.
    """
    d = max(0.0, float(duration))
    in_range = sorted(float(c) for c in cuts if isinstance(c, (int, float)) and 0.0 <= float(c) <= d + 1e-9)
    signals = tuple(
        Signal(
            channel="sceneCut",
            start=round(c, 3),
            end=round(c, 3),
            value=1.0,
            confidence=1.0,
            meta={},
        )
        for c in in_range
    )
    return SignalTrack(channel="sceneCut", signals=signals, present=True)


def _as_1d(arr: np.ndarray) -> np.ndarray:
    """Flatten a model output to a 1-D probability array (lazy numpy import)."""
    import numpy as np  # noqa: PLC0415 - numpy is in the venv; kept local for symmetry

    return np.asarray(arr, dtype=float).reshape(-1)


# --- Default heavy seams (lazy real impls; tests inject fakes) --------------
def _default_backend_factory(
    settings: dict[str, Any],
) -> TransNetBackend:  # pragma: no cover - prod seam (imports the heavy native stack)
    """Build the real TransNetV2 backend (LAZY import inside the function)."""
    from .scene_transnet_backend import RealTransNetBackend  # noqa: PLC0415 - heavy seam

    return RealTransNetBackend(settings)


def _default_frame_loader(media_path: str, fps: float) -> np.ndarray:
    """Default frame loader: decode ``media_path`` to a 48x27 RGB stack (lazy cv2).

    ``cv2`` is imported INSIDE the loader so importing this module never drags
    in OpenCV (mirrors ``reframe_claudeshorts.detect_subject_centers``). Tests
    inject a fake loader returning synthetic numpy frames, so this body is the
    runtime-only seam and is coverage-excluded.
    """
    import cv2  # noqa: PLC0415 - job-time native (pre-imported by __main__)  # pragma: no cover - prod seam
    import numpy as np  # noqa: PLC0415  # pragma: no cover - prod seam

    cap = cv2.VideoCapture(media_path)  # pragma: no cover - prod seam
    frames: list[np.ndarray] = []  # pragma: no cover - prod seam
    try:  # pragma: no cover - prod seam
        src_fps = cap.get(cv2.CAP_PROP_FPS) or fps  # pragma: no cover - prod seam
        step = max(1, int(round(src_fps / fps))) if fps > 0 else 1  # pragma: no cover - prod seam
        idx = 0  # pragma: no cover - prod seam
        while True:  # pragma: no cover - prod seam
            ok, frame = cap.read()  # pragma: no cover - prod seam
            if not ok:  # pragma: no cover - prod seam
                break  # pragma: no cover - prod seam
            if idx % step == 0:  # pragma: no cover - prod seam
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)  # pragma: no cover - prod seam
                frames.append(cv2.resize(rgb, (48, 27)))  # pragma: no cover - prod seam
            idx += 1  # pragma: no cover - prod seam
    finally:  # pragma: no cover - prod seam
        cap.release()  # pragma: no cover - prod seam
    return np.asarray(frames, dtype="uint8")  # pragma: no cover - prod seam


def default_models_present(settings: dict[str, Any]) -> bool:
    """True when the converted TransNetV2 weights are installed (no import).

    Looks the asset up via the asset manager so an already-cached snapshot
    counts — that is what lets the model run offline. Any lookup failure (asset
    not yet registered in Wave-1) degrades to ``False`` (use the fallback),
    never raises.
    """
    try:
        from ..assets import manifest  # noqa: PLC0415 - lazy: avoids a cycle
        from ..assets.manager import AssetManager  # noqa: PLC0415

        entry = manifest.get_asset(ASSET_NAME)
        if entry is None:
            return False
        mgr = AssetManager(settings_provider=lambda: settings)
        return mgr.installed_path(entry) is not None
    except Exception:  # noqa: BLE001 - missing asset machinery -> use fallback
        return False


# --- Public runner ----------------------------------------------------------
def compute_scene_cuts(
    media_path: str,
    *,
    fps_hint: float | None = None,
    settings: dict[str, Any] | None = None,
    backend_factory: BackendFactory | None = None,
    frame_loader: FrameLoader | None = None,
    scene_provider: SceneProvider | None = None,
    threshold: float = DEFAULT_THRESHOLD,
    merge_eps: float = DEFAULT_MERGE_EPS,
    models_present: ModelsPresent | None = None,
    on_progress: ProgressCb | None = None,
    should_cancel: CancelProbe | None = None,
) -> tuple[float, ...]:
    """Return shot-cut timestamps (seconds) for ``media_path``.

    Strategy:

    1. If the TransNetV2 model is available (installed, or online so it could be
       fetched), load frames via ``frame_loader``, run ``predict``, and convert
       the rising edges to cuts.
    2. Pull the PySceneDetect CPU-fallback cuts from ``scene_provider`` (if
       injected) and **merge** them with the model cuts (eps-dedup). Either
       source alone still produces a result, so the fallback never stops
       working — the WU3 acceptance.
    3. If NEITHER source is available (model missing + offline, AND no
       provider), return an empty tuple — the caller's degrade path. Any backend
       failure also degrades to the provider's cuts rather than raising.

    Output shape is ``tuple[float, ...]`` — exactly ``boundary``'s ``scene_cuts``.
    """
    settings = settings or {}
    fps = float(fps_hint) if fps_hint and fps_hint > 0 else 25.0
    present = models_present or default_models_present
    have_model = present(settings)

    # Offline + no installed model -> the model path is unreachable (a fetch
    # would need the network). Fall back to the provider only.
    if not have_model and _offline.is_offline(settings):
        log.info("scene_transnet: model unavailable offline; using PySceneDetect fallback")
        return _fallback_cuts(scene_provider)

    transnet_cuts: tuple[float, ...] = ()
    if have_model:
        transnet_cuts = _run_model(
            media_path,
            fps=fps,
            settings=settings,
            backend_factory=backend_factory or _default_backend_factory,
            frame_loader=frame_loader or _default_frame_loader,
            threshold=threshold,
            on_progress=on_progress,
            should_cancel=should_cancel,
        )

    pyscene_cuts = _fallback_cuts(scene_provider)
    return merge_with_pyscenedetect(transnet_cuts, pyscene_cuts, eps=merge_eps)


def _run_model(
    media_path: str,
    *,
    fps: float,
    settings: dict[str, Any],
    backend_factory: BackendFactory,
    frame_loader: FrameLoader,
    threshold: float,
    on_progress: ProgressCb | None,
    should_cancel: CancelProbe | None,
) -> tuple[float, ...]:
    """Load frames + run the backend; a failure degrades to no model cuts."""
    try:
        frames = frame_loader(media_path, fps)
        backend = backend_factory(settings)
        probs = backend.predict(frames, on_progress=on_progress, should_cancel=should_cancel)
        return predictions_to_cuts(probs, threshold=threshold, fps=fps)
    except Exception as exc:  # noqa: BLE001 - a model failure must not crash the pipeline
        log.warning("scene_transnet: TransNetV2 failed for %s: %s", media_path, exc)
        return ()


def _fallback_cuts(scene_provider: SceneProvider | None) -> tuple[float, ...]:
    """Pull + sanitize the injected PySceneDetect fallback cuts (never raises)."""
    if scene_provider is None:
        return ()
    try:
        raw = scene_provider()
    except Exception as exc:  # noqa: BLE001 - fallback failure must not crash
        log.warning("scene_transnet: scene_provider failed: %s", exc)
        return ()
    return tuple(sorted({float(c) for c in raw if isinstance(c, (int, float))}))


def compute_scene_signals(
    media_path: str,
    duration: float,
    *,
    fps_hint: float | None = None,
    settings: dict[str, Any] | None = None,
    backend_factory: BackendFactory | None = None,
    frame_loader: FrameLoader | None = None,
    scene_provider: SceneProvider | None = None,
    threshold: float = DEFAULT_THRESHOLD,
    merge_eps: float = DEFAULT_MERGE_EPS,
    models_present: ModelsPresent | None = None,
    on_progress: ProgressCb | None = None,
    should_cancel: CancelProbe | None = None,
) -> SignalTrack:
    """Compute scene cuts and emit them as a ``SignalTrack(channel="sceneCut")``.

    The Wave-2-scorer-facing entry point. Returns ``present=False`` only when no
    cut source is available at all (model missing + offline, AND no fallback
    provider) — the degrade contract. Otherwise ``present=True`` with one
    instantaneous ``Signal`` per cut (an empty-but-present track means "this clip
    genuinely has no scene changes", which the scorer treats as a real value).
    """
    have_source = _has_cut_source(
        settings=settings or {},
        scene_provider=scene_provider,
        models_present=models_present,
    )
    cuts = compute_scene_cuts(
        media_path,
        fps_hint=fps_hint,
        settings=settings,
        backend_factory=backend_factory,
        frame_loader=frame_loader,
        scene_provider=scene_provider,
        threshold=threshold,
        merge_eps=merge_eps,
        models_present=models_present,
        on_progress=on_progress,
        should_cancel=should_cancel,
    )
    if not have_source:
        return SignalTrack(channel="sceneCut", signals=(), present=False, fps_hint=fps_hint)
    track = emit_scene_signals(cuts, duration)
    return SignalTrack(
        channel=track.channel,
        signals=track.signals,
        present=track.present,
        fps_hint=fps_hint,
    )


def _has_cut_source(
    *,
    settings: Mapping[str, Any],
    scene_provider: SceneProvider | None,
    models_present: ModelsPresent | None,
) -> bool:
    """True if SOME cut source can run (model reachable, or a fallback provider).

    The model is reachable when installed, or when online (it could be fetched).
    A fallback ``scene_provider`` is always a valid source. Only when both are
    absent is the modality truly unavailable (``present=False``).
    """
    if scene_provider is not None:
        return True
    present = models_present or default_models_present
    settings_dict = dict(settings)
    if present(settings_dict):
        return True
    return not _offline.is_offline(settings_dict)


# --------------------------------------------------------------------------- #
# asset registration (mirrors diarize / parakeet_asr / ctc_align)
# --------------------------------------------------------------------------- #
#: pinned TransNetV2 commit (SOTA manifest #4).
ASSET_REVISION: str = "85cef72"
ASSET_SIZE_MB: int = 40


def register_scene_transnet_assets() -> None:
    """Register the TransNetV2 PyTorch weights as an on-demand asset (idempotent).

    MIT (commercial OK), ~40 MB, fp16 <1 GB. The asset name matches
    :data:`ASSET_NAME` (and ``system_advisor.ComponentSpec``'s ``scene_transnet``
    lookup key) so :func:`default_models_present` detects an already-cached
    snapshot. Identical re-registration is a no-op (module re-import safe).
    """
    from ..assets import manifest  # noqa: PLC0415 - lazy: avoids an import cycle

    manifest.register_asset(
        manifest.AssetEntry(
            name=ASSET_NAME,
            kind="model",
            size_mb=ASSET_SIZE_MB,
            label="TransNetV2 (scene-cut detection, MIT)",
            installer="hf",
            hf_repo=HF_REPO,
            hf_revision=ASSET_REVISION,
        )
    )


# Register the asset at import (mirrors diarize.register_diarize_assets()).
register_scene_transnet_assets()


__all__ = [
    "ASSET_NAME",
    "ASSET_REVISION",
    "ASSET_SIZE_MB",
    "DEFAULT_MERGE_EPS",
    "DEFAULT_THRESHOLD",
    "HF_REPO",
    "Signal",
    "SignalTrack",
    "TransNetBackend",
    "compute_scene_cuts",
    "compute_scene_signals",
    "default_models_present",
    "emit_scene_signals",
    "merge_with_pyscenedetect",
    "predictions_to_cuts",
    "register_scene_transnet_assets",
    "sample_windows",
]
