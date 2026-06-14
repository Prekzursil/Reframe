"""Waveform peaks for the timeline subtitle editor (P2 ADDENDUM A2, T1).

Method (name FROZEN by A2):

  - ``timeline.peaks({videoId})`` -> ``{sampleRate:int, peaks:[float 0..1]}``
    (cached; invalidated by source mtime/path)

Pipeline: decode the FIRST audio stream with ffmpeg (s16le, mono, 8 kHz) into
a **temp file** — the run goes through :func:`media_studio.ffmpeg.run`, whose
stdout carries only the ``-progress`` stream and whose stderr is drained on a
daemon thread (A6 lesson 2: never Popen a PIPE you don't read; routing the PCM
through a temp file keeps the bulk payload off the pipes entirely). The PCM is
then downsampled to ~:data:`TARGET_BUCKETS` peak-abs buckets normalized 0..1.

Cache: ``%APPDATA%/media-studio/peaks/<videoId>.json`` (same config root the
settings store resolves). The JSON embeds ``sourcePath`` + ``sourceMtimeNs``;
a changed/moved/re-encoded source mismatches and triggers a rebuild (A2:
"invalidated by source mtime/path"). The cache HIT path does no subprocess
work at all — a 1-hour file answers from cache in milliseconds.

Heavy seams are injectable exactly like the sibling features (media_compat):
``resolver`` (videoId -> path), ``settings_provider`` (ffmpeg resolution),
``run`` (the ffmpeg runner) and ``peaks_dir`` — tests never spawn a process.
argv lists only (A6 lesson 4). No native modules are imported (nothing to
pre-import per A6 lesson 1). ``timeline.peaks`` is a DIRECT-RETURN method per
A2 (no jobId), so failures surface as structured RpcErrors on the call itself
(the job.done error-payload rule in A6 lesson 3 applies to long jobs only).
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from array import array
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .. import ffmpeg, protocol
from ..protocol import ErrorCode, RpcContext, RpcError
from ..settings_store import default_config_dir
from ..util import get_logger

log = get_logger("media_studio.timeline")

# Decode parameters: mono 8 kHz s16le is plenty for a visual waveform and keeps
# a 1-hour decode at ~57 MB of PCM / a few seconds of ffmpeg time.
SAMPLE_RATE = 8000
# CONTRACT-NOTE: the unit contract says "~2000 buckets"; exactly 2000 chosen.
TARGET_BUCKETS = 2000

# Injectable run seam: mirrors ffmpeg.run(argv, total_sec=..., ...) -> exit code.
RunFn = Callable[..., int]
# A library-style resolver: videoId -> absolute path (or None when unknown).
Resolver = Callable[[str], Optional[str]]


def _invalid(message: str) -> RpcError:
    return RpcError(message, ErrorCode.INVALID_PARAMS)


def _require_str(params: Dict[str, Any], key: str) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value:
        raise _invalid(f"{key} (str) is required")
    return value


# --------------------------------------------------------------------------- #
# pure: cache paths
# --------------------------------------------------------------------------- #
def default_peaks_dir() -> Path:
    """``%APPDATA%/media-studio/peaks`` (same root the settings store uses)."""
    return default_config_dir() / "peaks"


def _safe_cache_key(video_id: str) -> str:
    """Sanitize a videoId for use as a filename component (no traversal)."""
    key = "".join(ch for ch in video_id if ch.isalnum() or ch in "-_")
    return key or "video"


def peaks_cache_path(peaks_dir: str | os.PathLike, video_id: str) -> Path:
    """The cache file for ``video_id`` (``<peaksDir>/<videoId>.json``).

    Unlike the proxy cache the filename is mtime-free (the unit contract pins
    ``<videoId>.json``); the source mtime/path live INSIDE the JSON and are
    compared on read — a mismatch is a miss and the rebuild overwrites in place
    (self-evicting, never more than one file per video).
    """
    return Path(peaks_dir) / f"{_safe_cache_key(video_id)}.json"


# --------------------------------------------------------------------------- #
# pure: ffmpeg argv builder
# --------------------------------------------------------------------------- #
def build_peaks_argv(
    in_path: str, out_path: str, settings: Optional[Dict[str, Any]] = None
) -> List[str]:
    """ffmpeg argv decoding the first audio stream to raw s16le mono 8 kHz.

    Output goes to ``out_path`` (a temp FILE — the PCM payload never rides a
    pipe); ``-progress pipe:1 -nostats`` keeps stdout as the small key=value
    progress stream :func:`ffmpeg.run` already knows how to drain.
    """
    return [
        ffmpeg.ffmpeg_path(settings),
        "-hide_banner", "-nostdin", "-y",
        "-i", in_path,
        "-vn", "-sn", "-dn",
        "-map", "0:a:0",
        "-ac", "1",
        "-ar", str(SAMPLE_RATE),
        "-f", "s16le",
        "-progress", "pipe:1", "-nostats",
        out_path,
    ]


# --------------------------------------------------------------------------- #
# pure: downsample (the math under test)
# --------------------------------------------------------------------------- #
def peaks_from_pcm(pcm: bytes, buckets: int = TARGET_BUCKETS) -> List[float]:
    """Downsample raw s16le PCM to ``buckets`` peak-abs values in 0..1.

    Bucket ``i`` spans samples ``[i*n//buckets, (i+1)*n//buckets)`` — integer
    boundary math distributes a non-divisible sample count evenly (bucket sizes
    differ by at most 1) and covers every sample exactly once. The bucket value
    is ``max(|sample|) / 32768`` (so a full-scale -32768 maps to exactly 1.0).
    Fewer samples than buckets yields one bucket per sample (len <= buckets —
    the array length is the UI's bucket count, never padded). A trailing odd
    byte is ignored; empty/no-audio PCM yields ``[]``.
    """
    if buckets <= 0:
        raise ValueError(f"buckets must be positive, got {buckets}")
    usable = len(pcm) - (len(pcm) % 2)
    if usable <= 0:
        return []
    samples = array("h")
    samples.frombytes(pcm[:usable])
    if sys.byteorder == "big":  # pragma: no cover - s16le on a big-endian host
        samples.byteswap()
    n = len(samples)
    count = min(buckets, n)
    peaks: List[float] = []
    for i in range(count):
        lo = i * n // count
        hi = (i + 1) * n // count
        seg = samples[lo:hi]
        # max(|x|) without a per-sample Python loop: max() and min() over an
        # array slice run at C speed; |min| covers the negative extreme.
        peak = max(max(seg), -min(seg))
        peaks.append(min(peak / 32768.0, 1.0))
    return peaks


# --------------------------------------------------------------------------- #
# the feature service
# --------------------------------------------------------------------------- #
class Timeline:
    """Owns the peaks decode + cache behind ``timeline.peaks``.

    All heavy seams are injected: ``resolver`` (videoId -> path),
    ``settings_provider`` (for ffmpeg resolution) and ``run`` (the ffmpeg
    runner). ``peaks_dir`` is overridable so tests use a tmp dir instead of
    %APPDATA%.
    """

    def __init__(
        self,
        *,
        resolver: Resolver,
        settings_provider: Optional[Callable[[], Dict[str, Any]]] = None,
        peaks_dir: Optional[str | os.PathLike] = None,
        run: Optional[RunFn] = None,
        buckets: int = TARGET_BUCKETS,
    ) -> None:
        self._resolver = resolver
        self._settings_provider = settings_provider or (lambda: {})
        self._peaks_dir = (
            Path(peaks_dir) if peaks_dir is not None else default_peaks_dir()
        )
        self._run: RunFn = run or ffmpeg.run
        self._buckets = int(buckets)

    # -- internals ---------------------------------------------------------
    def _settings(self) -> Dict[str, Any]:
        try:
            return dict(self._settings_provider() or {})
        except Exception:  # noqa: BLE001 - settings must never break the decode
            return {}

    def _resolve(self, video_id: str) -> str:
        path = self._resolver(video_id)
        if not path:
            raise _invalid(f"unknown video: {video_id}")
        return str(path)

    def _read_cache(
        self, video_id: str, in_path: str, mtime_ns: int
    ) -> Optional[Dict[str, Any]]:
        """The cached ``{sampleRate, peaks}`` if it matches (path, mtime)."""
        cache_file = peaks_cache_path(self._peaks_dir, video_id)
        if not cache_file.exists():
            return None
        try:
            data = json.loads(cache_file.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return None  # corrupt/unreadable cache = miss, rebuild overwrites
        if not isinstance(data, dict):
            return None
        if data.get("sourceMtimeNs") != mtime_ns or data.get("sourcePath") != in_path:
            return None  # source changed or moved -> invalidated
        peaks = data.get("peaks")
        rate = data.get("sampleRate")
        if not isinstance(peaks, list) or not isinstance(rate, int):
            return None
        return {"sampleRate": rate, "peaks": peaks}

    def _write_cache(
        self, video_id: str, in_path: str, mtime_ns: int, result: Dict[str, Any]
    ) -> None:
        """Atomically persist the cache JSON (temp file + os.replace)."""
        cache_file = peaks_cache_path(self._peaks_dir, video_id)
        payload = {
            "sampleRate": result["sampleRate"],
            "peaks": result["peaks"],
            "sourcePath": in_path,
            "sourceMtimeNs": mtime_ns,
        }
        tmp = cache_file.with_name(cache_file.name + ".tmp")
        try:
            tmp.write_text(json.dumps(payload), encoding="utf-8")
            os.replace(tmp, cache_file)
        except OSError as exc:  # pragma: no cover - best-effort cache
            log.warning("peaks cache write failed for %s: %s", video_id, exc)
            tmp.unlink(missing_ok=True)

    def _decode_pcm(self, in_path: str, settings: Dict[str, Any]) -> bytes:
        """Decode the first audio stream to raw PCM via a temp file."""
        self._peaks_dir.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            prefix="peaks-", suffix=".pcm", dir=str(self._peaks_dir)
        )
        os.close(fd)  # ffmpeg (re)writes the path itself (-y)
        try:
            argv = build_peaks_argv(in_path, tmp_name, settings)
            code = self._run(argv, total_sec=0.0)
            if code != 0:
                raise RpcError(
                    f"ffmpeg exited with code {code} decoding audio peaks for "
                    f"{in_path} (no decodable audio stream?)",
                    ErrorCode.INTERNAL_ERROR,
                )
            return Path(tmp_name).read_bytes()
        finally:
            try:
                os.unlink(tmp_name)
            except OSError:  # pragma: no cover - best-effort temp cleanup
                pass

    # -- timeline.peaks ------------------------------------------------------
    def peaks(self, params: Dict[str, Any], ctx: RpcContext) -> Dict[str, Any]:
        """``timeline.peaks({videoId})`` -> ``{sampleRate, peaks}`` (A2).

        Direct-return. Cache hit = read one JSON file (no subprocess);
        otherwise decode + downsample + cache, then return.

        CONTRACT-NOTE: A2 does not define ``sampleRate``'s semantics; here it
        is the PCM rate the peaks were computed FROM (8000). The peaks span the
        audio uniformly, so the UI maps bucket i -> time as
        ``i / len(peaks) * durationSec`` (duration comes from the Video row).
        """
        video_id = _require_str(params, "videoId")
        in_path = self._resolve(video_id)
        try:
            mtime_ns = os.stat(in_path).st_mtime_ns
        except OSError as exc:
            raise _invalid(f"source file not found: {in_path} ({exc})") from exc

        cached = self._read_cache(video_id, in_path, mtime_ns)
        if cached is not None:
            return cached

        pcm = self._decode_pcm(in_path, self._settings())
        result: Dict[str, Any] = {
            "sampleRate": SAMPLE_RATE,
            "peaks": peaks_from_pcm(pcm, self._buckets),
        }
        self._write_cache(video_id, in_path, mtime_ns, result)
        return result


# --------------------------------------------------------------------------- #
# registration (the wiring agent calls this from handlers.register_all)
# --------------------------------------------------------------------------- #
def register(
    *,
    resolver: Resolver,
    settings_provider: Optional[Callable[[], Dict[str, Any]]] = None,
    peaks_dir: Optional[str | os.PathLike] = None,
    run: Optional[RunFn] = None,
    buckets: int = TARGET_BUCKETS,
    register_fn: Optional[Callable[[str, Any], None]] = None,
) -> Timeline:
    """Create a :class:`Timeline` and register ``timeline.peaks`` imperatively.

    ``register_fn`` defaults to :func:`protocol.register` (duplicate names fail
    loudly); tests inject a fake registrar. Returns the service so the caller
    can hold/inspect it.
    """
    service = Timeline(
        resolver=resolver,
        settings_provider=settings_provider,
        peaks_dir=peaks_dir,
        run=run,
        buckets=buckets,
    )
    reg = register_fn if register_fn is not None else protocol.register
    reg("timeline.peaks", service.peaks)
    return service


__all__ = [
    "SAMPLE_RATE",
    "TARGET_BUCKETS",
    "Timeline",
    "build_peaks_argv",
    "default_peaks_dir",
    "peaks_cache_path",
    "peaks_from_pcm",
    "register",
]
