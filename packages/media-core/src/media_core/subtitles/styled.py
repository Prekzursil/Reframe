from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

from media_core.subtitles.builder import SubtitleLine

logger = logging.getLogger(__name__)

Color = Tuple[int, int, int]  # RGB 0-255


@dataclass
class SubtitleStyle:
    font: str = "Arial"
    font_size: int = 48
    text_color: Color = (255, 255, 255)
    highlight_color: Color = (255, 235, 59)
    stroke_color: Color = (0, 0, 0)
    stroke_width: int = 2
    shadow: bool = True
    shadow_offset: Tuple[int, int] = (2, 2)
    align: str = "center"  # center | left | right
    position: str = "bottom"  # bottom | top


def preset_styles() -> List[SubtitleStyle]:
    return [
        SubtitleStyle(),
        SubtitleStyle(
            font="Arial",
            font_size=52,
            text_color=(255, 255, 255),
            highlight_color=(255, 200, 87),
            stroke_color=(0, 0, 0),
            stroke_width=3,
            shadow=True,
            align="center",
        ),
        SubtitleStyle(
            font="Helvetica",
            font_size=48,
            text_color=(245, 245, 245),
            highlight_color=(58, 134, 255),
            stroke_color=(0, 0, 0),
            stroke_width=2,
            shadow=True,
            position="top",
        ),
    ]


class StyledSubtitleRenderer:
    """Renderer scaffold for TikTok-style subtitles.

    This provides a lightweight render plan and a solid-color preview. MoviePy import
    is deferred to runtime to avoid heavy dependencies during tests.
    """

    """Renderer scaffold for TikTok-style subtitles.

    This provides a lightweight render plan and a solid-color preview. MoviePy import
    is deferred to runtime to avoid heavy dependencies during tests.
    """

    def __init__(self, style: Optional[SubtitleStyle] = None):
        self.style = style or SubtitleStyle()

    def render_preview(
        self,
        lines: Iterable[SubtitleLine],
        *,
        size: Tuple[int, int] = (1080, 1920),
        background_color: Color = (0, 0, 0),
    ):
        try:
            from moviepy.editor import ColorClip  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "moviepy is required for rendering. Install with `pip install moviepy`."
            ) from exc

        duration = max((line.end for line in lines), default=0.0)
        clip = ColorClip(size, color=background_color).set_duration(duration)
        return clip

    def build_plan(
        self,
        lines: Iterable[SubtitleLine],
        *,
        size: Tuple[int, int] = (1080, 1920),
        orientation: str = "vertical",  # vertical 9:16 or horizontal 16:9
    ) -> Dict[str, object]:
        """Build a render plan with approximate positions and timings."""
        width, height = size
        padding_x = width * 0.1
        padding_y = height * 0.08
        line_height = self.style.font_size * 1.2
        y_base = height - padding_y if self.style.position == "bottom" else padding_y
        align = self.style.align

        base_layers: List[Dict[str, object]] = []
        word_layers: List[Dict[str, object]] = []

        def compute_x(text: str) -> float:
            approx_char_w = self.style.font_size * 0.6
            text_w = max(approx_char_w, len(text) * approx_char_w)
            if align == "center":
                return (width - text_w) / 2
            if align == "left":
                return padding_x
            return width - padding_x - text_w

        for idx, line in enumerate(lines):
            text = line.text()
            y = y_base - idx * line_height if self.style.position == "bottom" else y_base + idx * line_height
            x = compute_x(text)
            base_layers.append(
                {
                    "text": text,
                    "start": line.start,
                    "end": line.end,
                    "x": x,
                    "y": y,
                    "font": self.style.font,
                    "font_size": self.style.font_size,
                    "color": self.style.text_color,
                    "stroke_color": self.style.stroke_color,
                    "stroke_width": self.style.stroke_width,
                    "shadow": self.style.shadow,
                    "shadow_offset": self.style.shadow_offset,
                }
            )
            for word in line.words:
                wx = compute_x(word.text)
                wy = y
                word_layers.append(
                    {
                        "text": word.text,
                        "start": word.start,
                        "end": word.end,
                        "x": wx,
                        "y": wy,
                        "color": self.style.highlight_color,
                    }
                )

        return {
            "base_layers": base_layers,
            "word_layers": word_layers,
            "meta": {"size": size, "orientation": orientation, "style": self.style},
        }

    def render_video(
        self,
        lines: Iterable[SubtitleLine],
        *,
        size: Tuple[int, int] = (1080, 1920),
        background_color: Color = (0, 0, 0),
    ):
        """Render subtitles with MoviePy text/highlight layers.

        Falls back to render_preview when MoviePy or ImageMagick is unavailable.
        """
        try:  # pragma: no cover - optional dependency
            from moviepy.editor import ColorClip, CompositeVideoClip, TextClip  # type: ignore
        except Exception as exc:  # pragma: no cover
            logger.warning("MoviePy not available (%s); falling back to preview-only clip", exc)
            return self.render_preview(lines, size=size, background_color=background_color)

        plan = self.build_plan(lines, size=size)
        base_layers = plan["base_layers"]
        word_layers = plan["word_layers"]

        duration = max((layer["end"] for layer in base_layers), default=0.1)
        base_clip = ColorClip(size, color=background_color).set_duration(duration)

        clips = [base_clip]
        for layer in base_layers:
            try:
                clip = (
                    TextClip(
                        layer["text"],
                        font=self.style.font,
                        fontsize=int(self.style.font_size),
                        color=_rgb_to_hex(layer["color"]),
                        stroke_color=_rgb_to_hex(layer["stroke_color"]),
                        stroke_width=int(self.style.stroke_width),
                    )
                    .set_position((layer["x"], layer["y"]))
                    .set_start(layer["start"])
                    .set_end(layer["end"])
                )
                clips.append(clip)
            except Exception as exc:
                logger.debug("Skipping base layer due to render error: %s", exc)

        for layer in word_layers:
            try:
                clip = (
                    TextClip(
                        layer["text"],
                        font=self.style.font,
                        fontsize=int(self.style.font_size),
                        color=_rgb_to_hex(layer["color"]),
                    )
                    .set_position((layer["x"], layer["y"]))
                    .set_start(layer["start"])
                    .set_end(layer["end"])
                )
                clips.append(clip)
            except Exception as exc:
                logger.debug("Skipping word layer due to render error: %s", exc)

        return CompositeVideoClip(clips)


def _rgb_to_hex(color: Color) -> str:
    r, g, b = color
    return "#{:02x}{:02x}{:02x}".format(r, g, b)
