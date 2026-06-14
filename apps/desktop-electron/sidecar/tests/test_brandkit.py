"""Unit tests for media_studio.features.brandkit (P4 §8d brand kit export side).

The logo-overlay builder is PURE: ffmpeg argv/filter strings with no subprocess.
These tests pin the corner geometry, the second-input pattern (clip + logo), the
drained-run-ready argv shape, and the brand-default resolution (template/font
fill in ONLY when the user didn't override — immutable, never mutates the input).
"""
from __future__ import annotations

import pytest

from media_studio.features import brandkit


# --------------------------------------------------------------------------- #
# build_logo_overlay_filter — corner geometry
# --------------------------------------------------------------------------- #
def test_default_corner_is_top_right_padded() -> None:
    f = brandkit.build_logo_overlay_filter()
    # top-right: x = main_w-overlay_w-P, y = P
    assert f"overlay=main_w-overlay_w-{brandkit.DEFAULT_PADDING}:{brandkit.DEFAULT_PADDING}" in f


def test_each_corner_maps_to_distinct_xy() -> None:
    seen = set()
    for corner in brandkit.CORNERS:
        f = brandkit.build_logo_overlay_filter(corner=corner, padding=10)
        seen.add(f)
    assert len(seen) == len(brandkit.CORNERS)


def test_bottom_left_geometry() -> None:
    f = brandkit.build_logo_overlay_filter(corner="bottom-left", padding=20)
    assert "overlay=20:main_h-overlay_h-20" in f


def test_logo_scale_pct_scales_input_one() -> None:
    f = brandkit.build_logo_overlay_filter(logo_scale_pct=15.0)
    assert "[1:v]scale=iw*0.1500:-1[logo]" in f
    assert "[0:v][logo]overlay=" in f


def test_unknown_corner_rejected() -> None:
    with pytest.raises(ValueError):
        brandkit.build_logo_overlay_filter(corner="middle")


def test_negative_padding_rejected() -> None:
    with pytest.raises(ValueError):
        brandkit.build_logo_overlay_filter(padding=-1)


def test_non_positive_scale_rejected() -> None:
    with pytest.raises(ValueError):
        brandkit.build_logo_overlay_filter(logo_scale_pct=0.0)


# --------------------------------------------------------------------------- #
# build_logo_overlay_argv — the second-input runnable argv
# --------------------------------------------------------------------------- #
def test_argv_uses_two_inputs_clip_then_logo(monkeypatch) -> None:
    monkeypatch.setattr(
        "media_studio.ffmpeg.ffmpeg_path", lambda settings=None: "/bin/ffmpeg"
    )
    argv = brandkit.build_logo_overlay_argv("clip.mp4", "logo.png", "out.mp4")
    assert isinstance(argv, list)
    # input 0 = the clip, input 1 = the logo (the build_audio_mux_argv pattern).
    i_indices = [i for i, a in enumerate(argv) if a == "-i"]
    assert argv[i_indices[0] + 1] == "clip.mp4"
    assert argv[i_indices[1] + 1] == "logo.png"
    assert argv[-1] == "out.mp4"


def test_argv_is_drained_run_ready_and_copies_audio(monkeypatch) -> None:
    monkeypatch.setattr(
        "media_studio.ffmpeg.ffmpeg_path", lambda settings=None: "/bin/ffmpeg"
    )
    argv = brandkit.build_logo_overlay_argv("clip.mp4", "logo.png", "out.mp4")
    assert "-progress" in argv and "pipe:1" in argv and "-nostats" in argv
    assert "-filter_complex" in argv
    ai = argv.index("-c:a")
    assert argv[ai + 1] == "copy"  # audio passes through


def test_argv_loops_the_still_logo(monkeypatch) -> None:
    monkeypatch.setattr(
        "media_studio.ffmpeg.ffmpeg_path", lambda settings=None: "/bin/ffmpeg"
    )
    argv = brandkit.build_logo_overlay_argv("clip.mp4", "logo.png", "out.mp4")
    # -loop 1 + -shortest so a still PNG spans the clip and ends with the video.
    assert "-loop" in argv and "-shortest" in argv


def test_argv_requires_clip_and_logo(monkeypatch) -> None:
    monkeypatch.setattr(
        "media_studio.ffmpeg.ffmpeg_path", lambda settings=None: "/bin/ffmpeg"
    )
    with pytest.raises(ValueError):
        brandkit.build_logo_overlay_argv("", "logo.png", "out.mp4")
    with pytest.raises(ValueError):
        brandkit.build_logo_overlay_argv("clip.mp4", "", "out.mp4")


# --------------------------------------------------------------------------- #
# brand_logo_path / has_brand_logo
# --------------------------------------------------------------------------- #
def test_has_brand_logo_reflects_setting() -> None:
    assert brandkit.has_brand_logo({"brandLogoPath": "C:/logo.png"}) is True
    assert brandkit.has_brand_logo({"brandLogoPath": ""}) is False
    assert brandkit.has_brand_logo({}) is False
    assert brandkit.has_brand_logo(None) is False


def test_brand_logo_path_strips_whitespace() -> None:
    assert brandkit.brand_logo_path({"brandLogoPath": "  C:/logo.png  "}) == "C:/logo.png"


# --------------------------------------------------------------------------- #
# resolve_brand_defaults — defaults only, immutable
# --------------------------------------------------------------------------- #
def test_brand_template_fills_caption_style_when_unset() -> None:
    out = brandkit.resolve_brand_defaults({"brandCaptionTemplate": "hormozi"})
    assert out["captionStyle"] == "hormozi"


def test_brand_font_fills_caption_font_when_unset() -> None:
    out = brandkit.resolve_brand_defaults({"brandFontFamily": "Inter"})
    assert out["captionFontFamily"] == "Inter"


def test_user_caption_style_beats_brand_default() -> None:
    out = brandkit.resolve_brand_defaults(
        {"captionStyle": "neon", "brandCaptionTemplate": "hormozi"}
    )
    assert out["captionStyle"] == "neon"


def test_user_font_beats_brand_default() -> None:
    out = brandkit.resolve_brand_defaults(
        {"captionFontFamily": "Roboto", "brandFontFamily": "Inter"}
    )
    assert out["captionFontFamily"] == "Roboto"


def test_blank_brand_values_are_ignored() -> None:
    out = brandkit.resolve_brand_defaults(
        {"brandCaptionTemplate": "", "brandFontFamily": "   "}
    )
    assert "captionStyle" not in out
    assert "captionFontFamily" not in out


def test_resolve_is_immutable() -> None:
    src = {"brandCaptionTemplate": "hormozi"}
    out = brandkit.resolve_brand_defaults(src)
    assert out is not src
    assert "captionStyle" not in src  # the input was not mutated


def test_resolve_tolerates_none() -> None:
    assert brandkit.resolve_brand_defaults(None) == {}
