"""Shorts library — persisted export metadata + the ``shorts.*`` RPC methods (P4 §2/§3).

The short-maker EXPORT stage writes a sidecar ``<clip>.json`` metadata file next
to every produced ``<clip>.mp4`` (see :func:`build_metadata` /
:func:`write_export_metadata`, called from ``shortmaker._export_one`` where the
hook / template / viralityPct / duration are still in scope). That ``.json`` is
the PRIMARY source ``shorts.list`` reconstructs ``ShortInfo`` from — without it
the gallery would be empty (PLAN-P4 C5).

Methods (names FROZEN by §2):

  - ``shorts.list``      ``{videoId?}``  -> ``{shorts: ShortInfo[]}``
        Scan the exports root (``exports/shorts-<videoId>/`` per ``out_dir_for``)
        for ``*.mp4``; reconstruct each ``ShortInfo`` from its ``.json`` (one
        ffprobe fallback for dims when the ``.json`` is absent); ``createdAt`` desc.
  - ``shorts.thumbnail`` ``{path}``      -> ``{thumbnailPath}``
        ffmpeg-extract a poster frame to ``<clip>.thumb.jpg`` (idempotent);
        drained pipes via the shared ``ffmpeg.run``; raises on failure. ``path``
        MUST be inside the exports root (path-traversal guard).
  - ``shorts.delete``    ``{path}``      -> ``{ok: true}``
        Delete the ``.mp4`` + its ``.thumb.jpg`` + ``.json``; reject paths
        outside the exports root.
  - ``shorts.reexport``  ``{path}``      -> ``{videoId, candidate}``
        Return the clip's source ``videoId`` + ``candidate`` (from the ``.json``)
        so the UI can re-open Short-maker primed (the simplest acceptable impl
        per §2 — no job started here; the UI replays ``shortmaker.export``).

``ShortInfo`` (PLAN-P4 §3, field names FROZEN)::

    {id, path, videoId, sourceTitle, template, viralityPct, durationSec,
     width, height, createdAt, thumbnailPath, hook}

All heavy work is behind the same seams the sibling features use: the ffprobe
sniff (``probe``) and the ffmpeg ``run`` are injectable, so tests never spawn a
real process. argv lists only (never ``shell=True``); ``ffmpeg.run`` already
drains both pipes on a thread (the 29-min-freeze lesson) and is reused as-is;
failures raise -> they surface through the RPC error / job.done payload.
"""

from __future__ import annotations

import builtins
import hashlib
import json
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .. import ffmpeg, protocol
from ..protocol import ErrorCode, RpcContext, RpcError
from ..util import get_logger

log = get_logger("media_studio.shorts")

# Suffixes for the sidecar artifacts written next to each exported ``<clip>.mp4``.
META_SUFFIX = ".json"
THUMB_SUFFIX = ".thumb.jpg"

# The persisted ``.json`` carries exactly these export-time fields (§3); the
# remaining ShortInfo fields (id/path/width/height/createdAt/thumbnailPath) are
# derived at list time from the filesystem (+ ffprobe fallback for dims).
META_FIELDS = (
    "videoId",
    "sourceTitle",
    "template",
    "viralityPct",
    "durationSec",
    "hook",
    "createdAt",
)

# Injectable seams (mirrors media_compat): ProbeFn -> ffprobe dims; RunFn ->
# ffmpeg.run(argv, total_sec, on_progress, should_cancel) -> int.
ProbeFn = Callable[..., dict[str, Any]]
RunFn = Callable[..., int]


def _invalid(message: str) -> RpcError:
    return RpcError(message, ErrorCode.INVALID_PARAMS)


def _require_str(params: dict[str, Any], key: str) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value:
        raise _invalid(f"{key} (str) is required")
    return value


# --------------------------------------------------------------------------- #
# pure: sidecar paths + metadata shaping
# --------------------------------------------------------------------------- #
def metadata_path(clip_path: str | os.PathLike) -> Path:
    """``<clip>.json`` next to the exported ``<clip>.mp4``."""
    p = Path(clip_path)
    return p.with_name(p.name + META_SUFFIX)


def thumbnail_path(clip_path: str | os.PathLike) -> Path:
    """``<clip>.thumb.jpg`` next to the exported ``<clip>.mp4``."""
    p = Path(clip_path)
    return p.with_name(p.name + THUMB_SUFFIX)


def short_id(clip_path: str | os.PathLike) -> str:
    """Stable id for a short = sha1 of its absolute path (PLAN-P4 §3 ``id``)."""
    key = str(Path(clip_path).resolve())
    # Non-security content hash: a stable id derived from the clip's path, not a
    # credential. usedforsecurity=False keeps the digest value identical (so
    # existing persisted short ids stay stable) while satisfying the SAST gate.
    return hashlib.sha1(key.encode("utf-8"), usedforsecurity=False).hexdigest()[:16]


