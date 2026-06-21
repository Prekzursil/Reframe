"""NLE timeline export — CMX3600 EDL + CSV for Premiere / DaVinci Resolve.

Approved short-maker clips (the ``Project.clips`` records ``{candidate, path}``,
each candidate carrying ``sourceStart``/``end``/``durationSec``) are exported as
an *editable timeline* an editor can import: a CMX3600 ``.edl`` (the lingua
franca of NLEs) and/or a ``.csv`` (a per-clip spreadsheet for batch ingest or
review).

Pure logic — no heavy deps, no subprocess, no transport. The handler in
``handlers.py`` reads the project's clip list, calls these builders, writes the
file under the exports dir, and returns ``{path}``. Everything here is a pure
``data -> str`` transform so tests exercise the timecode math + EDL/CSV shape
directly.

Public surface (mirrors ``subtitles`` / ``shorts`` module style):
  - ``FPS_CHOICES``                       the selectable frame rates (24/25/30/60)
  - ``seconds_to_timecode(sec, fps)``     float seconds -> ``HH:MM:SS:FF``
  - ``clips_to_events(clips, fps)``       Project.clips -> ordered EDLEvent dicts
  - ``build_edl(events, *, title, fps)``  CMX3600 EDL document text
  - ``build_csv(events, fps)``            CSV document text
  - ``export(clips, out_path, *, fmt, fps, title)`` -> path (the job/handler body)

CONTRACT-NOTE: CMX3600 record timecodes are *contiguous* (each event's record-in
is the previous event's record-out) so the imported sequence lays the approved
clips back-to-back on the timeline — the editable rough cut. Source timecodes use
the clip's ORIGINAL-video window (``sourceStart`` -> ``end``) so the reel/source
relink points at the real footage.
"""

from __future__ import annotations

import csv
import io
import os
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

Clip = dict[str, Any]
EDLEvent = dict[str, Any]

#: Selectable integer frame rates for timecode quantization (UI-frozen).
FPS_CHOICES: tuple[int, ...] = (24, 25, 30, 60)

#: Default reel name when a clip carries none (CMX3600 reel field, <= 8 chars).
DEFAULT_REEL = "AX"

#: The two NLE export formats this unit writes.
FORMATS: tuple[str, ...] = ("edl", "csv")

# CSV column order (frozen so downstream sheets/scripts can rely on it).
CSV_COLUMNS: tuple[str, ...] = (
    "index",
    "reel",
    "clipName",
    "sourcePath",
    "sourceIn",
    "sourceOut",
    "recordIn",
    "recordOut",
    "durationSec",
    "hook",
)


# --------------------------------------------------------------------------- #
# fps + timecode
# --------------------------------------------------------------------------- #
def normalize_fps(fps: Any) -> int:
    """Coerce ``fps`` to one of :data:`FPS_CHOICES` (raises on anything else)."""
    try:
        value = int(fps)
    except (TypeError, ValueError):
        raise ValueError(f"unsupported fps: {fps!r} (want one of {FPS_CHOICES})") from None
    if value not in FPS_CHOICES:
        raise ValueError(f"unsupported fps: {fps!r} (want one of {FPS_CHOICES})")
    return value


def seconds_to_frames(seconds: float, fps: int) -> int:
    """Quantize float seconds to a whole frame count at ``fps`` (clamps negatives)."""
    return int(round(max(0.0, float(seconds)) * fps))


def frames_to_timecode(total_frames: int, fps: int) -> str:
    """Whole frame count -> non-drop ``HH:MM:SS:FF`` timecode at ``fps``."""
    total = max(0, int(total_frames))
    frames = total % fps
    total_seconds = total // fps
    s = total_seconds % 60
    total_minutes = total_seconds // 60
    m = total_minutes % 60
    h = total_minutes // 60
    return f"{h:02d}:{m:02d}:{s:02d}:{frames:02d}"


def seconds_to_timecode(seconds: float, fps: Any) -> str:
    """Float seconds -> non-drop ``HH:MM:SS:FF`` timecode at ``fps`` (24/25/30/60)."""
    f = normalize_fps(fps)
    return frames_to_timecode(seconds_to_frames(seconds, f), f)


# --------------------------------------------------------------------------- #
# reel / clip-name sanitizing
# --------------------------------------------------------------------------- #
def sanitize_reel(name: str | None) -> str:
    """Coerce a reel name to a CMX3600-safe token (A-Z 0-9, <= 8 chars, upper).

    CMX3600 reel names are historically <= 8 chars, uppercase, no spaces. We
    strip everything else, uppercase, and truncate; an empty result falls back to
    :data:`DEFAULT_REEL` so every event always has a valid reel.
    """
    cleaned = re.sub(r"[^A-Za-z0-9]", "", str(name or "")).upper()
    return cleaned[:8] or DEFAULT_REEL


