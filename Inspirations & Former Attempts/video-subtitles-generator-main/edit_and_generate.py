#!/usr/bin/env python3
"""
Two-step workflow: transcribe first, edit, then generate video.
This allows you to manually correct transcription errors before video generation.
"""

import argparse
import json
import sys
from pathlib import Path

from generate_subtitles import SubtitleGenerator


def step1_transcribe(
    video_path: str, model: str = "large", language: str = "nl"
) -> tuple:
    """Step 1: Extract audio and transcribe to JSON."""
    video_path = Path(video_path)
    audio_path = video_path.parent / f"{video_path.stem}_audio.mp3"
    json_path = video_path.parent / f"{video_path.stem}_timestamps.json"

    print("=" * 60)
    print("STEP 1: TRANSCRIBING VIDEO")
    print("=" * 60)

    generator = SubtitleGenerator()

    # Check if files already exist
    audio_exists = audio_path.exists()
    json_exists = json_path.exists()

    if audio_exists and json_exists:
        print("\n⚡ EXISTING FILES FOUND!")
        print(f"   Audio: {audio_path}")
        print(f"   JSON: {json_path}")
        print("\n   Skipping transcription (files already exist)")
        print("   To re-transcribe, delete these files first.\n")
    elif audio_exists and not json_exists:
        print(f"\n⚡ Audio file found: {audio_path}")
        print("   Skipping audio extraction\n")
        # Transcribe
        result = generator.transcribe_audio(
            str(audio_path), model_name=model, language=language
        )
        # Save timestamps
        generator.save_word_timestamps(result, str(json_path))
    else:
        # Extract audio
        if not audio_exists:
            generator.extract_audio(str(video_path), str(audio_path))

        # Transcribe
        result = generator.transcribe_audio(
            str(audio_path), model_name=model, language=language
        )

        # Save timestamps
        generator.save_word_timestamps(result, str(json_path))

    print("\n" + "=" * 60)
    print("TRANSCRIPTION COMPLETE!")
    print("=" * 60)
    print(f"\nTimestamps saved to: {json_path}")
    print(f"Audio saved to: {audio_path}")
    print("\n" + "=" * 60)
    print("NEXT STEPS:")
    print("=" * 60)
    print("\n📝 STEP 2A: EDIT THE TRANSCRIPT (OPTIONEEL)")
    print("-" * 60)
    print("Open het JSON bestand in je text editor:")
    print(f"   {json_path}")
    print("\nWat je kan aanpassen:")
    print("  - Spelfouten corrigeren")
    print("  - Namen/bedrijfsnamen aanpassen")
    print("  - Hoofdletters corrigeren")
    print("\nVoorbeeld JSON structuur:")
    print('  {"word": " Hallo", "start": 0.5, "end": 0.8}')
    print("\n💡 TIP: Maak eerst een backup:")
    print(f"   cp '{json_path}' '{json_path}.backup'")
    print("\n" + "-" * 60)
    print("\n🎬 STEP 2B: GENEREER VIDEO")
    print("-" * 60)
    print("Als je klaar bent met bewerken (of direct door wilt):")
    print(f"\n   python edit_and_generate.py --step2 '{json_path}' '{audio_path}'")
    print("\n" + "=" * 60)

    # Ask if user wants to see the transcript
    try:
        response = (
            input("\n❓ Wil je de transcript nu bekijken? (j/n): ").strip().lower()
        )
        if response in ["j", "y", "yes", "ja"]:
            show_transcript_preview(str(json_path), max_words=100)
            print("\n💡 Je kunt het JSON bestand nu bewerken in je editor")
            input("\n   Druk op ENTER als je klaar bent om de video te genereren...")
            return step2_generate(str(json_path), str(audio_path))
    except (KeyboardInterrupt, EOFError):
        print("\n")

    return str(json_path), str(audio_path)


def step2_generate(
    json_path: str, audio_path: str, output_path: str = None, video_path: str = None
) -> str:
    """Step 2: Load edited JSON and generate video."""
    json_path = Path(json_path)
    audio_path = Path(audio_path)

    if not output_path:
        output_path = (
            json_path.parent
            / f"{json_path.stem.replace('_timestamps', '')}_subtitled.mp4"
        )
    else:
        output_path = Path(output_path)

    print("=" * 60)
    print("STEP 2: GENERATING VIDEO")
    print("=" * 60)
    print(f"Loading: {json_path}")
    print(f"Audio: {audio_path}")
    print(f"Output: {output_path}")
    print("=" * 60)

    generator = SubtitleGenerator()

    # If video path is provided or can be inferred, detect resolution
    if video_path is None:
        # Try to infer video path from json_path
        potential_video = (
            json_path.parent / f"{json_path.stem.replace('_timestamps', '')}.mov"
        )
        if potential_video.exists():
            video_path = str(potential_video)
        else:
            # Try .mp4 extension
            potential_video = (
                json_path.parent / f"{json_path.stem.replace('_timestamps', '')}.mp4"
            )
            if potential_video.exists():
                video_path = str(potential_video)

    # Detect video resolution if video exists
    if video_path:
        print(f"Original video: {video_path}")
        width, height = generator.get_video_resolution(video_path)
        generator.bg_width = width
        generator.bg_height = height

        # Adjust fontsize based on video dimensions
        base_dimension = min(width, height)
        generator.fontsize = int(base_dimension * 0.05)  # 5% of smaller dimension
        print(f"Adjusted font size to {generator.fontsize} for {width}x{height} video")

    # Load timestamps
    word_timestamps = generator.load_word_timestamps(str(json_path))

    # Split into lines
    print("\nOrganizing subtitles...")
    subtitles = generator.split_text_into_lines(word_timestamps)

    print(f"Created {len(subtitles)} subtitle segments")

    # Generate video with original video as background
    generator.generate_video(subtitles, str(audio_path), str(output_path), video_path)

    print("\n" + "=" * 60)
    print("VIDEO GENERATION COMPLETE!")
    print("=" * 60)
    print(f"\nOutput: {output_path}")
    print("=" * 60)

    return str(output_path)


