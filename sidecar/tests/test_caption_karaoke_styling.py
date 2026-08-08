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
from media_studio.features import caption_override as co
from media_studio.features import caption_polish as cp
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

    def test_base_font_stays_off_the_allowlist(self):
        # LOAD-BEARING for resolve_karaoke_style: it detects "fontFamily untouched"
        # by comparing apply_override's result to caption_override.BASE_FONT. That
        # sentinel is only unambiguous while BASE_FONT is NOT a font a user can pick.
        # Adding "Arial" to CURATED_CAPTION_FONTS would make an explicit Arial pick
        # silently render as Anton — so this fails the day that happens, pointing here.
        assert co.BASE_FONT not in co.CURATED_CAPTION_FONTS
        assert ck.KARAOKE_FONT in co.CURATED_CAPTION_FONTS

    def test_size_scale_is_clamped(self):
        assert ck.resolve_karaoke_style({"sizeScale": 1.5}).size_scale == 1.5
        assert ck.resolve_karaoke_style({"sizeScale": 99.0}).size_scale == 1.8
        assert ck.resolve_karaoke_style({"sizeScale": 0.01}).size_scale == 0.6
        assert ck.resolve_karaoke_style({"sizeScale": "big"}).size_scale == 1.0

    def test_text_color_becomes_the_fill(self):
        resolved = ck.resolve_karaoke_style({"textColor": "#FF0000"})
        assert resolved.primary_color == "&H000000FF"
        assert resolved.secondary_color == "&H000000FF"

    def test_spoken_color_is_a_separate_role_not_the_fill(self):
        # spokenColor paints ALREADY-SPOKEN words only — the third state the preview
        # implements at CaptionOverlay.wordColor:162
        # (`if (word.spoken) return visual.spokenColor || visual.textColor`).
        # It must NOT be folded into the whole-line fill: with textColor also set the
        # burn would discard it, and with only spokenColor set every not-yet-spoken
        # word would wrongly take it too.
        spoken_only = ck.resolve_karaoke_style({"spokenColor": "#00FF00"})
        assert spoken_only.primary_color == ck.KARAOKE_FILL  # fill untouched
        assert spoken_only.spoken_color == "&H0000FF00&"  # inline form, own role

        both = ck.resolve_karaoke_style({"textColor": "#FF0000", "spokenColor": "#00FF00"})
        assert both.primary_color == "&H000000FF"
        assert both.spoken_color == "&H0000FF00&"  # NOT discarded

        assert ck.resolve_karaoke_style({}).spoken_color is None  # no persistent state
        assert ck.resolve_karaoke_style({"spokenColor": "bad"}).spoken_color is None

    def test_spoken_words_get_the_spoken_colour_in_the_events(self):
        # Within one per-word event the words BEFORE the active one are already
        # spoken; they must carry the spoken accent, and the ones after must not.
        doc = ck.build_karaoke_ass([KARAOKE_CUE], override={"spokenColor": "#00FF00"})
        events = event_lines(doc, "Default")
        # event 0: "GO" active, "NOW" not yet spoken -> no spoken accent anywhere.
        assert r"{\1c&H0000FF00&}" not in events[0]
        # event 1: "NOW" active, "GO" already spoken -> GO carries the spoken accent.
        assert r"{\1c&H0000FF00&}GO{\r}" in events[1]

    def test_spoken_colour_is_absent_without_the_override(self):
        doc = ck.build_karaoke_ass([KARAOKE_CUE])
        # Un-tuned: already-spoken words reset to the white Style fill, matching
        # KARAOKE_PRESET_VISUAL.spokenColor === textColor in the renderer mirror.
        assert event_lines(doc, "Default")[1] == (
            "Dialogue: 0,0:00:00.50,0:00:01.00,Default,,0,0,0,,"
            r"GO {\1c&H0000FF00&\t(0,120,\fscx115\fscy115)}NOW{\r}"
        )

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
        # The box is chosen so its OWN MarginV differs from the band's: bottom edge
        # at y+h = 0.8 -> (1 - 0.8) * 1920 = 384, whereas band "top" -> 0.10 * 1920
        # = 192. With y = 0.7 both come to 192 and the assertion below would pass
        # even if MarginV had come from the box — proving only the Alignment flip.
        box = {"x": 0.2, "y": 0.6, "w": 0.6, "h": 0.2}
        without_band = ck.build_karaoke_ass([KARAOKE_CUE], position=box)
        assert style_line(without_band).endswith(",2,216,216,384,1")

        doc = ck.build_karaoke_ass([KARAOKE_CUE], position=box, override={"positionBand": "top"})
        # band wins on Alignment + MarginV (8 / 192); the box keeps the L/R offset.
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


