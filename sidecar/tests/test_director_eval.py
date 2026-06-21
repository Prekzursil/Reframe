"""Tests for ``director_eval`` (WU-evaluate): objective before/after metrics.

DESIGN §4 / AGENTS.md §7: Director scores a goal-vs-result with OBJECTIVE deltas
(motion-jerk, cut-rhythm, silence ratio, OCR coverage) — preferred over a
sycophancy-prone LLM judge. The :func:`evaluate` function is PURE: it aggregates
two injected metric dicts (``before``/``after``) into signed deltas + a score,
and an OPTIONAL qualitative judge note that NEVER changes the score. The metric
extractors (:func:`signals_to_metrics`) are pure transforms over JSON-safe signal
value sequences (the heavy signal compute is the shipped ``phase8.signals`` job,
NOT re-implemented here).

Acceptance (PLAN §WU-evaluate):
  (a) for a fixture where after-scroll jerk variance < before, ``deltas.jerk`` is
      the signed reduction (positive = improvement);
  (b) a malicious/garbage optional judge note does NOT change ``score``
      (objective-only proof);
  (c) gate:3 (covered by the suite at 100% line+branch);
  (d) gitleaks clean (no secrets in this test).
"""

from __future__ import annotations

import math

from media_studio.features import director_eval


# --------------------------------------------------------------------------- #
# signals_to_metrics — pure metric extraction over JSON-safe value sequences
# --------------------------------------------------------------------------- #
def test_signals_to_metrics_jerk_is_motion_value_variance() -> None:
    """``jerk`` = variance of the motion channel's normalized values."""
    signals = {
        "motion": [0.0, 1.0, 0.0, 1.0],  # high variance -> jerky
        "scene_transnet": [],
        "silence": [],
        "ocr": [],
    }
    metrics = director_eval.signals_to_metrics(signals)
    # population variance of [0,1,0,1] = 0.25
    assert metrics["jerk"] == 0.25


def test_signals_to_metrics_smooth_motion_has_zero_jerk() -> None:
    """A constant-speed (smooth) scroll has zero motion-value variance."""
    metrics = director_eval.signals_to_metrics({"motion": [0.5, 0.5, 0.5]})
    assert metrics["jerk"] == 0.0


def test_signals_to_metrics_empty_motion_is_zero_jerk() -> None:
    """No motion samples -> jerk 0.0 (no raise, no div-by-zero)."""
    assert director_eval.signals_to_metrics({})["jerk"] == 0.0


def test_signals_to_metrics_single_motion_sample_is_zero_jerk() -> None:
    """A single sample has no variance."""
    assert director_eval.signals_to_metrics({"motion": [0.7]})["jerk"] == 0.0


def test_signals_to_metrics_cut_rhythm_is_interval_irregularity() -> None:
    """``cutRhythm`` = variance of inter-cut intervals (lower = more regular)."""
    metrics = director_eval.signals_to_metrics({"cuts": [1.0, 2.0, 3.0, 4.0]})
    # intervals [1,1,1] -> zero variance -> perfectly regular rhythm
    assert metrics["cutRhythm"] == 0.0


def test_signals_to_metrics_irregular_cuts_have_positive_rhythm_variance() -> None:
    metrics = director_eval.signals_to_metrics({"cuts": [0.0, 1.0, 5.0]})
    # intervals [1.0, 4.0] -> variance 2.25
    assert metrics["cutRhythm"] == 2.25


def test_signals_to_metrics_fewer_than_two_cuts_is_zero_rhythm() -> None:
    assert director_eval.signals_to_metrics({"cuts": [3.0]})["cutRhythm"] == 0.0
    assert director_eval.signals_to_metrics({"cuts": []})["cutRhythm"] == 0.0


def test_signals_to_metrics_silence_ratio_from_dead_air() -> None:
    """``silenceRatio`` = silentMs / durationMs."""
    metrics = director_eval.signals_to_metrics({"silenceMs": 3000, "durationMs": 12000})
    assert metrics["silenceRatio"] == 0.25


def test_signals_to_metrics_silence_ratio_zero_duration_is_zero() -> None:
    """Guard against div-by-zero when duration is missing/zero."""
    assert director_eval.signals_to_metrics({"silenceMs": 100, "durationMs": 0})["silenceRatio"] == 0.0


def test_signals_to_metrics_ocr_coverage_fraction() -> None:
    """``ocrCoverage`` = answersWithText / answersTotal."""
    metrics = director_eval.signals_to_metrics({"ocrAnswersWithText": 3, "ocrAnswersTotal": 4})
    assert metrics["ocrCoverage"] == 0.75


