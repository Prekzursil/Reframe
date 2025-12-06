from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import (
    TranscriptionBackend,
    TranscriptionConfig,
    transcribe_faster_whisper,
    transcribe_noop,
    transcribe_openai_file,
    transcribe_whisper_cpp,
    transcribe_whisper_timestamped,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Transcribe an audio/video file.")
    parser.add_argument("input", help="Path to the media file.")
    parser.add_argument("--language", help="ISO language code (optional).")
    parser.add_argument("--backend", default=TranscriptionBackend.NOOP.value, help="Backend name (openai_whisper, faster_whisper, whisper_cpp, whisper_timestamped, noop).")
    parser.add_argument("--model", default="whisper-1", help="Model name.")
    parser.add_argument("--device", help="Device hint (e.g., cpu, cuda).")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        backend = TranscriptionBackend(args.backend)
    except ValueError:
        print(f"Unsupported backend: {args.backend}", file=sys.stderr)
        return 1

    config = TranscriptionConfig(backend=backend, model=args.model, language=args.language, device=args.device)
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Input not found: {input_path}", file=sys.stderr)
        return 1

    try:
        if backend == TranscriptionBackend.OPENAI_WHISPER:
            result = transcribe_openai_file(str(input_path), config)
        elif backend == TranscriptionBackend.FASTER_WHISPER:
            result = transcribe_faster_whisper(str(input_path), config)
        elif backend == TranscriptionBackend.WHISPER_CPP:
            result = transcribe_whisper_cpp(str(input_path), config)
        elif backend in (TranscriptionBackend.WHISPER_TIMESTAMPED, TranscriptionBackend.WHISPERX):
            result = transcribe_whisper_timestamped(str(input_path), config)
        else:
            result = transcribe_noop(str(input_path), config)
    except Exception as exc:
        print(f"Transcription failed: {exc}", file=sys.stderr)
        print("Tip: use backend 'noop' for an offline smoke test.", file=sys.stderr)
        return 1

    print(json.dumps(result.model_dump(), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
