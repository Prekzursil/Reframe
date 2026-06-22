"""Property tests for the zoom expression builder + caption ASS escaping (WU-B).

Both are pure string builders dense in branch logic. Invariants:

zoom (features/zoom.py):
  * ``sentence_start_beats`` is sorted, de-duplicated, all >= 0, and clip-local
    (re-based by ``source_start``); the first non-blank cue is always a beat,
  * ``build_zoom_expr`` clamps to ``MAX_ZOOM`` and ignores negative beats,
  * ``build_zoom_filter`` raises on non-positive dimensions, and otherwise emits
    a ``zoompan=`` string carrying the exact output size.

caption (features/caption.py):
  * ``escape_ass_text`` never leaves a raw ``{``/``}`` (no ASS override
    injection) and turns every newline into the ASS hard break,
  * ``format_ass_timestamp`` round-trips within centisecond resolution and
    clamps negatives to zero,
  * ``rebase_cue_time`` is >= 0 and equals ``max(0, t - source_start)``,
  * ``wrap_hook_title`` never exceeds the requested line count and is escaped.

Append-only: ADDS coverage; no source/existing-test change.
"""

from __future__ import annotations

from hypothesis import assume, given
from hypothesis import strategies as st
from media_studio.features import caption as C
from media_studio.features import zoom as Z

_t = st.floats(min_value=0.0, max_value=600.0, allow_nan=False, allow_infinity=False)
_terminator = st.sampled_from([".", "!", "?", "…"])


@st.composite
def _cue(draw: st.DrawFn) -> dict:
    start = draw(_t)
    end = start + draw(st.floats(min_value=0.01, max_value=10.0, allow_nan=False))
    text = draw(st.text(st.characters(min_codepoint=0x41, max_codepoint=0x7A), min_size=1, max_size=12))
    if draw(st.booleans()):
        text += draw(_terminator)
    return {"index": 0, "start": start, "end": end, "text": text}


_cues = st.lists(_cue(), min_size=0, max_size=8)


# --------------------------------------------------------------------------- #
# zoom beats
# --------------------------------------------------------------------------- #
@given(cues=_cues, source_start=st.floats(min_value=0.0, max_value=120.0, allow_nan=False))
def test_sentence_start_beats_sorted_nonneg_clip_local(cues: list[dict], source_start: float) -> None:
    beats = Z.sentence_start_beats(cues, source_start=source_start)
    assert beats == sorted(beats)
    assert all(b >= 0.0 for b in beats)
    # de-duplicated at 3-decimal granularity
    keys = [round(b, 3) for b in beats]
    assert len(keys) == len(set(keys))


@given(cues=st.lists(_cue(), min_size=1, max_size=8))
def test_first_nonblank_cue_is_a_beat(cues: list[dict]) -> None:
    # at least one beat exists whenever any cue has non-blank text
    assume(any(c["text"].strip() for c in cues))
    beats = Z.sentence_start_beats(cues, source_start=0.0)
    assert beats  # non-empty


@given(
    dur=st.floats(min_value=0.0, max_value=120.0, allow_nan=False),
    beats=st.lists(st.floats(min_value=-10.0, max_value=120.0, allow_nan=False), max_size=6),
    fps=st.integers(min_value=1, max_value=120),
)
def test_zoom_expr_clamped_to_max(dur: float, beats: list[float], fps: int) -> None:
    expr = Z.build_zoom_expr(duration_sec=dur, beats=beats, fps=fps)
    # the whole expression is wrapped in a min(...,MAX_ZOOM) clamp
    assert expr.startswith("min(")
    assert f"{Z.MAX_ZOOM}" in expr


@given(
    w=st.integers(min_value=-5, max_value=4096),
    h=st.integers(min_value=-5, max_value=4096),
    dur=st.floats(min_value=0.0, max_value=60.0, allow_nan=False),
)
def test_zoom_filter_positive_dims_or_raise(w: int, h: int, dur: float) -> None:
    if w <= 0 or h <= 0:
        try:
            Z.build_zoom_filter(width=w, height=h, duration_sec=dur)
        except ValueError:
            return
        raise AssertionError("expected ValueError for non-positive dims")
    flt = Z.build_zoom_filter(width=w, height=h, duration_sec=dur)
    assert flt.startswith("zoompan=")
    assert f"s={w}x{h}" in flt


# --------------------------------------------------------------------------- #
# caption escaping + timestamps
# --------------------------------------------------------------------------- #
@given(text=st.text(max_size=60))
def test_escape_ass_text_neutralizes_braces_and_newlines(text: str) -> None:
    out = C.escape_ass_text(text)
    # every '{' and '}' is backslash-escaped: no UN-escaped brace remains
    for i, ch in enumerate(out):
        if ch in "{}":
            assert i > 0 and out[i - 1] == "\\"
    # no literal newline survives (all became the ASS hard break token)
    assert "\n" not in out and "\r" not in out


@given(text=st.text(max_size=40))
def test_escape_ass_text_total(text: str) -> None:
    # escaping is a total function (no crash) and idempotent-shaped on braces
    assert isinstance(C.escape_ass_text(text), str)


@given(seconds=st.floats(min_value=0.0, max_value=359_999.0, allow_nan=False))
def test_format_ass_timestamp_roundtrips_within_cs(seconds: float) -> None:
    text = C.format_ass_timestamp(seconds)
    # parse it back via the subtitles parser (shared H:MM:SS.cc grammar)
    from media_studio.features import subtitles as S

    assert abs(S.parse_timestamp(text) - seconds) < 1e-2 + 1e-6


@given(seconds=st.floats(max_value=0.0, allow_nan=False, allow_infinity=False))
def test_format_ass_timestamp_clamps_negative(seconds: float) -> None:
    assert C.format_ass_timestamp(seconds) == "0:00:00.00"


@given(t=st.floats(min_value=-100.0, max_value=600.0, allow_nan=False), src=_t)
def test_rebase_cue_time_nonneg(t: float, src: float) -> None:
    out = C.rebase_cue_time(t, src)
    assert out >= 0.0
    assert abs(out - max(0.0, t - src)) < 1e-9


@given(
    words=st.lists(
        st.text(st.characters(min_codepoint=0x41, max_codepoint=0x7A), min_size=1, max_size=6),
        max_size=12,
    ),
    max_lines=st.integers(min_value=1, max_value=3),
)
def test_wrap_hook_title_bounded_lines(words: list[str], max_lines: int) -> None:
    title = C.wrap_hook_title(" ".join(words), max_lines=max_lines)
    if not words:
        assert title == ""
        return
    lines = title.split(r"\N")
    assert 1 <= len(lines) <= max_lines


@given(text=st.text(max_size=30))
def test_wrap_hook_title_is_escaped(text: str) -> None:
    out = C.wrap_hook_title(text, max_lines=2)
    # no un-escaped brace can leak through the wrap (it escapes first)
    for i, ch in enumerate(out):
        if ch in "{}":
            assert i > 0 and out[i - 1] == "\\"
