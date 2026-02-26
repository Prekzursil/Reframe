from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, List, Sequence

from media_core.transcribe.models import Word


@dataclass
class SubtitleLine:
    start: float
    end: float
    words: List[Word] = field(default_factory=list)
    speaker: str | None = None

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
    max_chars_per_second: float = 35.0
    sentence_break_on_punctuation: bool = True
    sentence_break_min_gap: float = 0.05
    repair_overlaps: bool = True
    min_word_duration: float = 0.01


_SENTENCE_BREAK_RE = re.compile(r"[.!?…]+[\"')\]]*$")


def _normalize_words(words: Sequence[Word], config: GroupingConfig) -> list[Word]:
    ordered = sorted(words, key=lambda item: (item.start, item.end))
    if not config.repair_overlaps:
        return ordered

    repaired: list[Word] = []
    prev_end = 0.0
    for word in ordered:
        start = max(float(word.start), prev_end)
        end = max(float(word.end), start + max(0.001, float(config.min_word_duration)))
        if start != word.start or end != word.end:
            word = word.model_copy(update={"start": start, "end": end})
        repaired.append(word)
        prev_end = end
    return repaired


def _ends_sentence(text: str) -> bool:
    return bool(_SENTENCE_BREAK_RE.search((text or "").strip()))


def group_words(words: Sequence[Word], config: GroupingConfig) -> List[SubtitleLine]:
    lines: List[SubtitleLine] = []
    normalized_words = _normalize_words(words, config)
    if not normalized_words:
        return lines

    current_words: List[Word] = []
    current_start = normalized_words[0].start
    last_end = normalized_words[0].end

    def flush():
        nonlocal current_words, current_start, last_end
        if current_words:
            lines.append(SubtitleLine(start=current_start, end=last_end, words=current_words.copy()))
        current_words = []

    for w in normalized_words:
        if not current_words:
            current_start = w.start
            last_end = w.end
            current_words.append(w)
            continue

        sentence_break = (
            config.sentence_break_on_punctuation
            and _ends_sentence(current_words[-1].text)
            and (w.start - last_end) >= max(0.0, float(config.sentence_break_min_gap))
        )
        if sentence_break:
            flush()
            current_start = w.start
            last_end = w.end
            current_words.append(w)
            continue

        candidate_text = " ".join([*(cw.text for cw in current_words), w.text])
        candidate_end = max(last_end, w.end)
        candidate_duration = max(0.001, candidate_end - current_start)
        candidate_cps = len(candidate_text) / candidate_duration
        too_many_chars = len(candidate_text) > config.max_chars_per_line
        too_many_words = len(current_words) + 1 > config.max_words_per_line
        too_long = (w.end - current_start) > config.max_duration
        too_far = (w.start - last_end) > config.max_gap
        too_dense = candidate_cps > max(1.0, float(config.max_chars_per_second))

        if too_many_chars or too_many_words or too_long or too_far or too_dense:
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
        text = line.text()
        if line.speaker:
            text = f"{line.speaker}: {text}" if text else line.speaker
        output.append(text)
        output.append("")  # blank line separator
    return "\n".join(output)


def to_vtt(lines: Iterable[SubtitleLine]) -> str:
    output = ["WEBVTT", ""]
    for line in lines:
        output.append(f"{_format_timestamp(line.start).replace(',', '.')} --> {_format_timestamp(line.end).replace(',', '.')}")
        text = line.text()
        if line.speaker:
            text = f"{line.speaker}: {text}" if text else line.speaker
        output.append(text)
        output.append("")
    return "\n".join(output)


def _format_ass_timestamp(seconds: float) -> str:
    centis = int(round(seconds * 100))
    hours, rem = divmod(centis, 360_000)
    minutes, rem = divmod(rem, 6_000)
    secs, cs = divmod(rem, 100)
    return f"{hours:d}:{minutes:02d}:{secs:02d}.{cs:02d}"


def _tokenize_for_karaoke(text: str) -> List[str]:
    return re.findall(r"\S+", text.strip())


