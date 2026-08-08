r"""Karaoke caption STYLING parity (v1.5 lane-karaoke).

``CaptionEngine.render(karaoke=True)`` used to call ``build_karaoke_ass`` with only
``cues``/``width``/``height``/``source_start``, silently dropping SIX styling
parameters that were in scope at the call site — ``override``, ``position``,
``hook_title``, ``total_sec``, ``hook_card`` and ``hook_card_sec``. Net effect: a
user picked a style + tuned it in the gallery and the karaoke renderer ignored
every setting, while the renderer's LIVE PREVIEW (``captionOverridePreview
.previewVisual`` folded onto ``KARAOKE_PRESET_VISUAL``) showed the tuned look. The
preview and the burn disagreed.

These tests are OUTPUT-level on purpose: each one proves the emitted ASS DIFFERS
between two settings (or matches an exact expected token), never merely that a
value reached a function. The no-override case is pinned byte-for-byte so the
teardown-verified OpusClip preset can never silently drift.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from media_studio import ffmpeg
from media_studio.features import caption
from media_studio.features import caption_karaoke as ck
from media_studio.features import hook_card as hc
from media_studio.features.caption import CaptionEngine

# --------------------------------------------------------------------------- #
# fixtures / helpers
# --------------------------------------------------------------------------- #
#: two aligned words so the karaoke builder emits two per-word Dialogue events.
KARAOKE_CUE: dict[str, Any] = {
    "index": 1,
    "start": 0.0,
    "end": 1.0,
    "text": "go now",
    "words": [
        {"text": "go", "start": 0.0, "end": 0.5},
        {"text": "now", "start": 0.5, "end": 1.0},
    ],
}


@pytest.fixture()
def fake_ffmpeg(monkeypatch, tmp_path: Path):
    """Make ffmpeg.ffmpeg_path resolve to a fake binary (no real ffmpeg)."""
    fake = tmp_path / "ffmpeg"
    fake.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(ffmpeg, "ffmpeg_path", lambda settings=None: str(fake))
    return str(fake)


def render_karaoke_ass(monkeypatch, **render_kw: Any) -> str:
    """The ASS document ``render(karaoke=True, **render_kw)`` hands to ffmpeg.

    Spies on the temp-file seam so the assertion is on the bytes libass would
    actually consume — the only place a dropped parameter is observable.
    """
    written: dict[str, str] = {}
    real_mkstemp = caption.tempfile.mkstemp

    def spy_mkstemp(*a: Any, **k: Any):
        fd, path = real_mkstemp(*a, **k)
        written["path"] = path
        return fd, path

    monkeypatch.setattr(caption.tempfile, "mkstemp", spy_mkstemp)

    captured: dict[str, str] = {}

    def runner(argv, total_sec=0.0, on_progress=None, should_cancel=None):
        captured["ass"] = Path(written["path"]).read_text(encoding="utf-8")
        return 0

    engine = CaptionEngine(runner=runner)
    engine.render("/in.mp4", [KARAOKE_CUE], "/out.mp4", karaoke=True, **render_kw)
    return captured["ass"]


def style_line(doc: str, name: str = "Default") -> str:
    """The single ``Style: <name>,...`` line in ``doc`` (fails loudly if absent)."""
    matches = [ln for ln in doc.splitlines() if ln.startswith(f"Style: {name},")]
    assert len(matches) == 1, f"expected exactly one Style: {name} line, got {matches}"
    return matches[0]


def event_lines(doc: str, name: str) -> list[str]:
    """Every ``Dialogue:`` line in ``doc`` that uses the ``name`` style."""
    return [ln for ln in doc.splitlines() if ln.startswith("Dialogue: ") and f",{name},," in ln]


# --------------------------------------------------------------------------- #
# THE REGRESSION: render(karaoke=True) must thread the styling parameters
# --------------------------------------------------------------------------- #
class TestRenderThreadsStyling:
    """Each case changes ONE render() styling argument and requires the ASS to move."""

    def test_two_different_overrides_produce_different_ass(self, fake_ffmpeg, monkeypatch):
        # The headline both-states proof: if the override is dropped, these are
        # byte-identical and the styling is unreachable from the gallery.
        red = render_karaoke_ass(monkeypatch, override={"textColor": "#FF0000"})
        blue = render_karaoke_ass(monkeypatch, override={"textColor": "#0000FF"})
        assert red != blue

    def test_override_font_reaches_the_style_line(self, fake_ffmpeg, monkeypatch):
        doc = render_karaoke_ass(monkeypatch, override={"fontFamily": "Bebas Neue"})
        assert style_line(doc).startswith("Style: Default,Bebas Neue,")

    def test_position_box_reaches_the_style_line(self, fake_ffmpeg, monkeypatch):
        boxed = render_karaoke_ass(monkeypatch, position={"x": 0.1, "y": 0.05, "w": 0.8, "h": 0.1})
        plain = render_karaoke_ass(monkeypatch)
        assert style_line(boxed) != style_line(plain)
        # top-anchored box: Alignment 8, MarginL/R 108, MarginV 96.
        assert style_line(boxed).endswith(",8,108,108,96,1")

    def test_hook_title_reaches_the_document(self, fake_ffmpeg, monkeypatch):
        doc = render_karaoke_ass(monkeypatch, hook_title="Watch this")
        assert style_line(doc, "HookTitle").startswith("Style: HookTitle,Arial,")
        assert event_lines(doc, "HookTitle") == ["Dialogue: 0,0:00:00.00,0:01:00.00,HookTitle,,0,0,0,,Watch this"]

    def test_total_sec_bounds_the_hook_title_span(self, fake_ffmpeg, monkeypatch):
        doc = render_karaoke_ass(monkeypatch, hook_title="Watch this", total_sec=12.0)
        assert event_lines(doc, "HookTitle") == ["Dialogue: 0,0:00:00.00,0:00:12.00,HookTitle,,0,0,0,,Watch this"]

    def test_hook_card_reaches_the_document(self, fake_ffmpeg, monkeypatch):
        doc = render_karaoke_ass(monkeypatch, hook_title="Watch this", hook_card=True, hook_card_sec=5.0)
        assert style_line(doc, hc.HOOK_CARD_STYLE_NAME) == hc.hook_card_style_line(1080, 1920)
        assert event_lines(doc, hc.HOOK_CARD_STYLE_NAME) == [
            "Dialogue: 0,0:00:00.00,0:00:05.00,HookCard,,0,0,0,,Watch this"
        ]
        # the card REPLACES the plain headline style (never both).
        assert "Style: HookTitle," not in doc

    def test_hook_card_sec_bounds_the_card(self, fake_ffmpeg, monkeypatch):
        doc = render_karaoke_ass(monkeypatch, hook_title="Watch this", hook_card=True, hook_card_sec=2.0)
        assert event_lines(doc, hc.HOOK_CARD_STYLE_NAME) == [
            "Dialogue: 0,0:00:00.00,0:00:02.00,HookCard,,0,0,0,,Watch this"
        ]

    def test_no_styling_args_keeps_the_preset_look(self, fake_ffmpeg, monkeypatch):
        # Back-compat keystone: an un-tuned karaoke render is byte-identical to the
        # teardown-verified preset the pure builder emits.
        doc = render_karaoke_ass(monkeypatch)
        assert doc == ck.build_karaoke_ass([KARAOKE_CUE])


# --------------------------------------------------------------------------- #
# resolve_karaoke_style — the override merged onto the KARAOKE base
# --------------------------------------------------------------------------- #
class TestResolveKaraokeStyle:
    def test_empty_override_is_the_preset(self):
        for empty in (None, {}):
            resolved = ck.resolve_karaoke_style(empty)
            assert resolved.font_name == ck.KARAOKE_FONT
            assert resolved.size_scale == 1.0
            assert resolved.primary_color == ck.KARAOKE_FILL
            assert resolved.secondary_color == ck.KARAOKE_FILL
            assert resolved.outline_color == ck.KARAOKE_OUTLINE
            assert resolved.back_color == ck.KARAOKE_BACK
            assert resolved.border_style == ck.KARAOKE_BORDER_STYLE
            assert resolved.outline_width == ck.KARAOKE_OUTLINE_WIDTH
            assert resolved.shadow == ck.KARAOKE_SHADOW
            assert resolved.active_colors == ck.KARAOKE_ACTIVE_INLINE
            # tri-state: absent, so the caller's own default wins.
            assert resolved.uppercase is None
            assert resolved.position_band is None

    def test_font_must_be_in_the_curated_allowlist(self):
        assert ck.resolve_karaoke_style({"fontFamily": "Oswald"}).font_name == "Oswald"
        # an off-allowlist face would not exist in the burn fontconfig set -> preset.
        assert ck.resolve_karaoke_style({"fontFamily": "Comic Sans MS"}).font_name == ck.KARAOKE_FONT

    def test_size_scale_is_clamped(self):
        assert ck.resolve_karaoke_style({"sizeScale": 1.5}).size_scale == 1.5
        assert ck.resolve_karaoke_style({"sizeScale": 99.0}).size_scale == 1.8
        assert ck.resolve_karaoke_style({"sizeScale": 0.01}).size_scale == 0.6
        assert ck.resolve_karaoke_style({"sizeScale": "big"}).size_scale == 1.0

    def test_text_color_becomes_the_fill(self):
        resolved = ck.resolve_karaoke_style({"textColor": "#FF0000"})
        assert resolved.primary_color == "&H000000FF"
        assert resolved.secondary_color == "&H000000FF"

    def test_spoken_color_is_the_fill_fallback(self):
        # Mirrors caption_override.apply_override: textColor wins, else spokenColor.
        assert ck.resolve_karaoke_style({"spokenColor": "#00FF00"}).primary_color == "&H0000FF00"
        both = ck.resolve_karaoke_style({"textColor": "#FF0000", "spokenColor": "#00FF00"})
        assert both.primary_color == "&H000000FF"

    def test_bad_hex_keeps_the_preset_fill(self):
        assert ck.resolve_karaoke_style({"textColor": "red"}).primary_color == ck.KARAOKE_FILL

    def test_active_color_collapses_the_alternation(self):
        # An explicit active colour is a deliberate single accent; alternating it
        # against the preset green would defeat the setting.
        resolved = ck.resolve_karaoke_style({"activeColor": "#FF00FF"})
        assert resolved.active_colors == ("&H00FF00FF&", "&H00FF00FF&")

    def test_bad_active_hex_keeps_the_alternation(self):
        assert ck.resolve_karaoke_style({"activeColor": "nope"}).active_colors == ck.KARAOKE_ACTIVE_INLINE

    @pytest.mark.parametrize(
        ("override", "expected"),
        [
            ({}, (ck.KARAOKE_BORDER_STYLE, ck.KARAOKE_OUTLINE_WIDTH)),
            ({"box": True}, (3, ck.KARAOKE_OUTLINE_WIDTH)),
            ({"outline": True}, (1, ck.KARAOKE_OUTLINE_WIDTH)),
            ({"outline": False}, (1, 0)),
            # a solid card and a pure outline are exclusive — the card wins.
            ({"box": True, "outline": False}, (3, ck.KARAOKE_OUTLINE_WIDTH)),
            ({"box": False}, (ck.KARAOKE_BORDER_STYLE, ck.KARAOKE_OUTLINE_WIDTH)),
        ],
    )
    def test_border_resolution_keeps_the_thick_karaoke_outline(self, override, expected):
        resolved = ck.resolve_karaoke_style(override)
        assert (resolved.border_style, resolved.outline_width) == expected

    def test_uppercase_is_tri_state(self):
        assert ck.resolve_karaoke_style({"uppercase": True}).uppercase is True
        assert ck.resolve_karaoke_style({"uppercase": False}).uppercase is False
        assert ck.resolve_karaoke_style({"uppercase": "yes"}).uppercase is None

    def test_position_band_must_be_known(self):
        assert ck.resolve_karaoke_style({"positionBand": "top"}).position_band == "top"
        assert ck.resolve_karaoke_style({"positionBand": "sideways"}).position_band is None


# --------------------------------------------------------------------------- #
# build_karaoke_ass — every threaded parameter must MOVE the output
# --------------------------------------------------------------------------- #
class TestBuildKaraokeAssStyling:
    def test_preset_style_line_is_pinned(self):
        # The drift guard for the whole feature: 1920*0.05 = 96 px, 1080*0.06 = 65
        # px side margins, 1920*0.18 = 346 px up from the bottom, Alignment 2.
        assert style_line(ck.build_karaoke_ass([KARAOKE_CUE])) == (
            "Style: Default,Anton,96,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,"
            "-1,0,0,0,100,100,0,0,1,4,2,2,65,65,346,1"
        )

    def test_size_scale_scales_the_font(self):
        doc = ck.build_karaoke_ass([KARAOKE_CUE], override={"sizeScale": 1.5})
        assert style_line(doc).startswith("Style: Default,Anton,144,")

    def test_size_scale_never_goes_below_the_floor(self):
        doc = ck.build_karaoke_ass([KARAOKE_CUE], height=100, override={"sizeScale": 0.6})
        # 100*0.05 = 5 -> floored to 12, then 12*0.6 = 7.2 -> floored to 12 again.
        assert style_line(doc).startswith("Style: Default,Anton,12,")

    def test_text_color_changes_the_primary_colour(self):
        doc = ck.build_karaoke_ass([KARAOKE_CUE], override={"textColor": "#FF0000"})
        assert ",&H000000FF,&H000000FF," in style_line(doc)

    def test_active_color_changes_the_inline_accent(self):
        doc = ck.build_karaoke_ass([KARAOKE_CUE], override={"activeColor": "#FF00FF"})
        assert r"{\1c&H00FF00FF&\t(0,120,\fscx115\fscy115)}GO{\r}" in doc
        # both words now use the SAME accent (the alternation is collapsed).
        assert ck.KARAOKE_ACTIVE_INLINE[1] not in doc

    def test_box_switches_to_an_opaque_card(self):
        doc = ck.build_karaoke_ass([KARAOKE_CUE], override={"box": True})
        assert ",100,100,0,0,3,4,2," in style_line(doc)

    def test_outline_off_drops_the_stroke_width(self):
        doc = ck.build_karaoke_ass([KARAOKE_CUE], override={"outline": False})
        assert ",100,100,0,0,1,0,2," in style_line(doc)

    def test_uppercase_off_keeps_the_transcript_casing(self):
        doc = ck.build_karaoke_ass([KARAOKE_CUE], override={"uppercase": False})
        assert "go" in doc
        assert "GO" not in doc

    def test_override_position_band_beats_the_explicit_default(self):
        doc = ck.build_karaoke_ass([KARAOKE_CUE], override={"positionBand": "top"})
        # top band: Alignment 8, MarginV 1920*0.10 = 192.
        assert style_line(doc).endswith(",8,65,65,192,1")

    def test_explicit_position_band_still_works(self):
        doc = ck.build_karaoke_ass([KARAOKE_CUE], position_band="center")
        assert style_line(doc).endswith(",5,65,65,0,1")

    def test_position_box_sets_alignment_and_margins(self):
        doc = ck.build_karaoke_ass([KARAOKE_CUE], position={"x": 0.1, "y": 0.05, "w": 0.8, "h": 0.1})
        assert style_line(doc).endswith(",8,108,108,96,1")

    def test_malformed_position_box_falls_back_to_the_band(self):
        doc = ck.build_karaoke_ass([KARAOKE_CUE], position={"x": "nope"})
        assert style_line(doc).endswith(",2,65,65,346,1")

    def test_override_band_re_anchors_but_keeps_the_box_side_margins(self):
        doc = ck.build_karaoke_ass(
            [KARAOKE_CUE],
            position={"x": 0.2, "y": 0.7, "w": 0.6, "h": 0.2},
            override={"positionBand": "top"},
        )
        # band wins on Alignment + MarginV; the box keeps the fine L/R offset.
        assert style_line(doc).endswith(",8,216,216,192,1")

    def test_hook_title_adds_a_headline_style_and_event(self):
        doc = ck.build_karaoke_ass([KARAOKE_CUE], hook_title="Watch this")
        assert style_line(doc, "HookTitle") == (
            "Style: HookTitle,Arial,106,&H00FFFFFF,&H000000FF,&H00000000,&H96000000,"
            "-1,0,0,0,100,100,0,0,1,4,2,8,60,60,134,1"
        )
        assert event_lines(doc, "HookTitle") == ["Dialogue: 0,0:00:00.00,0:01:00.00,HookTitle,,0,0,0,,Watch this"]

    def test_blank_hook_title_adds_nothing(self):
        assert ck.build_karaoke_ass([KARAOKE_CUE], hook_title="   ") == ck.build_karaoke_ass([KARAOKE_CUE])

    def test_hook_title_is_escaped(self):
        doc = ck.build_karaoke_ass([KARAOKE_CUE], hook_title=r"{\fake}pwn")
        assert r"{\fake}" not in doc

    def test_hook_card_replaces_the_headline(self):
        doc = ck.build_karaoke_ass([KARAOKE_CUE], hook_title="Watch this", hook_card=True, hook_card_sec=5.0)
        assert style_line(doc, hc.HOOK_CARD_STYLE_NAME) == hc.hook_card_style_line(1080, 1920)
        assert "Style: HookTitle," not in doc

    def test_hook_card_is_capped_to_the_clip(self):
        doc = ck.build_karaoke_ass(
            [KARAOKE_CUE],
            hook_title="Watch this",
            hook_card=True,
            hook_card_sec=5.0,
            total_sec=3.0,
        )
        assert event_lines(doc, hc.HOOK_CARD_STYLE_NAME) == [
            "Dialogue: 0,0:00:00.00,0:00:03.00,HookCard,,0,0,0,,Watch this"
        ]

    def test_the_karaoke_effects_survive_a_full_override(self):
        # A tuned karaoke render keeps its word-by-word reveal + scale-pop; only
        # the flat visual fields move.
        doc = ck.build_karaoke_ass(
            [KARAOKE_CUE],
            override={
                "fontFamily": "Oswald",
                "sizeScale": 1.2,
                "textColor": "#101010",
                "activeColor": "#FF00FF",
                "box": True,
                "uppercase": False,
                "positionBand": "center",
            },
        )
        assert r"\t(0,120,\fscx115\fscy115)" in doc
        assert len(event_lines(doc, "Default")) == 2
