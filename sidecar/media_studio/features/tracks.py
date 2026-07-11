"""Subtitle / track management on a Project (CONTRACTS.md sections 2/3/4/6).

This unit owns the ``tracks.*`` public surface:

  - **list / rename / relabel / add / remove** — manifest-level edits to a
    Project's ``tracks`` list (each entry a ``SubtitleTrack`` per section 3).
  - **burn** — *hardcoded* subtitles via **libass through ffmpeg** (the
    ``subtitles=`` video filter); produces a new file (``-> {path}``) and runs
    as a job (``-> {jobId}``).
  - **soft-mux** — multiplex a subtitle stream into the container *without*
    re-encoding the picture (a removable, toggleable track).
  - **strip** — re-mux the container *omitting* one chosen subtitle stream.

Design rules taken straight from the contract:

  * ``SubtitleTrack`` = ``{id, lang, name, format, kind:"soft"|"hard", cues}``;
    field names are frozen (section 3). Tracks may also carry an optional
    ``path`` (the on-disk sidecar/burned asset) — ``library.Project`` already
    treats ``track["path"]`` as a consolidatable ref.
  * A burned-in (``kind == "hard"``) track is part of the picture and therefore
    **cannot be removed** — :func:`remove_track` surfaces that as a
    :class:`HardSubtitleError` rather than silently dropping the row.
  * All ffmpeg invocation uses **argv lists** (never ``shell=True``) so paths
    with spaces are safe (section 6). Cue text rendered into an ASS sidecar is
    **escaped** so no raw ``{``/``}`` ASS override block can be injected
    (section 4).

This module is pure logic + argv construction + an injectable subprocess seam:
the heavy ffmpeg run is delegated to :mod:`media_studio.ffmpeg` (mockable). No
heavy-ML imports here, so the unit tests stay light.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from .. import ffmpeg
from ..jobs import JobContext
from ..util import get_logger
from .tracks_audio import probe_streams

log = get_logger("media_studio.tracks")

# Type aliases mirroring CONTRACTS.md section 3 (keep field names identical).
Cue = dict[str, Any]
SubtitleTrack = dict[str, Any]

# A track's ``kind`` (section 3): a soft, removable stream vs a burned-in,
# part-of-the-picture overlay.
KIND_SOFT = "soft"
KIND_HARD = "hard"

# Subtitle sidecar formats the contract speaks (subtitles.export: srt|ass|vtt).
_SUBTITLE_FORMATS = ("srt", "ass", "vtt")

# ffmpeg's text-subtitle muxers per container. MP4/MOV want mov_text; MKV and
# most others can carry the original codec, so we copy for those.
_MOV_CONTAINERS = (".mp4", ".mov", ".m4v")


class TrackError(Exception):
    """A track operation failed (bad input, missing track, ...)."""


class TrackNotFoundError(TrackError):
    """The requested ``trackId`` is not on the Project."""


class HardSubtitleError(TrackError):
    """A burned-in (``kind == "hard"``) subtitle cannot be removed.

    Surfaced explicitly (CONTRACTS.md: "Hardcoded subs cannot be removed —
    surface that") so the UI can tell the user a hard track is baked into the
    picture and is not a removable stream.
    """


# --------------------------------------------------------------------------- #
# Project-tracks helpers (pure manifest edits)
# --------------------------------------------------------------------------- #
def _tracks_of(project: dict[str, Any]) -> list[SubtitleTrack]:
    """Return the project's ``tracks`` list, creating it if absent."""
    tracks = project.setdefault("tracks", [])
    if not isinstance(tracks, list):
        raise TrackError("project.tracks must be a list")
    return tracks


def find_track(project: dict[str, Any], track_id: str) -> SubtitleTrack:
    """Return the track whose ``id == track_id`` or raise.

    :raises TrackNotFoundError: when no track on the project matches.
    """
    for track in _tracks_of(project):
        if isinstance(track, dict) and track.get("id") == track_id:
            return track
    raise TrackNotFoundError(f"no such track: {track_id}")


def list_tracks(project: dict[str, Any]) -> list[SubtitleTrack]:
    """Return the project's tracks (``tracks.list`` -> ``{tracks}``)."""
    return list(_tracks_of(project))


def add_track(project: dict[str, Any], track: SubtitleTrack) -> SubtitleTrack:
    """Append ``track`` to the project, normalizing it to the section-3 schema.

    Re-adding a track with an id already present is idempotent (the existing
    row is returned unchanged) rather than creating a duplicate.
    """
    normalized = normalize_track(track)
    tracks = _tracks_of(project)
    for existing in tracks:
        if isinstance(existing, dict) and existing.get("id") == normalized["id"]:
            return existing
    tracks.append(normalized)
    return normalized


def remove_track(project: dict[str, Any], track_id: str) -> SubtitleTrack:
    """Remove a soft track from the project and return it.

    :raises TrackNotFoundError: when the track is not present.
    :raises HardSubtitleError: when the track is ``kind == "hard"`` — a burned-in
        subtitle is baked into the picture and cannot be removed.
    """
    track = find_track(project, track_id)
    if track.get("kind") == KIND_HARD:
        raise HardSubtitleError(f"track {track_id!r} is burned-in (hardcoded) and cannot be removed")
    tracks = _tracks_of(project)
    project["tracks"] = [t for t in tracks if not (isinstance(t, dict) and t.get("id") == track_id)]
    return track


def rename_track(project: dict[str, Any], track_id: str, name: str) -> SubtitleTrack:
    """Set a track's human ``name`` (``tracks.rename``). Returns the track."""
    if not isinstance(name, str) or not name.strip():
        raise TrackError("name must be a non-empty string")
    track = find_track(project, track_id)
    track["name"] = name
    return track


def relabel_track(project: dict[str, Any], track_id: str, lang: str) -> SubtitleTrack:
    """Set a track's BCP-47 ``lang`` (``tracks.relabel``). Returns the track."""
    if not isinstance(lang, str) or not lang.strip():
        raise TrackError("lang must be a non-empty string")
    track = find_track(project, track_id)
    track["lang"] = lang
    return track


def normalize_track(track: dict[str, Any]) -> SubtitleTrack:
    """Backfill a track dict to the full section-3 SubtitleTrack schema.

    Field names are frozen: ``{id, lang, name, format, kind, cues}``. A missing
    ``kind`` defaults to ``"soft"`` (the common, removable case); an unknown
    ``kind`` value is rejected so a typo never produces an unremovable track.
    """
    if not isinstance(track, dict):
        raise TrackError("track must be an object")
    track_id = track.get("id")
    if not isinstance(track_id, str) or not track_id:
        raise TrackError("track.id (str) is required")
    kind = track.get("kind", KIND_SOFT)
    if kind not in (KIND_SOFT, KIND_HARD):
        raise TrackError(f"track.kind must be 'soft' or 'hard', got {kind!r}")
    fmt = track.get("format") or "srt"
    normalized: SubtitleTrack = {
        "id": track_id,
        "lang": track.get("lang") or "und",
        "name": track.get("name") or track_id,
        "format": fmt,
        "kind": kind,
        "cues": list(track.get("cues") or []),
    }
    # Preserve the optional on-disk asset ref (a sidecar .srt/.ass or burned mp4)
    # so library.Project.consolidate can rebase it.
    if track.get("path"):
        normalized["path"] = track["path"]
    return normalized


# --------------------------------------------------------------------------- #
# ASS sidecar generation (libass) — escaping per CONTRACTS.md section 4
# --------------------------------------------------------------------------- #
def ass_escape(text: str) -> str:
    r"""Escape cue text for safe embedding in an ASS dialogue line.

    CONTRACTS.md section 4: "escape cue text (no raw ``{``/``}`` ASS override
    injection)". libass treats ``{...}`` as an override block and a bare
    backslash as the start of an escape (``\N`` newline, ``\h`` hard space), so:

      * ``\`` -> ``\\``   (neutralize override escapes)
      * ``{`` -> ``\{`` and ``}`` -> ``\}``  (no override-block injection)
      * literal newlines -> the ASS soft line-break ``\N``

    The result is safe to drop into a ``Dialogue:`` line's text field.
    """
    out = (text or "").replace("\\", "\\\\")
    out = out.replace("{", "\\{").replace("}", "\\}")
    out = out.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\N")
    return out


def _ass_timestamp(seconds: float) -> str:
    """Format ``seconds`` as an ASS ``H:MM:SS.cc`` timestamp (centiseconds)."""
    seconds = max(0.0, float(seconds))
    centis_total = int(round(seconds * 100))
    cs = centis_total % 100
    total_s = centis_total // 100
    s = total_s % 60
    m = (total_s // 60) % 60
    h = total_s // 3600
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"


def build_ass_document(
    cues: Sequence[Cue],
    width: int = 1080,
    height: int = 1920,
    source_start: float = 0.0,
) -> str:
    """Render ``cues`` into a complete ASS subtitle document string.

    - Sized for ``width`` x ``height`` (``PlayResX``/``PlayResY``), matching the
      CaptionEngine sizing convention (section 4).
    - Cue times are **re-based** by subtracting ``source_start`` (a clip's start
      in the original video) so captions line up with the clip's local t=0
      (section 3 ``Candidate.sourceStart`` / section 4).
    - Every cue's text is run through :func:`ass_escape`.

    Cues that fall entirely before the rebase point (end <= 0 after subtraction)
    are dropped; a cue straddling t=0 is clamped to start at 0.
    """
    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {int(width)}\n"
        f"PlayResY: {int(height)}\n"
        "WrapStyle: 0\n"
        "ScaledBorderAndShadow: yes\n"
        "\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, "
        "BackColour, Bold, Italic, BorderStyle, Outline, Shadow, Alignment, "
        "MarginL, MarginR, MarginV, Encoding\n"
        "Style: Default,Arial,64,&H00FFFFFF,&H00000000,&H00000000,"
        "-1,0,1,3,0,2,40,40,80,1\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, "
        "MarginV, Effect, Text\n"
    )
    lines: list[str] = [header]
    for cue in cues:
        start = float(cue.get("start", 0.0)) - float(source_start)
        end = float(cue.get("end", 0.0)) - float(source_start)
        if end <= 0:
            continue
        start = max(0.0, start)
        text = ass_escape(str(cue.get("text", "")))
        lines.append(f"Dialogue: 0,{_ass_timestamp(start)},{_ass_timestamp(end)},Default,,0,0,0,,{text}\n")
    return "".join(lines)


# --------------------------------------------------------------------------- #
# ffmpeg argv builders for burn / soft-mux / strip
# --------------------------------------------------------------------------- #
def _ass_filter_path(ass_path: str) -> str:
    r"""Escape an ASS path for use inside the ffmpeg ``subtitles=`` filter.

    Inside ``-vf``, ffmpeg parses the filtergraph: backslashes, colons (Windows
    drive letters), single quotes, and ``[]`` are special. Wrapping the value in
    single quotes and escaping ``\`` and ``:`` keeps a real Windows path like
    ``C:\a b\subs.ass`` intact as a *single* argv element. An embedded single
    quote is emitted via the ``'\''`` idiom (close the quote, an escaped literal
    quote, reopen) so a path like ``C:\a\O'Brien\subs.ass`` survives the ffmpeg
    single-quoted filtergraph instead of terminating the quoted value early.
    """
    escaped = ass_path.replace("\\", "\\\\").replace(":", "\\:").replace("'", "'\\''")
    return f"subtitles='{escaped}'"


def build_burn_argv(
    in_path: str,
    ass_path: str,
    out_path: str,
    settings: dict[str, Any] | None = None,
) -> list[str]:
    """argv to **hardcode** (burn) an ASS subtitle into the video via libass.

    Uses the ``subtitles=`` video filter (libass), which re-encodes the video
    with the captions painted on — the result has no separate, removable
    subtitle stream. ``-map 0`` keeps ALL source streams (every audio track — a
    muxed dub included — and every pre-existing soft-subtitle stream) so nothing
    is silently dropped by ffmpeg's most-channels auto stream selection; audio
    and any copied soft-sub streams are stream-copied (the sub codec picked for
    the output container). ``-progress pipe:1`` is wired so :func:`ffmpeg.run`
    can report progress.
    """
    return [
        ffmpeg.ffmpeg_path(settings),
        "-hide_banner",
        "-nostdin",
        "-y",
        "-i",
        in_path,
        "-map",
        "0",
        "-vf",
        _ass_filter_path(ass_path),
        "-c:a",
        "copy",
        "-c:s",
        _subtitle_codec_for(out_path),
        "-progress",
        "pipe:1",
        "-nostats",
        out_path,
    ]


def _subtitle_codec_for(out_path: str) -> str:
    """Pick the text-subtitle codec for the output container.

    MP4/MOV/M4V need ``mov_text``; everything else (MKV, ...) can carry the
    source codec, so we ``copy``.
    """
    return "mov_text" if Path(out_path).suffix.lower() in _MOV_CONTAINERS else "copy"


def build_soft_mux_argv(
    in_path: str,
    sub_path: str,
    out_path: str,
    lang: str | None = None,
    settings: dict[str, Any] | None = None,
    existing_sub_count: int = 0,
) -> list[str]:
    """argv to **soft-mux** a subtitle sidecar into the container.

    Both the video input and the subtitle sidecar are mapped; the picture is
    stream-copied (no re-encode), so the subtitle becomes a *removable* track.
    The subtitle codec is chosen for the output container; the track's language
    metadata is tagged when ``lang`` is given.

    Because ``-map 0`` (all input-0 streams) precedes ``-map 1`` (the sidecar),
    the newly added subtitle is the LAST subtitle stream in the output. Its
    output subtitle-stream index therefore equals ``existing_sub_count`` — the
    number of subtitle streams the input already carried — so the ``language``
    tag lands on the new track, not a pre-existing one.
    """
    argv = [
        ffmpeg.ffmpeg_path(settings),
        "-hide_banner",
        "-nostdin",
        "-y",
        "-i",
        in_path,
        "-i",
        sub_path,
        "-map",
        "0",
        "-map",
        "1",
        "-c",
        "copy",
        "-c:s",
        _subtitle_codec_for(out_path),
    ]
    if lang:
        # Tag the *newly added* subtitle stream (the last s-stream, whose output
        # index == the count of pre-existing subtitle streams) with its lang.
        argv += [f"-metadata:s:s:{existing_sub_count}", f"language={lang}"]
    argv += ["-progress", "pipe:1", "-nostats", out_path]
    return argv


def _probe_subtitle_count(
    in_path: str,
    settings: dict[str, Any] | None = None,
    runner: Callable[..., Any] = subprocess.run,
) -> int:
    """Count the subtitle streams already in ``in_path`` (fail-loud).

    Delegates to the shared :func:`media_studio.features.tracks_audio.probe_streams`
    ffprobe ``-show_streams`` seam — one canonical probe instead of a second
    bespoke ffprobe subprocess call — and counts the ``codec_type == "subtitle"``
    streams. ``probe_streams`` returns ``{}`` on any probe failure, which we
    surface as a :class:`TrackError` rather than silently defaulting to 0 (which
    would re-tag the wrong stream). ``runner`` stays injectable so tests never
    spawn a real ffprobe.
    """
    probe = probe_streams(in_path, settings, runner)
    if not probe:
        raise TrackError("subtitle-stream probe failed")
    return sum(1 for s in probe.get("streams", []) if s.get("codec_type") == "subtitle")


def build_strip_argv(
    in_path: str,
    out_path: str,
    sub_stream_index: int = 0,
    settings: dict[str, Any] | None = None,
) -> list[str]:
    """argv to re-mux the container **omitting** one chosen subtitle stream.

    Maps everything (``-map 0``) then negatively maps the chosen subtitle stream
    (``-map -0:s:<index>``); all kept streams are copied (no re-encode). This is
    the "strip a subtitle" operation — a mux WITHOUT the selected sub stream
    (CONTRACTS.md section 2 ``tracks.strip``).
    """
    if sub_stream_index < 0:
        raise TrackError("sub_stream_index must be >= 0")
    return [
        ffmpeg.ffmpeg_path(settings),
        "-hide_banner",
        "-nostdin",
        "-y",
        "-i",
        in_path,
        "-map",
        "0",
        "-map",
        f"-0:s:{sub_stream_index}",
        "-c",
        "copy",
        "-progress",
        "pipe:1",
        "-nostats",
        out_path,
    ]


# --------------------------------------------------------------------------- #
# write the ASS sidecar (filesystem I/O, no subprocess)
# --------------------------------------------------------------------------- #
def write_ass_sidecar(
    cues: Sequence[Cue],
    out_path: str | os.PathLike,
    width: int = 1080,
    height: int = 1920,
    source_start: float = 0.0,
) -> str:
    """Render ``cues`` to an ASS file at ``out_path`` and return its path."""
    doc = build_ass_document(cues, width=width, height=height, source_start=source_start)
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(doc, encoding="utf-8")
    return str(p)


# --------------------------------------------------------------------------- #
# high-level operations (compose argv + the ffmpeg run seam)
# --------------------------------------------------------------------------- #
def _default_out_path(in_path: str, suffix: str, ext: str | None = None) -> str:
    """Derive a sibling output path: ``<stem><suffix><ext>``."""
    p = Path(in_path)
    out_ext = ext if ext is not None else p.suffix
    return str(p.with_name(f"{p.stem}{suffix}{out_ext}"))


def burn_track(
    in_path: str,
    track: SubtitleTrack,
    out_path: str | None = None,
    *,
    width: int = 1080,
    height: int = 1920,
    source_start: float = 0.0,
    settings: dict[str, Any] | None = None,
    ctx: JobContext | None = None,
    ass_path: str | None = None,
    run: Callable[..., int] = ffmpeg.run,
    duration: Callable[..., float] = ffmpeg.ffprobe_duration,
) -> str:
    """Burn (hardcode) ``track``'s cues into ``in_path``; return the output path.

    Generates an ASS sidecar from the track's cues (escaped, re-based by
    ``source_start``, sized ``width`` x ``height``), then runs ffmpeg with the
    libass ``subtitles=`` filter. ``run`` / ``duration`` are injectable so the
    ffmpeg subprocess is fully mockable in tests. Progress is reported through
    ``ctx`` when supplied (the job seam).
    """
    out_path = out_path or _default_out_path(in_path, "-hardsub", ".mp4")
    sidecar = ass_path or _default_out_path(in_path, "-captions", ".ass")
    write_ass_sidecar(
        track.get("cues") or [],
        sidecar,
        width=width,
        height=height,
        source_start=source_start,
    )
    argv = build_burn_argv(in_path, sidecar, out_path, settings)
    total = _safe_duration(duration, in_path, settings)
    on_progress = (lambda pct, msg: ctx.progress(pct, msg)) if ctx is not None else None
    should_cancel = (lambda: ctx.cancelled) if ctx is not None else None
    code = run(
        argv,
        total_sec=total,
        on_progress=on_progress,
        should_cancel=should_cancel,
    )
    if code != 0:
        raise TrackError(f"burn-in failed (ffmpeg exit {code})")
    return out_path


def soft_mux_track(
    in_path: str,
    sub_path: str,
    track: SubtitleTrack,
    out_path: str | None = None,
    *,
    settings: dict[str, Any] | None = None,
    ctx: JobContext | None = None,
    run: Callable[..., int] = ffmpeg.run,
    duration: Callable[..., float] = ffmpeg.ffprobe_duration,
    sub_count: Callable[..., int] = _probe_subtitle_count,
) -> str:
    """Soft-mux ``sub_path`` into ``in_path`` as a removable track; return path.

    Probes how many subtitle streams ``in_path`` already carries (``sub_count``,
    injectable) so the new track's ``language`` tag lands on the appended stream
    rather than a pre-existing one. A probe failure raises :class:`TrackError`
    (fail loud — no silent 0 fallback that would mistag).
    """
    out_path = out_path or _default_out_path(in_path, "-softsub", ".mkv")
    existing_sub_count = sub_count(in_path, settings)
    argv = build_soft_mux_argv(
        in_path,
        sub_path,
        out_path,
        lang=track.get("lang"),
        settings=settings,
        existing_sub_count=existing_sub_count,
    )
    total = _safe_duration(duration, in_path, settings)
    on_progress = (lambda pct, msg: ctx.progress(pct, msg)) if ctx is not None else None
    should_cancel = (lambda: ctx.cancelled) if ctx is not None else None
    code = run(
        argv,
        total_sec=total,
        on_progress=on_progress,
        should_cancel=should_cancel,
    )
    if code != 0:
        raise TrackError(f"soft-mux failed (ffmpeg exit {code})")
    return out_path


def strip_track(
    in_path: str,
    out_path: str | None = None,
    *,
    sub_stream_index: int = 0,
    settings: dict[str, Any] | None = None,
    ctx: JobContext | None = None,
    run: Callable[..., int] = ffmpeg.run,
    duration: Callable[..., float] = ffmpeg.ffprobe_duration,
) -> str:
    """Re-mux ``in_path`` omitting the chosen subtitle stream; return path."""
    out_path = out_path or _default_out_path(in_path, "-stripped")
    argv = build_strip_argv(in_path, out_path, sub_stream_index, settings)
    total = _safe_duration(duration, in_path, settings)
    on_progress = (lambda pct, msg: ctx.progress(pct, msg)) if ctx is not None else None
    should_cancel = (lambda: ctx.cancelled) if ctx is not None else None
    code = run(
        argv,
        total_sec=total,
        on_progress=on_progress,
        should_cancel=should_cancel,
    )
    if code != 0:
        raise TrackError(f"strip failed (ffmpeg exit {code})")
    return out_path


def _safe_duration(duration: Callable[..., float], in_path: str, settings: dict[str, Any] | None) -> float:
    """Probe the source duration for progress; never fail the op over a probe."""
    try:
        return float(duration(in_path, settings))
    except Exception:  # noqa: BLE001 - a probe failure must not block the op
        log.warning("duration probe failed for %s; progress will be coarse", in_path)
        return 0.0
