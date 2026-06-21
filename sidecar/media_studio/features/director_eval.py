"""Director objective evaluation (WU-evaluate, DESIGN §4, AGENTS.md §7).

Director scores a *goal-vs-result* with **objective** before/after metrics rather
than a sycophancy-prone LLM judge. This module is the PURE aggregation layer:

  * :func:`signals_to_metrics` — turn a JSON-safe bundle of signal value sequences
    (the digest of the shipped ``phase8.signals`` tracks — motion values, scene-cut
    timestamps, dead-air ms, OCR answer counts) into the four scalar metrics
    ``{jerk, cutRhythm, silenceRatio, ocrCoverage}``. The heavy signal compute is
    NOT here — it is the shipped ``phase8.signals`` job; this only shapes its output.
  * :func:`evaluate` — aggregate a ``before`` + ``after`` metric dict into signed
    deltas (positive = improvement) + a single ``score`` in ``[0, 1]``, plus an
    OPTIONAL qualitative judge note that NEVER changes the score (objective-only).

Metric polarity (DESIGN §4 table):
  * ``jerk`` — motion-value variance; LOWER is smoother. Improvement = before-after.
  * ``cutRhythm`` — inter-cut interval variance; LOWER is more regular. before-after.
  * ``silenceRatio`` — dead-air fraction; LOWER is tighter. before-after.
  * ``ocrCoverage`` — answers with on-screen text; HIGHER is better. after-before.

PURITY: stdlib only — NO ``Provider`` / transport / heavy-ML import. The optional
judge callable is supplied by the handler (which routes it through ``_run_ai_job``);
this module only CALLS it and discards any influence on ``score``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

#: The four objective metrics, with their improvement polarity.
#: ``True`` = lower-is-better (improvement = before - after); ``False`` =
#: higher-is-better (improvement = after - before).
_LOWER_IS_BETTER: dict[str, bool] = {
    "jerk": True,
    "cutRhythm": True,
    "silenceRatio": True,
    "ocrCoverage": False,
}


def _population_variance(values: Sequence[float]) -> float:
    """Population variance of ``values`` (0.0 for fewer than two samples)."""
    n = len(values)
    if n < 2:
        return 0.0
    mean = sum(values) / n
    return sum((v - mean) ** 2 for v in values) / n


def _floats(raw: Any) -> list[float]:
    """Coerce a raw value sequence into a list of floats (empty if absent)."""
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return []
    return [float(v) for v in raw]


def signals_to_metrics(signals: Mapping[str, Any]) -> dict[str, float]:
    """Shape a signal-value bundle into the four objective metrics.

    ``signals`` is a JSON-safe digest of the shipped ``phase8.signals`` tracks:

      * ``motion`` — the per-window normalized motion values (a constant-speed
        scroll has near-zero variance; an erratic one is high-variance → jerky);
      * ``cuts`` — scene-cut timestamps in seconds (their inter-cut intervals'
        variance is the rhythm irregularity);
      * ``silenceMs`` / ``durationMs`` — dead-air ms over total ms (silence ratio);
      * ``ocrAnswersWithText`` / ``ocrAnswersTotal`` — OCR answer coverage.

    Any absent channel contributes its neutral 0.0 — never a raise. PURE.
    """
    motion = _floats(signals.get("motion"))
    cuts = sorted(_floats(signals.get("cuts")))
    duration_ms = float(signals.get("durationMs") or 0.0)
    silence_ms = float(signals.get("silenceMs") or 0.0)
    answers_total = float(signals.get("ocrAnswersTotal") or 0.0)
    answers_with_text = float(signals.get("ocrAnswersWithText") or 0.0)

    intervals = [cuts[i + 1] - cuts[i] for i in range(len(cuts) - 1)]

    return {
        "jerk": _population_variance(motion),
        "cutRhythm": _population_variance(intervals),
        "silenceRatio": (silence_ms / duration_ms) if duration_ms > 0.0 else 0.0,
        "ocrCoverage": (answers_with_text / answers_total) if answers_total > 0.0 else 0.0,
    }


def _delta(metric: str, before: float, after: float) -> float:
    """Signed improvement for ``metric`` (positive = better) per its polarity."""
    return (before - after) if _LOWER_IS_BETTER[metric] else (after - before)


def _score(deltas: Mapping[str, float]) -> float:
    """Collapse the signed deltas into a single ``[0, 1]`` score.

    A logistic squash of the mean signed improvement: 0.5 = no change, → 1.0 as
    the edit improves the objective metrics, → 0.0 as it regresses them. Bounded,
    monotonic in improvement, and entirely derived from the OBJECTIVE deltas (no
    judge influence — DESIGN §4 / AGENTS.md §7).
    """
    mean = sum(deltas.values()) / len(deltas)
    # 1 / (1 + e^-x) without importing math.exp: use the stable closed form.
    return 1.0 / (1.0 + _exp(-mean))


def _exp(x: float) -> float:
    """``e ** x`` via the stdlib power operator (avoids a math import for purity)."""
    import math  # local: import-light, stdlib only

    return math.exp(x)


def evaluate(
    before: Mapping[str, float],
    after: Mapping[str, float],
    *,
    goal: str,  # noqa: ARG001 - part of the public contract; future judge prompts key on it
    judge: Callable[[Mapping[str, float], Mapping[str, float], str], str] | None = None,
) -> dict[str, Any]:
    """Aggregate ``before``/``after`` metric dicts into deltas + an objective score.

    Returns ``{score, deltas, beforeAfter, judgeNote}``:

      * ``deltas`` — the signed improvement per metric (positive = better), with a
        missing metric on either side treated as ``0.0``;
      * ``score`` — a single ``[0, 1]`` summary derived ONLY from ``deltas``;
      * ``beforeAfter`` — the echoed before/after metric snapshots (the storyboard
        renders these side by side);
      * ``judgeNote`` — the OPTIONAL qualitative note from ``judge`` (or ``None``).
        It is descriptive only: a garbage/malicious note can NEVER move ``score``
        (objective-only, AGENTS.md §7 anti-sycophancy). A judge that raises is
        contained (note stays ``None``).

    PURE aggregation; the heavy signal compute + the LLM judge call live in the
    handler (the judge rides ``_run_ai_job`` — no parallel AI path).
    """
    before_m = {m: float(before.get(m, 0.0)) for m in _LOWER_IS_BETTER}
    after_m = {m: float(after.get(m, 0.0)) for m in _LOWER_IS_BETTER}
    deltas = {m: _delta(m, before_m[m], after_m[m]) for m in _LOWER_IS_BETTER}

    judge_note: str | None = None
    if judge is not None:
        try:
            judge_note = judge(before_m, after_m, goal)
        except Exception:  # noqa: BLE001 - a flaky judge must never break the objective verdict
            judge_note = None

    return {
        "score": _score(deltas),
        "deltas": deltas,
        "beforeAfter": {"before": before_m, "after": after_m},
        "judgeNote": judge_note,
    }
