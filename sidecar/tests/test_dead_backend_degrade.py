"""T11 DEAD-BACKEND contract: a missing sibling backend module degrades honestly.

Four Phase-8 feature modules build their heavy half by lazily importing a sibling
``<feature>_backend`` module. Those four sibling modules are NOT part of this
build (verified: ``audio_saliency_backend`` / ``beatgrid_backend`` /
``clearervoice_backend`` / ``overdub_backend`` are all absent, while 16 other
``*_backend.py`` siblings ship). Two consequences were measured against HEAD:

  1. ``audio_saliency.compute_audio_signals`` CRASHED — a raw
     ``ModuleNotFoundError`` escaped the public runner (and therefore
     ``handlers._wire._run_phase8_signals``), violating the module's own
     documented "never raises for a missing modality" contract.
  2. every ``default_models_present`` probe LIED — it checks only that the model
     CHECKPOINT is installed, so once the weights download the UI reports the
     feature ready even though the code that consumes them cannot be imported.

These tests lock in the fixed contract: a typed ``*BackendUnavailableError``
instead of a raw ``ModuleNotFoundError``, an honest ``backend_available`` /
``default_models_present``, and a graceful degrade at every public entry point.

No heavy ML is touched: a missing module is simulated deterministically with
``sys.modules[name] = None`` (CPython raises ``ImportError`` for a ``None``
entry), so the tests hold whether or not a future wave ships the real backends.
"""

from __future__ import annotations

import importlib.util
import sys
from typing import Any

import numpy as np
import pytest
from media_studio.features import audio_saliency as a
from media_studio.features import beatgrid as bg
from media_studio.features import clearervoice as cv
from media_studio.features import overdub as od

NUM_CLASSES = 527

#: (module, expected BACKEND_MODULE dotted name) for the shared-surface tests.
MODULES: tuple[tuple[Any, str], ...] = (
    (a, "media_studio.features.audio_saliency_backend"),
    (bg, "media_studio.features.beatgrid_backend"),
    (cv, "media_studio.features.clearervoice_backend"),
    (od, "media_studio.features.overdub_backend"),
)

_IDS = ("audio_saliency", "beatgrid", "clearervoice", "overdub")


def _loader(samples: np.ndarray, sr: int) -> Any:
    def load(_path: str) -> tuple[np.ndarray, int]:
        return samples, sr

    return load


# --------------------------------------------------------------------------- #
# shared surface: BACKEND_MODULE + backend_available (the honest probe)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(("mod", "expected"), MODULES, ids=_IDS)
def test_backend_module_constant_names_the_sibling(mod: Any, expected: str) -> None:
    assert expected == mod.BACKEND_MODULE


@pytest.mark.parametrize(("mod", "expected"), MODULES, ids=_IDS)
def test_backend_available_true_when_spec_found(mod: Any, expected: str) -> None:
    asked: list[str] = []

    def find(name: str) -> object:
        asked.append(name)
        return object()

    assert mod.backend_available(find_spec=find) is True
    # It must probe the SIBLING module, not something else.
    assert asked == [expected]


@pytest.mark.parametrize(("mod", "expected"), MODULES, ids=_IDS)
def test_backend_available_false_when_spec_absent(mod: Any, expected: str) -> None:
    assert mod.backend_available(find_spec=lambda _name: None) is False


@pytest.mark.parametrize(("mod", "expected"), MODULES, ids=_IDS)
def test_backend_available_false_when_probe_raises_import_error(mod: Any, expected: str) -> None:
    def boom(_name: str) -> object:
        raise ImportError("broken/partial install")

    assert mod.backend_available(find_spec=boom) is False


@pytest.mark.parametrize(("mod", "expected"), MODULES, ids=_IDS)
def test_backend_available_false_when_probe_raises_value_error(mod: Any, expected: str) -> None:
    def boom(_name: str) -> object:
        raise ValueError("namespace package without a spec")

    assert mod.backend_available(find_spec=boom) is False


