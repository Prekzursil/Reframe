"""Tier-0 learned re-ranker — LGBMRanker (LambdaMART) over the feedback flywheel.

The final stage of the Phase-8 selection pipeline: an OpusClip-style virality
flywheel. Every approve / discard / export the user records lands in
``features.feedback``'s append-only ``feedback.jsonl``; once that store holds
enough labels, this module trains a **LambdaMART** ranker (``lightgbm``'s
``LGBMRanker``) on a fixed-order feature vector built from each candidate's four
P3-C factors plus the Phase-8 per-channel signal aggregates, then re-ranks fresh
candidate sets by the model's relevance prediction.

Design (mirrors the proven seam pattern of ``diarize`` + the calibration gate of
``feedback``):

* **Pure half** (fully covered, no heavy import): :func:`build_feature_row` turns
  a :class:`~media_studio.features.select.Candidate` + a per-channel signal map
  into a frozen-order :data:`FeatureVector`; :func:`training_rows_from_feedback`
  derives ``(X, y, groups)`` LambdaMART training rows from a
  :class:`~media_studio.features.feedback.FeedbackStore` (positive=1 for
  approved/exported, 0 for discarded, ``nudged`` excluded exactly like the
  calibration table); :func:`rerank` reorders candidates by a backend's scores.
* **Heavy half behind a Protocol seam** (:class:`RankerBackend`): the real
  ``LGBMRanker`` is built lazily by :func:`_default_ranker_factory` (which imports
  ``lightgbm`` *inside* the function — it is NOT in the test venv). Tests inject a
  fake backend whose ``predict`` is a simple linear scorer, so no native ML stack
  is ever touched.
* **Graceful fallback** (the OpusClip cold-start rule): :func:`train_ranker`
  returns ``None`` below ``min_labels`` (the same 50-label gate as feedback
  calibration) OR when ``lightgbm`` cannot be imported; :func:`rank` then falls
  back to deterministic **factor-average** ordering, so a brand-new install with
  no flywheel data — or a build without ``lightgbm`` — still produces a sane,
  ranked candidate set with zero model download.

Manifest row #14: ``lightgbm`` 4.6.0, MIT (commercial YES), ~1-3 MB, CPU,
``objective='lambdarank'`` — zero model download, trains on the local
``feedback.jsonl``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import TYPE_CHECKING, Any, Protocol

from ..util import clamp, get_logger
from .feedback import (
    CALIBRATION_MIN_LABELS,
    NEGATIVE_ACTIONS,
    POSITIVE_ACTIONS,
)

if TYPE_CHECKING:  # pragma: no cover - typing-only import, never executed at runtime
    from .feedback import FeedbackStore

log = get_logger("media_studio.features.ranker")

#: A single training/inference row: a fixed-order list of plain floats.
FeatureVector = list[float]

#: A per-channel signal-aggregate map (channel name -> 0..1 pooled value), the
#: Phase-8 unified-scorer output a candidate carries. Missing channels degrade to
#: 0.0 at featurization (a clip with no audio simply has zeroed audio features).
SignalMap = Mapping[str, float]

# --------------------------------------------------------------------------- #
# Frozen feature layout (wire-stable: column order MUST match between training
# and inference, so it lives in one place and is asserted by the tests). The
# first four columns are the P3-C virality factors (0..1, rescaled from 0-100);
# the rest are the Phase-8 signal channels the unified scorer pools per clip.
# --------------------------------------------------------------------------- #
FACTOR_FEATURES: tuple[str, ...] = (
    "hookStrength",
    "emotionalFlow",
    "perceivedValue",
    "shareability",
)

#: The signal channels appended after the factor columns (frozen order). Mirrors
#: the Wave-1 Signal channel vocabulary the unified scorer keys weights off.
SIGNAL_FEATURES: tuple[str, ...] = (
    "motion",
    "saliency",
    "aesthetic",
    "zeroShot",
    "novelty",
    "audioSalience",
    "laughter",
    "applause",
    "music",
    "loudness",
)

#: The complete, frozen feature-column order (factors first, then signals). The
#: scorer/trainer both read columns from THIS tuple, so the vector layout can
#: never silently drift between train and predict.
FEATURE_NAMES: tuple[str, ...] = FACTOR_FEATURES + SIGNAL_FEATURES

#: The minimum labels before a model is trained (same gate as feedback
#: calibration — below it, :func:`rank` keeps the factor-average order).
RANKER_MIN_LABELS = CALIBRATION_MIN_LABELS

#: The candidate field the re-ranked score is stamped onto.
SCORE_FIELD = "rankerScore"


# --------------------------------------------------------------------------- #
# pure: featurization
# --------------------------------------------------------------------------- #
def _factor_unit(candidate: Mapping[str, Any], name: str) -> float:
    """One P3-C factor rescaled from its stored 0-100 int to a 0..1 unit float.

    A missing / unparseable factor degrades to ``0.0`` (the clip simply scores
    nothing on that factor) — featurization must never raise on partial data.
    """
    factors = candidate.get("factors")
    if not isinstance(factors, Mapping):
        return 0.0
    try:
        raw = float(factors[name])
    except (KeyError, TypeError, ValueError):
        return 0.0
    return clamp(raw / 100.0, 0.0, 1.0)


def _signal_unit(signals: SignalMap, name: str) -> float:
    """One signal channel as a clamped 0..1 float (missing channel -> 0.0)."""
    try:
        value = float(signals[name])
    except (KeyError, TypeError, ValueError):
        return 0.0
    return clamp(value, 0.0, 1.0)


def build_feature_row(candidate: Mapping[str, Any], signals: SignalMap | None = None) -> FeatureVector:
    """Build a fixed-order feature vector for one candidate.

    Columns follow :data:`FEATURE_NAMES` exactly: the four P3-C virality factors
    (rescaled 0-100 -> 0..1) followed by the Phase-8 per-channel signal
    aggregates (each clamped 0..1, missing channels zeroed). ``signals`` is the
    per-clip pooled signal map the Wave-2 unified scorer produces; ``None`` (no
    Phase-8 signals available) yields the factor columns plus zeroed signals.
    """
    sig = signals or {}
    row: FeatureVector = [_factor_unit(candidate, name) for name in FACTOR_FEATURES]
    row.extend(_signal_unit(sig, name) for name in SIGNAL_FEATURES)
    return row


def factor_average_unit(candidate: Mapping[str, Any]) -> float:
    """Mean of the four factor columns (0..1) — the fallback ordering key."""
    values = [_factor_unit(candidate, name) for name in FACTOR_FEATURES]
    return sum(values) / float(len(FACTOR_FEATURES))


# --------------------------------------------------------------------------- #
# pure: training-row derivation from the feedback flywheel
# --------------------------------------------------------------------------- #
def _label_for_action(action: Any) -> int | None:
    """Map a feedback action to a LambdaMART relevance label.

    ``approved``/``exported`` -> 1 (positive), ``discarded`` -> 0 (negative).
    Anything else (``nudged``) returns ``None`` and is excluded from training,
    exactly as the calibration table excludes it (it is a taste nudge, not an
    approve/reject decision).
    """
    if action in POSITIVE_ACTIONS:
        return 1
    if action in NEGATIVE_ACTIONS:
        return 0
    return None


def training_rows_from_feedback(
    store: FeedbackStore,
) -> tuple[list[FeatureVector], list[int], list[int]]:
    """Derive ``(X, y, groups)`` LambdaMART training rows from the flywheel.

    Walks the store's labeled entries in append order:

    * ``X`` — one :func:`build_feature_row` per labeled (approved/exported/
      discarded) entry. The signals a past candidate was scored with are read
      from its stored ``signals`` map when present (the flywheel keeps the
      Phase-8 aggregates on the candidate payload), else zeroed.
    * ``y`` — the relevance label (1 positive, 0 negative); ``nudged`` excluded.
    * ``groups`` — the per-``videoId`` query-group sizes LambdaMART needs, in
      first-seen videoId order (a ranking objective ranks WITHIN a query).

    Returns three parallel structures (``sum(groups) == len(X) == len(y)``).
    """
    features: list[FeatureVector] = []
    labels: list[int] = []
    group_order: list[str] = []
    group_counts: dict[str, int] = {}
    for entry in store.entries():
        label = _label_for_action(entry.get("action"))
        if label is None:
            continue  # 'nudged' is a label total but not a train row
        candidate = entry.get("candidate")
        if not isinstance(candidate, Mapping):
            continue
        signals = candidate.get("signals")
        signal_map = signals if isinstance(signals, Mapping) else None
        features.append(build_feature_row(candidate, signal_map))
        labels.append(label)
        video_id = str(entry.get("videoId", "") or "")
        if video_id not in group_counts:
            group_counts[video_id] = 0
            group_order.append(video_id)
        group_counts[video_id] += 1
    groups = [group_counts[vid] for vid in group_order]
    return features, labels, groups


# --------------------------------------------------------------------------- #
# the heavy backend seam (LGBMRanker) — never imported here
# --------------------------------------------------------------------------- #
class RankerBackend(Protocol):
    """The slice of the LambdaMART ranker the pure runner needs.

    A real implementation wraps ``lightgbm.LGBMRanker(objective='lambdarank')``
    (built lazily by :func:`_default_ranker_factory`, never at import). Tests
    inject a fake whose ``predict`` is a simple linear scorer over the feature
    columns, so no native ML stack is touched.
    """

    def fit(self, x: Sequence[FeatureVector], y: Sequence[int], groups: Sequence[int]) -> None:
        """Train on feature rows ``x``, relevance labels ``y``, query ``groups``."""
        ...  # pragma: no cover - Protocol body, never executed

    def predict(self, x: Sequence[FeatureVector]) -> list[float]:
        """Score each feature row — higher is more relevant."""
        ...  # pragma: no cover - Protocol body, never executed


#: Factory seam: ``settings -> RankerBackend`` (default = lazy real impl).
RankerFactory = Callable[[Mapping[str, Any]], RankerBackend]


def _default_ranker_factory(settings: Mapping[str, Any]) -> RankerBackend:
    """Build the real lightgbm-backed ranker (LAZY import; runtime only)."""
    from .ranker_backend import LgbmRankerBackend  # noqa: PLC0415 - heavy seam

    return LgbmRankerBackend(settings)


# --------------------------------------------------------------------------- #
# train + rank
# --------------------------------------------------------------------------- #
def train_ranker(
    store: FeedbackStore,
    *,
    settings: Mapping[str, Any] | None = None,
    backend_factory: RankerFactory | None = None,
    min_labels: int = RANKER_MIN_LABELS,
) -> RankerBackend | None:
    """Train a LambdaMART ranker on the flywheel, or ``None`` below threshold.

    Returns ``None`` (cold-start / fallback signal) when:

    * the store holds fewer than ``min_labels`` labels (the same gate as feedback
      calibration — too little signal to learn a useful ranking), OR
    * no usable train rows survive (every entry was ``nudged`` / malformed), OR
    * the backend cannot be built (``lightgbm`` not importable) — the lazy import
      raises and is swallowed into the fallback.

    A returned backend has been ``fit`` on ``(X, y, groups)`` and is ready for
    :func:`rerank` / :func:`rank`.
    """
    if store.labels() < min_labels:
        return None
    features, labels, groups = training_rows_from_feedback(store)
    if not features or not groups:
        return None
    factory = backend_factory or _default_ranker_factory
    try:
        backend = factory(settings or {})
        backend.fit(features, labels, groups)
    except Exception:  # noqa: BLE001 - any backend failure -> graceful fallback
        log.warning("ranker training failed; falling back to factor-average order", exc_info=True)
        return None
    return backend


def _stamp_score(candidate: Mapping[str, Any], score: float) -> dict[str, Any]:
    """Return an immutable copy of ``candidate`` with ``rankerScore`` stamped."""
    return {**candidate, SCORE_FIELD: float(score)}


def rerank(
    candidates: Sequence[Mapping[str, Any]],
    feature_rows: Sequence[FeatureVector],
    ranker: RankerBackend,
) -> list[dict[str, Any]]:
    """Re-rank candidates by a trained backend's relevance scores.

    Each candidate gets a fresh ``rankerScore`` (immutable copy — inputs are
    never mutated) and the list is returned sorted by that score descending;
    ties keep the input order (stable). ``feature_rows`` must align 1:1 with
    ``candidates`` (built via :func:`build_feature_row`).
    """
    if len(feature_rows) != len(candidates):
        raise ValueError(f"feature_rows ({len(feature_rows)}) must align 1:1 with candidates ({len(candidates)})")
    if not candidates:
        return []
    scores = ranker.predict(list(feature_rows))
    scored = [_stamp_score(cand, scores[i]) for i, cand in enumerate(candidates)]
    order = sorted(enumerate(scored), key=lambda iv: (-iv[1][SCORE_FIELD], iv[0]))
    return [cand for _idx, cand in order]


def _fallback_order(candidates: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Deterministic factor-average ordering (the cold-start / no-model path).

    Stamps each candidate's ``rankerScore`` with its factor-average (0..1) and
    sorts descending, ties stable. This is what a brand-new install — or a build
    without ``lightgbm`` — uses, so selection is always ranked, never empty.
    """
    scored = [_stamp_score(cand, factor_average_unit(cand)) for cand in candidates]
    order = sorted(enumerate(scored), key=lambda iv: (-iv[1][SCORE_FIELD], iv[0]))
    return [cand for _idx, cand in order]


