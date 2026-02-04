from __future__ import annotations

import os
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
    if config.backend == DiarizationBackend.SPEECHBRAIN:
        return _diarize_speechbrain(audio_path, config)
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
    if config.huggingface_token:
        # pyannote.audio switched from `use_auth_token=` to `token=` across versions.
        try:
            pipeline = Pipeline.from_pretrained(config.model, token=config.huggingface_token)
        except TypeError:
            pipeline = Pipeline.from_pretrained(config.model, use_auth_token=config.huggingface_token)
    else:
        pipeline = Pipeline.from_pretrained(config.model)
    diarization = pipeline(path)

    segments: List[SpeakerSegment] = []
    for turn, _, speaker in diarization.itertracks(yield_label=True):
        start = float(turn.start)
        end = float(turn.end)
        if config.min_segment_duration and (end - start) < config.min_segment_duration:
            continue
        segments.append(SpeakerSegment(start=start, end=end, speaker=str(speaker)))
    return segments


def _diarize_speechbrain(audio_path: str | Path, config: DiarizationConfig) -> List[SpeakerSegment]:
    """Basic SpeechBrain diarization (token-free).

    This is a pragmatic fallback when pyannote models are unavailable:
    - run SpeechBrain VAD to find speech regions
    - compute speaker embeddings per region
    - cluster regions into speakers via greedy cosine-threshold assignment
    """
    try:
        import torch
        import torch.nn.functional as F
        import torchaudio
    except ImportError as exc:
        raise RuntimeError(
            "speechbrain diarization backend selected but dependencies are not installed. "
            "Install with: pip install 'media-core[diarize-speechbrain]'"
        ) from exc

    try:
        from speechbrain.inference.VAD import VAD  # type: ignore
        from speechbrain.inference.speaker import SpeakerRecognition  # type: ignore
    except ImportError:
        # Older SpeechBrain versions expose these in `speechbrain.pretrained`.
        try:
            from speechbrain.pretrained import VAD, SpeakerRecognition  # type: ignore
        except ImportError as exc:  # pragma: no cover - exercised when speechbrain isn't installed
            raise RuntimeError(
                "speechbrain diarization backend selected but dependencies are not installed. "
                "Install with: pip install 'media-core[diarize-speechbrain]'"
            ) from exc

    def safe_slug(model_id: str) -> str:
        return model_id.replace("/", "_").replace(":", "_")

    base_cache_dir = Path(os.getenv("HF_HOME") or os.getenv("HUGGINGFACE_HUB_CACHE") or Path.home() / ".cache" / "reframe")
    sb_cache_dir = base_cache_dir / "speechbrain"
    vad_model_id = "speechbrain/vad-crdnn-libriparty"
    spk_model_id = config.model or "speechbrain/spkrec-ecapa-voxceleb"

    vad = VAD.from_hparams(source=vad_model_id, savedir=str(sb_cache_dir / safe_slug(vad_model_id)))
    spk = SpeakerRecognition.from_hparams(source=spk_model_id, savedir=str(sb_cache_dir / safe_slug(spk_model_id)))

    # VAD boundaries are a 1D tensor: [start0, end0, start1, end1, ...]
    boundaries = vad.get_speech_segments(str(audio_path))
    if boundaries is None:
        return []

    boundaries_list = boundaries.detach().cpu().tolist() if hasattr(boundaries, "detach") else list(boundaries)
    if not boundaries_list:
        return []

    waveform, sample_rate = torchaudio.load(str(audio_path))
    if waveform.ndim != 2:
        raise ValueError(f"Unexpected waveform shape {tuple(waveform.shape)}")
    if waveform.shape[0] > 1:
        waveform = waveform.mean(dim=0, keepdim=True)

    # Greedy clustering in embedding space.
    similarity_threshold = 0.65
    merge_gap_seconds = 0.10

    centroids: list[torch.Tensor] = []
    centroid_counts: list[int] = []
    assignments: list[int] = []
    speech_regions: list[tuple[float, float]] = []

    for i in range(0, len(boundaries_list), 2):
        try:
            start = float(boundaries_list[i])
            end = float(boundaries_list[i + 1])
        except (TypeError, ValueError, IndexError):
            continue

        if end <= start:
            continue
        if config.min_segment_duration and (end - start) < config.min_segment_duration:
            continue

        start_idx = max(0, int(start * sample_rate))
        end_idx = min(int(end * sample_rate), waveform.shape[1])
        if end_idx <= start_idx:
            continue

        segment_wav = waveform[:, start_idx:end_idx]
        emb = spk.encode_batch(segment_wav)
        if emb.ndim == 2:
            emb = emb[0]
        emb = F.normalize(emb.to(torch.float32).detach(), dim=0)

        best_idx = None
        best_sim = -1.0
        for idx, centroid in enumerate(centroids):
            sim = float(F.cosine_similarity(emb, centroid, dim=0).item())
            if sim > best_sim:
                best_sim = sim
                best_idx = idx

        if best_idx is None or best_sim < similarity_threshold:
            centroids.append(emb)
            centroid_counts.append(1)
            assignments.append(len(centroids) - 1)
        else:
            centroid_counts[best_idx] += 1
            # Online centroid update + re-normalize.
            updated = (centroids[best_idx] * (centroid_counts[best_idx] - 1) + emb) / float(centroid_counts[best_idx])
            centroids[best_idx] = F.normalize(updated, dim=0)
            assignments.append(best_idx)

        speech_regions.append((start, end))

    if not speech_regions:
        return []

    segments: list[SpeakerSegment] = []
    for (start, end), cluster_idx in zip(speech_regions, assignments):
        speaker = f"SPEAKER_{cluster_idx:02d}"
        if segments and segments[-1].speaker == speaker and start <= (segments[-1].end + merge_gap_seconds):
            segments[-1].end = max(segments[-1].end, end)
            continue
        segments.append(SpeakerSegment(start=start, end=end, speaker=speaker))

    if config.min_segment_duration:
        segments = [s for s in segments if (s.end - s.start) >= config.min_segment_duration]

    return segments


__all__ = [
    "DiarizationBackend",
    "DiarizationConfig",
    "SpeakerSegment",
    "assign_speakers_to_lines",
    "diarize_audio",
]
