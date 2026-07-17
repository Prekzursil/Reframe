"""Vendored LR-ASD visual active-speaker model.

PRODUCTION VENDORING (R1 Phase 2 upgrade): the active-speaker model is vendored
here from ``Junhua-Liao/LR-ASD`` (IJCV 2025; commit
``1b6dcd2d8fc2895683de6508ec6294ec47d388ca``, **MIT** — see the sibling
``LICENSE`` file, redistribution permitted), the strictly-Pareto-better
successor of Light-ASD by the same author (smaller 0.84M params; cross-domain
+5.0 Columbia / +11.2 RealVAD / +4.7 EasyCom — the in-the-wild regime this
engine runs on). It is a true drop-in: the public ``forward_*`` model API + the
112-crop / 13-cep-MFCC input contract are identical, so ``.asd`` and
``_lightasd_infer`` consume it unchanged; only the encoder/backend internals +
the ``finetuning_TalkSet.model`` weights change. The model files import torch at
module top; the ASD weight is resolved by PATH (constructor argument) instead of
relative to the process CWD.

WU-L1 (commercialization IP fix): the S3FD face detector that used to sit
alongside this model was REMOVED — its ``sfd_face.pth`` weight shipped under NO
license (an all-rights-reserved commercial blocker). Face detection is now MIT
**YuNet** (``cv2.FaceDetectorYN``), resolved via
``reframe_claudeshorts.resolve_yunet_model_path`` in ``_lightasd_infer``.

This package ``__init__`` is intentionally **light** — it imports NOTHING heavy
(no torch / cv2). The model modules (:mod:`.model`, :mod:`.asd`) each import
torch at module top (an ``nn.Module`` subclass needs ``torch.nn`` at
class-definition time), so they are imported LAZILY only from inside
``_lightasd_infer.analyze_visual`` (a ``# pragma: no cover`` GPU-runtime seam) and
NEVER at package import or during the test suite. Every executable statement in
those modules carries ``# pragma: no cover``; since they are never imported under
the coverage run they report zero measurable statements and never perturb the
100% line+branch gate (mirrors the ``Real*Backend`` heavy-seam convention, but
adapted for torch model definitions that cannot be made import-light).

The LR-ASD weight (``finetuning_TalkSet.model``) is registered as an on-demand,
sha256-pinned asset in :mod:`media_studio.assets.manifest`; its on-disk location
is resolved by ``_lightasd_infer`` (a ``settings['lightAsdWeightsDir']`` override,
else the asset-manager install path).
"""

from __future__ import annotations

#: Upstream source coordinates (provenance for the vendored LR-ASD model + weights).
LR_ASD_UPSTREAM = "https://github.com/Junhua-Liao/LR-ASD"
LR_ASD_COMMIT = "1b6dcd2d8fc2895683de6508ec6294ec47d388ca"
LR_ASD_LICENSE = "MIT"

#: The LR-ASD active-speaker weight basename the vendored loader expects under the
#: weights dir (reuses the upstream basename).
ASD_WEIGHT_NAME = "finetuning_TalkSet.model"

__all__ = [
    "ASD_WEIGHT_NAME",
    "LR_ASD_COMMIT",
    "LR_ASD_LICENSE",
    "LR_ASD_UPSTREAM",
]
