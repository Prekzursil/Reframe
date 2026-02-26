from __future__ import annotations

import re
from typing import List

from media_core.subtitles.builder import SubtitleLine
from media_core.transcribe.models import Word


_TIME_RE = re.compile(r"(?:(?P<h>\d{2}):)?(?P<m>\d{2}):(?P<s>\d{2})\.(?P<ms>\d{3})")


def _parse_timestamp(ts: str) -> float:
    match = _TIME_RE.match(ts.strip())
    if not match:
        raise ValueError(f"Invalid VTT timestamp: {ts}")
    h = int(match.group("h") or 0)
    m = int(match.group("m") or 0)
    s = int(match.group("s") or 0)
    ms = int(match.group("ms") or 0)
    return h * 3600 + m * 60 + s + ms / 1000.0


def parse_vtt(vtt_text: str) -> List[SubtitleLine]:
    """Parse a basic WebVTT string into SubtitleLine objects.

    This is intentionally minimal (supports the subset produced by `to_vtt`), but also
    tolerates cue identifiers and timing settings after the end timestamp.
    """
    text = vtt_text.lstrip("\ufeff")
    out: List[SubtitleLine] = []

    timing: str | None = None
    cue_lines: List[str] = []
    in_note = False

    def flush():
        nonlocal timing, cue_lines
        if not timing:
            cue_lines = []
            return
        try:
            start_raw, end_raw = timing.split("-->")
            start = _parse_timestamp(start_raw.strip().split()[0])
            end = _parse_timestamp(end_raw.strip().split()[0])
        except Exception as exc:
            raise ValueError(f"Invalid VTT timing line: {timing}") from exc

        content = " ".join(l.strip() for l in cue_lines if l.strip()).strip()
        if content:
            out.append(SubtitleLine(start=start, end=end, words=[Word(text=content, start=start, end=end)]))
        timing = None
        cue_lines = []

    for raw in text.splitlines():
        line = raw.rstrip("\n")
        stripped = line.strip()

        if not stripped:
            flush()
            in_note = False
            continue

        if stripped.startswith("WEBVTT"):
            continue

        if stripped.startswith("NOTE"):
            in_note = True
            continue

        if in_note:
            continue

        if "-->" in stripped:
            flush()
            timing = stripped
            continue

        if timing is None:
            # Cue identifier or stray metadata line; ignore.
            continue

        cue_lines.append(stripped)

    flush()
    return out
