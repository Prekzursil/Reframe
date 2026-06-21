"""Heavy-ML-free tests for the WU2 PANNs audio-saliency module.

No torch / panns / ffmpeg is touched: the PANNs tagger is a fake
:class:`PannsBackend` returning a hand-built ``frames x 527`` matrix and the
audio decode is a fake ``audio_loader`` returning synthetic numpy samples. Real
numpy is available, so the numeric assertions are exact.
"""

from __future__ import annotations

import sys
import types
from typing import Any

import numpy as np
import pytest
from media_studio.features import audio_saliency as a
from media_studio.features import offline as _offline

# --------------------------------------------------------------------------- #
# helpers / fakes
# --------------------------------------------------------------------------- #
NUM_CLASSES = 527


def _tag_matrix(frames: int, spikes: dict[int, dict[int, float]] | None = None) -> np.ndarray:
    """A ``frames x 527`` probability matrix, mostly tiny, with optional spikes.

    ``spikes`` maps ``frame_index -> {class_index: probability}``.
    """
    arr = np.full((frames, NUM_CLASSES), 0.01, dtype=np.float64)
    for frame, classes in (spikes or {}).items():
        for cls, prob in classes.items():
            arr[frame, cls] = prob
    return arr


class FakeTagger:
    """A fake :class:`a.PannsBackend` returning a canned matrix; records calls."""

    def __init__(self, matrix: np.ndarray) -> None:
        self.matrix = matrix
        self.calls: list[tuple[int, int]] = []

    def tag(self, samples: np.ndarray, sr: int) -> np.ndarray:
        self.calls.append((int(samples.shape[0]), int(sr)))
        return self.matrix


def _loader(samples: np.ndarray, sr: int = a.TARGET_SR) -> Any:
    def load(_path: str) -> tuple[np.ndarray, int]:
        return samples, sr

    return load


# --------------------------------------------------------------------------- #
# sample_windows
# --------------------------------------------------------------------------- #
def test_sample_windows_basic_grid() -> None:
    assert a.sample_windows(3.0, 1.0, 1.0) == ((0.0, 1.0), (1.0, 2.0), (2.0, 3.0))


def test_sample_windows_partial_last_window() -> None:
    wins = a.sample_windows(2.5, 1.0, 1.0)
    assert wins[-1] == (2.0, 2.5)


def test_sample_windows_overlapping_hop() -> None:
    wins = a.sample_windows(2.0, 1.0, 0.5)
    assert wins[0] == (0.0, 1.0)
    assert wins[1] == (0.5, 1.5)


def test_sample_windows_zero_duration_is_single_degenerate() -> None:
    assert a.sample_windows(0.0) == ((0.0, 0.0),)
    assert a.sample_windows(-5.0) == ((0.0, 0.0),)


def test_sample_windows_nonpositive_step_floored() -> None:
    # A zero/negative step must not loop forever — floored to a tiny epsilon.
    wins = a.sample_windows(0.001, 1.0, 0.0)
    assert wins  # terminates and produces at least one window
    assert wins[0][0] == 0.0


# --------------------------------------------------------------------------- #
# _minmax_normalize
# --------------------------------------------------------------------------- #
def test_minmax_normalize_empty() -> None:
    assert a._minmax_normalize([]) == []


def test_minmax_normalize_flat_is_zeros() -> None:
    assert a._minmax_normalize([2.0, 2.0, 2.0]) == [0.0, 0.0, 0.0]


def test_minmax_normalize_spreads_to_unit_range() -> None:
    out = a._minmax_normalize([1.0, 3.0, 5.0])
    assert out[0] == 0.0
    assert out[-1] == 1.0
    assert 0.4 < out[1] < 0.6


