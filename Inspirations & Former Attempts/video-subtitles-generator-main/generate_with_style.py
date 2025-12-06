#!/usr/bin/env python3
"""
Generate subtitles with customizable style (color, stroke, shadow, font).
Bold white text with black stroke and word-by-word highlighting.
"""

import argparse
import json
import platform
import subprocess
import sys
from pathlib import Path

from generate_subtitles import SubtitleGenerator


def show_transcript_preview(json_path: str, max_words: int = 50):
    """Show a preview of the transcript."""
    with open(json_path, "r", encoding="utf-8") as f:
        timestamps = json.load(f)

    print("\n" + "=" * 60)
    print(f"TRANSCRIPT PREVIEW (eerste {max_words} woorden)")
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

    print(f"\nTotaal woorden: {len(timestamps)}")
    print("=" * 60)


def open_in_editor(json_path: str):
    """Open JSON file in default text editor."""
    print(f"\nOpenen van {json_path} in editor...")

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


def main():
    parser = argparse.ArgumentParser(
        description="Generate subtitles with customizable highlight color and style"
    )
    parser.add_argument("input", type=str, help="Input video file path")
    parser.add_argument(
        "-o",
        "--output",
        type=str,
        help="Output video file path (default: input_styled.mp4)",
    )
    parser.add_argument(
        "--color",
        type=str,
        default="orange",
        help="Highlight color (orange, cyan, yellow, red, lime, etc.) [default: orange]",
    )
    parser.add_argument(
        "--stroke-width",
        type=int,
        default=3,
        help="Inner stroke width in pixels [default: 3]",
    )
    parser.add_argument(
        "--outline-width",
        type=int,
        default=4,
        help="Outer outline width in pixels (8-directional border) [default: 4]",
    )
    parser.add_argument(
        "--no-outline",
        action="store_true",
        help="Disable outline border (enabled by default)",
    )
    parser.add_argument(
        "--fontsize",
        type=int,
        default=None,
        help="Font size (auto-adjusted by default based on video resolution)",
    )
    parser.add_argument(
        "--font", type=str, default=None, help="Path to custom font file"
    )
    parser.add_argument(
        "--no-shadow",
        action="store_true",
        help="Disable drop shadow (enabled by default)",
    )
    parser.add_argument(
        "--shadow-offset",
        type=int,
        default=6,
        help="Shadow offset in pixels [default: 6]",
    )
    parser.add_argument(
        "--max-words",
        type=int,
        default=4,
        help="Maximum words per subtitle line [default: 4]",
    )
    parser.add_argument(
        "--max-duration",
        type=float,
        default=3.0,
        help="Maximum duration per subtitle line in seconds [default: 3.0]",
    )

    args = parser.parse_args()

    # Validate input file
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: Input file '{args.input}' does not exist")
        sys.exit(1)

    # Generate output filename
    if args.output:
        output_path = Path(args.output)
    else:
        output_path = input_path.parent / f"{input_path.stem}_styled.mp4"

    print("=" * 60)
    print("Generating Subtitles with Custom Style")
    print("=" * 60)
    print(f"Input:           {input_path}")
    print(f"Output:          {output_path}")
    print(f"Highlight Color: {args.color}")
    print(f"Stroke Width:    {args.stroke_width}px (inner)")
    print(
        f"Outline:         {'Enabled' if not args.no_outline else 'Disabled'} ({args.outline_width}px)"
    )
    print(
        f"Shadow:          {'Enabled' if not args.no_shadow else 'Disabled'} ({args.shadow_offset}px offset)"
    )
    print(f"Max Words:       {args.max_words}")
    print("=" * 60)

    # Initialize generator with custom style settings
    generator_kwargs = {
        "max_words": args.max_words,
        "max_duration": args.max_duration,
        "max_gap": 1.5,
        "color": "white",
        "highlight_color": args.color,
        "stroke_color": "black",
        "stroke_width": args.stroke_width,
        "shadow": not args.no_shadow,
        "shadow_offset": args.shadow_offset,
        "outline": not args.no_outline,
        "outline_width": args.outline_width,
    }

    # Add optional parameters if specified
    if args.fontsize:
        generator_kwargs["fontsize"] = args.fontsize
    if args.font:
        generator_kwargs["font"] = args.font

    generator = SubtitleGenerator(**generator_kwargs)

    # Setup intermediate file paths
    audio_path = input_path.parent / f"{input_path.stem}_audio.mp3"
    json_path = input_path.parent / f"{input_path.stem}_timestamps.json"

    # Process the video with transcript editing pause
    try:
        # Step 0: Detect video resolution
        width, height = generator.get_video_resolution(str(input_path))
        generator.bg_width = width
        generator.bg_height = height

        # Adjust fontsize based on video dimensions
        base_dimension = min(width, height)
        generator.fontsize = int(base_dimension * 0.09)  # 9% of smaller dimension
        print(f"Adjusted font size to {generator.fontsize} for {width}x{height} video")

        # Check if timestamps already exist
        skip_transcription = json_path.exists()

        if skip_transcription:
            print(f"\n✓ Found existing timestamps file: {json_path}")
            print("   Skipping transcription and reusing existing timestamps...")

            # Make sure audio file exists
            if not audio_path.exists():
                print("   Audio file not found, extracting audio...")
                generator.extract_audio(str(input_path), str(audio_path))
        else:
            print("\nNo existing timestamps found, transcribing audio...")

            # Step 1: Extract audio
            generator.extract_audio(str(input_path), str(audio_path))

            # Step 2: Transcribe with Whisper
            result = generator.transcribe_audio(
                str(audio_path), model_name="large", language="nl"
            )

            # Step 3: Save word timestamps
            generator.save_word_timestamps(result, str(json_path))

            print("\n" + "=" * 60)
            print("TRANSCRIPTIE VOLTOOID!")
            print("=" * 60)
            print(f"Timestamps opgeslagen: {json_path}")
            print(f"Audio opgeslagen:      {audio_path}")
            print("=" * 60)

        # ALWAYS show preview and ask to edit
        print("\n")
        show_transcript_preview(str(json_path), max_words=100)

        print("\n" + "=" * 60)
        print("TRANSCRIPT BEWERKEN (OPTIONEEL)")
        print("=" * 60)
        print("Je kunt nu het transcript bewerken om:")
        print("  - Spelfouten te corrigeren")
        print("  - Namen/bedrijven aan te passen")
        print("  - Hoofdletters te verbeteren")
        print("\n" + "-" * 60)

        # Ask if user wants to edit
        try:
            response = (
                input("❓ Wil je het transcript bewerken? (j/n): ").strip().lower()
            )
            if response in ["j", "y", "yes", "ja"]:
                open_in_editor(str(json_path))
                print("\n💡 Bewerk het bestand en sla het op in je editor")
                input("   Druk op ENTER als je klaar bent om de video te genereren...")
        except (KeyboardInterrupt, EOFError):
            print("\n⏭️  Overslaan, direct naar video generatie...")

        # Step 4: Load and split into lines
        print("\n" + "=" * 60)
        print("VIDEO GENEREREN")
        print("=" * 60)
        word_timestamps = generator.load_word_timestamps(str(json_path))
        subtitles = generator.split_text_into_lines(word_timestamps)

        # Step 5: Generate final video
        generator.generate_video(
            subtitles, str(audio_path), str(output_path), str(input_path)
        )

        print("\n" + "=" * 60)
        print("✓ SUCCES!")
        print("=" * 60)
        print(f"Video met ondertitels: {output_path}")
        print("=" * 60)

    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
