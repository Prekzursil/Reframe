"""Unit tests for media_studio.features.zoom (P4 §8b auto punch-in zoom).

The filter builder is PURE: it returns ffmpeg ``zoompan`` strings with no
subprocess and no randomness. These tests pin the determinism, the sentence-start
beat derivation (the v1 beat source — PLAN-P4 C16), the clip-local re-basing, and
the argv shape (argv list, drained-run-ready ``-progress`` flags).
"""
from __future__ import annotations

from typing import Any, Dict, List

import pytest

from media_studio.features import zoom


def cue(text: str, start: float, end: float, index: int = 1) -> Dict[str, Any]:
    return {"index": index, "start": start, "end": end, "text": text}


# --------------------------------------------------------------------------- #
# sentence_start_beats — the v1 beat source
# --------------------------------------------------------------------------- #
def test_first_cue_is_always_a_beat() -> None:
    beats = zoom.sentence_start_beats([cue("hello there", 2.0, 3.0)])
    assert beats == [2.0]


def test_beat_after_sentence_final_punctuation() -> None:
    cues = [
        cue("this is one.", 0.0, 1.0, 1),
        cue("a new line", 1.0, 2.0, 2),  # follows a "." -> a beat
        cue("still going", 2.0, 3.0, 3),  # no preceding "." -> NOT a beat
        cue("done!", 3.0, 4.0, 4),
        cue("next", 4.0, 5.0, 5),  # follows "!" -> a beat
    ]
    beats = zoom.sentence_start_beats(cues)
    assert beats == [0.0, 1.0, 4.0]


def test_question_mark_and_ellipsis_count_as_sentence_end() -> None:
    cues = [
        cue("really?", 0.0, 1.0, 1),
        cue("yes", 1.0, 2.0, 2),  # after "?" -> beat
        cue("wait…", 2.0, 3.0, 3),
        cue("ok", 3.0, 4.0, 4),  # after "…" -> beat
    ]
    assert zoom.sentence_start_beats(cues) == [0.0, 1.0, 3.0]


def test_beats_are_rebased_to_clip_local_time() -> None:
    # source_start=10 -> a cue at 12s lands at clip-local 2s.
    cues = [cue("hi.", 12.0, 13.0, 1), cue("again", 13.0, 14.0, 2)]
    beats = zoom.sentence_start_beats(cues, source_start=10.0)
    assert beats == [2.0, 3.0]


def test_beats_clamped_non_negative() -> None:
    # A cue before the window (negative after re-base) clamps to 0.
    cues = [cue("early.", 5.0, 6.0, 1)]
    assert zoom.sentence_start_beats(cues, source_start=10.0) == [0.0]


def test_blank_cues_skipped() -> None:
    cues = [cue("   ", 0.0, 1.0, 1), cue("real", 1.0, 2.0, 2)]
    # The blank cue is skipped; "real" is the first non-blank -> a beat.
    assert zoom.sentence_start_beats(cues) == [1.0]


def test_beats_deduped_and_sorted() -> None:
    cues = [
        cue("a.", 5.0, 6.0, 1),
        cue("b.", 5.0, 6.0, 2),  # identical start collapses
        cue("c", 1.0, 2.0, 3),
    ]
    beats = zoom.sentence_start_beats(cues)
    assert beats == sorted(beats)
    assert len(beats) == len(set(round(b, 3) for b in beats))


def test_no_beats_for_empty_cues() -> None:
    assert zoom.sentence_start_beats([]) == []


# --------------------------------------------------------------------------- #
# build_zoom_expr — the z expression
# --------------------------------------------------------------------------- #
def test_slow_push_only_when_no_beats() -> None:
    expr = zoom.build_zoom_expr(duration_sec=10.0, beats=[])
    assert expr.startswith("min(")
    assert "*on" in expr  # the linear slow-push term
    assert "gte(" not in expr  # no punch terms


def test_punch_terms_added_per_beat() -> None:
    expr = zoom.build_zoom_expr(duration_sec=10.0, beats=[1.0, 5.0])
    assert expr.count("gte(") == 2  # one gate per beat
    assert "1.000" in expr and "5.000" in expr