# --------------------------------------------------------------------------- #
# loudness_curve (no model)
# --------------------------------------------------------------------------- #
def test_loudness_curve_peak_on_loud_burst() -> None:
    sr = 4
    # 3 one-second windows: quiet, LOUD burst, quiet.
    samples = np.concatenate(
        [
            np.full(sr, 0.01),
            np.full(sr, 0.9),
            np.full(sr, 0.01),
        ]
    )
    curve = a.loudness_curve(samples, sr, 1.0, 1.0)
    assert len(curve) == 3
    assert all(0.0 <= v <= 1.0 for v in curve)
    assert curve[1] == max(curve)
    assert curve[1] == 1.0


def test_loudness_curve_silence_is_all_zeros() -> None:
    sr = 4
    curve = a.loudness_curve(np.zeros(sr * 3), sr, 1.0, 1.0)
    assert curve == [0.0, 0.0, 0.0]


def test_loudness_curve_empty_buffer_single_zero() -> None:
    curve = a.loudness_curve(np.array([], dtype=np.float64), a.TARGET_SR, 1.0, 1.0)
    assert curve == [0.0]


def test_loudness_curve_empty_window_chunk_branch() -> None:
    # A window whose sample slice is empty (a < b but past the buffer end) must
    # contribute 0.0 rather than crash. Force it with a tiny buffer + a hop that
    # produces a window beyond the samples.
    sr = 2
    samples = np.full(sr, 0.5)  # 1 second of audio
    # duration is computed from samples, so the grid matches; the LAST window's
    # rounding can leave an empty slice — assert it is handled.
    curve = a.loudness_curve(samples, sr, 1.0, 1.0)
    assert curve  # no crash; honest values


# --------------------------------------------------------------------------- #
# peak_windows
# --------------------------------------------------------------------------- #
def test_peak_windows_empty_matrix() -> None:
    assert a.peak_windows(np.zeros((0, NUM_CLASSES)), 16, 1.0, 1.0) == []


def test_peak_windows_wrong_ndim() -> None:
    assert a.peak_windows(np.zeros(NUM_CLASSES), 16, 1.0, 1.0) == []


def test_peak_windows_laughter_peak_at_correct_window() -> None:
    laugh = a.AUDIOSET_CLASS_INDEX["laughter"]
    # 3 frames @ hop 1.0 -> 3 windows; laughter spikes in frame 1 (window 1).
    matrix = _tag_matrix(3, spikes={1: {laugh: 0.95}})
    signals = a.peak_windows(matrix, laugh, 1.0, 1.0, channel="laughter")
    assert len(signals) == 3
    assert all(isinstance(s, a.Signal) for s in signals)
    assert all(0.0 <= s.value <= 1.0 for s in signals)
    # The spiking window is the normalized maximum.
    peak = max(signals, key=lambda s: s.value)
    assert peak.value == 1.0
    assert peak.start == 1.0
    assert peak.channel == "laughter"
    assert peak.meta["classIndex"] == laugh
    assert peak.meta["prob"] == pytest.approx(0.95)
    assert peak.confidence == pytest.approx(0.95)


def test_peak_windows_pools_multiple_frames_per_window() -> None:
    laugh = a.AUDIOSET_CLASS_INDEX["laughter"]
    # 4 frames but hop 0.5 with win 1.0 means each window spans ~2 frames.
    matrix = _tag_matrix(4, spikes={3: {laugh: 0.8}})
    signals = a.peak_windows(matrix, laugh, 1.0, 0.5, channel="laughter")
    assert signals
    # The window covering frame 3 carries the pooled max.
    assert max(s.meta["prob"] for s in signals) == pytest.approx(0.8)


# --------------------------------------------------------------------------- #
# _audio_salience_signals (derived)
# --------------------------------------------------------------------------- #
def test_audio_salience_empty_matrix() -> None:
    assert a._audio_salience_signals(np.zeros((0, NUM_CLASSES)), 1.0, 1.0) == []


def test_audio_salience_wrong_ndim() -> None:
    assert a._audio_salience_signals(np.zeros(NUM_CLASSES), 1.0, 1.0) == []