def build_metadata(
    *,
    video_id: str,
    source_title: str,
    template: str,
    virality_pct: int | None,
    duration_sec: float,
    hook: str,
    created_at: float | None = None,
) -> dict[str, Any]:
    """Build the ``<clip>.json`` payload (the §3 export-time fields).

    Pure: every value is normalized to the frozen wire type so a malformed
    candidate can never write a half-typed record.
    """
    pct: int | None
    if virality_pct is None:
        pct = None
    else:
        try:
            pct = int(virality_pct)
        except (TypeError, ValueError):
            pct = None
    return {
        "videoId": str(video_id or ""),
        "sourceTitle": str(source_title or ""),
        "template": str(template or ""),
        "viralityPct": pct,
        "durationSec": float(duration_sec or 0.0),
        "hook": str(hook or ""),
        "createdAt": float(created_at if created_at is not None else time.time()),
    }


def write_export_metadata(clip_path: str | os.PathLike, meta: dict[str, Any]) -> Path:
    """Persist ``meta`` to ``<clip>.json`` (UTF-8, LF). Returns the json path.

    Called from ``shortmaker._export_one`` (PLAN-P4 C5 — the PRIMARY path that
    makes ``shorts.list`` non-empty). Best-effort: a write failure is logged and
    swallowed so it never fails the export job (the clip itself already exists).
    """
    json_path = metadata_path(clip_path)
    try:
        json_path.parent.mkdir(parents=True, exist_ok=True)
        with open(json_path, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(meta, fh, ensure_ascii=False, indent=2)
    except OSError as exc:  # pragma: no cover - exercised via the swallow test
        log.warning("failed to write short metadata %s: %s", json_path, exc)
    return json_path


def read_metadata(clip_path: str | os.PathLike) -> dict[str, Any] | None:
    """Read ``<clip>.json`` back (``None`` when absent / unreadable / not an obj)."""
    json_path = metadata_path(clip_path)
    if not json_path.exists():
        return None
    try:
        obj = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return obj if isinstance(obj, dict) else None


# --------------------------------------------------------------------------- #
# pure: ffmpeg/ffprobe argv builders
# --------------------------------------------------------------------------- #
def build_thumbnail_argv(in_path: str, out_path: str, settings: dict[str, Any] | None = None) -> list[str]:
    """ffmpeg argv extracting a single poster frame (~1s in) as a JPEG.

    ``-ss 1`` seeks to ~1s (past any black intro), ``-frames:v 1`` grabs one
    frame, ``-progress pipe:1 -nostats`` so :func:`ffmpeg.run` drains stdout.
    """
    return [
        ffmpeg.ffmpeg_path(settings),
        "-hide_banner",
        "-nostdin",
        "-y",
        "-ss",
        "1",
        "-i",
        in_path,
        "-frames:v",
        "1",
        "-q:v",
        "3",
        "-progress",
        "pipe:1",
        "-nostats",
        out_path,
    ]


def build_probe_dims_argv(in_path: str, settings: dict[str, Any] | None = None) -> list[str]:
    """ffprobe argv printing the first video stream's ``width,height`` as JSON."""
    return [
        ffmpeg.ffprobe_path(settings),
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height",
        "-of",
        "json",
        in_path,
    ]


def probe_dims(
    in_path: str,
    settings: dict[str, Any] | None = None,
    runner: Callable[..., Any] = None,
) -> tuple[int, int]:
    """Probe ``(width, height)`` for ``in_path`` (``(0, 0)`` on any failure).

    ``runner`` is injectable so tests never spawn ffprobe.
    """
    import subprocess

    runner = runner or subprocess.run
    argv = build_probe_dims_argv(in_path, settings)
    completed = runner(argv, capture_output=True, text=True, check=False)
    if getattr(completed, "returncode", 1) != 0:
        return 0, 0
    try:
        data = json.loads(getattr(completed, "stdout", "") or "")
    except ValueError:
        return 0, 0
    streams = data.get("streams") if isinstance(data, dict) else None
    if not isinstance(streams, list) or not streams:
        return 0, 0
    first = streams[0] if isinstance(streams[0], dict) else {}
    try:
        return int(first.get("width") or 0), int(first.get("height") or 0)
    except (TypeError, ValueError):
        return 0, 0


# --------------------------------------------------------------------------- #
# pure: ShortInfo reconstruction
# --------------------------------------------------------------------------- #
def short_info(
    clip_path: str | os.PathLike,
    meta: dict[str, Any] | None,
    *,
    width: int = 0,
    height: int = 0,
) -> dict[str, Any]:
    """Reconstruct one ``ShortInfo`` (§3) from a clip path + its ``.json`` meta.

    Filesystem-derived fields (id/path/createdAt/thumbnailPath) always come from
    disk; export-time fields default to blank/None when ``meta`` is absent
    (back-compat for clips produced before the ``.json`` write existed). ``width``
    / ``height`` come from the ffprobe fallback when the caller could not find
    them in ``meta``.
    """
    p = Path(clip_path)
    meta = meta or {}
    try:
        created = float(meta.get("createdAt")) if meta.get("createdAt") else 0.0
    except (TypeError, ValueError):
        created = 0.0
    if not created:
        try:
            created = p.stat().st_mtime
        except OSError:
            created = 0.0
    thumb = thumbnail_path(p)
    pct = meta.get("viralityPct")
    return {
        "id": short_id(p),
        "path": str(p),
        "videoId": str(meta.get("videoId") or ""),
        "sourceTitle": str(meta.get("sourceTitle") or ""),
        "template": str(meta.get("template") or ""),
        "viralityPct": pct if isinstance(pct, int) else None,
        "durationSec": float(meta.get("durationSec") or 0.0),
        "width": int(meta.get("width") or width or 0),
        "height": int(meta.get("height") or height or 0),
        "createdAt": created,
        "thumbnailPath": str(thumb) if thumb.exists() else "",
        "hook": str(meta.get("hook") or ""),
    }


# --------------------------------------------------------------------------- #
# the feature service
# --------------------------------------------------------------------------- #
class Shorts:
    """Owns the ``shorts.*`` logic over the exports root.

    Seams (all injectable): ``exports_dir`` (the ``Services.exports_dir`` root),
    ``out_dir_for`` (videoId -> its ``shorts-<id>`` subdir — mirrors
    ``Services._shortmaker``), ``settings_provider`` (ffmpeg/ffprobe resolution),
    ``probe`` (the ffprobe dims sniff) and ``run`` (the ffmpeg runner).
    """

    def __init__(
        self,
        *,
        exports_dir: str | os.PathLike,
        out_dir_for: Callable[[str], str] | None = None,
        settings_provider: Callable[[], dict[str, Any]] | None = None,
        probe: ProbeFn | None = None,
        run: RunFn | None = None,
    ) -> None:
        self._exports_dir = Path(exports_dir)
        self._out_dir_for = out_dir_for or (lambda vid: str(self._exports_dir / f"shorts-{vid}"))
        self._settings_provider = settings_provider or (lambda: {})
        self._probe: ProbeFn = probe or probe_dims
        self._run: RunFn = run or ffmpeg.run

    # -- internals ---------------------------------------------------------
    def _settings(self) -> dict[str, Any]:
        try:
            return dict(self._settings_provider() or {})
        except Exception:  # noqa: BLE001 - settings must never break a listing
            return {}

    def _guard_in_root(self, path: str) -> Path:
        """Resolve ``path`` and assert it lives inside the exports root.

        Path-traversal guard (§2): a ``shorts.delete`` / ``shorts.thumbnail``
        target outside ``exports_dir`` is rejected with INVALID_PARAMS so a
        crafted path can never reach an arbitrary file.
        """
        resolved = Path(path).resolve()
        root = self._exports_dir.resolve()
        try:
            resolved.relative_to(root)
        except ValueError:
            raise _invalid(f"path is outside the exports root: {path}") from None
        return resolved

    def _scan_dir(self, directory: Path) -> builtins.list[dict[str, Any]]:
        """Reconstruct a ShortInfo for every ``*.mp4`` in ``directory``."""
        out: list[dict[str, Any]] = []
        if not directory.is_dir():
            return out
        for mp4 in sorted(directory.glob("*.mp4")):
            meta = read_metadata(mp4)
            width = height = 0
            if meta is None or not (meta.get("width") and meta.get("height")):
                # One ffprobe fallback for dims when the .json is absent/partial.
                try:
                    width, height = self._probe(str(mp4), self._settings())
                except Exception as exc:  # noqa: BLE001 - a probe miss != fatal
                    log.warning("ffprobe dims failed for %s: %s", mp4, exc)
                    width = height = 0
            out.append(short_info(mp4, meta, width=width, height=height))
        return out

    # -- shorts.list ---------------------------------------------------------
    def list(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``shorts.list({videoId?})`` -> ``{shorts: ShortInfo[]}`` (§2).

        ``videoId`` filters to that source's ``shorts-<id>`` dir; omitted scans
        every ``shorts-*`` dir under the exports root. Sorted ``createdAt`` desc.
        """
        video_id = params.get("videoId")
        if video_id is not None and not isinstance(video_id, str):
            raise _invalid("videoId must be a string when given")

        dirs: list[Path]
        if video_id:
            dirs = [Path(self._out_dir_for(video_id))]
        else:
            root = self._exports_dir
            dirs = sorted(root.glob("shorts-*")) if root.is_dir() else []

        shorts: list[dict[str, Any]] = []
        for directory in dirs:
            shorts.extend(self._scan_dir(directory))
        shorts.sort(key=lambda s: s["createdAt"], reverse=True)
        return {"shorts": shorts}

    # -- shorts.thumbnail ----------------------------------------------------
    def thumbnail(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``shorts.thumbnail({path})`` -> ``{thumbnailPath}`` (§2).

        Idempotent: an existing ``<clip>.thumb.jpg`` short-circuits. Otherwise
        ffmpeg extracts one poster frame via the drained ``run`` seam; a non-zero
        exit raises (surfacing through the RPC error payload).
        """
        path = _require_str(params, "path")
        clip = self._guard_in_root(path)
        if not clip.exists():
            raise _invalid(f"short not found: {path}")
        thumb = thumbnail_path(clip)
        if thumb.exists():
            return {"thumbnailPath": str(thumb)}

        argv = build_thumbnail_argv(str(clip), str(thumb), self._settings())
        code = self._run(argv, total_sec=0.0)
        if code != 0:
            raise RpcError(
                f"ffmpeg exited with code {code} extracting a thumbnail for {path}",
                ErrorCode.INTERNAL_ERROR,
            )
        return {"thumbnailPath": str(thumb)}

    # -- shorts.delete -------------------------------------------------------
    def delete(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``shorts.delete({path})`` -> ``{ok: true}`` (§2).

        Deletes the ``.mp4`` + its ``.thumb.jpg`` + ``.json``. The path-traversal
        guard rejects any target outside the exports root BEFORE unlinking.
        """
        path = _require_str(params, "path")
        clip = self._guard_in_root(path)
        for target in (clip, thumbnail_path(clip), metadata_path(clip)):
            try:
                Path(target).unlink(missing_ok=True)
            except OSError as exc:  # pragma: no cover - best-effort unlink
                log.warning("failed to delete %s: %s", target, exc)
        return {"ok": True}

    # -- shorts.reexport -----------------------------------------------------
    def reexport(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``shorts.reexport({path})`` -> ``{videoId, candidate}`` (§2).

        The simplest acceptable impl (§2): return the source ``videoId`` + a
        ``candidate`` skeleton (rebuilt from the persisted ``.json`` — hook /
        template / viralityPct / durationSec) so the UI can re-open Short-maker
        primed and replay ``shortmaker.export`` itself. No job is started here.
        """
        path = _require_str(params, "path")
        clip = self._guard_in_root(path)
        if not clip.exists():
            raise _invalid(f"short not found: {path}")
        meta = read_metadata(clip) or {}
        candidate = {
            "hook": str(meta.get("hook") or ""),
            "template": str(meta.get("template") or ""),
            "viralityPct": meta.get("viralityPct"),
            "durationSec": float(meta.get("durationSec") or 0.0),
        }
        return {"videoId": str(meta.get("videoId") or ""), "candidate": candidate}


# --------------------------------------------------------------------------- #
# registration (the wiring agent calls this from handlers.register_all)
# --------------------------------------------------------------------------- #
def register(
    *,
    exports_dir: str | os.PathLike,
    out_dir_for: Callable[[str], str] | None = None,
    settings_provider: Callable[[], dict[str, Any]] | None = None,
    probe: ProbeFn | None = None,
    run: RunFn | None = None,
    register_fn: Callable[[str, Any], None] | None = None,
) -> Shorts:
    """Create a :class:`Shorts` and register the four ``shorts.*`` methods (C6).

    ``register_fn`` defaults to :func:`protocol.register` (duplicate names fail
    loudly); tests inject a fake registrar. Returns the service so the caller can
    hold/inspect it. Mirrors ``media_compat.register`` / ``feedback.register``.
    """
    service = Shorts(
        exports_dir=exports_dir,
        out_dir_for=out_dir_for,
        settings_provider=settings_provider,
        probe=probe,
        run=run,
    )
    reg = register_fn if register_fn is not None else protocol.register
    reg("shorts.list", service.list)
    reg("shorts.thumbnail", service.thumbnail)
    reg("shorts.delete", service.delete)
    reg("shorts.reexport", service.reexport)
    return service


__all__ = [
    "META_FIELDS",
    "META_SUFFIX",
    "THUMB_SUFFIX",
    "Shorts",
    "build_metadata",
    "build_probe_dims_argv",
    "build_thumbnail_argv",
    "metadata_path",
    "probe_dims",
    "read_metadata",
    "register",
    "short_id",
    "short_info",
    "thumbnail_path",
    "write_export_metadata",
]
