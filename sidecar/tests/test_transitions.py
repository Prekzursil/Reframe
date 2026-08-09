"""Unit tests for the boundary-TRANSITION filtergraph builders (v1.5 transitions lane).

PURE: every function under test is an argv/string builder over plain numbers — no
subprocess, no ffmpeg, no filesystem. The engine adapter that CALLS these (and the
one impure ffmpeg run) is covered separately in ``test_director_op_engines.py``
through the injected fake runner.

The spec these tests pin, in one sentence: a transition OVERLAPS two clips by
``duration``, so unlike ``join``/concat (which SUMS durations) the output is
``sum(parts) - boundaries * duration`` and it can NEVER be stream-copied.
"""

from __future__ import annotations

from typing import Any

import pytest
from media_studio.features import transitions as tr

# --------------------------------------------------------------------------- #
# vocabulary
# --------------------------------------------------------------------------- #


def test_styles_map_to_real_xfade_transition_names() -> None:
    # Our ids are camelCase (wire/UI friendly); the VALUES are the literal ffmpeg
    # xfade transition names, which are lowercase and must never drift.
    assert tr.TRANSITION_STYLES["dissolve"] == "fade"
    assert tr.TRANSITION_STYLES["fadeBlack"] == "fadeblack"
    assert tr.TRANSITION_STYLES["wipeLeft"] == "wipeleft"
    assert all(name.islower() and name.isalpha() for name in tr.TRANSITION_STYLES.values())
    assert tr.DEFAULT_STYLE in tr.TRANSITION_STYLES


def test_style_ids_is_a_sorted_tuple_of_the_mapping_keys() -> None:
    assert tuple(sorted(tr.TRANSITION_STYLES)) == tr.STYLE_IDS


@pytest.mark.parametrize("style", ["dissolve", "fadeBlack", "wipeLeft", "slideRight"])
def test_normalize_style_accepts_known_ids(style: str) -> None:
    assert tr.normalize_style(style) == tr.TRANSITION_STYLES[style]


def test_normalize_style_defaults_when_absent() -> None:
    assert tr.normalize_style(None) == tr.TRANSITION_STYLES[tr.DEFAULT_STYLE]


@pytest.mark.parametrize("bad", ["starWipe", "", 7, ["dissolve"]])
def test_normalize_style_rejects_unknown(bad: Any) -> None:
    # An unknown style is a REJECT, never a silent fallback: a user who asked for
    # a star wipe must not silently receive a cross-dissolve.
    with pytest.raises(tr.TransitionError, match="unknown transition style"):
        tr.normalize_style(bad)


# --------------------------------------------------------------------------- #
# duration
# --------------------------------------------------------------------------- #


def test_normalize_duration_defaults_and_clamps() -> None:
    assert tr.normalize_duration_ms(None) == tr.DEFAULT_DURATION_MS
    assert tr.normalize_duration_ms(750) == 750
    assert tr.normalize_duration_ms(1) == tr.MIN_DURATION_MS
    assert tr.normalize_duration_ms(10_000_000) == tr.MAX_DURATION_MS
    assert tr.normalize_duration_ms(400.6) == 400  # truncates toward zero


@pytest.mark.parametrize("bad", ["500ms", [500], {}, True])
def test_normalize_duration_rejects_non_numeric(bad: Any) -> None:
    # `True` is an int subclass in Python — a bool is NOT a duration, so it must
    # be rejected rather than quietly becoming 1ms -> clamped to the floor.
    with pytest.raises(tr.TransitionError, match="transition duration"):
        tr.normalize_duration_ms(bad)


# --------------------------------------------------------------------------- #
# offset math — the heart of xfade
# --------------------------------------------------------------------------- #


def test_offsets_for_a_single_boundary() -> None:
    # Two 10s clips with a 1s transition: the xfade starts at 10 - 1 = 9s.
    assert tr.xfade_offsets([10.0, 10.0], 1.0) == pytest.approx([9.0])


def test_offsets_accumulate_across_boundaries() -> None:
    # Three clips 10/20/30 with D=2. Boundary 0 at 10-2=8. After it the running
    # output is 10+20-2=28, so boundary 1 sits at 28-2=26.
    assert tr.xfade_offsets([10.0, 20.0, 30.0], 2.0) == pytest.approx([8.0, 26.0])


def test_total_duration_subtracts_every_overlap() -> None:
    # THE distinguishing fact vs concat: overlaps are SUBTRACTED, not summed.
    assert tr.total_duration_sec([10.0, 20.0, 30.0], 2.0) == pytest.approx(56.0)
    assert tr.total_duration_sec([10.0, 10.0], 1.0) == pytest.approx(19.0)


def test_offsets_reject_fewer_than_two_clips() -> None:
    with pytest.raises(tr.TransitionError, match="at least two"):
        tr.xfade_offsets([10.0], 1.0)


def test_offsets_reject_a_clip_shorter_than_the_transition() -> None:
    # A 0.5s clip cannot host a 1s dissolve — it would be entirely consumed and
    # xfade would emit a negative offset. Reject loudly instead.
    with pytest.raises(tr.TransitionError, match="shorter than the 1.000s transition"):
        tr.xfade_offsets([10.0, 0.5], 1.0)


def test_offsets_reject_a_clip_exactly_the_transition_length() -> None:
    with pytest.raises(tr.TransitionError, match="shorter than"):
        tr.xfade_offsets([1.0, 10.0], 1.0)


