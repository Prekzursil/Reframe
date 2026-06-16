"""Library + Project persistence for the media-studio sidecar.

Library: add/list/remove videos in a JSON index on disk. Each added video is
probed for its ``durationSec`` via ``ffprobe`` (resolved through ``ffmpeg.py``).

Project: open/save a *versioned* JSON manifest that references its source video
**by path** (never by copied bytes). ``consolidate`` copies referenced assets
into the project folder and rewrites the refs to be *relative* to that folder,
and ``find_missing_sources`` reports refs whose files no longer exist.

Schema field names are frozen by CONTRACTS.md section 3:
  Video   = {id, path, title, addedAt, durationSec, hasTranscript}
  Project = {id, video, transcript?, tracks, clips, settings}

This module is pure logic + filesystem I/O. The only external dependency is the
ffprobe duration probe, which is injected (``probe_duration``) so tests can mock
the subprocess seam without importing ffmpeg/ffprobe.
"""

from __future__ import annotations

import builtins
import json
import os
import shutil
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

# CONTRACT-NOTE: the manifest schema version is local to this unit (the contract
# only mandates "versioned"); bump on any breaking field change. open() tolerates
# missing/older versions by filling defaults rather than failing hard.
MANIFEST_VERSION = 1

# Type aliases for clarity (matching CONTRACTS.md section 3 field names).
# NOTE: the manifest *payload* alias is ``ProjectData`` (a plain dict), kept
# distinct from the ``Project`` *class* below so the alias is not shadowed by
# the class (that shadowing was the root of the basedpyright `Project` cascade).
Video = dict[str, Any]
ProjectData = dict[str, Any]

# A duration prober: (path) -> seconds. Injected so the ffprobe subprocess can be
# mocked at the seam in tests (no ffmpeg import required for library tests).
DurationProber = Callable[[str], float]


