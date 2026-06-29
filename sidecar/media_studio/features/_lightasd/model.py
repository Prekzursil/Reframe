"""Vendored LR-ASD audio-visual active-speaker model architecture.

Faithful port of ``Junhua-Liao/LR-ASD`` ``model/Encoder.py`` +
``model/Classifier.py`` + ``model/Model.py`` (commit
``1b6dcd2d8fc2895683de6508ec6294ec47d388ca``, **MIT**). LR-ASD (IJCV 2025) is the
successor of Light-ASD by the same author: a smaller (0.84M params / 0.51 GFLOPs
vs 1.0M / 0.6) yet strictly Pareto-better detector — notably +5.0 Columbia /
+11.2 RealVAD / +4.7 EasyCom cross-domain (the in-the-wild regime this engine
runs on) — and a true drop-in: the public ``forward_audio_frontend`` /
``forward_visual_frontend`` / ``forward_audio_visual_backend`` /
``forward_visual_backend`` API + the 112-crop visual / 13-cep MFCC audio input
contract are identical to Light-ASD, so :mod:`._lightasd_infer` and
:mod:`.asd` consume it unchanged. The internal encoder/backend blocks differ
(sequential m_1/m_2/t_1/t_2 conv chains + a Fusion/Detector backend in place of
the old parallel 3/5-kernel blocks + BGRU), so the layer shapes match the LR-ASD
``finetuning_TalkSet.model`` weights (which REPLACE the Light-ASD weights).

HEAVY MODULE — torch is imported at module top (an ``nn.Module`` subclass needs
``torch.nn`` at class-definition time), so this module is imported LAZILY only
from ``_lightasd_infer.analyze_visual`` and NEVER during the test suite. Every
executable statement carries ``# pragma: no cover``; being never imported under
the coverage run it contributes zero measurable statements and never affects the
100% gate.
"""

import torch  # pragma: no cover - heavy torch model defs
import torch.nn as nn  # pragma: no cover - heavy torch model defs


