"""Vendored LR-ASD inference wrapper + AV loss heads.

Faithful port of ``Junhua-Liao/LR-ASD`` ``loss.py`` (the ``lossAV`` / ``lossV``
classification heads) + the inference-relevant slice of ``ASD.py`` (commit
``1b6dcd2d8fc2895683de6508ec6294ec47d388ca``, MIT). The heads are byte-identical
to the Light-ASD predecessor (FC(128, 2) over the backend embedding), so this
wrapper is unchanged by the LR-ASD model upgrade. The training-only methods
(``train_network`` / ``evaluate_network`` / ``saveParameters``) are dropped; the
hardcoded ``.cuda()`` is replaced by an explicit ``device`` argument and
``loadParameters`` takes the weight PATH + a ``map_location`` so the model loads
on CPU or GPU without a CWD-relative weight lookup.

HEAVY MODULE — torch at module top; imported LAZILY only from
``_lightasd_infer.analyze_visual`` and NEVER during the test suite. Every
executable statement carries ``# pragma: no cover``; never imported under
coverage, it contributes zero measurable statements (100% gate untouched).
"""

import sys  # pragma: no cover - heavy torch inference wrapper

import torch  # pragma: no cover - heavy torch inference wrapper
import torch.nn as nn  # pragma: no cover - heavy torch inference wrapper
import torch.nn.functional as F  # pragma: no cover - heavy torch inference wrapper

from .model import ASD_Model  # pragma: no cover - heavy torch inference wrapper


class lossAV(nn.Module):  # pragma: no cover - heavy torch inference wrapper
    def __init__(self):
        super().__init__()
        self.criterion = nn.BCELoss()
        self.FC = nn.Linear(128, 2)

    def forward(self, x, labels=None, r=1):
        x = x.squeeze(1)
        x = self.FC(x)
        if labels is None:
            predScore = x[:, 1]
            predScore = predScore.t()
            predScore = predScore.view(-1).detach().cpu().numpy()
            return predScore
        x1 = x / r
        x1 = F.softmax(x1, dim=-1)[:, 1]
        nloss = self.criterion(x1, labels.float())
        predScore = F.softmax(x, dim=-1)
        predLabel = torch.round(F.softmax(x, dim=-1))[:, 1]
        correctNum = (predLabel == labels).sum().float()
        return nloss, predScore, predLabel, correctNum


class lossV(nn.Module):  # pragma: no cover - heavy torch inference wrapper
    def __init__(self):
        super().__init__()
        self.criterion = nn.BCELoss()
        self.FC = nn.Linear(128, 2)

    def forward(self, x, labels, r=1):
        x = x.squeeze(1)
        x = self.FC(x)
        x = x / r
        x = F.softmax(x, dim=-1)
        nloss = self.criterion(x[:, 1], labels.float())
        return nloss


class ASD(nn.Module):  # pragma: no cover - heavy torch inference wrapper
    """Inference-only Light-ASD wrapper (model + AV/V loss heads).

    ``device`` selects where the model + heads live ("cuda"/"cpu"). The state-dict
    layout (``model.*`` / ``lossAV.*`` / ``lossV.*``) matches the released
    ``finetuning_TalkSet.model`` so :meth:`loadParameters` restores it verbatim.
    """

    def __init__(self, device="cuda"):
        super().__init__()
        self.device = device
        self.model = ASD_Model().to(device)
        self.lossAV = lossAV().to(device)
        self.lossV = lossV().to(device)

    def loadParameters(self, path):
        selfState = self.state_dict()
        loadedState = torch.load(path, map_location=self.device, weights_only=True)
        for name, param in loadedState.items():
            origName = name
            if name not in selfState:
                name = name.replace("module.", "")
                if name not in selfState:
                    sys.stderr.write("%s is not in the model.\n" % origName)
                    continue
            if selfState[name].size() != loadedState[origName].size():
                sys.stderr.write(
                    "Wrong parameter length: %s, model: %s, loaded: %s\n"
                    % (origName, selfState[name].size(), loadedState[origName].size())
                )
                continue
            selfState[name].copy_(param)
