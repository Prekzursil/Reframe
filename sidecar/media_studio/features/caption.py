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

import contextlib
import math
import os
import tempfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from media_studio import ffmpeg

from . import caption_override as _override
from . import emphasis as _emphasis
from . import hook_card as _hook_card
from .caption_override import ResolvedCaptionStyle

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
    lines: list[str] = []
    for i in range(0, len(words), per_line):
        lines.append(" ".join(words[i : i + per_line]))
        if len(lines) == max_lines:
            # Anything left over is appended to the last line (libass wraps it).
            rest = words[i + per_line :]
            if rest:  # pragma: no cover - rest is always empty: max_lines*ceil(n/max_lines) >= n, so the last chunk consumes all words
                lines[-1] = lines[-1] + " " + " ".join(rest)
            break
    return _ASS_NEWLINE.join(lines)


# P4 §8a emphasis: bold ON / bold OFF ASS inline override codes. Wrapping an
# emphasised word in ``{\b1}word{\b0}`` renders it bold (the libass approximation
# of the colored/boxed highlight the Remotion + overlay paths draw).
_ASS_BOLD_ON = r"{\b1}"
_ASS_BOLD_OFF = r"{\b0}"


def render_cue_text(cue: CueLike, uppercase: bool = False) -> str:
    r"""Escaped ASS text for a cue, with §8a emphasis bolding + a trailing emoji.

    The cue's raw ``text`` is escaped against override injection FIRST. Then any
    annotated ``emphasis`` spans (char offsets into the RAW text, from
    :mod:`media_studio.features.emphasis`) bold their words via ``{\b1}..{\b0}``,
    and a trailing ``emoji`` (when present) is appended. Spans are clamped to the
    text bounds, sorted, and skipped when they overlap, so a malformed annotation
    can never corrupt the line. With no annotation this returns exactly
    :func:`escape_ass_text` of the text (byte-identical to the pre-§8a output).

    When ``uppercase`` is set (the V1.1 ``CaptionOverride.uppercase`` text
    transform) each raw text slice is upper-cased BEFORE escaping — never the
    assembled string, so the inserted ``{\b1}`` override tags can never be
    corrupted into ``{\B1}``. Span offsets index the original-case ``raw`` and the
    slices are upper-cased independently, so the casing transform cannot shift them.
    The trailing emoji is left untransformed.
    """
    raw = str(cue.get("text", "") or "")
    spans = _emphasis.normalize_spans(cue.get("emphasis"), len(raw))

    def _tx(slice_text: str) -> str:
        return slice_text.upper() if uppercase else slice_text

    if not spans:
        body = escape_ass_text(_tx(raw))
    else:
        parts: list[str] = []
        cursor = 0
        for span in spans:
            start, end = span["start"], span["end"]
            parts.append(escape_ass_text(_tx(raw[cursor:start])))
            parts.append(_ASS_BOLD_ON + escape_ass_text(_tx(raw[start:end])) + _ASS_BOLD_OFF)
            cursor = end
        parts.append(escape_ass_text(_tx(raw[cursor:])))
        body = "".join(parts)
    emoji = str(cue.get("emoji", "") or "")
    if emoji:
        body = f"{body} {escape_ass_text(emoji)}" if body else escape_ass_text(emoji)
    return body


# --------------------------------------------------------------------------- #
# ASS document generation (pure function — the heart of the unit)
# --------------------------------------------------------------------------- #
def normalize_caption_box(raw: Any) -> dict[str, float] | None:
    """Validate a renderer caption box (``{x,y,w,h}`` fractions 0..1) or None.

    The renderer's caption position editor (P4 §4) sends a NORMALISED box; this
    coerces + clamps it into a usable box, returning ``None`` for anything that
    is not a finite-numbered ``{x,y,w,h}`` so the caller keeps the default
    bottom-centred placement (never a silent crash on malformed input).
    """
    if not isinstance(raw, dict):
        return None
    try:
        x = float(raw["x"])
        y = float(raw["y"])
        w = float(raw["w"])
        h = float(raw["h"])
    except (KeyError, TypeError, ValueError):
        return None
    if not all(math.isfinite(v) for v in (x, y, w, h)):
        return None
    w = min(max(w, 0.0), 1.0)
    h = min(max(h, 0.0), 1.0)
    x = min(max(x, 0.0), 1.0)
    y = min(max(y, 0.0), 1.0)
    return {"x": x, "y": y, "w": w, "h": h}


