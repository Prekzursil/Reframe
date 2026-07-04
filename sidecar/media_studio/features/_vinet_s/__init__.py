"""Vendored ViNet-S video-saliency network (ViNet-Saliency/vinet_v2, CC-BY-NC-SA 4.0).

PRODUCTION VENDORING (WU B4): the saliency network is vendored here from
``ViNet-Saliency/vinet_v2`` — ``ViNet_S/ViNet_S_model.py`` (:mod:`.model`) + its
``from model_utils import *`` dependency ``ViNet_S/model_utils.py``
(:mod:`.model_utils`), the ICASSP-2025 "ViNet++" minimalistic saliency model
(arXiv:2502.00397). LICENSE **CC-BY-NC-SA 4.0** — see the sibling ``LICENSE``:
personal / NON-COMMERCIAL use only, with attribution + share-alike (redistributed
derivatives carry the same license). ATTRIBUTION: © 2025 Rohit Girmaji, Siddharth
Jain, Bhav Beri, Sarthak Bansal, Vineet Gandhi (IIIT Hyderabad).

The re-hosted ``vinet-s-saliency.safetensors`` weight (WU I1; the visual-only
DHF1K checkpoint — the no-face crop-track model) loads into
``VideoSaliencyModel(use_upsample=True, num_hier=3, num_clips=32,
grouped_conv=True, root_grouping=True, depth=False, efficientnet=False,
BiCubic=False, maxpool3d=True)`` — the exact config the backend builds; its 470
``backbone.*`` / ``decoder.*`` keys (9.5M params, 36 MB) match the weight.

This package ``__init__`` is intentionally **light** — it imports NOTHING heavy
(no torch). The model modules (:mod:`.model`, :mod:`.model_utils`) import torch at
module top, so they are imported LAZILY only from
:mod:`media_studio.features.saliency_backend.ViNetSaliencyBackend` and NEVER at
package import or during the test suite. Every top-level statement in those modules
carries ``# pragma: no cover``; being never imported under the coverage run they
report zero measurable statements and never perturb the 100% gate (mirrors the
``_lightasd`` heavy-seam convention).
"""

from __future__ import annotations

#: Upstream source coordinates (provenance for the vendored ViNet-S network).
VINET_S_UPSTREAM = "https://github.com/ViNet-Saliency/vinet_v2"
VINET_S_LICENSE = "CC-BY-NC-SA-4.0"
VINET_S_PAPER = "arXiv:2502.00397"  # ViNet++ (ICASSP 2025)
#: The re-host weight basename the backend loads (verify-before-load: safetensors).
VINET_S_WEIGHT_NAME = "vinet-s-saliency.safetensors"

__all__ = [
    "VINET_S_LICENSE",
    "VINET_S_PAPER",
    "VINET_S_UPSTREAM",
    "VINET_S_WEIGHT_NAME",
]
