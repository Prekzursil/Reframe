"""Multi-lane VIDEO timeline — ``tracks.video.*`` (the direct-manipulation editor).

Wire surface::

    tracks.video.list({videoId, fps?})                     -> {videoTracks, fps}
    tracks.video.addLane({videoId, name?})                 -> {videoTrack}
    tracks.video.removeLane({videoId, videoTrackId})       -> {removed}
    tracks.video.addClip({videoId, videoTrackId, path,
                          srcIn, srcOut, timelineStart})    -> {clip}
    tracks.video.trimClip({videoId, clipId, edge,
                           timelineTime, fps?})             -> {clip}
    tracks.video.splitClip({videoId, clipId,
                            atTimeline, fps?})              -> {clips}
    tracks.video.moveClip({videoId, clipId, timelineStart,
                           videoTrackId?, fps?})            -> {clip}
    tracks.video.removeClip({videoId, clipId})              -> {removed}
    tracks.video.render({videoId, fps?})                    -> {path, segments}

Schema (field names chosen to MIRROR the shipped ``audioTracks`` shape, so the
manifest keeps one convention)::

    VideoClip  {id, path, srcIn, srcOut, timelineStart}
    VideoTrack {id, name, index, clips:[VideoClip]}
    Project.videoTracks: [VideoTrack]

Why there is no ``duration`` field: a clip's length is DERIVED
(``srcOut - srcIn``). Storing it would let the stored value drift from the
source window it describes, which is exactly the "silently drops edits" failure
this module must not have. Every op therefore re-derives it
(:func:`clip_duration`) and the timing invariant

    clip_timeline_end(c) - c["timelineStart"]  ==  c["srcOut"] - c["srcIn"]

holds by construction, in WHOLE FRAMES at the project's fps.

**Frame accuracy.** Every boundary an op produces is snapped to the frame grid
through the SHIPPED quantizer :func:`media_studio.features.nle_export.seconds_to_frames`
(fps restricted to its ``FPS_CHOICES`` — 24/25/30/60), so an edit point is
always an integral frame index. :func:`frame_span` / :func:`frame_source_span`
express the invariant above in integers, which is what the tests assert.

**Rendering reuses the shipped engine, it does not reimplement it.** For a
timeline whose clips all come from ONE source file (the overwhelmingly common
case — trim/razor/reorder of a single video) :func:`build_timeline_render_argv`
delegates VERBATIM to :func:`media_studio.features.fillers.build_segment_cut_argv`
(frame-accurate decode-side ``trim``/``atrim`` + ``concat``, LIST ORDER, no
sort). A multi-source timeline needs one ``-i`` per distinct file, which that
helper cannot express, so this module builds the N-input form — structurally the
same filter graph, asserted byte-identical to the shipped builder in the
single-source case (``tests/test_video_tracks.py::TestEngineReuse``).

**Fail closed.** Anything the model cannot represent RAISES
:class:`VideoTrackError` instead of clamping an edit into silence:

* a trim that would leave less than :data:`MIN_CLIP_FRAMES`;
* a razor cut outside the clip;
* a negative timeline position;
* clips that OVERLAP in time — on one lane or across lanes. Stacked lanes are a
  real video-layer model (park B-roll / alternates, reorder across lanes), but
  compositing two pictures at the same instant needs a compositor
  (cross-fade / picture-in-picture / speed-ramp), which is NOT in this module.
  :func:`flatten_timeline` therefore refuses an overlap and names both clips.
  SEAM for that work: a compositing owner replaces the ``overlap`` refusal in
  :func:`flatten_timeline` with a resolver that emits ``overlay``/``xfade``
  nodes; nothing else here needs to change.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Any

from .. import ffmpeg, protocol
from ..protocol import ErrorCode, RpcContext, RpcError
from ..util import get_logger
from . import fillers as _fillers
from .nle_export import FPS_CHOICES, normalize_fps, seconds_to_frames

log = get_logger("media_studio.video_tracks")

#: A clip on a lane: a source window (``srcIn``..``srcOut``) placed at ``timelineStart``.
VideoClip = dict[str, Any]
#: A lane: an ordered set of non-overlapping clips.
VideoTrack = dict[str, Any]
#: What :func:`flatten_timeline` hands the argv builder.
RenderSegment = dict[str, Any]

#: Timeline frame rate used when neither the call nor the settings pick one.
DEFAULT_FPS = 30
#: The shortest clip an edit may produce. One frame — anything less is not a clip.
MIN_CLIP_FRAMES = 1
#: The two draggable trim handles.
EDGES = ("start", "end")

# Injectable seams (mirroring tracks_audio.py):
RunFn = Callable[..., int]
DurationFn = Callable[..., float]
Resolver = Callable[[str], str | None]
LoadProject = Callable[[str], dict[str, Any]]
SaveProject = Callable[[str, dict[str, Any]], None]


class VideoTrackError(Exception):
    """A video-timeline operation is not representable (bad edit, overlap, missing id)."""


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _invalid(message: str) -> RpcError:
    return RpcError(message, ErrorCode.INVALID_PARAMS)


def _require_str(params: dict[str, Any], key: str) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value:
        raise _invalid(f"{key} (str) is required")
    return value


def _require_number(params: dict[str, Any], key: str) -> float:
    value = params.get(key)
    # bool is an int subclass but never a valid time coordinate (handlers/_shared.py:81).
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _invalid(f"{key} (number) is required")
    return float(value)


# --------------------------------------------------------------------------- #
# pure: the frame grid (delegates to the SHIPPED quantizer)
# --------------------------------------------------------------------------- #
def resolve_fps(value: Any, settings: dict[str, Any] | None = None) -> int:
    """The timeline fps: explicit ``value`` -> ``settings.exportDefaults.nleFps`` -> 30.

    Always one of :data:`~media_studio.features.nle_export.FPS_CHOICES`; an
    unsupported explicit value raises (never silently becomes 30 — a wrong frame
    rate silently mis-snaps every edit point in the project).
    """
    if value is not None:
        try:
            return normalize_fps(value)
        except ValueError as exc:
            raise VideoTrackError(str(exc)) from exc
    export_defaults = (settings or {}).get("exportDefaults")
    if isinstance(export_defaults, dict) and export_defaults.get("nleFps") is not None:
        try:
            return normalize_fps(export_defaults["nleFps"])
        except ValueError:
            log.warning("settings.exportDefaults.nleFps is not one of %s; using %d", FPS_CHOICES, DEFAULT_FPS)
    return DEFAULT_FPS


def snap(seconds: float, fps: int) -> float:
    """``seconds`` quantized onto the ``fps`` frame grid (negatives clamp to 0)."""
    return seconds_to_frames(seconds, fps) / fps


def clip_duration(clip: VideoClip) -> float:
    """The clip's length — DERIVED from its source window, never stored."""
    return float(clip["srcOut"]) - float(clip["srcIn"])


