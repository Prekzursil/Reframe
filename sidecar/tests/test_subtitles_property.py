"""Property/fuzz tests for media_studio.features.subtitles (WU-B).

Hypothesis-driven invariants over the edge-dense pure parser/serializer logic:

  * timestamp format -> parse round-trips within the format's quantization
    (SRT/VTT = ms, ASS = cs) and is monotonic in the input,
  * cue serialize -> parse round-trips (srt/vtt/ass) preserving timing (within
    the format epsilon) and text for inputs the format can represent,
  * ``parse``/``read_*`` over arbitrary text never crash other than the
    documented ``ValueError`` (and ``parse_timestamp`` is total-or-ValueError),
  * structural invariants of ``reindex`` / ``new_track`` / ``stack_cue_text`` /
    ``stack_bilingual``.

Append-only: this file ADDS coverage; it touches no source and no existing test.
The deterministic ``ci`` Hypothesis profile (conftest) keeps the gate stable.
"""

from __future__ import annotations

import math

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st
from media_studio.features import subtitles as S

# --------------------------------------------------------------------------- #
# strategies
# --------------------------------------------------------------------------- #
# Non-negative times bounded so float formatting stays in the hours range the
# H:MM:SS forms can render. ms granularity avoids sub-ms noise the formats drop.
_times = st.floats(min_value=0.0, max_value=359_999.0, allow_nan=False, allow_infinity=False)

# Cue text the subtitle formats can faithfully carry: no blank line (the SRT/VTT
# block separator), no CR/LF (the serializers strip a trailing "\n" but a blank
# interior line would split a block on re-parse), and no leading/trailing space
# that ``.strip()`` in the serializer would drop. We also keep "-->" out so a
# text line is never mistaken for a timing line by the tolerant parsers.
_text_chars = st.characters(
    min_codepoint=0x20,
    max_codepoint=0x2FFF,
    blacklist_characters="\n\r",
    blacklist_categories=("Cs",),
)
_cue_text = (
    st.text(_text_chars, min_size=1, max_size=40)
    .map(lambda s: s.strip())
    .filter(lambda s: s and "-->" not in s and "﻿" not in s)
)


@st.composite
def _cue(draw: st.DrawFn) -> dict:
    """A cue whose end strictly exceeds its start (a renderable interval)."""
    start = draw(_times)
    dur = draw(st.floats(min_value=0.01, max_value=600.0, allow_nan=False))
    return S.make_cue(0, start, start + dur, draw(_cue_text))


_cues = st.lists(_cue(), min_size=0, max_size=8)


# --------------------------------------------------------------------------- #
# timestamp round-trip + monotonicity
# --------------------------------------------------------------------------- #
@given(seconds=_times)
def test_srt_timestamp_roundtrips_within_ms(seconds: float) -> None:
    text = S.format_timestamp_srt(seconds)
    parsed = S.parse_timestamp(text)
    # SRT quantizes to whole milliseconds; the round-trip error is < 1ms.
    assert abs(parsed - seconds) < 1e-3 + 1e-6


@given(seconds=_times)
def test_vtt_timestamp_roundtrips_within_ms(seconds: float) -> None:
    parsed = S.parse_timestamp(S.format_timestamp_vtt(seconds))
    assert abs(parsed - seconds) < 1e-3 + 1e-6


@given(seconds=_times)
def test_ass_timestamp_roundtrips_within_cs(seconds: float) -> None:
    # ASS quantizes to centiseconds; the round-trip error is < 10ms.
    parsed = S.parse_timestamp(S.format_timestamp_ass(seconds))
    assert abs(parsed - seconds) < 1e-2 + 1e-6


@given(a=_times, b=_times)
def test_srt_timestamp_format_is_monotonic(a: float, b: float) -> None:
    # Rounding to the same ms can tie; a strict-vs-equal split keeps it exact.
    assume(abs(a - b) >= 1e-3)
    fa, fb = S.format_timestamp_srt(a), S.format_timestamp_srt(b)
    if a < b:
        assert S.parse_timestamp(fa) <= S.parse_timestamp(fb)
    else:
        assert S.parse_timestamp(fb) <= S.parse_timestamp(fa)


@given(
    h=st.integers(min_value=0, max_value=99),
    m=st.integers(min_value=0, max_value=59),
    s=st.integers(min_value=0, max_value=59),
    ms=st.integers(min_value=0, max_value=999),
)
def test_parse_timestamp_decodes_components(h: int, m: int, s: int, ms: int) -> None:
    text = f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
    assert math.isclose(S.parse_timestamp(text), h * 3600 + m * 60 + s + ms / 1000.0, abs_tol=1e-9)


@given(text=st.text(max_size=30))
def test_parse_timestamp_is_total_or_valueerror(text: str) -> None:
    # Contract: a parseable timestamp -> a finite non-negative float; anything
    # else raises ValueError. Never any other exception.
    try:
        out = S.parse_timestamp(text)
    except ValueError:
        return
    assert isinstance(out, float)
    assert out >= 0.0 and math.isfinite(out)


