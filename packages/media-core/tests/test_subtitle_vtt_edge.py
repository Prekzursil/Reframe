"""Edge-case coverage for the minimal WebVTT parser."""

from __future__ import annotations

import pytest

from media_core.subtitles import vtt
from media_core.subtitles.vtt import _parse_timestamp, _parse_timing, parse_vtt


def test_parse_timestamp_rejects_invalid():
    with pytest.raises(ValueError, match="Invalid VTT timestamp"):
        _parse_timestamp("not-a-timestamp")


def test_parse_timing_rejects_invalid():
    with pytest.raises(ValueError, match="Invalid VTT timing line"):
        _parse_timing("garbage-without-arrow")


def test_parse_vtt_skips_empty_cue_content():
    # A timing line followed by only blank content -> the `if content` branch is False.
    text = "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\n   \n\n"
    assert parse_vtt(text) == []


def test_parse_vtt_ignores_note_blocks():
    text = (
        "WEBVTT\n\n"
        "NOTE this is a comment\n"
        "still inside the note\n\n"
        "00:00:01.000 --> 00:00:02.000\n"
        "real cue\n\n"
    )
    lines = parse_vtt(text)
    assert len(lines) == 1
    assert lines[0].text() == "real cue"


def test_parse_vtt_handles_cue_identifier_before_timing():
    text = (
        "WEBVTT\n\n"
        "cue-1\n"
        "00:00:00.500 --> 00:00:01.500\n"
        "hello there\n\n"
    )
    lines = parse_vtt(text)
    assert len(lines) == 1
    assert lines[0].start == pytest.approx(0.5)
    assert lines[0].text() == "hello there"


def test_vtt_module_exports_parse():
    assert hasattr(vtt, "parse_vtt")
