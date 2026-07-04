"""Opt-in (e2e) real-weights load+infer tests for the WU B4 re-hosted models.

DESELECTED FROM THE DEFAULT / COVERAGE GATE — marked ``e2e`` (pyproject
``addopts = "-m 'not e2e'"``), so it never runs in the torch-free 100%-coverage
run. It proves that the VENDORED ViNet-S / TransNetV2 architectures load the exact
re-hosted ``.safetensors`` weights through the verify-before-load gate
(safetensors ONLY, sha re-verified, ``load_state_dict`` strict) and produce the
expected output shapes.

Run explicitly on a machine that has torch + safetensors AND the weights on disk:

    pip install "media-studio-sidecar[reframe-gpu]"
    export REFRAME_VINET_S_WEIGHT=/path/to/vinet-s-saliency.safetensors
    export REFRAME_TRANSNETV2_WEIGHT=/path/to/transnetv2.safetensors
    pytest -m e2e tests/test_saliency_scene_weights_integration.py

Each test SKIPS (never fails) when torch/safetensors or its weight file is absent,
so a partial environment does not break the opt-in suite. The heavy imports live
INSIDE the tests (via ``importorskip``) so collecting this module in the torch-free
gate never pulls torch.
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.e2e

_VINET_S_SHA = "803e6d265d46d3f4f3d7ec2c6c2f3b4511f9ba176aa12e348ac317788ca0dc68"
_TRANSNETV2_SHA = "e2877ef6750ccbb3f02256bb4b5f4f53035111677be641d56b9723af499f881d"


def _weight_or_skip(env_var: str) -> str:
    path = os.environ.get(env_var)
    if not path or not os.path.isfile(path):
        pytest.skip(f"{env_var} not set to an existing weight file")
    return path


def test_vinet_s_vendored_arch_loads_rehosted_weight_and_infers() -> None:
    torch = pytest.importorskip("torch")
    pytest.importorskip("safetensors")
    weight = _weight_or_skip("REFRAME_VINET_S_WEIGHT")

    from media_studio.features._safetensors_loader import load_into_model
    from media_studio.features._vinet_s.model import VideoSaliencyModel

    model = VideoSaliencyModel(
        use_upsample=True,
        num_hier=3,
        num_clips=32,
        grouped_conv=True,
        root_grouping=True,
        depth=False,
        efficientnet=False,
        BiCubic=False,
        maxpool3d=True,
    )
    # verify-before-load: safetensors-only + sha re-verify + strict load_state_dict.
    from safetensors.torch import load_file

    load_into_model(model, weight, expected_sha256=_VINET_S_SHA, load_file=lambda p: load_file(p, device="cpu"))
    model.eval()
    # A 32-frame RGB clip [B, C, T, H, W] -> a single-channel saliency map.
    clip = torch.rand(1, 3, 32, 224, 384)
    with torch.no_grad():
        out = model(clip)
    sal = out.squeeze()
    assert sal.ndim == 2  # H x W saliency map


def test_transnetv2_vendored_arch_loads_rehosted_weight_and_infers() -> None:
    torch = pytest.importorskip("torch")
    pytest.importorskip("safetensors")
    weight = _weight_or_skip("REFRAME_TRANSNETV2_WEIGHT")

    from media_studio.features._safetensors_loader import load_into_model
    from media_studio.features._transnetv2.transnetv2_pytorch import TransNetV2

    model = TransNetV2()
    from safetensors.torch import load_file

    load_into_model(model, weight, expected_sha256=_TRANSNETV2_SHA, load_file=lambda p: load_file(p, device="cpu"))
    model.eval()
    # A [B, T, 27, 48, 3] uint8 clip -> per-frame shot-change logits.
    frames = torch.randint(0, 256, (1, 50, 27, 48, 3), dtype=torch.uint8)
    with torch.no_grad():
        single = model(frames)
    logits = single[0] if isinstance(single, tuple) else single
    assert logits.shape[0] == 1  # batch preserved
