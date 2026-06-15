"""Speaker diarization backends and helpers for the media-core pipeline.

Offline-first: the default NOOP backend returns no speaker labels. Optional
pyannote and SpeechBrain backends are imported lazily so the package works
without their heavy dependencies installed.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Iterable, List, Sequence

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


def assign_speakers_to_lines(
    lines: Sequence[SubtitleLine], segments: Iterable[SpeakerSegment]
) -> List[SubtitleLine]:
    """Attach `speaker` labels to subtitle lines based on overlap with segments."""
    segments_list = list(segments)
    if not segments_list:
        return [
            SubtitleLine(start=l.start, end=l.end, words=l.words, speaker=l.speaker)
            for l in lines  # noqa: E741
        ]

    out: List[SubtitleLine] = []
    for line in lines:
        best_speaker: str | None = None
        best_overlap = 0.0
        for seg in segments_list:
            overlap = max(0.0, min(line.end, seg.end) - max(line.start, seg.start))
            if overlap > best_overlap:
                best_overlap = overlap
                best_speaker = seg.speaker
        out.append(
            SubtitleLine(
                start=line.start, end=line.end, words=line.words, speaker=best_speaker
            )
        )
    return out


def _iter_pyannote_tracks(diarization: Any) -> Iterator[tuple[Any, Any, Any]]:
    """Yield tracks from either classic Annotation or newer DiarizeOutput shapes."""

    itertracks = getattr(diarization, "itertracks", None)
    if callable(itertracks):
        return itertracks(yield_label=True)

    for attr in ("speaker_diarization", "diarization", "annotation"):
        nested = getattr(diarization, attr, None)
        nested_itertracks = getattr(nested, "itertracks", None)
        if callable(nested_itertracks):
            return nested_itertracks(yield_label=True)

    to_annotation = getattr(diarization, "to_annotation", None)
    if callable(to_annotation):
        annotation = to_annotation()
        annotation_itertracks = getattr(annotation, "itertracks", None)
        if callable(annotation_itertracks):
            return annotation_itertracks(yield_label=True)

    raise RuntimeError(
        "Unsupported pyannote diarization output type "
        f"'{type(diarization).__name__}'. Expected itertracks()-compatible output."
    )


def _diarize_pyannote(audio_path: str | Path, config: DiarizationConfig) -> List[SpeakerSegment]:
    try:
        # pylint: disable-next=import-outside-toplevel
        from pyannote.audio import Pipeline  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "pyannote diarization backend selected but dependencies are not installed. "
            "Install with: pip install 'media-core[diarize-pyannote]'"
        ) from exc

    path = str(audio_path)
    try:
        if config.huggingface_token:
            # pyannote.audio switched from `use_auth_token=` to `token=` across versions.
            try:
                pipeline = Pipeline.from_pretrained(
                    config.model, token=config.huggingface_token
                )
            except TypeError:
                pipeline = Pipeline.from_pretrained(
                    config.model, use_auth_token=config.huggingface_token
                )
        else:
            pipeline = Pipeline.from_pretrained(config.model)
    except Exception as exc:
        hint = ""
        msg = str(exc)
        if "403" in msg or "gated" in msg.lower() or "restricted" in msg.lower():
            hint = (
                "\n\nHint: this model is gated on Hugging Face. Ensure you:\n"
                "- accepted the model terms / requested access (one-time)\n"
                "- created an HF token with read access\n"
                "- set HF_TOKEN (or HUGGINGFACE_TOKEN) in your environment\n"
            )
        raise RuntimeError(f"Failed to load pyannote pipeline '{config.model}'.{hint}") from exc
    diarization = pipeline(path)

    segments: List[SpeakerSegment] = []
    for turn, _, speaker in _iter_pyannote_tracks(diarization):
        start = float(turn.start)
        end = float(turn.end)
        if config.min_segment_duration and (end - start) < config.min_segment_duration:
            continue
        segments.append(SpeakerSegment(start=start, end=end, speaker=str(speaker)))
    return segments


def _install_hf_auth_token_compat() -> None:
    """Shim `huggingface_hub.hf_hub_download` to accept the legacy `use_auth_token=`.

    SpeechBrain still calls huggingface_hub APIs with the legacy `use_auth_token=`
    kwarg. Newer huggingface_hub versions removed it in favor of `token=`, so we
    shim compatibility here before importing SpeechBrain (so their internal
    downloads keep working).
    """
    try:
        # pylint: disable=import-outside-toplevel
        import inspect

        import huggingface_hub  # type: ignore
    except ImportError:
        return

    hf_download = getattr(huggingface_hub, "hf_hub_download", None)
    if hf_download is None:
        return

    try:
        params = inspect.signature(hf_download).parameters
    except (TypeError, ValueError):
        params = {}
    if "use_auth_token" in params:
        return

    original = hf_download

    def _hf_hub_download_compat(  # type: ignore[no-redef]
        *args, use_auth_token=None, token=None, **kwargs
    ):
        if token is None and use_auth_token is not None:
            token = use_auth_token
        return original(*args, token=token, **kwargs)

    huggingface_hub.hf_hub_download = _hf_hub_download_compat  # type: ignore[attr-defined]


def _import_speechbrain_classes() -> tuple[Any, Any]:
    """Return `(VAD, SpeakerRecognition)` classes across SpeechBrain versions."""
    try:
        # pylint: disable=import-outside-toplevel
        from speechbrain.inference.VAD import VAD  # type: ignore
        from speechbrain.inference.speaker import SpeakerRecognition  # type: ignore
    except ImportError:
        # Older SpeechBrain versions expose these in `speechbrain.pretrained`.
        try:
            # pylint: disable-next=import-outside-toplevel
            from speechbrain.pretrained import VAD, SpeakerRecognition  # type: ignore
        except ImportError as exc:  # pragma: no cover - speechbrain not installed
            raise RuntimeError(
                "speechbrain diarization backend selected but dependencies are not "
                "installed. Install with: pip install 'media-core[diarize-speechbrain]'"
            ) from exc
    return VAD, SpeakerRecognition


def _ensure_local_hf_snapshot(repo_id: str, sb_cache_dir: Path) -> Path:
    """Download `repo_id` into the SpeechBrain cache and return its local dir.

    SpeechBrain's `from_hparams()` tries to download `custom.py` from the model
    repo, but many official SpeechBrain repos don't include it. We pre-download
    the repo and create an empty `custom.py` locally so SpeechBrain can proceed
    without a 404.
    """
    local_dir = sb_cache_dir / repo_id.replace("/", "_").replace(":", "_")
    local_dir.mkdir(parents=True, exist_ok=True)

    if not (local_dir / "hyperparams.yaml").exists():
        try:
            # pylint: disable-next=import-outside-toplevel
            from huggingface_hub import snapshot_download  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "speechbrain diarization requires `huggingface_hub` for model downloads"
            ) from exc

        snapshot_download(
            repo_id=repo_id, local_dir=str(local_dir), local_dir_use_symlinks=False
        )

    custom_py = local_dir / "custom.py"
    if not custom_py.exists():
        custom_py.write_text(
            "# Auto-generated by Reframe (SpeechBrain models often don't ship "
            "custom.py)\n",
            encoding="utf-8",
        )

    return local_dir


def _load_mono_waveform(audio_path: str | Path, torch: Any, torchaudio: Any) -> tuple[Any, int]:
    """Load `audio_path` as a mono (channels=1) waveform tensor and sample rate."""
    try:
        waveform, sample_rate = torchaudio.load(str(audio_path))
    except Exception:  # pylint: disable=broad-exception-caught
        # torchaudio raises varied backend-specific errors; fall back for any.
        try:
            # pylint: disable-next=import-outside-toplevel
            import soundfile as sf  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "Failed to load audio via torchaudio, and `soundfile` is not "
                "installed. Install with: pip install soundfile"
            ) from exc

        audio, sample_rate = sf.read(str(audio_path), dtype="float32", always_2d=True)
        # soundfile returns (frames, channels); torchaudio expects (channels, frames).
        waveform = torch.from_numpy(audio.T)

    if waveform.ndim != 2:
        raise ValueError(f"Unexpected waveform shape {tuple(waveform.shape)}")
    if waveform.shape[0] > 1:
        waveform = waveform.mean(dim=0, keepdim=True)
    return waveform, sample_rate


def _assign_centroid(
    emb: Any,
    centroids: list,
    centroid_counts: list,
    similarity_threshold: float,
    functional: Any,
) -> int:
    """Assign `emb` to an existing centroid or create a new one; return its index."""
    best_idx = None
    best_sim = -1.0
    for idx, centroid in enumerate(centroids):
        sim = float(functional.cosine_similarity(emb, centroid, dim=0).item())
        if sim > best_sim:
            best_sim = sim
            best_idx = idx

    if best_idx is None or best_sim < similarity_threshold:
        centroids.append(emb)
        centroid_counts.append(1)
        return len(centroids) - 1

    centroid_counts[best_idx] += 1
    # Online centroid update + re-normalize.
    count = float(centroid_counts[best_idx])
    updated = (centroids[best_idx] * (centroid_counts[best_idx] - 1) + emb) / count
    centroids[best_idx] = functional.normalize(updated, dim=0)
    return best_idx


# pylint: disable-next=too-many-arguments,too-many-positional-arguments,too-many-locals
def _cluster_speech_regions(
    boundaries_list: list,
    waveform: Any,
    sample_rate: int,
    spk: Any,
    config: DiarizationConfig,
    torch: Any,
    functional: Any,
) -> tuple[list[tuple[float, float]], list[int]]:
    """Greedy clustering in embedding space over VAD speech regions."""
    similarity_threshold = 0.65

    centroids: list = []
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
        emb = functional.normalize(emb.to(torch.float32).detach(), dim=0)

        assignments.append(
            _assign_centroid(
                emb, centroids, centroid_counts, similarity_threshold, functional
            )
        )
        speech_regions.append((start, end))

    return speech_regions, assignments


def _build_speaker_segments(
    speech_regions: list[tuple[float, float]],
    assignments: list[int],
    config: DiarizationConfig,
) -> List[SpeakerSegment]:
    """Merge adjacent same-speaker regions into `SpeakerSegment`s."""
    merge_gap_seconds = 0.10

    segments: list[SpeakerSegment] = []
    for (start, end), cluster_idx in zip(speech_regions, assignments):
        speaker = f"SPEAKER_{cluster_idx:02d}"
        if (
            segments
            and segments[-1].speaker == speaker
            and start <= (segments[-1].end + merge_gap_seconds)
        ):
            segments[-1].end = max(segments[-1].end, end)
            continue
        segments.append(SpeakerSegment(start=start, end=end, speaker=speaker))

    if config.min_segment_duration:
        segments = [
            s for s in segments if (s.end - s.start) >= config.min_segment_duration
        ]

    return segments


# pylint: disable-next=too-many-locals
def _diarize_speechbrain(
    audio_path: str | Path, config: DiarizationConfig
) -> List[SpeakerSegment]:
    """Basic SpeechBrain diarization (token-free).

    This is a pragmatic fallback when pyannote models are unavailable:
    - run SpeechBrain VAD to find speech regions
    - compute speaker embeddings per region
    - cluster regions into speakers via greedy cosine-threshold assignment
    """
    try:
        _install_hf_auth_token_compat()

        # pylint: disable=import-outside-toplevel
        import torch
        import torchaudio
        from torch.nn import functional
    except ImportError as exc:
        raise RuntimeError(
            "speechbrain diarization backend selected but dependencies are not "
            "installed. Install with: pip install 'media-core[diarize-speechbrain]'"
        ) from exc

    vad_cls, spkrec_cls = _import_speechbrain_classes()

    base_cache_dir = Path(
        os.getenv("HF_HOME")
        or os.getenv("HUGGINGFACE_HUB_CACHE")
        or Path.home() / ".cache" / "reframe"
    )
    sb_cache_dir = base_cache_dir / "speechbrain"
    vad_model_id = "speechbrain/vad-crdnn-libriparty"
    spk_model_id = config.model or "speechbrain/spkrec-ecapa-voxceleb"

    vad_dir = _ensure_local_hf_snapshot(vad_model_id, sb_cache_dir)
    spk_dir = _ensure_local_hf_snapshot(spk_model_id, sb_cache_dir)

    # pylint: disable-next=import-outside-toplevel,import-error
    from speechbrain.utils.fetching import LocalStrategy  # type: ignore

    vad = vad_cls.from_hparams(
        source=str(vad_dir), savedir=str(vad_dir), local_strategy=LocalStrategy.NO_LINK
    )
    spk = spkrec_cls.from_hparams(
        source=str(spk_dir), savedir=str(spk_dir), local_strategy=LocalStrategy.NO_LINK
    )

    # VAD boundaries are a 1D tensor: [start0, end0, start1, end1, ...]
    boundaries = vad.get_speech_segments(str(audio_path))
    if boundaries is None:
        return []

    boundaries_list = (
        boundaries.detach().cpu().tolist()
        if hasattr(boundaries, "detach")
        else list(boundaries)
    )
    if not boundaries_list:
        return []

    waveform, sample_rate = _load_mono_waveform(audio_path, torch, torchaudio)

    speech_regions, assignments = _cluster_speech_regions(
        boundaries_list, waveform, sample_rate, spk, config, torch, functional
    )
    if not speech_regions:
        return []

    return _build_speaker_segments(speech_regions, assignments, config)


__all__ = [
    "DiarizationBackend",
    "DiarizationConfig",
    "SpeakerSegment",
    "assign_speakers_to_lines",
    "diarize_audio",
]