# --------------------------------------------------------------------------- #
# filtergraph
# --------------------------------------------------------------------------- #


def test_filtergraph_two_inputs_conforms_then_xfades_then_acrossfades() -> None:
    graph = tr.build_transition_filtergraph(
        count=2,
        xfade_name="fade",
        duration_sec=1.0,
        offsets=[9.0],
        width=1920,
        height=1080,
        fps=30,
    )
    # Every input is CONFORMED first (scale/pad/sar/fps/pix_fmt) — xfade refuses
    # mismatched geometry, so this is what makes heterogeneous clips joinable.
    assert "[0:v]scale=1920:1080:force_original_aspect_ratio=decrease," in graph
    assert "pad=1920:1080:-1:-1:color=black,setsar=1,fps=30,format=yuv420p[tv0]" in graph
    assert "[1:v]scale=1920:1080" in graph
    assert "[tv0][tv1]xfade=transition=fade:duration=1.000:offset=9.000[vx1]" in graph
    assert "[0:a][1:a]acrossfade=d=1.000:c1=tri:c2=tri[ax1]" in graph


def test_filtergraph_three_inputs_chains_both_lanes() -> None:
    graph = tr.build_transition_filtergraph(
        count=3,
        xfade_name="wipeleft",
        duration_sec=2.0,
        offsets=[8.0, 26.0],
        width=1080,
        height=1920,
        fps=25,
    )
    assert "[tv0][tv1]xfade=transition=wipeleft:duration=2.000:offset=8.000[vx1]" in graph
    assert "[vx1][tv2]xfade=transition=wipeleft:duration=2.000:offset=26.000[vx2]" in graph
    assert "[0:a][1:a]acrossfade=d=2.000:c1=tri:c2=tri[ax1]" in graph
    assert "[ax1][2:a]acrossfade=d=2.000:c1=tri:c2=tri[ax2]" in graph
    assert graph.count("xfade=") == 2
    assert graph.count("acrossfade=") == 2


def test_filtergraph_output_labels_name_the_last_stage() -> None:
    assert tr.video_out_label(2) == "[vx1]"
    assert tr.video_out_label(4) == "[vx3]"
    assert tr.audio_out_label(2) == "[ax1]"
    assert tr.audio_out_label(4) == "[ax3]"


def test_filtergraph_rejects_an_offset_count_mismatch() -> None:
    # A defensive invariant: N inputs need exactly N-1 offsets. A mismatch means
    # the caller mis-derived the math, which must never reach ffmpeg.
    with pytest.raises(tr.TransitionError, match="offset count"):
        tr.build_transition_filtergraph(
            count=3,
            xfade_name="fade",
            duration_sec=1.0,
            offsets=[8.0],
            width=1920,
            height=1080,
            fps=30,
        )


# --------------------------------------------------------------------------- #
# argv
# --------------------------------------------------------------------------- #


def test_argv_has_one_input_per_clip_and_maps_the_chain_outputs() -> None:
    argv = tr.build_transition_argv(
        ["a.mp4", "b.mp4", "c.mp4"],
        "out.mp4",
        style="dissolve",
        duration_ms=2000,
        durations_sec=[10.0, 20.0, 30.0],
        width=1920,
        height=1080,
        fps=30,
        settings={},
    )
    assert argv.count("-i") == 3
    assert argv[argv.index("-i") + 1] == "a.mp4"
    assert argv[-1] == "out.mp4"
    assert argv[argv.index("-map") + 1] == "[vx2]"
    assert "[ax2]" in argv
    # The transition RE-ENCODES by construction (see reencode_note): assert the
    # codec flags are present so no future edit can quietly try `-c copy`.
    assert "libx264" in argv and "aac" in argv
    assert "-c" not in argv or "copy" not in argv


def test_argv_embeds_the_derived_offsets() -> None:
    argv = tr.build_transition_argv(
        ["a.mp4", "b.mp4"],
        "out.mp4",
        style="dissolve",
        duration_ms=1000,
        durations_sec=[10.0, 10.0],
        width=1280,
        height=720,
        fps=24,
        settings=None,
    )
    graph = argv[argv.index("-filter_complex") + 1]
    assert "offset=9.000" in graph
    assert "duration=1.000" in graph
    assert "fps=24" in graph


def test_argv_rejects_a_duration_count_mismatch() -> None:
    with pytest.raises(tr.TransitionError, match="one duration per clip"):
        tr.build_transition_argv(
            ["a.mp4", "b.mp4"],
            "out.mp4",
            style="dissolve",
            duration_ms=1000,
            durations_sec=[10.0],
            width=1280,
            height=720,
            fps=24,
            settings=None,
        )


# --------------------------------------------------------------------------- #
# the honesty control: a transition CANNOT be stream-copied
# --------------------------------------------------------------------------- #


def test_reencode_note_states_the_cost_and_the_boundary_count() -> None:
    note = tr.reencode_note(3)
    assert "re-encode" in note
    assert "2 transition" in note  # 3 clips -> 2 boundaries


def test_reencode_note_is_singular_for_one_boundary() -> None:
    assert "1 transition boundary" in tr.reencode_note(2)


def test_reencode_note_requires_two_clips() -> None:
    with pytest.raises(tr.TransitionError, match="at least two"):
        tr.reencode_note(1)
