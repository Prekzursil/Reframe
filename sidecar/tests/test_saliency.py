"""Heavy-ML-free tests for the Phase-8 saliency module.

Every test drives the PURE half with hand-built numpy arrays, or the runner with
a FAKE backend + fake frame_loader injected through the seam — torch / the ViNet-S
model are NEVER imported. Real numpy is in the venv so numeric assertions are exact.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest
from media_studio.features import saliency
from media_studio.features.saliency import (
    Signal,
    SignalTrack,
    compute_saliency_signals,
    crop_centers_from_saliency,
    interestingness_curve,
    normalize_curve,
    sample_windows,
)


# --------------------------------------------------------------------------- #
# fakes
# --------------------------------------------------------------------------- #
class FakeBackend:
    """A fake SaliencyBackend: ``infer`` returns a pre-canned saliency stack."""

    def __init__(self, maps: np.ndarray) -> None:
        self._maps = maps
        self.calls = 0
        self.last_frames: np.ndarray | None = None

    def infer(self, frames: np.ndarray) -> np.ndarray:
        self.calls += 1
        self.last_frames = frames
        return self._maps


def _fake_loader(frames: list[np.ndarray]):
    """Build a frame_loader returning a fixed list, recording the call args."""
    seen: dict[str, Any] = {}

    def loader(path: str, timestamps):  # noqa: ANN001
        seen["path"] = path
        seen["timestamps"] = list(timestamps)
        return frames

    return loader, seen


# --------------------------------------------------------------------------- #
# sample_windows
# --------------------------------------------------------------------------- #
def test_sample_windows_tiles_duration() -> None:
    wins = sample_windows(3.0, win_sec=1.0, hop_sec=1.0)
    assert wins == ((0.0, 1.0), (1.0, 2.0), (2.0, 3.0))


def test_sample_windows_last_window_clamped_to_duration() -> None:
    wins = sample_windows(2.5, win_sec=1.0, hop_sec=1.0)
    assert wins[-1] == (2.0, 2.5)


def test_sample_windows_zero_duration_single_instant_window() -> None:
    assert sample_windows(0.0) == ((0.0, 0.0),)


def test_sample_windows_negative_duration_single_instant_window() -> None:
    assert sample_windows(-5.0) == ((0.0, 0.0),)


def test_sample_windows_hop_overlap() -> None:
    wins = sample_windows(2.0, win_sec=1.0, hop_sec=0.5)
    assert wins == ((0.0, 1.0), (0.5, 1.5), (1.0, 2.0), (1.5, 2.0))


def test_sample_windows_nonpositive_win_and_hop_floored() -> None:
    # win_sec/hop_sec <= 0 are floored to a tiny positive epsilon (no infinite loop).
    wins = sample_windows(1e-5, win_sec=0.0, hop_sec=0.0)
    assert len(wins) >= 1
    assert all(0.0 <= s <= e for s, e in wins)


# --------------------------------------------------------------------------- #
# normalize_curve
# --------------------------------------------------------------------------- #
def test_normalize_curve_minmax() -> None:
    assert normalize_curve([0.0, 5.0, 10.0]) == [0.0, 0.5, 1.0]


def test_normalize_curve_flat_maps_to_zeros() -> None:
    assert normalize_curve([7.0, 7.0, 7.0]) == [0.0, 0.0, 0.0]


def test_normalize_curve_empty() -> None:
    assert normalize_curve([]) == []


def test_normalize_curve_clamps_within_unit_interval() -> None:
    out = normalize_curve([-3.0, 0.0, 4.0])
    assert min(out) == 0.0
    assert max(out) == 1.0


# --------------------------------------------------------------------------- #
# interestingness_curve
# --------------------------------------------------------------------------- #
def test_interestingness_curve_peaked_frame_scores_high() -> None:
    flat = np.ones((4, 4), dtype=np.float64)  # uniform -> peak/mean ~ 1
    peaked = np.zeros((4, 4), dtype=np.float64)
    peaked[1, 1] = 100.0  # sharp peak -> high peak/mean
    maps = np.stack([flat, peaked])
    curve = interestingness_curve(maps)
    assert curve == [0.0, 1.0]


def test_interestingness_curve_all_in_unit_interval() -> None:
    rng = np.random.default_rng(0)
    maps = rng.random((5, 8, 8))
    curve = interestingness_curve(maps)
    assert len(curve) == 5
    assert all(0.0 <= v <= 1.0 for v in curve)


def test_interestingness_curve_empty_size() -> None:
    assert interestingness_curve(np.zeros((0, 4, 4))) == []


def test_interestingness_curve_empty_array() -> None:
    assert interestingness_curve(np.array([])) == []


# --------------------------------------------------------------------------- #
# crop_centers_from_saliency
# --------------------------------------------------------------------------- #
def test_crop_centers_hot_region_lands_on_argmax() -> None:
    m = np.zeros((1, 5, 5), dtype=np.float64)
    m[0, 4, 4] = 1.0  # bottom-right corner -> (1.0, 1.0)
    centers = crop_centers_from_saliency(m)
    assert centers == [(1.0, 1.0)]


def test_crop_centers_top_left_corner() -> None:
    m = np.zeros((1, 5, 5), dtype=np.float64)
    m[0, 0, 0] = 1.0
    assert crop_centers_from_saliency(m) == [(0.0, 0.0)]


def test_crop_centers_single_pixel_map_no_division_by_zero() -> None:
    m = np.ones((1, 1, 1), dtype=np.float64)
    assert crop_centers_from_saliency(m) == [(0.0, 0.0)]


def test_crop_centers_empty_size() -> None:
    assert crop_centers_from_saliency(np.zeros((0, 4, 4))) == []


def test_crop_centers_empty_array() -> None:
    assert crop_centers_from_saliency(np.array([])) == []


def test_crop_centers_multi_frame() -> None:
    m = np.zeros((2, 3, 3), dtype=np.float64)
    m[0, 0, 2] = 1.0  # top-right -> (cx=1.0, cy=0.0)
    m[1, 2, 0] = 1.0  # bottom-left -> (cx=0.0, cy=1.0)
    assert crop_centers_from_saliency(m) == [(1.0, 0.0), (0.0, 1.0)]


# --------------------------------------------------------------------------- #
# compute_saliency_signals — happy path via fakes
# --------------------------------------------------------------------------- #
def _maps_for(n: int) -> np.ndarray:
    """A NxHxW stack: frame i has a peak at [1,1] whose strength grows with i.

    The base is a small ramp (not flat) so every frame has a strict argmax at
    [1,1] -> a stable, non-degenerate crop center even for frame 0.
    """
    maps = np.ones((n, 4, 4), dtype=np.float64)
    for i in range(n):
        maps[i, 1, 1] = 2.0 + i * 10.0
    return maps


def test_compute_emits_one_signal_per_window_normalized() -> None:
    frames = [np.zeros((4, 4, 3), dtype=np.uint8) for _ in range(3)]
    loader, seen = _fake_loader(frames)
    backend = FakeBackend(_maps_for(3))
    track = compute_saliency_signals(
        "video.mp4",
        3.0,
        backend_factory=lambda _s: backend,
        frame_loader=loader,
        models_present=lambda _s: True,
    )
    assert isinstance(track, SignalTrack)
    assert track.present is True
    assert track.channel == "saliency"
    assert len(track.signals) == 3
    assert all(s.channel == "saliency" for s in track.signals)
    assert all(0.0 <= s.value <= 1.0 for s in track.signals)
    # the last (strongest peak) window is maximally interesting
    assert track.signals[-1].value == 1.0
    assert track.signals[0].value == 0.0
    # crop center stashed in meta
    assert track.signals[0].meta["cropCenter"] == [pytest.approx(1 / 3), pytest.approx(1 / 3)]
    # backend ran once over the loaded frames
    assert backend.calls == 1
    assert seen["path"] == "video.mp4"


def test_compute_invokes_progress_callback() -> None:
    frames = [np.zeros((4, 4, 3), dtype=np.uint8) for _ in range(2)]
    loader, _ = _fake_loader(frames)
    events: list[tuple[float, str]] = []
    compute_saliency_signals(
        "v.mp4",
        2.0,
        backend_factory=lambda _s: FakeBackend(_maps_for(2)),
        frame_loader=loader,
        models_present=lambda _s: True,
        on_progress=lambda pct, msg: events.append((pct, msg)),
    )
    assert events[0] == (5.0, "sampling frames for saliency")
    assert events[-1] == (100.0, "saliency done")


def test_compute_more_windows_than_curve_entries_fills_zero() -> None:
    # backend returns FEWER maps than windows -> trailing windows get value 0.0
    # and no cropCenter meta (defensive index guards).
    frames = [np.zeros((4, 4, 3), dtype=np.uint8) for _ in range(3)]
    loader, _ = _fake_loader(frames)
    backend = FakeBackend(_maps_for(1))  # only 1 map for 3 windows
    track = compute_saliency_signals(
        "v.mp4",
        3.0,
        backend_factory=lambda _s: backend,
        frame_loader=loader,
        models_present=lambda _s: True,
    )
    assert len(track.signals) == 3
    assert track.signals[1].value == 0.0
    assert track.signals[2].value == 0.0
    assert track.signals[1].meta == {}


# --------------------------------------------------------------------------- #
# compute_saliency_signals — degrade + edge branches
# --------------------------------------------------------------------------- #
def test_compute_offline_missing_model_degrades() -> None:
    track = compute_saliency_signals(
        "v.mp4",
        3.0,
        settings={"offline": True},
        backend_factory=lambda _s: pytest.fail("backend must not be built"),  # type: ignore[arg-type,return-value]
        frame_loader=lambda _p, _t: pytest.fail("loader must not run"),  # type: ignore[arg-type,return-value]
        models_present=lambda _s: False,
    )
    assert track.present is False
    assert track.signals == ()
    assert track.channel == "saliency"


def test_compute_offline_but_model_present_runs() -> None:
    frames = [np.zeros((4, 4, 3), dtype=np.uint8)]
    loader, _ = _fake_loader(frames)
    track = compute_saliency_signals(
        "v.mp4",
        1.0,
        settings={"offline": True},
        backend_factory=lambda _s: FakeBackend(_maps_for(1)),
        frame_loader=loader,
        models_present=lambda _s: True,
    )
    assert track.present is True
    assert len(track.signals) == 1


def test_compute_online_missing_model_still_runs() -> None:
    # online (not offline) + missing model -> the gate does not trip; backend runs.
    frames = [np.zeros((4, 4, 3), dtype=np.uint8)]
    loader, _ = _fake_loader(frames)
    track = compute_saliency_signals(
        "v.mp4",
        1.0,
        settings={"offline": False},
        backend_factory=lambda _s: FakeBackend(_maps_for(1)),
        frame_loader=loader,
        models_present=lambda _s: False,
    )
    assert track.present is True


def test_compute_no_frames_emits_single_neutral_signal() -> None:
    track = compute_saliency_signals(
        "v.mp4",
        3.0,
        backend_factory=lambda _s: pytest.fail("backend must not run with no frames"),  # type: ignore[arg-type,return-value]
        frame_loader=lambda _p, _t: [],
        models_present=lambda _s: True,
    )
    assert track.present is True
    assert len(track.signals) == 1
    assert track.signals[0].value == 0.0
    assert track.signals[0].start == 0.0


def test_compute_cancelled_before_load_returns_empty_present_track() -> None:
    track = compute_saliency_signals(
        "v.mp4",
        3.0,
        backend_factory=lambda _s: pytest.fail("backend must not run when cancelled"),  # type: ignore[arg-type,return-value]
        frame_loader=lambda _p, _t: pytest.fail("loader must not run when cancelled"),  # type: ignore[arg-type,return-value]
        models_present=lambda _s: True,
        should_cancel=lambda: True,
    )
    assert track.present is True
    assert track.signals == ()


def test_compute_not_cancelled_runs_normally() -> None:
    frames = [np.zeros((4, 4, 3), dtype=np.uint8)]
    loader, _ = _fake_loader(frames)
    track = compute_saliency_signals(
        "v.mp4",
        1.0,
        backend_factory=lambda _s: FakeBackend(_maps_for(1)),
        frame_loader=loader,
        models_present=lambda _s: True,
        should_cancel=lambda: False,
    )
    assert track.present is True


def test_compute_loader_returns_none_treated_as_no_frames() -> None:
    track = compute_saliency_signals(
        "v.mp4",
        1.0,
        backend_factory=lambda _s: pytest.fail("backend must not run"),  # type: ignore[arg-type,return-value]
        frame_loader=lambda _p, _t: None,  # type: ignore[arg-type,return-value]
        models_present=lambda _s: True,
    )
    assert track.present is True
    assert len(track.signals) == 1


def test_compute_default_settings_none() -> None:
    # settings=None path: not offline by default (no MEDIA_STUDIO_OFFLINE in env
    # for tests) -> with models present, runs.
    frames = [np.zeros((4, 4, 3), dtype=np.uint8)]
    loader, _ = _fake_loader(frames)
    track = compute_saliency_signals(
        "v.mp4",
        1.0,
        backend_factory=lambda _s: FakeBackend(_maps_for(1)),
        frame_loader=loader,
        models_present=lambda _s: True,
    )
    assert track.present is True


# --------------------------------------------------------------------------- #
# default_models_present (pure asset-manager check, no heavy import)
# --------------------------------------------------------------------------- #
def test_default_models_present_unregistered_asset_is_false() -> None:
    # ASSET_NAME is not registered in the manifest by default -> False.
    assert saliency.default_models_present({}) is False


def test_default_models_present_registered_but_not_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    from media_studio.assets import manifest

    fake_entry = object()

    class _FakeMgr:
        def __init__(self, **_kw: Any) -> None: ...

        def installed_path(self, _entry: Any) -> str | None:
            return None

    monkeypatch.setattr(manifest, "get_asset", lambda _name: fake_entry)
    import media_studio.assets.manager as manager_mod

    monkeypatch.setattr(manager_mod, "AssetManager", _FakeMgr)
    assert saliency.default_models_present({"x": 1}) is False


def test_default_models_present_installed_is_true(monkeypatch: pytest.MonkeyPatch) -> None:
    from media_studio.assets import manifest

    class _FakeMgr:
        def __init__(self, **_kw: Any) -> None: ...

        def installed_path(self, _entry: Any) -> str | None:
            return "/cache/vinet-s.pt"

    monkeypatch.setattr(manifest, "get_asset", lambda _name: object())
    import media_studio.assets.manager as manager_mod

    monkeypatch.setattr(manager_mod, "AssetManager", _FakeMgr)
    assert saliency.default_models_present({}) is True


# --------------------------------------------------------------------------- #
# Signal / SignalTrack dataclasses
# --------------------------------------------------------------------------- #
def test_signal_defaults() -> None:
    s = Signal(channel="saliency", start=0.0, end=1.0, value=0.5)
    assert s.confidence == 1.0
    assert s.meta == {}


def test_signal_is_frozen() -> None:
    s = Signal(channel="saliency", start=0.0, end=1.0, value=0.5)
    with pytest.raises(Exception):  # noqa: B017,PT011 - FrozenInstanceError
        s.value = 0.9  # type: ignore[misc]


def test_signaltrack_fps_hint_default() -> None:
    t = SignalTrack(channel="saliency", signals=(), present=True)
    assert t.fps_hint is None
