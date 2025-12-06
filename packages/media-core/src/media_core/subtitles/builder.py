from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, List, Sequence

from media_core.transcribe.models import Word


@dataclass
class SubtitleLine:
    start: float
    end: float
    words: List[Word] = field(default_factory=list)

    def text(self) -> str:
        return " ".join(w.text for w in self.words).strip()

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


@dataclass
class GroupingConfig:
    max_chars_per_line: int = 40
    max_words_per_line: int = 12
    max_duration: float = 6.0
    max_gap: float = 0.6


def group_words(words: Sequence[Word], config: GroupingConfig) -> List[SubtitleLine]:
    lines: List[SubtitleLine] = []
    if not words:
        return lines

    current_words: List[Word] = []
    current_start = words[0].start
    last_end = words[0].end

    def flush():
        nonlocal current_words, current_start, last_end
        if current_words:
            lines.append(SubtitleLine(start=current_start, end=last_end, words=current_words.copy()))
        current_words = []

    for w in words:
        if not current_words:
            current_start = w.start
            last_end = w.end
            current_words.append(w)
            continue

        candidate_text = " ".join([*(cw.text for cw in current_words), w.text])
        too_many_chars = len(candidate_text) > config.max_chars_per_line
        too_many_words = len(current_words) + 1 > config.max_words_per_line
        too_long = (w.end - current_start) > config.max_duration
        too_far = (w.start - last_end) > config.max_gap

        if too_many_chars or too_many_words or too_long or too_far:
            flush()
            current_start = w.start
            last_end = w.end
            current_words.append(w)
            continue

        current_words.append(w)
        last_end = w.end

    flush()
    return lines


def _format_timestamp(seconds: float) -> str:
    millis = int(round(seconds * 1000))
    hours, rem = divmod(millis, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1_000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def to_srt(lines: Iterable[SubtitleLine]) -> str:
    output = []
    for idx, line in enumerate(lines, start=1):
        output.append(str(idx))
        output.append(f"{_format_timestamp(line.start)} --> {_format_timestamp(line.end)}")
        output.append(line.text())
        output.append("")  # blank line separator
    return "\n".join(output)


def to_vtt(lines: Iterable[SubtitleLine]) -> str:
    output = ["WEBVTT", ""]
    for line in lines:
        output.append(f"{_format_timestamp(line.start).replace(',', '.')} --> {_format_timestamp(line.end).replace(',', '.')}")
        output.append(line.text())
        output.append("")
    return "\n".join(output)
