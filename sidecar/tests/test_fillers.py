"""Unit tests for filler-word removal (features/fillers.py, P3-B).

Pure-logic cut-list tests plus argv-shape tests for the ffmpeg segment-concat
apply (the runner itself is exercised through the shortmaker CUT stage with a
mocked ``ffmpeg.run`` in test_shortmaker.py).
"""

from __future__ import annotations

from typing import Any

import pytest
from media_studio.features import fillers as fl


def w(text: str, start: float, end: float) -> dict[str, Any]:
    return {"text": text, "start": start, "end": end}


# ---------------------------------------------------------------------------
# normalize_token
# ---------------------------------------------------------------------------
def test_normalize_token_strips_punctuation_and_case():
    assert fl.normalize_token("Um,") == "um"
    assert fl.normalize_token(" LIKE… ") == "like"
    assert fl.normalize_token("'uh'") == "uh"
    assert fl.normalize_token(None) == ""


# ---------------------------------------------------------------------------
# build_cutlist — basic drops
# ---------------------------------------------------------------------------
def test_always_filler_is_cut_at_word_boundaries():
    words = [
        w("people", 0.0, 0.5),
        w("um,", 0.6, 1.0),
        w("buy", 1.1, 1.5),
    ]
    keeps = fl.build_cutlist(words, "en")
    # Cut edges land exactly on the filler's word boundaries.
    assert keeps == [(0.0, 0.6), (1.0, 1.5)]


def test_no_fillers_yields_single_keep_spanning_words():
    words = [w("hello", 0.0, 0.4), w("world", 0.5, 1.0)]
    assert fl.build_cutlist(words, "en") == [(0.0, 1.0)]


def test_consecutive_fillers_coalesce_into_one_cut():
    words = [
        w("so", 0.0, 0.3),  # standalone, edge-of-sequence pause
        w("um", 0.35, 0.7),  # always
        w("uh", 0.75, 1.1),  # always
        w("listen", 1.2, 1.8),
    ]
    keeps = fl.build_cutlist(words, "en")
    assert keeps == [(1.1, 1.8)] or keeps == [(0.0, 0.0), (1.1, 1.8)]
    assert (1.1, 1.8) in keeps


def test_romanian_set_drops_ro_basics():
    words = [
        w("ăă", 0.0, 0.4),
        w("salut", 0.5, 1.0),
        w("deci", 1.5, 1.9),  # standalone: 0.5s pause before it
        w("hai", 2.0, 2.4),
    ]
    keeps = fl.build_cutlist(words, "ro")
    assert (0.4, 1.5) in keeps or keeps[0] == (0.4, 1.5)
    # Both 'ăă' and 'deci' are removed.
    removed = 2.4 - 0.0 - sum(b - a for a, b in keeps)
    assert removed == pytest.approx(0.8, abs=1e-6)


def test_language_falls_back_to_en_for_unknown_lang():
    words = [w("um", 0.0, 0.4), w("ok", 0.5, 1.0)]
    keeps = fl.build_cutlist(words, "xx")
    assert keeps == [(0.4, 1.0)]


def test_lang_region_variant_resolves_base_language():
    words = [w("um", 0.0, 0.4), w("ok", 0.5, 1.0)]
    assert fl.build_cutlist(words, "en-US") == [(0.4, 1.0)]


# ---------------------------------------------------------------------------
# standalone vs always tiers
# ---------------------------------------------------------------------------
def test_like_mid_sentence_is_not_cut():
    # "I like it": 'like' is tightly surrounded by words (no pause) -> kept.
    words = [
        w("I", 0.0, 0.2),
        w("like", 0.25, 0.5),
        w("it", 0.55, 0.8),
    ]
    assert fl.build_cutlist(words, "en") == [(0.0, 0.8)]


def test_like_standalone_with_pause_is_cut():
    # A 0.4s pause before 'like' marks it as a discourse filler.
    words = [
        w("amazing", 0.0, 0.5),
        w("like", 0.9, 1.3),
        w("totally", 1.35, 1.9),
    ]
    keeps = fl.build_cutlist(words, "en")
    assert keeps == [(0.0, 0.9), (1.3, 1.9)]


def test_you_know_phrase_is_cut_when_pause_bounded():
    words = [
        w("works", 0.0, 0.5),
        w("you", 1.0, 1.2),
        w("know,", 1.25, 1.5),
        w("every", 2.0, 2.4),
    ]
    keeps = fl.build_cutlist(words, "en")
    assert keeps == [(0.0, 1.0), (1.5, 2.4)]


