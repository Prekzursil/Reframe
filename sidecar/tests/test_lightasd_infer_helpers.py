"""Unit tests for the PURE helpers of ``_lightasd_infer`` (real, no torch).

The torch/cv2/ffmpeg seam of ``_lightasd_infer`` is ``# pragma: no cover`` (it
needs the heavy native stack + real weights), but the small PURE helpers it
relies on — IoU, the 25-fps grid mapping, and the numpy RMS VAD — are exercised
here for real (numpy is available in the CI gate env). These cover every line +
branch of the un-pragma'd helpers so the 100% gate holds without the heavy stack.
"""

from __future__ import annotations

import numpy as np
import pytest
from media_studio.features import _lightasd_infer as li


class TestBbIou:
    def test_identical_boxes_iou_is_one(self) -> None:
        assert li._bb_iou((0, 0, 10, 10), (0, 0, 10, 10)) == pytest.approx(1.0)

    def test_partial_overlap(self) -> None:
        # Two 10x10 boxes overlapping in a 5x5 corner -> inter 25, union 175.
        assert li._bb_iou((0, 0, 10, 10), (5, 5, 15, 15)) == pytest.approx(25.0 / 175.0)

    def test_disjoint_boxes_iou_is_zero(self) -> None:
        # Edge-touching / fully separate -> inter <= 0 -> the early-return branch.
        assert li._bb_iou((0, 0, 10, 10), (10, 10, 20, 20)) == 0.0
        assert li._bb_iou((0, 0, 10, 10), (100, 100, 110, 110)) == 0.0


class TestSourceFrameIndex:
    def test_maps_proportionally_to_25fps(self) -> None:
        # 30 fps source, frame 30 (=1.0 s) -> 25-fps grid index 25.
        assert li._source_frame_index(30, 30.0, 100) == 25

    def test_clamps_to_last_grid_frame(self) -> None:
        # A source frame that maps past the extracted grid is clamped to n25-1.
        assert li._source_frame_index(1000, 30.0, 10) == 9

    def test_zero_frame_is_zero(self) -> None:
        assert li._source_frame_index(0, 25.0, 50) == 0


class TestVadPerFrame:
    def test_mono_rms_normalised_and_clamped(self) -> None:
        wav = np.array([0.0, 0.0, 100.0, 100.0], dtype=np.float32)
        out = li._vad_per_frame(wav, sr=4, total_frames=4, fps=4.0)
        assert len(out) == 4
        assert all(0.0 <= v <= 1.0 for v in out)
        # Silent leading frames score lower than the loud trailing frames.
        assert out[0] < out[2]

    def test_frames_past_audio_end_are_silent(self) -> None:
        # total_frames extends past the audio -> the empty-segment branch -> 0.0.
        wav = np.array([10.0, 10.0, 10.0, 10.0], dtype=np.float32)
        out = li._vad_per_frame(wav, sr=4, total_frames=6, fps=4.0)
        assert len(out) == 6
        assert out[4] == 0.0
        assert out[5] == 0.0

    def test_multichannel_is_averaged(self) -> None:
        # 2-D (stereo) input -> the wav.ndim > 1 mean-down branch.
        stereo = np.array([[1.0, 3.0], [2.0, 4.0]], dtype=np.float32)
        out = li._vad_per_frame(stereo, sr=2, total_frames=2, fps=2.0)
        assert len(out) == 2
        assert all(0.0 <= v <= 1.0 for v in out)
