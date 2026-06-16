"""Tests for the Tier-0 motion-energy signal module (heavy-ML-free).

cv2 IS in the venv, so the pure measures (``frame_diff_energy`` /
``farneback_flow_magnitude``) run for real over hand-built numpy frames. The
frame-LOADING seam is faked everywhere (no real video / VideoCapture). The
optional :class:`MotionBackend` is exercised via a tiny fake — no NeuFlow weights.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np
import pytest
from media_studio.features import motion


# --------------------------------------------------------------------------- #
# fakes / fixtures
# --------------------------------------------------------------------------- #
def _frame(value: int, shape: tuple[int, int, int] = (8, 8, 3)) -> np.ndarray:
    """A solid-colour BGR frame filled with ``value``."""
    return np.full(shape, value, dtype=np.uint8)


def _noisy_frame(seed: int, shape: tuple[int, int, int] = (8, 8, 3)) -> np.ndarray:
    """A reproducible random BGR frame (high diff vs a solid frame)."""
    rng = np.random.default_rng(seed)
    return rng.integers(0, 256, size=shape, dtype=np.uint8)


def _loader_returning(frames: list[np.ndarray]) -> motion.FrameLoader:
    """A fake FrameLoader that ignores the path/timestamps and returns ``frames``."""

    def _load(path: str, timestamps: Sequence[float]) -> list[np.ndarray]:
        assert isinstance(path, str)
        assert len(timestamps) >= 1
        return list(frames)

    return _load


# --------------------------------------------------------------------------- #
# frame_diff_energy
# --------------------------------------------------------------------------- #
def test_frame_diff_energy_identical_is_zero() -> None:
    a = _frame(100)
    assert motion.frame_diff_energy(a, a) == 0.0


def test_frame_diff_energy_max_is_one() -> None:
    black = _frame(0)
    white = _frame(255)
    assert motion.frame_diff_energy(black, white) == pytest.approx(1.0)


def test_frame_diff_energy_partial_in_unit_range() -> None:
    val = motion.frame_diff_energy(_frame(0), _frame(128))
    assert 0.0 < val < 1.0
    assert val == pytest.approx(128 / 255.0)


def test_frame_diff_energy_shape_mismatch_raises() -> None:
    with pytest.raises(ValueError, match="shape mismatch"):
        motion.frame_diff_energy(_frame(0, (8, 8, 3)), _frame(0, (4, 4, 3)))


# --------------------------------------------------------------------------- #
# farneback_flow_magnitude
# --------------------------------------------------------------------------- #
def test_flow_magnitude_static_is_low() -> None:
    gray = np.zeros((32, 32), dtype=np.uint8)
    val = motion.farneback_flow_magnitude(gray, gray)
    assert val == pytest.approx(0.0, abs=1e-6)


def test_flow_magnitude_moving_pattern_in_range() -> None:
    prev = np.zeros((48, 48), dtype=np.uint8)
    prev[10:30, 10:20] = 255
    cur = np.zeros((48, 48), dtype=np.uint8)
    cur[10:30, 25:35] = 255  # shifted right -> real flow
    val = motion.farneback_flow_magnitude(prev, cur)
    assert 0.0 <= val < 1.0
    assert val > 0.0  # some motion was detected


def test_flow_magnitude_shape_mismatch_raises() -> None:
    with pytest.raises(ValueError, match="shape mismatch"):
        motion.farneback_flow_magnitude(np.zeros((8, 8), np.uint8), np.zeros((4, 4), np.uint8))


# --------------------------------------------------------------------------- #
# sample_windows
# --------------------------------------------------------------------------- #
def test_sample_windows_basic_grid() -> None:
    wins = motion.sample_windows(3.0, win_sec=1.0, hop_sec=1.0)
    assert wins == ((0.0, 1.0), (1.0, 2.0), (2.0, 3.0))


def test_sample_windows_last_window_clamped_to_duration() -> None:
    wins = motion.sample_windows(2.5, win_sec=1.0, hop_sec=1.0)
    assert wins[-1] == (2.0, 2.5)


def test_sample_windows_overlapping_hop() -> None:
    wins = motion.sample_windows(2.0, win_sec=1.0, hop_sec=0.5)
    assert wins[0] == (0.0, 1.0)
    assert wins[1] == (0.5, 1.5)


def test_sample_windows_zero_duration_single_empty_window() -> None:
    assert motion.sample_windows(0.0) == ((0.0, 0.0),)


def test_sample_windows_negative_duration_single_empty_window() -> None:
    assert motion.sample_windows(-5.0) == ((0.0, 0.0),)


@pytest.mark.parametrize(("win", "hop"), [(0.0, 1.0), (1.0, 0.0), (-1.0, 1.0)])
def test_sample_windows_nonpositive_step_raises(win: float, hop: float) -> None:
    with pytest.raises(ValueError, match="must be positive"):
        motion.sample_windows(3.0, win_sec=win, hop_sec=hop)


# --------------------------------------------------------------------------- #
# normalize_curve
# --------------------------------------------------------------------------- #
def test_normalize_curve_empty() -> None:
    assert motion.normalize_curve([]) == []


def test_normalize_curve_flat_is_all_zero() -> None:
    assert motion.normalize_curve([0.5, 0.5, 0.5]) == [0.0, 0.0, 0.0]


def test_normalize_curve_minmax() -> None:
    out = motion.normalize_curve([1.0, 2.0, 3.0])
    assert out == [0.0, 0.5, 1.0]


def test_normalize_curve_clamps_negatives() -> None:
    out = motion.normalize_curve([-2.0, 0.0, 2.0])
    assert out[0] == 0.0
    assert out[-1] == 1.0
    assert all(0.0 <= v <= 1.0 for v in out)


# --------------------------------------------------------------------------- #
# _to_gray
# --------------------------------------------------------------------------- #
def test_to_gray_converts_bgr() -> None:
    gray = motion._to_gray(_frame(100, (8, 8, 3)))
    assert gray.ndim == 2
    assert gray.shape == (8, 8)


def test_to_gray_passes_through_2d() -> None:
    g = np.zeros((8, 8), dtype=np.uint8)
    out = motion._to_gray(g)
    assert out is g


# --------------------------------------------------------------------------- #
# _window_value
# --------------------------------------------------------------------------- #
def test_window_value_no_pairs_is_zero() -> None:
    assert motion._window_value([], 3, 0) == 0.0
    assert motion._window_value([], 3, 2) == 0.0


def test_window_value_first_window_mirrors_next() -> None:
    assert motion._window_value([0.4, 0.9], 3, 0) == 0.4


def test_window_value_first_window_single_window_is_zero() -> None:
    assert motion._window_value([0.4], 1, 0) == 0.0


def test_window_value_maps_to_incoming_pair() -> None:
    assert motion._window_value([0.4, 0.9], 3, 1) == 0.4
    assert motion._window_value([0.4, 0.9], 3, 2) == 0.9


def test_window_value_out_of_range_pair_is_zero() -> None:
    # window index whose pair_idx exceeds the available pair scores
    assert motion._window_value([0.4], 3, 2) == 0.0


# --------------------------------------------------------------------------- #
# compute_motion_signals — absdiff floor
# --------------------------------------------------------------------------- #
def test_compute_absdiff_peak_lands_on_high_diff_window() -> None:
    # 3 frames: solid, solid (low diff), noisy (high diff) -> peak at last window.
    frames = [_frame(100), _frame(100), _noisy_frame(7)]
    track = motion.compute_motion_signals(
        "video.mp4",
        3.0,
        frame_loader=_loader_returning(frames),
        mode="absdiff",
    )
    assert track.present is True
    assert track.channel == "motion"
    assert len(track.signals) == 3
    values = [s.value for s in track.signals]
    assert all(0.0 <= v <= 1.0 for v in values)
    # the high-diff window (last) is the normalized peak
    assert values[-1] == pytest.approx(1.0)
    assert max(values) == values[-1]
    assert track.signals[0].meta["mode"] == "absdiff"


def test_compute_absdiff_static_clip_all_zero() -> None:
    frames = [_frame(50), _frame(50), _frame(50)]
    track = motion.compute_motion_signals("v.mp4", 3.0, frame_loader=_loader_returning(frames), mode="absdiff")
    assert [s.value for s in track.signals] == [0.0, 0.0, 0.0]
    assert track.present is True


# --------------------------------------------------------------------------- #
# compute_motion_signals — flow path
# --------------------------------------------------------------------------- #
def test_compute_flow_mode_runs_and_normalizes() -> None:
    a = np.zeros((48, 48), dtype=np.uint8)
    b = a.copy()
    b[10:30, 25:35] = 255  # motion between frame 1->2
    c = b.copy()  # no motion 2->3
    track = motion.compute_motion_signals("v.mp4", 3.0, frame_loader=_loader_returning([a, b, c]), mode="flow")
    assert track.present is True
    assert len(track.signals) == 3
    assert all(0.0 <= s.value <= 1.0 for s in track.signals)
    assert track.signals[0].meta["mode"] == "flow"


# --------------------------------------------------------------------------- #
# compute_motion_signals — backend seam
# --------------------------------------------------------------------------- #
class _FakeBackend:
    """Fake MotionBackend returning canned per-pair magnitudes (no model)."""

    def __init__(self, mags: list[float]) -> None:
        self._mags = mags
        self.calls = 0

    def pair_magnitudes(self, frames: list[np.ndarray]) -> list[float]:
        self.calls += 1
        assert len(frames) >= 1
        return self._mags


def test_compute_with_backend_uses_seam_and_clamps() -> None:
    backend = _FakeBackend([0.1, 5.0])  # 5.0 must clamp to 1.0
    frames = [_frame(0), _frame(0), _frame(0)]
    track = motion.compute_motion_signals("v.mp4", 3.0, frame_loader=_loader_returning(frames), backend=backend)
    assert backend.calls == 1
    # raw window values: w0 mirrors pair[0]=0.1, w1=pair[0]=0.1, w2=pair[1]=1.0
    raws = [s.meta["raw"] for s in track.signals]
    assert raws == [0.1, 0.1, 1.0]
    assert track.signals[-1].value == pytest.approx(1.0)
    assert track.signals[0].meta["mode"] == "backend"


# --------------------------------------------------------------------------- #
# compute_motion_signals — edge cases (empty / single frame)
# --------------------------------------------------------------------------- #
def test_compute_empty_video_single_zero_sample() -> None:
    track = motion.compute_motion_signals("v.mp4", 0.0, frame_loader=_loader_returning([]))
    assert track.present is True
    assert len(track.signals) == 1
    assert track.signals[0].value == 0.0
    assert track.signals[0].start == 0.0
    assert track.signals[0].end == 0.0


def test_compute_single_frame_clip_no_motion() -> None:
    track = motion.compute_motion_signals("v.mp4", 1.0, frame_loader=_loader_returning([_frame(10)]))
    assert track.present is True
    assert all(s.value == 0.0 for s in track.signals)


def test_compute_loader_returns_none_is_handled() -> None:
    def _none_loader(path: str, timestamps: Sequence[float]) -> list[np.ndarray]:
        return None  # type: ignore[return-value]

    track = motion.compute_motion_signals("v.mp4", 2.0, frame_loader=_none_loader)
    assert track.present is True
    assert all(s.value == 0.0 for s in track.signals)


# --------------------------------------------------------------------------- #
# compute_motion_signals — progress + cancel seams
# --------------------------------------------------------------------------- #
def test_compute_reports_progress() -> None:
    seen: list[tuple[float, str]] = []
    motion.compute_motion_signals(
        "v.mp4",
        2.0,
        frame_loader=_loader_returning([_frame(0), _noisy_frame(1)]),
        on_progress=lambda pct, msg: seen.append((pct, msg)),
    )
    assert (50.0, "loaded frames") in seen
    assert (100.0, "done") in seen


def test_compute_cancel_before_load_returns_empty_track() -> None:
    track = motion.compute_motion_signals(
        "v.mp4",
        3.0,
        frame_loader=_loader_returning([_frame(0), _frame(1)]),
        should_cancel=lambda: True,
    )
    assert track.present is True
    assert track.signals == ()


def test_compute_cancel_mid_emit_returns_partial_track() -> None:
    # cancel only AFTER the frame load (so load happens, emit is interrupted).
    state = {"loaded": False}

    def _loader(path: str, timestamps: Sequence[float]) -> list[np.ndarray]:
        state["loaded"] = True
        return [_frame(0), _noisy_frame(2), _noisy_frame(3)]

    def _cancel() -> bool:
        # False until frames are loaded, then True to break the emit loop.
        return state["loaded"]

    track = motion.compute_motion_signals("v.mp4", 3.0, frame_loader=_loader, should_cancel=_cancel)
    assert track.present is True
    assert track.signals == ()  # broke on the first emit iteration


def test_compute_settings_accepted_for_symmetry() -> None:
    track = motion.compute_motion_signals(
        "v.mp4",
        2.0,
        settings={"anything": 1},
        frame_loader=_loader_returning([_frame(0), _frame(0)]),
    )
    assert track.present is True


# --------------------------------------------------------------------------- #
# default loader uses cv2 only when NOT injected (no real video here)
# --------------------------------------------------------------------------- #
def test_default_loader_is_used_when_none_injected(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def _fake_default(path: str, timestamps: Sequence[float]) -> list[np.ndarray]:
        captured["path"] = path
        captured["timestamps"] = list(timestamps)
        return [_frame(0), _noisy_frame(4)]

    monkeypatch.setattr(motion, "_default_frame_loader", _fake_default)
    track = motion.compute_motion_signals("real.mp4", 2.0)  # no frame_loader -> default
    assert captured["path"] == "real.mp4"
    assert track.present is True


# --------------------------------------------------------------------------- #
# Signal / SignalTrack contract shape
# --------------------------------------------------------------------------- #
def test_signal_dataclass_defaults_and_frozen() -> None:
    sig = motion.Signal(channel="motion", start=0.0, end=1.0, value=0.5)
    assert sig.confidence == 1.0
    assert sig.meta == {}
    with pytest.raises(Exception):  # frozen dataclass  # noqa: B017, PT011
        sig.value = 0.9  # type: ignore[misc]


def test_signal_track_present_flag() -> None:
    track = motion.SignalTrack(channel="motion", signals=(), present=False)
    assert track.present is False
    assert track.fps_hint is None


def test_module_value_always_clamped() -> None:
    # sanity: every emitted value is a valid normalized float
    track = motion.compute_motion_signals(
        "v.mp4", 4.0, frame_loader=_loader_returning([_frame(0), _frame(255), _frame(0), _frame(255)])
    )
    for s in track.signals:
        assert 0.0 <= s.value <= 1.0
        assert not math.isnan(s.value)
