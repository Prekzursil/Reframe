"""ffmpeg conversion feature: map options -> argv, run single + batch jobs.

This is the feature-layer wrapper behind the IPC methods (CONTRACTS.md section 2):

  - ``convert.start({videoId|path, options})`` -> ``{jobId}`` -> ``{path}``
  - ``convert.batch({items})``                 -> ``{jobId}`` -> ``{paths}``

The heavy lifting (binary resolution, the ffmpeg argv builder, the progress-
parsing ``run``, and ``ffprobe_duration``) already lives in :mod:`media_studio.ffmpeg`.
This module adds three things on top of it:

  1. A **pure** output-path derivation: given a source path + ``options`` (and an
     optional caller-supplied ``out`` override), decide the destination file and
     its extension. ``audioOnly`` swaps the extension to ``audioFormat`` (mp3,
     m4a, wav, ...); otherwise ``container`` (mp4, mkv, webm, ...) wins. This is
     fully unit-tested, including paths that contain spaces.
  2. ``convert_one`` / ``convert_batch`` — resolve the source, probe its duration,
     build the argv, and stream progress through the injected ``run`` seam. Batch
     work distributes the 0..100 progress evenly across its items.
  3. ``start_handler`` / ``batch_handler`` — :class:`~media_studio.jobs.JobContext`
     handlers (cooperative-cancel aware) ready to hand to ``JobRegistry.start``.

``options`` keys (frozen by CONTRACTS.md section 2 ``convert.start``)::

    {container, vcodec, acodec, scale, fps, crf, audioOnly, audioFormat}

Subprocess safety is inherited from :mod:`ffmpeg`: every call is an argv **list**
(never ``shell=True``), so paths with spaces are a single argv element and just
work. The subprocess is injected (``run``/``probe``) so tests never spawn ffmpeg.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from .. import ffmpeg
from ..jobs import JobContext
from ..util import clamp_pct, get_logger

log = get_logger("media_studio.convert")

# Seams (injected in tests so no real ffmpeg/ffprobe is ever spawned):
#   RunFn   mirrors ffmpeg.run(argv, total_sec, on_progress, should_cancel) -> int
#   ProbeFn mirrors ffmpeg.ffprobe_duration(path, settings) -> float
RunFn = Callable[..., int]
ProbeFn = Callable[..., float]

# A library-style source resolver: videoId -> absolute path (or None if unknown).
SourceResolver = Callable[[str], str | None]

# CONTRACT-NOTE: §2 only names the option keys, not the file extensions. We map
# audioFormat / container to sensible default extensions; an explicit ``out`` in
# the item overrides all derivation, and an unrecognised value is used verbatim
# as the extension (so a novel container/format still produces a usable name).
_DEFAULT_VIDEO_EXT = "mp4"
_DEFAULT_AUDIO_EXT = "m4a"

# audioFormat -> file extension (codec-ish name -> on-disk extension).
_AUDIO_EXT: dict[str, str] = {
    "mp3": "mp3",
    "libmp3lame": "mp3",
    "aac": "m4a",
    "m4a": "m4a",
    "alac": "m4a",
    "wav": "wav",
    "pcm": "wav",
    "flac": "flac",
    "opus": "opus",
    "libopus": "opus",
    "vorbis": "ogg",
    "libvorbis": "ogg",
    "ogg": "ogg",
    "ac3": "ac3",
}


def _ext_for_audio(audio_format: str | None) -> str:
    """Map an ``audioFormat`` value to an output file extension."""
    if not audio_format:
        return _DEFAULT_AUDIO_EXT
    key = str(audio_format).strip().lower().lstrip(".")
    return _AUDIO_EXT.get(key, key or _DEFAULT_AUDIO_EXT)


def _ext_for_container(container: str | None) -> str:
    """Map a ``container`` value to an output file extension."""
    if not container:
        return _DEFAULT_VIDEO_EXT
    return str(container).strip().lower().lstrip(".") or _DEFAULT_VIDEO_EXT


def output_path(
    in_path: str,
    options: dict[str, Any] | None = None,
    out: str | None = None,
) -> str:
    """Derive the destination path for a conversion (pure, no I/O).

    Precedence:
      1. an explicit ``out`` override (used verbatim — caller owns the name);
      2. otherwise ``<in stem>.<ext>`` in the source's own directory, where
         ``ext`` is the ``audioFormat`` extension when ``audioOnly`` is set, else
         the ``container`` extension.

    A ``.converted`` infix is added when the derived destination would collide
    with the source path (same dir + same extension), so a re-encode never
    silently clobbers the original. Paths with spaces are preserved exactly.
    """
    if out:
        return out

    options = options or {}
    src = Path(in_path)
    if options.get("audioOnly"):
        ext = _ext_for_audio(options.get("audioFormat") or options.get("acodec"))
    else:
        ext = _ext_for_container(options.get("container"))

    dest = src.with_name(f"{src.stem}.{ext}")
    if str(dest) == str(src):
        # Same name + extension as the source: avoid in-place clobber.
        dest = src.with_name(f"{src.stem}.converted.{ext}")
    return str(dest)


def _resolve_source(
    item: dict[str, Any],
    resolver: SourceResolver | None,
) -> str:
    """Resolve an item's source to a concrete path.

    Accepts ``{"path": ...}`` directly, or ``{"videoId": ...}`` resolved through
    ``resolver`` (a ``library.get(id)["path"]``-style callable). Raises
    ``ValueError`` when neither is usable so a job fails loudly rather than
    feeding ffmpeg an empty input.
    """
    path = item.get("path")
    if path:
        return str(path)

    video_id = item.get("videoId")
    if video_id and resolver is not None:
        resolved = resolver(str(video_id))
        if resolved:
            return str(resolved)
        raise ValueError(f"unknown videoId: {video_id}")

    raise ValueError("convert item needs a 'path' or a resolvable 'videoId'")


def convert_one(
    item: dict[str, Any],
    *,
    settings: dict[str, Any] | None = None,
    resolver: SourceResolver | None = None,
    on_progress: Callable[[float, str], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
    run: RunFn = ffmpeg.run,
    probe: ProbeFn = ffmpeg.ffprobe_duration,
) -> str:
    """Convert a single ``item`` and return the output path.

    ``item`` = ``{"path"|"videoId", "options"?, "out"?}``. The source is resolved,
    probed for duration (so progress can be a real percentage), encoded via an
    argv built by :func:`ffmpeg.build_convert_argv`, and the chosen output path
    is returned. A non-zero ffmpeg exit raises :class:`RuntimeError`.
    """
    in_path = _resolve_source(item, resolver)
    options = item.get("options") or {}
    out_path = output_path(in_path, options, item.get("out"))

    # Probe the source duration so out_time can be turned into a real pct. A
    # failed/zero probe is fine — run() then just reports the final 100/done.
    try:
        total_sec = float(probe(in_path, settings))
    except Exception:  # noqa: BLE001 - a probe failure must not abort the convert
        log.warning("duration probe failed for %s; progress will be coarse", in_path)
        total_sec = 0.0

    argv = ffmpeg.build_convert_argv(in_path, out_path, options, settings)
    code = run(
        argv,
        total_sec=total_sec,
        on_progress=on_progress,
        should_cancel=should_cancel,
    )
    if code != 0:
        raise RuntimeError(f"ffmpeg exited with code {code} converting {in_path}")
    return out_path


def convert_batch(
    items: Sequence[dict[str, Any]],
    *,
    settings: dict[str, Any] | None = None,
    resolver: SourceResolver | None = None,
    on_progress: Callable[[float, str], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
    run: RunFn = ffmpeg.run,
    probe: ProbeFn = ffmpeg.ffprobe_duration,
) -> list[str]:
    """Convert each item in turn, returning the list of output paths (in order).

    Progress is spread evenly across the items: item ``i`` of ``n`` reports
    ``(i*100 + per_item_pct) / n`` overall, so a 4-item batch climbs 0->25->...
    smoothly. Cancellation is honored between items (and within an item, via the
    ``should_cancel`` seam handed to :func:`ffmpeg.run`).
    """
    items = list(items)
    n = len(items)
    paths: list[str] = []

    for i, item in enumerate(items):
        if should_cancel is not None and should_cancel():
            break

        def _item_progress(pct: float, message: str, _i: int = i) -> None:
            if (
                on_progress is None
            ):  # pragma: no cover - closure is only passed to convert_one when on_progress is not None (see call site)
                return
            overall = (_i * 100.0 + max(0.0, min(100.0, pct))) / n if n else 100.0
            on_progress(overall, f"[{_i + 1}/{n}] {message}")

        out = convert_one(
            item,
            settings=settings,
            resolver=resolver,
            on_progress=_item_progress if on_progress is not None else None,
            should_cancel=should_cancel,
            run=run,
            probe=probe,
        )
        paths.append(out)

    return paths


# --------------------------------------------------------------------------- #
# Job handlers (wire convert_one / convert_batch onto JobContext)
# --------------------------------------------------------------------------- #
def start_handler(
    params: dict[str, Any],
    *,
    settings: dict[str, Any] | None = None,
    resolver: SourceResolver | None = None,
    run: RunFn = ffmpeg.run,
    probe: ProbeFn = ffmpeg.ffprobe_duration,
) -> Callable[[JobContext], dict[str, str]]:
    """Build a ``convert.start`` job handler from request ``params``.

    ``params`` = ``{"videoId"|"path", "options"?}`` (CONTRACTS.md §2). The
    returned handler runs on a worker thread, emits ``job.progress``, observes
    cooperative cancellation, and resolves to ``{"path": <out>}`` for ``job.done``.
    """
    item: dict[str, Any] = {
        "path": params.get("path"),
        "videoId": params.get("videoId"),
        "options": params.get("options") or {},
        "out": params.get("out"),
    }

    def handler(ctx: JobContext) -> dict[str, str]:
        ctx.raise_if_cancelled()
        out = convert_one(
            item,
            settings=settings,
            resolver=resolver,
            on_progress=lambda pct, msg: ctx.progress(pct, msg),
            should_cancel=lambda: ctx.cancelled,
            run=run,
            probe=probe,
        )
        return {"path": out}

    return handler


def batch_handler(
    params: dict[str, Any],
    *,
    settings: dict[str, Any] | None = None,
    resolver: SourceResolver | None = None,
    run: RunFn = ffmpeg.run,
    probe: ProbeFn = ffmpeg.ffprobe_duration,
) -> Callable[[JobContext], dict[str, list[str]]]:
    """Build a ``convert.batch`` job handler from request ``params``.

    ``params`` = ``{"items": [{"videoId"|"path", "options"?, "out"?}, ...]}``. The
    returned handler converts each item, emits aggregate ``job.progress``, honors
    cancellation between items, and resolves to ``{"paths": [...]}`` for ``job.done``.
    """
    items: list[dict[str, Any]] = list(params.get("items") or [])

    def handler(ctx: JobContext) -> dict[str, list[str]]:
        ctx.raise_if_cancelled()
        paths = convert_batch(
            items,
            settings=settings,
            resolver=resolver,
            on_progress=lambda pct, msg: ctx.progress(pct, msg),
            should_cancel=lambda: ctx.cancelled,
            run=run,
            probe=probe,
        )
        # If we stopped early because of a cancel, surface it so the registry
        # marks the job CANCELLED rather than DONE with a partial result.
        ctx.raise_if_cancelled()
        return {"paths": paths}

    return handler


# clamp_pct re-exported for callers that want to pre-normalize a pct value the
# same way the job layer will (kept here to avoid a util import at the call site).
__all__ = [
    "output_path",
    "convert_one",
    "convert_batch",
    "start_handler",
    "batch_handler",
    "clamp_pct",
]
