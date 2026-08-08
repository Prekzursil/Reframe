"""PURE N-window b-roll compositing argv tests (v1.5 flagship #3, WU BR5).

The design calls this the highest-risk surface in the feature: arg order,
per-window enable gates, the b-roll's own timebase, and the audio map all have
to be right at once, and a filtergraph that is merely *plausible* renders
garbage. So these tests assert the EXACT argv and the EXACT filter_complex
string rather than "contains overlay" — a builder is a pure function and
deserves an exact oracle.

What a green run here does NOT prove: that ffmpeg accepts the graph or produces
the pixels. That needs the real-ffmpeg tier (WU BR8) and is NOT covered on this
branch.
"""

from __future__ import annotations

import pytest
from media_studio.features import broll_compose as bc

CLIP = "/videos/talk.mp4"
OUT = "/exports/talk.broll.mp4"


def _ins(start: float, end: float, path: str, kind: str = "image", layout: str = "cutaway", source_start: float = 0.0):
    return {
        "start": start,
        "end": end,
        "duration": end - start,
        "sourceStart": source_start,
        "assetId": "a1",
        "path": path,
        "kind": kind,
        "score": 0.9,
        "reason": "r",
        "layout": layout,
        "segmentIndex": 0,
    }


# --------------------------------------------------------------------------- #
# inputs — a still is looped and bounded; a clip is seeked and bounded
# --------------------------------------------------------------------------- #
def test_still_input_is_looped_and_time_bounded():
    assert bc.build_input_args([_ins(10.0, 14.0, "/lib/city.png")]) == [
        "-loop",
        "1",
        "-t",
        "4.000",
        "-i",
        "/lib/city.png",
    ]


def test_video_input_is_seeked_to_its_own_offset_and_bounded():
    ins = _ins(10.0, 14.0, "/lib/dog.mp4", kind="video", source_start=2.5)
    assert bc.build_input_args([ins]) == ["-ss", "2.500", "-t", "4.000", "-i", "/lib/dog.mp4"]


def test_inputs_are_emitted_in_insertion_order():
    args = bc.build_input_args([_ins(1.0, 3.0, "/a.png"), _ins(9.0, 12.0, "/b.png")])
    assert args.index("/a.png") < args.index("/b.png")


# --------------------------------------------------------------------------- #
# filtergraph — the exact string, for each layout
# --------------------------------------------------------------------------- #
def test_cutaway_filtergraph_is_exact():
    got = bc.build_filtergraph([_ins(10.0, 14.0, "/lib/city.png")])
    assert got == (
        "[1:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
        "setpts=PTS-STARTPTS+10.000/TB[b0];"
        "[0:v][b0]overlay=0:0:eof_action=pass:enable='between(t,10.000,14.000)'[v0];"
        "[v0]format=yuv420p[vout]"
    )


def test_pip_filtergraph_insets_into_a_corner_at_an_even_width():
    got = bc.build_filtergraph([_ins(10.0, 14.0, "/lib/city.png", layout="pip")])
    # 1080 * 0.34 = 367.2 -> 367 -> rounded DOWN to an even 366 (libx264 needs
    # even dimensions; -2 keeps the height even too).
    assert got == (
        "[1:v]scale=366:-2,setpts=PTS-STARTPTS+10.000/TB[b0];"
        "[0:v][b0]overlay=main_w-overlay_w-48:48:eof_action=pass:enable='between(t,10.000,14.000)'[v0];"
        "[v0]format=yuv420p[vout]"
    )


def test_pip_corner_expression_comes_from_the_brandkit_table():
    from media_studio.features import brandkit

    got = bc.build_filtergraph([_ins(1.0, 3.0, "/a.png", layout="pip")], pip_corner="bottom-left")
    assert brandkit._corner_xy("bottom-left", bc.DEFAULT_PIP_PADDING) in got


def test_n_windows_chain_in_one_pass():
    got = bc.build_filtergraph([_ins(1.0, 3.0, "/a.png"), _ins(9.0, 12.0, "/b.png", layout="pip")])
    # Two inputs, two overlay stages, one chained video label per stage.
    assert got.count("overlay=") == 2
    assert "[1:v]" in got and "[2:v]" in got
    assert "[0:v][b0]" in got and "[v0][b1]" in got
    assert got.endswith("[v1]format=yuv420p[vout]")


def test_each_window_carries_its_own_enable_gate():
    got = bc.build_filtergraph([_ins(1.0, 3.0, "/a.png"), _ins(9.0, 12.0, "/b.png")])
    assert "enable='between(t,1.000,3.000)'" in got
    assert "enable='between(t,9.000,12.000)'" in got


def test_filtergraph_honours_a_custom_canvas():
    got = bc.build_filtergraph([_ins(1.0, 3.0, "/a.png")], canvas_w=1920, canvas_h=1080)
    assert "scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080" in got


def test_filtergraph_rejects_an_unknown_layout():
    with pytest.raises(ValueError, match="layout"):
        bc.build_filtergraph([_ins(1.0, 3.0, "/a.png", layout="ken-burns")])


