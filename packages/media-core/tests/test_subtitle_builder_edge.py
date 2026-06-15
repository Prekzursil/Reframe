"""Edge-case coverage for subtitle grouping and ASS/VTT rendering helpers."""

from __future__ import annotations

import sys
import types

import pytest

from media_core.subtitles import builder
from media_core.subtitles.builder import (
    GroupingConfig,
    SubtitleLine,
    _allocate_karaoke_durations_cs,
    _karaoke_text_for_line,
    _normalize_words,
    group_words,
    to_ass,
    to_ass_karaoke,
    to_vtt,
)
from media_core.transcribe.models import Word


def test_normalize_words_without_repair_keeps_order():
    words = [Word(text="b", start=1.0, end=1.5), Word(text="a", start=0.0, end=0.5)]
    cfg = GroupingConfig(repair_overlaps=False)
    out = _normalize_words(words, cfg)
    # Sorted by (start, end) but NOT repaired.
    assert [w.text for w in out] == ["a", "b"]
    assert out[0].start == 0.0


def test_group_words_empty_returns_empty():
    assert group_words([], GroupingConfig()) == []


def test_to_vtt_includes_speaker_prefix():
    line = SubtitleLine(
        start=0.0,
        end=1.0,
        words=[Word(text="hi", start=0.0, end=1.0)],
        speaker="SPEAKER_01",
    )
    out = to_vtt([line])
    assert "SPEAKER_01: hi" in out


def test_allocate_karaoke_durations_empty_tokens():
    assert _allocate_karaoke_durations_cs([], 100) == []


def test_allocate_karaoke_durations_nonpositive_total():
    # total_cs <= 0 -> reset to len(tokens); each token gets >= 1 cs.
    durations = _allocate_karaoke_durations_cs(["a", "b", "c"], 0)
    assert len(durations) == 3
    assert all(d >= 1 for d in durations)


def test_allocate_karaoke_durations_total_less_than_tokens():
    # total_cs < len(tokens) -> every token gets exactly 1.
    durations = _allocate_karaoke_durations_cs(["a", "b", "c", "d"], 2)
    assert durations == [1, 1, 1, 1]


def test_allocate_karaoke_durations_distributes_remainder():
    # total > sum of base weights -> delta > 0 branch distributes extra cs.
    tokens = ["aa", "b"]
    total = 100
    durations = _allocate_karaoke_durations_cs(tokens, total)
    assert sum(durations) == total
    # Longer token receives the larger share.
    assert durations[0] >= durations[1]


def test_allocate_karaoke_durations_removes_excess():
    # base = [max(1, int(3*1/6)), max(1, int(3*1/6)), max(1, int(3*4/6))] = [1, 1, 2]
    # sum(base) = 4 > total (3) -> the delta < 0 trim branch runs.
    tokens = ["x", "x", "xxxx"]
    total = 3
    durations = _allocate_karaoke_durations_cs(tokens, total)
    assert sum(durations) == total
    assert all(d >= 1 for d in durations)


def test_allocate_karaoke_durations_trim_skips_min_duration_tokens():
    # base = [1, 1, 1, 1, 3], delta = -2. The trim loop walks the weight-sorted
    # order and must SKIP the four min-duration (==1) tokens (the `durations[idx] > 1`
    # else branch) before trimming the long token twice.
    tokens = ["x", "x", "x", "x", "xxxxxx"]
    total = 5
    durations = _allocate_karaoke_durations_cs(tokens, total)
    assert sum(durations) == total
    assert all(d >= 1 for d in durations)


def test_karaoke_text_for_line_uses_real_word_timings():
    line = SubtitleLine(
        start=0.0,
        end=2.0,
        words=[
            Word(text="hello", start=0.0, end=1.0),
            Word(text="world", start=1.0, end=2.0),
        ],
    )
    text = _karaoke_text_for_line(line)
    # Two \k tags, one per real word.
    assert text.count("{\\k") == 2
    assert "hello" in text and "world" in text


def test_to_ass_karaoke_synthesizes_when_single_word():
    # A single multi-token "word" forces the tokenize/synthesize path.
    line = SubtitleLine(start=0.0, end=2.0, words=[Word(text="one two three", start=0.0, end=2.0)])
    ass = to_ass_karaoke([line])
    assert ass.count("{\\k") == 3


def test_to_ass_uses_pysubs2_when_available(monkeypatch):
    """When pysubs2 is importable, to_ass delegates to it."""

    class FakeStyle:
        def __init__(self):
            self.name = ""

    class FakeEvent:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeSSAFile:
        def __init__(self):
            self.styles = {}
            self.events = []

        def to_string(self, fmt):
            assert fmt == "ass"
            return f"FAKE_ASS:{len(self.events)} events"

    fake_pysubs2 = types.ModuleType("pysubs2")
    fake_pysubs2.SSAFile = FakeSSAFile
    fake_pysubs2.SSAStyle = FakeStyle
    fake_pysubs2.SSAEvent = FakeEvent
    monkeypatch.setitem(sys.modules, "pysubs2", fake_pysubs2)

    line = SubtitleLine(start=0.0, end=1.0, words=[Word(text="hello", start=0.0, end=1.0)])
    out = to_ass([line])
    assert out == "FAKE_ASS:1 events"


def test_to_ass_manual_fallback_without_pysubs2(monkeypatch):
    # Force the import of pysubs2 to fail so the manual-formatting branch runs.
    real_import = __import__

    def fake_import(name, *args, **kwargs):
        if name == "pysubs2":
            raise ImportError("not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)
    line = SubtitleLine(
        start=0.0,
        end=1.0,
        words=[Word(text="hi", start=0.0, end=1.0)],
        speaker="SPEAKER_00",
    )
    out = to_ass([line])
    assert "[Script Info]" in out
    assert "SPEAKER_00: hi" in out


def test_builder_module_exports_present():
    assert hasattr(builder, "group_words")