def test_expr_is_clamped_to_max_zoom() -> None:
    expr = zoom.build_zoom_expr(duration_sec=10.0, beats=[2.0])
    assert f"{zoom.MAX_ZOOM}" in expr
    assert expr.startswith("min(")


def test_zero_duration_uses_constant_base() -> None:
    # No drift when the duration is unknown/non-positive (base term is just "1").
    expr = zoom.build_zoom_expr(duration_sec=0.0, beats=[])
    assert expr == f"min(1\\,{zoom.MAX_ZOOM})"


def test_expr_is_deterministic() -> None:
    a = zoom.build_zoom_expr(duration_sec=30.0, beats=[1.0, 2.0])
    b = zoom.build_zoom_expr(duration_sec=30.0, beats=[1.0, 2.0])
    assert a == b


def test_negative_beats_dropped() -> None:
    expr = zoom.build_zoom_expr(duration_sec=10.0, beats=[-1.0, 3.0])
    assert expr.count("gte(") == 1


# --------------------------------------------------------------------------- #
# build_zoom_filter — the full zoompan=... string
# --------------------------------------------------------------------------- #
def test_filter_targets_output_size_and_fps() -> None:
    vf = zoom.build_zoom_filter(
        width=1080, height=1920, duration_sec=30.0, cues=[]
    )
    assert vf.startswith("zoompan=")
    assert "s=1080x1920" in vf
    assert "fps=30" in vf
    assert "d=1" in vf


def test_filter_centers_the_zoom() -> None:
    vf = zoom.build_zoom_filter(width=1080, height=1920, duration_sec=30.0, cues=[])
    assert "x='iw/2-(iw/zoom/2)'" in vf
    assert "y='ih/2-(ih/zoom/2)'" in vf


def test_filter_explicit_beats_win_over_cues() -> None:
    cues = [cue("a.", 0.0, 1.0, 1), cue("b", 1.0, 2.0, 2)]
    # Explicit beats bypass the sentence-start derivation entirely.
    vf = zoom.build_zoom_filter(
        width=100, height=100, duration_sec=10.0, beats=[5.0], cues=cues
    )
    assert "gte(on/30,5.000)" in vf
    assert vf.count("gte(") == 1  # only the one explicit beat


def test_filter_derives_beats_from_cues_when_no_explicit_beats() -> None:
    cues = [cue("a.", 0.0, 1.0, 1), cue("b", 1.0, 2.0, 2)]
    vf = zoom.build_zoom_filter(
        width=100, height=100, duration_sec=10.0, cues=cues
    )
    # Two sentence-start beats -> two punch gates.
    assert vf.count("gte(") == 2


def test_filter_rejects_non_positive_dimensions() -> None:
    with pytest.raises(ValueError):
        zoom.build_zoom_filter(width=0, height=100, duration_sec=10.0, cues=[])


# --------------------------------------------------------------------------- #
# build_zoom_argv — the runnable argv
# --------------------------------------------------------------------------- #
def test_argv_is_a_list_with_filter_and_progress(monkeypatch) -> None:
    monkeypatch.setattr(
        "media_studio.ffmpeg.ffmpeg_path", lambda settings=None: "/bin/ffmpeg"
    )
    argv = zoom.build_zoom_argv(
        "in.mp4", "out.mp4", width=1080, height=1920, duration_sec=30.0, cues=[]
    )
    assert isinstance(argv, list)
    assert argv[0] == "/bin/ffmpeg"
    assert "in.mp4" in argv
    assert "out.mp4" == argv[-1]
    # drained-run-ready (the 29-min-freeze lesson) + a video filter.
    assert "-progress" in argv and "pipe:1" in argv and "-nostats" in argv
    fi = argv.index("-filter:v")
    assert argv[fi + 1].startswith("zoompan=")
    # audio is copied (zoom is a video-only transform).
    ai = argv.index("-c:a")
    assert argv[ai + 1] == "copy"


def test_argv_never_a_shell_string(monkeypatch) -> None:
    monkeypatch.setattr(
        "media_studio.ffmpeg.ffmpeg_path", lambda settings=None: "/bin/ffmpeg"
    )
    argv = zoom.build_zoom_argv(
        "in.mp4", "out.mp4", width=100, height=100, duration_sec=5.0, cues=[]
    )
    assert all(isinstance(part, str) for part in argv)