def clip_timeline_end(clip: VideoClip) -> float:
    """Where the clip's tail sits on the program timeline."""
    return float(clip["timelineStart"]) + clip_duration(clip)


def frame_span(clip: VideoClip, fps: int) -> int:
    """The clip's length on the TIMELINE, in whole frames."""
    return seconds_to_frames(clip_timeline_end(clip), fps) - seconds_to_frames(clip["timelineStart"], fps)


def frame_source_span(clip: VideoClip, fps: int) -> int:
    """The clip's length in the SOURCE, in whole frames.

    Equal to :func:`frame_span` for every clip any op in this module produces —
    that equality IS the timing contract.
    """
    return seconds_to_frames(clip["srcOut"], fps) - seconds_to_frames(clip["srcIn"], fps)


# --------------------------------------------------------------------------- #
# pure: the model
# --------------------------------------------------------------------------- #
def normalize_video_clip(clip: dict[str, Any], *, fps: int) -> VideoClip:
    """Backfill + frame-snap a dict to the full VideoClip schema.

    Raises when the window is empty/inverted or the placement is negative — a
    zero-length clip is not a clip, and both are edits we refuse to store.
    """
    if not isinstance(clip, dict):
        raise VideoTrackError("video clip must be an object")
    path = str(clip.get("path") or "")
    if not path:
        raise VideoTrackError("video clip requires a source path")
    in_f = seconds_to_frames(clip.get("srcIn", 0.0), fps)
    out_f = seconds_to_frames(clip.get("srcOut", 0.0), fps)
    start_f = seconds_to_frames(clip.get("timelineStart", 0.0), fps)
    if out_f - in_f < MIN_CLIP_FRAMES:
        raise VideoTrackError(
            f"video clip must span at least {MIN_CLIP_FRAMES} frame(s) at {fps}fps (got {out_f - in_f})"
        )
    return {
        "id": str(clip.get("id") or _new_id()),
        "path": path,
        "srcIn": in_f / fps,
        "srcOut": out_f / fps,
        "timelineStart": start_f / fps,
    }


