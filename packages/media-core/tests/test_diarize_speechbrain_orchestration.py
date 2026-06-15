"""Coverage for SpeechBrain import shims, snapshot helper, and full pipeline.

The heavy SpeechBrain / torch / huggingface_hub dependencies are injected as fake
modules so the real packages are never required (mirroring the diarize pyannote tests).
"""

from __future__ import annotations

import inspect
import sys
import types

import pytest

from media_core.diarize import (
    DiarizationBackend,
    DiarizationConfig,
    _ensure_local_hf_snapshot,
    _import_speechbrain_classes,
    _install_hf_auth_token_compat,
    diarize_audio,
)


# ---------------------------------------------------------------------------
# _install_hf_auth_token_compat
# ---------------------------------------------------------------------------
def test_install_hf_compat_no_huggingface_hub(monkeypatch):
    real_import = __import__

    def fake_import(name, *args, **kwargs):
        if name == "huggingface_hub":
            raise ImportError("not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)
    # Should silently return without raising.
    assert _install_hf_auth_token_compat() is None


def test_install_hf_compat_no_download_attr(monkeypatch):
    fake_hub = types.ModuleType("huggingface_hub")
    # No hf_hub_download attribute -> early return.
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake_hub)
    assert _install_hf_auth_token_compat() is None


def test_install_hf_compat_already_supports_use_auth_token(monkeypatch):
    fake_hub = types.ModuleType("huggingface_hub")

    def hf_hub_download(repo_id, use_auth_token=None):  # already has the kwarg
        return repo_id

    fake_hub.hf_hub_download = hf_hub_download
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake_hub)

    _install_hf_auth_token_compat()
    # Not wrapped: the original function object is unchanged.
    assert fake_hub.hf_hub_download is hf_hub_download


def test_install_hf_compat_wraps_and_maps_use_auth_token(monkeypatch):
    fake_hub = types.ModuleType("huggingface_hub")
    received = {}

    def hf_hub_download(repo_id, token=None):  # only supports `token`
        received["repo_id"] = repo_id
        received["token"] = token
        return "downloaded"

    fake_hub.hf_hub_download = hf_hub_download
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake_hub)

    _install_hf_auth_token_compat()
    # Now wrapped: calling with the legacy kwarg maps it to `token`.
    assert fake_hub.hf_hub_download is not hf_hub_download
    result = fake_hub.hf_hub_download("repo", use_auth_token="secret")
    assert result == "downloaded"
    assert received == {"repo_id": "repo", "token": "secret"}

    # Calling with `token` directly (no use_auth_token) takes the False branch:
    # the legacy-mapping `if` is skipped and `token` is passed through unchanged.
    received.clear()
    result = fake_hub.hf_hub_download("repo2", token="direct")
    assert result == "downloaded"
    assert received == {"repo_id": "repo2", "token": "direct"}


def test_install_hf_compat_handles_unintrospectable_signature(monkeypatch):
    fake_hub = types.ModuleType("huggingface_hub")

    class Uninspectable:
        def __call__(self, *args, **kwargs):
            return "ok"

    download = Uninspectable()
    fake_hub.hf_hub_download = download
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake_hub)

    def boom(_obj):
        raise TypeError("cannot introspect")

    monkeypatch.setattr(inspect, "signature", boom)
    # signature() raising -> params = {} -> shim is installed.
    _install_hf_auth_token_compat()
    assert fake_hub.hf_hub_download is not download


# ---------------------------------------------------------------------------
# _import_speechbrain_classes
# ---------------------------------------------------------------------------
def test_import_speechbrain_classes_new_layout(monkeypatch):
    vad_mod = types.ModuleType("speechbrain.inference.VAD")
    vad_mod.VAD = "VAD-CLASS"
    spk_mod = types.ModuleType("speechbrain.inference.speaker")
    spk_mod.SpeakerRecognition = "SPK-CLASS"

    monkeypatch.setitem(sys.modules, "speechbrain", types.ModuleType("speechbrain"))
    monkeypatch.setitem(sys.modules, "speechbrain.inference", types.ModuleType("speechbrain.inference"))
    monkeypatch.setitem(sys.modules, "speechbrain.inference.VAD", vad_mod)
    monkeypatch.setitem(sys.modules, "speechbrain.inference.speaker", spk_mod)

    vad, spk = _import_speechbrain_classes()
    assert vad == "VAD-CLASS"
    assert spk == "SPK-CLASS"


def test_import_speechbrain_classes_legacy_layout(monkeypatch):
    # New layout import fails; legacy speechbrain.pretrained succeeds.
    pretrained = types.ModuleType("speechbrain.pretrained")
    pretrained.VAD = "OLD-VAD"
    pretrained.SpeakerRecognition = "OLD-SPK"
    monkeypatch.setitem(sys.modules, "speechbrain.pretrained", pretrained)

    real_import = __import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("speechbrain.inference"):
            raise ImportError("new layout missing")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)
    vad, spk = _import_speechbrain_classes()
    assert vad == "OLD-VAD"
    assert spk == "OLD-SPK"