def show_transcript_preview(json_path: str, max_words: int = 50):
    """Show a preview of the transcript."""
    with open(json_path, "r", encoding="utf-8") as f:
        timestamps = json.load(f)

    print("\n" + "=" * 60)
    print("TRANSCRIPT PREVIEW (first {} words)".format(max_words))
    print("=" * 60)

    words = [item["word"] for item in timestamps[:max_words]]
    text = " ".join(words)

    # Wrap text at 60 characters
    lines = []
    current_line = ""
    for word in text.split():
        if len(current_line) + len(word) + 1 <= 60:
            current_line += word + " "
        else:
            lines.append(current_line.strip())
            current_line = word + " "
    if current_line:
        lines.append(current_line.strip())

    for line in lines:
        print(line)

    print(f"\nTotal words: {len(timestamps)}")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="Two-step workflow for editing transcripts before video generation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Step 1: Transcribe video
  python edit_and_generate.py video.mov

  # Step 1 with specific model
  python edit_and_generate.py video.mov --model medium

  # Preview the transcript
  python edit_and_generate.py --preview video_timestamps.json

  # Step 2: Generate video after editing JSON
  python edit_and_generate.py --step2 video_timestamps.json video_audio.mp3

  # Step 2 with custom output
  python edit_and_generate.py --step2 video_timestamps.json video_audio.mp3 -o final.mp4
        """,
    )

    parser.add_argument(
        "input",
        nargs="?",
        help="Video file (step 1) or JSON file (step 2 with --step2)",
    )
    parser.add_argument(
        "audio",
        nargs="?",
        help="Audio file (required for step 2 with --step2)",
    )
    parser.add_argument(
        "-m",
        "--model",
        default="large",
        choices=["tiny", "base", "small", "medium", "large"],
        help="Whisper model for step 1 (default: large)",
    )
    parser.add_argument(
        "-l",
        "--language",
        default="nl",
        help="Language code for transcription (default: nl for Dutch)",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Output video path for step 2",
    )
    parser.add_argument(
        "--step2",
        action="store_true",
        help="Run step 2: generate video from edited JSON",
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Preview the transcript from JSON file",
    )
    parser.add_argument(
        "--edit",
        action="store_true",
        help="Open JSON file in default text editor",
    )

    args = parser.parse_args()

    if args.edit:
        if not args.input or not args.input.endswith(".json"):
            print("Error: --edit requires a JSON file")
            sys.exit(1)

        import platform
        import subprocess

        json_path = args.input
        print(f"Opening {json_path} in editor...")

        # Open in default editor based on OS
        if platform.system() == "Darwin":  # macOS
            subprocess.run(["open", "-t", json_path])
        elif platform.system() == "Windows":
            subprocess.run(["notepad", json_path])
        else:  # Linux
            editors = ["gedit", "nano", "vi"]
            for editor in editors:
                try:
                    subprocess.run([editor, json_path])
                    break
                except FileNotFoundError:
                    continue

        print("\n💡 After editing, run step 2 to generate the video:")
        # Extract audio path
        audio_path = (
            Path(json_path).parent
            / f"{Path(json_path).stem.replace('_timestamps', '')}_audio.mp3"
        )
        print(f"   python edit_and_generate.py --step2 '{json_path}' '{audio_path}'")
        return

    if args.preview:
        if not args.input or not args.input.endswith(".json"):
            print("Error: --preview requires a JSON file")
            sys.exit(1)
        show_transcript_preview(args.input)
        return

    if args.step2:
        # Step 2: Generate video
        if not args.input or not args.audio:
            print("Error: Step 2 requires both JSON file and audio file")
            print("Usage: python edit_and_generate.py --step2 <json_file> <audio_file>")
            sys.exit(1)

        step2_generate(args.input, args.audio, args.output)

    else:
        # Step 1: Transcribe
        if not args.input:
            parser.print_help()
            sys.exit(1)

        json_path, audio_path = step1_transcribe(args.input, args.model, args.language)

        # Show preview
        show_transcript_preview(json_path, max_words=100)


if __name__ == "__main__":
    main()
