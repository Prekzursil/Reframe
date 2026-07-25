"""BEAT-GRID cuts (Beat This!) + a beatAlignment metric + OpenTimelineIO export.

Three cohesive, mostly model-free capabilities for music-driven editing and NLE
round-tripping:

  * **Beat grid + beat-quantized cuts** — detect a music track's beats/downbeats
    with **Beat This!** (CPJKU, ISMIR 2024 — code + published weights **MIT**),
    then SNAP a set of cut points onto the nearest beat so edits land on the
    groove. The detector is the ONLY heavy part and lives behind the
    :class:`BeatThisBackend` seam; the snapping is pure.
  * **``beatAlignment`` metric** — an OBJECTIVE 0..1 score of how well a cut list
    lands on the beat grid (1.0 = every cut on a beat). This is an OBSERVE-ONLY
    metric (COUNCIL C5 shadow discipline): :func:`beat_alignment` just returns a
    number for the director/UI to surface — it NEVER blocks, nags, or re-cuts.
  * **OpenTimelineIO export** — serialize a cut list / approved clips to a valid
    ``.otio`` JSON document (the modern NLE interchange that round-trips through
    Resolve / Premiere / Flame far more faithfully than the hand-rolled CMX3600
    EDL). It consumes the SAME ``nle_export`` event shape, so it is a drop-in
    alternative exporter — no new timeline model. Hand-built JSON (the documented
    OTIO schema), so it needs NO ``opentimelineio`` runtime dependency; if that
    library (Apache-2.0) IS installed, the emitted JSON loads into it directly.

Missing-modality / degrade contract (mirrors ``audio_saliency``): the beat
detector returns an EMPTY :class:`BeatGrid` (no beats) when the model is
unavailable offline, the audio is empty, or the backend fails — never a raise.
Snapping against an empty grid is the identity (cuts pass through unchanged).
"""

from __future__ import annotations

import bisect
import json
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import TYPE_CHECKING, Any, Protocol

from ..util import clamp, get_logger
from . import nle_export as _nle
from . import offline as _offline

if TYPE_CHECKING:
    import numpy as np

log = get_logger("media_studio.features.beatgrid")

Span = tuple[float, float]
CancelProbe = Callable[[], bool]
ProgressCb = Callable[[float, str], None]

#: Beat This! model metadata (MIT). Weights ship on the CPJKU GitHub releases
#: (``final0.ckpt``), NOT a floating HF branch — so the asset is registered by an
#: OWNER-called helper that supplies a VERIFIED pin (F3c forbids fabricating one).
BEAT_THIS_LABEL = "Beat This! beat/downbeat tracker (MIT)"
BEAT_THIS_ASSET_NAME = "beat-this"
BEAT_THIS_SIZE_MB = 90
#: PANNs-style target rate hint for the detector's audio frontend (22.05 kHz).
DEFAULT_SR = 22050


# --------------------------------------------------------------------------- #
# the beat grid + the heavy detector seam (Beat This!) — lazy
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class BeatGrid:
    """Detected beats + downbeats (seconds, ascending) and an optional tempo.

    ``beats`` are every beat; ``downbeats`` are the subset that start a bar.
    ``bpm`` is a convenience tempo estimate (``None`` when unknown / too few
    beats). An empty grid (no beats) is the degrade result and the identity for
    snapping.
    """

    beats: tuple[float, ...] = ()
    downbeats: tuple[float, ...] = ()
    bpm: float | None = None

    def is_empty(self) -> bool:
        """True when no beats were detected (the degrade / no-op grid)."""
        return not self.beats


class BeatThisBackend(Protocol):
    """The slice of Beat This! the pure logic needs.

    A real impl (built lazily by :func:`_default_backend_factory`, never at
    import) runs the tracker over mono ``samples`` and returns a
    :class:`BeatGrid`. Tests inject a fake returning a hand-built grid — no torch,
    no model, no network.
    """

    def detect(
        self,
        samples: np.ndarray,
        sr: int,
        *,
        on_progress: ProgressCb | None = None,
        should_cancel: CancelProbe | None = None,
    ) -> BeatGrid:
        """Return the detected :class:`BeatGrid` for ``samples``."""
        ...  # pragma: no cover - Protocol method body is never executed