# ---------------------------------------------------------------------------
# _ensure_local_hf_snapshot
# ---------------------------------------------------------------------------
def test_ensure_local_hf_snapshot_downloads_and_writes_custom(monkeypatch, tmp_path):
    calls = {}

    fake_hub = types.ModuleType("huggingface_hub")

    def snapshot_download(repo_id, local_dir, local_dir_use_symlinks):  # noqa: ARG001
        calls["repo_id"] = repo_id
        # Simulate a download by creating hyperparams.yaml.
        from pathlib import Path

        (Path(local_dir) / "hyperparams.yaml").write_text("ok", encoding="utf-8")

    fake_hub.snapshot_download = snapshot_download
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake_hub)

    local_dir = _ensure_local_hf_snapshot("org/model", tmp_path)
    assert calls["repo_id"] == "org/model"
    assert (local_dir / "hyperparams.yaml").exists()
    assert (local_dir / "custom.py").exists()  # auto-generated stub


def test_ensure_local_hf_snapshot_skips_when_present(monkeypatch, tmp_path):
    # Pre-create the cache dir with hyperparams.yaml and custom.py so neither the
    # download nor the custom.py write happens.
    expected = tmp_path / "org_model"
    expected.mkdir(parents=True)
    (expected / "hyperparams.yaml").write_text("present", encoding="utf-8")
    (expected / "custom.py").write_text("present", encoding="utf-8")

    def fail_download(*_a, **_k):  # pragma: no cover - must NOT be called
        raise AssertionError("snapshot_download should not run")

    fake_hub = types.ModuleType("huggingface_hub")
    fake_hub.snapshot_download = fail_download
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake_hub)

    local_dir = _ensure_local_hf_snapshot("org/model", tmp_path)
    assert local_dir == expected
    assert (local_dir / "custom.py").read_text(encoding="utf-8") == "present"


def test_ensure_local_hf_snapshot_missing_huggingface_hub(monkeypatch, tmp_path):
    real_import = __import__

    def fake_import(name, *args, **kwargs):
        if name == "huggingface_hub":
            raise ImportError("not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)
    with pytest.raises(RuntimeError, match="requires `huggingface_hub`"):
        _ensure_local_hf_snapshot("org/model", tmp_path)


# ---------------------------------------------------------------------------
# Full _diarize_speechbrain pipeline
# ---------------------------------------------------------------------------
class _Vec:
    def __init__(self, values, ndim=1):
        self.values = list(values)
        self.ndim = ndim

    def to(self, _dtype):
        return self

    def detach(self):
        return self

    def __getitem__(self, idx):
        return _Vec(self.values, ndim=1)


class _Functional:
    @staticmethod
    def cosine_similarity(a, b, dim=0):  # noqa: ARG004
        import math

        dot = sum(x * y for x, y in zip(a.values, b.values))
        na = math.sqrt(sum(x * x for x in a.values)) or 1.0
        nb = math.sqrt(sum(y * y for y in b.values)) or 1.0
        return type("S", (), {"item": lambda self: dot / (na * nb)})()

    @staticmethod
    def normalize(vec, dim=0):  # noqa: ARG004
        import math

        norm = math.sqrt(sum(x * x for x in vec.values)) or 1.0
        return _Vec([x / norm for x in vec.values], ndim=vec.ndim)


class _Boundaries:
    def __init__(self, values):
        self._values = values

    def detach(self):
        return self

    def cpu(self):
        return self

    def tolist(self):
        return list(self._values)


class _Waveform:
    def __init__(self, length):
        self.shape = (1, length)
        self.ndim = 2

    def __getitem__(self, _key):
        return "segment"

    def mean(self, dim=0, keepdim=False):  # noqa: ARG002 - single channel never calls this
        return self


def _install_full_speechbrain(monkeypatch, *, boundaries, embeddings):
    """Install fake speechbrain (+ torch/torchaudio) so _diarize_speechbrain runs end-to-end."""

    class FakeVAD:
        @classmethod
        def from_hparams(cls, source, savedir, local_strategy):  # noqa: ARG003
            return cls()

        def get_speech_segments(self, _path):
            return _Boundaries(boundaries)

    class FakeSpk:
        _embeddings = list(embeddings)
        _i = 0

        @classmethod
        def from_hparams(cls, source, savedir, local_strategy):  # noqa: ARG003
            return cls()

        def encode_batch(self, _wav):
            emb = FakeSpk._embeddings[FakeSpk._i]
            FakeSpk._i += 1
            return emb

    FakeSpk._i = 0

    # speechbrain.inference.* classes
    vad_mod = types.ModuleType("speechbrain.inference.VAD")
    vad_mod.VAD = FakeVAD
    spk_mod = types.ModuleType("speechbrain.inference.speaker")
    spk_mod.SpeakerRecognition = FakeSpk
    fetch_mod = types.ModuleType("speechbrain.utils.fetching")
    fetch_mod.LocalStrategy = types.SimpleNamespace(NO_LINK="NO_LINK")

    monkeypatch.setitem(sys.modules, "speechbrain", types.ModuleType("speechbrain"))
    monkeypatch.setitem(sys.modules, "speechbrain.inference", types.ModuleType("speechbrain.inference"))
    monkeypatch.setitem(sys.modules, "speechbrain.inference.VAD", vad_mod)
    monkeypatch.setitem(sys.modules, "speechbrain.inference.speaker", spk_mod)
    monkeypatch.setitem(sys.modules, "speechbrain.utils", types.ModuleType("speechbrain.utils"))
    monkeypatch.setitem(sys.modules, "speechbrain.utils.fetching", fetch_mod)

    # torch / torchaudio / functional
    fake_torch = types.ModuleType("torch")
    fake_torch.float32 = "float32"
    fake_torch.from_numpy = lambda arr: arr
    fake_nn = types.ModuleType("torch.nn")
    fake_nn.functional = _Functional()
    fake_torch.nn = fake_nn

    fake_torchaudio = types.ModuleType("torchaudio")
    fake_torchaudio.load = lambda _p: (_Waveform(16000 * 6), 16000)

    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "torch.nn", fake_nn)
    monkeypatch.setitem(sys.modules, "torchaudio", fake_torchaudio)

    # huggingface_hub for snapshot + the compat shim.
    fake_hub = types.ModuleType("huggingface_hub")

    def snapshot_download(repo_id, local_dir, local_dir_use_symlinks):  # noqa: ARG001
        from pathlib import Path

        (Path(local_dir) / "hyperparams.yaml").write_text("ok", encoding="utf-8")

    fake_hub.snapshot_download = snapshot_download
    fake_hub.hf_hub_download = lambda *a, token=None, **k: "ok"  # supports token
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake_hub)


