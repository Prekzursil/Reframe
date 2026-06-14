"""CaptionEngine — render captions onto a clip via **libass / ffmpeg**.

This is the sole caption implementation for the build (CONTRACTS.md section 4):
generate an ASS subtitle file sized for ``width`` x ``height``, then either
**burn** it into the video (``burn=True``, hardcoded pixels via ffmpeg's
``subtitles`` filter / libass) or **soft-mux** it as a selectable subtitle
stream (``burn=False``).

Two correctness rules from the contract drive the design:

1. **Re-base cue times to the clip.** A :class:`Candidate` carries
   ``sourceStart`` = the clip's start time in the ORIGINAL video. The cues
   handed to us are timed against that original timeline, so every cue time has
   ``sourceStart`` subtracted to map it to the exported clip's local t=0. A clip
   cut from t=120s of the source therefore shows its first caption at clip-local
   t=0, not t=120 (which would never display).

2. **Escape cue text.** ASS uses ``{...}`` for inline override codes. Raw braces
   in caption text would be interpreted as overrides ("ASS override injection")
   — e.g. a transcript line ``{\fake}`` could blank the line or worse. We escape
   the text so it always renders literally.

Subprocess safety (CONTRACTS.md section 6): every ffmpeg call is built as an
**argv list** and run via the shared :mod:`media_studio.ffmpeg` ``run`` (never
``shell=True``), so paths with spaces are handled correctly. The runner is
injectable so tests exercise argv construction with no real ffmpeg present.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from media_studio import ffmpeg

from . import emphasis as _emphasis

# A Cue is the contract's ``{index:int, start:float, end:float, text:str}``
# (CONTRACTS.md section 3). We accept it duck-typed as a Mapping so this module
# does not depend on another unit's TypedDict definition and stays import-light.
CueLike = Mapping[str, Any]

# A runner with the same shape as ``media_studio.ffmpeg.run`` (returns exit code).
RunnerCb = Callable[..., int]

# ASS line-break token. Literal "\N" inside dialogue is a hard newline in ASS.
_ASS_NEWLINE = r"\N"

# P3-A hook-title overlay: a top-anchored headline rendered above the captions.
# The hook text is user-ish data (it comes from the candidate's ``hook`` field,
# ultimately model/transcript-derived), so it is escaped exactly like a cue.
# A long hook is soft-wrapped onto at most two lines so it never overruns the
# safe top margin.
_HOOK_TITLE_STYLE = "HookTitle"
# Wrap the title into <= this many lines (2) at word boundaries.
_HOOK_TITLE_MAX_LINES = 2
# Headlines with this many words or fewer stay on a single line (short hooks
# should not be split into one-word-per-line stacks).
_HOOK_TITLE_MIN_WRAP_WORDS = 4
# Fallback hook-title display length (seconds) when the clip duration is unknown
# — the §5 hard MAX clip length, so the headline persists across the whole clip.
_HOOK_TITLE_FALLBACK_SEC = 60.0


class CaptionError(RuntimeError):
    """Raised when the underlying ffmpeg caption render fails (non-zero exit)."""


# --------------------------------------------------------------------------- #
# text + time helpers (pure functions — fully unit-testable, no subprocess)
# --------------------------------------------------------------------------- #
def escape_ass_text(text: str) -> str:
    r"""Escape arbitrary caption text so libass renders it literally.

    Defenses (in order so we never double-process an escape we just inserted):

    - ``\``  -> ``\\``      (a lone backslash would start an override like ``\b``)
    - ``{``  -> ``\{`` and ``}`` -> ``\}``  (braces delimit ASS override blocks;
      escaping them neutralises injection such as ``{\fake}`` / ``{\an8}``)
    - real newlines -> ``\N`` (ASS hard line break) so multi-line cues survive
      the single-line Dialogue format.

    Note the ``\`` pass runs FIRST, otherwise the backslashes we add for braces
    and newlines would themselves be doubled.
    """
    if text is None:  # be tolerant of a missing/None cue text
        return ""
    out = str(text)
    out = out.replace("\\", "\\\\")
    out = out.replace("{", r"\{").replace("}", r"\}")
    out = out.replace("\r\n", "\n").replace("\r", "\n").replace("\n", _ASS_NEWLINE)
    return out


def format_ass_timestamp(seconds: float) -> str:
    """Format ``seconds`` as an ASS timestamp ``H:MM:SS.cc`` (centiseconds).

    Negative inputs clamp to ``0:00:00.00`` — a cue that began before the clip's
    local zero (after re-basing) is pinned to the clip start rather than going
    negative, which ASS cannot represent.
    """
    if seconds is None or seconds < 0:
        seconds = 0.0
    total_cs = int(round(float(seconds) * 100))  # whole centiseconds
    cs = total_cs % 100
    total_s = total_cs // 100
    s = total_s % 60
    total_m = total_s // 60
    m = total_m % 60
    h = total_m // 60
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"


def rebase_cue_time(t: float, source_start: float) -> float:
    """Re-base an absolute source time ``t`` to clip-local time.

    Subtracts ``source_start`` (the clip's offset in the original video) and
    clamps the result to ``>= 0`` so a cue straddling the clip's in-point starts
    at the clip's t=0 instead of a negative time.
    """
    return max(0.0, float(t) - float(source_start))


def wrap_hook_title(text: str, max_lines: int = _HOOK_TITLE_MAX_LINES) -> str:
    """Soft-wrap a hook headline onto at most ``max_lines`` balanced lines.

    The text is escaped for ASS FIRST (so the hook — user-ish data — can never
    inject an override), then split on whitespace and packed greedily into
    ``max_lines`` lines joined by the ASS hard-break token. An empty/blank hook
    returns ``""``. The wrap is purely cosmetic; libass also wraps on its own,
    but pre-wrapping keeps the headline balanced and inside the safe margin.
    """
    escaped = escape_ass_text(text)
    if not escaped.strip():
        return ""
    words = escaped.split()
    # Short headlines stay on one line; only wrap when there are enough words
    # that a single line would overrun the safe top margin.
    if not words or max_lines <= 1 or len(words) <= _HOOK_TITLE_MIN_WRAP_WORDS:
        return " ".join(words)
    # Balanced pack: aim for an even number of words per line so the headline is
    # roughly balanced rather than one long line + one orphan word.
    per_line = max(1, (len(words) + max_lines - 1) // max_lines)
    lines: List[str] = []
    for i in range(0, len(words), per_line):
        lines.append(" ".join(words[i : i + per_line]))
        if len(lines) == max_lines:
            # Anything left over is appended to the last line (libass wraps it).
            rest = words[i + per_line :]
            if rest:
                lines[-1] = lines[-1] + " " + " ".join(rest)
            break
    return _ASS_NEWLINE.join(lines)


# P4 §8a emphasis: bold ON / bold OFF ASS inline override codes. Wrapping an
# emphasised word in ``{\b1}word{\b0}`` renders it bold (the libass approximation
# of the colored/boxed highlight the Remotion + overlay paths draw).
_ASS_BOLD_ON = r"{\b1}"
_ASS_BOLD_OFF = r"{\b0}"


def render_cue_text(cue: CueLike) -> str:
    r"""Escaped ASS text for a cue, with §8a emphasis bolding + a trailing emoji.

    The cue's raw ``text`` is escaped against override injection FIRST. Then any
    annotated ``emphasis`` spans (char offsets into the RAW text, from
    :mod:`media_studio.features.emphasis`) bold their words via ``{\b1}..{\b0}``,
    and a trailing ``emoji`` (when present) is appended. Spans are clamped to the
    text bounds, sorted, and skipped when they overlap, so a malformed annotation
    can never corrupt the line. With no annotation this returns exactly
    :func:`escape_ass_text` of the text (byte-identical to the pre-§8a output).
    """
    raw = str(cue.get("text", "") or "")
    spans = _emphasis.normalize_spans(cue.get("emphasis"), len(raw))
    if not spans:
        body = escape_ass_text(raw)
    else:
        parts: List[str] = []
        cursor = 0
        for span in spans:
            start, end = span["start"], span["end"]
            parts.append(escape_ass_text(raw[cursor:start]))
            parts.append(_ASS_BOLD_ON + escape_ass_text(raw[start:end]) + _ASS_BOLD_OFF)
            cursor = end
        parts.append(escape_ass_text(raw[cursor:]))
        body = "".join(parts)
    emoji = str(cue.get("emoji", "") or "")
    if emoji:
        body = f"{body} {escape_ass_text(emoji)}" if body else escape_ass_text(emoji)
    return body


# --------------------------------------------------------------------------- #
# ASS document generation (pure function — the heart of the unit)
# --------------------------------------------------------------------------- #
def build_ass(
    cues: Sequence[CueLike],
    width: int = 1080,
    height: int = 1920,
    source_start: float = 0.0,
    hook_title: Optional[str] = None,
    total_sec: float = 0.0,
) -> str:
    """Build a complete ASS subtitle document for ``cues``.

    - ``[Script Info]`` carries ``PlayResX``/``PlayResY`` = ``width``/``height``
      so libass lays the text out for the exact export canvas (default the
      contract's 1080x1920 vertical short).
    - Each cue's ``start``/``end`` is re-based by ``source_start`` (subtract the
      clip's origin) and its ``text`` is escaped against override injection.
    - Cues whose end falls at or before their start AFTER re-basing (i.e. they
      lie entirely before the clip) are skipped — they could never display.
    - When ``hook_title`` is given (P3-A), a bold top-anchored headline is added
      as its own style + event. The hook text is escaped (it is user-ish data)
      and soft-wrapped onto <= 2 lines inside a safe top margin. It shows for the
      whole clip (``total_sec`` if known, else through the last cue / 60s floor).
    """
    play_x = int(width)
    play_y = int(height)

    # A readable default style scaled to the canvas height. Bottom-centred,
    # white fill with a black outline + drop shadow (typical short-form caption).
    font_size = max(12, int(round(play_y * 0.045)))
    margin_v = max(10, int(round(play_y * 0.06)))

    styles = [
        (
            "Style: Default,Arial,"
            f"{font_size},"
            "&H00FFFFFF,&H000000FF,&H00000000,&H64000000,"
            "-1,0,0,0,"
            "100,100,0,0,1,3,1,"
            f"2,40,40,{margin_v},1"
        ),
    ]

    # P3-A: a bold, larger, TOP-anchored headline style (Alignment 8 = top-
    # centre). Slightly larger than the body caption with a thicker outline so
    # it reads as a headline; safe top margin keeps it off the very edge.
    title_text = wrap_hook_title(hook_title or "")
    if title_text:
        title_size = max(14, int(round(play_y * 0.055)))
        title_margin_v = max(12, int(round(play_y * 0.07)))
        styles.append(
            "Style: HookTitle,Arial,"
            f"{title_size},"
            "&H00FFFFFF,&H000000FF,&H00000000,&H96000000,"
            "-1,0,0,0,"
            "100,100,0,0,1,4,2,"
            f"8,60,60,{title_margin_v},1"
        )

    header = [
        "[Script Info]",
        "; Generated by media-studio CaptionEngine (libass/ffmpeg).",
        "ScriptType: v4.00+",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        f"PlayResX: {play_x}",
        f"PlayResY: {play_y}",
        "",
        "[V4+ Styles]",
        (
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
            "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
            "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding"
        ),
        *styles,
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    events: List[str] = []

    # P3-A: emit the hook-title event FIRST so it draws above the body captions.
    if title_text:
        title_end = float(total_sec)
        if title_end <= 0.0:
            # No probed duration: span to the last cue (clip-local) or a 60s
            # floor (the §5 hard max clip length) so the headline persists.
            cue_ends = [
                rebase_cue_time(c.get("end", 0.0), source_start) for c in cues
            ]
            title_end = max(
                [*cue_ends, _HOOK_TITLE_FALLBACK_SEC],
                default=_HOOK_TITLE_FALLBACK_SEC,
            )
        events.append(
            "Dialogue: 0,"
            f"{format_ass_timestamp(0.0)},"
            f"{format_ass_timestamp(title_end)},"
            "HookTitle,,0,0,0,,"
            f"{title_text}"
        )

    for cue in cues:
        raw_start = cue.get("start", 0.0)
        raw_end = cue.get("end", 0.0)
        start = rebase_cue_time(raw_start, source_start)
        end = rebase_cue_time(raw_end, source_start)
        if end <= start:
            # Entirely before the clip (or zero-length after re-base): skip.
            continue
        events.append(
            "Dialogue: 0,"
            f"{format_ass_timestamp(start)},"
            f"{format_ass_timestamp(end)},"
            "Default,,0,0,0,,"
            f"{render_cue_text(cue)}"
        )

    # ASS files are conventionally CRLF; libass accepts LF too. Use LF for
    # determinism across platforms (tests assert on exact content).
    return "\n".join(header + events) + "\n"


# --------------------------------------------------------------------------- #
# ffmpeg argv builders (pure functions — no subprocess)
# --------------------------------------------------------------------------- #
def _escape_filter_path(path: str) -> str:
    r"""Escape a filesystem path for use inside an ffmpeg ``subtitles=`` filter.

    Inside a filtergraph, ``\``, ``:`` and the surrounding ``'`` quoting are
    special. We wrap the path in single quotes and escape the characters libass
    / the filter parser treat specially. Windows drive colons (``C:``) and
    backslashes are the common breakage this guards against.
    """
    # Backslash first, then the filter-special characters.
    p = path.replace("\\", "\\\\")
    p = p.replace(":", "\\:")
    p = p.replace("'", "\\'")
    return f"'{p}'"


def build_burn_argv(
    clip_path: str,
    ass_path: str,
    out_path: str,
    settings: Optional[Dict[str, Any]] = None,
) -> List[str]:
    """argv to **hardcode** ``ass_path`` into ``clip_path`` (burn-in).

    Uses ffmpeg's ``subtitles`` filter (libass) to rasterise the ASS onto the
    video; audio is stream-copied. ``-progress pipe:1 -nostats`` lets the shared
    runner parse progress; ``-y`` overwrites the output.
    """
    vf = f"subtitles={_escape_filter_path(ass_path)}"
    return [
        ffmpeg.ffmpeg_path(settings),
        "-hide_banner",
        "-nostdin",
        "-y",
        "-i", clip_path,
        "-vf", vf,
        "-c:a", "copy",
        "-progress", "pipe:1",
        "-nostats",
        out_path,
    ]


def build_softmux_argv(
    clip_path: str,
    ass_path: str,
    out_path: str,
    settings: Optional[Dict[str, Any]] = None,
) -> List[str]:
    """argv to **soft-mux** ``ass_path`` as a selectable subtitle track.

    Video and audio are stream-copied; the subtitle is muxed in its own stream.
    For an MP4 container ffmpeg needs ``mov_text``; for MKV/other we keep native
    ASS. Choice is driven purely by the output extension.
    """
    ext = Path(out_path).suffix.lower()
    scodec = "mov_text" if ext in (".mp4", ".m4v", ".mov") else "ass"
    return [
        ffmpeg.ffmpeg_path(settings),
        "-hide_banner",
        "-nostdin",
        "-y",
        "-i", clip_path,
        "-i", ass_path,
        "-map", "0:v",
        "-map", "0:a?",
        "-map", "1:0",
        "-c:v", "copy",
        "-c:a", "copy",
        "-c:s", scodec,
        "-progress", "pipe:1",
        "-nostats",
        out_path,
    ]


# --------------------------------------------------------------------------- #
# CaptionEngine
# --------------------------------------------------------------------------- #
class CaptionEngine:
    """Render captions onto a clip via libass/ffmpeg (sole impl, section 4).

    ``settings`` (optional) is forwarded to :mod:`media_studio.ffmpeg` for binary
    resolution (e.g. ``{"ffmpegPath": "..."}``). ``runner`` is injectable and
    defaults to the shared :func:`media_studio.ffmpeg.run`; tests pass a fake to
    capture the argv and skip the real subprocess.
    """

    def __init__(
        self,
        settings: Optional[Dict[str, Any]] = None,
        runner: RunnerCb = ffmpeg.run,
    ) -> None:
        self._settings = settings or {}
        self._runner = runner

    def build_ass(
        self,
        cues: Sequence[CueLike],
        width: int = 1080,
        height: int = 1920,
        source_start: float = 0.0,
        hook_title: Optional[str] = None,
        total_sec: float = 0.0,
    ) -> str:
        """Generate the ASS document (delegates to module-level :func:`build_ass`)."""
        return build_ass(
            cues,
            width=width,
            height=height,
            source_start=source_start,
            hook_title=hook_title,
            total_sec=total_sec,
        )

    def render(
        self,
        clip_path: str,
        cues: Sequence[CueLike],
        out_path: str,
        burn: bool = True,
        width: int = 1080,
        height: int = 1920,
        source_start: float = 0.0,
        on_progress: Optional[Callable[[float, str], None]] = None,
        should_cancel: Optional[Callable[[], bool]] = None,
        total_sec: float = 0.0,
        hook_title: Optional[str] = None,
    ) -> str:
        """Render ``cues`` onto ``clip_path`` -> ``out_path`` and return ``out_path``.

        Steps:
          1. Generate an ASS document sized ``width`` x ``height`` with cue times
             re-based by ``source_start`` and text escaped.
          2. Write it to a temp ``.ass`` file (argv-passed, never piped via a
             shell).
          3. Run ffmpeg to either burn it in (``burn=True``) or soft-mux it
             (``burn=False``).
          4. Clean up the temp file and return ``out_path``.

        Raises :class:`CaptionError` on a non-zero ffmpeg exit. ``source_start``
        defaults to 0.0; callers exporting a :class:`Candidate` pass that
        candidate's ``sourceStart`` so the captions line up with the clip.
        """
        ass_doc = build_ass(
            cues,
            width=width,
            height=height,
            source_start=source_start,
            hook_title=hook_title,
            total_sec=total_sec,
        )

        # Write the ASS to a temp sidecar file. We pass its path as an argv
        # element to ffmpeg (no shell, no stdin pipe), so spaces are safe.
        fd, ass_path = tempfile.mkstemp(suffix=".ass", prefix="media_studio_caption_")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
                fh.write(ass_doc)

            if burn:
                argv = build_burn_argv(clip_path, ass_path, out_path, self._settings)
            else:
                argv = build_softmux_argv(clip_path, ass_path, out_path, self._settings)

            code = self._runner(
                argv,
                total_sec=total_sec,
                on_progress=on_progress,
                should_cancel=should_cancel,
            )
            if code != 0:
                raise CaptionError(
                    f"ffmpeg caption render failed (exit {code}) for {out_path}"
                )
            return out_path
        finally:
            # Best-effort cleanup; never mask a CaptionError with a cleanup error.
            try:
                os.unlink(ass_path)
            except OSError:
                pass
