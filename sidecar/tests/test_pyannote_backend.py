"""Tests for media_studio.features.pyannote_backend — the OPT-IN pyannote backend.

The LIGHT half (HF-token resolution, asset registration, installed-state probing,
the backend selector, the pyannote-annotation -> (regions, embeddings) converter)
is exercised exhaustively with hand-built fakes — no pyannote / torch import, no
audio, no real HF token. The heavy ``PyannoteDiarizer.detect_and_embed`` is
``# pragma: no cover`` (it needs the native stack + gated weights); only its
constructor's token plumbing is asserted via the typed-refusal path on the
factory, which validates the token BEFORE any heavy import.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from media_studio.assets import manifest
from media_studio.assets.manager import hf_repo_dir
from media_studio.features import pyannote_backend as pb
from media_studio.protocol import ErrorCode, RpcError


# --------------------------------------------------------------------------- #
# fakes
# --------------------------------------------------------------------------- #
class FakeBackend:
    """A stand-in DiarizerBackend (records the settings it was built with)."""

    def __init__(self, settings: dict[str, Any]) -> None:
        self.settings = settings

    def detect_and_embed(self, audio_path: str, **_kw: Any) -> tuple[list[dict[str, Any]], list[list[float]]]:
        return [], []  # pragma: no cover - never invoked by these tests


def _speechbrain_factory(settings: dict[str, Any]) -> FakeBackend:
    return FakeBackend({**settings, "kind": "speechbrain"})


def _pyannote_factory(settings: dict[str, Any]) -> FakeBackend:
    return FakeBackend({**settings, "kind": "pyannote"})


# --------------------------------------------------------------------------- #
# resolve_hf_token / require_hf_token (Decision #3)
# --------------------------------------------------------------------------- #
class TestResolveHfToken:
    def test_hf_token_preferred(self):
        env = {"HF_TOKEN": "tok-a", "HUGGING_FACE_HUB_TOKEN": "tok-b"}
        assert pb.resolve_hf_token(env) == "tok-a"

    def test_falls_back_to_legacy_name(self):
        env = {"HUGGING_FACE_HUB_TOKEN": "tok-legacy"}
        assert pb.resolve_hf_token(env) == "tok-legacy"

    def test_strips_whitespace(self):
        assert pb.resolve_hf_token({"HF_TOKEN": "  tok  "}) == "tok"

    def test_blank_is_absent(self):
        # A whitespace-only export must NOT masquerade as a real token.
        assert pb.resolve_hf_token({"HF_TOKEN": "   ", "HUGGING_FACE_HUB_TOKEN": ""}) is None

    def test_missing_returns_none(self):
        assert pb.resolve_hf_token({}) is None

    def test_defaults_to_os_environ(self, monkeypatch):
        monkeypatch.delenv("HF_TOKEN", raising=False)
        monkeypatch.delenv("HUGGING_FACE_HUB_TOKEN", raising=False)
        monkeypatch.setenv("HF_TOKEN", "from-environ")
        assert pb.resolve_hf_token() == "from-environ"


class TestRequireHfToken:
    def test_returns_token_when_present(self):
        assert pb.require_hf_token({"HF_TOKEN": "tok"}) == "tok"

    def test_missing_raises_typed_config_error(self):
        with pytest.raises(pb.PyannoteConfigError) as exc:
            pb.require_hf_token({})
        # actionable: names BOTH env vars and BOTH gated repos.
        assert "HF_TOKEN" in str(exc.value)
        assert "HUGGING_FACE_HUB_TOKEN" in str(exc.value)
        assert pb.PYANNOTE_PIPELINE in str(exc.value)
        assert pb.PYANNOTE_SEGMENTATION in str(exc.value)

    def test_config_error_is_rpc_error_invalid_params(self):
        err = pb.PyannoteConfigError("nope")
        assert isinstance(err, RpcError)
        assert err.code == ErrorCode.INVALID_PARAMS


# --------------------------------------------------------------------------- #
# regions_and_embeddings (pure converter into the diarize seam shape)
# --------------------------------------------------------------------------- #
class TestRegionsAndEmbeddings:
    def test_normalizes_spans_and_vectors(self):
        spans = [{"start": 0.0, "end": 1.5}, {"start": 1.5, "end": 3.0}]
        embs = [[1, 0], [0, 1]]
        regions, vecs = pb.regions_and_embeddings(spans, embs)
        assert regions == [{"start": 0.0, "end": 1.5}, {"start": 1.5, "end": 3.0}]
        assert vecs == [[1.0, 0.0], [0.0, 1.0]]
        assert all(isinstance(x, float) for v in vecs for x in v)

    def test_missing_keys_default_to_zero(self):
        regions, vecs = pb.regions_and_embeddings([{}], [[0.5]])
        assert regions == [{"start": 0.0, "end": 0.0}]
        assert vecs == [[0.5]]

    def test_empty_is_empty(self):
        assert pb.regions_and_embeddings([], []) == ([], [])

    def test_length_mismatch_raises(self):
        with pytest.raises(ValueError, match="length mismatch"):
            pb.regions_and_embeddings([{"start": 0.0, "end": 1.0}], [])


# --------------------------------------------------------------------------- #
# selected_backend_name + select_backend_factory (the integrate-phase selector)
# --------------------------------------------------------------------------- #
class TestSelectedBackendName:
    def test_pyannote_selected(self):
        assert pb.selected_backend_name({"diarizeBackend": "pyannote"}) == pb.PYANNOTE_BACKEND

    def test_pyannote_case_insensitive_and_trimmed(self):
        assert pb.selected_backend_name({"diarizeBackend": "  PyAnnote "}) == pb.PYANNOTE_BACKEND

    def test_default_is_speechbrain(self):
        assert pb.selected_backend_name({}) == pb.SPEECHBRAIN_BACKEND

    def test_none_settings_default(self):
        assert pb.selected_backend_name(None) == pb.SPEECHBRAIN_BACKEND

    def test_unknown_value_falls_back(self):
        assert pb.selected_backend_name({"diarizeBackend": "whisperx"}) == pb.SPEECHBRAIN_BACKEND

    def test_non_string_value_falls_back(self):
        assert pb.selected_backend_name({"diarizeBackend": 1}) == pb.SPEECHBRAIN_BACKEND


class TestSelectBackendFactory:
    def test_default_builds_speechbrain(self):
        backend = pb.select_backend_factory(
            {},
            speechbrain_factory=_speechbrain_factory,
            pyannote_factory=_pyannote_factory,
        )
        assert isinstance(backend, FakeBackend)
        assert backend.settings["kind"] == "speechbrain"

    def test_pyannote_selected_uses_injected_factory(self):
        backend = pb.select_backend_factory(
            {"diarizeBackend": "pyannote"},
            speechbrain_factory=_speechbrain_factory,
            pyannote_factory=_pyannote_factory,
        )
        assert isinstance(backend, FakeBackend)
        assert backend.settings["kind"] == "pyannote"

    def test_pyannote_default_factory_validates_token(self, monkeypatch):
        # No pyannote_factory injected -> real pyannote_backend_factory runs,
        # which builds PyannoteDiarizer, which requires an HF token in env.
        monkeypatch.delenv("HF_TOKEN", raising=False)
        monkeypatch.delenv("HUGGING_FACE_HUB_TOKEN", raising=False)
        with pytest.raises(pb.PyannoteConfigError):
            pb.select_backend_factory(
                {"diarizeBackend": "pyannote"},
                speechbrain_factory=_speechbrain_factory,
            )

    def test_pyannote_default_factory_builds_with_token(self, monkeypatch):
        monkeypatch.setenv("HF_TOKEN", "tok-present")
        backend = pb.select_backend_factory(
            {"diarizeBackend": "pyannote"},
            speechbrain_factory=_speechbrain_factory,
        )
        assert isinstance(backend, pb.PyannoteDiarizer)


# --------------------------------------------------------------------------- #
# pyannote_backend_factory + PyannoteDiarizer constructor (token plumbing only)
# --------------------------------------------------------------------------- #
class TestPyannoteBackendFactory:
    def test_factory_requires_token(self, monkeypatch):
        monkeypatch.delenv("HF_TOKEN", raising=False)
        monkeypatch.delenv("HUGGING_FACE_HUB_TOKEN", raising=False)
        with pytest.raises(pb.PyannoteConfigError):
            pb.pyannote_backend_factory({})

    def test_factory_builds_diarizer_with_token(self, monkeypatch):
        monkeypatch.delenv("HF_TOKEN", raising=False)
        monkeypatch.setenv("HUGGING_FACE_HUB_TOKEN", "tok")
        backend = pb.pyannote_backend_factory({"device": "cpu"})
        assert isinstance(backend, pb.PyannoteDiarizer)
        # constructor stored the token + settings without importing torch.
        assert backend._token == "tok"
        assert backend._settings == {"device": "cpu"}

    def test_diarizer_constructor_injectable_env(self):
        # env is injectable so the constructor never touches os.environ.
        backend = pb.PyannoteDiarizer({}, env={"HF_TOKEN": "injected"})
        assert backend._token == "injected"

    def test_diarizer_constructor_missing_token_raises(self):
        with pytest.raises(pb.PyannoteConfigError):
            pb.PyannoteDiarizer({}, env={})

    def test_conforms_to_diarizer_backend_seam(self, monkeypatch):
        # PyannoteDiarizer must satisfy the existing diarize.DiarizerBackend
        # Protocol so diarize.py can drive it unchanged. The Protocol is not
        # @runtime_checkable, so assert structural conformance: the seam method
        # exists with the same call shape (audio_path + keyword-only sinks).
        import inspect

        monkeypatch.setenv("HF_TOKEN", "tok")
        backend = pb.pyannote_backend_factory({})
        method = backend.detect_and_embed
        assert callable(method)
        params = inspect.signature(method).parameters
        assert "audio_path" in params
        assert "on_progress" in params
        assert "should_cancel" in params

        # Static conformance: a DiarizerBackend-typed binding accepts it.
        from media_studio.features.diarize import DiarizerBackend

        seam: DiarizerBackend = backend
        assert seam is backend


# --------------------------------------------------------------------------- #
# asset registration (BOTH gated repos)
# --------------------------------------------------------------------------- #
class TestAssetRegistration:
    def test_both_gated_assets_registered_at_import(self):
        pipeline = manifest.get_asset(pb.PIPELINE_ASSET_NAME)
        segmentation = manifest.get_asset(pb.SEGMENTATION_ASSET_NAME)
        assert pipeline is not None
        assert segmentation is not None
        assert pipeline.installer == "hf"
        assert pipeline.hf_repo == pb.PYANNOTE_PIPELINE
        assert segmentation.hf_repo == pb.PYANNOTE_SEGMENTATION
        assert pb.REQUIRED_ASSETS == (pb.PIPELINE_ASSET_NAME, pb.SEGMENTATION_ASSET_NAME)

    def test_register_is_idempotent(self):
        # Re-registering identical entries is a no-op (module re-import safe).
        before = manifest.registry_snapshot()
        pb.register_pyannote_assets()
        pb.register_pyannote_assets()
        assert manifest.get_asset(pb.PIPELINE_ASSET_NAME) == before[pb.PIPELINE_ASSET_NAME]


# --------------------------------------------------------------------------- #
# default_models_present (drives the offline gate, like diarize)
# --------------------------------------------------------------------------- #
def _make_snapshot(cache_root: Path, repo_id: str) -> None:
    """Create a non-empty HF snapshot dir so installed-detection counts it."""
    repo_dir = hf_repo_dir(repo_id, {"HF_HUB_CACHE": str(cache_root)})
    snap = repo_dir / "snapshots" / "abc123"
    snap.mkdir(parents=True, exist_ok=True)
    (snap / "config.yaml").write_text("present", encoding="utf-8")


class TestDefaultModelsPresent:
    def test_true_when_both_snapshots_present(self, tmp_path, monkeypatch):
        cache = tmp_path / "hub"
        monkeypatch.setenv("HF_HUB_CACHE", str(cache))
        _make_snapshot(cache, pb.PYANNOTE_PIPELINE)
        _make_snapshot(cache, pb.PYANNOTE_SEGMENTATION)
        assert pb.default_models_present({}) is True

    def test_false_when_one_missing(self, tmp_path, monkeypatch):
        cache = tmp_path / "hub"
        monkeypatch.setenv("HF_HUB_CACHE", str(cache))
        _make_snapshot(cache, pb.PYANNOTE_PIPELINE)  # only the pipeline, not segmentation
        assert pb.default_models_present({}) is False

    def test_false_when_none_present(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path / "empty"))
        assert pb.default_models_present({}) is False

    def test_false_when_asset_entry_unregistered(self, tmp_path, monkeypatch):
        # Exercise the `entry is None` branch: drop one asset from the registry.
        cache = tmp_path / "hub"
        monkeypatch.setenv("HF_HUB_CACHE", str(cache))
        _make_snapshot(cache, pb.PYANNOTE_PIPELINE)
        _make_snapshot(cache, pb.PYANNOTE_SEGMENTATION)
        snapshot = manifest.registry_snapshot()
        try:
            reduced = {k: v for k, v in snapshot.items() if k != pb.SEGMENTATION_ASSET_NAME}
            manifest.registry_restore(reduced)
            assert pb.default_models_present({}) is False
        finally:
            manifest.registry_restore(snapshot)
