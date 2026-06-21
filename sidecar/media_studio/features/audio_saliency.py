"""Tier-1 AUDIO-EVENT saliency (Phase-8 WU2 — PANNs CNN14 audio tagging).

This module turns the soundtrack into a set of per-window audio *interest*
signals that the Wave-2 unified scorer consumes uniformly with the visual
signals — WITHOUT relying on a transcript keyword like ``(Applause)`` (the
fragile heuristic this replaces). A laughter burst, an applause swell, a music
hit, or a sudden loudness spike each becomes a normalized ``Signal`` on the
shared timeline.

Design (the canonical Phase-8 seam pattern — see ``diarize`` / ``stabilize`` /
``reframe_claudeshorts``):

  * **Pure half (fully covered, no heavy deps):** the :class:`Signal` /
    :class:`SignalTrack` contract, the shared ``sample_windows`` grid, the
    AudioSet class-index map, :func:`loudness_curve` (RMS -> 0..1, plain numpy,
    needs NO model), :func:`peak_windows` (turns a frame x 527 tag-probability
    matrix into windowed :class:`Signal` peaks), and the track-assembly /
    degrade logic. Every line here is unit-tested with hand-built numpy arrays.

  * **Heavy half (behind seams, never imported at module load):** the real
    PANNs CNN14 tagger lives in a sibling ``audio_saliency_backend.py`` and is
    built LAZILY by :func:`_default_backend_factory`; the audio decode (ffmpeg
    -> numpy) is the injectable ``audio_loader`` seam. Tests inject a fake
    :class:`PannsBackend` returning a canned tag matrix and a fake loader
    returning synthetic samples — no torch, no panns, no ffmpeg.

Missing-modality contract (the §3 degrade rule): a silent / no-audio clip, or an
offline machine without the model, returns ``present=False`` tracks for the
model-backed channels (``audioSalience`` / ``laughter`` / ``applause`` /
``music``) — never fabricated zeros, never a raise. ``loudness`` needs no model,
so it is ALWAYS present (its samples are zeros for true silence — an honest
measurement, not a fabrication).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

from ..util import clamp, get_logger
from . import offline as _offline

if TYPE_CHECKING:  # numpy IS in the venv; kept import-light for symmetry with peers.
    import numpy as np

log = get_logger("media_studio.features.audio_saliency")

# --------------------------------------------------------------------------- #
# frozen channel vocabulary (wire-stable; the Wave-2 scorer keys weights here)
# --------------------------------------------------------------------------- #
#: every audio channel this module can emit. ``audioSalience`` is the
#: name-of-record (the primary track); the rest are event-specific.
AUDIO_CHANNELS: tuple[str, ...] = (
    "audioSalience",
    "laughter",
    "applause",
    "music",
    "loudness",
)

#: AudioSet (527-class) indices for the events we surface. CNN14's tag vector is
#: ordered by the canonical AudioSet ontology; these are the stable indices for
#: the three event classes (frozen so a model swap can re-map without touching
#: the pure logic). ``audioSalience`` is DERIVED (max over the event classes),
#: not a single AudioSet index.
AUDIOSET_CLASS_INDEX: dict[str, int] = {
    "laughter": 16,
    "applause": 63,
    "music": 137,
}

#: the model-backed channels (everything except the model-free ``loudness``).
TAG_CHANNELS: tuple[str, ...] = ("audioSalience", "laughter", "applause", "music")

#: PANNs CNN14 expects 32 kHz mono (the checkpoint's training rate).
TARGET_SR = 32000

#: on-demand asset (SOTA manifest #6 — PANNs CNN14, MIT, ~300 MB, CPU-designed).
#: name matches ``default_models_present`` + system_advisor's ``audio_saliency``.
ASSET_NAME = "panns-cnn14"
ASSET_SIZE_MB = 300
#: PINNED PANNs CNN14 AudioSet checkpoint (the URL panns-inference resolves to).
ASSET_URL = "https://zenodo.org/record/3987831/files/Cnn14_mAP%3D0.431.pth?download=1"
ASSET_DEST = "models/panns-cnn14.pth"

#: cooperative cancel probe + progress sink (match the rest of the codebase).
CancelProbe = Callable[[], bool]
ProgressCb = Callable[[float, str], None]


# --------------------------------------------------------------------------- #
# the shared Signal contract (one shape the Wave-2 scorer consumes uniformly)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Signal:
    """One scored observation on the shared timeline (seconds, ORIGINAL video).

    ``value`` is ALWAYS normalized to 0.0..1.0 (1.0 = maximally interesting on
    this channel); raw model outputs are squashed inside the module before
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
    """All Signals from one channel + a modality-presence flag for degrade.

    ``present=False`` is the degrade signal (silent video / no audio / model
    unavailable): the Wave-2 scorer drops the channel's weight and re-normalizes
    the survivors so a silent clip is scored on the visual channels alone.
    """

    channel: str
    signals: tuple[Signal, ...]
    present: bool
    fps_hint: float | None = None