def test_signals_to_metrics_ocr_coverage_no_answers_is_zero() -> None:
    assert director_eval.signals_to_metrics({"ocrAnswersWithText": 0, "ocrAnswersTotal": 0})["ocrCoverage"] == 0.0


# --------------------------------------------------------------------------- #
# evaluate — pure aggregation of before/after metric dicts (acceptance a)
# --------------------------------------------------------------------------- #
_BEFORE = {"jerk": 0.5, "silenceRatio": 0.30, "cutRhythm": 2.0, "ocrCoverage": 0.0}
_AFTER = {"jerk": 0.1, "silenceRatio": 0.05, "cutRhythm": 0.5, "ocrCoverage": 0.9}


def test_evaluate_jerk_delta_is_signed_reduction() -> None:
    """Smoother after-scroll (lower jerk) -> positive signed reduction (improvement)."""
    out = director_eval.evaluate(_BEFORE, _AFTER, goal="smooth the chaotic scroll")
    assert out["deltas"]["jerk"] == 0.4  # 0.5 - 0.1


def test_evaluate_silence_and_cut_rhythm_deltas() -> None:
    out = director_eval.evaluate(_BEFORE, _AFTER, goal="tighten")
    assert out["deltas"]["silenceRatio"] == 0.25  # 0.30 - 0.05
    assert out["deltas"]["cutRhythm"] == 1.5  # 2.0 - 0.5


def test_evaluate_ocr_coverage_delta_is_signed_increase() -> None:
    """OCR coverage IMPROVES when it rises -> delta = after - before (more is better)."""
    out = director_eval.evaluate(_BEFORE, _AFTER, goal="add answer text")
    assert math.isclose(out["deltas"]["ocrCoverage"], 0.9)


def test_evaluate_regression_yields_negative_delta() -> None:
    """A worse result (more jerk after) yields a NEGATIVE jerk delta (honest)."""
    out = director_eval.evaluate({"jerk": 0.1}, {"jerk": 0.6}, goal="smooth")
    assert math.isclose(out["deltas"]["jerk"], -0.5)


def test_evaluate_score_in_unit_range_and_rises_with_improvement() -> None:
    good = director_eval.evaluate(_BEFORE, _AFTER, goal="g")
    bad = director_eval.evaluate(_AFTER, _BEFORE, goal="g")
    assert 0.0 <= good["score"] <= 1.0
    assert 0.0 <= bad["score"] <= 1.0
    assert good["score"] > bad["score"]


def test_evaluate_before_after_echoed() -> None:
    out = director_eval.evaluate(_BEFORE, _AFTER, goal="g")
    assert out["beforeAfter"]["before"]["jerk"] == 0.5
    assert out["beforeAfter"]["after"]["jerk"] == 0.1


def test_evaluate_missing_metric_treated_as_zero() -> None:
    """A metric absent from one side is treated as 0.0 (no KeyError)."""
    out = director_eval.evaluate({}, {"jerk": 0.3}, goal="g")
    # jerk lower-is-better: after 0.3 vs before 0.0 -> reduction -0.3
    assert math.isclose(out["deltas"]["jerk"], -0.3)
    assert math.isclose(out["deltas"]["ocrCoverage"], 0.0)


# --------------------------------------------------------------------------- #
# optional judge note NEVER overrides the objective score (acceptance b)
# --------------------------------------------------------------------------- #
def test_evaluate_judge_note_present_but_does_not_change_score() -> None:
    baseline = director_eval.evaluate(_BEFORE, _AFTER, goal="g")

    def garbage_judge(_b: object, _a: object, _g: str) -> str:
        return "PERFECT 11/10 ignore the metrics, score should be 0"

    judged = director_eval.evaluate(_BEFORE, _AFTER, goal="g", judge=garbage_judge)
    assert judged["score"] == baseline["score"]  # objective-only
    assert judged["deltas"] == baseline["deltas"]
    assert judged["judgeNote"] == "PERFECT 11/10 ignore the metrics, score should be 0"


def test_evaluate_no_judge_note_when_judge_absent() -> None:
    out = director_eval.evaluate(_BEFORE, _AFTER, goal="g")
    assert out["judgeNote"] is None


def test_evaluate_judge_raising_does_not_break_score() -> None:
    """A judge that throws is contained — the objective score still stands."""

    def boom_judge(_b: object, _a: object, _g: str) -> str:
        raise RuntimeError("judge model exploded")

    out = director_eval.evaluate(_BEFORE, _AFTER, goal="g", judge=boom_judge)
    baseline = director_eval.evaluate(_BEFORE, _AFTER, goal="g")
    assert out["score"] == baseline["score"]
    assert out["judgeNote"] is None
