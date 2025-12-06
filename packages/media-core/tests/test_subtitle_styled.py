import pytest

from media_core.subtitles.builder import SubtitleLine
from media_core.subtitles.styled import StyledSubtitleRenderer, SubtitleStyle, preset_styles
from media_core.transcribe.models import Word


def test_preset_styles_present():
    styles = preset_styles()
    assert len(styles) >= 3
    assert isinstance(styles[0], SubtitleStyle)


def test_renderer_raises_without_moviepy(monkeypatch):
    line = SubtitleLine(start=0.0, end=1.0, words=[Word(text="hi", start=0.0, end=1.0)])

    real_import = __import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("moviepy"):
            raise ImportError("moviepy not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)
    renderer = StyledSubtitleRenderer()
    with pytest.raises(RuntimeError):
        renderer.render_preview([line], size=(320, 240))


def test_build_plan_produces_layers():
    lines = [
        SubtitleLine(
            start=0.0,
            end=2.0,
            words=[Word(text="hello", start=0.0, end=0.5), Word(text="world", start=0.6, end=1.2)],
        )
    ]
    renderer = StyledSubtitleRenderer()
    plan = renderer.build_plan(lines, size=(720, 1280), orientation="vertical")
    assert plan["base_layers"] and plan["word_layers"]
    assert plan["meta"]["size"] == (720, 1280)
    assert plan["meta"]["orientation"] == "vertical"
    # word timing retained
    assert plan["word_layers"][0]["start"] == 0.0
    assert plan["word_layers"][1]["end"] == 1.2
