"""Coverage for StyledSubtitleRenderer alignment and MoviePy render paths.

MoviePy is mocked via a fake ``moviepy.editor`` module so the heavy dependency
(and ImageMagick) is never required.
"""

from __future__ import annotations

import sys
import types

import pytest

from media_core.subtitles import styled as styled_mod
from media_core.subtitles.builder import SubtitleLine
from media_core.subtitles.styled import (
    StyledSubtitleRenderer,
    SubtitleStyle,
    _rgb_to_hex,
)
from media_core.transcribe.models import Word


def _line():
    return SubtitleLine(
        start=0.0,
        end=2.0,
        words=[Word(text="hello", start=0.0, end=1.0), Word(text="world", start=1.0, end=2.0)],
    )


def test_rgb_to_hex():
    assert _rgb_to_hex((255, 0, 16)) == "#ff0010"


def test_build_plan_left_align():
    style = SubtitleStyle(align="left")
    renderer = StyledSubtitleRenderer(style)
    plan = renderer.build_plan([_line()], size=(720, 1280))
    # Left alignment positions text at the left padding.
    expected_x = 720 * 0.1
    assert plan["base_layers"][0]["x"] == pytest.approx(expected_x)


def test_build_plan_right_align():
    style = SubtitleStyle(align="right")
    renderer = StyledSubtitleRenderer(style)
    plan = renderer.build_plan([_line()], size=(720, 1280))
    # Right alignment positions text against the right padding minus text width.
    assert plan["base_layers"][0]["x"] < 720


def _install_fake_moviepy(monkeypatch, *, text_clip):
    """Install a fake ``moviepy.editor`` exposing the clip classes used by render_video."""

    class FakeColorClip:
        def __init__(self, size, color=None):
            self.size = size
            self.color = color
            self.duration = None

        def set_duration(self, duration):
            self.duration = duration
            return self

    class FakeComposite:
        def __init__(self, clips):
            self.clips = clips

    fake_editor = types.ModuleType("moviepy.editor")
    fake_editor.ColorClip = FakeColorClip
    fake_editor.CompositeVideoClip = FakeComposite
    fake_editor.TextClip = text_clip

    fake_moviepy = types.ModuleType("moviepy")
    fake_moviepy.editor = fake_editor
    monkeypatch.setitem(sys.modules, "moviepy", fake_moviepy)
    monkeypatch.setitem(sys.modules, "moviepy.editor", fake_editor)
    return FakeComposite


class _ChainableTextClip:
    """Minimal MoviePy TextClip stand-in supporting the fluent setters."""

    instances: list = []

    def __init__(self, text, **kwargs):
        self.text = text
        self.kwargs = kwargs
        _ChainableTextClip.instances.append(self)

    def set_position(self, _pos):
        return self

    def set_start(self, _start):
        return self

    def set_end(self, _end):
        return self


def test_render_video_composes_clips(monkeypatch):
    _ChainableTextClip.instances = []
    FakeComposite = _install_fake_moviepy(monkeypatch, text_clip=_ChainableTextClip)

    renderer = StyledSubtitleRenderer()
    result = renderer.render_video([_line()], size=(320, 240))

    assert isinstance(result, FakeComposite)
    # base clip + one base text layer + two word layers = 4 clips.
    assert len(result.clips) == 4
    # Each text layer was created with the requested text.
    texts = [c.text for c in _ChainableTextClip.instances]
    assert "hello world" in texts  # base layer text
    assert "hello" in texts and "world" in texts


def test_render_video_skips_layers_on_textclip_error(monkeypatch):
    class ExplodingTextClip:
        def __init__(self, *_args, **_kwargs):
            raise RuntimeError("imagemagick missing")

    FakeComposite = _install_fake_moviepy(monkeypatch, text_clip=ExplodingTextClip)

    renderer = StyledSubtitleRenderer()
    result = renderer.render_video([_line()], size=(320, 240))
    # All text layers fail and are skipped; only the base ColorClip remains.
    assert isinstance(result, FakeComposite)
    assert len(result.clips) == 1


def test_render_video_falls_back_to_preview_without_moviepy(monkeypatch):
    # Make every moviepy import raise so render_video falls back to render_preview,
    # which also fails to import and raises RuntimeError.
    real_import = __import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("moviepy"):
            raise ImportError("moviepy not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)
    renderer = StyledSubtitleRenderer()
    with pytest.raises(RuntimeError, match="moviepy is required"):
        renderer.render_video([_line()], size=(320, 240))


def test_styled_module_symbols():
    assert hasattr(styled_mod, "StyledSubtitleRenderer")
