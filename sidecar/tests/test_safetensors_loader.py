"""Unit tests for the verify-before-load safetensors gate (WU B4 / I2).

The gate is torch-FREE by design: it refuses any non-``.safetensors`` container
(the pickle / RCE gate), optionally re-verifies the on-disk sha256, then delegates
the tensor read to an injectable ``load_file`` seam and the state-dict application
to the model's own ``load_state_dict``. These tests inject a fake reader + a fake
model (mock the file bytes) so no torch / safetensors is ever imported, and cover
the loud-fail arcs (wrong extension, sha mismatch, key/shape mismatch propagation)
that make the loader safe. The real ``safetensors.torch.load_file`` seam is
``# pragma: no cover`` (heavy native), mirroring every other Phase-8 backend.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest
from media_studio.features import _safetensors_loader as loader
from media_studio.features._safetensors_loader import WeightLoadError


# --------------------------------------------------------------------------- #
# assert_safetensors_path — the pickle-refusal gate
# --------------------------------------------------------------------------- #
def test_assert_safetensors_path_accepts_safetensors() -> None:
    assert loader.assert_safetensors_path("models/vinet-s-saliency.safetensors") == (
        "models/vinet-s-saliency.safetensors"
    )


def test_assert_safetensors_path_accepts_pathlib(tmp_path: Path) -> None:
    p = tmp_path / "transnetv2.safetensors"
    assert loader.assert_safetensors_path(p) == str(p)


@pytest.mark.parametrize(
    "bad", ["weights.pth", "weights.pt", "finetuning_TalkSet.model", "weights", "x.safetensors.pth"]
)
def test_assert_safetensors_path_refuses_pickle_containers_loud(bad: str) -> None:
    with pytest.raises(WeightLoadError, match="torch.load / pickle is forbidden"):
        loader.assert_safetensors_path(bad)


# --------------------------------------------------------------------------- #
# sha256_file + verify_sha256
# --------------------------------------------------------------------------- #
def test_sha256_file_matches_hashlib(tmp_path: Path) -> None:
    data = b"tensor-bytes" * 5000  # spans multiple 1 MiB-less chunks in one read
    f = tmp_path / "w.safetensors"
    f.write_bytes(data)
    assert loader.sha256_file(f) == hashlib.sha256(data).hexdigest()


def test_sha256_file_small_chunk_size_streams(tmp_path: Path) -> None:
    data = b"abcdefgh" * 4
    f = tmp_path / "w.safetensors"
    f.write_bytes(data)
    assert loader.sha256_file(f, chunk_size=7) == hashlib.sha256(data).hexdigest()


def test_verify_sha256_returns_actual_on_match(tmp_path: Path) -> None:
    data = b"content"
    f = tmp_path / "w.safetensors"
    f.write_bytes(data)
    expected = hashlib.sha256(data).hexdigest()
    assert loader.verify_sha256(f, expected.upper()) == expected  # case-insensitive


def test_verify_sha256_raises_loud_on_mismatch(tmp_path: Path) -> None:
    f = tmp_path / "w.safetensors"
    f.write_bytes(b"content")
    with pytest.raises(WeightLoadError, match="sha256 mismatch"):
        loader.verify_sha256(f, "0" * 64)


# --------------------------------------------------------------------------- #
# load_state_dict_safetensors — gate + read via injected seam
# --------------------------------------------------------------------------- #
def test_load_state_dict_uses_injected_reader_without_sha(tmp_path: Path) -> None:
    f = tmp_path / "w.safetensors"
    f.write_bytes(b"ignored-by-fake")
    sentinel = {"backbone.weight": object()}
    seen: list[str] = []

    def fake_reader(path: str) -> dict[str, Any]:
        seen.append(path)
        return sentinel

    out = loader.load_state_dict_safetensors(f, load_file=fake_reader)
    assert out is sentinel
    assert seen == [str(f)]


def test_load_state_dict_reverifies_sha_before_read(tmp_path: Path) -> None:
    data = b"real-bytes"
    f = tmp_path / "w.safetensors"
    f.write_bytes(data)
    good = hashlib.sha256(data).hexdigest()
    out = loader.load_state_dict_safetensors(f, expected_sha256=good, load_file=lambda _p: {"k": 1})
    assert out == {"k": 1}


def test_load_state_dict_sha_mismatch_blocks_read(tmp_path: Path) -> None:
    f = tmp_path / "w.safetensors"
    f.write_bytes(b"real-bytes")
    called = False

    def fake_reader(_path: str) -> dict[str, Any]:
        nonlocal called
        called = True
        return {}

    with pytest.raises(WeightLoadError, match="sha256 mismatch"):
        loader.load_state_dict_safetensors(f, expected_sha256="0" * 64, load_file=fake_reader)
    assert called is False  # the read never happens on a bad hash


def test_load_state_dict_refuses_non_safetensors_before_read(tmp_path: Path) -> None:
    f = tmp_path / "w.pth"
    f.write_bytes(b"pickled")
    with pytest.raises(WeightLoadError, match="pickle is forbidden"):
        loader.load_state_dict_safetensors(f, load_file=lambda _p: {})


# --------------------------------------------------------------------------- #
# load_into_model — strict apply, loud-fail propagation
# --------------------------------------------------------------------------- #
class _FakeModel:
    """Records the state dict passed to ``load_state_dict`` (torch stand-in)."""

    def __init__(self) -> None:
        self.loaded: dict[str, Any] | None = None

    def load_state_dict(self, state_dict: dict[str, Any]) -> None:
        self.loaded = state_dict


def test_load_into_model_applies_state_dict(tmp_path: Path) -> None:
    f = tmp_path / "w.safetensors"
    f.write_bytes(b"x")
    sd = {"decoder.convtsp1.weight": 1}
    model = _FakeModel()
    result = loader.load_into_model(model, f, load_file=lambda _p: sd)
    assert result is model
    assert model.loaded is sd


def test_load_into_model_propagates_strict_mismatch_loud(tmp_path: Path) -> None:
    # A wrong-arch / corrupt weight makes torch's strict load_state_dict raise; the
    # loader must PROPAGATE it (never swallow -> never a silent partial load).
    f = tmp_path / "w.safetensors"
    f.write_bytes(b"x")

    class _StrictModel:
        def load_state_dict(self, _sd: dict[str, Any]) -> None:
            raise RuntimeError("Missing key(s) in state_dict: 'backbone.base1.0.weight'")

    with pytest.raises(RuntimeError, match="Missing key"):
        loader.load_into_model(_StrictModel(), f, load_file=lambda _p: {"wrong": 1})