def normalize_video_track(track: dict[str, Any], *, fps: int) -> VideoTrack:
    """Backfill + frame-snap a dict to the full VideoTrack schema."""
    if not isinstance(track, dict):
        raise VideoTrackError("video track must be an object")
    raw_clips = track.get("clips") or []
    if not isinstance(raw_clips, list):
        raise VideoTrackError("videoTrack.clips must be a list")
    index = track.get("index", 0)
    if isinstance(index, bool) or not isinstance(index, int) or index < 0:
        raise VideoTrackError(f"videoTrack.index must be a non-negative int, got {index!r}")
    return {
        "id": str(track.get("id") or _new_id()),
        "name": str(track.get("name") or f"Video {index + 1}"),
        "index": index,
        "clips": [normalize_video_clip(c, fps=fps) for c in raw_clips],
    }


def video_tracks_of(project: dict[str, Any]) -> list[VideoTrack]:
    """The project's ``videoTracks`` list, created when absent."""
    tracks = project.setdefault("videoTracks", [])
    if not isinstance(tracks, list):
        raise VideoTrackError("project.videoTracks must be a list")
    return tracks


def find_video_track(project: dict[str, Any], track_id: str) -> VideoTrack:
    """The lane whose ``id == track_id`` or raise."""
    for track in video_tracks_of(project):
        if isinstance(track, dict) and track.get("id") == track_id:
            return track
    raise VideoTrackError(f"no such video track: {track_id}")


def find_clip(project: dict[str, Any], clip_id: str) -> tuple[VideoTrack, VideoClip]:
    """The ``(lane, clip)`` pair owning ``clip_id`` or raise."""
    for track in video_tracks_of(project):
        if not isinstance(track, dict):
            continue
        for clip in track.get("clips") or []:
            if isinstance(clip, dict) and clip.get("id") == clip_id:
                return track, clip
    raise VideoTrackError(f"no such video clip: {clip_id}")


def add_video_track(project: dict[str, Any], track: dict[str, Any], *, fps: int) -> VideoTrack:
    """Append a lane (idempotent on an existing id); ``index`` defaults to the next free lane."""
    tracks = video_tracks_of(project)
    payload = dict(track)
    if payload.get("index") is None:
        payload["index"] = len(tracks)
    normalized = normalize_video_track(payload, fps=fps)
    for existing in tracks:
        if isinstance(existing, dict) and existing.get("id") == normalized["id"]:
            return existing
    tracks.append(normalized)
    return normalized


def remove_video_track(project: dict[str, Any], track_id: str) -> VideoTrack:
    """Remove + return the lane (raises when absent)."""
    track = find_video_track(project, track_id)
    project["videoTracks"] = [
        t for t in video_tracks_of(project) if not (isinstance(t, dict) and t.get("id") == track_id)
    ]
    return track


def clips_of(track: VideoTrack) -> list[VideoClip]:
    """The lane's ``clips`` list, created when absent."""
    clips = track.setdefault("clips", [])
    if not isinstance(clips, list):
        raise VideoTrackError("videoTrack.clips must be a list")
    return clips


def add_clip(project: dict[str, Any], track_id: str, clip: dict[str, Any], *, fps: int) -> VideoClip:
    """Place a clip on a lane, refusing an id collision or a time overlap."""
    track = find_video_track(project, track_id)
    normalized = normalize_video_clip(clip, fps=fps)
    for existing in clips_of(track):
        if isinstance(existing, dict) and existing.get("id") == normalized["id"]:
            raise VideoTrackError(f"video clip already exists: {normalized['id']}")
    assert_no_overlap([*clips_of(track), normalized], fps=fps)
    clips_of(track).append(normalized)
    return normalized


def remove_clip(project: dict[str, Any], clip_id: str) -> VideoClip:
    """Remove + return the clip (raises when absent)."""
    track, clip = find_clip(project, clip_id)
    track["clips"] = [c for c in clips_of(track) if not (isinstance(c, dict) and c.get("id") == clip_id)]
    return clip


def replace_clip(track: VideoTrack, clip_id: str, replacements: Sequence[VideoClip]) -> None:
    """Swap ``clip_id`` for ``replacements`` IN PLACE, preserving lane order.

    Used by trim/split/move: the edited clip keeps its slot in the list, so a
    UI that renders lane order sees an in-place change rather than a re-append.
    """
    clips = clips_of(track)
    for i, clip in enumerate(clips):
        if isinstance(clip, dict) and clip.get("id") == clip_id:
            track["clips"] = [*clips[:i], *replacements, *clips[i + 1 :]]
            return
    raise VideoTrackError(f"no such video clip: {clip_id}")