def _clip_basename(path: str) -> str:
    """Last path component (used as the EDL/CSV clip name comment)."""
    if not path:
        return ""
    return Path(path).name


# --------------------------------------------------------------------------- #
# clips -> events
# --------------------------------------------------------------------------- #
def _clip_window(clip: Clip) -> tuple[float, float, str, str]:
    """Extract (source_in, source_out, path, hook) from a Project.clip record.

    Tolerates both the persisted ``{candidate, path}`` shape and a flat candidate
    dict. The source window is the candidate's ORIGINAL-video span
    (``sourceStart`` -> ``end``); ``durationSec`` backstops a missing ``end``.
    """
    raw_candidate = clip.get("candidate")
    candidate = raw_candidate if isinstance(raw_candidate, dict) else clip
    path = str(clip.get("path") or candidate.get("path") or "")
    source_in = float(candidate.get("sourceStart", candidate.get("start", 0.0)) or 0.0)
    end = candidate.get("end")
    if end is None:
        duration = float(candidate.get("durationSec", 0.0) or 0.0)
        source_out = source_in + duration
    else:
        source_out = float(end or 0.0)
    if source_out < source_in:
        source_out = source_in
    hook = str(candidate.get("hook") or "")
    return source_in, source_out, path, hook


def clips_to_events(clips: Sequence[Clip], fps: Any) -> list[EDLEvent]:
    """Turn ordered ``Project.clips`` into contiguous-record EDL events.

    Each event carries the clip's source window (frames, from ``sourceStart`` ->
    ``end``) and a *record* window laid back-to-back (the rough cut). Reel names
    come per-clip from the candidate's ``reel`` (falling back to a per-index
    ``AX``/``AX2``... token). Zero-length clips are kept (a 1-frame minimum) so an
    editor still sees every approved selection. Returns fresh dicts (no mutation).
    """
    f = normalize_fps(fps)
    events: list[EDLEvent] = []
    record_cursor = 0  # frames on the record (timeline) side
    for i, clip in enumerate(clips or [], start=1):
        if not isinstance(clip, dict):
            continue
        source_in_sec, source_out_sec, path, hook = _clip_window(clip)
        raw_candidate = clip.get("candidate")
        candidate = raw_candidate if isinstance(raw_candidate, dict) else clip
        src_in_f = seconds_to_frames(source_in_sec, f)
        src_out_f = seconds_to_frames(source_out_sec, f)
        length_f = max(1, src_out_f - src_in_f)  # >=1 frame so the event is real
        src_out_f = src_in_f + length_f
        explicit_reel = candidate.get("reel")
        reel = sanitize_reel(explicit_reel) if explicit_reel else sanitize_reel(f"AX{i if i > 1 else ''}")
        rec_in_f = record_cursor
        rec_out_f = rec_in_f + length_f
        record_cursor = rec_out_f
        events.append(
            {
                "index": i,
                "reel": reel,
                "clipName": _clip_basename(path),
                "sourcePath": path,
                "sourceInFrames": src_in_f,
                "sourceOutFrames": src_out_f,
                "recordInFrames": rec_in_f,
                "recordOutFrames": rec_out_f,
                "durationSec": round(length_f / f, 3),
                "hook": hook,
                "fps": f,
            }
        )
    return events


# --------------------------------------------------------------------------- #
# EDL (CMX3600)
# --------------------------------------------------------------------------- #
def _edl_title(title: str) -> str:
    """CMX3600 ``TITLE:`` line value — single line, sanitized whitespace."""
    return re.sub(r"\s+", " ", str(title or "Media Studio Timeline")).strip()[:70]


