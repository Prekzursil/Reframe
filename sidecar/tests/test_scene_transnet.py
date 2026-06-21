"""Tests for media_studio.features.scene_transnet — TransNetV2 scene-cut seam.

The PURE half (rising-edge cut extraction, eps-merge with PySceneDetect, the
shared windowing grid, Signal-track assembly) is tested with hand-built numpy
arrays — no model, no video. The runner is tested with a FAKE backend_factory
whose ``predict`` returns a canned per-frame probability array and a FAKE
frame_loader returning synthetic numpy frames, plus the offline / no-source
degrade gates. No torch / tensorflow import anywhere.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest
from media_studio.features import scene_transnet as st


# --------------------------------------------------------------------------- #
# fakes (the injected seams)
# --------------------------------------------------------------------------- #
class FakeBackend:
    """A TransNetBackend whose predict returns a canned per-frame prob array."""

    def __init__(self, probs: Any, *, record: dict[str, Any] | None = None) -> None:
        self._probs = np.asarray(probs, dtype=float)
        self._record = record if record is not None else {}

    def predict(
        self,
        frames: np.ndarray,
        *,
        on_progress: Any = None,
        should_cancel: Any = None,
    ) -> np.ndarray:
        self._record["frames_shape"] = np.asarray(frames).shape
        if on_progress is not None:
            on_progress(50.0, "predicting")
        return self._probs


def make_factory(probs: Any, record: dict[str, Any] | None = None) -> Any:
    return lambda settings: FakeBackend(probs, record=record)


def fake_loader(probs_len: int = 4) -> Any:
    """Frame loader returning a synthetic NxHxWx3 uint8 stack."""
    return lambda path, fps: np.zeros((probs_len, 27, 48, 3), dtype="uint8")


# --------------------------------------------------------------------------- #
# pure: predictions_to_cuts
# --------------------------------------------------------------------------- #
class TestPredictionsToCuts:
    def test_single_rising_edge(self):
        probs = np.array([0.1, 0.2, 0.9, 0.3])
        # rising edge at frame 2 -> 2/10 = 0.2s
        assert st.predictions_to_cuts(probs, threshold=0.5, fps=10.0) == (0.2,)

    def test_dissolve_ramp_is_one_cut(self):
        # A multi-frame ramp staying above threshold = ONE cut at its leading
        # edge (a dissolve PySceneDetect misses, the WU3 acceptance).
        probs = np.array([0.0, 0.6, 0.7, 0.8, 0.9, 0.1])
        assert st.predictions_to_cuts(probs, threshold=0.5, fps=10.0) == (0.1,)

    def test_two_separate_cuts(self):
        probs = np.array([0.9, 0.1, 0.9, 0.1])
        # frame 0 rises (prev_above False) and frame 2 rises again
        assert st.predictions_to_cuts(probs, threshold=0.5, fps=10.0) == (0.0, 0.2)

    def test_nx1_output_flattened(self):
        probs = np.array([[0.1], [0.9], [0.2]])
        assert st.predictions_to_cuts(probs, threshold=0.5, fps=10.0) == (0.1,)

    def test_no_cuts(self):
        assert st.predictions_to_cuts(np.array([0.1, 0.2, 0.3]), threshold=0.5, fps=10.0) == ()

    def test_non_positive_fps_raises(self):
        with pytest.raises(ValueError):
            st.predictions_to_cuts(np.array([0.9]), threshold=0.5, fps=0.0)


# --------------------------------------------------------------------------- #
# pure: merge_with_pyscenedetect
# --------------------------------------------------------------------------- #
class TestMerge:
    def test_overlapping_within_eps_dedup(self):
        # 1.0 (transnet) and 1.1 (pyscene) within eps=0.25 -> keep the earlier
        assert st.merge_with_pyscenedetect([1.0], [1.1], eps=0.25) == (1.0,)

    def test_disjoint_preserved(self):
        # The fallback still works: a pyscene-only cut survives.
        assert st.merge_with_pyscenedetect([1.0], [5.0], eps=0.25) == (1.0, 5.0)

    def test_empty_transnet_keeps_pyscene(self):
        assert st.merge_with_pyscenedetect([], [2.0, 4.0], eps=0.25) == (2.0, 4.0)

    def test_non_numeric_filtered(self):
        assert st.merge_with_pyscenedetect([1.0, "x"], [2.0], eps=0.25) == (1.0, 2.0)

    def test_both_empty(self):
        assert st.merge_with_pyscenedetect([], [], eps=0.25) == ()


# --------------------------------------------------------------------------- #
# pure: sample_windows
# --------------------------------------------------------------------------- #
class TestSampleWindows:
    def test_basic_grid(self):
        assert st.sample_windows(3.0, 1.0, 1.0) == ((0.0, 1.0), (1.0, 2.0), (2.0, 3.0))

    def test_final_window_clamped(self):
        assert st.sample_windows(2.5, 1.0, 1.0) == ((0.0, 1.0), (1.0, 2.0), (2.0, 2.5))

    def test_overlapping_hop(self):
        assert st.sample_windows(2.0, 1.0, 0.5) == (
            (0.0, 1.0),
            (0.5, 1.5),
            (1.0, 2.0),
            (1.5, 2.0),
        )

    def test_zero_duration_empty(self):
        assert st.sample_windows(0.0) == ()

    def test_negative_duration_empty(self):
        assert st.sample_windows(-5.0) == ()

    def test_non_positive_step_raises(self):
        with pytest.raises(ValueError):
            st.sample_windows(3.0, 0.0, 1.0)


# --------------------------------------------------------------------------- #
# pure: emit_scene_signals
# --------------------------------------------------------------------------- #
class TestEmitSceneSignals:
    def test_cuts_become_instantaneous_signals(self):
        track = st.emit_scene_signals([1.0, 2.0], duration=10.0)
        assert track.channel == "sceneCut"
        assert track.present is True
        assert len(track.signals) == 2
        sig = track.signals[0]
        assert sig.start == sig.end == 1.0
        assert sig.value == 1.0
        assert sig.confidence == 1.0
        assert sig.meta == {}

    def test_out_of_range_cuts_dropped(self):
        track = st.emit_scene_signals([-1.0, 5.0, 20.0], duration=10.0)
        assert tuple(s.start for s in track.signals) == (5.0,)

    def test_empty_but_present(self):
        track = st.emit_scene_signals([], duration=10.0)
        assert track.signals == ()
        assert track.present is True

    def test_non_numeric_filtered(self):
        track = st.emit_scene_signals([1.0, "x"], duration=10.0)
        assert tuple(s.start for s in track.signals) == (1.0,)


# --------------------------------------------------------------------------- #
# pure: _as_1d
# --------------------------------------------------------------------------- #
class TestAs1d:
    def test_flattens_2d(self):
        out = st._as_1d(np.array([[0.1, 0.2], [0.3, 0.4]]))
        assert out.tolist() == [0.1, 0.2, 0.3, 0.4]


# --------------------------------------------------------------------------- #
# default_models_present
# --------------------------------------------------------------------------- #
class TestModelsPresent:
    def test_asset_machinery_failure_returns_false(self, monkeypatch):
        # get_asset returns None -> default_models_present is False (the entry-is
        # -None degrade arc / use the fallback). The module now registers its asset
        # at import (Wave-3 wiring), so force get_asset -> None to hit this branch.
        import media_studio.assets.manifest as manifest_mod

        monkeypatch.setattr(manifest_mod, "get_asset", lambda name: None)
        assert st.default_models_present({}) is False

    def test_installed_returns_true(self, monkeypatch):
        import media_studio.assets.manager as manager_mod
        import media_studio.assets.manifest as manifest_mod

        monkeypatch.setattr(manifest_mod, "get_asset", lambda name: object())

        class FakeMgr:
            def __init__(self, *, settings_provider):
                pass

            def installed_path(self, entry):
                return "/some/path"

        monkeypatch.setattr(manager_mod, "AssetManager", FakeMgr)
        assert st.default_models_present({}) is True

    def test_not_installed_returns_false(self, monkeypatch):
        import media_studio.assets.manager as manager_mod
        import media_studio.assets.manifest as manifest_mod

        monkeypatch.setattr(manifest_mod, "get_asset", lambda name: object())

        class FakeMgr:
            def __init__(self, *, settings_provider):
                pass

            def installed_path(self, entry):
                return None

        monkeypatch.setattr(manager_mod, "AssetManager", FakeMgr)
        assert st.default_models_present({}) is False

    def test_asset_lookup_exception_returns_false(self, monkeypatch):
        import media_studio.assets.manifest as manifest_mod

        def boom(name):
            raise RuntimeError("manifest exploded")

        monkeypatch.setattr(manifest_mod, "get_asset", boom)
        assert st.default_models_present({}) is False


# --------------------------------------------------------------------------- #
# compute_scene_cuts
# --------------------------------------------------------------------------- #
class TestComputeSceneCuts:
    def test_model_run_merges_with_fallback(self):
        # FakeBackend predicts a dissolve at frame 1 (0.1s @10fps); the
        # PySceneDetect fallback offers a disjoint cut at 5.0s. Both survive.
        record: dict[str, Any] = {}
        probs = [0.0, 0.9, 0.1, 0.1]
        cuts = st.compute_scene_cuts(
            "vid.mp4",
            fps_hint=10.0,
            backend_factory=make_factory(probs, record),
            frame_loader=fake_loader(4),
            scene_provider=lambda: [5.0],
            models_present=lambda s: True,
        )
        assert cuts == (0.1, 5.0)
        assert record["frames_shape"] == (4, 27, 48, 3)

    def test_dissolve_caught_that_pyscene_misses(self):
        # The model catches a dissolve; the fallback (pyscene) found nothing
        # there. This is the WU3 acceptance proven at the runner level.
        cuts = st.compute_scene_cuts(
            "vid.mp4",
            fps_hint=10.0,
            backend_factory=make_factory([0.0, 0.6, 0.7, 0.8]),
            frame_loader=fake_loader(4),
            scene_provider=lambda: [],
            models_present=lambda s: True,
        )
        assert cuts == (0.1,)

    def test_offline_no_model_uses_fallback_only(self):
        cuts = st.compute_scene_cuts(
            "vid.mp4",
            settings={"offline": True},
            scene_provider=lambda: [3.0, 7.0],
            models_present=lambda s: False,
        )
        assert cuts == (3.0, 7.0)

    def test_offline_no_model_no_provider_empty(self):
        cuts = st.compute_scene_cuts(
            "vid.mp4",
            settings={"offline": True},
            models_present=lambda s: False,
        )
        assert cuts == ()

    def test_online_no_model_no_provider_empty(self):
        # online but model not present and no fallback -> nothing to merge.
        cuts = st.compute_scene_cuts(
            "vid.mp4",
            settings={"offline": False},
            models_present=lambda s: False,
        )
        assert cuts == ()

    def test_default_fps_when_no_hint(self):
        # fps_hint omitted -> default 25fps; frame 25 = 1.0s.
        probs = [0.0] * 25 + [0.9]
        cuts = st.compute_scene_cuts(
            "vid.mp4",
            backend_factory=make_factory(probs),
            frame_loader=fake_loader(26),
            models_present=lambda s: True,
        )
        assert cuts == (1.0,)

    def test_backend_failure_degrades_to_fallback(self):
        def boom_loader(path, fps):
            raise RuntimeError("decode failed")

        cuts = st.compute_scene_cuts(
            "vid.mp4",
            fps_hint=10.0,
            backend_factory=make_factory([0.9]),
            frame_loader=boom_loader,
            scene_provider=lambda: [4.0],
            models_present=lambda s: True,
        )
        # model path raised -> degrades to the fallback cut only.
        assert cuts == (4.0,)


# --------------------------------------------------------------------------- #
# _fallback_cuts
# --------------------------------------------------------------------------- #
class TestFallbackCuts:
    def test_none_provider_empty(self):
        assert st._fallback_cuts(None) == ()

    def test_provider_failure_empty(self):
        def boom() -> list[float]:
            raise RuntimeError("scenedetect crashed")

        assert st._fallback_cuts(boom) == ()

    def test_sanitizes_and_sorts(self):
        assert st._fallback_cuts(lambda: [5.0, 1.0, "x", 1.0]) == (1.0, 5.0)


# --------------------------------------------------------------------------- #
# compute_scene_signals
# --------------------------------------------------------------------------- #
class TestComputeSceneSignals:
    def test_present_track_from_model(self):
        track = st.compute_scene_signals(
            "vid.mp4",
            duration=10.0,
            fps_hint=10.0,
            backend_factory=make_factory([0.0, 0.9, 0.1]),
            frame_loader=fake_loader(3),
            scene_provider=lambda: [],
            models_present=lambda s: True,
        )
        assert track.present is True
        assert track.fps_hint == 10.0
        assert tuple(s.start for s in track.signals) == (0.1,)

    def test_no_source_present_false(self):
        track = st.compute_scene_signals(
            "vid.mp4",
            duration=10.0,
            settings={"offline": True},
            models_present=lambda s: False,
        )
        assert track.present is False
        assert track.signals == ()

    def test_empty_but_present_when_source_exists(self):
        # A source exists (fallback provider) but it found no cuts -> present
        # with zero signals (a real "no scene changes" answer, not a degrade).
        track = st.compute_scene_signals(
            "vid.mp4",
            duration=10.0,
            settings={"offline": True},
            scene_provider=lambda: [],
            models_present=lambda s: False,
        )
        assert track.present is True
        assert track.signals == ()


# --------------------------------------------------------------------------- #
# _has_cut_source
# --------------------------------------------------------------------------- #
class TestHasCutSource:
    def test_provider_always_a_source(self):
        assert (
            st._has_cut_source(
                settings={"offline": True},
                scene_provider=lambda: [],
                models_present=lambda s: False,
            )
            is True
        )

    def test_installed_model_is_a_source(self):
        assert (
            st._has_cut_source(
                settings={"offline": True},
                scene_provider=None,
                models_present=lambda s: True,
            )
            is True
        )

    def test_online_no_model_is_a_source(self):
        # online -> the model could be fetched, so the modality is available.
        assert (
            st._has_cut_source(
                settings={"offline": False},
                scene_provider=None,
                models_present=lambda s: False,
            )
            is True
        )

    def test_offline_no_model_no_provider_not_a_source(self):
        assert (
            st._has_cut_source(
                settings={"offline": True},
                scene_provider=None,
                models_present=lambda s: False,
            )
            is False
        )

    def test_default_models_present_used_when_none(self):
        # models_present=None -> default_models_present (False, no asset), and
        # online -> still a source.
        assert (
            st._has_cut_source(
                settings={"offline": False},
                scene_provider=None,
                models_present=None,
            )
            is True
        )


# --------------------------------------------------------------------------- #
# module surface: no heavy import at load
# --------------------------------------------------------------------------- #
def test_no_heavy_imports_at_module_load():
    import sys

    assert "torch" not in sys.modules
    assert "tensorflow" not in sys.modules
