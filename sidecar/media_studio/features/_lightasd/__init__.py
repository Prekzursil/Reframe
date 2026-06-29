"""Vendored LR-ASD visual active-speaker stack (S3FD detector + LR-ASD model).

PRODUCTION VENDORING (R1 Phase 2 upgrade): the active-speaker model is vendored
here from ``Junhua-Liao/LR-ASD`` (IJCV 2025; commit
``1b6dcd2d8fc2895683de6508ec6294ec47d388ca``, **MIT** — see the sibling
``LICENSE`` file, redistribution permitted), the strictly-Pareto-better
successor of Light-ASD by the same author (smaller 0.84M params; cross-domain
+5.0 Columbia / +11.2 RealVAD / +4.7 EasyCom — the in-the-wild regime this
engine runs on). It is a true drop-in: the public ``forward_*`` model API + the
112-crop / 13-cep-MFCC input contract are identical, so ``.asd`` and
``_lightasd_infer`` consume it unchanged; only the encoder/backend internals +
the ``finetuning_TalkSet.model`` weights change. The S3FD face detector is the
SAME upstream code, retained from the Light-ASD vendoring. The two model files
import torch at module top; the S3FD code keeps its ``np.int`` numpy-1 idioms
dropped (numpy-2 clean) and the weight files are resolved by PATH (constructor
argument) instead of relative to the process CWD.

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

#: Upstream source coordinates (provenance for the vendored LR-ASD model + weights).
LR_ASD_UPSTREAM = "https://github.com/Junhua-Liao/LR-ASD"
LR_ASD_COMMIT = "1b6dcd2d8fc2895683de6508ec6294ec47d388ca"
LR_ASD_LICENSE = "MIT"

#: The two weight file basenames the vendored loaders expect under the weights dir
#: (the LR-ASD active-speaker weight reuses the upstream basename).
S3FD_WEIGHT_NAME = "sfd_face.pth"
ASD_WEIGHT_NAME = "finetuning_TalkSet.model"

__all__ = [
    "ASD_WEIGHT_NAME",
    "LR_ASD_COMMIT",
    "LR_ASD_LICENSE",
    "LR_ASD_UPSTREAM",
    "S3FD_WEIGHT_NAME",
]