def test_audio_salience_takes_max_over_events() -> None:
    laugh = a.AUDIOSET_CLASS_INDEX["laughter"]
    music = a.AUDIOSET_CLASS_INDEX["music"]
    # frame 0 laughter spike, frame 2 music spike -> both windows salient.
    matrix = _tag_matrix(3, spikes={0: {laugh: 0.7}, 2: {music: 0.9}})
    signals = a._audio_salience_signals(matrix, 1.0, 1.0)
    assert len(signals) == 3
    assert all(s.channel == "audioSalience" for s in signals)
    # Window 2 (the strongest event, music 0.9) normalizes to 1.0.
    assert max(signals, key=lambda s: s.value).start == 2.0


# --------------------------------------------------------------------------- #
# compute_audio_signals — happy path (the WU2 acceptance)
# --------------------------------------------------------------------------- #
def test_compute_detects_laughter_without_transcript_keyword() -> None:
    laugh = a.AUDIOSET_CLASS_INDEX["laughter"]
    matrix = _tag_matrix(3, spikes={1: {laugh: 0.96}})
    tagger = FakeTagger(matrix)
    samples = np.full(a.TARGET_SR * 3, 0.2)  # 3s of audio
    tracks = a.compute_audio_signals(
        "vid.mp4",
        3.0,
        backend_factory=lambda _s: tagger,
        audio_loader=_loader(samples),
        models_present=lambda _s: True,
    )
    assert set(tracks) == set(a.AUDIO_CHANNELS)
    laugh_track = tracks["laughter"]
    assert laugh_track.present is True
    # The peak laughter Signal lands at the spiking window — NO (Applause)/text.
    peak = max(laugh_track.signals, key=lambda s: s.value)
    assert peak.value == 1.0
    assert peak.start == 1.0
    # The tagger was called exactly once with the decoded samples.
    assert len(tagger.calls) == 1


def test_compute_all_tag_channels_present_and_loudness_present() -> None:
    matrix = _tag_matrix(2, spikes={0: {a.AUDIOSET_CLASS_INDEX["music"]: 0.5}})
    samples = np.full(a.TARGET_SR * 2, 0.3)
    tracks = a.compute_audio_signals(
        "vid.mp4",
        2.0,
        backend_factory=lambda _s: FakeTagger(matrix),
        audio_loader=_loader(samples),
        models_present=lambda _s: True,
    )
    for channel in a.TAG_CHANNELS:
        assert tracks[channel].present is True
    assert tracks["loudness"].present is True
    assert tracks["loudness"].fps_hint == pytest.approx(1.0)


def test_compute_progress_callback_invoked() -> None:
    matrix = _tag_matrix(2)
    samples = np.full(a.TARGET_SR, 0.3)
    seen: list[tuple[float, str]] = []
    a.compute_audio_signals(
        "vid.mp4",
        1.0,
        backend_factory=lambda _s: FakeTagger(matrix),
        audio_loader=_loader(samples),
        models_present=lambda _s: True,
        on_progress=lambda pct, msg: seen.append((pct, msg)),
    )
    assert seen
    assert seen[-1] == (100.0, "done")
    assert all(0.0 <= pct <= 100.0 for pct, _ in seen)


# --------------------------------------------------------------------------- #
# compute_audio_signals — degrade paths
# --------------------------------------------------------------------------- #
def test_compute_no_audio_degrades_tag_channels_keeps_loudness() -> None:
    tracks = a.compute_audio_signals(
        "silent.mp4",
        5.0,
        backend_factory=lambda _s: pytest.fail("tagger must not run for no-audio"),
        audio_loader=_loader(np.array([], dtype=np.float64)),
        models_present=lambda _s: True,
    )
    for channel in a.TAG_CHANNELS:
        assert tracks[channel].present is False
        assert tracks[channel].signals == ()
    # loudness is ALWAYS present — an honest single 0.0 window.
    loud = tracks["loudness"]
    assert loud.present is True
    assert len(loud.signals) == 1
    assert loud.signals[0].value == 0.0