def test_diarize_speechbrain_end_to_end(monkeypatch, tmp_path):
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
    monkeypatch.delenv("HUGGINGFACE_HUB_CACHE", raising=False)

    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"fake-audio")

    # Two regions, distinct embeddings -> two speakers.
    _install_full_speechbrain(
        monkeypatch,
        boundaries=[0.0, 1.0, 1.5, 2.5],
        embeddings=[_Vec([1.0, 0.0], ndim=2), _Vec([0.0, 1.0], ndim=2)],
    )

    config = DiarizationConfig(backend=DiarizationBackend.SPEECHBRAIN)
    segments = diarize_audio(audio, config)
    assert [s.speaker for s in segments] == ["SPEAKER_00", "SPEAKER_01"]


def test_diarize_speechbrain_no_boundaries_returns_empty(monkeypatch, tmp_path):
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
    monkeypatch.delenv("HUGGINGFACE_HUB_CACHE", raising=False)
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"fake")

    # Empty boundaries list -> early empty return.
    _install_full_speechbrain(monkeypatch, boundaries=[], embeddings=[])

    config = DiarizationConfig(backend=DiarizationBackend.SPEECHBRAIN)
    assert diarize_audio(audio, config) == []


def test_diarize_speechbrain_none_boundaries_returns_empty(monkeypatch, tmp_path):
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"fake")

    _install_full_speechbrain(monkeypatch, boundaries=[0.0, 1.0], embeddings=[_Vec([1.0])])

    # Patch get_speech_segments to return None for the VAD instance.
    vad_mod = sys.modules["speechbrain.inference.VAD"]
    vad_mod.VAD.get_speech_segments = lambda self, _p: None

    config = DiarizationConfig(backend=DiarizationBackend.SPEECHBRAIN)
    assert diarize_audio(audio, config) == []


def test_diarize_speechbrain_no_speech_regions_returns_empty(monkeypatch, tmp_path):
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"fake")

    # Boundaries present but every region invalid (end <= start) -> no speech regions.
    _install_full_speechbrain(
        monkeypatch, boundaries=[2.0, 1.0], embeddings=[_Vec([1.0, 0.0], ndim=2)]
    )

    config = DiarizationConfig(backend=DiarizationBackend.SPEECHBRAIN)
    assert diarize_audio(audio, config) == []


def test_diarize_speechbrain_torch_missing_raises(monkeypatch, tmp_path):
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"fake")

    # huggingface_hub present (for the compat shim) but torch import fails.
    fake_hub = types.ModuleType("huggingface_hub")
    fake_hub.hf_hub_download = lambda *a, token=None, **k: "ok"
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake_hub)

    real_import = __import__

    def fake_import(name, *args, **kwargs):
        if name == "torch" or name.startswith("torch."):
            raise ImportError("torch not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)

    config = DiarizationConfig(backend=DiarizationBackend.SPEECHBRAIN)
    with pytest.raises(RuntimeError, match="speechbrain diarization backend selected"):
        diarize_audio(audio, config)
