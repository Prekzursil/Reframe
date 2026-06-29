"""Vendored Light-ASD visual active-speaker stack (S3FD detector + ASD model).

PRODUCTION VENDORING (R1 Phase 3): the heavy face-detect + active-speaker model
code is vendored here from ``Junhua-Liao/Light-ASD`` (commit
``ed38c232de5efe0261dbd68627c0ade7cdfe14eb``, **MIT** — see the sibling
``LICENSE`` file, redistribution permitted) so production NEVER depends on a
``$HOME`` checkout or a ``chdir``/``sys.path`` seam. The original repo's
``np.int`` numpy-1 idioms are dropped (this is numpy-2 clean) and the weight
files are resolved by PATH (constructor argument) instead of relative to the
process CWD.

This package ``__init__`` is intentionally **light** — it imports NOTHING heavy
(no torch / cv2). The model modules (:mod:`.model`, :mod:`.asd`, :mod:`.s3fd`)
each import torch/cv2 at module top (an ``nn.Module`` subclass needs ``torch.nn``
at class-definition time), so they are imported LAZILY only from inside
``_lightasd_infer.analyze_visual`` (a ``# pragma: no cover`` GPU-runtime seam) and
NEVER at package import or during the test suite. Every executable statement in
those modules carries ``# pragma: no cover``; since they are never imported under
the coverage run they report zero measurable statements and never perturb the
100% line+branch gate (mirrors the ``Real*Backend`` heavy-seam convention, but
adapted for torch model definitions that cannot be made import-light).

The two weight files (``sfd_face.pth`` + ``finetuning_TalkSet.model``) are
registered as on-demand, sha256-pinned assets in
:mod:`media_studio.assets.manifest`; their on-disk location is resolved by
``_lightasd_infer`` (a ``settings['lightAsdWeightsDir']`` override, else the
asset-manager install path).
"""

from __future__ import annotations

#: Upstream source coordinates (provenance for the vendored code + weights).
LIGHT_ASD_UPSTREAM = "https://github.com/Junhua-Liao/Light-ASD"
LIGHT_ASD_COMMIT = "ed38c232de5efe0261dbd68627c0ade7cdfe14eb"
LIGHT_ASD_LICENSE = "MIT"

#: The two weight file basenames the vendored loaders expect under the weights dir.
S3FD_WEIGHT_NAME = "sfd_face.pth"
ASD_WEIGHT_NAME = "finetuning_TalkSet.model"

__all__ = [
    "ASD_WEIGHT_NAME",
    "LIGHT_ASD_COMMIT",
    "LIGHT_ASD_LICENSE",
    "LIGHT_ASD_UPSTREAM",
    "S3FD_WEIGHT_NAME",
]
