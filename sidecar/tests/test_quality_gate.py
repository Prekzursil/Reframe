"""Tests for media_studio.features.quality_gate — DOVER late re-rank gate.

The PURE half (QualityScore combine math, demote_factor floor clamping,
apply_quality_gate demotion + re-rank + no-op) is tested with hand-built scores.
``compute_quality_scores`` is driven by a FAKE DoverBackend + fake frame loader
+ fake models_present so no torch / DOVER / cv2 is ever imported. Real numpy is
available, so numeric assertions are exact.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
import pytest
from media_studio.features import quality_gate as qg


# --------------------------------------------------------------------------- #
# fakes
# --------------------------------------------------------------------------- #
class FakeDover:
    """A DoverBackend returning canned (technical, aesthetic) pairs in order."""

    def __init__(self, pairs: Sequence[tuple[float, float]]) -> None:
        self._pairs = list(pairs)
        self.calls: list[Any] = []

    def assess(self, frames: np.ndarray) -> tuple[float, float]:
        self.calls.append(frames)
        return self._pairs[len(self.calls) - 1]


def _cand(rank: int, score: float, **extra: Any) -> dict[str, Any]:
    """A minimal §3 Candidate dict."""
    base: dict[str, Any] = {
        "rank": rank,
        "start": 0.0,
        "end": 10.0,
        "durationSec": 10.0,
        "hook": f"hook {rank}",
        "why": "because",
        "score": score,
        "sourceStart": 0.0,
    }
    base.update(extra)
    return base


# --------------------------------------------------------------------------- #
# pure: combine_quality
# --------------------------------------------------------------------------- #
class TestCombineQuality:
    def test_weighted_combine(self):
        # 0.6*1.0 + 0.4*0.0 == 0.6
        assert qg.combine_quality(1.0, 0.0) == pytest.approx(0.6)

    def test_clamps_above_one(self):
        assert qg.combine_quality(2.0, 2.0) == pytest.approx(1.0)

    def test_clamps_below_zero(self):
        assert qg.combine_quality(-1.0, -1.0) == pytest.approx(0.0)

    def test_weights_sum_to_one(self):
        assert pytest.approx(1.0) == qg.TECHNICAL_WEIGHT + qg.AESTHETIC_WEIGHT


# --------------------------------------------------------------------------- #
# pure: make_quality_score
# --------------------------------------------------------------------------- #
class TestMakeQualityScore:
    def test_normalizes_and_combines(self):
        qs = qg.make_quality_score(1.0, 0.5)
        assert qs.technical == pytest.approx(1.0)
        assert qs.aesthetic == pytest.approx(0.5)
        assert qs.overall == pytest.approx(0.6 * 1.0 + 0.4 * 0.5)

    def test_clamps_raw_inputs(self):
        qs = qg.make_quality_score(5.0, -3.0)
        assert qs.technical == 1.0
        assert qs.aesthetic == 0.0
        assert 0.0 <= qs.overall <= 1.0

    def test_is_frozen(self):
        import dataclasses

        qs = qg.make_quality_score(0.5, 0.5)
        with pytest.raises(dataclasses.FrozenInstanceError):
            qs.technical = 0.1  # type: ignore[misc]


# --------------------------------------------------------------------------- #
# pure: demote_factor
# --------------------------------------------------------------------------- #
class TestDemoteFactor:
    def test_pristine_keeps_full_relevance(self):
        qs = qg.QualityScore(technical=1.0, aesthetic=1.0, overall=1.0)
        assert qg.demote_factor(qs) == pytest.approx(1.0)

    def test_worst_hits_floor(self):
        qs = qg.QualityScore(technical=0.0, aesthetic=0.0, overall=0.0)
        assert qg.demote_factor(qs, floor=0.3) == pytest.approx(0.3)

    def test_linear_midpoint(self):
        qs = qg.QualityScore(technical=0.5, aesthetic=0.5, overall=0.5)
        # floor + (1-floor)*overall = 0.2 + 0.8*0.5 = 0.6
        assert qg.demote_factor(qs, floor=0.2) == pytest.approx(0.6)

    def test_floor_clamped_above_one(self):
        qs = qg.QualityScore(technical=0.0, aesthetic=0.0, overall=0.0)
        # floor clamped to 1.0 -> factor 1.0 regardless of overall
        assert qg.demote_factor(qs, floor=2.0) == pytest.approx(1.0)

    def test_floor_clamped_below_zero(self):
        qs = qg.QualityScore(technical=0.0, aesthetic=0.0, overall=0.0)
        # floor clamped to 0.0 -> factor 0.0 at overall 0
        assert qg.demote_factor(qs, floor=-1.0) == pytest.approx(0.0)

    def test_overall_clamped(self):
        qs = qg.QualityScore(technical=0.0, aesthetic=0.0, overall=5.0)
        # overall clamped to 1.0 -> full factor
        assert qg.demote_factor(qs, floor=0.3) == pytest.approx(1.0)


# --------------------------------------------------------------------------- #
# pure: apply_quality_gate
# --------------------------------------------------------------------------- #
class TestApplyQualityGate:
    def test_low_quality_clip_demoted_below_high(self):
        # Two clips with EQUAL legacy score; the low-quality one must drop below.
        cands = [_cand(1, 50.0), _cand(2, 50.0)]
        scores = [
            qg.QualityScore(technical=0.1, aesthetic=0.1, overall=0.1),  # clip 0 poor
            qg.QualityScore(technical=1.0, aesthetic=1.0, overall=1.0),  # clip 1 great
        ]
        out = qg.apply_quality_gate(cands, scores, floor=0.3)
        # The high-quality clip (originally rank 2) is now rank 1.
        assert out[0]["hook"] == "hook 2"
        assert out[1]["hook"] == "hook 1"
        assert out[0]["rank"] == 1
        assert out[1]["rank"] == 2
        # qualityScore stamped from overall.
        assert out[0]["qualityScore"] == pytest.approx(1.0)
        assert out[1]["qualityScore"] == pytest.approx(0.1)

    def test_score_is_demoted_multiplicatively(self):
        cands = [_cand(1, 100.0)]
        scores = [qg.QualityScore(technical=0.0, aesthetic=0.0, overall=0.0)]
        out = qg.apply_quality_gate(cands, scores, floor=0.3)
        # factor 0.3 -> 100 * 0.3 == 30
        assert out[0]["score"] == pytest.approx(30.0)

    def test_empty_scores_is_noop_unchanged_order(self):
        cands = [_cand(1, 10.0), _cand(2, 90.0)]
        out = qg.apply_quality_gate(cands, [])
        assert out == cands
        # Same objects' content; order preserved (no re-rank).
        assert [c["hook"] for c in out] == ["hook 1", "hook 2"]

    def test_inputs_not_mutated(self):
        cands = [_cand(1, 50.0)]
        scores = [qg.QualityScore(technical=0.5, aesthetic=0.5, overall=0.5)]
        qg.apply_quality_gate(cands, scores)
        assert cands[0]["score"] == 50.0
        assert "qualityScore" not in cands[0]

    def test_more_candidates_than_scores_keeps_unpaired(self):
        # 3 candidates, only 2 scores: the 3rd is kept untouched in ranking.
        cands = [_cand(1, 10.0), _cand(2, 20.0), _cand(3, 99.0)]
        scores = [
            qg.QualityScore(technical=1.0, aesthetic=1.0, overall=1.0),
            qg.QualityScore(technical=1.0, aesthetic=1.0, overall=1.0),
        ]
        out = qg.apply_quality_gate(cands, scores)
        # Unpaired high-score clip (99) keeps its score and sorts to the top.
        top = out[0]
        assert top["hook"] == "hook 3"
        assert top["score"] == pytest.approx(99.0)
        assert "qualityScore" not in top  # never assessed
        # The two scored ones got qualityScore stamped.
        scored = [c for c in out if "qualityScore" in c]
        assert len(scored) == 2

    def test_missing_score_field_defaults_zero(self):
        cand = _cand(1, 0.0)
        del cand["score"]
        scores = [qg.QualityScore(technical=1.0, aesthetic=1.0, overall=1.0)]
        out = qg.apply_quality_gate([cand], scores)
        assert out[0]["score"] == pytest.approx(0.0)

    def test_stable_tie_order(self):
        # Equal demoted scores -> input order preserved.
        cands = [_cand(1, 50.0), _cand(2, 50.0)]
        scores = [
            qg.QualityScore(technical=1.0, aesthetic=1.0, overall=1.0),
            qg.QualityScore(technical=1.0, aesthetic=1.0, overall=1.0),
        ]
        out = qg.apply_quality_gate(cands, scores)
        assert [c["hook"] for c in out] == ["hook 1", "hook 2"]


# --------------------------------------------------------------------------- #
# compute_quality_scores — fake seams (no torch / cv2)
# --------------------------------------------------------------------------- #
class TestComputeQualityScores:
    def test_assesses_each_clip(self):
        cands = [_cand(1, 10.0), _cand(2, 20.0)]
        fake = FakeDover([(0.2, 0.3), (0.9, 0.8)])
        frames = [np.zeros((2, 4, 4, 3), dtype=np.uint8), np.ones((2, 4, 4, 3), dtype=np.uint8)]
        scores = qg.compute_quality_scores(
            "video.mp4",
            cands,
            backend_factory=lambda _s: fake,
            frame_loader=lambda _p, _c: frames,
            models_present=lambda _s: True,
        )
        assert len(scores) == 2
        assert scores[0].technical == pytest.approx(0.2)
        assert scores[1].aesthetic == pytest.approx(0.8)
        # The loader's frames were passed to the backend in order.
        assert len(fake.calls) == 2

    def test_empty_candidates_returns_empty(self):
        scores = qg.compute_quality_scores(
            "video.mp4",
            [],
            backend_factory=lambda _s: FakeDover([]),
            frame_loader=lambda _p, _c: [],
            models_present=lambda _s: True,
        )
        assert scores == []

    def test_missing_model_offline_is_noop(self):
        scores = qg.compute_quality_scores(
            "video.mp4",
            [_cand(1, 10.0)],
            settings={"offline": True},
            backend_factory=lambda _s: FakeDover([(0.5, 0.5)]),
            frame_loader=lambda _p, _c: [np.zeros((1, 2, 2, 3), dtype=np.uint8)],
            models_present=lambda _s: False,
        )
        assert scores == []

    def test_missing_model_online_still_runs(self):
        # Online + missing: the lazy backend would fetch; here the fake runs.
        fake = FakeDover([(0.7, 0.6)])
        scores = qg.compute_quality_scores(
            "video.mp4",
            [_cand(1, 10.0)],
            settings={"offline": False},
            backend_factory=lambda _s: fake,
            frame_loader=lambda _p, _c: [np.zeros((1, 2, 2, 3), dtype=np.uint8)],
            models_present=lambda _s: False,
        )
        assert len(scores) == 1
        assert scores[0].technical == pytest.approx(0.7)

    def test_progress_callback_invoked(self):
        seen: list[tuple[float, str]] = []
        qg.compute_quality_scores(
            "video.mp4",
            [_cand(1, 10.0)],
            backend_factory=lambda _s: FakeDover([(0.5, 0.5)]),
            frame_loader=lambda _p, _c: [np.zeros((1, 2, 2, 3), dtype=np.uint8)],
            models_present=lambda _s: True,
            on_progress=lambda pct, msg: seen.append((pct, msg)),
        )
        assert seen == [(100.0, "assessed clip 1/1")]

    def test_should_cancel_stops_early(self):
        cands = [_cand(1, 10.0), _cand(2, 20.0), _cand(3, 30.0)]
        fake = FakeDover([(0.5, 0.5), (0.5, 0.5), (0.5, 0.5)])
        scores = qg.compute_quality_scores(
            "video.mp4",
            cands,
            backend_factory=lambda _s: fake,
            frame_loader=lambda _p, _c: [np.zeros((1, 2, 2, 3), dtype=np.uint8)] * 3,
            models_present=lambda _s: True,
            should_cancel=lambda: True,  # cancel before the first clip
        )
        assert scores == []

    def test_loader_short_uses_empty_frame_stack(self):
        # Loader returns FEWER frame stacks than candidates -> the missing clip
        # gets an empty stack (the _empty_frames degrade path).
        cands = [_cand(1, 10.0), _cand(2, 20.0)]
        fake = FakeDover([(0.4, 0.4), (0.6, 0.6)])
        scores = qg.compute_quality_scores(
            "video.mp4",
            cands,
            backend_factory=lambda _s: fake,
            frame_loader=lambda _p, _c: [np.zeros((1, 2, 2, 3), dtype=np.uint8)],  # only 1
            models_present=lambda _s: True,
        )
        assert len(scores) == 2
        # The 2nd clip's frames were the empty stack.
        assert fake.calls[1].shape == (0, 0, 0, 3)

    def test_default_settings_none(self):
        # settings=None branch -> {} ; model present so it runs.
        scores = qg.compute_quality_scores(
            "video.mp4",
            [_cand(1, 10.0)],
            backend_factory=lambda _s: FakeDover([(0.5, 0.5)]),
            frame_loader=lambda _p, _c: [np.zeros((1, 2, 2, 3), dtype=np.uint8)],
            models_present=lambda _s: True,
        )
        assert len(scores) == 1


# --------------------------------------------------------------------------- #
# _empty_frames helper
# --------------------------------------------------------------------------- #
def test_empty_frames_shape():
    ef = qg._empty_frames()
    assert ef.shape == (0, 0, 0, 3)
    assert ef.dtype == np.uint8


# --------------------------------------------------------------------------- #
# default seams (lazy importers) — exercised without the heavy stack
# --------------------------------------------------------------------------- #
class TestDefaultSeams:
    def test_default_models_present_no_entry(self, monkeypatch: pytest.MonkeyPatch):
        # manifest has no DOVER asset registered -> False, no heavy import.
        from media_studio.assets import manifest

        monkeypatch.setattr(manifest, "get_asset", lambda _name: None)
        assert qg.default_models_present({}) is False

    def test_default_models_present_with_entry_installed(self, monkeypatch: pytest.MonkeyPatch):
        from media_studio.assets import manager as manager_mod
        from media_studio.assets import manifest

        sentinel_entry = object()
        monkeypatch.setattr(manifest, "get_asset", lambda _name: sentinel_entry)

        class FakeMgr:
            def __init__(self, *_a: Any, **_k: Any) -> None:
                pass

            def installed_path(self, entry: Any) -> str | None:
                assert entry is sentinel_entry
                return "/some/path"

        monkeypatch.setattr(manager_mod, "AssetManager", FakeMgr)
        assert qg.default_models_present({}) is True

    def test_default_models_present_with_entry_missing(self, monkeypatch: pytest.MonkeyPatch):
        from media_studio.assets import manager as manager_mod
        from media_studio.assets import manifest

        monkeypatch.setattr(manifest, "get_asset", lambda _name: object())

        class FakeMgr:
            def __init__(self, *_a: Any, **_k: Any) -> None:
                pass

            def installed_path(self, _entry: Any) -> str | None:
                return None

        monkeypatch.setattr(manager_mod, "AssetManager", FakeMgr)
        assert qg.default_models_present({}) is False

    def test_default_backend_factory_lazy_imports(self):
        backend = qg._default_backend_factory({})
        # Real DoverMobileBackend (excluded from coverage); construction is cheap.
        from media_studio.features.quality_gate_backend import DoverMobileBackend

        assert isinstance(backend, DoverMobileBackend)

    def test_default_frame_loader_lazy_imports(self):
        # The default loader imports the backend's load_clip_frames; calling it
        # raises NotImplementedError (stub) without importing torch.
        with pytest.raises(NotImplementedError):
            qg._default_frame_loader("video.mp4", [_cand(1, 10.0)])