# --------------------------------------------------------------------------- #
# pure: the edit ops (immutable — every one returns NEW clip dicts)
# --------------------------------------------------------------------------- #
def trim_clip_edge(clip: VideoClip, edge: str, timeline_time: float, *, fps: int) -> VideoClip:
    """Drag one trim HANDLE to ``timeline_time`` (the drag-to-trim primitive).

    Trimming is expressed in TIMELINE coordinates because that is what the user
    drags, and the source window follows by the same delta — so the frames under
    the handle never shift (the standard NLE trim, not a re-time):

    * ``edge="start"``: the head moves, the TAIL IS PINNED, ``srcIn`` moves with it;
    * ``edge="end"``: the tail moves, the HEAD IS PINNED, ``srcOut`` moves with it.

    Refuses (never clamps) a trim that would leave under :data:`MIN_CLIP_FRAMES`
    or would need frames before the source's own head. A drag UI clamps its
    PREVIEW to the legal range; the committed value is always legal here.
    """
    if edge not in EDGES:
        raise VideoTrackError(f"edge must be one of {EDGES}, got {edge!r}")
    fps = normalize_fps(fps)
    start_f = seconds_to_frames(clip["timelineStart"], fps)
    end_f = seconds_to_frames(clip_timeline_end(clip), fps)
    in_f = seconds_to_frames(clip["srcIn"], fps)
    at_f = seconds_to_frames(timeline_time, fps)
    if edge == "start":
        if end_f - at_f < MIN_CLIP_FRAMES:
            raise VideoTrackError(f"trim would leave {end_f - at_f} frame(s); a clip needs at least {MIN_CLIP_FRAMES}")
        new_in_f = in_f + (at_f - start_f)
        if new_in_f < 0:
            raise VideoTrackError(f"trim would need frame {new_in_f}, before the source's start")
        return {**clip, "srcIn": new_in_f / fps, "timelineStart": at_f / fps}
    if at_f - start_f < MIN_CLIP_FRAMES:
        raise VideoTrackError(f"trim would leave {at_f - start_f} frame(s); a clip needs at least {MIN_CLIP_FRAMES}")
    # The new tail is derived from the PINNED head, so the source window and the
    # timeline window necessarily stay the same length (the timing invariant).
    new_out_f = in_f + (at_f - start_f)
    return {**clip, "srcOut": new_out_f / fps}


def split_clip(clip: VideoClip, at_timeline: float, *, fps: int) -> tuple[VideoClip, VideoClip]:
    """RAZOR: cut ``clip`` at ``at_timeline`` into two abutting clips.

    Lossless by construction — the halves tile the original exactly (the left's
    ``srcOut`` IS the right's ``srcIn``, and the left's timeline end IS the
    right's ``timelineStart``), so no frame is invented or lost. The left half
    keeps the clip's id (it is still "that clip"); the right half gets a new one.
    """
    fps = normalize_fps(fps)
    start_f = seconds_to_frames(clip["timelineStart"], fps)
    end_f = seconds_to_frames(clip_timeline_end(clip), fps)
    in_f = seconds_to_frames(clip["srcIn"], fps)
    at_f = seconds_to_frames(at_timeline, fps)
    if at_f - start_f < MIN_CLIP_FRAMES or end_f - at_f < MIN_CLIP_FRAMES:
        raise VideoTrackError(
            f"the razor must fall inside the clip with at least {MIN_CLIP_FRAMES} frame(s) either side "
            f"(clip spans frames {start_f}..{end_f}, cut at {at_f})"
        )
    cut_src_f = in_f + (at_f - start_f)
    left: VideoClip = {**clip, "srcOut": cut_src_f / fps}
    right: VideoClip = {
        **clip,
        "id": _new_id(),
        "srcIn": cut_src_f / fps,
        "timelineStart": at_f / fps,
    }
    return left, right


def move_clip(clip: VideoClip, timeline_start: float, *, fps: int) -> VideoClip:
    """SLIDE the clip to ``timeline_start``, preserving its source window exactly.

    Refuses a negative position rather than clamping it to 0 (a clamp turns
    "drag before the head" into a silent no-op the user cannot see).
    """
    fps = normalize_fps(fps)
    if timeline_start < 0:
        raise VideoTrackError(f"timelineStart must be >= 0, got {timeline_start}")
    return {**clip, "timelineStart": seconds_to_frames(timeline_start, fps) / fps}


# --------------------------------------------------------------------------- #
# pure: overlap detection + flatten
# --------------------------------------------------------------------------- #
def _ordered(clips: Iterable[VideoClip], fps: int) -> list[VideoClip]:
    """Clips in TIMELINE order (the order the concat will use)."""
    return sorted(clips, key=lambda c: (seconds_to_frames(c["timelineStart"], fps), str(c.get("id"))))


