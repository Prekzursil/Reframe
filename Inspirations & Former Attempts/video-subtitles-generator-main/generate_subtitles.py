#!/usr/bin/env python3
"""
Generate Descript-like word-highlighted subtitles for videos.
Based on: https://github.com/ramsrigouthamg/Supertranslate.ai
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import ffmpeg
import whisper

# Configure MoviePy to find ImageMagick
os.environ["IMAGEMAGICK_BINARY"] = "/opt/homebrew/bin/convert"

from moviepy.editor import (
    AudioFileClip,
    ColorClip,
    CompositeVideoClip,
    TextClip,
)


class SubtitleGenerator:
    """Generate word-highlighted subtitles for videos."""

    def __init__(
        self,
        max_chars: int = 80,
        max_words: int = 4,
        max_duration: float = 3.0,
        max_gap: float = 1.5,
        font: str = None,
        fontsize: int = 80,
        color: str = "white",
        highlight_color: str = "blue",
        bg_width: int = 1080,
        bg_height: int = 1920,
        bg_color: Tuple[int, int, int] = (28, 163, 236),
        stroke_color: str = "black",
        stroke_width: int = 3,
        shadow: bool = True,
        shadow_offset: int = 6,
        shadow_color: str = "black",
        outline: bool = True,
        outline_width: int = 4,
        outline_color: str = "black",
    ):
        """Initialize subtitle generator with configuration parameters.

        Note: stroke_width is for inner stroke (default 3px).
        outline creates a thick border around text (default 4px, 8 directions).
        Shadow is enabled by default for extra depth.
        """
        self.max_chars = max_chars
        self.max_words = max_words
        self.max_duration = max_duration
        self.max_gap = max_gap
        # Use system default font if none specified - more reliable cross-platform
        self.font = font if font else self._get_default_font()
        self.fontsize = fontsize
        self.color = color
        self.highlight_color = highlight_color
        self.bg_width = bg_width
        self.bg_height = bg_height
        self.bg_color = bg_color
        self.stroke_color = stroke_color
        self.stroke_width = stroke_width
        self.shadow = shadow
        self.shadow_offset = shadow_offset
        self.shadow_color = shadow_color
        self.outline = outline
        self.outline_width = outline_width
        self.outline_color = outline_color

    def _get_default_font(self) -> str:
        """Get a default BOLD/BLACK font that works cross-platform.

        Prioritizes heavy, impactful fonts for social media style subtitles.
        """
        import platform

        system = platform.system()

        if system == "Darwin":  # macOS
            # Try heavy/black fonts first for maximum impact
            possible_fonts = [
                # Very bold fonts (preferred)
                "/System/Library/Fonts/Supplemental/Impact.ttf",
                "/System/Library/Fonts/Supplemental/Arial Black.ttf",
                "/Library/Fonts/Arial Black.ttf",
                # Bold variants
                "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
                "/System/Library/Fonts/Supplemental/Futura.ttc",  # Contains Bold
                # Fallbacks
                "/System/Library/Fonts/Helvetica.ttc",
                "/System/Library/Fonts/SFNSDisplay.ttf",
            ]
        elif system == "Linux":
            possible_fonts = [
                # Very bold fonts
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-ExtraBold.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            ]
        else:  # Windows
            possible_fonts = [
                "C:\\Windows\\Fonts\\impact.ttf",
                "C:\\Windows\\Fonts\\ariblk.ttf",  # Arial Black
                "C:\\Windows\\Fonts\\arialbd.ttf",  # Arial Bold
                "C:\\Windows\\Fonts\\arial.ttf",
            ]

        # Check which font exists
        for font_path in possible_fonts:
            if os.path.exists(font_path):
                print(f"Using bold font: {font_path}")
                return font_path

        # Fallback to None (moviepy will use default)
        print("Warning: No bold font found, using system default")
        return None

    def get_video_resolution(self, video_path: str) -> Tuple[int, int]:
        """Get video resolution using ffprobe."""
        print(f"Detecting video resolution for {video_path}...")
        try:
            probe = ffmpeg.probe(video_path)
            video_stream = next(
                (
                    stream
                    for stream in probe["streams"]
                    if stream["codec_type"] == "video"
                ),
                None,
            )
            if video_stream is None:
                raise ValueError("No video stream found")

            width = int(video_stream["width"])
            height = int(video_stream["height"])
            print(f"Detected resolution: {width}x{height}")
            return width, height
        except Exception as e:
            print(f"Warning: Could not detect video resolution: {e}")
            print(f"Using default resolution: {self.bg_width}x{self.bg_height}")
            return self.bg_width, self.bg_height

    def extract_audio(self, video_path: str, audio_path: str) -> None:
        """Extract audio from video file."""
        print(f"Extracting audio from {video_path}...")
        try:
            # Select only the first audio stream (0:a:0) to handle videos with multiple audio tracks
            # This is common with iPhone videos that have spatial audio
            input_stream = ffmpeg.input(video_path)
            output_stream = ffmpeg.output(
                input_stream["a:0"],
                audio_path,
                acodec="libmp3lame",
                audio_bitrate="192k",
            )
            output_stream = ffmpeg.overwrite_output(output_stream)
            ffmpeg.run(output_stream, capture_stdout=True, capture_stderr=True)
            print(f"Audio extracted to {audio_path}")
        except ffmpeg.Error as e:
            print("FFmpeg error details:")
            print(f"stdout: {e.stdout.decode() if e.stdout else 'N/A'}")
            print(f"stderr: {e.stderr.decode() if e.stderr else 'N/A'}")
            raise

    def transcribe_audio(
        self, audio_path: str, model_name: str = "large", language: str = "nl"
    ) -> Dict:
        """Transcribe audio using Whisper with word-level timestamps."""
        print(f"Loading Whisper model '{model_name}'...")
        model = whisper.load_model(model_name)
        print(f"Transcribing {audio_path} (language: {language})...")
        result = model.transcribe(audio_path, word_timestamps=True, language=language)
        print("Transcription completed!")
        return result

    def save_word_timestamps(self, result: Dict, output_path: str) -> None:
        """Save word-level timestamps to JSON file."""
        word_timestamps = []
        for segment in result["segments"]:
            for word_data in segment.get("words", []):
                word_timestamps.append(
                    {
                        "word": word_data["word"],
                        "start": word_data["start"],
                        "end": word_data["end"],
                    }
                )

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(word_timestamps, f, indent=2, ensure_ascii=False)
        print(f"Word timestamps saved to {output_path}")

    def load_word_timestamps(self, json_path: str) -> List[Dict]:
        """Load word timestamps from JSON file."""
        with open(json_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def split_text_into_lines(self, word_timestamps: List[Dict]) -> List[Dict]:
        """Split word-level timestamps into subtitle lines."""
        subtitles = []
        line = []
        line_duration = 0
        line_chars = 0

        for idx, word_data in enumerate(word_timestamps):
            word = word_data["word"]
            end = word_data["end"]

            line.append(word_data)
            line_chars += len(word)
            line_duration = end - line[0]["start"]

            # Check if we need to break the line
            temp = " ".join([w["word"] for w in line])
            new_line_chars = len(temp)

            # Determine if next word should trigger line break
            should_break = False
            if idx < len(word_timestamps) - 1:
                next_word = word_timestamps[idx + 1]["word"]
                next_start = word_timestamps[idx + 1]["start"]
                gap = next_start - end
                current_word_count = len(line)

                if (
                    line_duration >= self.max_duration
                    or new_line_chars + len(next_word) > self.max_chars
                    or current_word_count >= self.max_words
                    or gap > self.max_gap
                ):
                    should_break = True
            else:
                # Last word
                should_break = True

            if should_break:
                subtitle = {
                    "word": " ".join([w["word"] for w in line]),
                    "start": line[0]["start"],
                    "end": line[-1]["end"],
                    "textcontents": line,
                }
                subtitles.append(subtitle)
                line = []
                line_duration = 0
                line_chars = 0

        return subtitles

    def create_caption(self, subtitle_data: Dict, framesize: Tuple[int, int]) -> list:
        """Create caption clip with word-level highlighting - Descript style with stroke and shadow."""
        word_clips = []
        frame_width = framesize[0]
        frame_height = framesize[1]

        # Calculate text positioning
        # Position at bottom center of frame
        y_base = frame_height - 200  # 200px from bottom

        # Build full line to calculate total width and center it
        words = subtitle_data["textcontents"]

        # Calculate positions for each word
        word_positions = []
        x_offset = 0

        # First pass: calculate all word widths
        for word_data in words:
            word_text = word_data["word"]
            # Create temporary clip to get size
            temp_clip = TextClip(
                word_text,
                font=self.font,
                fontsize=self.fontsize,
                color=self.color,
                stroke_color=self.stroke_color,
                stroke_width=self.stroke_width,
            )
            word_width = temp_clip.size[0]
            word_height = temp_clip.size[1]

            word_positions.append(
                {
                    "word": word_text,
                    "width": word_width,
                    "height": word_height,
                    "x_offset": x_offset,
                    "start": word_data["start"],
                    "end": word_data["end"],
                }
            )

            x_offset += word_width

        # Calculate centering offset
        total_width = x_offset
        center_offset = (frame_width - total_width) // 2

        # Layer 1: Drop Shadow (if enabled) - behind everything
        if self.shadow:
            for pos in word_positions:
                shadow_clip = (
                    TextClip(
                        pos["word"],
                        font=self.font,
                        fontsize=self.fontsize,
                        color=self.shadow_color,
                        stroke_color=self.shadow_color,
                        stroke_width=self.stroke_width + 2,
                    )
                    .set_start(subtitle_data["start"])
                    .set_duration(subtitle_data["end"] - subtitle_data["start"])
                    .set_position(
                        (
                            center_offset + pos["x_offset"] + self.shadow_offset,
                            y_base + self.shadow_offset,
                        )
                    )
                )
                word_clips.append(shadow_clip)

        # Layer 2: Outline (if enabled) - thick black border in 8 directions
        if self.outline:
            # Create outline by placing black text in 8 directions around the main text
            outline_offsets = [
                (-self.outline_width, -self.outline_width),  # top-left
                (0, -self.outline_width),  # top
                (self.outline_width, -self.outline_width),  # top-right
                (-self.outline_width, 0),  # left
                (self.outline_width, 0),  # right
                (-self.outline_width, self.outline_width),  # bottom-left
                (0, self.outline_width),  # bottom
                (self.outline_width, self.outline_width),  # bottom-right
            ]

            for pos in word_positions:
                for offset_x, offset_y in outline_offsets:
                    outline_clip = (
                        TextClip(
                            pos["word"],
                            font=self.font,
                            fontsize=self.fontsize,
                            color=self.outline_color,
                            stroke_color=self.outline_color,
                            stroke_width=self.stroke_width,
                        )
                        .set_start(subtitle_data["start"])
                        .set_duration(subtitle_data["end"] - subtitle_data["start"])
                        .set_position(
                            (
                                center_offset + pos["x_offset"] + offset_x,
                                y_base + offset_y,
                            )
                        )
                    )
                    word_clips.append(outline_clip)

        # Layer 3: White base clips with stroke for each word
        for pos in word_positions:
            word_clip = (
                TextClip(
                    pos["word"],
                    font=self.font,
                    fontsize=self.fontsize,
                    color=self.color,
                    stroke_color=self.stroke_color,
                    stroke_width=self.stroke_width,
                )
                .set_start(subtitle_data["start"])
                .set_duration(subtitle_data["end"] - subtitle_data["start"])
                .set_position((center_offset + pos["x_offset"], y_base))
            )

            word_clips.append(word_clip)

        # Layer 4: Highlight clips with stroke for each word
        for pos in word_positions:
            highlight_clip = (
                TextClip(
                    pos["word"],
                    font=self.font,
                    fontsize=self.fontsize,
                    color=self.highlight_color,
                    stroke_color=self.stroke_color,
                    stroke_width=self.stroke_width,
                )
                .set_start(pos["start"])
                .set_duration(pos["end"] - pos["start"])
                .set_position((center_offset + pos["x_offset"], y_base))
            )

            word_clips.append(highlight_clip)

        return word_clips

    def generate_video(
        self,
        subtitles: List[Dict],
        audio_path: str,
        output_path: str,
        video_path: str = None,
    ) -> None:
        """Generate final video with subtitles."""
        print("Generating video with subtitles...")

        frame_size = (self.bg_width, self.bg_height)
        all_clips = []

        for subtitle in subtitles:
            caption_clips = self.create_caption(subtitle, frame_size)
            all_clips.extend(caption_clips)

        # Create background clip
        audio_clip = AudioFileClip(audio_path)

        if video_path:
            # Use original video as background
            from moviepy.editor import VideoFileClip

            print(f"Using original video as background: {video_path}")
            bg_clip = VideoFileClip(video_path)
            # Resize if needed (compare dimensions, not exact tuple equality)
            if bg_clip.size[0] != frame_size[0] or bg_clip.size[1] != frame_size[1]:
                print(f"Resizing video from {bg_clip.size} to {frame_size}")
                bg_clip = bg_clip.resize(frame_size)
            else:
                print(f"Video size matches target size: {frame_size}")
        else:
            # Use colored background (blue screen)
            print("Using colored background")
            bg_clip = ColorClip(
                size=frame_size, color=self.bg_color, duration=audio_clip.duration
            )

        # Composite everything
        final_video = CompositeVideoClip([bg_clip] + all_clips, size=frame_size)
        final_video = final_video.set_duration(audio_clip.duration)
        final_video = final_video.set_audio(audio_clip)

        # Write output
        print(f"Writing video to {output_path}...")
        final_video.write_videofile(
            output_path,
            fps=24,
            codec="libx264",
            audio_codec="aac",
            threads=4,
            preset="medium",
        )
        print(f"Video generated successfully: {output_path}")

    def process_video(
        self,
        video_path: str,
        output_path: str,
        whisper_model: str = "large",
        language: str = "nl",
        save_intermediate: bool = True,
        skip_transcription: bool = False,
    ) -> None:
        """Complete pipeline: video -> audio -> transcription -> subtitles -> final video.

        Args:
            video_path: Path to input video
            output_path: Path to output video
            whisper_model: Whisper model size
            language: Language code for transcription
            save_intermediate: Keep intermediate files (audio, JSON)
            skip_transcription: Skip transcription if JSON exists (auto-detected if False)
        """
        video_path = Path(video_path)
        output_path = Path(output_path)

        # Setup intermediate file paths
        audio_path = video_path.parent / f"{video_path.stem}_audio.mp3"
        json_path = video_path.parent / f"{video_path.stem}_timestamps.json"

        # Step 0: Detect video resolution and update background size
        width, height = self.get_video_resolution(str(video_path))
        self.bg_width = width
        self.bg_height = height

        # Adjust fontsize based on video dimensions
        # Use larger font for impactful social media style subtitles
        base_dimension = min(width, height)
        self.fontsize = int(base_dimension * 0.09)  # 9% of smaller dimension (was 5%)
        print(f"Adjusted font size to {self.fontsize} for {width}x{height} video")

        # Check if timestamps JSON already exists
        if json_path.exists():
            print(f"Found existing timestamps file: {json_path}")
            print("Skipping transcription and reusing existing timestamps...")
            skip_transcription = True
        else:
            print("No existing timestamps found, will transcribe audio...")

        # Step 1 & 2 & 3: Extract audio, transcribe, and save timestamps (if needed)
        if not skip_transcription:
            # Step 1: Extract audio
            self.extract_audio(str(video_path), str(audio_path))

            # Step 2: Transcribe with Whisper
            result = self.transcribe_audio(str(audio_path), whisper_model, language)

            # Step 3: Save word timestamps
            self.save_word_timestamps(result, str(json_path))
        else:
            # Make sure audio file exists for video generation
            if not audio_path.exists():
                print("Audio file not found, extracting audio...")
                self.extract_audio(str(video_path), str(audio_path))

        # Step 4: Load and split into lines
        word_timestamps = self.load_word_timestamps(str(json_path))
        subtitles = self.split_text_into_lines(word_timestamps)

        # Step 5: Generate final video with original video as background
        self.generate_video(
            subtitles, str(audio_path), str(output_path), str(video_path)
        )

        # Cleanup intermediate files if requested
        if not save_intermediate:
            audio_path.unlink(missing_ok=True)
            json_path.unlink(missing_ok=True)
            print("Intermediate files cleaned up")


def main():
    """Main entry point for the script."""
    parser = argparse.ArgumentParser(
        description="Generate Descript-like word-highlighted subtitles for videos"
    )
    parser.add_argument("input", type=str, help="Input video file path")
    parser.add_argument(
        "-o",
        "--output",
        type=str,
        help="Output video file path (default: input_subtitled.mp4)",
    )
    parser.add_argument(
        "-m",
        "--model",
        type=str,
        default="large",
        choices=["tiny", "base", "small", "medium", "large"],
        help="Whisper model size (default: large)",
    )
    parser.add_argument(
        "-l",
        "--language",
        type=str,
        default="nl",
        help="Language code for transcription (default: nl for Dutch)",
    )
    parser.add_argument(
        "--max-chars",
        type=int,
        default=80,
        help="Maximum characters per subtitle line (default: 80)",
    )
    parser.add_argument(
        "--max-words",
        type=int,
        default=4,
        help="Maximum words per subtitle line (default: 4)",
    )
    parser.add_argument(
        "--max-duration",
        type=float,
        default=3.0,
        help="Maximum duration per subtitle line in seconds (default: 3.0)",
    )
    parser.add_argument(
        "--max-gap",
        type=float,
        default=1.5,
        help="Maximum gap between words in seconds (default: 1.5)",
    )
    parser.add_argument(
        "--fontsize",
        type=int,
        default=80,
        help="Font size for subtitles (default: 80)",
    )
    parser.add_argument(
        "--keep-intermediate",
        action="store_true",
        help="Keep intermediate audio and JSON files",
    )

    args = parser.parse_args()

    # Validate input file
    if not os.path.exists(args.input):
        print(f"Error: Input file '{args.input}' does not exist")
        sys.exit(1)

    # Set output path
    if args.output:
        output_path = args.output
    else:
        input_path = Path(args.input)
        output_path = input_path.parent / f"{input_path.stem}_subtitled.mp4"

    # Initialize generator with parameters
    generator = SubtitleGenerator(
        max_chars=args.max_chars,
        max_words=args.max_words,
        max_duration=args.max_duration,
        max_gap=args.max_gap,
        fontsize=args.fontsize,
    )

    # Process video
    try:
        generator.process_video(
            args.input,
            str(output_path),
            whisper_model=args.model,
            language=args.language,
            save_intermediate=args.keep_intermediate,
        )
        print(f"\nSuccess! Output saved to: {output_path}")
    except Exception as e:
        print(f"\nError processing video: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
