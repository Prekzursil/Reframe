"""Vendored S3FD face detector (PATH-resolved weights, no CWD/gdown seam).

Faithful port of ``Junhua-Liao/Light-ASD``
``model/faceDetector/s3fd/__init__.py`` (commit
``ed38c232de5efe0261dbd68627c0ade7cdfe14eb``, MIT) with two production changes:

* the weight file is loaded from an EXPLICIT ``weights_path`` argument instead of
  ``os.path.join(os.getcwd(), 'model/faceDetector/s3fd/sfd_face.pth')`` — so the
  caller no longer has to ``chdir`` into a ``$HOME`` checkout (the seam dropped in
  R1 Phase 3); and
* the gdown auto-download fallback is removed — the weight is an on-demand,
  sha256-pinned asset (see ``media_studio.assets.manifest``), never a runtime
  Google-Drive fetch.

HEAVY MODULE — torch/cv2 at module top; imported LAZILY only from
``_lightasd_infer.analyze_visual`` and NEVER during the test suite. Every
executable statement carries ``# pragma: no cover`` (zero measurable statements
under coverage; 100% gate untouched).
"""

import numpy as np  # pragma: no cover - heavy s3fd detector
import cv2  # pragma: no cover - heavy s3fd detector
import torch  # pragma: no cover - heavy s3fd detector

from .nets import S3FDNet  # pragma: no cover - heavy s3fd detector
from .box_utils import nms_  # pragma: no cover - heavy s3fd detector

img_mean = np.array([104.0, 117.0, 123.0])[:, np.newaxis, np.newaxis].astype("float32")  # pragma: no cover - heavy s3fd detector


class S3FD:  # pragma: no cover - heavy s3fd detector
    """S3FD face detector. ``weights_path`` points at the pinned ``sfd_face.pth``."""

    def __init__(self, weights_path, device="cuda"):
        self.device = device
        self.net = S3FDNet(device=self.device).to(self.device)
        state_dict = torch.load(weights_path, map_location=self.device, weights_only=True)
        self.net.load_state_dict(state_dict)
        self.net.eval()

    def detect_faces(self, image, conf_th=0.8, scales=[1]):
        w, h = image.shape[1], image.shape[0]
        bboxes = np.empty(shape=(0, 5))
        with torch.no_grad():
            for s in scales:
                scaled_img = cv2.resize(image, dsize=(0, 0), fx=s, fy=s, interpolation=cv2.INTER_LINEAR)
                scaled_img = np.swapaxes(scaled_img, 1, 2)
                scaled_img = np.swapaxes(scaled_img, 1, 0)
                scaled_img = scaled_img[[2, 1, 0], :, :]
                scaled_img = scaled_img.astype("float32")
                scaled_img -= img_mean
                scaled_img = scaled_img[[2, 1, 0], :, :]
                x = torch.from_numpy(scaled_img).unsqueeze(0).to(self.device)
                y = self.net(x)
                detections = y.data
                scale = torch.Tensor([w, h, w, h])
                for i in range(detections.size(1)):
                    j = 0
                    while detections[0, i, j, 0] > conf_th:
                        score = detections[0, i, j, 0]
                        pt = (detections[0, i, j, 1:] * scale).cpu().numpy()
                        bbox = (pt[0], pt[1], pt[2], pt[3], score)
                        bboxes = np.vstack((bboxes, bbox))
                        j += 1
            keep = nms_(bboxes, 0.1)
            bboxes = bboxes[keep]
        return bboxes