def _now_iso() -> str:
    """UTC timestamp, e.g. ``2026-06-11T19:30:00Z`` (stable, sortable, tz-aware)."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _new_id() -> str:
    """A short, collision-free id for a library entry / project."""
    return uuid.uuid4().hex[:12]


def _default_probe(path: str) -> float:
    """Default duration prober delegating to ffmpeg.ffprobe_duration.

    Imported lazily so that importing :mod:`library` (and its tests) never pulls
    in the ffmpeg module at import time.
    """
    from . import ffmpeg  # local import keeps the seam mockable / import-light

    return ffmpeg.ffprobe_duration(path)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: Any) -> None:
    """Atomically write ``data`` as pretty JSON (temp file + os.replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


class Library:
    """A JSON-indexed collection of videos on disk.

    The index file is a single JSON document::

        {"version": 1, "videos": [ <Video>, ... ]}

    Methods return / accept plain dicts whose keys match CONTRACTS.md section 3.
    """

    def __init__(self, index_path: str | os.PathLike, probe_duration: DurationProber | None = None):
        self.index_path = Path(index_path)
        self._probe = probe_duration or _default_probe

    # ---- index I/O ---------------------------------------------------------
    def _load(self) -> builtins.list[Video]:
        if not self.index_path.exists():
            return []
        data = _read_json(self.index_path)
        videos = data.get("videos", []) if isinstance(data, dict) else []
        # Backfill any missing schema keys so callers always get full Video dicts.
        return [self._normalize(v) for v in videos]

    def _save(self, videos: builtins.list[Video]) -> None:
        _write_json(self.index_path, {"version": MANIFEST_VERSION, "videos": videos})

    @staticmethod
    def _normalize(v: dict[str, Any]) -> Video:
        return {
            "id": v.get("id") or _new_id(),
            "path": v.get("path", ""),
            "title": v.get("title", ""),
            "addedAt": v.get("addedAt") or _now_iso(),
            "durationSec": float(v.get("durationSec") or 0.0),
            "hasTranscript": bool(v.get("hasTranscript", False)),
        }

    # ---- public surface (matches library.* methods) ------------------------
    def list(self) -> builtins.list[Video]:
        """Return all videos in the index (newest order preserved as stored)."""
        return self._load()

    def add(self, path: str, title: str | None = None) -> Video:
        """Add ``path`` to the library, probing its duration, and return the Video.

        Re-adding an existing path is idempotent: the existing entry is returned
        rather than creating a duplicate row.
        """
        src = Path(path)
        if not src.exists():
            raise FileNotFoundError(f"video not found: {path}")

        abspath = str(src.resolve())
        videos = self._load()
        for existing in videos:
            if existing["path"] == abspath:
                return existing  # idempotent re-add

        try:
            duration = float(self._probe(abspath))
        except Exception:
            # CONTRACT-NOTE: a probe failure must not block adding the video; we
            # store 0.0 and let a later re-probe / transcribe fill it in.
            duration = 0.0

        video: Video = {
            "id": _new_id(),
            "path": abspath,
            "title": title or src.stem,
            "addedAt": _now_iso(),
            "durationSec": duration,
            "hasTranscript": False,
        }
        videos.append(video)
        self._save(videos)
        return video

    def get(self, video_id: str) -> Video | None:
        """Return the Video with ``id == video_id`` or ``None``."""
        for v in self._load():
            if v["id"] == video_id:
                return v
        return None

    def remove(self, video_id: str) -> bool:
        """Remove the video with ``id == video_id``. Returns True if removed.

        Only the index row is dropped — the source file on disk is never deleted
        (refs are by path; deletion is out of scope for a library remove).
        """
        videos = self._load()
        kept = [v for v in videos if v["id"] != video_id]
        if len(kept) == len(videos):
            return False
        self._save(kept)
        return True

    def set_has_transcript(self, video_id: str, value: bool = True) -> Video | None:
        """Mark a video's ``hasTranscript`` flag and persist; returns the Video."""
        videos = self._load()
        result: Video | None = None
        for v in videos:
            if v["id"] == video_id:
                v["hasTranscript"] = bool(value)
                result = v
        if result is not None:
            self._save(videos)
        return result


class Project:
    """A versioned JSON project manifest referencing its source video by path.

    Manifest on disk::

        {"version": 1, "id", "video", "transcript"?, "tracks": [...],
         "clips": [{"candidate", "path"}], "audioTracks": [...], "settings": {...}}

    Refs (the video path and each clip/track ``path``) are stored as written by
    the caller. ``consolidate`` copies those assets *into* the project folder and
    rewrites the refs to be **relative** to the folder, so the project becomes
    self-contained and portable.
    """

    def __init__(self, data: ProjectData, manifest_path: str | os.PathLike | None = None):
        self.data = data
        self.manifest_path = Path(manifest_path) if manifest_path else None

    # ---- construction ------------------------------------------------------
    @classmethod
    def new(cls, video: Video, settings: dict[str, Any] | None = None) -> Project:
        """Create a fresh project around ``video`` with empty tracks/clips."""
        data: ProjectData = {
            "id": _new_id(),
            "video": dict(video),
            "tracks": [],
            "clips": [],
            "settings": dict(settings or {}),
        }
        return cls(data)

    @classmethod
    def open(cls, manifest_path: str | os.PathLike) -> Project:
        """Open a manifest from disk, backfilling any missing schema fields."""
        path = Path(manifest_path)
        raw = _read_json(path)
        if not isinstance(raw, dict):
            raise ValueError(f"invalid project manifest: {manifest_path}")
        data: ProjectData = {
            "id": raw.get("id") or _new_id(),
            "video": raw.get("video") or {},
            "tracks": raw.get("tracks") or [],
            "clips": raw.get("clips") or [],
            "audioTracks": raw.get("audioTracks") or [],  # A3 (T2)
            "settings": raw.get("settings") or {},
        }
        # transcript is optional (only present once transcribed).
        if raw.get("transcript") is not None:
            data["transcript"] = raw["transcript"]
        return cls(data, manifest_path=path)

    # ---- persistence -------------------------------------------------------
    def save(self, manifest_path: str | os.PathLike | None = None) -> Path:
        """Write the manifest (versioned) to disk and return its path."""
        path = Path(manifest_path) if manifest_path else self.manifest_path
        if path is None:
            raise ValueError("no manifest_path given to save()")
        out: dict[str, Any] = {"version": MANIFEST_VERSION}
        out.update(self.data)
        _write_json(path, out)
        self.manifest_path = path
        return path

    # ---- refs --------------------------------------------------------------
    def _ref_paths(self) -> list[str]:
        """Every external file path the manifest references (video + clips + tracks)."""
        refs: list[str] = []
        video = self.data.get("video") or {}
        if video.get("path"):
            refs.append(video["path"])
        for clip in self.data.get("clips") or []:
            if isinstance(clip, dict) and clip.get("path"):
                refs.append(clip["path"])
        for track in self.data.get("tracks") or []:
            if isinstance(track, dict) and track.get("path"):
                refs.append(track["path"])
        return refs

    def find_missing_sources(self) -> list[str]:
        """Return referenced paths that do not currently exist on disk.

        Relative refs are resolved against the manifest's folder when known.
        """
        base = self.manifest_path.parent if self.manifest_path else Path.cwd()
        missing: list[str] = []
        for ref in self._ref_paths():
            p = Path(ref)
            resolved = p if p.is_absolute() else base / p
            if not resolved.exists():
                missing.append(ref)
        return missing

    def consolidate(self, folder: str | os.PathLike) -> str:
        """Copy every referenced asset into ``folder/assets`` and rebase refs.

        After consolidation the manifest's video/clip/track paths are *relative*
        (``assets/<name>``) to ``folder``, the manifest is saved into ``folder``,
        and the absolute folder path is returned. Missing sources are skipped
        (their refs are left untouched) rather than raising, so a partially
        recoverable project can still be consolidated.
        """
        dest = Path(folder)
        assets = dest / "assets"
        assets.mkdir(parents=True, exist_ok=True)

        base = self.manifest_path.parent if self.manifest_path else Path.cwd()
        used: set[str] = set()

        def _copy_in(ref: str) -> str:
            src = Path(ref)
            resolved = src if src.is_absolute() else base / src
            if not resolved.exists():
                return ref  # missing source: leave ref as-is
            name = self._unique_name(resolved.name, used)
            used.add(name)
            shutil.copy2(resolved, assets / name)
            # POSIX-style relative ref keeps manifests portable across OSes.
            return f"assets/{name}"

        video = self.data.get("video") or {}
        if video.get("path"):
            video["path"] = _copy_in(video["path"])
        for clip in self.data.get("clips") or []:
            if isinstance(clip, dict) and clip.get("path"):
                clip["path"] = _copy_in(clip["path"])
        for track in self.data.get("tracks") or []:
            if isinstance(track, dict) and track.get("path"):
                track["path"] = _copy_in(track["path"])

        self.save(dest / "project.json")
        return str(dest.resolve())

    @staticmethod
    def _unique_name(name: str, used: set[str]) -> str:
        """Disambiguate ``name`` against ``used`` (appends -1, -2, ... before ext)."""
        if name not in used:
            return name
        stem = Path(name).stem
        suffix = Path(name).suffix
        i = 1
        while f"{stem}-{i}{suffix}" in used:
            i += 1
        return f"{stem}-{i}{suffix}"