BackendFactory = Callable[[dict[str, Any]], BeatThisBackend]
AudioLoader = Callable[[str], "tuple[np.ndarray, int]"]
ModelsPresent = Callable[[dict[str, Any]], bool]
#: ``importlib.util.find_spec`` seam: module name -> spec | ``None`` (no import).
SpecFn = Callable[[str], object | None]

#: the sibling module that ships the REAL Beat This! tracker. It is NOT part of
#: the pure build: when it is absent beat DETECTION is unavailable (the pure
#: snapping / metric / OTIO halves keep working against an empty grid).
BACKEND_MODULE = "media_studio.features.beatgrid_backend"


class BeatThisBackendUnavailableError(RuntimeError):
    """:data:`BACKEND_MODULE` (the real Beat This! tracker) is not importable.

    A SETUP/PROVISIONING failure, NOT a per-clip event: without that module no
    beat grid can be detected at all. Raised TYPED and actionable — mirroring
    ``diarize_backend.DiarizeBackendUnavailableError`` — so :func:`detect_beats`
    degrades on a NAMED cause instead of a raw :class:`ModuleNotFoundError`. The
    pure snapping / :func:`beat_alignment` / OTIO export need no model.
    """


def _default_find_spec(module_name: str) -> object | None:
    """Lazy ``importlib.util.find_spec`` (kept behind a seam for testing)."""
    import importlib.util  # noqa: PLC0415 - stdlib, lazy for symmetry with peers

    return importlib.util.find_spec(module_name)


def backend_available(*, find_spec: SpecFn | None = None) -> bool:
    """True when :data:`BACKEND_MODULE` is IMPORTABLE — WITHOUT importing it.

    Uses ``importlib.util.find_spec`` behind an injectable seam (mirroring
    ``health`` / ``self_test`` / ``system_advisor``) so answering "can this
    feature run at all?" never loads a heavy dependency. A probe failure (a
    broken / partial install) reports ABSENT — the honest answer for a feature
    that cannot run.
    """
    spec_fn = find_spec or _default_find_spec
    try:
        return spec_fn(BACKEND_MODULE) is not None
    except (ImportError, ValueError):  # a broken/partial install probes as absent
        return False


# --------------------------------------------------------------------------- #
# pure: tempo, nearest-beat, snapping, and the alignment metric
# --------------------------------------------------------------------------- #
def estimate_bpm(beats: Sequence[float]) -> float | None:
    """Median-interval BPM estimate from ascending beat times (``None`` if < 2)."""
    ordered = sorted(float(b) for b in beats)
    intervals = [b - a for a, b in zip(ordered, ordered[1:], strict=False) if b > a]
    if not intervals:
        return None
    med = median(intervals)
    return round(60.0 / med, 2) if med > 0 else None


def nearest_beat(time: float, beats: Sequence[float]) -> float | None:
    """The beat closest to ``time`` (``None`` for an empty grid).

    ``beats`` MUST be ascending (a detected grid always is). Uses a binary search
    so a long grid stays O(log n) per query.
    """
    if not beats:
        return None
    ordered = list(beats)
    t = float(time)
    pos = bisect.bisect_left(ordered, t)
    if pos == 0:
        return float(ordered[0])
    if pos == len(ordered):
        return float(ordered[-1])
    before, after = float(ordered[pos - 1]), float(ordered[pos])
    return before if (t - before) <= (after - t) else after


def snap_times_to_beats(
    times: Sequence[float],
    beats: Sequence[float],
    *,
    max_shift_sec: float | None = None,
) -> list[float]:
    """Snap each cut in ``times`` to its nearest beat.

    When ``max_shift_sec`` is given, a cut whose nearest beat is farther than that
    is KEPT unsnapped (so a cut deliberately off-grid is not yanked onto a distant
    beat). An empty ``beats`` grid is the identity (every cut passes through). The
    result preserves input order and is rounded to ms.
    """
    ordered_beats = sorted(float(b) for b in beats)
    out: list[float] = []
    for t in times:
        t = float(t)
        beat = nearest_beat(t, ordered_beats)
        if beat is None or (max_shift_sec is not None and abs(beat - t) > float(max_shift_sec)):
            out.append(round(t, 3))
        else:
            out.append(round(beat, 3))
    return out


