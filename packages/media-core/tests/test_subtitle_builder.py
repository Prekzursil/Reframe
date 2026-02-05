from media_core.subtitles.builder import (
    GroupingConfig,
    SubtitleLine,
    group_words,
    to_srt,
    to_ass,
    to_ass_karaoke,
    to_vtt,
)
from media_core.subtitles.vtt import parse_vtt
from media_core.transcribe.models import Word


def test_group_words_respects_limits_and_sorting():
    words = [
        Word(text="hello", start=0.0, end=0.5),
        Word(text="world", start=0.6, end=1.1),
        Word(text="this", start=3.0, end=3.4),
        Word(text="is", start=3.5, end=3.7),
        Word(text="long", start=3.8, end=4.5),
    ]
    cfg = GroupingConfig(max_chars_per_line=11, max_words_per_line=2, max_gap=0.7, max_duration=3.0)
    lines = group_words(words, cfg)
    assert len(lines) == 3
    assert [line.text() for line in lines] == ["hello world", "this is", "long"]
    assert lines[0].start == 0.0 and lines[0].end == 1.1
    assert lines[1].start == 3.0 and lines[1].end == 3.7


def test_to_srt_and_vtt_render_simple_lines():
    line = SubtitleLine(
        start=1.0,
        end=2.5,
        words=[Word(text="sample", start=1.0, end=1.5), Word(text="text", start=1.6, end=2.0)],
    )
    srt = to_srt([line])
    vtt = to_vtt([line])
    assert "00:00:01,000 --> 00:00:02,500" in srt
    assert "00:00:01.000 --> 00:00:02.500" in vtt
    assert "sample text" in srt and "sample text" in vtt


def test_to_ass_renders_dialogue_lines():
    line = SubtitleLine(
        start=1.0,
        end=2.0,
        words=[Word(text="hello", start=1.0, end=1.4), Word(text="world", start=1.5, end=1.9)],
    )
    ass = to_ass([line])
    assert "[Script Info]" in ass
    assert "Dialogue:" in ass
    assert "hello world" in ass


def test_group_words_handles_fast_and_slow_speech():
    # Fast speech with small gaps should stay together.
    fast_words = [
        Word(text="quick", start=0.0, end=0.2),
        Word(text="brown", start=0.25, end=0.4),
        Word(text="fox", start=0.45, end=0.6),
    ]
    cfg_fast = GroupingConfig(max_gap=0.5, max_duration=2.0, max_words_per_line=5, max_chars_per_line=30)
    fast_lines = group_words(fast_words, cfg_fast)
    assert len(fast_lines) == 1

    # Slow speech with a large pause should split.
    slow_words = [
        Word(text="hello", start=0.0, end=0.5),
        Word(text="again", start=5.0, end=5.5),
    ]
    cfg_slow = GroupingConfig(max_gap=1.0, max_duration=4.0, max_words_per_line=5, max_chars_per_line=30)
    slow_lines = group_words(slow_words, cfg_slow)
    assert len(slow_lines) == 2


def test_grouping_handles_multilingual_tokens():
    words = [
        Word(text="hola", start=0.0, end=0.4),
        Word(text="bonjour", start=0.5, end=1.0),
        Word(text="hello", start=1.6, end=2.0),
    ]
    cfg = GroupingConfig(max_gap=0.6, max_duration=3.0, max_words_per_line=4, max_chars_per_line=20)
    lines = group_words(words, cfg)
    # First two are close and short; third is separated by gap
    assert len(lines) == 2
    assert lines[0].text() == "hola bonjour"
    assert lines[1].text() == "hello"


def test_parse_vtt_parses_basic_cue():
    vtt = "WEBVTT\n\n00:00:01.000 --> 00:00:02.500\nhello world\n\n"
    lines = parse_vtt(vtt)
    assert len(lines) == 1
    assert lines[0].start == 1.0
    assert lines[0].end == 2.5
    assert lines[0].text() == "hello world"


def test_to_ass_karaoke_includes_k_tags():
    line = SubtitleLine(start=1.0, end=2.0, words=[Word(text="hello world", start=1.0, end=2.0)])
    ass = to_ass_karaoke([line])
    assert "Dialogue:" in ass
    assert "{\\k" in ass
