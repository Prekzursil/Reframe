from __future__ import annotations

from pathlib import Path
from typing import Iterable, List, Sequence

from media_core.diarize.config import DiarizationBackend, DiarizationConfig
from media_core.diarize.models import SpeakerSegment
from media_core.subtitles.builder import SubtitleLine


def diarize_audio(audio_path: str | Path, config: DiarizationConfig) -> List[SpeakerSegment]:
    """Return speaker segments for the provided audio.

    This is **offline-first**: the default backend is NOOP (returns no speaker labels).
    """
    if config.backend == DiarizationBackend.NOOP:
        return []
    if config.backend == DiarizationBackend.PYANNOTE:
        return _diarize_pyannote(audio_path, config)
    raise ValueError(f"Unknown diarization backend: {config.backend}")


def assign_speakers_to_lines(lines: Sequence[SubtitleLine], segments: Iterable[SpeakerSegment]) -> List[SubtitleLine]:
    """Attach `speaker` labels to subtitle lines based on overlap with diarization segments."""
    segments_list = list(segments)
    if not segments_list:
        return [SubtitleLine(start=l.start, end=l.end, words=l.words, speaker=l.speaker) for l in lines]

    out: List[SubtitleLine] = []
    for line in lines:
        best_speaker: str | None = None
        best_overlap = 0.0
        for seg in segments_list:
            overlap = max(0.0, min(line.end, seg.end) - max(line.start, seg.start))
            if overlap > best_overlap:
                best_overlap = overlap
                best_speaker = seg.speaker
        out.append(SubtitleLine(start=line.start, end=line.end, words=line.words, speaker=best_speaker))
    return out


def _diarize_pyannote(audio_path: str | Path, config: DiarizationConfig) -> List[SpeakerSegment]:
    try:
        from pyannote.audio import Pipeline  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "pyannote diarization backend selected but dependencies are not installed. "
            "Install with: pip install 'media-core[diarize-pyannote]'"
        ) from exc

    path = str(audio_path)
    pipeline = Pipeline.from_pretrained(config.model, use_auth_token=config.huggingface_token)
    diarization = pipeline(path)

    segments: List[SpeakerSegment] = []
    for turn, _, speaker in diarization.itertracks(yield_label=True):
        start = float(turn.start)
        end = float(turn.end)
        if config.min_segment_duration and (end - start) < config.min_segment_duration:
            continue
        segments.append(SpeakerSegment(start=start, end=end, speaker=str(speaker)))
    return segments


__all__ = [
    "DiarizationBackend",
    "DiarizationConfig",
    "SpeakerSegment",
    "assign_speakers_to_lines",
    "diarize_audio",
]

