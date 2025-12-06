"""CLI entrypoint for quick transcription checks.

Note: Backend execution is not yet wired. This serves as a placeholder to show
the expected interface and to verify that the package imports cleanly.
"""

from __future__ import annotations

import argparse
import sys

from .config import TranscriptionConfig


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Transcribe an audio/video file.")
    parser.add_argument("input", help="Path to the media file.")
    parser.add_argument("--language", help="ISO language code (optional).")
    parser.add_argument("--backend", default="openai_whisper", help="Backend name.")
    parser.add_argument("--model", default="whisper-1", help="Model name.")
    parser.add_argument("--device", help="Device hint (e.g., cpu, cuda).")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = TranscriptionConfig(
        backend=args.backend,
        model=args.model,
        language=args.language,
        device=args.device,
    )
    print(
        "Transcription CLI placeholder. No backend wired yet.\n"
        f"Input: {args.input}\n"
        f"Config: {config.model_dump_json(indent=2)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