def assert_no_overlap(clips: Iterable[VideoClip], *, fps: int) -> list[VideoClip]:
    """Return the clips in timeline order, or raise naming the overlapping pair.

    Abutting clips (``a.end == b.start``) are legal and are the normal result of
    a razor cut; a strict inequality is what constitutes an overlap.
    """
    ordered = _ordered(clips, fps)
    for prev, nxt in zip(ordered, ordered[1:], strict=False):
        prev_end_f = seconds_to_frames(clip_timeline_end(prev), fps)
        next_start_f = seconds_to_frames(nxt["timelineStart"], fps)
        if next_start_f < prev_end_f:
            raise VideoTrackError(
                f"clips {prev.get('id')} and {nxt.get('id')} overlap in time "
                f"(frames {next_start_f}..{prev_end_f} at {fps}fps); "
                "compositing two pictures at once needs a transition/overlay engine, which this timeline "
                "deliberately does not fake"
            )
    return ordered


def flatten_timeline(tracks: Sequence[VideoTrack], *, fps: int) -> list[RenderSegment]:
    """Collapse the stacked lanes into ONE ordered, gapless-in-order segment list.

    Every lane's clips are pooled and ordered by ``timelineStart``. Any time
    overlap — within a lane or across lanes — RAISES (see the module docstring's
    fail-closed note and the compositor SEAM).
    """
    fps = normalize_fps(fps)
    pooled: list[VideoClip] = []
    for track in tracks:
        if not isinstance(track, dict):
            raise VideoTrackError("video track must be an object")
        pooled.extend(c for c in clips_of(track) if isinstance(c, dict))
    ordered = assert_no_overlap(pooled, fps=fps)
    return [
        {
            "clipId": c["id"],
            "path": c["path"],
            "srcIn": c["srcIn"],
            "srcOut": c["srcOut"],
            "timelineStart": c["timelineStart"],
        }
        for c in ordered
    ]


def timeline_duration(segments: Sequence[RenderSegment]) -> float:
    """Total rendered length = the sum of the segment durations (concat, not gaps).

    NOTE (honest limitation): ``concat`` butts the kept segments together, so a
    GAP between two clips on the timeline is closed in the render rather than
    filled with black. That is the shipped cutter's semantics
    (``fillers.build_segment_cut_argv``) and this module does not change it.
    """
    return sum(float(s["srcOut"]) - float(s["srcIn"]) for s in segments)


# --------------------------------------------------------------------------- #
# pure: the render argv (single source -> the SHIPPED engine, verbatim)
# --------------------------------------------------------------------------- #
def build_timeline_render_argv(
    segments: Sequence[RenderSegment],
    out_path: str,
    settings: dict[str, Any] | None = None,
) -> list[str]:
    """argv rendering ``segments`` (already in timeline order) to ``out_path``.

    ONE distinct source path -> delegates to the shipped frame-accurate cutter
    :func:`media_studio.features.fillers.build_segment_cut_argv` (byte-identical,
    asserted by test). N distinct paths -> the same filter-graph shape with one
    ``-i`` per distinct file, deduped in order of first use. argv LIST only, so
    paths with spaces survive.
    """
    if not segments:
        raise VideoTrackError("timeline render requires at least one clip")
    keeps = [(float(s["srcIn"]), float(s["srcOut"])) for s in segments]
    paths: list[str] = []
    for seg in segments:
        path = str(seg["path"])
        if path not in paths:
            paths.append(path)
    if len(paths) == 1:
        # The shipped engine, unchanged — no second cut implementation exists.
        return _fillers.build_segment_cut_argv(paths[0], out_path, keeps, settings)

    parts: list[str] = []
    labels: list[str] = []
    for i, seg in enumerate(segments):
        k = paths.index(str(seg["path"]))
        start, end = keeps[i]
        parts.append(f"[{k}:v]trim=start={start:.3f}:end={end:.3f},setpts=PTS-STARTPTS[v{i}]")
        parts.append(f"[{k}:a]atrim=start={start:.3f}:end={end:.3f},asetpts=PTS-STARTPTS[a{i}]")
        labels.append(f"[v{i}][a{i}]")
    parts.append(f"{''.join(labels)}concat=n={len(segments)}:v=1:a=1[v][a]")

    argv: list[str] = [ffmpeg.ffmpeg_path(settings), "-hide_banner", "-nostdin", "-y"]
    for path in paths:
        argv += ["-i", path]
    argv += [
        "-filter_complex",
        ";".join(parts),
        "-map",
        "[v]",
        "-map",
        "[a]",
        "-c:v",
        "libx264",
        "-c:a",
        "aac",
        "-progress",
        "pipe:1",
        "-nostats",
        out_path,
    ]
    return argv


