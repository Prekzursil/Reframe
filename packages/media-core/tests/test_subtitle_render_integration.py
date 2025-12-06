import types

from media_core.subtitles.builder import SubtitleLine
from media_core.subtitles.styled import StyledSubtitleRenderer
from media_core.transcribe.models import Word


def test_render_preview_with_fake_moviepy(monkeypatch):
    # Stub ColorClip to avoid moviepy dependency.
    class FakeClip:
        def __init__(self, size, color):
            self.size = size
            self.color = color
            self.duration = None

        def set_duration(self, dur):
            self.duration = dur
            return self

    fake_editor = types.SimpleNamespace(ColorClip=FakeClip)
    monkeypatch.setitem(
        __import__("sys").modules,
        "moviepy",
        types.SimpleNamespace(editor=fake_editor),
    )
    monkeypatch.setitem(__import__("sys").modules, "moviepy.editor", fake_editor)

    lines = [
        SubtitleLine(start=0.0, end=2.0, words=[Word(text="hello", start=0.0, end=1.0)]),
        SubtitleLine(start=2.1, end=5.5, words=[Word(text="world", start=2.1, end=3.0)]),
        SubtitleLine(start=6.0, end=8.5, words=[Word(text="again", start=6.0, end=8.5)]),
    ]
    renderer = StyledSubtitleRenderer()
    clip = renderer.render_preview(lines, size=(320, 640))
    assert isinstance(clip, FakeClip)
    assert clip.duration == 8.5
    assert clip.size == (320, 640)
