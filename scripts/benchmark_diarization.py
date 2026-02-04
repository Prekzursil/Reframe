#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import resource
import shutil
import subprocess
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory


def _ensure_repo_paths() -> Path:
    repo_root = Path(__file__).resolve().parents[1]
    media_core_src = repo_root / "packages" / "media-core" / "src"
    if media_core_src.is_dir() and str(media_core_src) not in sys.path:
        sys.path.insert(0, str(media_core_src))

    tools_bin = repo_root / ".tools" / "bin"
    if tools_bin.is_dir():
        os.environ["PATH"] = f"{tools_bin}{os.pathsep}{os.environ.get('PATH', '')}"
    return repo_root


def _extract_wav_16k_mono(input_path: Path, output_path: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise FileNotFoundError("ffmpeg not found in PATH (run `make tools-ffmpeg` or install system ffmpeg)")
    cmd = [
        ffmpeg,
        "-y",
        "-v",
        "error",
        "-i",
        str(input_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
        str(output_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def _get_peak_rss_mb() -> float:
    # On Linux, ru_maxrss is in KiB.
    return float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) / 1024.0


def main(argv: list[str]) -> int:
    repo_root = _ensure_repo_paths()

    parser = argparse.ArgumentParser(description="Benchmark diarization wall time and peak RSS.")
    parser.add_argument("input", help="Path to an audio/video file.")
    parser.add_argument(
        "--backend",
        default="pyannote",
        choices=["pyannote", "speechbrain"],
        help="Diarization backend to benchmark (default: %(default)s)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Model id. For pyannote: pipeline id (e.g. pyannote/speaker-diarization-3.1). "
        "For speechbrain: speaker embedding model id (e.g. speechbrain/spkrec-ecapa-voxceleb).",
    )
    parser.add_argument("--min-segment-duration", type=float, default=0.0, help="Drop segments shorter than this (seconds).")
    parser.add_argument("--hf-token", default="", help="Hugging Face token (or set HF_TOKEN/HUGGINGFACE_TOKEN env var).")
    parser.add_argument("--warmup", action="store_true", help="Run one warmup pass (downloads/loads model) before measuring.")
    parser.add_argument("--runs", type=int, default=1, help="Number of measured runs (default: %(default)s)")
    parser.add_argument(
        "--format",
        default="text",
        choices=["text", "md"],
        help="Output format (default: %(default)s)",
    )
    args = parser.parse_args(argv)

    input_path = Path(args.input)
    if not input_path.is_file():
        raise FileNotFoundError(input_path)

    backend_raw = str(args.backend or "pyannote").strip().lower()
    token = None
    if backend_raw == "pyannote":
        token = (args.hf_token or os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_TOKEN") or "").strip() or None
        if not token:
            dotenv_path = repo_root / ".env"
            if dotenv_path.is_file():
                for line in dotenv_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                    stripped = line.strip()
                    if not stripped or stripped.startswith("#") or "=" not in stripped:
                        continue
                    key, value = stripped.split("=", 1)
                    key = key.strip()
                    if key not in {"HF_TOKEN", "HUGGINGFACE_TOKEN"}:
                        continue
                    token = value.strip().strip("\"'") or None
                    if token:
                        break

    from media_core.diarize import DiarizationBackend, DiarizationConfig, diarize_audio

    backend = DiarizationBackend(backend_raw)
    model = args.model
    if not model:
        model = "pyannote/speaker-diarization-3.1" if backend == DiarizationBackend.PYANNOTE else "speechbrain/spkrec-ecapa-voxceleb"

    config = DiarizationConfig(
        backend=backend,
        model=model,
        huggingface_token=token,
        min_segment_duration=max(0.0, float(args.min_segment_duration or 0.0)),
    )

    with TemporaryDirectory(prefix="reframe-diarize-bench-") as tmp:
        wav_path = Path(tmp) / "input.wav"
        _extract_wav_16k_mono(input_path, wav_path)

        if args.warmup:
            print("Warmup run (not timed)...")
            _ = diarize_audio(wav_path, config)

        durations: list[float] = []
        segments_count: int | None = None
        run_lines: list[str] = []

        for i in range(max(1, int(args.runs))):
            start = time.perf_counter()
            segments = diarize_audio(wav_path, config)
            durations.append(time.perf_counter() - start)
            segments_count = len(segments)
            run_line = f"run={i + 1} duration_s={durations[-1]:.3f} segments={segments_count}"
            run_lines.append(run_line)
            if args.format == "text":
                print(run_line)

    peak_mb = _get_peak_rss_mb()
    duration_min = min(durations)
    duration_max = max(durations)
    duration_avg = sum(durations) / len(durations)

    if args.format == "md":
        print("")
        print("### Diarization benchmark")
        print("")
        print(f"- backend: `{backend.value}`")
        print(f"- model: `{model}`")
        print(f"- runs: `{len(durations)}` (warmup: `{bool(args.warmup)}`)")
        print(f"- duration_s_avg: `{duration_avg:.3f}` (min `{duration_min:.3f}`, max `{duration_max:.3f}`)")
        if segments_count is not None:
            print(f"- segments_last_run: `{segments_count}`")
        print(f"- peak_rss_mb: `{peak_mb:.1f}`")
        if run_lines:
            print("")
            print("```text")
            for line in run_lines:
                print(line)
            print("```")
    else:
        print("")
        print("Summary")
        print(f"backend={backend.value}")
        print(f"model={model}")
        print(f"runs={len(durations)} warmup={bool(args.warmup)}")
        print(f"duration_s_min={duration_min:.3f} duration_s_max={duration_max:.3f} duration_s_avg={duration_avg:.3f}")
        if segments_count is not None:
            print(f"segments_last_run={segments_count}")
        print(f"peak_rss_mb={peak_mb:.1f}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