@pytest.mark.parametrize(("mod", "expected"), MODULES, ids=_IDS)
def test_backend_available_default_seam_agrees_with_importlib(mod: Any, expected: str) -> None:
    # Exercises the real (un-injected) find_spec seam and asserts it agrees with
    # importlib — stable whether or not a later wave ships the sibling module.
    assert mod.backend_available() is (importlib.util.find_spec(expected) is not None)


@pytest.mark.parametrize(("mod", "expected"), MODULES, ids=_IDS)
def test_default_models_present_is_false_without_the_backend_module(
    mod: Any,
    expected: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An installed CHECKPOINT is not enough: with no backend module the feature
    # can never run, so the availability probe must report absent (the UI then
    # shows it unavailable instead of appearing ready). The asset store must not
    # even be consulted — the module gate short-circuits first.
    from media_studio.assets import manifest

    def never(*_args: Any, **_kw: Any) -> Any:
        pytest.fail("the asset store must not be probed once the backend module is absent")

    monkeypatch.setattr(mod, "backend_available", lambda **_kw: False)
    monkeypatch.setattr(manifest, "get_asset", never)
    # clearervoice / overdub take (settings, model_id); the others (settings,).
    verdict = mod.default_models_present({}, "any-model") if mod in (cv, od) else mod.default_models_present({})
    assert verdict is False


# --------------------------------------------------------------------------- #
# the factories: a TYPED, actionable error instead of a raw ModuleNotFoundError
# --------------------------------------------------------------------------- #
def _absent(monkeypatch: pytest.MonkeyPatch, dotted: str) -> None:
    """Make ``from .<sibling> import X`` fail deterministically (None in sys.modules)."""
    monkeypatch.setitem(sys.modules, dotted, None)


def test_audio_saliency_factory_raises_typed_when_module_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    _absent(monkeypatch, a.BACKEND_MODULE)
    with pytest.raises(a.PannsBackendUnavailableError) as excinfo:
        a._default_backend_factory({})
    assert a.BACKEND_MODULE in str(excinfo.value)
    assert isinstance(excinfo.value, RuntimeError)
    assert isinstance(excinfo.value.__cause__, ImportError)


def test_beatgrid_factory_raises_typed_when_module_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    _absent(monkeypatch, bg.BACKEND_MODULE)
    with pytest.raises(bg.BeatThisBackendUnavailableError) as excinfo:
        bg._default_backend_factory({})
    assert bg.BACKEND_MODULE in str(excinfo.value)
    assert isinstance(excinfo.value, RuntimeError)


def test_clearervoice_factory_raises_typed_when_module_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    _absent(monkeypatch, cv.BACKEND_MODULE)
    with pytest.raises(cv.ClearerVoiceBackendUnavailableError) as excinfo:
        cv._default_backend_factory({}, cv.DEFAULT_MODEL_ID)
    assert cv.BACKEND_MODULE in str(excinfo.value)
    assert isinstance(excinfo.value, RuntimeError)


def test_overdub_factory_raises_typed_when_module_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    _absent(monkeypatch, od.BACKEND_MODULE)
    with pytest.raises(od.OverdubBackendUnavailableError) as excinfo:
        od._default_backend_factory({}, od.DEFAULT_MODEL_ID)
    assert od.BACKEND_MODULE in str(excinfo.value)
    assert isinstance(excinfo.value, RuntimeError)


# --------------------------------------------------------------------------- #
# the TIER-1 crash: audio_saliency's public runner must DEGRADE, never raise
# --------------------------------------------------------------------------- #
def test_compute_audio_signals_degrades_when_backend_module_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    # The regression under test: with NO injected factory the real default factory
    # runs, the sibling module is absent, and HEAD let ModuleNotFoundError escape
    # compute_audio_signals (and _wire._run_phase8_signals, and the job thread).
    _absent(monkeypatch, a.BACKEND_MODULE)
    samples = np.full(a.TARGET_SR * 2, 0.4)
    tracks = a.compute_audio_signals(
        "vid.mp4",
        2.0,
        settings={},
        audio_loader=_loader(samples, a.TARGET_SR),
        models_present=lambda _s: True,  # checkpoint "installed" -> reaches the factory
    )
    for channel in a.TAG_CHANNELS:
        assert tracks[channel].present is False, channel
        assert tracks[channel].signals == ()
    # loudness needs no model, so it stays present with REAL measured samples.
    assert tracks["loudness"].present is True
    assert len(tracks["loudness"].signals) == 2
    assert set(tracks) == set(a.AUDIO_CHANNELS)


def test_compute_audio_signals_degrades_when_tagger_raises() -> None:
    # Same contract for a backend that builds but fails to tag (OOM / bad weights).
    class Exploding:
        def tag(self, samples: np.ndarray, sr: int) -> np.ndarray:
            raise RuntimeError("CUDA out of memory")

    samples = np.full(a.TARGET_SR * 2, 0.4)
    progress: list[tuple[float, str]] = []
    tracks = a.compute_audio_signals(
        "vid.mp4",
        2.0,
        backend_factory=lambda _s: Exploding(),
        audio_loader=_loader(samples, a.TARGET_SR),
        models_present=lambda _s: True,
        on_progress=lambda pct, msg: progress.append((pct, msg)),
    )
    for channel in a.TAG_CHANNELS:
        assert tracks[channel].present is False, channel
    assert tracks["loudness"].present is True
    # It degraded rather than reporting a completed run.
    assert "done" not in [msg for _pct, msg in progress]


# --------------------------------------------------------------------------- #
# the other three already wrap their factory call — assert the DEGRADE holds
# with the real default factory + an absent module (no test double for the SUT)
# --------------------------------------------------------------------------- #
def test_detect_beats_degrades_to_empty_grid_when_module_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    _absent(monkeypatch, bg.BACKEND_MODULE)
    grid = bg.detect_beats(
        "song.wav",
        settings={},
        audio_loader=_loader(np.full(bg.DEFAULT_SR, 0.3), bg.DEFAULT_SR),
        models_present=lambda _s: True,
    )
    assert grid.is_empty() is True
    assert grid.beats == ()
    assert grid.bpm is None


def test_enhance_clip_degrades_to_passthrough_when_module_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    _absent(monkeypatch, cv.BACKEND_MODULE)
    notices: list[dict[str, str]] = []
    path, enhanced = cv.enhance_clip(
        "in.mp4",
        "out.mp4",
        "tmp.wav",
        "enh.wav",
        settings={},
        run=lambda _argv, **_kw: 0,
        duration=lambda *_args, **_kw: 3.0,
        models_present=lambda _s, _m: True,
        on_notice=notices.append,
    )
    assert (path, enhanced) == ("in.mp4", False)
    assert len(notices) == 1
    assert notices[0]["type"] == cv.STUDIO_SOUND_UNAVAILABLE_NOTICE
    # The LOUD reason must name the missing module, not just "failed".
    assert cv.BACKEND_MODULE in notices[0]["message"]


def test_overdub_degrades_to_plan_only_when_module_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    _absent(monkeypatch, od.BACKEND_MODULE)
    transcript = {"segments": [{"start": 0.0, "end": 1.0, "words": [{"text": "hi", "start": 0.0, "end": 0.5}]}]}
    result = od.overdub(
        transcript,
        "clip.wav",
        [{"op": "replace", "index": 0, "text": "hey"}],
        "out.wav",
        settings={},
        audio_loader=_loader(np.full(24000, 0.2), 24000),
        models_present=lambda _s, _m: True,
        sample_writer=lambda *_args: pytest.fail("must not write audio when unavailable"),
    )
    assert result["applied"] is False
    assert result["path"] is None
    assert result["notice"] == od.OVERDUB_SKIPPED_NOTICE
    # The PLAN is still returned so the UI can preview the intended edit.
    assert result["editedText"] == "hey"


# --------------------------------------------------------------------------- #
# the surface is exported (callers outside the module can ask honestly)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(("mod", "expected"), MODULES, ids=_IDS)
def test_dead_backend_surface_is_exported(mod: Any, expected: str) -> None:
    assert "BACKEND_MODULE" in mod.__all__
    assert "backend_available" in mod.__all__
    unavailable = [name for name in mod.__all__ if name.endswith("BackendUnavailableError")]
    assert len(unavailable) == 1
    assert issubclass(getattr(mod, unavailable[0]), RuntimeError)
