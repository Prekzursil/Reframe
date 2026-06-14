"""Media playability verdict + playback-proxy feature (P2 ADDENDUM A2, U1).

Methods (names FROZEN by A2):

  - ``media.playable({videoId})``    -> ``{playable:bool, reason?, proxyPath?}``
  - ``media.proxy.start({videoId})`` -> ``{jobId}`` -> ``job.done`` ``{path}``

The verdict tree is **codec-driven, not container-driven** (PLAN-P2 U1):

  1. ffprobe sniff (``-show_streams -show_format -of json``);
  2. every video/audio stream Chromium-playable AND the container directly
     playable                      -> ``playable`` (play the original);
  3. every stream playable but the container is not (e.g. h264-in-MKV)
                                   -> ``remux`` (``-c copy`` into mp4 — cheap);
  4. ANY stream unplayable (HEVC/WMV/MPEG-2/...; including HEVC inside MKV)
                                   -> ``proxy`` (h264 720p transcode).

Both derivatives are produced by the ``media.proxy.start`` job and cached in
``%APPDATA%/media-studio/proxies`` keyed by **videoId + source mtime** — a
re-downloaded/edited source invalidates the cache automatically. While the
proxy plays, all operations (convert/burn/export) keep using the ORIGINAL.

Heavy work stays behind the same seams the other features use: the ffprobe
``runner`` and the ffmpeg ``run`` are injectable, so tests never spawn a real
process. ``ffmpeg.run`` already drains stderr on a thread (A6 lesson 2) and is
reused as-is; failures surface through the job.done error payload (A6 lesson
3) because the job body raises on a non-zero exit. argv lists only (A6 lesson
4). No new native modules are imported (nothing to pre-import per A6 lesson 1).
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .. import ffmpeg, protocol
from ..jobs import JobContext
from ..protocol import ErrorCode, RpcContext, RpcError
from ..settings_store import default_config_dir
from ..util import get_logger

log = get_logger("media_studio.media_compat")

# --------------------------------------------------------------------------- #
# verdicts + playability tables
# --------------------------------------------------------------------------- #
VERDICT_PLAYABLE = "playable"
VERDICT_REMUX = "remux"
VERDICT_PROXY = "proxy"

# CONTRACT-NOTE: A2 freezes the method shapes, not the codec tables. These are
# the codecs Chromium (Electron's renderer) decodes without licensing gaps —
# hevc/wmv/mpeg2 are deliberately absent (the A2 examples of proxy-needing
# streams). pcm_* covers the WAV/PCM family.
PLAYABLE_VIDEO_CODECS = frozenset({"h264", "vp8", "vp9", "av1"})
PLAYABLE_AUDIO_CODECS = frozenset({"aac", "mp3", "opus", "vorbis", "flac"})
_PLAYABLE_AUDIO_PREFIXES: Tuple[str, ...] = ("pcm_",)

# Container families whose ffprobe format_name tokens are directly playable.
_PLAYABLE_CONTAINER_TOKENS = frozenset({"mp4", "m4a", "mov", "3gp", "ogg", "mp3", "wav", "flac"})

# Injectable seams (tests stub these so no subprocess ever runs):
#   ProbeFn mirrors probe_media(path, settings) -> dict
#   RunFn   mirrors ffmpeg.run(argv, total_sec, on_progress, should_cancel) -> int
ProbeFn = Callable[..., Dict[str, Any]]
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
# pure: probe argv + classification
# --------------------------------------------------------------------------- #
def build_probe_streams_argv(
    in_path: str, settings: Optional[Dict[str, Any]] = None
) -> List[str]:
    """argv for the ffprobe codec/container sniff (JSON streams + format)."""
    return [
        ffmpeg.ffprobe_path(settings),
        "-v", "error",
        "-show_streams",
        "-show_format",
        "-of", "json",
        in_path,
    ]


def probe_media(
    in_path: str,
    settings: Optional[Dict[str, Any]] = None,
    runner: Callable[..., Any] = subprocess.run,
) -> Dict[str, Any]:
    """Run the ffprobe sniff; return the parsed JSON (``{}`` on any failure).

    ``runner`` is injectable so tests never spawn ffprobe. A failed/garbled
    probe yields ``{}``, which :func:`classify` maps to the proxy verdict —
    an unreadable file can never be declared playable.
    """
    argv = build_probe_streams_argv(in_path, settings)
    completed = runner(argv, capture_output=True, text=True, check=False)
    if getattr(completed, "returncode", 1) != 0:
        return {}
    try:
        data = json.loads(getattr(completed, "stdout", "") or "")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _stream_block_reason(stream: Dict[str, Any]) -> Optional[str]:
    """Why ``stream`` blocks direct playback, or None when it doesn't.

    Subtitle/data/attachment streams never gate playback; neither does an
    ``attached_pic`` video stream (embedded cover art is mjpeg/png by
    convention and is not the video being played).
    """
    codec_type = stream.get("codec_type")
    codec = str(stream.get("codec_name") or "").lower()
    if codec_type == "video":
        disposition = stream.get("disposition") or {}
        if disposition.get("attached_pic"):
            return None
        if codec in PLAYABLE_VIDEO_CODECS:
            return None
        return f"video codec not Chromium-playable: {codec or 'unknown'}"
    if codec_type == "audio":
        if codec in PLAYABLE_AUDIO_CODECS or codec.startswith(_PLAYABLE_AUDIO_PREFIXES):
            return None
        return f"audio codec not Chromium-playable: {codec or 'unknown'}"
    return None


def _container_playable(format_name: str, in_path: str) -> bool:
    """Whether ffprobe's ``format_name`` denotes a directly playable container.

    CONTRACT-NOTE: ffprobe reports BOTH .webm and .mkv as ``matroska,webm``
    (one demuxer family), so the extension disambiguates: a real ``.webm``
    file (whose streams already passed the codec check) is playable; ``.mkv``
    goes to remux. ``mov,mp4,m4a,3gp,3g2,mj2`` is the mp4 family.
    """
    tokens = {t.strip().lower() for t in format_name.split(",") if t.strip()}
    if tokens & _PLAYABLE_CONTAINER_TOKENS:
        return True
    if "webm" in tokens and Path(in_path).suffix.lower() == ".webm":
        return True
    return False


def classify(probe: Dict[str, Any], in_path: str) -> Tuple[str, str]:
    """Map an ffprobe result to ``(verdict, reason)`` per the A2 codec tree.

    Verdicts: :data:`VERDICT_PLAYABLE` / :data:`VERDICT_REMUX` /
    :data:`VERDICT_PROXY`. Pure — fully unit-testable with fabricated probes.
    """
    streams = probe.get("streams")
    if not isinstance(streams, list) or not streams:
        return VERDICT_PROXY, "ffprobe found no streams (unreadable media)"
    for stream in streams:
        if not isinstance(stream, dict):
            return VERDICT_PROXY, "malformed ffprobe stream entry"
        reason = _stream_block_reason(stream)
        if reason:
            return VERDICT_PROXY, reason
    fmt = probe.get("format") or {}
    format_name = str(fmt.get("format_name") or "")
    if _container_playable(format_name, in_path):
        return VERDICT_PLAYABLE, "all streams playable in a playable container"
    return (
        VERDICT_REMUX,
        f"streams playable but container is not: {format_name.lower() or 'unknown'}",
    )


# --------------------------------------------------------------------------- #
# pure: proxy cache paths + ffmpeg argv builders
# --------------------------------------------------------------------------- #
def default_proxies_dir() -> Path:
    """``%APPDATA%/media-studio/proxies`` (same root the settings store uses)."""
    return default_config_dir() / "proxies"


def _safe_cache_key(video_id: str) -> str:
    """Sanitize a videoId for use as a filename component (no traversal)."""
    key = "".join(ch for ch in video_id if ch.isalnum() or ch in "-_")
    return key or "video"


def proxy_cache_path(proxies_dir: str | os.PathLike, video_id: str, mtime_ns: int) -> Path:
    """The cached playable derivative for (videoId, source mtime).

    The mtime in the name IS the invalidation: a changed source produces a
    different cache path, and stale siblings are evicted after a build.
    """
    return Path(proxies_dir) / f"{_safe_cache_key(video_id)}-{mtime_ns}.mp4"


def build_remux_argv(
    in_path: str, out_path: str, settings: Optional[Dict[str, Any]] = None
) -> List[str]:
    """ffmpeg argv for the remux derivative (all streams already playable).

    ``-c copy`` into mp4; subtitle/data/attachment streams are dropped (mkv
    subtitle codecs are not mp4-legal under stream copy, and the proxy is for
    PLAYBACK — track operations keep using the original file).
    """
    return [
        ffmpeg.ffmpeg_path(settings),
        "-hide_banner", "-nostdin", "-y",
        "-i", in_path,
        "-map", "0", "-map", "-0:s", "-map", "-0:d", "-map", "-0:t",
        "-c", "copy",
        "-movflags", "+faststart",
        "-progress", "pipe:1", "-nostats",
        out_path,
    ]


def build_proxy_argv(
    in_path: str, out_path: str, settings: Optional[Dict[str, Any]] = None
) -> List[str]:
    """ffmpeg argv for the h264 720p playback proxy (A2: ``proxy transcode``).

    First video stream + first audio stream (if any); ``scale=-2:720`` keeps
    the aspect with an even width; yuv420p for universal decode; faststart so
    the <video> tag can begin before the file is fully read.
    """
    return [
        ffmpeg.ffmpeg_path(settings),
        "-hide_banner", "-nostdin", "-y",
        "-i", in_path,
        "-map", "0:v:0", "-map", "0:a:0?",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-vf", "scale=-2:720",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        "-progress", "pipe:1", "-nostats",
        out_path,
    ]


# --------------------------------------------------------------------------- #
# the feature service
# --------------------------------------------------------------------------- #
class MediaCompat:
    """Owns the verdict + proxy-cache logic behind the two A2 methods.

    All heavy seams are injected: ``resolver`` (videoId -> path),
    ``settings_provider`` (for ffmpeg/ffprobe resolution), ``probe`` (the
    ffprobe sniff) and ``run`` (the ffmpeg runner). ``proxies_dir`` is
    overridable so tests use a tmp dir instead of %APPDATA%.
    """

    def __init__(
        self,
        *,
        resolver: Resolver,
        settings_provider: Optional[Callable[[], Dict[str, Any]]] = None,
        proxies_dir: Optional[str | os.PathLike] = None,
        probe: Optional[ProbeFn] = None,
        run: Optional[RunFn] = None,
    ) -> None:
        self._resolver = resolver
        self._settings_provider = settings_provider or (lambda: {})
        self._proxies_dir = (
            Path(proxies_dir) if proxies_dir is not None else default_proxies_dir()
        )
        self._probe: ProbeFn = probe or probe_media
        self._run: RunFn = run or ffmpeg.run

    # -- internals ---------------------------------------------------------
    def _settings(self) -> Dict[str, Any]:
        try:
            return dict(self._settings_provider() or {})
        except Exception:  # noqa: BLE001 - settings must never break a verdict
            return {}

    def _resolve(self, video_id: str) -> str:
        path = self._resolver(video_id)
        if not path:
            raise _invalid(f"unknown video: {video_id}")
        return str(path)

    def _classify_path(
        self, in_path: str, settings: Dict[str, Any]
    ) -> Tuple[str, str, Dict[str, Any]]:
        """(verdict, reason, probe) for a concrete file path."""
        if not Path(in_path).exists():
            return VERDICT_PROXY, f"source file not found: {in_path}", {}
        try:
            probe = self._probe(in_path, settings) or {}
        except Exception as exc:  # noqa: BLE001 - a probe crash = unplayable, not a 500
            log.warning("ffprobe sniff failed for %s: %s", in_path, exc)
            return VERDICT_PROXY, f"ffprobe failed: {exc}", {}
        verdict, reason = classify(probe, in_path)
        return verdict, reason, probe

    def _cached_proxy(self, video_id: str, in_path: str) -> Optional[Path]:
        """The existing cache file for (videoId, current source mtime), if any."""
        try:
            mtime_ns = os.stat(in_path).st_mtime_ns
        except OSError:
            return None
        candidate = proxy_cache_path(self._proxies_dir, video_id, mtime_ns)
        return candidate if candidate.exists() else None

    def _evict_stale(self, video_id: str, keep: Path) -> None:
        """Drop older-mtime derivatives for this video (cache invalidation)."""
        try:
            for old in self._proxies_dir.glob(f"{_safe_cache_key(video_id)}-*.mp4"):
                if old != keep and old.is_file():
                    old.unlink()
        except OSError:  # pragma: no cover - best-effort cleanup
            log.warning("stale proxy eviction failed for %s", video_id)

    # -- media.playable ------------------------------------------------------
    def playable(self, params: Dict[str, Any], ctx: RpcContext) -> Dict[str, Any]:
        """``media.playable({videoId})`` -> ``{playable, reason?, proxyPath?}`` (A2).

        Direct-return. A cached derivative (remux OR proxy — both live in the
        same cache) short-circuits to ``{playable:true, proxyPath}``; otherwise
        the codec-driven verdict decides. ``playable:false`` carries the reason
        so the UI can explain why it is about to run ``media.proxy.start``.
        """
        video_id = _require_str(params, "videoId")
        in_path = self._resolve(video_id)

        cached = self._cached_proxy(video_id, in_path)
        if cached is not None:
            return {"playable": True, "proxyPath": str(cached)}

        verdict, reason, _probe = self._classify_path(in_path, self._settings())
        if verdict == VERDICT_PLAYABLE:
            return {"playable": True}
        return {"playable": False, "reason": reason}

    # -- media.proxy.start ----------------------------------------------------
    def proxy_start(self, params: Dict[str, Any], ctx: RpcContext) -> Dict[str, Any]:
        """``media.proxy.start({videoId})`` -> ``{jobId}`` -> ``{path}`` (A2).

        Job-based. The job builds the verdict-appropriate derivative (remux
        ``-c copy`` or h264 720p transcode), streams ffmpeg progress, honors
        cooperative cancel, caches by videoId+mtime, and resolves to
        ``{"path": <playable file>}``. Failures raise -> job.done error payload.
        """
        video_id = _require_str(params, "videoId")
        if ctx.jobs is None:
            raise RpcError("no job registry available", ErrorCode.INTERNAL_ERROR)
        # Validate the id up front so a bad request fails the CALL, not the job.
        in_path = self._resolve(video_id)
        settings = self._settings()

        def job_body(job_ctx: JobContext) -> Dict[str, str]:
            job_ctx.raise_if_cancelled()
            return {"path": self._build_derivative(video_id, in_path, settings, job_ctx)}

        job = ctx.jobs.start(job_body)
        return {"jobId": job.id}

    def _build_derivative(
        self,
        video_id: str,
        in_path: str,
        settings: Dict[str, Any],
        job_ctx: JobContext,
    ) -> str:
        """Produce (or reuse) the playable derivative for ``in_path``."""
        try:
            mtime_ns = os.stat(in_path).st_mtime_ns
        except OSError as exc:
            raise RuntimeError(f"source file not readable: {in_path} ({exc})") from exc

        final = proxy_cache_path(self._proxies_dir, video_id, mtime_ns)
        if final.exists():
            job_ctx.progress(100.0, "proxy cached")
            return str(final)

        verdict, reason, probe = self._classify_path(in_path, settings)
        if verdict == VERDICT_PLAYABLE:
            # CONTRACT-NOTE: A2 types the result as {path}; for a source that
            # already plays there is nothing to build — the path IS the source.
            job_ctx.progress(100.0, "source already playable")
            return str(in_path)

        try:
            total_sec = float((probe.get("format") or {}).get("duration") or 0.0)
        except (TypeError, ValueError):
            total_sec = 0.0

        self._proxies_dir.mkdir(parents=True, exist_ok=True)
        # Build into a partial file, then atomically publish (os.replace), so a
        # crash/cancel never leaves a half-written file at the cache path.
        partial = final.with_name(f"{final.stem}.partial.mp4")

        if verdict == VERDICT_REMUX:
            argv = build_remux_argv(in_path, str(partial), settings)
            job_ctx.progress(0.0, f"remuxing (stream copy): {reason}")
        else:
            argv = build_proxy_argv(in_path, str(partial), settings)
            job_ctx.progress(0.0, f"building h264 720p proxy: {reason}")

        code = self._run(
            argv,
            total_sec=total_sec,
            on_progress=lambda pct, msg: job_ctx.progress(pct, msg),
            should_cancel=lambda: job_ctx.cancelled,
        )

        if job_ctx.cancelled:
            partial.unlink(missing_ok=True)
            job_ctx.raise_if_cancelled()  # unwind -> registry marks CANCELLED
        if code != 0:
            partial.unlink(missing_ok=True)
            raise RuntimeError(
                f"ffmpeg exited with code {code} building the playback proxy for {in_path}"
            )

        os.replace(partial, final)
        self._evict_stale(video_id, final)
        return str(final)


# --------------------------------------------------------------------------- #
# registration (the wiring agent calls this from handlers.register_all)
# --------------------------------------------------------------------------- #
def register(
    *,
    resolver: Resolver,
    settings_provider: Optional[Callable[[], Dict[str, Any]]] = None,
    proxies_dir: Optional[str | os.PathLike] = None,
    probe: Optional[ProbeFn] = None,
    run: Optional[RunFn] = None,
    register_fn: Optional[Callable[[str, Any], None]] = None,
) -> MediaCompat:
    """Create a :class:`MediaCompat` and register the A2 methods imperatively.

    ``register_fn`` defaults to :func:`protocol.register` (duplicate names fail
    loudly); tests inject a fake registrar. Returns the service so the caller
    can hold/inspect it.
    """
    service = MediaCompat(
        resolver=resolver,
        settings_provider=settings_provider,
        proxies_dir=proxies_dir,
        probe=probe,
        run=run,
    )
    reg = register_fn if register_fn is not None else protocol.register
    reg("media.playable", service.playable)
    reg("media.proxy.start", service.proxy_start)
    return service


__all__ = [
    "VERDICT_PLAYABLE",
    "VERDICT_REMUX",
    "VERDICT_PROXY",
    "PLAYABLE_VIDEO_CODECS",
    "PLAYABLE_AUDIO_CODECS",
    "MediaCompat",
    "build_probe_streams_argv",
    "build_remux_argv",
    "build_proxy_argv",
    "classify",
    "default_proxies_dir",
    "probe_media",
    "proxy_cache_path",
    "register",
]
