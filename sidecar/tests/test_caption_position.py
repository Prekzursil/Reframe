"""P4 §4 — caption POSITION box -> ASS alignment + margins (caption.py).

Heavy-ML-free: ffmpeg is mocked at the seam (binary resolution monkeypatched,
runner injected), so no real ffmpeg is spawned.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from media_studio import ffmpeg
from media_studio.features import caption
from media_studio.features.caption import CaptionEngine, build_ass


def cue(index: int, start: float, end: float, text: str) -> dict[str, Any]:
    return {"index": index, "start": start, "end": end, "text": text}


@pytest.fixture()
def fake_ffmpeg(monkeypatch, tmp_path: Path):
    fake = tmp_path / "ffmpeg"
    fake.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(ffmpeg, "ffmpeg_path", lambda settings=None: str(fake))
    return str(fake)


def _default_style_line(doc: str) -> list[str]:
    line = next(ln for ln in doc.splitlines() if ln.startswith("Style: Default,"))
    return line.split(",")


# --------------------------------------------------------------------------- #
# normalize_caption_box
# --------------------------------------------------------------------------- #
def test_normalize_caption_box_clamps_into_unit_range():
    assert caption.normalize_caption_box({"x": -0.5, "y": 2.0, "w": 5.0, "h": -1.0}) == {
        "x": 0.0,
        "y": 1.0,
        "w": 1.0,
        "h": 0.0,
    }


def test_normalize_caption_box_passes_valid_box():
    assert caption.normalize_caption_box({"x": 0.1, "y": 0.2, "w": 0.5, "h": 0.2}) == {
        "x": 0.1,
        "y": 0.2,
        "w": 0.5,
        "h": 0.2,
    }


def test_normalize_caption_box_rejects_bad_input():
    assert caption.normalize_caption_box(None) is None
    assert caption.normalize_caption_box([1, 2]) is None
    assert caption.normalize_caption_box({"x": 0.1}) is None
    assert caption.normalize_caption_box({"x": "wide", "y": 0, "w": 0.5, "h": 0.2}) is None
    assert caption.normalize_caption_box({"x": float("nan"), "y": 0, "w": 0.5, "h": 0.2}) is None


# --------------------------------------------------------------------------- #
# caption_position_fields
# --------------------------------------------------------------------------- #
def test_caption_position_fields_bottom_band():
    align, ml, mr, mv = caption.caption_position_fields({"x": 0.1, "y": 0.8, "w": 0.8, "h": 0.15}, 1000, 2000)
    assert align == 2
    assert (ml, mr) == (100, 100)
    assert mv == int(round((1.0 - 0.95) * 2000))


def test_caption_position_fields_top_band():
    align, _ml, _mr, mv = caption.caption_position_fields({"x": 0.0, "y": 0.02, "w": 1.0, "h": 0.1}, 1000, 2000)
    assert align == 8
    assert mv == int(round(0.02 * 2000))


def test_caption_position_fields_middle_band():
    align, _ml, _mr, mv = caption.caption_position_fields({"x": 0.0, "y": 0.45, "w": 1.0, "h": 0.1}, 1000, 2000)
    assert align == 5
    assert mv == 0


# --------------------------------------------------------------------------- #
# build_ass + CaptionEngine threading
# --------------------------------------------------------------------------- #
def test_build_ass_honours_position_box_top():
    doc = build_ass(
        [cue(1, 0.0, 1.0, "hi")],
        width=1080,
        height=1920,
        position={"x": 0.0, "y": 0.05, "w": 1.0, "h": 0.1},
    )
    assert _default_style_line(doc)[-5] == "8"


def test_build_ass_default_position_is_bottom_centre():
    doc = build_ass([cue(1, 0.0, 1.0, "hi")], width=1080, height=1920)
    fields = _default_style_line(doc)
    assert fields[-5] == "2"
    assert (fields[-4], fields[-3]) == ("40", "40")


def test_build_ass_ignores_malformed_position():
    doc = build_ass([cue(1, 0.0, 1.0, "hi")], position={"x": 0.1})  # missing keys
    assert _default_style_line(doc)[-5] == "2"  # falls back to the default


def test_engine_build_ass_threads_position():
    doc = CaptionEngine().build_ass([cue(1, 0.0, 1.0, "hi")], position={"x": 0.0, "y": 0.05, "w": 1.0, "h": 0.1})
    assert _default_style_line(doc)[-5] == "8"


def test_render_threads_position_into_ass(fake_ffmpeg, monkeypatch):
    written: dict[str, str] = {}
    captured: dict[str, str] = {}
    real_mkstemp = caption.tempfile.mkstemp

    def spy(*a, **k):
        fd, path = real_mkstemp(*a, **k)
        written["path"] = path
        return fd, path

    monkeypatch.setattr(caption.tempfile, "mkstemp", spy)

    def runner(argv, total_sec=0.0, on_progress=None, should_cancel=None):
        with open(written["path"], encoding="utf-8") as fh:
            captured["ass"] = fh.read()
        return 0

    CaptionEngine(runner=runner).render(
        "/in.mp4",
        [cue(1, 0.0, 1.0, "body")],
        "/out.mp4",
        position={"x": 0.0, "y": 0.05, "w": 1.0, "h": 0.1},
    )
    assert _default_style_line(captured["ass"])[-5] == "8"