def beat_alignment(times: Sequence[float], beats: Sequence[float]) -> float:
    """OBJECTIVE 0..1 score of how well ``times`` (cuts) land on the beat grid.

    For each cut, its distance to the nearest beat is normalized by HALF the
    median beat interval (the natural tolerance — a cut within half a beat of the
    grid is "on"), clamped to 1, and 1 minus the mean is returned. 1.0 = every cut
    on a beat, 0.0 = every cut a half-beat-or-more off. Returns 1.0 for NO cuts
    (nothing is misaligned) and 0.0 when the grid has < 2 beats (no interval to
    judge against). OBSERVE-ONLY — this reports, it never gates.
    """
    ordered_beats = sorted(float(b) for b in beats)
    if not times:
        return 1.0
    if len(ordered_beats) < 2:
        return 0.0
    intervals = [b - a for a, b in zip(ordered_beats, ordered_beats[1:], strict=False) if b > a]
    half = (median(intervals) / 2.0) if intervals else 0.0
    if half <= 0.0:
        return 0.0
    penalties = []
    for t in times:
        beat = nearest_beat(float(t), ordered_beats)
        dist = abs(float(beat) - float(t)) if beat is not None else half
        penalties.append(min(1.0, dist / half))
    return round(clamp(1.0 - (sum(penalties) / len(penalties)), 0.0, 1.0), 4)


# --------------------------------------------------------------------------- #
# default heavy seams (lazy real impls; tests inject fakes)
# --------------------------------------------------------------------------- #
def _default_backend_factory(settings: dict[str, Any]) -> BeatThisBackend:  # pragma: no cover - prod seam
    """Build the real Beat This! backend (LAZY import; runtime only).

    Raises :class:`BeatThisBackendUnavailableError` when :data:`BACKEND_MODULE`
    is not part of this build — never a raw :class:`ModuleNotFoundError`.
    """
    try:
        from .beatgrid_backend import RealBeatThisBackend  # noqa: PLC0415 - heavy seam
    except ImportError as exc:
        raise BeatThisBackendUnavailableError(
            f"beat detection requires the {BACKEND_MODULE} module (the Beat This! "
            "tracker), which is not part of this build; the beat grid is UNAVAILABLE "
            "(beat snapping, beatAlignment and the OTIO export still work)"
        ) from exc

    return RealBeatThisBackend(settings)


def _default_audio_loader(media_path: str) -> tuple[np.ndarray, int]:  # pragma: no cover - needs ffmpeg + a real file
    """Decode ``media_path`` to mono float samples at 22.05 kHz via ffmpeg."""
    import subprocess  # noqa: PLC0415, S404 - argv-list only, never shell=True

    from .. import ffmpeg  # noqa: PLC0415 - avoids a top-level import cycle
    from .ctc_align import _decode_pcm_or_raise  # noqa: PLC0415 - reuse the tested decoder

    argv = [
        ffmpeg.ffmpeg_path(None),
        "-hide_banner",
        "-nostdin",
        "-i",
        media_path,
        "-ac",
        "1",
        "-ar",
        str(DEFAULT_SR),
        "-f",
        "f32le",
        "-",
    ]
    completed = subprocess.run(argv, capture_output=True, check=False)  # noqa: S603 - argv list, no shell
    return _decode_pcm_or_raise(completed.returncode, completed.stdout, completed.stderr, target_sr=DEFAULT_SR)


