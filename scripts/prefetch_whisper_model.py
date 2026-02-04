#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Pre-download a faster-whisper model into the local HF cache.")
    parser.add_argument(
        "--model",
        default="whisper-large-v3",
        help="Model name. Accepts aliases like whisper-large-v3 (default: %(default)s).",
    )
    parser.add_argument("--device", default="", help="Optional device hint for faster-whisper (cpu|cuda).")
    args = parser.parse_args(argv)

    try:
        from media_core.transcribe.backends.faster_whisper import _normalize_model_name  # type: ignore
    except Exception:
        _normalize_model_name = lambda x: x  # noqa: E731

    model_name = _normalize_model_name(args.model)

    try:
        from faster_whisper import WhisperModel  # type: ignore
    except ImportError:
        print("ERROR: faster-whisper is not installed.", file=sys.stderr)
        print("Tip: install media-core extras: pip install 'packages/media-core[transcribe-faster-whisper]'", file=sys.stderr)
        return 2

    kwargs = {}
    if args.device:
        kwargs["device"] = args.device

    print(f"Prefetching faster-whisper model: {model_name}")
    _ = WhisperModel(model_name, **kwargs)
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