def caption_position_fields(box: dict[str, float], play_x: int, play_y: int) -> tuple[int, int, int, int]:
    """ASS ``(Alignment, MarginL, MarginR, MarginV)`` for a normalised box.

    The box centre's vertical band picks the anchor (top=8 / middle=5 /
    bottom=2, all horizontally centred); margins place the box edge in pixels.
    For a TOP-anchored line MarginV measures from the top edge, for a BOTTOM line
    from the bottom edge, and a MIDDLE line ignores MarginV (libass centres it).
    """
    y = box["y"]
    h = box["h"]
    cy = y + h / 2.0
    if cy < 1.0 / 3.0:
        alignment = 8
        margin_v = int(round(y * play_y))
    elif cy < 2.0 / 3.0:
        alignment = 5
        margin_v = 0
    else:
        alignment = 2
        margin_v = int(round((1.0 - (y + h)) * play_y))
    margin_l = int(round(box["x"] * play_x))
    margin_r = int(round((1.0 - (box["x"] + box["w"])) * play_x))
    return alignment, max(0, margin_l), max(0, margin_r), max(0, margin_v)


def _band_position(band: str, default_margin_v: int) -> tuple[int, int]:
    """``(Alignment, MarginV)`` for a coarse ``CaptionOverride.positionBand``.

    The band maps to the centred numpad anchor (top=8 / center=5 / bottom=2);
    a centre band is libass-centred so its ``MarginV`` is ``0``, while top/bottom
    sit ``default_margin_v`` px from their edge (fine offset stays in the box
    margins). Pure.
    """
    alignment = _override.POSITION_BAND_ALIGNMENT[band]
    return alignment, (0 if alignment == 5 else default_margin_v)


def _default_style_line(
    resolved: ResolvedCaptionStyle,
    font_size: int,
    alignment: int,
    margin_l: int,
    margin_r: int,
    margin_v: int,
) -> str:
    """Assemble the ``Style: Default`` line from a resolved caption style.

    With the base (no-override) :class:`ResolvedCaptionStyle` this is byte-identical
    to the historical hard-coded V1 line (back-compat keystone — guarded by the
    existing caption tests); an override only changes the fields it touches.
    """
    return (
        f"Style: Default,{resolved.font_name},"
        f"{font_size},"
        f"{resolved.primary_color},{resolved.secondary_color},"
        f"{resolved.outline_color},{resolved.back_color},"
        "-1,0,0,0,"
        f"100,100,0,0,{resolved.border_style},{resolved.outline_width},{resolved.shadow},"
        f"{alignment},{margin_l},{margin_r},{margin_v},1"
    )


def build_ass(
    cues: Sequence[CueLike],
    width: int = 1080,
    height: int = 1920,
    source_start: float = 0.0,
    hook_title: str | None = None,
    total_sec: float = 0.0,
    position: Any = None,
    override: Mapping[str, Any] | None = None,
    hook_card: bool = False,
    hook_card_sec: float = 0.0,
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
    - When a V1.1 ``override`` (validated ``CaptionOverride``) is given, the body
      ``Style: Default`` line is rebuilt from the resolved style (font / size /
      colours / outline / card / position-band) and cue text is upper-cased when
      requested. An absent/empty override resolves to the base style, so the
      emitted document is byte-identical to V1 (back-compat).
    """
    play_x = int(width)
    play_y = int(height)

    # V1.1: resolve the (validated, additive) caption override onto the base libass
    # visual. An absent/empty override yields the base style => byte-identical V1.
    resolved = _override.apply_override(override)

    # A readable default style scaled to the canvas height. Bottom-centred, white
    # fill with a black outline + drop shadow (typical short-form caption). The
    # override's size scale multiplies the canvas-derived base size (>=12 floor).
    font_size = max(12, int(round(play_y * 0.045)))
    font_size = max(12, int(round(font_size * resolved.size_scale)))
    default_margin_v = max(10, int(round(play_y * 0.06)))

    # P4 §4: honour the renderer's normalised caption POSITION box when present
    # (alignment + margins from the box); otherwise keep the bottom-centred
    # default. Malformed boxes fall back to the default (no silent crash).
    box = normalize_caption_box(position)
    if box is not None:
        alignment, margin_l, margin_r, margin_v = caption_position_fields(box, play_x, play_y)
    else:
        alignment, margin_l, margin_r, margin_v = 2, 40, 40, default_margin_v

    # V1.1: a coarse positionBand override re-anchors the body caption (alignment +
    # band margin_v); the box still supplies the fine L/R offset.
    if resolved.position_band is not None:
        alignment, margin_v = _band_position(resolved.position_band, default_margin_v)

    styles = [
        _default_style_line(resolved, font_size, alignment, margin_l, margin_r, margin_v),
    ]

    # P3-A: a bold, larger, TOP-anchored headline style (Alignment 8 = top-
    # centre). Slightly larger than the body caption with a thicker outline so
    # it reads as a headline; safe top margin keeps it off the very edge.
    # V1.1 WU SP2: a carded clip (top-N by virality) swaps the plain headline for
    # the OpusClip HOOK CARD style — a white opaque box with bold black text in
    # the upper third, time-boxed to the first ~5 s (the event below).
    title_text = wrap_hook_title(hook_title or "")
    if title_text:
        if hook_card:
            styles.append(_hook_card.hook_card_style_line(play_x, play_y))
        else:
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

    events: list[str] = []

    # P3-A: emit the hook-title event FIRST so it draws above the body captions.
    # WU SP2: a carded clip emits a HookCard event time-boxed to the first ~5 s
    # (NOT the whole clip), capped to the clip length when known.
    if title_text:
        if hook_card:
            card_end = _hook_card.hook_card_end_sec(hook_card_sec, total_sec)
            events.append(
                f"Dialogue: 0,{format_ass_timestamp(0.0)},{format_ass_timestamp(card_end)},"
                f"{_hook_card.HOOK_CARD_STYLE_NAME},,0,0,0,,{title_text}"
            )
        else:
            title_end = float(total_sec)
            if title_end <= 0.0:
                # No probed duration: span to the last cue (clip-local) or a 60s
                # floor (the §5 hard max clip length) so the headline persists.
                cue_ends = [rebase_cue_time(c.get("end", 0.0), source_start) for c in cues]
                title_end = max(
                    [*cue_ends, _HOOK_TITLE_FALLBACK_SEC],
                    default=_HOOK_TITLE_FALLBACK_SEC,
                )
            events.append(
                f"Dialogue: 0,{format_ass_timestamp(0.0)},{format_ass_timestamp(title_end)},HookTitle,,0,0,0,,{title_text}"
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
            f"{render_cue_text(cue, uppercase=resolved.uppercase)}"
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

    An apostrophe cannot be backslash-escaped inside single quotes (a backslash
    is literal there and the next ``'`` always closes the quote). The portable
    idiom is close-quote → escaped-quote → reopen-quote (``'\''``), so a path
    like ``C:\Users\O'Brien\sub.ass`` survives the filtergraph parser.
    """
    # Backslash first, then the filter-special characters.
    p = path.replace("\\", "\\\\")
    p = p.replace(":", "\\:")
    p = p.replace("'", "'\\''")
    return f"'{p}'"


def build_burn_argv(
    clip_path: str,
    ass_path: str,
    out_path: str,
    settings: dict[str, Any] | None = None,
) -> list[str]:
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
        "-i",
        clip_path,
        "-vf",
        vf,
        "-c:a",
        "copy",
        "-progress",
        "pipe:1",
        "-nostats",
        out_path,
    ]