def default_models_present(settings: dict[str, Any]) -> bool:  # pragma: no cover - probes the asset store
    """True when the Beat This! backend module AND its asset are BOTH installed.

    An installed checkpoint alone is NOT enough: without :data:`BACKEND_MODULE`
    the tracker can never run, so a missing backend module reports ABSENT — the
    UI then shows the feature as unavailable instead of appearing ready.
    """
    if not backend_available():
        return False
    try:
        from ..assets import manifest  # noqa: PLC0415
        from ..assets.manager import AssetManager  # noqa: PLC0415

        entry = manifest.get_asset(BEAT_THIS_ASSET_NAME)
        if entry is None:
            return False
        mgr = AssetManager(settings_provider=lambda: settings)
        return mgr.installed_path(entry) is not None
    except Exception:  # noqa: BLE001 - any probe failure -> treat as absent
        return False


# --------------------------------------------------------------------------- #
# the public detector runner
# --------------------------------------------------------------------------- #
def detect_beats(
    audio_path: str,
    *,
    settings: dict[str, Any] | None = None,
    backend_factory: BackendFactory | None = None,
    audio_loader: AudioLoader | None = None,
    models_present: ModelsPresent | None = None,
    on_progress: ProgressCb | None = None,
    should_cancel: CancelProbe | None = None,
) -> BeatGrid:
    """Detect the :class:`BeatGrid` of ``audio_path`` (Beat This!).

    Degrade paths (each returns an EMPTY grid, never raises):
      * offline AND the model asset (or :data:`BACKEND_MODULE`) is not installed;
      * a cooperative cancel before detection, an audio-decode failure, or an
        empty audio buffer;
      * any backend failure — including :class:`BeatThisBackendUnavailableError`
        when the backend module is absent from this build.
    A returned grid always carries a ``bpm`` estimate when >= 2 beats were found.
    """
    settings = settings or {}
    factory = backend_factory or _default_backend_factory
    loader = audio_loader or _default_audio_loader
    present = models_present or default_models_present

    def _progress(pct: float, msg: str) -> None:
        if on_progress is not None:
            on_progress(clamp(pct, 0.0, 100.0), msg)

    if not present(settings) and _offline.is_offline(settings):
        log.info("beatgrid: offline + model missing — empty grid")
        return BeatGrid()
    if should_cancel is not None and should_cancel():
        return BeatGrid()

    _progress(5.0, "decoding audio")
    try:
        samples, sr = loader(audio_path)
    except Exception as exc:  # noqa: BLE001 - a decode failure must not crash the pipeline
        log.warning("beatgrid: audio decode failed for %s: %s", audio_path, exc)
        return BeatGrid()

    import numpy as np  # noqa: PLC0415 - numpy is in the venv

    arr = np.asarray(samples, dtype=np.float64).reshape(-1)
    if arr.size == 0:
        return BeatGrid()

    _progress(20.0, "tracking beats (Beat This!)")
    try:
        backend = factory(settings)
        grid = backend.detect(
            arr,
            int(sr),
            on_progress=lambda pct, msg: _progress(clamp(pct, 20.0, 95.0), msg),
            should_cancel=should_cancel,
        )
    except Exception as exc:  # noqa: BLE001 - a detection failure must not crash the pipeline
        log.warning("beatgrid: detection failed for %s: %s", audio_path, exc)
        return BeatGrid()

    beats = tuple(round(float(b), 3) for b in sorted(grid.beats))
    downbeats = tuple(round(float(b), 3) for b in sorted(grid.downbeats))
    bpm = grid.bpm if grid.bpm is not None else estimate_bpm(beats)
    _progress(100.0, "done")
    return BeatGrid(beats=beats, downbeats=downbeats, bpm=bpm)


# --------------------------------------------------------------------------- #
# OpenTimelineIO export (hand-built .otio JSON — no runtime dep)
# --------------------------------------------------------------------------- #
def _rational_time(value: float, rate: float) -> dict[str, Any]:
    return {"OTIO_SCHEMA": "RationalTime.1", "rate": float(rate), "value": float(value)}


def _time_range(start_value: float, duration_value: float, rate: float) -> dict[str, Any]:
    return {
        "OTIO_SCHEMA": "TimeRange.1",
        "start_time": _rational_time(start_value, rate),
        "duration": _rational_time(duration_value, rate),
    }


