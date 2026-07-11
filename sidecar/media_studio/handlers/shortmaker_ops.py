# The only inter-module cycle is the TYPE_CHECKING-only Services ref below
# (no runtime cycle); silence the type-only back-edge warning.
# pyright: reportImportCycles=false
"""Composition-root handlers (F4b split): Short-maker select/export + NLE/package export handlers.

Each function is a Services method body extracted verbatim from the former
monolithic handlers.py; `self` is typed against the composed `Services` (bound
in services.py). Behaviour + the RPC surface are byte-identical to pre-split.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from .. import library as _library
from ..features import boundary as _boundary
from ..features import nle_export as _nle_export
from ..features import package_export as _package_export
from ..features import shortmaker as _shortmaker
from ..features import shorts as _shorts_meta
from ..protocol import ErrorCode, RpcContext, RpcError
from ._shared import (
    Candidate,
    _invalid,
    _require_number,
    _require_str,
)
from ._wire import (
    _js_number,
)

if TYPE_CHECKING:  # pragma: no cover - typing-only import, never executed at runtime
    from ._services import Services


def _build_shortmaker(self: Services) -> _shortmaker.ShortMaker:
    """Build a ShortMaker bound to our context loader + selection cache."""
    return _shortmaker.ShortMaker(
        load_context=self._shortmaker_context,
        out_dir_for=lambda vid: str(self.exports_dir / f"shorts-{vid}"),
        stages=_shortmaker.Stages(),
        settings_provider=self.settings.get,
    )


def _detect_boundaries(self: Services, video_id: str) -> dict[str, Any]:
    """Run the silence + scene-cut detectors for a video's path.

    CONTRACT-NOTE: ``_lazy_snap`` reads ``settings["silences"]`` /
    ``settings["sceneCuts"]`` which nothing fills. We detect them here (ffmpeg
    silencedetect + PySceneDetect, both behind the boundary seams) and inject
    them into the settings dict the select job uses, so boundary-snap has real
    silence + scene targets — not just sentence ends. Detection failures fall
    back to empty lists (snap then uses sentence ends only).
    """
    path = self._resolve_video_path(video_id)
    if not path:
        return {"silences": [], "sceneCuts": []}
    silences = _boundary.detect_silences(path, settings=self.settings.get(), run=self._silence_run)
    scene_cuts = _boundary.detect_scene_cuts(path, detector=self._scene_detector)
    return {"silences": list(silences), "sceneCuts": list(scene_cuts)}


def _shortmaker_context(self: Services, video_id: str) -> dict[str, Any]:
    """Load a video's path + transcript + the cached candidate map.

    CONTRACT-NOTE (HIGH-3): exposes the cached select result under
    ``"candidates"`` (id -> Candidate), which ``ShortMaker._resolve_candidates``
    consults when the UI sends only ``candidateIds``.

    CONTRACT-NOTE (A2 audioTrackId): also exposes the manifest's A3
    ``Project.audioTracks`` under ``"audioTracks"`` so the export pipeline
    can resolve ``shortmaker.export``'s optional ``audioTrackId`` and mux
    the chosen track onto each exported clip.
    """
    path = self._resolve_video_path(video_id) or ""
    transcript = None
    audio_tracks: list[dict[str, Any]] = []
    manifest = self._project_path(video_id)
    if manifest.exists():
        try:
            data = _library.Project.open(manifest).data
            transcript = data.get("transcript")
            audio_tracks = list(data.get("audioTracks") or [])
        except Exception:  # noqa: BLE001 - a bad manifest just means no transcript
            transcript = None
            audio_tracks = []
    # P4 §3: the source video title for the persisted ShortInfo metadata.
    video = self.library.get(video_id)
    source_title = str((video or {}).get("title") or "")
    return {
        "path": path,
        "transcript": transcript,
        "sourceTitle": source_title,
        "candidates": self._selection_cache.get(video_id, {}),
        "audioTracks": audio_tracks,
    }


def _ensure_transcript(self: Services, video_id: str, job_ctx: Any) -> None:
    """Auto-transcribe a video for Make-Shorts when it has no usable transcript.

    ``shortmaker.select`` reads the transcript from the manifest (via
    ``_shortmaker_context``); a video the user never transcribed would otherwise
    select ZERO clips. To keep the star flow plug-and-play we produce + persist
    the transcript here — the SAME transcribe+persist path as ``transcribe.start``
    (``_transcribe_and_persist``) — so SELECT has speech to work with. A video
    that already has a usable transcript is left untouched (no wasteful
    re-transcribe). Runs inside the select job, so transcription progress streams
    and a mid-transcribe cancel leaves the manifest unchanged (the persist is
    cancel-gated inside the shared helper).
    """
    project = self._load_or_create_project(video_id)
    if _shortmaker._is_empty_transcript(project.data.get("transcript")):
        self._transcribe_and_persist(video_id, job_ctx)


def shortmaker_select(self: Services, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
    """``shortmaker.select({videoId, prompt, controls})`` -> ``{jobId}`` (§2).

    Wraps the feature pipeline so (a) boundary detectors feed the snap stage
    and (b) the produced candidates are cached server-side (keyed by
    "rank@sourceStart") for a later ``shortmaker.export``.
    """
    if ctx.jobs is None:
        raise RpcError("no job registry available", ErrorCode.INTERNAL_ERROR)
    video_id = _require_str(params, "videoId")
    sm = self._shortmaker()

    def handler(job_ctx: Any) -> dict[str, Any]:
        settings = dict(self.settings.get())
        # Plug-and-play (root-cause fix): Make-Shorts consumes the manifest
        # transcript, but nothing in the select flow used to produce one — a
        # freshly-imported, never-transcribed video selected ZERO clips ("no
        # clips" -> the UI's "No candidates were proposed"). Transcribe + persist
        # it now (once, reused by SELECT/export/subtitles) so the star flow works
        # without a separate manual transcribe step.
        self._ensure_transcript(video_id, job_ctx)
        # Feed the real silence + scene-cut detectors into the snap settings.
        settings.update(self._detect_boundaries(video_id))
        result = _shortmaker.run_select(
            job_ctx,
            video_id=video_id,
            prompt=str(params.get("prompt") or ""),
            controls=params.get("controls") or {},
            load_context=self._shortmaker_context,
            stages=sm.stages,
            settings=settings,
        )
        self._cache_candidates(video_id, result.get("candidates") or [])
        return result

    job = ctx.jobs.start(handler)
    return {"jobId": job.id}


def shortmaker_export(self: Services, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
    """``shortmaker.export({videoId, candidateIds})`` -> ``{jobId}`` (§2).

    Resolution uses the cached select result (HIGH-3): the UI's
    ``candidateIds`` ("rank@sourceStart") index into the per-video cache, so
    export carves the real clips. The UI may also forward full ``candidates``.
    A2's optional ``audioTrackId`` (plus T4b's ``captionStyle`` /
    ``reframeEngine``) flows through ``params`` into ``ShortMaker.export``;
    the AudioTrack itself is resolved against ``_shortmaker_context``'s
    ``audioTracks``.
    """
    if ctx.jobs is None:
        raise RpcError("no job registry available", ErrorCode.INTERNAL_ERROR)
    sm = self._shortmaker()
    return sm.export(params, ctx)


def _approved_clips(self: Services, video_id: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    """Resolve the approved clips to export for ``video_id``.

    Prefers an explicit ``clips`` array on ``params`` (so the UI can export the
    just-produced batch before manifest persistence); otherwise reads the
    project manifest's persisted ``clips`` (the ``{candidate, path}`` records
    the short-maker export carved). Returns ``[]`` when neither has clips.
    """
    explicit = params.get("clips")
    if isinstance(explicit, list) and explicit:
        return [c for c in explicit if isinstance(c, dict)]
    project = self._load_or_create_project(video_id)
    return [c for c in (project.data.get("clips") or []) if isinstance(c, dict)]


def nle_export(self: Services, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
    """``nle.export({videoId, format?, fps?, title?, clips?})`` -> ``{path}`` (captions-export).

    Export the approved clips of a video as an editable NLE timeline: a
    CMX3600 ``.edl`` (default) or a ``.csv`` for Premiere / DaVinci Resolve.
    ``fps`` is one of 24/25/30/60 (default 30); ``title`` names the sequence.
    Per-clip reel names come from each candidate's optional ``reel``. Direct-
    return ``{path}`` (the build is fast, pure-Python — no job needed).
    """
    video_id = _require_str(params, "videoId")
    fmt = str(params.get("format") or "edl")
    fps = _require_number(params, "fps", 30)
    title = params.get("title")
    if not isinstance(title, str) or not title:
        video = self.library.get(video_id)
        title = str((video or {}).get("title") or "Media Studio Timeline")
    clips = self._approved_clips(video_id, params)
    try:
        out_path = self.exports_dir / f"{video_id}-timeline.{_nle_export.normalize_format(fmt)}"
        path = _nle_export.export(clips, out_path, fmt=fmt, fps=fps, title=title)
    except ValueError as exc:
        raise _invalid(str(exc)) from exc
    return {"path": path, "clipCount": len(clips)}


def package_export(self: Services, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
    """``package.export({path, suggestion?})`` -> ``{path, manifest}`` (captions-export).

    Bundle ONE produced short (its rendered ``<clip>.mp4`` + thumbnail + a
    suggested title/description/tags ``upload.json``) into a ``.zip`` for
    manual posting. ``path`` is the exported clip; the clip's sidecar
    ``<clip>.json`` metadata drives the suggested copy (an optional
    ``suggestion`` override wins per-field). The clip MUST live inside the
    exports root (path-traversal guard). Direct-return.
    """
    clip_path = _require_str(params, "path")
    resolved = Path(clip_path).resolve()
    root = self.exports_dir.resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        raise _invalid(f"path is outside the exports root: {clip_path}") from None
    if not resolved.exists():
        raise _invalid(f"short not found: {clip_path}")
    meta = _shorts_meta.read_metadata(resolved) or {}
    thumb = _shorts_meta.thumbnail_path(resolved)
    suggestion = params.get("suggestion")
    suggestion = suggestion if isinstance(suggestion, dict) else None
    out_zip = resolved.with_name(resolved.stem + ".package.zip")
    try:
        result = _package_export.package(
            resolved,
            out_zip,
            meta=meta,
            thumbnail_path=thumb if thumb.exists() else None,
            suggestion=suggestion,
        )
    except FileNotFoundError as exc:
        raise _invalid(str(exc)) from exc
    return result


def _cache_candidates(self: Services, video_id: str, candidates: list[Candidate]) -> None:
    """Cache select candidates keyed by "rank@sourceStart" (the UI's id form)."""
    by_id: dict[str, Candidate] = {}
    for cand in candidates:
        cid = self.candidate_id(cand)
        by_id[cid] = cand
    self._selection_cache[video_id] = by_id


def candidate_id(candidate: Candidate) -> str:
    """Stable candidate id matching ShortMaker.tsx's ``candidateId`` ("rank@sourceStart").

    CONTRACT-NOTE: the renderer builds ``${rank}@${sourceStart}``; we mirror it
    exactly. ``sourceStart`` is rendered the way JS ``String(number)`` would
    (an integer-valued float prints without a trailing ".0").
    """
    rank = candidate.get("rank")
    src = candidate.get("sourceStart", candidate.get("start", 0.0))
    return f"{rank}@{_js_number(src)}"