def build_softmux_argv(
    clip_path: str,
    ass_path: str,
    out_path: str,
    settings: dict[str, Any] | None = None,
) -> list[str]:
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
        "-i",
        clip_path,
        "-i",
        ass_path,
        "-map",
        "0:v",
        "-map",
        "0:a?",
        "-map",
        "1:0",
        "-c:v",
        "copy",
        "-c:a",
        "copy",
        "-c:s",
        scodec,
        "-progress",
        "pipe:1",
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
        settings: dict[str, Any] | None = None,
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
        hook_title: str | None = None,
        total_sec: float = 0.0,
        position: Any = None,
        override: Mapping[str, Any] | None = None,
        hook_card: bool = False,
        hook_card_sec: float = 0.0,
    ) -> str:
        """Generate the ASS document (delegates to module-level :func:`build_ass`)."""
        return build_ass(
            cues,
            width=width,
            height=height,
            source_start=source_start,
            hook_title=hook_title,
            total_sec=total_sec,
            position=position,
            override=override,
            hook_card=hook_card,
            hook_card_sec=hook_card_sec,
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
        on_progress: Callable[[float, str], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
        total_sec: float = 0.0,
        hook_title: str | None = None,
        position: Any = None,
        override: Mapping[str, Any] | None = None,
        karaoke: bool = False,
        hook_card: bool = False,
        hook_card_sec: float = 0.0,
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

        When ``karaoke`` is set (the V1.1 WU SP1 ``opusclip-karaoke`` preset), the
        OpusClip word-by-word karaoke ASS is built instead of the standard
        document — same temp-file burn/soft-mux path. ``hook_title``/``override``
        do not apply to the karaoke preset (its look is fixed by the teardown).
        """
        if karaoke:
            from . import caption_karaoke as _karaoke  # lazy: avoid an import cycle

            ass_doc = _karaoke.build_karaoke_ass(
                cues,
                width=width,
                height=height,
                source_start=source_start,
            )
        else:
            ass_doc = build_ass(
                cues,
                width=width,
                height=height,
                source_start=source_start,
                hook_title=hook_title,
                total_sec=total_sec,
                position=position,
                override=override,
                hook_card=hook_card,
                hook_card_sec=hook_card_sec,
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
                raise CaptionError(f"ffmpeg caption render failed (exit {code}) for {out_path}")
            return out_path
        finally:
            # Best-effort cleanup; never mask a CaptionError with a cleanup error.
            with contextlib.suppress(OSError):
                os.unlink(ass_path)
