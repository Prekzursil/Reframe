from media_core.subtitles.builder import (
    GroupingConfig,
    SubtitleLine,
    group_words,
    to_srt,
    to_vtt,
)
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
