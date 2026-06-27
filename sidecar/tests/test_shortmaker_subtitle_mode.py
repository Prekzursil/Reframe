"""P4 §4 — subtitle DELIVERY mode + caption position routing (shortmaker.py).

Self-contained: exercises the pure resolvers + ``_lazy_caption`` with both
caption engines faked (no ffmpeg, no heavy-ML imports).
"""

from __future__ import annotations

import pytest
from media_studio.features import shortmaker as sm


# --------------------------------------------------------------------------- #
# pure resolvers
# --------------------------------------------------------------------------- #
def test_resolve_subtitle_mode_defaults_to_burn():
    assert sm.resolve_subtitle_mode({}) == "burn"
    assert sm.resolve_subtitle_mode(None) == "burn"
    assert sm.resolve_subtitle_mode({"subtitleMode": "bogus"}) == "burn"


@pytest.mark.parametrize("mode", ["burn", "softmux", "sidecar", "none"])
def test_resolve_subtitle_mode_validates_case_insensitively(mode):
    assert sm.resolve_subtitle_mode({"subtitleMode": f"  {mode.upper()} "}) == mode


def test_caption_embedded():
    assert sm.caption_embedded({"subtitleMode": "burn"}) is True
    assert sm.caption_embedded({"subtitleMode": "softmux"}) is True
    assert sm.caption_embedded({"subtitleMode": "sidecar"}) is False
    assert sm.caption_embedded({"subtitleMode": "none"}) is False


def test_resolve_caption_burn():
    assert sm.resolve_caption_burn({"subtitleMode": "burn"}) is True
    assert sm.resolve_caption_burn({"subtitleMode": "softmux"}) is False
    assert sm.resolve_caption_burn({}) is True  # default burn


# --------------------------------------------------------------------------- #
# _lazy_caption delivery routing
# --------------------------------------------------------------------------- #
def _route(monkeypatch, settings):
    fired: dict = {}

    class FakeLibass:
        def __init__(self, s):
            fired["engine"] = "libass"

        def render(self, clip, cues, out, **kw):
            fired["kw"] = kw
            return out

    class FakeRemotion:
        def __init__(self, s):
            fired["engine"] = "remotion"

        def render(self, clip, cues, out, **kw):
            fired["kw"] = kw
            return out

    import media_studio.features.caption as cap
    import media_studio.features.caption_remotion as rem

    monkeypatch.setattr(cap, "CaptionEngine", FakeLibass)
    monkeypatch.setattr(rem, "RemotionCaptionEngine", FakeRemotion)
    out = sm._lazy_caption(
        "clip.mp4",
        [],
        "out.mp4",
        source_start=0.0,
        burn=True,
        width=1080,
        height=1920,
        settings=settings,
    )
    return fired, out


def test_sidecar_mode_skips_embedding(monkeypatch):
    fired, out = _route(monkeypatch, {"captionStyle": "libass", "subtitleMode": "sidecar"})
    assert "engine" not in fired  # nothing embedded in the video
    assert out == "clip.mp4"


def test_none_mode_skips_embedding(monkeypatch):
    fired, out = _route(monkeypatch, {"captionStyle": "bold", "subtitleMode": "none"})
    assert "engine" not in fired
    assert out == "clip.mp4"


def test_softmux_mode_still_renders(monkeypatch):
    fired, out = _route(monkeypatch, {"captionStyle": "libass", "subtitleMode": "softmux"})
    assert fired["engine"] == "libass"
    assert out == "out.mp4"


def test_caption_position_threaded_to_libass(monkeypatch):
    box = {"x": 0.0, "y": 0.05, "w": 1.0, "h": 0.1}
    fired, _out = _route(monkeypatch, {"captionStyle": "libass", "subtitleMode": "burn", "captionPosition": box})
    assert fired["engine"] == "libass"
    assert fired["kw"]["position"] == box
