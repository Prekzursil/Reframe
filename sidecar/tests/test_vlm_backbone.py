"""Heavy-ML-FREE tests for the shared SigLIP-2 backbone (WU4).

The whole module is exercised with a FAKE :class:`BackboneBackend` returning
hand-built numpy arrays and a fake ``frame_loader`` returning synthetic frames
— transformers / torch / cv2 are NEVER imported. numpy IS in the venv, so every
numeric assertion is exact.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from dataclasses import FrozenInstanceError
from typing import Any

import numpy as np
import pytest
from media_studio.features import vlm_backbone as vb


# --------------------------------------------------------------------------- #
# fakes (the injected seams)
# --------------------------------------------------------------------------- #
class FakeBackend:
    """Records call counts; returns canned embeds/texts/head."""

    def __init__(
        self,
        image_embeds: np.ndarray,
        text_embeds: np.ndarray,
        head: np.ndarray | None = None,
    ) -> None:
        self._img = np.asarray(image_embeds, dtype=np.float64)
        self._txt = np.asarray(text_embeds, dtype=np.float64)
        self._head = head
        self.embed_images_calls = 0
        self.embed_texts_calls = 0

    def embed_images(self, frames: np.ndarray) -> np.ndarray:
        self.embed_images_calls += 1
        # honour the actual frame count so window-alignment is realistic
        n = len(frames)
        return self._img[:n]

    def embed_texts(self, texts: Sequence[str]) -> np.ndarray:
        self.embed_texts_calls += 1
        return self._txt

    def head_weights(self) -> np.ndarray | None:
        return self._head


def _frame_loader_for(n: int):
    """A fake loader returning ``n`` tiny synthetic BGR frames."""

    def loader(media_path: str, timestamps: Sequence[float]) -> list[np.ndarray]:
        return [np.full((2, 2, 3), i, dtype=np.uint8) for i in range(n)]

    return loader


def _empty_loader(media_path: str, timestamps: Sequence[float]) -> list[np.ndarray]:
    return []


# --------------------------------------------------------------------------- #
# sample_windows
# --------------------------------------------------------------------------- #
def test_sample_windows_basic_grid() -> None:
    assert vb.sample_windows(3.0, 1.0, 1.0) == ((0.0, 1.0), (1.0, 2.0), (2.0, 3.0))


def test_sample_windows_last_window_clamped_to_duration() -> None:
    windows = vb.sample_windows(2.5, 1.0, 1.0)
    assert windows[-1] == (2.0, 2.5)


def test_sample_windows_zero_duration_single_instant() -> None:
    assert vb.sample_windows(0.0) == ((0.0, 0.0),)
    assert vb.sample_windows(-5.0) == ((0.0, 0.0),)


def test_sample_windows_floors_nonpositive_hop_and_win() -> None:
    # zero hop must NOT spin; tiny floor yields many windows for a short clip
    windows = vb.sample_windows(0.001, 0.0, 0.0)
    assert len(windows) >= 1
    assert windows[0][0] == 0.0


# --------------------------------------------------------------------------- #
# aesthetic_score
# --------------------------------------------------------------------------- #
def test_aesthetic_score_empty_returns_empty() -> None:
    assert vb.aesthetic_score(np.zeros((0, 4))) == []


def test_aesthetic_score_non_2d_returns_empty() -> None:
    assert vb.aesthetic_score(np.array([1.0, 2.0, 3.0])) == []


def test_aesthetic_score_with_head_linear() -> None:
    embeds = np.array([[1.0, 0.0], [0.0, 1.0]])
    head = np.array([10.0, -10.0])  # frame 0 -> high, frame 1 -> low
    scores = vb.aesthetic_score(embeds, head)
    assert len(scores) == 2
    assert all(0.0 <= s <= 1.0 for s in scores)
    assert scores[0] > scores[1]


def test_aesthetic_score_with_head_bias_term() -> None:
    embeds = np.array([[1.0, 0.0]])
    head = np.array([0.0, 0.0, 50.0])  # dim+1: pure positive bias -> ~1.0
    scores = vb.aesthetic_score(embeds, head)
    assert scores[0] == pytest.approx(1.0, abs=1e-6)


def test_aesthetic_score_head_dim_mismatch_raises() -> None:
    embeds = np.array([[1.0, 0.0, 0.0]])
    with pytest.raises(ValueError, match="head_weights length"):
        vb.aesthetic_score(embeds, np.array([1.0, 2.0]))


def test_aesthetic_score_no_head_norm_proxy() -> None:
    # rows with distinct norms -> min-max scaled to span [0,1]
    embeds = np.array([[1.0, 0.0], [3.0, 4.0]])  # norms 1 and 5
    scores = vb.aesthetic_score(embeds, None)
    assert scores == [pytest.approx(0.0), pytest.approx(1.0)]


def test_aesthetic_score_no_head_equal_norms_midpoint() -> None:
    embeds = np.array([[1.0, 0.0], [0.0, 1.0]])  # both norm 1 -> hi==lo
    scores = vb.aesthetic_score(embeds, None)
    assert scores == [0.5, 0.5]


# --------------------------------------------------------------------------- #
# zero_shot_interestingness
# --------------------------------------------------------------------------- #
def test_zero_shot_empty_returns_empty() -> None:
    assert vb.zero_shot_interestingness(np.zeros((0, 2)), np.eye(2)) == []


def test_zero_shot_non_2d_image_returns_empty() -> None:
    assert vb.zero_shot_interestingness(np.array([1.0, 2.0]), np.eye(2)) == []


def test_zero_shot_requires_prompt_pair() -> None:
    with pytest.raises(ValueError, match="prompt pair"):
        vb.zero_shot_interestingness(np.array([[1.0, 0.0]]), np.array([[1.0, 0.0]]))


def test_zero_shot_aligns_with_interesting_prompt() -> None:
    # interesting prompt = [1,0]; boring = [0,1]
    text = np.array([[1.0, 0.0], [0.0, 1.0]])
    # frame 0 like interesting, frame 1 like boring
    images = np.array([[1.0, 0.0], [0.0, 1.0]])
    scores = vb.zero_shot_interestingness(images, text)
    assert scores[0] > 0.9
    assert scores[1] < 0.1
    assert all(0.0 <= s <= 1.0 for s in scores)


def test_zero_shot_ignores_extra_prompt_rows() -> None:
    text = np.array([[1.0, 0.0], [0.0, 1.0], [0.5, 0.5]])  # 3rd row ignored
    images = np.array([[1.0, 0.0]])
    scores = vb.zero_shot_interestingness(images, text)
    assert scores[0] > 0.9


# --------------------------------------------------------------------------- #
# novelty_scores
# --------------------------------------------------------------------------- #
def test_novelty_empty_returns_empty() -> None:
    assert vb.novelty_scores(np.zeros((0, 3))) == []


def test_novelty_non_2d_returns_empty() -> None:
    assert vb.novelty_scores(np.array([1.0, 2.0, 3.0])) == []


def test_novelty_first_frame_maximal() -> None:
    embeds = np.array([[1.0, 0.0]])
    assert vb.novelty_scores(embeds) == [1.0]


def test_novelty_outlier_highest() -> None:
    # two near-identical rows + one orthogonal outlier
    embeds = np.array([[1.0, 0.0], [1.0, 0.001], [0.0, 1.0]])
    nov = vb.novelty_scores(embeds)
    assert nov[0] == 1.0  # first frame: nothing prior -> maximal
    assert nov[1] < 0.01  # near-dup of frame 0 -> low novelty
    assert nov[2] > 0.9  # orthogonal -> high novelty
    # among frames WITH priors, the outlier is the most novel
    assert nov[2] == max(nov[1:])


# --------------------------------------------------------------------------- #
# dataclass contract
# --------------------------------------------------------------------------- #
def test_signal_and_track_are_frozen() -> None:
    sig = vb.Signal(channel="aesthetic", start=0.0, end=1.0, value=0.5)
    assert sig.confidence == 1.0
    assert sig.meta == {}
    with pytest.raises(FrozenInstanceError):
        sig.value = 0.9  # type: ignore[misc]
    track = vb.SignalTrack(channel="aesthetic", signals=(sig,), present=True)
    with pytest.raises(FrozenInstanceError):
        track.present = False  # type: ignore[misc]


# --------------------------------------------------------------------------- #
# compute_backbone_signals — the WU4 acceptance + degrade paths
# --------------------------------------------------------------------------- #
def _present_true(settings: dict[str, Any]) -> bool:
    return True


def _present_false(settings: dict[str, Any]) -> bool:
    return False


def test_compute_one_embed_call_serves_all_three() -> None:
    # 3 frames, frame 2 an outlier; interesting/boring prompt pair + head
    img = np.array([[1.0, 0.0], [1.0, 0.05], [0.0, 1.0]])
    txt = np.array([[1.0, 0.0], [0.0, 1.0]])
    head = np.array([5.0, -5.0])
    backend = FakeBackend(img, txt, head)
    tracks = vb.compute_backbone_signals(
        "video.mp4",
        3.0,
        backend_factory=lambda s: backend,
        frame_loader=_frame_loader_for(3),
        models_present=_present_true,
    )
    # THE acceptance: ONE embed_images call serves all three sub-scores
    assert backend.embed_images_calls == 1
    assert set(tracks) == set(vb.BACKBONE_CHANNELS)
    for ch in vb.BACKBONE_CHANNELS:
        assert tracks[ch].present is True
        assert len(tracks[ch].signals) == 3
        assert all(0.0 <= s.value <= 1.0 for s in tracks[ch].signals)
    # novelty highest on the outlier among frames with priors (frame index 2)
    nov = [s.value for s in tracks[vb.CHANNEL_NOVELTY].signals]
    assert nov[2] == max(nov[1:])
    # signals carry the shared window timeline
    assert tracks[vb.CHANNEL_AESTHETIC].signals[0].start == 0.0
    assert tracks[vb.CHANNEL_AESTHETIC].signals[2].end == 3.0


def test_compute_progress_and_cancel_seams_invoked() -> None:
    img = np.array([[1.0, 0.0], [0.0, 1.0]])
    txt = np.array([[1.0, 0.0], [0.0, 1.0]])
    backend = FakeBackend(img, txt, None)
    progress: list[tuple[float, str]] = []
    tracks = vb.compute_backbone_signals(
        "v.mp4",
        2.0,
        backend_factory=lambda s: backend,
        frame_loader=_frame_loader_for(2),
        models_present=_present_true,
        on_progress=lambda pct, msg: progress.append((pct, msg)),
        should_cancel=lambda: False,
    )
    assert tracks[vb.CHANNEL_NOVELTY].present is True
    # progress fired at extract, embed, score, done
    assert progress[0][0] == 5.0
    assert progress[-1][1] == "done"


def test_compute_custom_prompts_override() -> None:
    img = np.array([[1.0, 0.0]])
    txt = np.array([[1.0, 0.0], [0.0, 1.0]])
    captured: dict[str, Any] = {}

    class CapturingBackend(FakeBackend):
        def embed_texts(self, texts: Sequence[str]) -> np.ndarray:
            captured["texts"] = list(texts)
            return super().embed_texts(texts)

    cb = CapturingBackend(img, txt, None)
    vb.compute_backbone_signals(
        "v.mp4",
        1.0,
        backend_factory=lambda s: cb,
        frame_loader=_frame_loader_for(1),
        models_present=_present_true,
        prompts=("custom interesting", "custom boring"),
    )
    assert captured["texts"] == ["custom interesting", "custom boring"]


def test_compute_offline_missing_model_degrades() -> None:
    tracks = vb.compute_backbone_signals(
        "v.mp4",
        2.0,
        settings={"offline": True},
        backend_factory=lambda s: FakeBackend(np.eye(2), np.eye(2)),
        frame_loader=_frame_loader_for(2),
        models_present=_present_false,
    )
    for ch in vb.BACKBONE_CHANNELS:
        assert tracks[ch].present is False
        assert tracks[ch].signals == ()


def test_compute_offline_but_model_present_runs() -> None:
    # offline is fine when the model IS installed -> not a degrade
    img = np.array([[1.0, 0.0], [0.0, 1.0]])
    backend = FakeBackend(img, np.array([[1.0, 0.0], [0.0, 1.0]]))
    tracks = vb.compute_backbone_signals(
        "v.mp4",
        2.0,
        settings={"offline": True},
        backend_factory=lambda s: backend,
        frame_loader=_frame_loader_for(2),
        models_present=_present_true,
    )
    assert tracks[vb.CHANNEL_AESTHETIC].present is True


def test_compute_no_frames_degrades() -> None:
    tracks = vb.compute_backbone_signals(
        "v.mp4",
        2.0,
        backend_factory=lambda s: FakeBackend(np.eye(2), np.eye(2)),
        frame_loader=_empty_loader,
        models_present=_present_true,
    )
    for ch in vb.BACKBONE_CHANNELS:
        assert tracks[ch].present is False


def test_compute_cancel_before_embed_degrades() -> None:
    backend = FakeBackend(np.eye(2), np.eye(2))
    tracks = vb.compute_backbone_signals(
        "v.mp4",
        2.0,
        backend_factory=lambda s: backend,
        frame_loader=_frame_loader_for(2),
        models_present=_present_true,
        should_cancel=lambda: True,
    )
    assert backend.embed_images_calls == 0
    for ch in vb.BACKBONE_CHANNELS:
        assert tracks[ch].present is False


def test_compute_empty_embeds_from_backend_degrades() -> None:
    # backend returns a 2-D array with zero rows -> degrade, no crash
    backend = FakeBackend(np.zeros((0, 4)), np.eye(2))
    tracks = vb.compute_backbone_signals(
        "v.mp4",
        2.0,
        backend_factory=lambda s: backend,
        frame_loader=_frame_loader_for(2),
        models_present=_present_true,
    )
    # frame_loader yields 2 frames but backend slices to 0 -> degrade
    for ch in vb.BACKBONE_CHANNELS:
        assert tracks[ch].present is False


# --------------------------------------------------------------------------- #
# default seams (no heavy imports actually executed — only the lazy bodies)
# --------------------------------------------------------------------------- #
def test_default_models_present_no_asset(monkeypatch: pytest.MonkeyPatch) -> None:
    import media_studio.assets.manifest as manifest_mod

    monkeypatch.setattr(manifest_mod, "get_asset", lambda name: None)
    assert vb._default_models_present({}) is False


def test_default_models_present_with_asset(monkeypatch: pytest.MonkeyPatch) -> None:
    import media_studio.assets.manager as manager_mod
    import media_studio.assets.manifest as manifest_mod

    monkeypatch.setattr(manifest_mod, "get_asset", lambda name: object())

    class FakeMgr:
        def __init__(self, **kwargs: Any) -> None:
            pass

        def installed_path(self, entry: Any) -> str | None:
            return "/models/siglip2"

    monkeypatch.setattr(manager_mod, "AssetManager", FakeMgr)
    assert vb._default_models_present({}) is True


def test_default_backbone_factory_lazy_imports(monkeypatch: pytest.MonkeyPatch) -> None:
    # inject a fake backend module so the lazy import resolves without torch
    import types

    fake_mod = types.ModuleType("media_studio.features.vlm_backbone_backend")

    class FakeReal:
        def __init__(self, settings: dict[str, Any]) -> None:
            self.settings = settings

    fake_mod.RealBackboneBackend = FakeReal  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "media_studio.features.vlm_backbone_backend", fake_mod)
    backend = vb._default_backbone_factory({"k": "v"})
    assert isinstance(backend, FakeReal)


def test_default_frame_loader_lazy_cv2(monkeypatch: pytest.MonkeyPatch) -> None:
    # inject a fake cv2 so the default loader runs without the real native dep
    import types

    fake_cv2 = types.ModuleType("cv2")
    fake_cv2.CAP_PROP_POS_MSEC = 0  # type: ignore[attr-defined]

    class FakeCap:
        def __init__(self, path: str) -> None:
            self._reads = 0

        def set(self, prop: int, value: float) -> None:
            pass

        def read(self):
            self._reads += 1
            if self._reads == 1:
                return True, np.zeros((2, 2, 3), dtype=np.uint8)
            return False, None  # second timestamp yields nothing -> skipped

        def release(self) -> None:
            pass

    fake_cv2.VideoCapture = FakeCap  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "cv2", fake_cv2)
    frames = vb._default_frame_loader("v.mp4", [0.5, 1.5])
    assert len(frames) == 1


def test_l2_normalize_handles_1d_input() -> None:
    # cover the ndim!=2 reshape branch via the private helper
    out = vb._l2_normalize(np.array([3.0, 4.0]))
    assert out.shape == (1, 2)
    assert np.allclose(out, [[0.6, 0.8]])


def test_l2_normalize_scalar_reshape() -> None:
    out = vb._l2_normalize(np.array(5.0))
    assert out.shape == (1, 1)
