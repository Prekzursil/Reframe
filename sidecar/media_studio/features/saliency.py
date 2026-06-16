"""Tier-1 visual SALIENCY (Phase-8 WU1).

A **ViNet-S** video-saliency wrapper (the ICASSP-2025 minimalistic repo, arXiv
2502.00397) that produces, over the shared signal timeline:

  * a per-frame **interestingness curve** (spatial-entropy / peak energy of each
    saliency map, normalized 0..1) emitted as the ``saliency`` :class:`Signal`
    channel, and
  * saliency-weighted **crop centers** (the argmax centroid of each map,
    normalized 0..1) — the *no-face* crop-track that later feeds
    :func:`reframe_claudeshorts.detect_subject_centers` so footage with no faces
    still tracks the most salient region.

The heavy half (the real ViNet-S torch model) lives behind a single injectable
**backend seam** (:class:`SaliencyBackend`): this module — and its tests — never
import torch / the model at import time. The real implementation is built lazily
by :func:`_default_backend_factory` from a sibling ``saliency_backend.py`` (the
diarize pattern). Tests inject a FAKE backend whose ``infer`` returns hand-built
numpy saliency stacks, so no weights/model are ever touched.

The PURE half — interestingness math, centroid extraction, windowing, min-max
normalization, track assembly — is plain numpy and is unit-tested exhaustively
with hand-built arrays (100% line+branch).

Missing-modality contract (the §-signal degrade rule): ViNet-S weights are an
on-demand, **non-commercial** (CC-BY-NC-SA 4.0) asset. When the model is not
present AND offline mode is on, :func:`compute_saliency_signals` returns
``SignalTrack(channel="saliency", signals=(), present=False)`` — it NEVER raises
and NEVER fabricates zeros; the Wave-2 scorer drops the channel and re-normalizes
the survivors.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

from ..util import clamp, get_logger
from . import offline as _offline

if TYPE_CHECKING:
    import numpy as np  # numpy IS in the venv; kept here so the module surface stays light.

log = get_logger("media_studio.features.saliency")

#: This module's channel-of-record (frozen wire vocabulary; see the signal contract).
CHANNEL = "saliency"

#: Default windowing grid (mirrors reframe_claudeshorts.window_timestamps spread).
DEFAULT_WIN_SEC = 1.0
DEFAULT_HOP_SEC = 1.0

#: ViNet-S is a non-commercial, on-demand asset (CC-BY-NC-SA 4.0).
ASSET_NAME = "vinet-s-saliency"
ASSET_SIZE_MB = 36

#: Cooperative cancel probe + progress sink (match the rest of the codebase).
CancelProbe = Callable[[], bool]
ProgressCb = Callable[[float, str], None]

#: path, timestamps -> sampled BGR frames (cv2 seam; default lazily uses cv2).
FrameLoader = Callable[[str, "Sequence[float]"], "list[np.ndarray]"]


# --------------------------------------------------------------------------- #
# the common Signal contract (shared shape every Phase-8 module emits)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Signal:
    """One scored observation on the shared timeline (seconds, ORIGINAL video).

    ``value`` is ALWAYS normalized to 0.0..1.0 (1.0 = maximally interesting on
    this channel); it is clamped at the boundary before emission.
    """

    channel: str
    start: float
    end: float
    value: float
    confidence: float = 1.0
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SignalTrack:
    """All :class:`Signal`\\ s from one module + a modality-presence flag.

    ``present=False`` is the degrade signal: the modality is ABSENT (model
    unavailable while offline) so the Wave-2 scorer drops this channel's weight
    and re-normalizes the surviving channels.
    """

    channel: str
    signals: tuple[Signal, ...]
    present: bool
    fps_hint: float | None = None


# --------------------------------------------------------------------------- #
# pure: windowing (shared grid so the scorer can align tracks by index)
# --------------------------------------------------------------------------- #
def sample_windows(
    duration: float,
    win_sec: float = DEFAULT_WIN_SEC,
    hop_sec: float = DEFAULT_HOP_SEC,
) -> tuple[tuple[float, float], ...]:
    """Tile ``duration`` seconds into ``[start, end)`` windows on a shared grid.

    Mirrors :func:`reframe_claudeshorts.window_timestamps` as a *window* grid:
    one window every ``hop_sec`` of width ``win_sec``, the last window clamped to
    ``duration``. A non-positive duration yields a single instantaneous window at
    the origin so callers always get at least one slot.
    """
    d = max(0.0, float(duration))
    w = max(1e-6, float(win_sec))
    h = max(1e-6, float(hop_sec))
    if d <= 0.0:
        return ((0.0, 0.0),)
    windows: list[tuple[float, float]] = []
    start = 0.0
    while start < d - 1e-9:
        end = min(start + w, d)
        windows.append((round(start, 6), round(end, 6)))
        start += h
    if not windows:  # pragma: no cover - d>0 with finite hop always yields >=1
        windows.append((0.0, d))
    return tuple(windows)


def normalize_curve(values: Sequence[float]) -> list[float]:
    """Min-max normalize a sequence into 0..1 (a flat curve maps to all zeros).

    The shared squash every module applies BEFORE emission so the scorer never
    sees an un-normalized number. An empty input returns an empty list.
    """
    vals = [float(v) for v in values]
    if not vals:
        return []
    lo = min(vals)
    hi = max(vals)
    span = hi - lo
    if span <= 0.0:
        return [0.0 for _ in vals]
    return [clamp((v - lo) / span, 0.0, 1.0) for v in vals]


# --------------------------------------------------------------------------- #
# pure: interestingness curve + crop centroids over saliency maps
# --------------------------------------------------------------------------- #
def interestingness_curve(saliency_maps: np.ndarray) -> list[float]:
    """Per-frame interestingness in 0..1 from an ``NxHxW`` saliency stack.

    A frame whose saliency mass concentrates on a sharp peak is more
    *interesting* than a flat/uniform one. We score each frame by its peak-to-
    mean ratio (``max / (mean + eps)``) — high for a single hot region, ~1 for a
    uniform map — then min-max normalize the per-frame scores across the clip.
    An empty stack returns an empty curve.
    """
    import numpy as np  # noqa: PLC0415 - numpy is in the venv; kept local for a light surface

    maps = np.asarray(saliency_maps, dtype=np.float64)
    if maps.size == 0 or maps.shape[0] == 0:
        return []
    flat = maps.reshape(maps.shape[0], -1)
    peak = flat.max(axis=1)
    mean = flat.mean(axis=1)
    scores = peak / (mean + 1e-9)
    return normalize_curve(scores.tolist())


def crop_centers_from_saliency(saliency_maps: np.ndarray) -> list[tuple[float, float]]:
    """Normalized ``(cx, cy)`` argmax centroid per frame of an ``NxHxW`` stack.

    For each frame the brightest saliency pixel is the crop center; the
    coordinates are normalized to 0..1 across width/height so they drop straight
    into :func:`reframe_claudeshorts.detect_subject_centers`'s ``cx_norm``
    contract. A single-pixel map yields ``(0.0, 0.0)`` (no division by zero). An
    empty stack returns an empty list.
    """
    import numpy as np  # noqa: PLC0415 - numpy is in the venv; kept local for a light surface

    maps = np.asarray(saliency_maps, dtype=np.float64)
    if maps.size == 0 or maps.shape[0] == 0:
        return []
    n, h, w = maps.shape
    centers: list[tuple[float, float]] = []
    for i in range(n):
        idx = int(np.argmax(maps[i]))
        row, col = divmod(idx, w)
        cx = (col / (w - 1)) if w > 1 else 0.0
        cy = (row / (h - 1)) if h > 1 else 0.0
        centers.append((clamp(cx, 0.0, 1.0), clamp(cy, 0.0, 1.0)))
    return centers


# --------------------------------------------------------------------------- #
# the heavy backend seam (real ViNet-S) — never imported at module load
# --------------------------------------------------------------------------- #
class SaliencyBackend(Protocol):
    """The slice of the ViNet-S model the pure runner needs.

    A real implementation (built lazily by :func:`_default_backend_factory`,
    never at import) takes sampled frames and returns an ``NxHxW`` saliency
    stack. Tests inject a FAKE returning hand-built numpy arrays — no model, no
    weights.
    """

    def infer(self, frames: np.ndarray) -> np.ndarray:
        """Return an ``NxHxW`` per-frame saliency stack for ``frames``."""
        ...  # pragma: no cover - Protocol body; the real impl lives in the backend module


#: factory seam: default = lazy real impl; tests inject a fake.
SaliencyFactory = Callable[[dict[str, Any]], SaliencyBackend]
#: availability seam: are the (gated, non-commercial) ViNet-S weights installed?
ModelsPresent = Callable[[dict[str, Any]], bool]


# --------------------------------------------------------------------------- #
# the public runner
# --------------------------------------------------------------------------- #
def compute_saliency_signals(
    media_path: str,
    duration: float,
    *,
    settings: dict[str, Any] | None = None,
    backend_factory: SaliencyFactory | None = None,
    frame_loader: FrameLoader | None = None,
    models_present: ModelsPresent | None = None,
    on_progress: ProgressCb | None = None,
    should_cancel: CancelProbe | None = None,
) -> SignalTrack:
    """Compute the ``saliency`` :class:`SignalTrack` for one clip.

    Samples one frame per :func:`sample_windows` window, runs the ViNet-S backend
    to get per-frame saliency maps, derives the interestingness curve, and emits
    one :class:`Signal` per window (its normalized interestingness, with the crop
    center stashed in ``meta``).

    Degrade (the missing-modality contract): when the gated ViNet-S weights are
    NOT installed AND offline mode is on, returns
    ``SignalTrack(channel="saliency", signals=(), present=False)`` — never raises,
    never fabricates zeros. If the model is present it runs offline too; if the
    loaded frames are empty (unreadable / zero-length media) the track is still
    ``present=True`` with one neutral 0.0 signal so the timeline is never blank.
    """
    settings = dict(settings or {})
    factory = backend_factory or _default_backend_factory
    loader = frame_loader or _default_frame_loader
    present_fn = models_present or default_models_present

    # Offline + missing model -> degrade (drop the channel). A download would
    # need the network; we refuse silently via the present=False flag.
    if not present_fn(settings) and _offline.is_offline(settings):
        log.info("saliency: ViNet-S unavailable offline -> channel absent (degrade)")
        return SignalTrack(channel=CHANNEL, signals=(), present=False)

    windows = sample_windows(duration)
    timestamps = [round((s + e) / 2.0, 6) for s, e in windows]

    if on_progress is not None:
        on_progress(5.0, "sampling frames for saliency")
    if should_cancel is not None and should_cancel():
        return SignalTrack(channel=CHANNEL, signals=(), present=True, fps_hint=None)

    frames = list(loader(media_path, timestamps) or [])
    if not frames:
        # Unreadable / zero-length media: a single neutral observation keeps the
        # timeline populated (present=True — the modality exists, just empty).
        s, e = windows[0]
        return SignalTrack(
            channel=CHANNEL,
            signals=(Signal(channel=CHANNEL, start=s, end=e, value=0.0, confidence=1.0),),
            present=True,
        )

    if on_progress is not None:
        on_progress(40.0, "running ViNet-S saliency")
    backend = factory(settings)
    import numpy as np  # noqa: PLC0415 - numpy is in the venv; kept local for a light surface

    saliency_maps = np.asarray(backend.infer(np.asarray(frames)), dtype=np.float64)
    curve = interestingness_curve(saliency_maps)
    centers = crop_centers_from_saliency(saliency_maps)

    signals: list[Signal] = []
    for i, (start, end) in enumerate(windows):
        value = curve[i] if i < len(curve) else 0.0
        meta: dict[str, Any] = {}
        if i < len(centers):
            cx, cy = centers[i]
            meta = {"cropCenter": [cx, cy]}
        signals.append(
            Signal(
                channel=CHANNEL,
                start=start,
                end=end,
                value=clamp(value, 0.0, 1.0),
                confidence=1.0,
                meta=meta,
            )
        )
    if on_progress is not None:
        on_progress(100.0, "saliency done")
    return SignalTrack(channel=CHANNEL, signals=tuple(signals), present=True)


# --------------------------------------------------------------------------- #
# default heavy seams (lazy real impls; tests inject fakes)
# --------------------------------------------------------------------------- #
def default_models_present(settings: dict[str, Any]) -> bool:
    """True when the ViNet-S weights are installed (no heavy import).

    Uses the asset manager's installed-detection so an already-cached weight
    counts — that is what makes offline saliency possible. A missing manifest
    entry or uninstalled asset returns False (-> degrade when offline).
    """
    from ..assets import manifest  # noqa: PLC0415 - lazy: avoids an import cycle
    from ..assets.manager import AssetManager  # noqa: PLC0415 - lazy: avoids a cycle

    entry = manifest.get_asset(ASSET_NAME)
    if entry is None:
        return False
    mgr = AssetManager(settings_provider=lambda: settings)
    return mgr.installed_path(entry) is not None


def _default_backend_factory(
    settings: dict[str, Any],
) -> SaliencyBackend:  # pragma: no cover - lazy heavy seam (torch/ViNet-S); tests inject a fake
    """Build the real ViNet-S backend (LAZY import inside the function; runtime only)."""
    from .saliency_backend import ViNetSaliencyBackend  # noqa: I001, PLC0415  # pyright: ignore[reportMissingImports]  # fmt: skip

    return ViNetSaliencyBackend(settings)


def _default_frame_loader(
    media_path: str, timestamps: Sequence[float]
) -> list[np.ndarray]:  # pragma: no cover - lazy native (cv2 + ffmpeg subprocess); tests inject a fake loader
    """Extract one BGR frame per timestamp (LAZY ``cv2``; runtime only).

    Delegates to :func:`reframe_claudeshorts`'s proven ffmpeg-extract +
    ``cv2.imread`` path so the cv2 native is imported only inside a job body
    (A6 pre-import rule). Frames that fail to decode are skipped.
    """
    import os  # noqa: PLC0415
    import shutil  # noqa: PLC0415
    import subprocess  # noqa: PLC0415 - argv list only, never shell=True
    import tempfile  # noqa: PLC0415

    import cv2  # noqa: PLC0415 - job-time native (pre-imported by __main__)

    from .reframe_claudeshorts import build_frame_extract_argv  # noqa: PLC0415 - heavy seam

    tmpdir = tempfile.mkdtemp(prefix="media_studio_saliency_")
    frames: list[np.ndarray] = []
    try:
        for i, ts in enumerate(timestamps):
            frame_path = os.path.join(tmpdir, f"f_{i:04d}.jpg")
            subprocess.run(  # noqa: S603 - argv list, never shell=True
                build_frame_extract_argv(media_path, float(ts), frame_path),
                capture_output=True,
                check=False,
            )
            if not os.path.exists(frame_path):
                continue
            img = cv2.imread(frame_path)
            if img is not None:
                frames.append(img)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    return frames


# --------------------------------------------------------------------------- #
# asset registration (mirrors diarize / parakeet_asr / ctc_align)
# --------------------------------------------------------------------------- #
#: pinned ViNet-S commit (SOTA manifest #1) — the GDrive-hosted ICASSP-2025 .pt.
ASSET_REVISION = "d09066b"
#: PINNED direct-download URL for the ~36 MB ViNet-S weight (A6 lesson 5).
ASSET_URL = (
    "https://drive.usercontent.google.com/download?id=1Tt5pPq4La8a-Nm5oN2g0K3sQ8aJpVfXk&export=download&confirm=t"
)
#: relative dest under the assets root (download installer needs a dest path).
ASSET_DEST = "models/vinet-s-saliency.pt"


def register_saliency_assets() -> None:
    """Register the ViNet-S saliency weights as an on-demand asset (idempotent).

    CC-BY-NC-SA 4.0 (non-commercial, local-only), ~36 MB. The asset name matches
    :data:`ASSET_NAME` (and ``system_advisor.ComponentSpec``'s ``saliency`` lookup
    key) so :func:`default_models_present` detects an already-downloaded weight.
    Identical re-registration is a no-op (module re-import safe).
    """
    from ..assets import manifest  # noqa: PLC0415 - lazy: avoids an import cycle

    manifest.register_asset(
        manifest.AssetEntry(
            name=ASSET_NAME,
            kind="model",
            size_mb=ASSET_SIZE_MB,
            dest=ASSET_DEST,
            label="ViNet-S (video saliency, CC-BY-NC-SA 4.0, local-only)",
            installer="download",
            url=ASSET_URL,
        )
    )


# Register the asset at import (mirrors diarize.register_diarize_assets()).
register_saliency_assets()


__all__ = [
    "ASSET_DEST",
    "ASSET_NAME",
    "ASSET_REVISION",
    "ASSET_SIZE_MB",
    "ASSET_URL",
    "CHANNEL",
    "DEFAULT_HOP_SEC",
    "DEFAULT_WIN_SEC",
    "FrameLoader",
    "ModelsPresent",
    "SaliencyBackend",
    "SaliencyFactory",
    "Signal",
    "SignalTrack",
    "compute_saliency_signals",
    "crop_centers_from_saliency",
    "default_models_present",
    "interestingness_curve",
    "normalize_curve",
    "register_saliency_assets",
    "sample_windows",
]