def _allocate_karaoke_durations_cs(tokens: List[str], total_cs: int) -> List[int]:
    if not tokens:
        return []

    # ASS karaoke durations are centiseconds. If the cue is extremely short, we still
    # want word-by-word highlighting rather than zero-duration tags.
    if total_cs <= 0:
        total_cs = len(tokens)

    if total_cs < len(tokens):
        return [1] * len(tokens)

    weights = [max(1, len(t)) for t in tokens]
    denom = sum(weights) or len(tokens)
    durations = [max(1, int(total_cs * w / denom)) for w in weights]

    delta = total_cs - sum(durations)
    if delta > 0:
        # Add remaining centiseconds to longer tokens first.
        order = sorted(range(len(tokens)), key=lambda i: weights[i], reverse=True)
        i = 0
        while delta > 0:
            durations[order[i % len(order)]] += 1
            delta -= 1
            i += 1
    elif delta < 0:
        # Remove extra centiseconds from longer tokens while keeping >= 1.
        order = sorted(range(len(tokens)), key=lambda i: weights[i], reverse=True)
        i = 0
        while delta < 0 and any(d > 1 for d in durations):
            idx = order[i % len(order)]
            if durations[idx] > 1:
                durations[idx] -= 1
                delta += 1
            i += 1
    return durations


def _escape_ass_text(text: str) -> str:
    # Keep it minimal: escape backslashes and braces which can introduce ASS override blocks.
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")


def _karaoke_text_for_line(line: SubtitleLine) -> str:
    # Prefer real word timings when available; otherwise synthesize timings per token.
    if line.words and len(line.words) > 1:
        segments: List[tuple[str, int]] = []
        for w in line.words:
            dur_cs = int(round(max(0.0, w.end - w.start) * 100))
            segments.append((w.text, max(1, dur_cs)))
        return " ".join(f"{{\\k{dur}}}{_escape_ass_text(text)}" for text, dur in segments if text.strip())

    tokens = _tokenize_for_karaoke(line.text())
    total_cs = int(round(max(0.01, line.duration) * 100))
    durations = _allocate_karaoke_durations_cs(tokens, total_cs)
    return " ".join(
        f"{{\\k{dur}}}{_escape_ass_text(token)}" for token, dur in zip(tokens, durations) if token.strip()
    )


def to_ass_karaoke(lines: Iterable[SubtitleLine]) -> str:
    """Render subtitles to ASS with word-by-word karaoke tags (\\k) suitable for libass burn-in."""
    header = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: 384",
        "PlayResY: 288",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
        # SecondaryColour is used by karaoke highlighting; runtime render can override via force_style.
        "Style: Default,Arial,36,&H00FFFFFF,&H0000FFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,2,0,2,10,10,10,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    body: List[str] = []
    for line in lines:
        name = (line.speaker or "").replace(",", " ")
        speaker_prefix = f"{_escape_ass_text(line.speaker)}: " if line.speaker else ""
        body.append(
            f"Dialogue: 0,{_format_ass_timestamp(line.start)},{_format_ass_timestamp(line.end)},"
            f"Default,{name},0,0,0,,{speaker_prefix}{_karaoke_text_for_line(line)}"
        )
    return "\n".join(header + body)


def to_ass(lines: Iterable[SubtitleLine]) -> str:
    """Render subtitles to a basic ASS string. Uses pysubs2 if available; falls back to manual formatting."""
    try:
        import pysubs2  # type: ignore
    except ImportError:
        pysubs2 = None  # type: ignore

    if pysubs2:
        subs = pysubs2.SSAFile()
        style = pysubs2.SSAStyle()
        style.name = "Default"
        subs.styles["Default"] = style
        for line in lines:
            event = pysubs2.SSAEvent(
                start=int(line.start * 1000),
                end=int(line.end * 1000),
                style="Default",
                text=line.text(),
            )
            subs.events.append(event)
        return subs.to_string("ass")

    header = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: 384",
        "PlayResY: 288",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
        "Style: Default,Arial,36,&H00FFFFFF,&H000000FF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,2,0,2,10,10,10,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    body = []
    for line in lines:
        name = (line.speaker or "").replace(",", " ")
        speaker_prefix = f"{line.speaker}: " if line.speaker else ""
        body.append(
            f"Dialogue: 0,{_format_ass_timestamp(line.start)},{_format_ass_timestamp(line.end)},"
            f"Default,{name},0,0,0,,{speaker_prefix}{line.text()}"
        )
    return "\n".join(header + body)
