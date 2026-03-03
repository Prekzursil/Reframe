#!/usr/bin/env python3
from __future__ import annotations

import argparse
import math
import struct
import wave
from pathlib import Path


def _sample_value(t: float) -> float:
    # Alternate short tone and silence windows to emulate speech-ish activity.
    bucket = int(t) % 3
    if bucket == 2:
        return 0.0
    carrier = math.sin(2.0 * math.pi * 220.0 * t)
    mod = 0.5 * math.sin(2.0 * math.pi * 3.0 * t)
    return 0.35 * carrier * (1.0 + mod)


def _safe_output_path(raw: str, *, base: Path) -> Path:
    candidate = Path((raw or "").strip()).expanduser()
    if not candidate.is_absolute():
        candidate = base / candidate
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(base.resolve())
    except ValueError as exc:
        raise ValueError(f"Output path escapes workspace root: {candidate}") from exc
    return resolved


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a deterministic mono WAV sample for benchmark workflows.")
    parser.add_argument("--out", default="samples/sample.wav")
    parser.add_argument("--duration", type=float, default=12.0)
    parser.add_argument("--sample-rate", type=int, default=16000)
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    out_path = _safe_output_path(args.out, base=repo_root)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    total_frames = int(args.duration * args.sample_rate)

    with wave.open(str(out_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(args.sample_rate)
        for idx in range(total_frames):
            t = idx / float(args.sample_rate)
            amp = _sample_value(t)
            sample = max(-32768, min(32767, int(amp * 32767.0)))
            wf.writeframesraw(struct.pack("<h", sample))

    print(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
