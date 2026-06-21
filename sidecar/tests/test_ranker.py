"""Heavy-ML-free tests for the Tier-0 learned re-ranker (media_studio.features.ranker).

The real LambdaMART backend (``lightgbm``) is NOT in the test venv. Every test
either injects a FAKE :class:`RankerBackend` (a deterministic linear scorer) or a
fake ``backend_factory``, so ``lightgbm`` is never imported. Real numpy is not
even needed — the module is plain-float math, so assertions are exact.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import pytest
from media_studio.features import ranker
from media_studio.features.feedback import FeedbackStore


# --------------------------------------------------------------------------- #
# fakes
# --------------------------------------------------------------------------- #
class LinearRanker:
    """A fake RankerBackend whose score is the plain SUM of feature columns.

    Records its fit args so tests can assert training derivation, and refuses to
    predict before fit (mirrors the real backend's guard).
    """

    def __init__(self) -> None:
        self.fit_calls: list[tuple[list[list[float]], list[int], list[int]]] = []

    def fit(self, x: Sequence[ranker.FeatureVector], y: Sequence[int], groups: Sequence[int]) -> None:
        self.fit_calls.append(([list(r) for r in x], list(y), list(groups)))

    def predict(self, x: Sequence[ranker.FeatureVector]) -> list[float]:
        if not self.fit_calls:
            raise RuntimeError("predict before fit")
        return [sum(row) for row in x]


def _candidate(
    factors: dict[str, int] | None = None,
    *,
    rank: int = 1,
    signals: Mapping[str, float] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    cand: dict[str, Any] = {
        "rank": rank,
        "start": 0.0,
        "end": 30.0,
        "hook": f"hook-{rank}",
        "score": 50,
    }
    if factors is not None:
        cand["factors"] = factors
    if signals is not None:
        cand["signals"] = dict(signals)
    cand.update(extra)
    return cand


_FULL_FACTORS = {
    "hookStrength": 80,
    "emotionalFlow": 60,
    "perceivedValue": 40,
    "shareability": 20,
}


# --------------------------------------------------------------------------- #
# frozen feature layout
# --------------------------------------------------------------------------- #
def test_feature_names_order_is_frozen() -> None:
    assert ranker.FEATURE_NAMES == ranker.FACTOR_FEATURES + ranker.SIGNAL_FEATURES
    assert ranker.FACTOR_FEATURES == (
        "hookStrength",
        "emotionalFlow",
        "perceivedValue",
        "shareability",
    )
    assert ranker.SIGNAL_FEATURES == (
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
    # The layout is wire-stable: 4 factor columns + 10 signal columns.
    assert len(ranker.FEATURE_NAMES) == 14


# --------------------------------------------------------------------------- #
# build_feature_row — factors + signals, clamping, degrade paths
# --------------------------------------------------------------------------- #
def test_build_feature_row_rescales_factors_and_clamps_signals() -> None:
    signals = {"motion": 0.5, "laughter": 1.5, "loudness": -0.2}
    row = ranker.build_feature_row(_candidate(_FULL_FACTORS), signals)
    assert len(row) == len(ranker.FEATURE_NAMES)
    # factors 0-100 -> 0..1
    assert row[:4] == [0.8, 0.6, 0.4, 0.2]
    # signals clamped: motion kept, laughter clamped to 1.0, loudness to 0.0
    cols = dict(zip(ranker.FEATURE_NAMES, row, strict=True))
    assert cols["motion"] == 0.5
    assert cols["laughter"] == 1.0
    assert cols["loudness"] == 0.0
    # an unspecified signal channel zeros out
    assert cols["saliency"] == 0.0


def test_build_feature_row_none_signals_zeros_signal_columns() -> None:
    row = ranker.build_feature_row(_candidate(_FULL_FACTORS), None)
    assert row[:4] == [0.8, 0.6, 0.4, 0.2]
    assert row[4:] == [0.0] * len(ranker.SIGNAL_FEATURES)


def test_build_feature_row_missing_factors_degrade_to_zero() -> None:
    # No 'factors' key at all -> factors mapping branch returns 0.0.
    row = ranker.build_feature_row(_candidate(None), {"motion": 1.0})
    assert row[:4] == [0.0, 0.0, 0.0, 0.0]
    assert dict(zip(ranker.FEATURE_NAMES, row, strict=True))["motion"] == 1.0


def test_build_feature_row_factors_not_a_mapping_degrade_to_zero() -> None:
    row = ranker.build_feature_row({"factors": "not-a-dict"}, None)
    assert row[:4] == [0.0, 0.0, 0.0, 0.0]


def test_build_feature_row_unparseable_factor_value_degrades() -> None:
    bad = {**_FULL_FACTORS, "hookStrength": "oops"}
    row = ranker.build_feature_row({"factors": bad}, None)
    # hookStrength unparseable -> 0.0; the rest still parse.
    assert row[0] == 0.0
    assert row[1] == 0.6


def test_build_feature_row_signal_value_unparseable_degrades() -> None:
    row = ranker.build_feature_row(_candidate(_FULL_FACTORS), {"motion": None})
    assert dict(zip(ranker.FEATURE_NAMES, row, strict=True))["motion"] == 0.0


# --------------------------------------------------------------------------- #
# factor_average_unit
# --------------------------------------------------------------------------- #
def test_factor_average_unit() -> None:
    avg = ranker.factor_average_unit(_candidate(_FULL_FACTORS))
    assert avg == pytest.approx((0.8 + 0.6 + 0.4 + 0.2) / 4)


# --------------------------------------------------------------------------- #
# training_rows_from_feedback — label mapping, groups, exclusions
# --------------------------------------------------------------------------- #
def _store_with(tmp_path: Any, entries: list[tuple[str, dict[str, Any], str]]) -> FeedbackStore:
    store = FeedbackStore(path=tmp_path / "feedback.jsonl")
    for video_id, candidate, action in entries:
        store.record(video_id, candidate, action)
    return store


def test_training_rows_label_mapping_and_groups(tmp_path: Any) -> None:
    store = _store_with(
        tmp_path,
        [
            ("vidA", _candidate(_FULL_FACTORS, signals={"motion": 1.0}), "approved"),
            ("vidA", _candidate(_FULL_FACTORS), "discarded"),
            ("vidA", _candidate(_FULL_FACTORS), "exported"),
            ("vidB", _candidate(_FULL_FACTORS), "approved"),
            ("vidB", _candidate(_FULL_FACTORS), "nudged"),  # excluded
        ],
    )
    x, y, groups = ranker.training_rows_from_feedback(store)
    # 4 train rows (nudged dropped), labels: approved/exported=1, discarded=0
    assert y == [1, 0, 1, 1]
    assert len(x) == 4
    # groups in first-seen videoId order: vidA has 3 train rows, vidB has 1
    assert groups == [3, 1]
    assert sum(groups) == len(x) == len(y)
    # the stored signal map flowed into the first row's motion column
    cols = dict(zip(ranker.FEATURE_NAMES, x[0], strict=True))
    assert cols["motion"] == 1.0
    assert x[0][:4] == [0.8, 0.6, 0.4, 0.2]


def test_training_rows_skips_non_mapping_candidate(tmp_path: Any) -> None:
    # FeedbackStore.record requires a dict, so write a torn entry directly to
    # exercise the "candidate not a Mapping" guard in derivation.
    path = tmp_path / "feedback.jsonl"
    import json

    path.write_text(
        json.dumps({"videoId": "v", "candidate": ["not", "a", "dict"], "action": "approved"}) + "\n",
        encoding="utf-8",
    )
    store = FeedbackStore(path=path)
    x, y, groups = ranker.training_rows_from_feedback(store)
    assert x == [] and y == [] and groups == []


def test_training_rows_signals_not_mapping_zeroed(tmp_path: Any) -> None:
    # A candidate whose 'signals' is not a mapping hits the isinstance(else)
    # branch -> signal columns zeroed (only factors carry through).
    store = FeedbackStore(path=tmp_path / "feedback.jsonl")
    store.record("v", {"factors": _FULL_FACTORS, "signals": "nope"}, "approved")
    x, _y, _g = ranker.training_rows_from_feedback(store)
    assert x[0][4:] == [0.0] * len(ranker.SIGNAL_FEATURES)
    assert x[0][:4] == [0.8, 0.6, 0.4, 0.2]


# --------------------------------------------------------------------------- #
# train_ranker — gates + success + fallback
# --------------------------------------------------------------------------- #
def _bulk_store(tmp_path: Any, n: int, action: str = "approved") -> FeedbackStore:
    store = FeedbackStore(path=tmp_path / "feedback.jsonl")
    for i in range(n):
        store.record(f"vid{i % 3}", _candidate(_FULL_FACTORS, rank=i), action)
    return store


def test_train_ranker_below_threshold_returns_none(tmp_path: Any) -> None:
    store = _bulk_store(tmp_path, 10)
    assert store.labels() < ranker.RANKER_MIN_LABELS
    assert ranker.train_ranker(store) is None


def test_train_ranker_custom_min_labels(tmp_path: Any) -> None:
    store = _bulk_store(tmp_path, 3)
    fake = LinearRanker()
    out = ranker.train_ranker(store, backend_factory=lambda _s: fake, min_labels=3)
    assert out is fake
    assert fake.fit_calls  # was fit


def test_train_ranker_no_usable_rows_returns_none(tmp_path: Any) -> None:
    # 60 entries, ALL nudged -> above label gate but zero train rows.
    store = _bulk_store(tmp_path, 60, action="nudged")
    assert store.labels() >= ranker.RANKER_MIN_LABELS
    assert ranker.train_ranker(store, backend_factory=lambda _s: LinearRanker()) is None


def test_train_ranker_success_fits_backend(tmp_path: Any) -> None:
    store = _bulk_store(tmp_path, 60)
    fake = LinearRanker()
    out = ranker.train_ranker(store, settings={"a": 1}, backend_factory=lambda _s: fake)
    assert out is fake
    (rows, labels, groups) = fake.fit_calls[0]
    assert len(rows) == 60
    assert all(label == 1 for label in labels)
    assert sum(groups) == 60


def test_train_ranker_backend_failure_falls_back_to_none(tmp_path: Any) -> None:
    store = _bulk_store(tmp_path, 60)

    def boom(_settings: Mapping[str, Any]) -> ranker.RankerBackend:
        raise RuntimeError("lightgbm import blew up")

    assert ranker.train_ranker(store, backend_factory=boom) is None


def test_default_ranker_factory_lazy_imports_backend() -> None:
    # The default factory must lazily import the heavy backend module. We don't
    # need lightgbm itself (the wrapper class import is light), only proof the
    # seam wires to LgbmRankerBackend without importing lightgbm at module load.
    backend = ranker._default_ranker_factory({})
    from media_studio.features.ranker_backend import LgbmRankerBackend

    assert isinstance(backend, LgbmRankerBackend)


# --------------------------------------------------------------------------- #
# rerank
# --------------------------------------------------------------------------- #
def test_rerank_orders_by_predicted_score_descending() -> None:
    fake = LinearRanker()
    fake.fit_calls.append(([], [], []))  # mark as fitted
    c_low = _candidate({"hookStrength": 10, "emotionalFlow": 10, "perceivedValue": 10, "shareability": 10}, rank=1)
    c_high = _candidate(_FULL_FACTORS, rank=2)
    rows = [ranker.build_feature_row(c_low, None), ranker.build_feature_row(c_high, None)]
    out = ranker.rerank([c_low, c_high], rows, fake)
    assert [c["rank"] for c in out] == [2, 1]  # high-factor clip first
    assert all(ranker.SCORE_FIELD in c for c in out)
    # inputs not mutated
    assert ranker.SCORE_FIELD not in c_low


def test_rerank_stable_for_ties() -> None:
    fake = LinearRanker()
    fake.fit_calls.append(([], [], []))
    a = _candidate(_FULL_FACTORS, rank=1)
    b = _candidate(_FULL_FACTORS, rank=2)
    rows = [ranker.build_feature_row(a, None), ranker.build_feature_row(b, None)]
    out = ranker.rerank([a, b], rows, fake)
    assert [c["rank"] for c in out] == [1, 2]  # equal scores -> input order kept


def test_rerank_empty_returns_empty() -> None:
    fake = LinearRanker()
    fake.fit_calls.append(([], [], []))
    assert ranker.rerank([], [], fake) == []


def test_rerank_length_mismatch_raises() -> None:
    fake = LinearRanker()
    with pytest.raises(ValueError, match="align 1:1"):
        ranker.rerank([_candidate(_FULL_FACTORS)], [], fake)


# --------------------------------------------------------------------------- #
# rank — the unified entry (fallback + model paths)
# --------------------------------------------------------------------------- #
def test_rank_none_ranker_falls_back_to_factor_average() -> None:
    low = _candidate({"hookStrength": 10, "emotionalFlow": 10, "perceivedValue": 10, "shareability": 10}, rank=1)
    high = _candidate(_FULL_FACTORS, rank=2)
    out = ranker.rank([low, high], ranker=None)
    assert [c["rank"] for c in out] == [2, 1]
    assert out[0][ranker.SCORE_FIELD] == pytest.approx(0.5)  # high avg
    assert out[1][ranker.SCORE_FIELD] == pytest.approx(0.1)


def test_rank_fallback_ties_stable() -> None:
    a = _candidate(_FULL_FACTORS, rank=1)
    b = _candidate(_FULL_FACTORS, rank=2)
    out = ranker.rank([a, b], ranker=None)
    assert [c["rank"] for c in out] == [1, 2]


def test_rank_with_model_and_signals_resolver() -> None:
    fake = LinearRanker()
    fake.fit_calls.append(([], [], []))
    weak = _candidate(_FULL_FACTORS, rank=1)
    strong = _candidate(_FULL_FACTORS, rank=2)
    # Give the 'strong' clip a big audio signal so the linear sum ranks it first.
    signal_lookup = {2: {"loudness": 1.0, "audioSalience": 1.0}}

    def signals_for(cand: Mapping[str, Any]) -> Mapping[str, float] | None:
        return signal_lookup.get(int(cand["rank"]))

    out = ranker.rank([weak, strong], ranker=fake, signals_for=signals_for)
    assert [c["rank"] for c in out] == [2, 1]


def test_rank_with_model_default_signals_resolver_zeros() -> None:
    fake = LinearRanker()
    fake.fit_calls.append(([], [], []))
    high = _candidate(_FULL_FACTORS, rank=1)
    low = _candidate({"hookStrength": 1, "emotionalFlow": 1, "perceivedValue": 1, "shareability": 1}, rank=2)
    # No signals_for -> default resolver returns None -> signals all zero, so the
    # linear model ranks purely on the factor columns.
    out = ranker.rank([low, high], ranker=fake)
    assert [c["rank"] for c in out] == [1, 2]


# --------------------------------------------------------------------------- #
# module surface: no heavy import at load time
# --------------------------------------------------------------------------- #
def test_module_does_not_import_lightgbm_at_load() -> None:
    import sys

    assert "lightgbm" not in sys.modules
