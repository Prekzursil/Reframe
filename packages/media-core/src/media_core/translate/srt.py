from __future__ import annotations

import re
from typing import Iterable, List, Tuple

from media_core.subtitles.builder import SubtitleLine, to_srt
from media_core.transcribe.models import Word
from media_core.translate.translator import Translator


_TIME_RE = re.compile(
    r"(?P<h>\d{2}):(?P<m>\d{2}):(?P<s>\d{2}),(?P<ms>\d{3})"
)


def _parse_timestamp(ts: str) -> float:
    match = _TIME_RE.match(ts.strip())
    if not match:
        raise ValueError(f"Invalid timestamp: {ts}")
    h, m, s, ms = (int(match.group(x)) for x in ("h", "m", "s", "ms"))
    return h * 3600 + m * 60 + s + ms / 1000.0


def parse_srt(srt_text: str) -> List[SubtitleLine]:
    lines: List[SubtitleLine] = []
    blocks = re.split(r"\n\s*\n", srt_text.strip(), flags=re.MULTILINE)
    for block in blocks:
        parts = block.strip().splitlines()
        if len(parts) < 2:
            continue
        # Skip index line if present
        if re.match(r"^\d+$", parts[0].strip()):
            parts = parts[1:]
        if not parts:
            continue
        timing = parts[0]
        content = " ".join(p.strip() for p in parts[1:])
        try:
            start_str, end_str = timing.split("-->")
            start = _parse_timestamp(start_str)
            end = _parse_timestamp(end_str)
        except Exception as exc:
            raise ValueError(f"Invalid timing line: {timing}") from exc
        words = [Word(text=content, start=start, end=end)]
        lines.append(SubtitleLine(start=start, end=end, words=words))
    return lines


def translate_srt(srt_text: str, translator: Translator, src: str, tgt: str) -> str:
    lines = parse_srt(srt_text)
    texts = [line.text() for line in lines]
    translated = translator.translate_batch(texts, src, tgt)
    translated_lines: List[SubtitleLine] = []
    for line, new_text in zip(lines, translated):
        translated_lines.append(
            SubtitleLine(
                start=line.start,
                end=line.end,
                speaker=line.speaker,
                words=[Word(text=new_text, start=line.start, end=line.end)],
            )
        )
    return to_srt(translated_lines)


def translate_srt_bilingual(
    srt_text: str,
    translator: Translator,
    src: str,
    tgt: str,
    separator: str = "\\N",
) -> str:
    """Return bilingual SRT where each line includes original and translated text."""
    lines = parse_srt(srt_text)
    texts = [line.text() for line in lines]
    translated = translator.translate_batch(texts, src, tgt)
    bilingual_lines: List[SubtitleLine] = []
    for line, new_text in zip(lines, translated):
        combined = f"{line.text()}{separator}{new_text}"
        bilingual_lines.append(
            SubtitleLine(
                start=line.start,
                end=line.end,
                speaker=line.speaker,
                words=[Word(text=combined, start=line.start, end=line.end)],
            )
        )
    return to_srt(bilingual_lines)