# --------------------------------------------------------------------------- #
# the heavy backend seam (PANNs CNN14) — never imported at module load
# --------------------------------------------------------------------------- #
class PannsBackend(Protocol):
    """The slice of the PANNs CNN14 tagger the pure runner needs.

    A real impl (built lazily by :func:`_default_backend_factory`, never at
    import) returns a ``frames x 527`` matrix of AudioSet tag probabilities for
    a mono waveform. Tests inject a fake returning a hand-built array — no model,
    no weights.
    """

    def tag(self, samples: np.ndarray, sr: int) -> np.ndarray:
        """Return a ``frames x 527`` AudioSet tag-probability matrix."""
        ...  # pragma: no cover - Protocol method body is never executed


#: factory seam: default = lazy real impl; tests inject a fake.
PannsFactory = Callable[[dict[str, Any]], PannsBackend]
#: audio decode seam: path -> (mono samples float array, sample-rate). The
#: default lazily uses ffmpeg -> numpy (NO heavy dep: ffmpeg + numpy only).
AudioLoader = Callable[[str], "tuple[np.ndarray, int]"]
#: availability probe seam: are the model assets installed? (drives degrade).
ModelsPresent = Callable[[dict[str, Any]], bool]


# --------------------------------------------------------------------------- #
# pure: windowing grid (mirrors reframe_claudeshorts.window_timestamps)
# --------------------------------------------------------------------------- #
def sample_windows(
    duration: float,
    win_sec: float = 1.0,
    hop_sec: float = 1.0,
) -> tuple[tuple[float, float], ...]:
    """The shared ``(start, end)`` window grid every Phase-8 module uses.

    Windows of ``win_sec`` stepped by ``hop_sec`` across ``[0, duration)`` so
    every module aligns by window index. A non-positive duration yields one
    degenerate ``(0.0, 0.0)`` window (an empty/zero-length clip still produces a
    single aligned slot). ``win_sec`` / ``hop_sec`` are floored at a tiny
    positive epsilon so a zero/negative step can never loop forever.
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
# pure: loudness (RMS -> 0..1) — needs NO model, ALWAYS present
# --------------------------------------------------------------------------- #
def loudness_curve(
    samples: np.ndarray,
    sr: int,
    win_sec: float = 1.0,
    hop_sec: float = 1.0,
) -> list[float]:
    """Per-window RMS loudness normalized to 0..1 (pure numpy, no model).

    For each window of the shared grid, compute the RMS of the samples falling
    in it, then min-max normalize the per-window RMS sequence to 0..1 (the
    loudest window -> 1.0). A constant (or silent) track normalizes to all
    zeros — an honest "no relative loudness peak", not a fabrication. An empty
    sample buffer yields one ``0.0`` (the single degenerate window).
    """
    import numpy as np  # noqa: PLC0415 - numpy is in the venv; kept local for symmetry

    arr = np.asarray(samples, dtype=np.float64).reshape(-1)
    n = int(arr.shape[0])
    rate = max(1, int(sr))
    duration = n / rate
    windows = sample_windows(duration, win_sec, hop_sec)

    rms: list[float] = []
    for w_start, w_end in windows:
        a = int(round(w_start * rate))
        b = int(round(w_end * rate))
        chunk = arr[a:b]
        if chunk.size == 0:
            rms.append(0.0)
        else:
            rms.append(float(np.sqrt(np.mean(np.square(chunk)))))

    return _minmax_normalize(rms)


def _minmax_normalize(values: Sequence[float]) -> list[float]:
    """Min-max a sequence to 0..1; a flat/empty sequence -> all zeros."""
    import numpy as np  # noqa: PLC0415 - numpy is in the venv

    if not values:
        return []
    arr = np.asarray(values, dtype=np.float64)
    lo = float(arr.min())
    hi = float(arr.max())
    if hi <= lo:
        return [0.0 for _ in values]
    out = (arr - lo) / (hi - lo)
    return [float(clamp(v, 0.0, 1.0)) for v in out]


# --------------------------------------------------------------------------- #
# pure: per-event peak windows from a frame x 527 tag-probability matrix
# --------------------------------------------------------------------------- #
def peak_windows(
    tag_probs: np.ndarray,
    class_index: int,
    win_sec: float,
    hop_sec: float,
    *,
    channel: str = "audioSalience",
) -> list[Signal]:
    """Turn one AudioSet class's per-frame probabilities into windowed Signals.

    ``tag_probs`` is ``frames x 527``. The frames are assumed uniformly spaced
    across the clip; each window of the shared grid pools (max) the per-frame
    probability of ``class_index`` within it. The pooled probabilities are
    min-max normalized to 0..1 so the loudest event window -> 1.0, and each
    becomes a :class:`Signal` on ``channel`` carrying the raw pooled probability
    in ``meta['prob']`` and the class index in ``meta['classIndex']``. An empty
    matrix yields no signals.
    """
    import numpy as np  # noqa: PLC0415 - numpy is in the venv

    arr = np.asarray(tag_probs, dtype=np.float64)
    if arr.ndim != 2 or arr.shape[0] == 0:
        return []
    frames = int(arr.shape[0])
    col = arr[:, class_index]

    # The clip duration the frames span: one "frame" per ``hop`` so the windows
    # and frames share the same time axis (frames sampled at the hop rate).
    duration = frames * float(max(1e-6, hop_sec))
    windows = sample_windows(duration, win_sec, hop_sec)

    pooled: list[float] = []
    for w_start, w_end in windows:
        a = int(np.floor(w_start / max(1e-6, hop_sec)))
        b = int(np.ceil(w_end / max(1e-6, hop_sec)))
        a = max(0, min(a, frames))
        b = max(a + 1, min(b, frames))
        pooled.append(float(col[a:b].max()))

    normalized = _minmax_normalize(pooled)
    signals: list[Signal] = []
    for (w_start, w_end), value, raw in zip(windows, normalized, pooled, strict=True):
        signals.append(
            Signal(
                channel=channel,
                start=float(w_start),
                end=float(w_end),
                value=float(clamp(value, 0.0, 1.0)),
                confidence=float(clamp(raw, 0.0, 1.0)),
                meta={"prob": float(raw), "classIndex": int(class_index)},
            )
        )
    return signals


def _audio_salience_signals(
    tag_probs: np.ndarray,
    win_sec: float,
    hop_sec: float,
) -> list[Signal]:
    """Derived ``audioSalience`` track: per-window MAX over the event classes.

    The overall audio-interest of a window is "the most salient event happening
    in it" — so we take, per frame, the max probability across the laughter /
    applause / music classes, then window+normalize exactly like an event class.
    """
    import numpy as np  # noqa: PLC0415 - numpy is in the venv

    arr = np.asarray(tag_probs, dtype=np.float64)
    if arr.ndim != 2 or arr.shape[0] == 0:
        return []
    indices = list(AUDIOSET_CLASS_INDEX.values())
    combined = arr[:, indices].max(axis=1, keepdims=True)  # frames x 1
    # Reuse peak_windows over the single combined column (class index 0 of it).
    return peak_windows(combined, 0, win_sec, hop_sec, channel="audioSalience")


# --------------------------------------------------------------------------- #
# default heavy seams (lazy real impls; tests inject fakes)
# --------------------------------------------------------------------------- #
def _default_backend_factory(settings: dict[str, Any]) -> PannsBackend:
    """Build the real PANNs CNN14 backend (LAZY import; runtime only)."""
    from .audio_saliency_backend import (  # noqa: PLC0415 - heavy seam  # pyright: ignore[reportMissingImports]  # Wave-2 ships the backend module
        PannsCnn14Backend,
    )

    return PannsCnn14Backend(settings)


def _default_audio_loader(media_path: str) -> tuple[np.ndarray, int]:  # pragma: no cover - needs ffmpeg + a real file
    """Decode ``media_path`` to mono float samples at ``TARGET_SR`` via ffmpeg.

    Excluded from coverage: it spawns ffmpeg and reads a real media file (the
    pure logic + the seam branches are covered with a fake loader). Lives here
    (not the backend module) because it has NO heavy-ML dep — only ffmpeg+numpy.
    """
    import subprocess  # noqa: PLC0415, S404 - argv-list only, never shell=True

    import numpy as np  # noqa: PLC0415

    from .. import ffmpeg  # noqa: PLC0415 - avoids a top-level import cycle

    argv = [
        ffmpeg.ffmpeg_path(None),
        "-hide_banner",
        "-nostdin",
        "-i",
        media_path,
        "-ac",
        "1",
        "-ar",
        str(TARGET_SR),
        "-f",
        "f32le",
        "-",
    ]
    completed = subprocess.run(argv, capture_output=True, check=False)  # noqa: S603 - argv list, no shell
    raw = completed.stdout or b""
    samples = np.frombuffer(raw, dtype=np.float32).astype(np.float64)
    return samples, TARGET_SR


def default_models_present(settings: dict[str, Any]) -> bool:  # pragma: no cover - probes the asset store at runtime
    """True when the PANNs CNN14 checkpoint is installed (no heavy import).

    Excluded from coverage: it reaches into the asset manager (a runtime
    concern). The pure runner is exercised with an injected ``models_present``.
    """
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


# --------------------------------------------------------------------------- #
# the public runner
# --------------------------------------------------------------------------- #
def _absent_tracks(fps_hint: float | None) -> dict[str, SignalTrack]:
    """All TAG channels absent (degrade); loudness handled separately."""
    return {
        channel: SignalTrack(channel=channel, signals=(), present=False, fps_hint=fps_hint) for channel in TAG_CHANNELS
    }


def compute_audio_signals(
    media_path: str,
    duration: float,
    *,
    settings: dict[str, Any] | None = None,
    backend_factory: PannsFactory | None = None,
    audio_loader: AudioLoader | None = None,
    models_present: ModelsPresent | None = None,
    win_sec: float = 1.0,
    hop_sec: float = 1.0,
    on_progress: ProgressCb | None = None,
    should_cancel: CancelProbe | None = None,
) -> dict[str, SignalTrack]:
    """Compute the per-channel audio-saliency tracks for ``media_path``.

    Returns ``{channel -> SignalTrack}`` for every channel in
    :data:`AUDIO_CHANNELS`. The tag channels (audioSalience/laughter/applause/
    music) come from the PANNs tagger; ``loudness`` is pure RMS (no model).

    Degrade rules (the §3 missing-modality contract):
      * **Offline + model missing** -> the tag channels are ``present=False``
        (a download would need the network); ``loudness`` still runs.
      * **No / silent audio** (the loader returns an empty buffer) -> the tag
        channels are ``present=False``; ``loudness`` is ``present=True`` with a
        single ``0.0`` window (an honest "silence", not a fabrication).
      * **Cancelled** before tagging -> the tag channels are ``present=False``;
        whatever loudness was computed is returned.

    Never raises for a missing modality and never fabricates tag zeros.
    """
    settings = settings or {}
    factory = backend_factory or _default_backend_factory
    loader = audio_loader or _default_audio_loader
    present_probe = models_present or default_models_present
    fps_hint = 1.0 / float(max(1e-6, hop_sec))

    def _progress(pct: float, msg: str) -> None:
        if on_progress is not None:
            on_progress(clamp(pct, 0.0, 100.0), msg)

    _progress(2.0, "decoding audio")
    samples, sr = loader(media_path)

    import numpy as np  # noqa: PLC0415 - numpy is in the venv

    arr = np.asarray(samples, dtype=np.float64).reshape(-1)

    # loudness is ALWAYS present (no model) — compute it up front.
    loud_values = loudness_curve(arr, sr, win_sec, hop_sec)
    loud_windows = sample_windows(arr.shape[0] / max(1, int(sr)), win_sec, hop_sec)
    loud_signals = tuple(
        Signal(channel="loudness", start=float(w0), end=float(w1), value=float(v))
        for (w0, w1), v in zip(loud_windows, loud_values, strict=True)
    )
    loudness_track = SignalTrack(channel="loudness", signals=loud_signals, present=True, fps_hint=fps_hint)

    # No audio -> tag channels degrade (loudness already honest).
    if arr.size == 0:
        log.info("audio_saliency: no audio in %s — tag channels absent", media_path)
        tracks = _absent_tracks(fps_hint)
        tracks["loudness"] = loudness_track
        return tracks

    # Offline gate: ONLY the network path (a missing-model download) degrades.
    # Online-but-missing falls through: a real factory would download, and the
    # seam is still invoked below (tests inject a factory regardless of this).
    if not present_probe(settings) and _offline.is_offline(settings):
        log.info("audio_saliency: offline + model missing — tag channels absent")
        tracks = _absent_tracks(fps_hint)
        tracks["loudness"] = loudness_track
        return tracks

    if should_cancel is not None and should_cancel():
        tracks = _absent_tracks(fps_hint)
        tracks["loudness"] = loudness_track
        return tracks

    _progress(20.0, "tagging audio events")
    backend = factory(settings)
    tag_probs = backend.tag(arr, int(sr))

    _progress(85.0, "assembling audio signals")
    tracks: dict[str, SignalTrack] = {}
    # event channels
    for channel in ("laughter", "applause", "music"):
        signals = tuple(peak_windows(tag_probs, AUDIOSET_CLASS_INDEX[channel], win_sec, hop_sec, channel=channel))
        tracks[channel] = SignalTrack(channel=channel, signals=signals, present=True, fps_hint=fps_hint)
    # derived overall salience
    salience = tuple(_audio_salience_signals(tag_probs, win_sec, hop_sec))
    tracks["audioSalience"] = SignalTrack(channel="audioSalience", signals=salience, present=True, fps_hint=fps_hint)
    tracks["loudness"] = loudness_track

    _progress(100.0, "done")
    return tracks


# --------------------------------------------------------------------------- #
# asset registration (mirrors diarize / parakeet_asr / ctc_align)
# --------------------------------------------------------------------------- #
def register_audio_saliency_assets() -> None:
    """Register the PANNs CNN14 audio-tagging checkpoint as an on-demand asset.

    MIT (commercial OK), ~300 MB, CPU-designed. The asset name matches
    :data:`ASSET_NAME` (and ``system_advisor.ComponentSpec``'s ``audio_saliency``
    lookup key) so :func:`default_models_present` detects an already-cached
    checkpoint. Identical re-registration is a no-op (module re-import safe).
    """
    from ..assets import manifest  # noqa: PLC0415 - lazy: avoids an import cycle

    manifest.register_asset(
        manifest.AssetEntry(
            name=ASSET_NAME,
            kind="model",
            size_mb=ASSET_SIZE_MB,
            dest=ASSET_DEST,
            label="PANNs CNN14 (audio tagging, MIT)",
            installer="download",
            url=ASSET_URL,
        )
    )


# Register the asset at import (mirrors diarize.register_diarize_assets()).
register_audio_saliency_assets()


__all__ = [
    "ASSET_DEST",
    "ASSET_NAME",
    "ASSET_SIZE_MB",
    "ASSET_URL",
    "AUDIOSET_CLASS_INDEX",
    "AUDIO_CHANNELS",
    "TAG_CHANNELS",
    "TARGET_SR",
    "AudioLoader",
    "ModelsPresent",
    "PannsBackend",
    "PannsFactory",
    "Signal",
    "SignalTrack",
    "compute_audio_signals",
    "default_models_present",
    "loudness_curve",
    "peak_windows",
    "register_audio_saliency_assets",
    "sample_windows",
]