def test_compute_offline_missing_model_degrades_tags() -> None:
    samples = np.full(a.TARGET_SR * 2, 0.4)
    tracks = a.compute_audio_signals(
        "vid.mp4",
        2.0,
        settings={_offline.SETTING_OFFLINE: True},
        backend_factory=lambda _s: pytest.fail("tagger must not run offline-missing"),
        audio_loader=_loader(samples),
        models_present=lambda _s: False,
    )
    for channel in a.TAG_CHANNELS:
        assert tracks[channel].present is False
    # loudness still computed from the real samples.
    assert tracks["loudness"].present is True
    assert len(tracks["loudness"].signals) == 2


def test_compute_online_missing_model_still_invokes_factory() -> None:
    # Online + model "missing": the probe says absent, but a real factory would
    # download — so the seam IS still invoked (here a fake stands in for it).
    matrix = _tag_matrix(2)
    tagger = FakeTagger(matrix)
    samples = np.full(a.TARGET_SR * 2, 0.4)
    tracks = a.compute_audio_signals(
        "vid.mp4",
        2.0,
        settings={_offline.SETTING_OFFLINE: False},
        backend_factory=lambda _s: tagger,
        audio_loader=_loader(samples),
        models_present=lambda _s: False,
    )
    assert tracks["laughter"].present is True
    assert len(tagger.calls) == 1


def test_compute_cancelled_before_tagging_degrades_tags() -> None:
    samples = np.full(a.TARGET_SR * 2, 0.4)
    tracks = a.compute_audio_signals(
        "vid.mp4",
        2.0,
        backend_factory=lambda _s: pytest.fail("tagger must not run when cancelled"),
        audio_loader=_loader(samples),
        models_present=lambda _s: True,
        should_cancel=lambda: True,
    )
    for channel in a.TAG_CHANNELS:
        assert tracks[channel].present is False
    assert tracks["loudness"].present is True


def test_compute_not_cancelled_runs_tagger() -> None:
    matrix = _tag_matrix(2)
    tagger = FakeTagger(matrix)
    samples = np.full(a.TARGET_SR * 2, 0.4)
    tracks = a.compute_audio_signals(
        "vid.mp4",
        2.0,
        backend_factory=lambda _s: tagger,
        audio_loader=_loader(samples),
        models_present=lambda _s: True,
        should_cancel=lambda: False,
    )
    assert tracks["audioSalience"].present is True
    assert len(tagger.calls) == 1


# --------------------------------------------------------------------------- #
# the default factory seam (lazy import of the sibling backend module)
# --------------------------------------------------------------------------- #
def test_default_backend_factory_lazy_imports_sibling(monkeypatch: pytest.MonkeyPatch) -> None:
    # Inject a fake sibling module so the lazy import resolves WITHOUT torch.
    built: list[dict[str, Any]] = []

    class _FakeReal:
        def __init__(self, settings: dict[str, Any]) -> None:
            built.append(settings)

        def tag(self, samples: np.ndarray, sr: int) -> np.ndarray:  # pragma: no cover - not called here
            return np.zeros((1, NUM_CLASSES))

    fake_mod = types.ModuleType("media_studio.features.audio_saliency_backend")
    fake_mod.PannsCnn14Backend = _FakeReal  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "media_studio.features.audio_saliency_backend", fake_mod)
    # Also set the parent-package attr so ``from .audio_saliency_backend import`` resolves.
    import media_studio.features as features_pkg

    monkeypatch.setattr(features_pkg, "audio_saliency_backend", fake_mod, raising=False)

    backend = a._default_backend_factory({"k": "v"})
    assert isinstance(backend, _FakeReal)
    assert built == [{"k": "v"}]