# --------------------------------------------------------------------------- #
# the service
# --------------------------------------------------------------------------- #
class VideoTracksService:
    """Owns the nine ``tracks.video.*`` methods + the manifest persistence."""

    def __init__(
        self,
        *,
        resolver: Resolver,
        load_project: LoadProject,
        save_project: SaveProject,
        out_dir: str | Path,
        settings_provider: Callable[[], dict[str, Any]] | None = None,
        run: RunFn | None = None,
        duration: DurationFn | None = None,
    ) -> None:
        self._resolver = resolver
        self._load_project = load_project
        self._save_project = save_project
        self._out_dir = Path(out_dir)
        self._settings_provider = settings_provider or (lambda: {})
        self._run: RunFn = run or ffmpeg.run
        self._duration: DurationFn = duration or ffmpeg.ffprobe_duration
        # Per-video locks guard reload->mutate->save, never held across ffmpeg
        # (mirrors AudioTracksService).
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    # -- internals ---------------------------------------------------------
    def _lock_for(self, video_id: str) -> threading.Lock:
        with self._locks_guard:
            lock = self._locks.get(video_id)
            if lock is None:
                lock = threading.Lock()
                self._locks[video_id] = lock
            return lock

    def _settings(self) -> dict[str, Any]:
        try:
            return dict(self._settings_provider() or {})
        except Exception:  # noqa: BLE001 - settings must never break an edit
            return {}

    def _resolve(self, video_id: str) -> str:
        path = self._resolver(video_id)
        if not path:
            raise _invalid(f"unknown video: {video_id}")
        return str(path)

    def _fps(self, params: dict[str, Any]) -> int:
        try:
            return resolve_fps(params.get("fps"), self._settings())
        except VideoTrackError as exc:
            raise _invalid(str(exc)) from exc

    def _probe_duration(self, path: str) -> float:
        try:
            return float(self._duration(path, self._settings()))
        except Exception:  # noqa: BLE001 - a probe failure only skips a bound check
            log.warning("duration probe failed for %s; source-length checks are skipped", path)
            return 0.0

    def _seed_base_lane(self, project: dict[str, Any], video_path: str, fps: int) -> bool:
        """On first contact, lay the source down as one full-length clip on lane 0.

        Returns whether anything changed. Needs the source duration; when the
        probe yields nothing usable the lane is created EMPTY rather than seeded
        with a guessed length (a fabricated duration would mis-place every later
        edit).
        """
        if video_tracks_of(project):
            return False
        total = self._probe_duration(video_path)
        clips: list[dict[str, Any]] = []
        if seconds_to_frames(total, fps) >= MIN_CLIP_FRAMES:
            clips = [{"id": _new_id(), "path": video_path, "srcIn": 0.0, "srcOut": total, "timelineStart": 0.0}]
        else:
            log.warning("no usable duration for %s; seeding an EMPTY base lane", video_path)
        project["videoTracks"] = [normalize_video_track({"index": 0, "name": "Video 1", "clips": clips}, fps=fps)]
        return True

    def _run_or_raise(self, argv: list[str], total_sec: float, what: str) -> None:
        code = self._run(argv, total_sec=total_sec)
        if code != 0:
            raise RpcError(f"{what} failed (ffmpeg exit {code})", ErrorCode.INTERNAL_ERROR)

    def _tracks_payload(self, project: dict[str, Any]) -> list[VideoTrack]:
        return [{**t, "clips": [dict(c) for c in clips_of(t)]} for t in video_tracks_of(project) if isinstance(t, dict)]

    def _edit(self, video_id: str, clip_id: str, fps: int, apply: Callable[[VideoTrack, VideoClip], list[VideoClip]]):
        """Load -> locate the clip -> ``apply`` -> overlap-check -> save, under the lock."""
        with self._lock_for(video_id):
            project = self._load_project(video_id)
            try:
                track, clip = find_clip(project, clip_id)
                replacements = apply(track, clip)
                survivors = [c for c in clips_of(track) if c.get("id") != clip_id]
                assert_no_overlap([*survivors, *replacements], fps=fps)
                replace_clip(track, clip_id, replacements)
            except VideoTrackError as exc:
                raise _invalid(str(exc)) from exc
            self._save_project(video_id, project)
            return [dict(c) for c in replacements]

    # -- wire methods --------------------------------------------------------
    def list(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``tracks.video.list({videoId, fps?})`` -> ``{videoTracks, fps}``."""
        video_id = _require_str(params, "videoId")
        video_path = self._resolve(video_id)
        fps = self._fps(params)
        with self._lock_for(video_id):
            project = self._load_project(video_id)
            try:
                if self._seed_base_lane(project, video_path, fps):
                    self._save_project(video_id, project)
                payload = self._tracks_payload(project)
            except VideoTrackError as exc:
                raise _invalid(str(exc)) from exc
        return {"videoTracks": payload, "fps": fps}

    def add_lane(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``tracks.video.addLane({videoId, name?})`` -> ``{videoTrack}``."""
        video_id = _require_str(params, "videoId")
        fps = self._fps(params)
        name = params.get("name")
        with self._lock_for(video_id):
            project = self._load_project(video_id)
            try:
                # video_tracks_of is INSIDE the try: a corrupt persisted manifest must
                # surface as a typed INVALID_PARAMS, not leak as an internal error.
                payload: dict[str, Any] = {"index": len(video_tracks_of(project))}
                if name:
                    payload["name"] = str(name)
                track = add_video_track(project, payload, fps=fps)
            except VideoTrackError as exc:
                raise _invalid(str(exc)) from exc
            self._save_project(video_id, project)
            return {"videoTrack": dict(track)}

    def remove_lane(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``tracks.video.removeLane({videoId, videoTrackId})`` -> ``{removed}``."""
        video_id = _require_str(params, "videoId")
        track_id = _require_str(params, "videoTrackId")
        with self._lock_for(video_id):
            project = self._load_project(video_id)
            try:
                removed = remove_video_track(project, track_id)
            except VideoTrackError as exc:
                raise _invalid(str(exc)) from exc
            self._save_project(video_id, project)
            return {"removed": removed["id"], "clips": len(removed.get("clips") or [])}

    def add_clip(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``tracks.video.addClip({videoId, videoTrackId, path, srcIn, srcOut, timelineStart})``."""
        video_id = _require_str(params, "videoId")
        track_id = _require_str(params, "videoTrackId")
        path = _require_str(params, "path")
        src_in = _require_number(params, "srcIn")
        src_out = _require_number(params, "srcOut")
        timeline_start = _require_number(params, "timelineStart")
        fps = self._fps(params)
        if not Path(path).is_file():
            raise _invalid(f"source file not found: {path}")
        self._assert_within_source(path, src_out, fps)
        with self._lock_for(video_id):
            project = self._load_project(video_id)
            try:
                clip = add_clip(
                    project,
                    track_id,
                    {"path": path, "srcIn": src_in, "srcOut": src_out, "timelineStart": timeline_start},
                    fps=fps,
                )
            except VideoTrackError as exc:
                raise _invalid(str(exc)) from exc
            self._save_project(video_id, project)
            return {"clip": dict(clip)}

    def _assert_within_source(self, path: str, src_out: float, fps: int) -> None:
        """Refuse a source window that runs past the file's own end.

        Without this the model would happily store ``srcOut`` beyond EOF and
        ffmpeg would quietly emit a SHORTER segment than the timeline promised —
        a silently dropped edit. One frame of slack absorbs container rounding.
        """
        total = self._probe_duration(path)
        if total <= 0:
            return  # probe unavailable: disclosed by the warning in _probe_duration
        if seconds_to_frames(src_out, fps) > seconds_to_frames(total, fps) + 1:
            raise _invalid(f"srcOut {src_out} runs past the end of {path} ({total:.3f}s)")

    def trim_clip(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``tracks.video.trimClip({videoId, clipId, edge, timelineTime, fps?})`` -> ``{clip}``."""
        video_id = _require_str(params, "videoId")
        clip_id = _require_str(params, "clipId")
        edge = _require_str(params, "edge")
        timeline_time = _require_number(params, "timelineTime")
        fps = self._fps(params)
        updated = self._edit(
            video_id,
            clip_id,
            fps,
            lambda _track, clip: [trim_clip_edge(clip, edge, timeline_time, fps=fps)],
        )
        return {"clip": updated[0]}

    def split_clip(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``tracks.video.splitClip({videoId, clipId, atTimeline, fps?})`` -> ``{clips}``."""
        video_id = _require_str(params, "videoId")
        clip_id = _require_str(params, "clipId")
        at_timeline = _require_number(params, "atTimeline")
        fps = self._fps(params)
        halves = self._edit(
            video_id,
            clip_id,
            fps,
            lambda _track, clip: list(split_clip(clip, at_timeline, fps=fps)),
        )
        return {"clips": halves}

    def move_clip(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``tracks.video.moveClip({videoId, clipId, timelineStart, videoTrackId?, fps?})`` -> ``{clip}``.

        ``videoTrackId`` moves the clip to ANOTHER lane (the reorder-across-lanes
        gesture); omitted, the clip slides within its own lane.
        """
        video_id = _require_str(params, "videoId")
        clip_id = _require_str(params, "clipId")
        timeline_start = _require_number(params, "timelineStart")
        target_lane = params.get("videoTrackId")
        fps = self._fps(params)
        if target_lane is None:
            moved = self._edit(video_id, clip_id, fps, lambda _t, clip: [move_clip(clip, timeline_start, fps=fps)])
            return {"clip": moved[0]}
        with self._lock_for(video_id):
            project = self._load_project(video_id)
            try:
                source_track, clip = find_clip(project, clip_id)
                dest = find_video_track(project, str(target_lane))
                moved_clip = move_clip(clip, timeline_start, fps=fps)
                keep = [c for c in clips_of(dest) if c.get("id") != clip_id]
                assert_no_overlap([*keep, moved_clip], fps=fps)
                source_track["clips"] = [c for c in clips_of(source_track) if c.get("id") != clip_id]
                clips_of(dest).append(moved_clip)
            except VideoTrackError as exc:
                raise _invalid(str(exc)) from exc
            self._save_project(video_id, project)
            return {"clip": dict(moved_clip), "videoTrackId": dest["id"]}

    def remove_clip(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``tracks.video.removeClip({videoId, clipId})`` -> ``{removed}``."""
        video_id = _require_str(params, "videoId")
        clip_id = _require_str(params, "clipId")
        with self._lock_for(video_id):
            project = self._load_project(video_id)
            try:
                removed = remove_clip(project, clip_id)
            except VideoTrackError as exc:
                raise _invalid(str(exc)) from exc
            self._save_project(video_id, project)
            return {"removed": removed["id"]}

    def render(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``tracks.video.render({videoId, fps?})`` -> ``{path, segments, durationSec}``.

        Renders the CURRENT timeline through the shipped frame-accurate engine.
        Refuses (rather than half-renders) when the timeline is empty or holds an
        overlap.
        """
        video_id = _require_str(params, "videoId")
        fps = self._fps(params)
        with self._lock_for(video_id):
            project = self._load_project(video_id)
            try:
                segments = flatten_timeline(self._tracks_payload(project), fps=fps)
            except VideoTrackError as exc:
                raise _invalid(str(exc)) from exc
        total = timeline_duration(segments)
        self._out_dir.mkdir(parents=True, exist_ok=True)
        out_path = str(self._out_dir / f"timeline-{video_id}-{int(time.time())}.mp4")
        try:
            argv = build_timeline_render_argv(segments, out_path, self._settings())
        except VideoTrackError as exc:
            raise _invalid(str(exc)) from exc
        self._run_or_raise(argv, total, "timeline render")
        log.info("rendered %d timeline segment(s) for %s -> %s", len(segments), video_id, out_path)
        return {"path": out_path, "segments": segments, "durationSec": round(total, 3)}


# --------------------------------------------------------------------------- #
# registration
# --------------------------------------------------------------------------- #
def register(
    *,
    resolver: Resolver,
    load_project: LoadProject,
    save_project: SaveProject,
    out_dir: str | Path,
    settings_provider: Callable[[], dict[str, Any]] | None = None,
    run: RunFn | None = None,
    duration: DurationFn | None = None,
    register_fn: Callable[[str, Any], None] | None = None,
) -> VideoTracksService:
    """Create the service and register the nine ``tracks.video.*`` methods."""
    service = VideoTracksService(
        resolver=resolver,
        load_project=load_project,
        save_project=save_project,
        out_dir=out_dir,
        settings_provider=settings_provider,
        run=run,
        duration=duration,
    )
    reg = register_fn if register_fn is not None else protocol.register
    reg("tracks.video.list", service.list)
    reg("tracks.video.addLane", service.add_lane)
    reg("tracks.video.removeLane", service.remove_lane)
    reg("tracks.video.addClip", service.add_clip)
    reg("tracks.video.trimClip", service.trim_clip)
    reg("tracks.video.splitClip", service.split_clip)
    reg("tracks.video.moveClip", service.move_clip)
    reg("tracks.video.removeClip", service.remove_clip)
    reg("tracks.video.render", service.render)
    log.info("registered the nine tracks.video.* methods")
    return service


__all__ = [
    "DEFAULT_FPS",
    "EDGES",
    "MIN_CLIP_FRAMES",
    "RenderSegment",
    "VideoClip",
    "VideoTrack",
    "VideoTrackError",
    "VideoTracksService",
    "add_clip",
    "add_video_track",
    "assert_no_overlap",
    "build_timeline_render_argv",
    "clip_duration",
    "clip_timeline_end",
    "clips_of",
    "find_clip",
    "find_video_track",
    "flatten_timeline",
    "frame_source_span",
    "frame_span",
    "move_clip",
    "normalize_video_clip",
    "normalize_video_track",
    "register",
    "remove_clip",
    "remove_video_track",
    "replace_clip",
    "resolve_fps",
    "snap",
    "split_clip",
    "timeline_duration",
    "trim_clip_edge",
    "video_tracks_of",
]