def test_filtergraph_rejects_an_empty_plan():
    with pytest.raises(ValueError, match="at least one"):
        bc.build_filtergraph([])


def test_pip_scale_must_be_positive():
    with pytest.raises(ValueError, match="pipScalePct"):
        bc.build_filtergraph([_ins(1.0, 3.0, "/a.png", layout="pip")], pip_scale_pct=0.0)


def test_a_tiny_pip_scale_still_yields_a_legal_even_width():
    got = bc.build_filtergraph([_ins(1.0, 3.0, "/a.png", layout="pip")], pip_scale_pct=0.01)
    assert "scale=2:-2," in got


# --------------------------------------------------------------------------- #
# argv — the full command, in order, list-only
# --------------------------------------------------------------------------- #
@pytest.fixture
def _pinned_ffmpeg(monkeypatch):
    """Pin the resolved binary (the test_brandkit.py:62 pattern).

    ``ffmpeg.ffmpeg_path`` goes through ``resolve_binary``, which PROBES the
    host — so a real path leaks in and the argv is not comparable. Pinning it is
    what makes an exact-argv oracle possible at all.
    """
    monkeypatch.setattr("media_studio.ffmpeg.ffmpeg_path", lambda settings=None: "/bin/ffmpeg")


def test_argv_is_exact(_pinned_ffmpeg):
    argv = bc.build_broll_argv(CLIP, [_ins(10.0, 14.0, "/lib/city.png")], OUT)
    assert argv == [
        "/bin/ffmpeg",
        "-hide_banner",
        "-nostdin",
        "-y",
        "-i",
        CLIP,
        "-loop",
        "1",
        "-t",
        "4.000",
        "-i",
        "/lib/city.png",
        "-filter_complex",
        bc.build_filtergraph([_ins(10.0, 14.0, "/lib/city.png")]),
        "-map",
        "[vout]",
        "-map",
        "0:a?",
        "-c:v",
        "libx264",
        "-c:a",
        "copy",
        "-progress",
        "pipe:1",
        "-nostats",
        OUT,
    ]


def test_argv_keeps_the_speakers_audio_and_never_maps_the_broll_audio(_pinned_ffmpeg):
    argv = bc.build_broll_argv(CLIP, [_ins(1.0, 3.0, "/lib/dog.mp4", kind="video")], OUT)
    maps = [argv[i + 1] for i, tok in enumerate(argv) if tok == "-map"]
    # Exactly the composited video and the MAIN input's audio. A b-roll audio
    # stream is muted by construction: it is simply never mapped.
    assert maps == ["[vout]", "0:a?"]
    assert "1:a" not in maps and "1:a?" not in maps


def test_argv_requires_a_clip_path():
    with pytest.raises(ValueError, match="clip path"):
        bc.build_broll_argv("", [_ins(1.0, 3.0, "/a.png")], OUT)


def test_argv_requires_an_output_path():
    with pytest.raises(ValueError, match="output path"):
        bc.build_broll_argv(CLIP, [_ins(1.0, 3.0, "/a.png")], "")


def test_argv_requires_a_non_empty_plan():
    with pytest.raises(ValueError, match="at least one"):
        bc.build_broll_argv(CLIP, [], OUT)


def test_argv_rejects_an_insertion_without_a_path():
    with pytest.raises(ValueError, match="asset path"):
        bc.build_broll_argv(CLIP, [_ins(1.0, 3.0, "")], OUT)


def test_argv_rejects_a_non_positive_duration():
    with pytest.raises(ValueError, match="duration"):
        bc.build_broll_argv(CLIP, [_ins(3.0, 3.0, "/a.png")], OUT)


def test_argv_is_a_list_of_strings_only(_pinned_ffmpeg):
    argv = bc.build_broll_argv(CLIP, [_ins(1.0, 3.0, "/a.png")], OUT)
    assert isinstance(argv, list)
    assert all(isinstance(token, str) for token in argv)


def test_argv_resolves_ffmpeg_through_the_shared_seam(monkeypatch):
    # The binary is NOT read straight out of settings — it goes through
    # ffmpeg.resolve_binary, the one place that knows about bundled/PATH/settings
    # precedence. Assert the seam is the thing being called.
    seen: list[object] = []
    monkeypatch.setattr(
        "media_studio.ffmpeg.ffmpeg_path",
        lambda settings=None: seen.append(settings) or "/opt/bin/ffmpeg",
    )
    argv = bc.build_broll_argv(CLIP, [_ins(1.0, 3.0, "/a.png")], OUT, settings={"ffmpegPath": "/opt/bin/ffmpeg"})
    assert argv[0] == "/opt/bin/ffmpeg"
    assert seen == [{"ffmpegPath": "/opt/bin/ffmpeg"}]


def test_duration_falls_back_to_end_minus_start_when_absent(_pinned_ffmpeg):
    # A hand-written plan (or one round-tripped through a trimming schema) may
    # carry only the window, not a precomputed duration.
    bare = {"start": 4.0, "end": 7.5, "path": "/a.png", "kind": "image", "layout": "cutaway"}
    argv = bc.build_broll_argv(CLIP, [bare], OUT)
    assert argv[argv.index("-t") + 1] == "3.500"