def test_sentence_final_filler_is_never_cut():
    # 'know?' ends the sentence -> the phrase owns a sentence boundary.
    words = [
        w("works", 0.0, 0.5),
        w("you", 1.0, 1.2),
        w("know?", 1.25, 1.5),
        w("Next", 2.0, 2.4),
    ]
    assert fl.build_cutlist(words, "en") == [(0.0, 2.4)]


# ---------------------------------------------------------------------------
# merge_gap_ms behavior
# ---------------------------------------------------------------------------
def test_sub_merge_gap_removal_is_restored():
    # 'um' is only 80ms long: too short to cut at the default 120ms gap.
    words = [
        w("people", 0.0, 0.5),
        w("um", 0.55, 0.63),
        w("buy", 0.7, 1.2),
    ]
    assert fl.build_cutlist(words, "en") == [(0.0, 1.2)]


def test_merge_gap_zero_keeps_tiny_cuts():
    words = [
        w("people", 0.0, 0.5),
        w("um", 0.55, 0.63),
        w("buy", 0.7, 1.2),
    ]
    keeps = fl.build_cutlist(words, "en", merge_gap_ms=0)
    assert keeps == [(0.0, 0.55), (0.63, 1.2)]


def test_keep_sliver_between_two_cuts_is_absorbed():
    # Two fillers separated by a 50ms keep: the sliver joins the cut.
    words = [
        w("good", 0.0, 0.5),
        w("um", 0.6, 0.9),
        w("uh", 0.95, 1.3),
        w("stuff", 1.5, 2.0),
    ]
    keeps = fl.build_cutlist(words, "en")
    assert keeps == [(0.0, 0.6), (1.3, 2.0)]


# ---------------------------------------------------------------------------
# window + degenerate inputs
# ---------------------------------------------------------------------------
def test_window_extends_keeps_to_clip_bounds():
    words = [w("um", 2.0, 2.4), w("text", 2.5, 3.0)]
    keeps = fl.build_cutlist(words, "en", window=(1.0, 4.0))
    assert keeps == [(1.0, 2.0), (2.4, 4.0)]


def test_empty_words_keep_whole_window():
    keeps, stats = fl.build_cutlist_with_stats([], "en", window=(0.0, 10.0))
    assert keeps == [(0.0, 10.0)]
    assert stats == {"fillersRemoved": 0, "fillerSeconds": 0.0}


def test_no_words_and_no_window_yields_empty():
    assert fl.build_cutlist([], "en") == []


def test_all_filler_words_keep_window_whole():
    words = [w("um", 0.0, 0.4), w("uh", 0.5, 0.9)]
    keeps, stats = fl.build_cutlist_with_stats(words, "en", window=(0.0, 1.0))
    assert keeps == [(0.0, 1.0)]
    assert stats["fillersRemoved"] == 0


def test_malformed_words_are_skipped():
    words = [
        {"text": "um"},  # no times
        {"text": "", "start": 0, "end": 1},  # blank
        {"text": "ok", "start": 2.0, "end": 1.0},  # inverted
        w("fine", 0.0, 1.0),
    ]
    assert fl.build_cutlist(words, "en") == [(0.0, 1.0)]


# ---------------------------------------------------------------------------
# stats
# ---------------------------------------------------------------------------
def test_stats_count_removed_words_and_seconds():
    words = [
        w("people", 0.0, 0.5),
        w("um", 0.6, 1.0),  # 0.4s
        w("buy", 1.1, 1.5),
        w("uh", 1.6, 1.9),  # 0.3s
        w("why", 2.0, 2.5),
    ]
    keeps, stats = fl.build_cutlist_with_stats(words, "en")
    assert stats["fillersRemoved"] == 2
    assert stats["fillerSeconds"] == pytest.approx(0.7, abs=1e-6)
    total_kept = sum(b - a for a, b in keeps)
    assert total_kept == pytest.approx(2.5 - 0.7, abs=1e-6)


def test_phrase_counts_each_word_in_stats():
    words = [
        w("works", 0.0, 0.5),
        w("you", 1.0, 1.2),
        w("know", 1.25, 1.5),
        w("every", 2.0, 2.4),
    ]
    _keeps, stats = fl.build_cutlist_with_stats(words, "en")
    assert stats["fillersRemoved"] == 2  # 'you' + 'know'
    assert stats["fillerSeconds"] == pytest.approx(0.5, abs=1e-6)