# --------------------------------------------------------------------------- #
# serialize -> parse round-trip (srt / vtt / ass)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("fmt", ["srt", "vtt", "ass"])
@given(cues=_cues)
def test_serialize_parse_roundtrip_preserves_timing_and_text(fmt: str, cues: list[dict]) -> None:
    track = S.new_track(cues, fmt=fmt)
    text = S.serialize(track, fmt)
    parsed = S.parse(text, fmt)
    expected = S.reindex(cues)
    assert len(parsed) == len(expected)
    eps = 1e-2 + 1e-6 if fmt == "ass" else 1e-3 + 1e-6
    for got, exp in zip(parsed, expected, strict=True):
        assert got["index"] == exp["index"]
        assert abs(got["start"] - exp["start"]) < eps
        assert abs(got["end"] - exp["end"]) < eps
        assert got["text"] == exp["text"]


@given(cues=_cues)
def test_to_srt_blocks_count_matches_cues(cues: list[dict]) -> None:
    text = S.to_srt(cues)
    if not cues:
        assert text == ""
        return
    # Re-parse rather than scan digit lines (a cue's TEXT may itself be a bare
    # number, which would fool a naive "index line = digits" heuristic).
    assert [c["index"] for c in S.read_srt(text)] == list(range(1, len(cues) + 1))


@given(cues=_cues)
def test_to_vtt_always_has_webvtt_header(cues: list[dict]) -> None:
    assert S.to_vtt(cues).startswith("WEBVTT\n\n")


# --------------------------------------------------------------------------- #
# robustness: parsers never crash on arbitrary text
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("reader", [S.read_srt, S.read_vtt, S.read_ass])
@given(text=st.text(max_size=200))
def test_readers_return_list_or_raise_valueerror(reader, text: str) -> None:
    try:
        cues = reader(text)
    except ValueError:
        return  # a malformed timestamp legitimately raises
    assert isinstance(cues, list)
    # Whatever survived is a well-formed, 1..N-reindexed cue list.
    for i, cue in enumerate(cues, start=1):
        assert cue["index"] == i
        assert set(cue) >= {"index", "start", "end", "text"}


# --------------------------------------------------------------------------- #
# structural invariants: reindex / new_track / bilingual
# --------------------------------------------------------------------------- #
@given(cues=_cues)
def test_reindex_is_sequential_and_nonmutating(cues: list[dict]) -> None:
    snapshot = [dict(c) for c in cues]
    out = S.reindex(cues)
    assert [c["index"] for c in out] == list(range(1, len(cues) + 1))
    # input list is not mutated (fresh dicts returned)
    assert cues == snapshot


@given(cues=_cues)
def test_reindex_is_idempotent(cues: list[dict]) -> None:
    once = S.reindex(cues)
    twice = S.reindex(once)
    assert once == twice


@given(cues=_cues, fmt=st.sampled_from(S.FORMATS))
def test_new_track_has_all_schema_fields(cues: list[dict], fmt: str) -> None:
    track = S.new_track(cues, fmt=fmt)
    assert set(track) == {"id", "lang", "name", "format", "kind", "cues"}
    assert track["kind"] == "soft"
    assert track["format"] == fmt
    assert [c["index"] for c in track["cues"]] == list(range(1, len(cues) + 1))


@given(kind=st.text(max_size=8))
def test_new_track_kind_is_coerced(kind: str) -> None:
    track = S.new_track([], kind=kind)
    assert track["kind"] == (kind if kind in ("soft", "hard") else "soft")


@given(
    original=_cue_text,
    translation=_cue_text,
    order=st.sampled_from(S.BILINGUAL_ORDERS),
)
def test_stack_cue_text_orders_and_keeps_both_lines(original: str, translation: str, order: str) -> None:
    stacked = S.stack_cue_text(original, translation, order=order)
    lines = stacked.split("\n")
    assert len(lines) == 2
    top, bottom = (original, translation) if order != "translation-first" else (translation, original)
    assert lines[0] == top.strip()
    assert lines[1] == bottom.strip()


@given(text=_cue_text, order=st.sampled_from(S.BILINGUAL_ORDERS))
def test_stack_cue_text_drops_blank_half(text: str, order: str) -> None:
    assert S.stack_cue_text(text, "   ", order=order) == text.strip()
    assert S.stack_cue_text("", text, order=order) == text.strip()


@given(cues=st.lists(_cue(), min_size=1, max_size=6))
def test_stack_bilingual_preserves_timing_and_count(cues: list[dict]) -> None:
    orig = S.new_track(cues, lang="en")
    trans = S.translate(orig, "es", translator=lambda s: f"[{s}]")
    bil = S.stack_bilingual(orig, S.new_track(trans["cues"], lang="es"), order="original-first")
    assert bil["lang"] == "en+es"
    assert len(bil["cues"]) == len(orig["cues"])
    for got, src in zip(bil["cues"], orig["cues"], strict=True):
        assert got["start"] == src["start"]
        assert got["end"] == src["end"]
        # the original line is on top; the bracketed translation underneath
        assert got["text"].split("\n")[0] == src["text"]
