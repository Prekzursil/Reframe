from media_core.diarize import SpeakerSegment, assign_speakers_to_lines
from media_core.subtitles.builder import SubtitleLine, to_srt
from media_core.transcribe.models import Word


def test_assign_speakers_to_lines_prefers_overlap():
    lines = [
        SubtitleLine(start=0.0, end=1.0, words=[Word(text="hello", start=0.0, end=1.0)]),
        SubtitleLine(start=1.0, end=2.0, words=[Word(text="world", start=1.0, end=2.0)]),
    ]
    segments = [
        SpeakerSegment(start=0.0, end=1.4, speaker="SPEAKER_01"),
        SpeakerSegment(start=1.4, end=3.0, speaker="SPEAKER_02"),
    ]

    out = assign_speakers_to_lines(lines, segments)
    assert [l.speaker for l in out] == ["SPEAKER_01", "SPEAKER_02"]


def test_to_srt_prefixes_speaker_when_present():
    line = SubtitleLine(start=0.0, end=1.0, words=[Word(text="hi", start=0.0, end=1.0)], speaker="SPEAKER_01")
    srt = to_srt([line])
    assert "SPEAKER_01: hi" in srt