def build_edl(events: Sequence[EDLEvent], *, title: str = "Media Studio Timeline", fps: int = 30) -> str:
    """Serialize EDL events to a CMX3600 document (non-drop-frame).

    Each event is one video cut (``V  C``) carrying source-in/out + record-in/out
    timecodes, with the clip's file name as a ``* FROM CLIP NAME:`` comment and
    its hook as a ``* COMMENT:`` line (both standard CMX3600 comment forms NLEs
    surface as clip metadata). The header declares ``FCM: NON-DROP FRAME``.
    """
    f = normalize_fps(fps)
    lines: list[str] = [f"TITLE: {_edl_title(title)}", "FCM: NON-DROP FRAME"]
    for ev in events:
        num = f"{int(ev['index']):03d}"
        reel = sanitize_reel(ev.get("reel"))
        src_in = frames_to_timecode(int(ev["sourceInFrames"]), f)
        src_out = frames_to_timecode(int(ev["sourceOutFrames"]), f)
        rec_in = frames_to_timecode(int(ev["recordInFrames"]), f)
        rec_out = frames_to_timecode(int(ev["recordOutFrames"]), f)
        # <num> <reel> <chan> <transition> <src-in> <src-out> <rec-in> <rec-out>
        lines.append(f"{num}  {reel:<8} V     C        {src_in} {src_out} {rec_in} {rec_out}")
        clip_name = str(ev.get("clipName") or "")
        if clip_name:
            lines.append(f"* FROM CLIP NAME: {clip_name}")
        hook = str(ev.get("hook") or "").strip()
        if hook:
            hook_one_line = re.sub(r"\s+", " ", hook)[:200]
            lines.append(f"* COMMENT: {hook_one_line}")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# CSV
# --------------------------------------------------------------------------- #
def build_csv(events: Sequence[EDLEvent], fps: int = 30) -> str:
    """Serialize EDL events to a CSV document (header :data:`CSV_COLUMNS`).

    Timecodes are rendered ``HH:MM:SS:FF`` at ``fps`` so the sheet matches the
    EDL. ``\\r\\n`` line terminators (Excel-friendly); the body is UTF-8.
    """
    f = normalize_fps(fps)
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\r\n")
    writer.writerow(CSV_COLUMNS)
    for ev in events:
        writer.writerow(
            [
                int(ev["index"]),
                sanitize_reel(ev.get("reel")),
                str(ev.get("clipName") or ""),
                str(ev.get("sourcePath") or ""),
                frames_to_timecode(int(ev["sourceInFrames"]), f),
                frames_to_timecode(int(ev["sourceOutFrames"]), f),
                frames_to_timecode(int(ev["recordInFrames"]), f),
                frames_to_timecode(int(ev["recordOutFrames"]), f),
                round(float(ev.get("durationSec") or 0.0), 3),
                str(ev.get("hook") or ""),
            ]
        )
    return buf.getvalue()


# --------------------------------------------------------------------------- #
# format dispatch + file I/O
# --------------------------------------------------------------------------- #
def normalize_format(fmt: str) -> str:
    """Coerce a format string to ``edl`` | ``csv`` (raises on anything else)."""
    f = str(fmt).strip().lower().lstrip(".")
    if f not in FORMATS:
        raise ValueError(f"unsupported NLE export format: {fmt!r} (want one of {FORMATS})")
    return f


def serialize(events: Sequence[EDLEvent], fmt: str, *, fps: int = 30, title: str = "Media Studio Timeline") -> str:
    """Serialize events to ``edl`` or ``csv`` text (no file I/O)."""
    f = normalize_format(fmt)
    if f == "edl":
        return build_edl(events, title=title, fps=fps)
    return build_csv(events, fps=fps)


def export(
    clips: Sequence[Clip],
    out_path: str | os.PathLike,
    *,
    fmt: str = "edl",
    fps: Any = 30,
    title: str = "Media Studio Timeline",
) -> str:
    """Build an EDL/CSV from approved ``clips`` and write it to ``out_path``.

    Returns the written path. ``fps`` is one of :data:`FPS_CHOICES`; ``fmt`` is
    ``edl`` | ``csv``. The events are derived once (:func:`clips_to_events`) and
    serialized to the chosen format. Empty ``clips`` still writes a valid (header-
    only) document so the editor opens an empty-but-importable timeline.
    """
    f = normalize_format(fmt)
    rate = normalize_fps(fps)
    events = clips_to_events(clips, rate)
    text = serialize(events, f, fps=rate, title=title)
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # CMX3600/CSV are CRLF-friendly; csv already emits CRLF, EDL we keep LF-as-written.
    newline = "" if f == "csv" else "\n"
    path.write_text(text, encoding="utf-8", newline=newline)
    return str(path)


__all__ = [
    "CSV_COLUMNS",
    "DEFAULT_REEL",
    "FORMATS",
    "FPS_CHOICES",
    "build_csv",
    "build_edl",
    "clips_to_events",
    "export",
    "frames_to_timecode",
    "normalize_format",
    "normalize_fps",
    "sanitize_reel",
    "seconds_to_frames",
    "seconds_to_timecode",
    "serialize",
]