# --------------------------------------------------------------------------- #
# DoD guard: EVERY settable CaptionOverride field, enumerated
# --------------------------------------------------------------------------- #
#: Every field of the renderer's ``CaptionOverride`` interface
#: (``app/renderer/src/lib/captionOverride.ts:27-50``), with two distinguishable
#: values. Adding a field there without wiring it here makes this go RED — which is
#: the point: a silent drop is exactly the defect this module exists to prevent.
OVERRIDE_FIELD_CASES: list[tuple[str, Any, Any]] = [
    ("fontFamily", "Anton", "Bebas Neue"),
    ("sizeScale", 0.8, 1.6),
    ("textColor", "#FF0000", "#0000FF"),
    ("activeColor", "#FF00FF", "#00FFFF"),
    ("spokenColor", "#123456", "#654321"),
    ("outline", True, False),
    ("box", True, False),
    ("uppercase", True, False),
    ("positionBand", "top", "bottom"),
    ("maxLines", 1, 2),
    ("maxCps", 10, 30),
]

#: The only fields that legitimately do NOT change the karaoke ASS. They shape the
#: SOFT-SUBTITLE route only (`caption_polish.polish_cues` -> its single production
#: caller `subtitles.generate_polished`); the burn's cue list comes from
#: `shortmaker._cues_for_clip`, which never calls it. `caption.build_ass` ignores
#: them identically, so this is engine-SYMMETRIC and pre-existing, not a karaoke
#: drop. Guarded by :meth:`…test_upstream_fields_are_not_on_either_burn_path`.
UPSTREAM_ONLY_FIELDS = frozenset({"maxLines", "maxCps"})


class TestEverySettableFieldReachesTheBurn:
    """The Definition of Done, enumerated field by field."""

    @pytest.mark.parametrize(("field", "value_a", "value_b"), OVERRIDE_FIELD_CASES)
    def test_field_moves_the_ass_unless_it_is_an_upstream_field(self, field: str, value_a: Any, value_b: Any) -> None:
        doc_a = ck.build_karaoke_ass([KARAOKE_CUE], override={field: value_a})
        doc_b = ck.build_karaoke_ass([KARAOKE_CUE], override={field: value_b})
        if field in UPSTREAM_ONLY_FIELDS:
            assert doc_a == doc_b, f"{field} unexpectedly reached the karaoke ASS"
        else:
            assert doc_a != doc_b, f"{field} is SILENTLY DROPPED by the karaoke renderer"

    def test_upstream_fields_are_not_on_either_burn_path(self) -> None:
        # The exemption's REAL justification is SYMMETRY: neither libass burn path
        # consumes these, so karaoke is not dropping anything the normal path keeps.
        #
        # (An earlier version asserted `resolve_caption_limits` reads them and called
        # that proof they were "consumed upstream of all three engines". REFUTED:
        # `polish_cues` appears nowhere in shortmaker.py — its only production caller
        # is `subtitles.generate_polished` via handlers/media_ops.py:53, the
        # soft-subtitle route. Reading that function proved nothing about the burn.)
        for field, value in (("maxCps", 11), ("maxLines", 1)):
            assert caption.build_ass([KARAOKE_CUE], override={field: value}) == caption.build_ass([KARAOKE_CUE]), (
                f"build_ass now honours {field}, so karaoke dropping it IS an asymmetry"
            )

        # They are live on the soft-subtitle route that does own them.
        assert cp.resolve_caption_limits({"captionOverride": {"maxCps": 11, "maxLines": 1}}) == (11.0, 1)
        assert cp.resolve_caption_limits({}) != (11.0, 1)

    @pytest.mark.parametrize("malformed", [[1, 2], "an-override", 7, 0.5, True])
    def test_a_non_mapping_override_degrades_instead_of_raising(self, malformed: Any) -> None:
        # `captionOverride` is an UNTRUSTED wire value: shortmaker passes
        # `settings.get("captionOverride")` straight through (shortmaker.py:441).
        # apply_override's docstring promises a malformed override "degrades
        # field-by-field ... never raises", so a non-Mapping must behave like an
        # absent one on BOTH libass paths, not crash the render with AttributeError.
        assert ck.build_karaoke_ass([KARAOKE_CUE], override=malformed) == ck.build_karaoke_ass([KARAOKE_CUE])
        assert caption.build_ass([KARAOKE_CUE], override=malformed) == caption.build_ass([KARAOKE_CUE])
        assert co.apply_override(malformed) == co.apply_override(None)

    @pytest.mark.parametrize(
        "override",
        [
            None,
            {},
            # a present override whose OTHER fields are absent must not disturb the
            # preset — the trap `ResolvedCaptionStyle` would have sprung by resolving
            # the outline against the libass-normal base and thinning it 4 -> 3.
            {"uppercase": True},
            {"maxCps": 17},
            {"fontFamily": "not-a-curated-font"},
            {"textColor": "not-a-hex"},
        ],
    )
    def test_untouched_fields_keep_the_preset_byte_for_byte(self, override: Any) -> None:
        assert ck.build_karaoke_ass([KARAOKE_CUE], override=override) == ck.build_karaoke_ass([KARAOKE_CUE])
