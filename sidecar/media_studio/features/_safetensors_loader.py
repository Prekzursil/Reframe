"""Verify-before-load gate for re-hosted safetensors model weights (WU B4 / I2).

SECURITY (I2): the ONLY permitted weight container on the load path is
``.safetensors``. ``torch.load`` / pickle is FORBIDDEN — a pickle can execute
arbitrary code at load time (an RCE surface), so this gate REFUSES any
non-safetensors path (``.pth`` / ``.pt`` / ``.model`` / anything else) LOUD,
before a single byte is deserialized. It never silently falls back.

The gate is deliberately torch-FREE: it validates the extension and (optionally)
re-verifies the on-disk sha256 against the manifest pin, then delegates the
actual tensor read to an injectable ``load_file`` seam (default:
``safetensors.torch.load_file``) and the state-dict application to the model's
own ``load_state_dict`` (strict=True, torch's default — a missing/unexpected key
or a shape mismatch raises, never a silent partial load). Only the default seam
touches torch/safetensors, so the gate logic is unit-tested at 100% without
either being installed (mirrors the ``Real*Backend`` heavy-seam convention).
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path
from typing import Any

#: The ONE permitted weight-container extension (pickle containers are refused).
SAFETENSORS_SUFFIX = ".safetensors"

#: path -> flat ``{name: tensor}`` state dict (the safetensors.torch.load_file shape).
StateDictLoader = Callable[[str], "dict[str, Any]"]


class WeightLoadError(RuntimeError):
    """A weight failed the verify-before-load gate (raised LOUD, never silent)."""


def assert_safetensors_path(path: str | Path) -> str:
    """Return ``path`` as ``str`` iff it is a ``.safetensors`` file; else raise LOUD.

    The pickle-refusal gate: a ``.pth`` / ``.pt`` / ``.model`` / any other
    container reaching the loader is a hard error (torch.load / pickle is an RCE
    surface), never a fallback.
    """
    text = str(path)
    if not text.endswith(SAFETENSORS_SUFFIX):
        raise WeightLoadError(
            f"refusing to load {text!r}: only {SAFETENSORS_SUFFIX} weights are "
            "permitted on the load path (torch.load / pickle is forbidden)"
        )
    return text


def sha256_file(path: str | Path, *, chunk_size: int = 1 << 20) -> str:
    """Stream ``path`` and return its lowercase hex sha256 (bounded memory)."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_sha256(path: str | Path, expected: str) -> str:
    """Re-verify the on-disk file against ``expected``; raise LOUD on mismatch.

    Catches cache tampering / bit-rot at LOAD time (a second anchor beyond the
    manager's download-time check). Comparison is case-insensitive hex.
    """
    actual = sha256_file(path)
    if actual.lower() != str(expected).lower():
        raise WeightLoadError(
            f"sha256 mismatch for {str(path)!r}: manifest pins {expected}, "
            f"on-disk file hashes {actual} — refusing to load (tamper / corruption)"
        )
    return actual


def load_state_dict_safetensors(
    path: str | Path,
    *,
    expected_sha256: str | None = None,
    load_file: StateDictLoader | None = None,
) -> dict[str, Any]:
    """Gate + read a flat state dict from a safetensors file (safetensors ONLY).

    1. refuse any non-``.safetensors`` path (pickle RCE gate), LOUD;
    2. optionally re-verify the on-disk sha256 vs the manifest pin, LOUD on
       mismatch;
    3. read the tensors via ``load_file`` (default: ``safetensors.torch.load_file``).

    ``load_file`` is injectable so the gate is unit-tested without torch /
    safetensors; the default seam is the only torch-touching line.
    """
    text = assert_safetensors_path(path)
    if expected_sha256 is not None:
        verify_sha256(text, expected_sha256)
    reader = load_file or _default_load_file
    return reader(text)


def load_into_model(
    model: Any,
    path: str | Path,
    *,
    expected_sha256: str | None = None,
    load_file: StateDictLoader | None = None,
) -> Any:
    """Load a safetensors state dict INTO ``model`` and return it (strict).

    ``model.load_state_dict`` runs with torch's strict default, so a missing /
    unexpected key or a shape mismatch raises — a corrupt or wrong-architecture
    weight fails LOUD rather than half-loading. The gate + read is
    :func:`load_state_dict_safetensors`.
    """
    state_dict = load_state_dict_safetensors(path, expected_sha256=expected_sha256, load_file=load_file)
    model.load_state_dict(state_dict)
    return model


def _default_load_file(path: str) -> dict[str, Any]:  # pragma: no cover - torch/safetensors native seam
    """Default tensor reader: ``safetensors.torch.load_file`` (returns torch tensors).

    The ONE line permitted to import safetensors/torch on the load path; a
    ``.pth`` / pickle can never reach here (the extension gate refuses it first).
    """
    from safetensors.torch import load_file as _load_file  # noqa: PLC0415

    return _load_file(path)


__all__ = [
    "SAFETENSORS_SUFFIX",
    "StateDictLoader",
    "WeightLoadError",
    "assert_safetensors_path",
    "load_into_model",
    "load_state_dict_safetensors",
    "sha256_file",
    "verify_sha256",
]
