"""Pure-logic tests for boundary-snapping (media_studio.features.boundary).

No heavy-ML imports: silence and scene-cut lists are injected directly (the seam
the orchestrator fills with ffmpeg silencedetect / PySceneDetect). Word timings
are hand-built so every assertion is deterministic. Covers: sentence-end
derivation, nearest-boundary snap, the 20-60s window, mid-word protection,
idempotence, batch re-ranking, and no-valid-boundary => drop-with-reason.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

import pytest
from media_studio.features import boundary
from media_studio.features.boundary import (
    BoundarySet,
    SnapResult,
    build_boundary_set,
    sentence_ends_from_words,
    snap_candidate,
    snap_candidates,
    snap_from_lists,
)


# --- builders ----------------------------------------------------------------
def make_word(text: str, start: float, end: float) -> dict[str, Any]:
    """A §3 Word: {text, start, end}."""
    return {"text": text, "start": start, "end": end}


def make_candidate(
    start: float,
    end: float,
    *,
    rank: int = 1,
    hook: str = "hook",
    why: str = "why",
    score: int = 80,
    source_start: float = 0.0,
) -> dict[str, Any]:
    """A §3 Candidate with all required fields."""
    return {
        "rank": rank,
        "start": start,
        "end": end,
        "durationSec": round(end - start, 3),
        "hook": hook,
        "why": why,
        "score": score,
        "sourceStart": source_start,
    }


def words_every_second(texts: Sequence[str], *, t0: float = 0.0) -> list[dict[str, Any]]:
    """One word per second: word i spans [t0+i, t0+i+1).

    A trailing period on a word marks a sentence end at that word's ``end``.
    """
    out: list[dict[str, Any]] = []
    for i, txt in enumerate(texts):
        out.append(make_word(txt, t0 + i, t0 + i + 1.0))
    return out


# --- sentence-end derivation -------------------------------------------------
class TestSentenceEnds:
    def test_basic_terminators(self) -> None:
        words = [
            make_word("Hello", 0.0, 0.5),
            make_word("world.", 0.5, 1.0),  # end at 1.0
            make_word("Wow!", 1.0, 1.4),  # end at 1.4
            make_word("Really?", 1.4, 2.0),  # end at 2.0
            make_word("mid", 2.0, 2.5),  # no terminator
        ]
        assert sentence_ends_from_words(words) == (1.0, 1.4, 2.0)

    def test_ellipsis_char_terminator(self) -> None:
        words = [make_word("well…", 3.0, 4.0)]
        assert sentence_ends_from_words(words) == (4.0,)

    def test_trailing_quote_is_trimmed(self) -> None:
        # 'done."' and 'go.)' still count as sentence ends.
        words = [make_word('done."', 2.0, 3.0), make_word("go.)", 4.0, 5.0)]
        assert sentence_ends_from_words(words) == (3.0, 5.0)

    def test_non_terminator_excluded(self) -> None:
        words = [make_word("and", 0.0, 1.0), make_word("then,", 1.0, 2.0)]
        assert sentence_ends_from_words(words) == ()

    def test_sorted_and_deduped(self) -> None:
        words = [
            make_word("b.", 5.0, 6.0),
            make_word("a.", 1.0, 2.0),
            make_word("c.", 5.5, 6.0),  # duplicate end 6.0
        ]
        assert sentence_ends_from_words(words) == (2.0, 6.0)

    def test_skips_malformed_words(self) -> None:
        words = [
            {"text": "good.", "end": 3.0},  # valid
            {"text": None, "end": 4.0},  # bad text
            {"text": "x.", "end": "nope"},  # bad end
            {"end": 9.0},  # no text
        ]
        assert sentence_ends_from_words(words) == (3.0,)


# --- BoundarySet -------------------------------------------------------------
class TestBoundarySet:
    def test_all_targets_merges_dedups_sorts(self) -> None:
        bs = BoundarySet(
            sentence_ends=(10.0, 30.0),
            silences=(30.0, 45.0),  # 30.0 duplicate
            scene_cuts=(5.0, 45.0),  # 45.0 duplicate
        )
        assert bs.all_targets() == (5.0, 10.0, 30.0, 45.0)

    def test_empty(self) -> None:
        assert BoundarySet().all_targets() == ()

    def test_build_from_direct_lists(self) -> None:
        words = [make_word("end.", 25.0, 26.0)]
        bs = build_boundary_set(words, silences=[12.5, 12.5], scene_cuts=[3.0])
        assert bs.sentence_ends == (26.0,)
        assert bs.silences == (12.5,)  # deduped
        assert bs.scene_cuts == (3.0,)

    def test_build_filters_non_numeric(self) -> None:
        bs = build_boundary_set([], silences=[1.0, "bad", None, 2.0])  # type: ignore[list-item]
        assert bs.silences == (1.0, 2.0)

    def test_build_uses_providers_when_lists_absent(self) -> None:
        bs = build_boundary_set(
            [],
            silence_provider=lambda: [7.0, 8.0],
            scene_provider=lambda: [9.0],
        )
        assert bs.silences == (7.0, 8.0)
        assert bs.scene_cuts == (9.0,)

    def test_direct_list_overrides_provider(self) -> None:
        bs = build_boundary_set(
            [],
            silences=[1.0],
            silence_provider=lambda: [99.0],  # ignored: direct list wins
        )
        assert bs.silences == (1.0,)


# --- snapping: the happy path ------------------------------------------------
class TestSnapHappyPath:
    def test_snaps_both_ends_to_nearest_boundary(self) -> None:
        # 40 one-second words -> spans [0,40). Sentence ends at 1.0 and 31.0.
        texts = ["w"] * 40
        texts[0] = "go."  # end 1.0
        texts[30] = "stop."  # end 31.0
        words = words_every_second(texts)
        bs = build_boundary_set(words, silences=[], scene_cuts=[])
        # Candidate roughly [1.3 .. 30.6]; should snap to 1.0 .. 31.0 (29s, in range).
        cand = make_candidate(1.3, 30.6)
        res = snap_candidate(cand, words, bs)
        assert res.kept
        assert res.candidate is not None
        assert res.candidate["start"] == pytest.approx(1.0)
        assert res.candidate["end"] == pytest.approx(31.0)
        assert res.candidate["durationSec"] == pytest.approx(30.0)

    def test_preserves_non_geometry_fields(self) -> None:
        words = words_every_second(["a."] + ["w"] * 24 + ["z."])
        bs = build_boundary_set(words, silences=[], scene_cuts=[])
        cand = make_candidate(0.6, 25.4, rank=3, hook="HOOK!", why="reason", score=91, source_start=12.5)
        res = snap_candidate(cand, words, bs)
        assert res.candidate is not None
        for key in ("rank", "hook", "why", "score", "sourceStart"):
            assert res.candidate[key] == cand[key]

    def test_silence_and_scene_are_valid_targets(self) -> None:
        # No sentence ends near the edges; rely on silence (start) + scene (end).
        words = [make_word("w", float(i), i + 1.0) for i in range(40)]
        bs = build_boundary_set(words, silences=[5.0], scene_cuts=[30.0])
        cand = make_candidate(5.3, 29.6)
        res = snap_candidate(cand, words, bs)
        assert res.candidate is not None
        assert res.candidate["start"] == pytest.approx(5.0)
        assert res.candidate["end"] == pytest.approx(30.0)

    def test_tie_breaks_toward_smaller_timestamp(self) -> None:
        words = [make_word("w", float(i), i + 1.0) for i in range(60)]
        # start original 10.0 equidistant from 9.0 and 11.0 -> choose 9.0.
        bs = build_boundary_set(words, silences=[9.0, 11.0], scene_cuts=[40.0])
        cand = make_candidate(10.0, 40.0)
        res = snap_candidate(cand, words, bs)
        assert res.candidate is not None
        assert res.candidate["start"] == pytest.approx(9.0)


# --- the 20-60s window -------------------------------------------------------
class TestDurationWindow:
    def test_end_must_keep_duration_in_range(self) -> None:
        # Sentence ends at 5.0 (start) and a far one at 70.0 (would be 65s -> too long),
        # plus 50.0 (45s -> in range). End should land on 50.0, not 70.0.
        words = [make_word("w", float(i), i + 1.0) for i in range(75)]
        bs = build_boundary_set(words, silences=[5.0, 50.0, 70.0], scene_cuts=[])
        cand = make_candidate(5.2, 52.0)
        res = snap_candidate(cand, words, bs)
        assert res.candidate is not None
        dur = res.candidate["end"] - res.candidate["start"]
        assert boundary.MIN_SEC - 1e-6 <= dur <= boundary.MAX_SEC + 1e-6
        assert res.candidate["end"] == pytest.approx(50.0)

    def test_rejects_when_only_target_makes_clip_too_short(self) -> None:
        words = [make_word("w", float(i), i + 1.0) for i in range(40)]
        # Only boundaries are 10.0 and 15.0 -> max possible clip is 5s (< 20s).
        bs = build_boundary_set(words, silences=[10.0, 15.0], scene_cuts=[])
        cand = make_candidate(10.0, 15.0)
        res = snap_candidate(cand, words, bs)
        assert res.dropped
        assert "20-60" in res.reason or "mid-word" in res.reason

    def test_extends_end_forward_to_reach_min_duration(self) -> None:
        # Original clip is only ~8s; a boundary at 30.0 lets it extend to >=20s.
        words = [make_word("w", float(i), i + 1.0) for i in range(40)]
        bs = build_boundary_set(words, silences=[2.0, 30.0], scene_cuts=[])
        cand = make_candidate(2.1, 10.0)
        res = snap_candidate(cand, words, bs)
        assert res.candidate is not None
        assert res.candidate["start"] == pytest.approx(2.0)
        assert res.candidate["end"] == pytest.approx(30.0)
        assert res.candidate["durationSec"] == pytest.approx(28.0)

    def test_custom_min_max(self) -> None:
        words = [make_word("w", float(i), i + 1.0) for i in range(20)]
        bs = build_boundary_set(words, silences=[2.0, 12.0], scene_cuts=[])
        cand = make_candidate(2.0, 12.0)  # 10s clip
        # default window (20-60) drops it; custom 5-15 keeps it.
        assert snap_candidate(cand, words, bs).dropped
        res = snap_candidate(cand, words, bs, min_sec=5.0, max_sec=15.0)
        assert res.kept

    def test_invalid_window_raises(self) -> None:
        words = [make_word("w", 0.0, 1.0)]
        bs = build_boundary_set(words, silences=[0.0, 30.0], scene_cuts=[])
        cand = make_candidate(0.0, 30.0)
        with pytest.raises(ValueError):
            snap_candidate(cand, words, bs, min_sec=60.0, max_sec=20.0)


# --- never cut mid-word ------------------------------------------------------
class TestNeverMidWord:
    def test_mid_word_boundary_is_rejected(self) -> None:
        # One long word spans [10, 20). A silence at 15.0 is mid-word -> rejected.
        # No other start target exists in range (the first word has no terminator,
        # so it contributes no sentence end), so the candidate must be dropped
        # rather than cut mid-word at 15.0.
        words = [
            make_word("intro", 0.0, 5.0),  # no terminator -> not a boundary
            make_word("loooong", 10.0, 20.0),  # mid-word zone 10..20
            make_word("after.", 35.0, 36.0),
        ]
        # start target 15.0 sits mid-word; end target 36.0 is fine.
        bs = build_boundary_set(words, silences=[15.0], scene_cuts=[36.0])
        cand = make_candidate(15.0, 36.0)
        res = snap_candidate(cand, words, bs)
        # 15.0 is mid-word and is the only near-start target -> no valid start.
        assert res.dropped

    def test_mid_word_target_skipped_when_aligned_alt_exists(self) -> None:
        # If a word-aligned boundary exists, the snapper uses it instead of the
        # mid-word target -- and the result never lands inside a word span.
        words = [
            make_word("intro.", 0.0, 5.0),  # sentence end at 5.0 (word edge)
            make_word("loooong", 10.0, 20.0),  # mid-word zone 10..20
            make_word("after.", 35.0, 36.0),
        ]
        bs = build_boundary_set(words, silences=[15.0], scene_cuts=[36.0])
        res = snap_candidate(make_candidate(15.0, 36.0), words, bs)
        assert res.kept
        assert res.candidate is not None
        # Must not be the mid-word 15.0; the aligned 5.0 wins.
        assert res.candidate["start"] == pytest.approx(5.0)
        assert res.candidate["end"] == pytest.approx(36.0)

    def test_boundary_exactly_at_word_edge_is_allowed(self) -> None:
        # A target exactly at a word's start/end is NOT mid-word.
        words = [
            make_word("a.", 0.0, 1.0),
            make_word("mid", 1.0, 30.0),  # spans 1..30; 1.0 and 30.0 are edges
            make_word("b.", 30.0, 31.0),
        ]
        bs = build_boundary_set(words, silences=[1.0, 30.0], scene_cuts=[])
        cand = make_candidate(1.0, 30.0)  # 29s, edges-only -> allowed
        res = snap_candidate(cand, words, bs)
        assert res.kept
        assert res.candidate is not None
        assert res.candidate["start"] == pytest.approx(1.0)
        assert res.candidate["end"] == pytest.approx(30.0)

    def test_no_words_means_no_midword_constraint(self) -> None:
        # With no word spans, any in-range boundary is acceptable.
        bs = build_boundary_set([], silences=[5.0, 30.0], scene_cuts=[])
        cand = make_candidate(5.0, 30.0)
        res = snap_candidate(cand, [], bs)
        assert res.kept


# --- idempotence -------------------------------------------------------------
class TestIdempotence:
    def test_resnapping_is_stable(self) -> None:
        texts = ["w"] * 50
        texts[1] = "go."  # end 2.0
        texts[31] = "stop."  # end 32.0
        words = words_every_second(texts)
        bs = build_boundary_set(words, silences=[], scene_cuts=[])
        cand = make_candidate(1.7, 31.6)
        first = snap_candidate(cand, words, bs)
        assert first.candidate is not None
        second = snap_candidate(first.candidate, words, bs)
        assert second.candidate is not None
        assert second.candidate["start"] == pytest.approx(first.candidate["start"])
        assert second.candidate["end"] == pytest.approx(first.candidate["end"])
        assert second.candidate["durationSec"] == pytest.approx(first.candidate["durationSec"])

    def test_already_on_boundary_unchanged(self) -> None:
        words = [make_word("w", float(i), i + 1.0) for i in range(40)]
        bs = build_boundary_set(words, silences=[3.0, 33.0], scene_cuts=[])
        cand = make_candidate(3.0, 33.0)  # exactly on boundaries, 30s
        res = snap_candidate(cand, words, bs)
        assert res.candidate is not None
        assert res.candidate["start"] == pytest.approx(3.0)
        assert res.candidate["end"] == pytest.approx(33.0)


# --- no valid boundary => drop with reason -----------------------------------
class TestDropWithReason:
    def test_no_boundaries_at_all_drops(self) -> None:
        words = [make_word("w", float(i), i + 1.0) for i in range(40)]
        bs = build_boundary_set(words, silences=[], scene_cuts=[])  # nothing
        cand = make_candidate(5.0, 30.0)
        res = snap_candidate(cand, words, bs)
        assert res.dropped
        assert res.candidate is None
        assert res.reason  # non-empty human-readable reason

    def test_drop_reason_mentions_window(self) -> None:
        words = [make_word("w", float(i), i + 1.0) for i in range(40)]
        bs = build_boundary_set(words, silences=[10.0, 12.0], scene_cuts=[])
        cand = make_candidate(10.0, 12.0)
        res = snap_candidate(cand, words, bs)
        assert res.dropped
        assert "20-60s" in res.reason

    def test_invalid_start_end_drops(self) -> None:
        bs = BoundarySet()
        res = snap_candidate({"start": "x", "end": 30.0}, [], bs)
        assert res.dropped
        assert "invalid" in res.reason

    def test_missing_keys_drops(self) -> None:
        bs = BoundarySet()
        res = snap_candidate({"start": 1.0}, [], bs)  # no 'end'
        assert res.dropped
        assert "invalid" in res.reason

    def test_non_positive_duration_drops(self) -> None:
        bs = BoundarySet(silences=(0.0, 30.0))
        res = snap_candidate(make_candidate(30.0, 30.0), [], bs)
        assert res.dropped
        assert "non-positive" in res.reason

    def test_reversed_endpoints_drops(self) -> None:
        bs = BoundarySet(silences=(0.0, 30.0))
        res = snap_candidate(make_candidate(30.0, 10.0), [], bs)
        assert res.dropped


# --- SnapResult dataclass ----------------------------------------------------
class TestSnapResult:
    def test_kept_property(self) -> None:
        assert SnapResult(candidate={"x": 1}).kept is True
        assert SnapResult(candidate=None, dropped=True, reason="r").kept is False


# --- batch snapping ----------------------------------------------------------
class TestBatch:
    def test_keeps_and_drops_separated(self) -> None:
        # Good clip has a clean (2.0 .. 32.0) pair. The bad clip lives in an
        # isolated 2s cluster (200.0, 201.0) far past every other boundary, so no
        # boundary sits 20-60s away from its endpoints -> it must drop.
        words = [make_word("w", float(i), i + 1.0) for i in range(210)]
        bs = build_boundary_set(words, silences=[2.0, 32.0, 200.0, 201.0], scene_cuts=[])
        good = make_candidate(2.1, 31.5, rank=1)  # snaps 2.0..32.0 (30s)
        bad = make_candidate(200.3, 201.0, rank=2)  # isolated cluster -> drop
        kept, dropped = snap_candidates([good, bad], words, bs)
        assert len(kept) == 1
        assert len(dropped) == 1
        assert dropped[0]["candidate"] is bad
        assert dropped[0]["reason"]

    def test_reranks_kept_clips_in_order(self) -> None:
        # Two keepers (ranks 5, 9 in) flank a candidate boxed into a tight cluster
        # at 50.0/51.0 (no boundary 20-60s away) that drops. Kept clips re-rank to
        # 1, 2 in their input order regardless of their incoming rank values.
        words = [make_word("w", float(i), i + 1.0) for i in range(220)]
        bs = build_boundary_set(words, silences=[1.0, 31.0, 105.0, 106.0, 180.0, 210.0], scene_cuts=[])
        c1 = make_candidate(1.0, 31.0, rank=5)  # -> rank 1
        bad = make_candidate(105.3, 106.0, rank=2)  # isolated cluster -> dropped
        c2 = make_candidate(180.0, 210.0, rank=9)  # -> rank 2 (30s)
        kept, dropped = snap_candidates([c1, bad, c2], words, bs)
        assert [c["rank"] for c in kept] == [1, 2]
        assert len(dropped) == 1
        assert dropped[0]["candidate"] is bad

    def test_empty_batch(self) -> None:
        kept, dropped = snap_candidates([], [], BoundarySet())
        assert kept == []
        assert dropped == []

    def test_batch_idempotent(self) -> None:
        words = [make_word("w", float(i), i + 1.0) for i in range(80)]
        bs = build_boundary_set(words, silences=[2.0, 32.0], scene_cuts=[])
        cands = [make_candidate(2.3, 31.6, rank=1)]
        kept1, _ = snap_candidates(cands, words, bs)
        kept2, _ = snap_candidates(kept1, words, bs)
        assert kept1[0]["start"] == pytest.approx(kept2[0]["start"])
        assert kept1[0]["end"] == pytest.approx(kept2[0]["end"])


# --- snap_from_lists convenience --------------------------------------------
class TestSnapFromLists:
    def test_direct_lists(self) -> None:
        words = [make_word("w", float(i), i + 1.0) for i in range(40)]
        kept, dropped = snap_from_lists(
            [make_candidate(2.1, 31.6)],
            words,
            silences=[2.0, 32.0],
            scene_cuts=[],
        )
        assert len(kept) == 1
        assert kept[0]["start"] == pytest.approx(2.0)
        assert kept[0]["end"] == pytest.approx(32.0)
        assert dropped == []

    def test_with_providers(self) -> None:
        words = [make_word("w", float(i), i + 1.0) for i in range(40)]
        calls = {"silence": 0, "scene": 0}

        def silence_provider() -> list[float]:
            calls["silence"] += 1
            return [3.0, 33.0]

        def scene_provider() -> list[float]:
            calls["scene"] += 1
            return []

        kept, dropped = snap_from_lists(
            [make_candidate(3.1, 32.6)],
            words,
            silence_provider=silence_provider,
            scene_provider=scene_provider,
        )
        assert len(kept) == 1
        assert kept[0]["start"] == pytest.approx(3.0)
        assert kept[0]["end"] == pytest.approx(33.0)
        assert calls == {"silence": 1, "scene": 1}


# --- detection (ffmpeg silencedetect / PySceneDetect, mocked seams) ----------
class _FakeCompleted:
    """Stand-in for a subprocess.run CompletedProcess (stderr only)."""

    def __init__(self, stderr: str) -> None:
        self.stderr = stderr
        self.returncode = 0


_SILENCEDETECT_STDERR = (
    "[silencedetect @ 0x1] silence_start: 10.0\n"
    "[silencedetect @ 0x1] silence_end: 12.0 | silence_duration: 2.0\n"
    "[silencedetect @ 0x1] silence_start: 30.5\n"
    "[silencedetect @ 0x1] silence_end: 31.5 | silence_duration: 1.0\n"
)


class TestDetectionSeam:
    def test_parse_silencedetect_returns_gap_midpoints(self) -> None:
        # midpoints of [10,12] and [30.5,31.5] -> 11.0 and 31.0
        assert boundary.parse_silencedetect(_SILENCEDETECT_STDERR) == (11.0, 31.0)

    def test_parse_silencedetect_ignores_unpaired_start(self) -> None:
        stderr = "silence_start: 5.0\n"  # no matching end before EOF
        assert boundary.parse_silencedetect(stderr) == ()

    def test_build_silencedetect_argv_is_a_list_no_shell(self) -> None:
        argv = boundary.build_silencedetect_argv("/a b/v.mp4", ffmpeg_path="ffmpeg")
        assert isinstance(argv, list)
        # the path with a space stays a single argv element
        assert "/a b/v.mp4" in argv
        assert any("silencedetect" in a for a in argv)

    def test_detect_silences_parses_mocked_ffmpeg_stderr(self) -> None:
        calls: list[list[str]] = []

        def fake_run(argv, **kwargs):  # type: ignore[no-untyped-def]
            calls.append(list(argv))
            return _FakeCompleted(_SILENCEDETECT_STDERR)

        out = boundary.detect_silences("/v.mp4", settings={"ffmpegPath": "/usr/bin/ffmpeg"}, run=fake_run)
        assert out == (11.0, 31.0)
        assert len(calls) == 1  # one ffmpeg invocation, mocked

    def test_detect_silences_returns_empty_on_run_failure(self) -> None:
        def boom(argv, **kwargs):  # type: ignore[no-untyped-def]
            raise OSError("ffmpeg missing")

        out = boundary.detect_silences("/v.mp4", settings={"ffmpegPath": "/usr/bin/ffmpeg"}, run=boom)
        assert out == ()

    def test_detect_scene_cuts_uses_injected_detector(self) -> None:
        out = boundary.detect_scene_cuts(
            "/v.mp4",
            detector=lambda p: [3.0, 17.5, 3.0],  # dup deduped
        )
        assert out == (3.0, 17.5)

    def test_detect_scene_cuts_returns_empty_on_detector_failure(self) -> None:
        def boom(_p: str) -> list[float]:
            raise RuntimeError("scenedetect blew up")

        assert boundary.detect_scene_cuts("/v.mp4", detector=boom) == ()

    def test_detected_lists_flow_into_snap(self) -> None:
        # The detectors' output is consumable by snap_from_lists (the real wiring).
        # Two silence gaps -> midpoints 5.0 (start target) and 35.0 (end target).
        words = [make_word("w", float(i), i + 1.0) for i in range(40)]
        stderr = "silence_start: 4.0\nsilence_end: 6.0\nsilence_start: 34.0\nsilence_end: 36.0\n"
        silences = boundary.detect_silences(
            "/v.mp4",
            settings={"ffmpegPath": "/usr/bin/ffmpeg"},
            run=lambda argv, **k: _FakeCompleted(stderr),
        )
        assert silences == (5.0, 35.0)
        kept, _ = snap_from_lists(
            [make_candidate(5.1, 34.6)],
            words,
            silences=list(silences),
            scene_cuts=[],
        )
        assert len(kept) == 1
        assert kept[0]["start"] == pytest.approx(5.0)
        assert kept[0]["end"] == pytest.approx(35.0)

    def test_orchestrator_can_override_seam_via_provider(self) -> None:
        # The seam is meant to be bound by the orchestrator; we simulate that by
        # passing a bound provider and confirming it flows through.
        words = [make_word("w", float(i), i + 1.0) for i in range(40)]
        bound_silence = lambda: boundary_fake_detect("/v.mp4")  # noqa: E731
        kept, _ = snap_from_lists(
            [make_candidate(5.1, 34.6)],
            words,
            silence_provider=bound_silence,
            scene_cuts=[],
        )
        assert len(kept) == 1
        assert kept[0]["start"] == pytest.approx(5.0)
        assert kept[0]["end"] == pytest.approx(35.0)


def boundary_fake_detect(_path: str) -> list[float]:
    """Stand-in for a real ffmpeg-backed silence detector (test seam fill)."""
    return [5.0, 35.0]


# --- numerical robustness ----------------------------------------------------
class TestNumericalRobustness:
    def test_float_durations_are_finite(self) -> None:
        words = [make_word("w", float(i), i + 1.0) for i in range(40)]
        bs = build_boundary_set(words, silences=[2.0, 32.0], scene_cuts=[])
        res = snap_candidate(make_candidate(2.1, 31.6), words, bs)
        assert res.candidate is not None
        assert math.isfinite(res.candidate["durationSec"])

    def test_near_epsilon_boundary_is_word_aligned(self) -> None:
        # A target within EPS of a word edge counts as edge-aligned, not mid-word.
        words = [make_word("a.", 0.0, 1.0), make_word("long", 1.0, 30.0), make_word("b.", 30.0, 31.0)]
        bs = build_boundary_set(words, silences=[1.0 + boundary.EPS / 2, 30.0], scene_cuts=[])
        cand = make_candidate(1.0, 30.0)
        res = snap_candidate(cand, words, bs)
        assert res.kept


# --- internal helpers: the remaining defensive branches ----------------------
class TestInternalHelpers:
    def test_word_spans_skips_words_without_valid_timings(self) -> None:
        # A word missing/invalid start or end is skipped (the 140->137 loop-back).
        words = [
            make_word("ok", 1.0, 2.0),
            {"text": "no-end", "start": 3.0},  # missing end -> skipped
            {"text": "bad", "start": "x", "end": "y"},  # non-numeric -> skipped
            make_word("ok2", 5.0, 6.0),
        ]
        assert boundary._word_spans(words) == ((1.0, 2.0), (5.0, 6.0))

    def test_nearest_valid_tie_break_prefers_smaller_when_seen_later(self) -> None:
        # Targets handed in DESCENDING order: the equidistant SMALLER target is
        # seen after the larger one, exercising the `t < best` tie-break (line 181).
        got = boundary._nearest_valid(
            10.0,
            [11.0, 9.0],  # both distance 1.0; 9.0 < 11.0 and seen second
            lower=0.0,
            upper=100.0,
            spans=(),
        )
        assert got == 9.0

    def test_parse_silencedetect_skips_pair_when_end_not_after_start(self) -> None:
        # A pair whose end <= start contributes no midpoint (the 469->468 skip).
        stderr = (
            "[silencedetect @ 0x1] silence_start: 12.0\n"
            "[silencedetect @ 0x1] silence_end: 12.0 | silence_duration: 0.0\n"
        )
        assert boundary.parse_silencedetect(stderr) == ()

    def test_detect_silences_returns_empty_when_ffmpeg_unresolvable(self, monkeypatch) -> None:
        # ffmpeg_path raising (no resolvable binary) -> warn + return () (506-508).
        import media_studio.ffmpeg as _ffmpeg

        def boom(_settings):
            raise _ffmpeg.FfmpegNotFound("ffmpeg")

        monkeypatch.setattr(_ffmpeg, "ffmpeg_path", boom)
        assert boundary.detect_silences("/v.mp4", settings={}, run=lambda *a, **k: None) == ()
