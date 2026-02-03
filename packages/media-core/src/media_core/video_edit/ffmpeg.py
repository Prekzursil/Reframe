from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Iterable, List, Optional


logger = logging.getLogger(__name__)


def _ensure_binary(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise FileNotFoundError(f"{name} not found in PATH")
    return path


def _run(cmd: List[str], runner=None) -> subprocess.CompletedProcess:
    runner = runner or subprocess.run
    try:
        return runner(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, (bytes, bytearray)) else str(exc.stderr or "")
        stdout = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, (bytes, bytearray)) else str(exc.stdout or "")
        logger.error(
            "ffmpeg command failed",
            extra={
                "cmd": cmd,
                "returncode": exc.returncode,
                "stderr": stderr[-4000:],
                "stdout": stdout[-4000:],
            },
        )
        raise


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
        "format=duration:bit_rate",
        "-show_entries",
        "stream=index,codec_name,width,height,codec_type",
        "-of",
        "json",
        str(media_path),
    ]
    completed = _run(cmd, runner=runner)
    info = json.loads(completed.stdout.decode() if completed.stdout else "{}")
    fmt = info.get("format", {}) or {}
    streams = info.get("streams", []) or []
    video_stream = next((s for s in streams if s.get("codec_type") == "video"), {})
    audio_streams = [s for s in streams if s.get("codec_type") == "audio"]
    return {
        "path": str(media_path),
        "duration": float(fmt.get("duration")) if fmt.get("duration") else None,
        "bitrate": int(fmt.get("bit_rate")) if fmt.get("bit_rate") else None,
        "video": {
            "codec": video_stream.get("codec_name"),
            "width": video_stream.get("width"),
            "height": video_stream.get("height"),
        },
        "audio_codecs": [a.get("codec_name") for a in audio_streams if a.get("codec_name")],
    }


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
    elif strategy == "blur_bg":
        ratio = aspect_ratio.replace(":", "/")
        filter_chain = (
            f"split=2[main][bg];"
            f"[bg]scale=-1:ih,boxblur=20:1[bgblur];"
            f"[main]scale='if(gt(a,{ratio}),iw/{ratio},{ratio}*ih)':'if(gt(a,{ratio}),ih,iw/{ratio})':force_original_aspect_ratio=decrease[fg];"
            f"[bgblur][fg]overlay=(W-w)/2:(H-h)/2"
        )
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