def _target_url(path: str) -> str:
    """A ``file://`` URL for an absolute path (raw string for empty/relative)."""
    if not path:
        return ""
    try:
        p = Path(path)
        return p.as_uri() if p.is_absolute() else path
    except (ValueError, OSError):
        return path


def _event_to_clip(event: dict[str, Any], fps: int) -> dict[str, Any]:
    """One ``nle_export`` EDLEvent -> an OTIO ``Clip.1`` (source_range + media ref)."""
    src_in = int(event.get("sourceInFrames", 0))
    src_out = int(event.get("sourceOutFrames", src_in))
    length = max(1, src_out - src_in)
    path = str(event.get("sourcePath") or "")
    return {
        "OTIO_SCHEMA": "Clip.1",
        "name": str(event.get("clipName") or f"clip{event.get('index', '')}"),
        "source_range": _time_range(src_in, length, fps),
        "media_reference": {
            "OTIO_SCHEMA": "ExternalReference.1",
            "target_url": _target_url(path),
            "available_range": None,
        },
        "metadata": {"hook": str(event.get("hook") or "")} if event.get("hook") else {},
    }


def build_otio_timeline(
    events: Sequence[dict[str, Any]],
    *,
    name: str = "Media Studio Timeline",
    fps: Any = 30,
) -> dict[str, Any]:
    """Build an OpenTimelineIO ``Timeline.1`` from ``nle_export`` EDL events.

    The events (from :func:`nle_export.clips_to_events`) become a single Video
    track of contiguous clips — the same rough cut the EDL lays down, but in the
    richer OTIO model that round-trips cleanly through modern NLEs. Returns the
    plain-dict OTIO document (``json.dumps``-able); no ``opentimelineio`` dep.
    """
    rate = _nle.normalize_fps(fps)
    clips = [_event_to_clip(ev, rate) for ev in events]
    track = {"OTIO_SCHEMA": "Track.1", "name": "V1", "kind": "Video", "children": clips, "metadata": {}}
    stack = {"OTIO_SCHEMA": "Stack.1", "name": "tracks", "children": [track], "metadata": {}}
    return {
        "OTIO_SCHEMA": "Timeline.1",
        "name": str(name or "Media Studio Timeline"),
        "global_start_time": None,
        "tracks": stack,
        "metadata": {"generator": "media_studio.beatgrid", "fps": rate},
    }


def serialize_otio(timeline: dict[str, Any]) -> str:
    """Serialize an OTIO timeline dict to pretty JSON text (the ``.otio`` body)."""
    return json.dumps(timeline, ensure_ascii=False, indent=2) + "\n"


def beat_cuts_to_events(
    cut_times: Sequence[float],
    *,
    source_path: str,
    fps: Any = 30,
    total_sec: float | None = None,
) -> list[dict[str, Any]]:
    """Turn beat-snapped CUT boundaries into contiguous ``nle_export`` EDL events.

    ``cut_times`` are the cut boundaries within ONE source; the segments BETWEEN
    consecutive boundaries become clips (source window == record window, laid
    back-to-back). A leading ``0.0`` is implied and ``total_sec`` (when given)
    closes the final segment. Empty / single-boundary input yields ``[]``. The
    output feeds :func:`build_otio_timeline` (or ``nle_export.build_edl``).
    """
    f = _nle.normalize_fps(fps)
    bounds = sorted({round(max(0.0, float(t)), 3) for t in cut_times})
    if bounds and bounds[0] > 0.0:
        bounds = [0.0, *bounds]
    if total_sec is not None and (not bounds or bounds[-1] < float(total_sec)):
        bounds.append(round(float(total_sec), 3))
    events: list[dict[str, Any]] = []
    record_cursor = 0
    for i, (a, b) in enumerate(zip(bounds, bounds[1:], strict=False), start=1):
        src_in = _nle.seconds_to_frames(a, f)
        src_out = _nle.seconds_to_frames(b, f)
        length = max(1, src_out - src_in)
        src_out = src_in + length
        events.append(
            {
                "index": i,
                "reel": _nle.sanitize_reel(f"AX{i if i > 1 else ''}"),
                "clipName": f"beatcut{i}",
                "sourcePath": source_path,
                "sourceInFrames": src_in,
                "sourceOutFrames": src_out,
                "recordInFrames": record_cursor,
                "recordOutFrames": record_cursor + length,
                "durationSec": round(length / f, 3),
                "hook": "",
                "fps": f,
            }
        )
        record_cursor += length
    return events


