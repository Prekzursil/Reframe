"""Runtime HF-revision pinning for the three heavy model backends (WU-S5).

The asset REGISTRY already hard-enforces a 40-hex commit pin for every
``installer="hf"`` entry (``assets/manifest.py`` ``_COMMIT_HASH_RE``, with an
explicit comment that a branch/tag like ``"main"`` is a MOVING target and is
rejected). The RUNTIME load calls, however, used to resolve their weights from a
FLOATING Hub revision, so the registration pin bought nothing at load time:

* ``diarize_backend.SpeechBrainDiarizer._ensure_models`` called
  ``VAD.from_hparams`` / ``EncoderClassifier.from_hparams`` with a bare
  ``source=<repo id>`` and no ``revision``;
* ``parakeet_asr_backend.RealParakeetLoader.load`` called NeMo's
  ``ASRModel.from_pretrained``, which has **no revision parameter at all**
  (verified against NVIDIA/NeMo v2.4.0 ``nemo/core/classes/common.py``; its own
  docstring says "Use restore_from() to instantiate from a local .nemo file");
* ``pyannote_backend.PyannoteDiarizer._ensure_pipeline`` called
  ``Pipeline.from_pretrained(<repo id>)`` with no ``@<revision>`` suffix.

A floating ref means a compromised upstream repo can change the bytes that get
loaded, and every one of these formats EXECUTES CODE at load time (SpeechBrain
HyperPyYAML ``!new`` / ``!apply`` constructors plus an optional ``custom.py``;
a NeMo ``.nemo`` archive; a pyannote ``config.yaml``).

These tests pin the RESOLUTION side — the pure, registry-driven logic where the
security property lives — so a load call can no longer drift from its
registration. The heavy load bodies stay ``# pragma: no cover``, but they are
still DRIVEN here with hand-built fakes (no weights, no network, no model, no
gated token) to prove the pinned value actually reaches the third-party call.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any

import pytest
from media_studio.assets import manifest
from media_studio.features import diarize as _diarize
from media_studio.features import diarize_backend as db
from media_studio.features import parakeet_asr as _pk
from media_studio.features import parakeet_asr_backend as pkb
from media_studio.features import pyannote_backend as pb

_PROBE_ASSET = "wu-s5-probe-asset"
_PROBE_REPO = "wu-s5/probe-repo"
_PROBE_REVISION = "a" * 40


@pytest.fixture
def clean_registry():
    """Snapshot + restore the asset registry so a tamper probe cannot leak."""
    snapshot = manifest.registry_snapshot()
    try:
        yield snapshot
    finally:
        manifest.registry_restore(snapshot)


def _hf_entry(*, repo: str = _PROBE_REPO, revision: str = _PROBE_REVISION) -> manifest.AssetEntry:
    return manifest.AssetEntry(
        name=_PROBE_ASSET,
        kind="model",
        size_mb=1,
        installer="hf",
        hf_repo=repo,
        hf_revision=revision,
    )


# --------------------------------------------------------------------------- #
# the shared resolver: the asset REGISTRY is the single source of truth
# --------------------------------------------------------------------------- #
class TestResolvePinnedHfSource:
    def test_returns_the_registered_repo_and_commit_pin(self):
        repo, revision = db.resolve_pinned_hf_source(_diarize.VAD_ASSET_NAME, _diarize.VAD_HF_REPO)
        assert repo == _diarize.VAD_HF_REPO
        # The revision comes from the REGISTRY, not from a constant in the
        # loading module — that is what makes drift impossible.
        assert revision == _diarize.VAD_HF_REVISION
        assert db._COMMIT_HASH_RE.match(revision)

    def test_local_recheck_regex_matches_the_registration_gate(self):
        # The load-site re-check must accept EXACTLY what the registration gate
        # accepts. Asserting the two patterns are identical is what stops the
        # deliberate (defense-in-depth) duplication from silently drifting.
        assert db._COMMIT_HASH_RE.pattern == manifest._COMMIT_HASH_RE.pattern

    def test_unregistered_asset_is_refused(self, clean_registry):
        reduced = {k: v for k, v in clean_registry.items() if k != _diarize.VAD_ASSET_NAME}
        manifest.registry_restore(reduced)
        with pytest.raises(db.UnpinnedModelRevisionError) as exc:
            db.resolve_pinned_hf_source(_diarize.VAD_ASSET_NAME, _diarize.VAD_HF_REPO)
        assert _diarize.VAD_ASSET_NAME in str(exc.value)

    def test_non_hf_installer_is_refused(self, clean_registry):
        # Only installer="hf" carries the manifest's validated commit pin, so a
        # download/env entry may not be used to source a runtime revision — even
        # when it happens to carry matching hf_* fields.
        manifest.register_asset(
            manifest.AssetEntry(
                name=_PROBE_ASSET,
                kind="model",
                size_mb=1,
                dest="models/probe.bin",
                installer="download",
                url="https://example.invalid/probe.bin",
                sha256="b" * 64,
                hf_repo=_PROBE_REPO,
                hf_revision=_PROBE_REVISION,
            )
        )
        with pytest.raises(db.UnpinnedModelRevisionError, match="installer"):
            db.resolve_pinned_hf_source(_PROBE_ASSET, _PROBE_REPO)

    def test_repo_drift_between_registry_and_load_site_is_refused(self, clean_registry):
        # THE drift guard: the repo the loader is about to fetch must be the repo
        # the registry pinned. A mismatch means one side was edited alone.
        manifest.register_asset(_hf_entry(repo="wu-s5/other-repo"))
        with pytest.raises(db.UnpinnedModelRevisionError, match="wu-s5/probe-repo"):
            db.resolve_pinned_hf_source(_PROBE_ASSET, _PROBE_REPO)

    def test_missing_repo_is_refused(self, clean_registry):
        entry = _hf_entry()
        object.__setattr__(entry, "hf_repo", None)
        manifest.register_asset(entry)
        with pytest.raises(db.UnpinnedModelRevisionError):
            db.resolve_pinned_hf_source(_PROBE_ASSET, _PROBE_REPO)

    @pytest.mark.parametrize("floating", ["main", "v3.1", "", "abc123"])
    def test_floating_revision_is_refused(self, clean_registry, floating):
        # A frozen dataclass can still be rewritten through object.__setattr__
        # (the same door manifest.__post_init__ itself uses), so simulate a
        # registry that has been loosened to a MOVING ref and prove the LOAD-SITE
        # re-check refuses it independently of the registration gate.
        entry = _hf_entry()
        object.__setattr__(entry, "hf_revision", floating)
        manifest.register_asset(entry)
        with pytest.raises(db.UnpinnedModelRevisionError, match="commit"):
            db.resolve_pinned_hf_source(_PROBE_ASSET, _PROBE_REPO)

    def test_error_is_a_runtime_error_so_a_job_surfaces_it(self):
        # Mirrors DiarizeBackendUnavailableError: a typed RuntimeError, so the
        # job thread reports an actionable message instead of crashing raw.
        assert issubclass(db.UnpinnedModelRevisionError, RuntimeError)

    def test_every_pinned_backend_asset_is_registered_with_a_commit(self):
        # Inventory: all five heavy-backend HF assets this WU pins.
        for asset_name, repo in (
            (_diarize.VAD_ASSET_NAME, _diarize.VAD_HF_REPO),
            (_diarize.ECAPA_ASSET_NAME, _diarize.ECAPA_HF_REPO),
            (_pk.ASSET_NAME, _pk.DEFAULT_MODEL),
            (pb.PIPELINE_ASSET_NAME, pb.PYANNOTE_PIPELINE),
            (pb.SEGMENTATION_ASSET_NAME, pb.PYANNOTE_SEGMENTATION),
        ):
            resolved_repo, revision = db.resolve_pinned_hf_source(asset_name, repo)
            assert resolved_repo == repo
            assert len(revision) == 40


# --------------------------------------------------------------------------- #
# speechbrain: the pin must reach VAD/ECAPA from_hparams
# --------------------------------------------------------------------------- #
def _install_fake_speechbrain(monkeypatch) -> list[dict[str, Any]]:
    """Inject fake ``speechbrain.inference`` modules that RECORD from_hparams."""
    calls: list[dict[str, Any]] = []

    class _FakeVAD:
        @staticmethod
        def from_hparams(**kwargs: Any) -> object:
            calls.append({"model": "vad", **kwargs})
            return object()

    class _FakeEncoder:
        @staticmethod
        def from_hparams(**kwargs: Any) -> object:
            calls.append({"model": "encoder", **kwargs})
            return object()

    sb = types.ModuleType("speechbrain")
    inference = types.ModuleType("speechbrain.inference")
    vad_mod = types.ModuleType("speechbrain.inference.VAD")
    cls_mod = types.ModuleType("speechbrain.inference.classifiers")
    vad_mod.VAD = _FakeVAD
    cls_mod.EncoderClassifier = _FakeEncoder
    sb.inference = inference
    inference.VAD = vad_mod
    inference.classifiers = cls_mod
    for name, mod in (
        ("speechbrain", sb),
        ("speechbrain.inference", inference),
        ("speechbrain.inference.VAD", vad_mod),
        ("speechbrain.inference.classifiers", cls_mod),
    ):
        monkeypatch.setitem(sys.modules, name, mod)
    return calls


class TestSpeechBrainLoadIsPinned:
    def test_ensure_models_passes_the_registered_commit_to_from_hparams(self, monkeypatch):
        calls = _install_fake_speechbrain(monkeypatch)
        inst = db.SpeechBrainDiarizer({"device": "cpu"})
        inst._ensure_models()
        by_model = {call["model"]: call for call in calls}
        # SpeechBrain forwards ``revision`` to the fetch of BOTH hyperparams.yaml
        # (HyperPyYAML !new/!apply) and custom.py — the two code-executing
        # artifacts — so pinning it closes the mutable-upstream load vector.
        assert by_model["vad"]["source"] == _diarize.VAD_HF_REPO
        assert by_model["vad"]["revision"] == _diarize.VAD_HF_REVISION
        assert by_model["encoder"]["source"] == _diarize.ECAPA_HF_REPO
        assert by_model["encoder"]["revision"] == _diarize.ECAPA_HF_REVISION

    def test_ensure_models_refuses_when_the_registry_pin_is_gone(self, monkeypatch, clean_registry):
        _install_fake_speechbrain(monkeypatch)
        reduced = {k: v for k, v in clean_registry.items() if k != _diarize.ECAPA_ASSET_NAME}
        manifest.registry_restore(reduced)
        inst = db.SpeechBrainDiarizer({"device": "cpu"})
        with pytest.raises(db.UnpinnedModelRevisionError):
            inst._ensure_models()


# --------------------------------------------------------------------------- #
# pyannote: repo@commit is the documented pin syntax for Pipeline.from_pretrained
# --------------------------------------------------------------------------- #
class TestPyannotePinnedCheckpoint:
    def test_checkpoint_is_repo_at_registered_commit(self):
        checkpoint = pb.pinned_pipeline_checkpoint()
        repo, sep, revision = checkpoint.partition("@")
        # pyannote.audio 3.1 splits the checkpoint on "@" and forwards the tail as
        # ``revision`` to hf_hub_download (verified against
        # pyannote-audio 3.1.1 pyannote/audio/core/pipeline.py).
        assert sep == "@"
        assert repo == pb.PYANNOTE_PIPELINE
        assert revision == pb.PYANNOTE_PIPELINE_REVISION
        assert len(revision) == 40

    def test_checkpoint_refuses_when_the_pipeline_asset_is_unregistered(self, clean_registry):
        reduced = {k: v for k, v in clean_registry.items() if k != pb.PIPELINE_ASSET_NAME}
        manifest.registry_restore(reduced)
        with pytest.raises(db.UnpinnedModelRevisionError):
            pb.pinned_pipeline_checkpoint()

    def test_ensure_pipeline_loads_the_pinned_checkpoint(self, monkeypatch):
        recorded: dict[str, Any] = {}

        class _FakeLoadedPipeline:
            def to(self, device: Any) -> None:
                recorded["device"] = device

        class _FakePipeline:
            @staticmethod
            def from_pretrained(checkpoint: str, use_auth_token: Any = None) -> _FakeLoadedPipeline:
                recorded["checkpoint"] = checkpoint
                recorded["token"] = use_auth_token
                return _FakeLoadedPipeline()

        pkg = types.ModuleType("pyannote")
        audio_mod = types.ModuleType("pyannote.audio")
        audio_mod.Pipeline = _FakePipeline
        pkg.audio = audio_mod
        monkeypatch.setitem(sys.modules, "pyannote", pkg)
        monkeypatch.setitem(sys.modules, "pyannote.audio", audio_mod)

        backend = pb.PyannoteDiarizer({}, env={"HF_TOKEN": "tok"})
        backend._ensure_pipeline()
        assert recorded["checkpoint"] == f"{pb.PYANNOTE_PIPELINE}@{pb.PYANNOTE_PIPELINE_REVISION}"
        assert recorded["token"] == "tok"


# --------------------------------------------------------------------------- #
# parakeet / NeMo: from_pretrained cannot be pinned -> pinned LOCAL .nemo restore
# --------------------------------------------------------------------------- #
class TestFindNemoCheckpoint:
    def test_returns_the_single_nemo_archive(self, tmp_path: Path):
        (tmp_path / "README.md").write_text("noise", encoding="utf-8")
        ckpt = tmp_path / "parakeet-tdt-0.6b-v3.nemo"
        ckpt.write_bytes(b"weights")
        assert pkb.find_nemo_checkpoint(str(tmp_path)) == str(ckpt)

    def test_refuses_when_no_nemo_archive_is_present(self, tmp_path: Path):
        (tmp_path / "README.md").write_text("noise", encoding="utf-8")
        with pytest.raises(pkb.UnpinnedModelRevisionError, match="no .nemo"):
            pkb.find_nemo_checkpoint(str(tmp_path))

    def test_refuses_an_ambiguous_snapshot(self, tmp_path: Path):
        (tmp_path / "a.nemo").write_bytes(b"x")
        (tmp_path / "b.nemo").write_bytes(b"y")
        with pytest.raises(pkb.UnpinnedModelRevisionError, match="ambiguous"):
            pkb.find_nemo_checkpoint(str(tmp_path))


def _snapshot_with_nemo(tmp_path: Path) -> tuple[Path, Path]:
    snap = tmp_path / "snapshots" / _pk.ASSET_REVISION
    snap.mkdir(parents=True)
    ckpt = snap / "parakeet-tdt-0.6b-v3.nemo"
    ckpt.write_bytes(b"weights")
    return snap, ckpt


class TestResolvePinnedCheckpoint:
    def test_fetches_the_pinned_revision_local_only(self, tmp_path: Path):
        snap, ckpt = _snapshot_with_nemo(tmp_path)
        seen: dict[str, Any] = {}

        def _fetch(*, repo_id: str, revision: str, local_files_only: bool) -> str:
            seen.update(repo_id=repo_id, revision=revision, local_files_only=local_files_only)
            return str(snap)

        assert pkb.resolve_pinned_checkpoint(snapshot_fetch=_fetch) == str(ckpt)
        assert seen == {
            "repo_id": _pk.DEFAULT_MODEL,
            "revision": _pk.ASSET_REVISION,
            # local_files_only=True: the runtime load never downloads. Fetching
            # weights is assets.ensure's job (pinned + progress-reported).
            "local_files_only": True,
        }

    def test_refuses_a_model_the_registry_did_not_pin(self, tmp_path: Path):
        snap, _ = _snapshot_with_nemo(tmp_path)

        def _fetch(**_kw: Any) -> str:  # pragma: no cover - must never be reached
            raise AssertionError("must refuse before fetching")

        with pytest.raises(pkb.UnpinnedModelRevisionError, match="attacker/parakeet"):
            pkb.resolve_pinned_checkpoint(model="attacker/parakeet", snapshot_fetch=_fetch)
        assert snap.exists()

    def test_refuses_when_the_asset_is_unregistered(self, clean_registry):
        reduced = {k: v for k, v in clean_registry.items() if k != _pk.ASSET_NAME}
        manifest.registry_restore(reduced)
        with pytest.raises(pkb.UnpinnedModelRevisionError):
            pkb.resolve_pinned_checkpoint(snapshot_fetch=lambda **_kw: "unused")


class TestRealParakeetLoaderIsPinned:
    def test_load_restores_from_the_pinned_local_checkpoint(self, tmp_path: Path, monkeypatch):
        snap, ckpt = _snapshot_with_nemo(tmp_path)
        seen: dict[str, Any] = {}
        restored: dict[str, Any] = {}

        def _fetch(*, repo_id: str, revision: str, local_files_only: bool) -> str:
            seen.update(repo_id=repo_id, revision=revision, local_files_only=local_files_only)
            return str(snap)

        class _FakeNemoModel:
            def to(self, target: Any) -> _FakeNemoModel:
                restored["device"] = target
                return self

            def eval(self) -> None:
                restored["eval"] = True

        class _FakeAsrModel:
            @staticmethod
            def restore_from(restore_path: str) -> _FakeNemoModel:
                restored["path"] = restore_path
                return _FakeNemoModel()

            @staticmethod
            def from_pretrained(**_kw: Any) -> None:  # pragma: no cover - must never run
                raise AssertionError("from_pretrained cannot be revision-pinned; it must not be used")

        nemo = types.ModuleType("nemo")
        collections = types.ModuleType("nemo.collections")
        asr = types.ModuleType("nemo.collections.asr")
        models = types.ModuleType("nemo.collections.asr.models")
        models.ASRModel = _FakeAsrModel
        asr.models = models
        collections.asr = asr
        nemo.collections = collections
        for name, mod in (
            ("nemo", nemo),
            ("nemo.collections", collections),
            ("nemo.collections.asr", asr),
            ("nemo.collections.asr.models", models),
        ):
            monkeypatch.setitem(sys.modules, name, mod)

        loader = pkb.RealParakeetLoader(snapshot_fetch=_fetch)
        built = loader.load(_pk.DEFAULT_MODEL, "cpu", "int8")
        assert seen["revision"] == _pk.ASSET_REVISION
        assert seen["local_files_only"] is True
        assert restored["path"] == str(ckpt)
        assert restored["eval"] is True
        # Cached per (model, device, compute_type): no second fetch/restore.
        assert loader.load(_pk.DEFAULT_MODEL, "cpu", "int8") is built
        loader.release()

    def test_default_loader_needs_no_injected_seam(self):
        # parakeet_asr._default_loader() constructs it with no arguments (prod
        # path), so the default seam must already be the real pinned materializer.
        assert pkb.RealParakeetLoader()._snapshot_fetch is pkb._default_snapshot_fetch


# --------------------------------------------------------------------------- #
# module surfaces (the heavy bodies stay pragma'd; the surface must import light)
# --------------------------------------------------------------------------- #
def test_backend_module_surfaces_export_the_pin_api():
    assert "UnpinnedModelRevisionError" in db.__all__
    assert "resolve_pinned_hf_source" in db.__all__
    assert "find_nemo_checkpoint" in pkb.__all__
    assert "resolve_pinned_checkpoint" in pkb.__all__
    assert "pinned_pipeline_checkpoint" in pb.__all__