class Audio_Block(nn.Module):  # pragma: no cover - heavy torch model defs
    def __init__(self, in_channels, out_channels, kernel_1, kernel_2):
        super().__init__()
        self.relu = nn.ReLU()
        self.padding_1 = int((kernel_1 - 1) / 2)
        self.padding_2 = int((kernel_2 - 1) / 2)
        self.m_1 = nn.Conv2d(in_channels, out_channels // 2, kernel_size=(kernel_1, 1), padding=(self.padding_1, 0), bias=False)
        self.m_norm_1 = nn.BatchNorm2d(out_channels // 2, momentum=0.01, eps=0.001)
        self.m_2 = nn.Conv2d(out_channels // 2, out_channels, kernel_size=(kernel_2, 1), padding=(self.padding_2, 0), bias=False)
        self.m_norm_2 = nn.BatchNorm2d(out_channels, momentum=0.01, eps=0.001)
        self.t_1 = nn.Conv2d(out_channels, out_channels, kernel_size=(1, kernel_1), padding=(0, self.padding_1), bias=False)
        self.t_norm_1 = nn.BatchNorm2d(out_channels, momentum=0.01, eps=0.001)
        self.t_2 = nn.Conv2d(out_channels, out_channels, kernel_size=(1, kernel_2), padding=(0, self.padding_2), bias=False)
        self.t_norm_2 = nn.BatchNorm2d(out_channels, momentum=0.01, eps=0.001)

    def forward(self, x):
        x = self.relu(self.m_norm_1(self.m_1(x)))
        x = self.relu(self.m_norm_2(self.m_2(x)))
        x = self.relu(self.t_norm_1(self.t_1(x)))
        x = self.relu(self.t_norm_2(self.t_2(x)))
        return x


class Visual_Block(nn.Module):  # pragma: no cover - heavy torch model defs
    def __init__(self, in_channels, out_channels, kernel_1, kernel_2, is_down=False):
        super().__init__()
        self.relu = nn.ReLU()
        self.padding_1 = int((kernel_1 - 1) / 2)
        self.padding_2 = int((kernel_2 - 1) / 2)
        if is_down:
            self.s_1 = nn.Conv3d(in_channels, out_channels // 2, kernel_size=(1, kernel_1, kernel_1), stride=(1, 2, 2), padding=(0, self.padding_1, self.padding_1), bias=False)
        else:
            self.s_1 = nn.Conv3d(in_channels, out_channels // 2, kernel_size=(1, kernel_1, kernel_1), padding=(0, self.padding_1, self.padding_1), bias=False)
        self.s_norm_1 = nn.BatchNorm3d(out_channels // 2, momentum=0.01, eps=0.001)
        self.s_2 = nn.Conv3d(out_channels // 2, out_channels, kernel_size=(1, kernel_2, kernel_2), padding=(0, self.padding_2, self.padding_2), bias=False)
        self.s_norm_2 = nn.BatchNorm3d(out_channels, momentum=0.01, eps=0.001)
        self.t_1 = nn.Conv3d(out_channels, out_channels, kernel_size=(kernel_1, 1, 1), padding=(self.padding_1, 0, 0), bias=False)
        self.t_norm_1 = nn.BatchNorm3d(out_channels, momentum=0.01, eps=0.001)
        self.t_2 = nn.Conv3d(out_channels, out_channels, kernel_size=(kernel_2, 1, 1), padding=(self.padding_2, 0, 0), bias=False)
        self.t_norm_2 = nn.BatchNorm3d(out_channels, momentum=0.01, eps=0.001)

    def forward(self, x):
        x = self.relu(self.s_norm_1(self.s_1(x)))
        x = self.relu(self.s_norm_2(self.s_2(x)))
        x = self.relu(self.t_norm_1(self.t_1(x)))
        x = self.relu(self.t_norm_2(self.t_2(x)))
        return x


class visual_encoder(nn.Module):  # pragma: no cover - heavy torch model defs
    def __init__(self):
        super().__init__()
        self.block1 = Visual_Block(1, 32, 5, 3, is_down=True)
        self.pool1 = nn.MaxPool3d(kernel_size=(1, 3, 3), stride=(1, 2, 2), padding=(0, 1, 1))
        self.block2 = Visual_Block(32, 64, 5, 3)
        self.pool2 = nn.MaxPool3d(kernel_size=(1, 3, 3), stride=(1, 2, 2), padding=(0, 1, 1))
        self.block3 = Visual_Block(64, 128, 5, 3)
        self.maxpool = nn.AdaptiveMaxPool2d((1, 1))
        self.__init_weight()

    def forward(self, x):
        x = self.block1(x)
        x = self.pool1(x)
        x = self.block2(x)
        x = self.pool2(x)
        x = self.block3(x)
        x = x.transpose(1, 2)
        B, T, C, W, H = x.shape
        x = x.reshape(B * T, C, W, H)
        x = self.maxpool(x)
        x = x.view(B, T, C)
        return x

    def __init_weight(self):
        for m in self.modules():
            if isinstance(m, nn.Conv3d):
                torch.nn.init.kaiming_normal_(m.weight)
            elif isinstance(m, nn.BatchNorm3d):
                m.weight.data.fill_(1)
                m.bias.data.zero_()


class audio_encoder(nn.Module):  # pragma: no cover - heavy torch model defs
    def __init__(self):
        super().__init__()
        self.block1 = Audio_Block(1, 32, 5, 3)
        self.pool1 = nn.MaxPool3d(kernel_size=(1, 1, 3), stride=(1, 1, 2), padding=(0, 0, 1))
        self.block2 = Audio_Block(32, 64, 5, 3)
        self.pool2 = nn.MaxPool3d(kernel_size=(1, 1, 3), stride=(1, 1, 2), padding=(0, 0, 1))
        self.block3 = Audio_Block(64, 128, 5, 3)
        self.__init_weight()

    def forward(self, x):
        x = self.block1(x)
        x = self.pool1(x)
        x = self.block2(x)
        x = self.pool2(x)
        x = self.block3(x)
        x = torch.mean(x, dim=2, keepdim=True)
        x = x.squeeze(2).transpose(1, 2)
        return x

    def __init_weight(self):
        for m in self.modules():
            if isinstance(m, nn.Conv2d):
                torch.nn.init.kaiming_normal_(m.weight)
            elif isinstance(m, nn.BatchNorm2d):
                m.weight.data.fill_(1)
                m.bias.data.zero_()


class Fusion(nn.Module):  # pragma: no cover - heavy torch model defs
    def __init__(self, channel):
        super().__init__()
        self.sigmoid = nn.Sigmoid()
        self.attention = nn.Conv1d(channel, channel, kernel_size=1, padding=0, bias=False)
        self.bn = nn.BatchNorm1d(channel, momentum=0.01, eps=0.001)

    def forward(self, x1, x2):
        x = torch.cat((x1, x2), 2)
        identity = x.transpose(1, 2)
        w = self.sigmoid(self.bn(self.attention(identity)))
        x = (identity * w).transpose(1, 2)
        return x


class Detector(nn.Module):  # pragma: no cover - heavy torch model defs
    def __init__(self, channel):
        super().__init__()
        self.gru_forward = nn.GRU(input_size=channel, hidden_size=channel // 4, num_layers=1, bidirectional=False, bias=True, batch_first=True)
        self.gru_backward = nn.GRU(input_size=channel, hidden_size=channel // 4, num_layers=1, bidirectional=False, bias=True, batch_first=True)
        self.drop = nn.Dropout(0.5)
        self.attention = Fusion(channel // 2)
        self.__init_weight()

    def forward(self, x):
        x1, _ = self.gru_forward(self.drop(x))
        x = torch.flip(x, dims=[1])
        x2, _ = self.gru_backward(self.drop(x))
        x2 = torch.flip(x2, dims=[1])
        x = self.attention(x1, x2)
        return x

    def __init_weight(self):
        for m in self.modules():
            if isinstance(m, nn.GRU):
                torch.nn.init.kaiming_normal_(m.weight_ih_l0)
                torch.nn.init.kaiming_normal_(m.weight_hh_l0)
                m.bias_ih_l0.data.zero_()
                m.bias_hh_l0.data.zero_()


class ASD_Model(nn.Module):  # pragma: no cover - heavy torch model defs
    def __init__(self):
        super().__init__()
        self.visualEncoder = visual_encoder()
        self.audioEncoder = audio_encoder()
        self.fusion = Fusion(256)
        self.detector = Detector(256)

    def forward_visual_frontend(self, x):
        B, T, W, H = x.shape
        x = x.view(B, 1, T, W, H)
        x = (x / 255 - 0.4161) / 0.1688
        x = self.visualEncoder(x)
        return x

    def forward_audio_frontend(self, x):
        x = x.unsqueeze(1).transpose(2, 3)
        x = self.audioEncoder(x)
        return x

    def forward_audio_visual_backend(self, x1, x2):
        x = self.fusion(x1, x2)
        x = self.detector(x)
        x = torch.reshape(x, (-1, 128))
        return x

    def forward_visual_backend(self, x):
        x = torch.reshape(x, (-1, 128))
        return x

    def forward(self, audioFeature, visualFeature):
        audioEmbed = self.forward_audio_frontend(audioFeature)
        visualEmbed = self.forward_visual_frontend(visualFeature)
        outsAV = self.forward_audio_visual_backend(audioEmbed, visualEmbed)
        outsV = self.forward_visual_backend(visualEmbed)
        return outsAV, outsV