# ---------------------------------------------------------------------------
# remap_time / remap_cues
# ---------------------------------------------------------------------------
def test_remap_time_compresses_across_cuts():
    keeps = [(0.0, 1.0), (2.0, 3.0)]
    assert fl.remap_time(0.5, keeps) == pytest.approx(0.5)
    assert fl.remap_time(1.5, keeps) == pytest.approx(1.0)  # inside the cut
    assert fl.remap_time(2.5, keeps) == pytest.approx(1.5)
    assert fl.remap_time(9.0, keeps) == pytest.approx(2.0)  # past the end


def test_remap_time_before_first_keep_clamps_to_zero():
    assert fl.remap_time(0.5, [(1.0, 2.0)]) == 0.0


def test_remap_cues_drops_cues_inside_removed_spans():
    keeps = [(0.0, 1.0), (2.0, 3.0)]
    cues = [
        {"index": 1, "start": 0.2, "end": 0.8, "text": "kept"},
        {"index": 2, "start": 1.2, "end": 1.8, "text": "gone"},  # inside cut
        {"index": 3, "start": 2.2, "end": 2.8, "text": "shifted"},
    ]
    out = fl.remap_cues(cues, keeps)
    assert [c["text"] for c in out] == ["kept", "shifted"]
    assert out[0]["start"] == pytest.approx(0.2)
    assert out[1]["start"] == pytest.approx(1.2)  # 2.2 - 1.0 removed
    assert out[1]["end"] == pytest.approx(1.8)
    assert [c["index"] for c in out] == [1, 2]


def test_remap_cues_clips_straddling_cue():
    keeps = [(0.0, 1.0), (2.0, 3.0)]
    cues = [{"index": 1, "start": 0.5, "end": 2.5, "text": "straddle"}]
    out = fl.remap_cues(cues, keeps)
    assert out[0]["start"] == pytest.approx(0.5)
    assert out[0]["end"] == pytest.approx(1.5)


# ---------------------------------------------------------------------------
# build_segment_cut_argv
# ---------------------------------------------------------------------------
@pytest.fixture()
def fake_ffmpeg(monkeypatch):
    from media_studio import ffmpeg

    monkeypatch.setattr(ffmpeg, "ffmpeg_path", lambda settings=None: "/bin/ffmpeg")


def test_segment_argv_is_list_with_trim_concat(fake_ffmpeg):
    argv = fl.build_segment_cut_argv(
        "C:/in/source video.mp4",
        "C:/out/cut clip.mp4",
        [(10.0, 20.0), (21.5, 40.0)],
    )
    assert isinstance(argv, list)
    assert argv[0] == "/bin/ffmpeg"
    assert "C:/in/source video.mp4" in argv  # spaces survive (argv list)
    assert argv[-1] == "C:/out/cut clip.mp4"
    fc = argv[argv.index("-filter_complex") + 1]
    assert "trim=start=10.000:end=20.000" in fc
    assert "atrim=start=21.500:end=40.000" in fc
    assert "concat=n=2:v=1:a=1[v][a]" in fc
    assert "setpts=PTS-STARTPTS" in fc and "asetpts=PTS-STARTPTS" in fc
    # mapped outputs + encoder + progress protocol.
    assert argv[argv.index("-map") + 1] == "[v]"
    assert "[a]" in argv
    assert argv[argv.index("-c:v") + 1] == "libx264"
    assert argv[argv.index("-c:a") + 1] == "aac"
    assert "-progress" in argv and "-nostats" in argv


def test_segment_argv_rejects_empty_keeps(fake_ffmpeg):
    with pytest.raises(ValueError):
        fl.build_segment_cut_argv("in.mp4", "out.mp4", [])
    with pytest.raises(ValueError):
        fl.build_segment_cut_argv("in.mp4", "out.mp4", [(5.0, 5.0)])


def test_segment_argv_single_keep(fake_ffmpeg):
    argv = fl.build_segment_cut_argv("in.mp4", "out.mp4", [(0.0, 30.0)])
    fc = argv[argv.index("-filter_complex") + 1]
    assert "concat=n=1:v=1:a=1[v][a]" in fc