def export_otio(
    clips: Sequence[dict[str, Any]],
    out_path: str | os.PathLike,
    *,
    fps: Any = 30,
    name: str = "Media Studio Timeline",
) -> str:
    """Build an ``.otio`` from approved ``Project.clips`` and write it -> the path.

    Mirrors :func:`nle_export.export`: derives events via
    :func:`nle_export.clips_to_events`, builds the OTIO timeline, and writes the
    JSON. Empty ``clips`` still writes a valid (empty-track) timeline the NLE opens.
    """
    rate = _nle.normalize_fps(fps)
    events = _nle.clips_to_events(clips, rate)
    timeline = build_otio_timeline(events, name=name, fps=rate)
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(serialize_otio(timeline), encoding="utf-8")
    return str(path)


def export_beat_cuts_otio(
    cut_times: Sequence[float],
    out_path: str | os.PathLike,
    *,
    source_path: str,
    fps: Any = 30,
    total_sec: float | None = None,
    name: str = "Beat Cut Timeline",
) -> str:
    """Write a beat-snapped cut list to an ``.otio`` document -> the path."""
    events = beat_cuts_to_events(cut_times, source_path=source_path, fps=fps, total_sec=total_sec)
    timeline = build_otio_timeline(events, name=name, fps=fps)
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(serialize_otio(timeline), encoding="utf-8")
    return str(path)


# --------------------------------------------------------------------------- #
# asset registration — OWNER-called with a verified pin (F3c: no fabricated hash)
# --------------------------------------------------------------------------- #
def register_beat_this_assets(*, url: str, sha256: str, size_mb: float = BEAT_THIS_SIZE_MB) -> None:
    """Register the Beat This! checkpoint as a pinned download asset.

    NOT auto-called at import: Beat This!'s ``final0.ckpt`` ships on the CPJKU
    GitHub releases (not a floating HF branch), so the OWNER supplies the verified
    pinned ``url`` + ``sha256`` during wiring (F3c forbids a fabricated hash). The
    pure beat/OTIO logic needs no model, so nothing here blocks on the asset.
    Example::

        register_beat_this_assets(
            url="https://github.com/CPJKU/beat_this/releases/download/v0.0.4/final0.ckpt",
            sha256="<verified 64-hex digest>",
        )
    """
    from ..assets import manifest  # noqa: PLC0415 - lazy: avoids an import cycle

    manifest.register_asset(
        manifest.AssetEntry(
            name=BEAT_THIS_ASSET_NAME,
            kind="model",
            size_mb=size_mb,
            label=BEAT_THIS_LABEL,
            tier="optional",
            why="Music beat/downbeat grid for beat-quantized cuts + the beatAlignment metric.",
            installer="download",
            url=url,
            sha256=sha256,
        )
    )


__all__ = [
    "BACKEND_MODULE",
    "BEAT_THIS_ASSET_NAME",
    "BEAT_THIS_LABEL",
    "BEAT_THIS_SIZE_MB",
    "DEFAULT_SR",
    "AudioLoader",
    "BackendFactory",
    "BeatGrid",
    "BeatThisBackend",
    "BeatThisBackendUnavailableError",
    "ModelsPresent",
    "SpecFn",
    "backend_available",
    "beat_alignment",
    "beat_cuts_to_events",
    "build_otio_timeline",
    "detect_beats",
    "estimate_bpm",
    "export_beat_cuts_otio",
    "export_otio",
    "nearest_beat",
    "register_beat_this_assets",
    "serialize_otio",
    "snap_times_to_beats",
]
