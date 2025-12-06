from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Iterable, List, Optional


def _ensure_binary(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise FileNotFoundError(f"{name} not found in PATH")
    return path


def _run(cmd: List[str], runner=None) -> subprocess.CompletedProcess:
    runner = runner or subprocess.run
    return runner(cmd, check=True, capture_output=True)


def probe_media(path: str | Path, runner=None) -> dict:
    ffprobe = _ensure_binary("ffprobe")
    media_path = Path(path)
    if not media_path.is_file():
        raise FileNotFoundError(media_path)
    cmd = [
        ffprobe,
        "-v",
        "error",
        "-show_entries",
        "format=duration:stream=width,height,codec_name",
        "-of",
        "default=noprint_wrappers=1",
        str(media_path),
    ]
    _run(cmd, runner=runner)
    return {"path": str(media_path)}


def extract_audio(video_path: str | Path, audio_path: str | Path, runner=None) -> None:
    ffmpeg = _ensure_binary("ffmpeg")
    cmd = [ffmpeg, "-y", "-i", str(video_path), "-vn", "-acodec", "copy", str(audio_path)]
    _run(cmd, runner=runner)


def cut_clip(video_path: str | Path, start: float, end: float, output_path: str | Path, runner=None) -> None:
    ffmpeg = _ensure_binary("ffmpeg")
    duration = max(0, end - start)
    cmd = [
        ffmpeg,
        "-y",
        "-ss",
        str(start),
        "-i",
        str(video_path),
        "-t",
        str(duration),
        "-c",
        "copy",
        str(output_path),
    ]
    _run(cmd, runner=runner)


def reframe(video_path: str | Path, output_path: str | Path, aspect_ratio: str, strategy: str = "crop", runner=None) -> None:
    ffmpeg = _ensure_binary("ffmpeg")
    if strategy == "crop":
        filter_chain = f"scale=-1:ih, crop=iw:iw/{aspect_ratio.replace(':', '/')}"
    else:
        filter_chain = (
            f"scale=-1:ih, pad=ceil(iw*{aspect_ratio.replace(':', '/')}/2)*2:"
            f"ceil(ih/{aspect_ratio.replace(':', '/')}/2)*2:(ow-iw)/2:(oh-ih)/2"
        )
    cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(video_path),
        "-vf",
        filter_chain,
        str(output_path),
    ]
    _run(cmd, runner=runner)


def merge_video_audio(
    video_path: str | Path,
    audio_path: str | Path,
    output_path: str | Path,
    offset: float = 0.0,
    ducking: Optional[float] = None,
    normalize: bool = False,
    runner=None,
) -> None:
    ffmpeg = _ensure_binary("ffmpeg")
    filter_complex: List[str] = []
    if ducking:
        filter_complex.append(f"[1:a]volume={ducking}[ducked]")
        amix_inputs = "[0:a][ducked]"
    else:
        amix_inputs = "[0:a][1:a]"
    if normalize:
        filter_complex.append("loudnorm")
    filter_str = ",".join(filter_complex) if filter_complex else None
    cmd = [ffmpeg, "-y", "-i", str(video_path), "-itsoffset", str(offset), "-i", str(audio_path)]
    if filter_str:
        cmd += ["-filter_complex", filter_str]
    cmd += ["-c:v", "copy", "-c:a", "aac", "-shortest", str(output_path)]
    _run(cmd, runner=runner)


def burn_subtitles(
    video_path: str | Path,
    subs_path: str | Path,
    output_path: str | Path,
    extra_filters: Optional[Iterable[str]] = None,
    runner=None,
) -> None:
    ffmpeg = _ensure_binary("ffmpeg")
    filters = [f"subtitles={subs_path}"]
    if extra_filters:
        filters.extend(extra_filters)
    filter_chain = ",".join(filters)
    cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(video_path),
        "-vf",
        filter_chain,
        str(output_path),
    ]
    _run(cmd, runner=runner)
