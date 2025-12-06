from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable, List, Optional, Tuple

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
        SubtitleStyle(),  # default
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
    """Renderer for TikTok-style word highlights.

    This is a scaffold; actual MoviePy rendering is not executed in tests. Import
    of moviepy is deferred to runtime to avoid heavy deps for now.
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

        # Placeholder: create a blank clip to show wiring. Real text layers to be added later.
        duration = max((line.end for line in lines), default=0.0)
        clip = ColorClip(size, color=background_color).set_duration(duration)
        return clip