def rank(
    candidates: Sequence[Mapping[str, Any]],
    *,
    ranker: RankerBackend | None = None,
    signals_for: Callable[[Mapping[str, Any]], SignalMap | None] | None = None,
) -> list[dict[str, Any]]:
    """Rank candidates, using the trained ``ranker`` when present else fallback.

    The single entry point Wave-2 calls per candidate set:

    * ``ranker is None`` (cold-start, below the label gate, or ``lightgbm``
      absent) -> deterministic :func:`_fallback_order` by factor-average.
    * otherwise -> :func:`build_feature_row` per candidate (pulling each clip's
      per-channel signals via ``signals_for`` when provided, else zeroed) then
      :func:`rerank` by the model.

    Inputs are never mutated; every returned candidate carries ``rankerScore``.
    """
    if ranker is None:
        return _fallback_order(candidates)
    resolve = signals_for or (lambda _cand: None)
    feature_rows = [build_feature_row(cand, resolve(cand)) for cand in candidates]
    return rerank(candidates, feature_rows, ranker)


__all__ = [
    "FACTOR_FEATURES",
    "FEATURE_NAMES",
    "RANKER_MIN_LABELS",
    "SCORE_FIELD",
    "SIGNAL_FEATURES",
    "FeatureVector",
    "RankerBackend",
    "RankerFactory",
    "SignalMap",
    "build_feature_row",
    "factor_average_unit",
    "rank",
    "rerank",
    "train_ranker",
    "training_rows_from_feedback",
]
