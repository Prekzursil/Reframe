"""Tests for the multi-lane VIDEO timeline (features/video_tracks.py).

The headline contract under test is TIMING, not "a function was called":

* every edit op preserves ``timelineEnd - timelineStart == srcOut - srcIn``
  EXACTLY, in whole frames at the project's fps (no drift, no silent rounding);
* every boundary an op produces lands on an integral frame index at that fps;
* the render argv carries those frame indices through the SHIPPED frame-accurate
  engine (``fillers.build_segment_cut_argv``) without changing them;
* anything the model cannot express FAILS CLOSED (raises) instead of silently
  dropping an edit.
"""

from __future__ import annotations

import re
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st
from media_studio import ffmpeg
from media_studio.features import fillers as _fillers
from media_studio.features import video_tracks as vt
from media_studio.features.nle_export import FPS_CHOICES, seconds_to_frames
from media_studio.protocol import RpcContext

SETTINGS = {"ffmpegPath": "C:/tools/ffmpeg/ffmpeg.exe"}

TRIM_RE = re.compile(r"\[0:v\]trim=start=([0-9.]+):end=([0-9.]+)")
ANY_TRIM_RE = re.compile(r"\[(\d+):v\]trim=start=([0-9.]+):end=([0-9.]+)")


@pytest.fixture(autouse=True)
def fake_ffmpeg(monkeypatch):
    """Pin binary resolution so tests never depend on a real ffmpeg install."""
    monkeypatch.setattr(ffmpeg, "ffmpeg_path", lambda settings=None: "/bin/ffmpeg")
    monkeypatch.setattr(ffmpeg, "ffprobe_path", lambda settings=None: "/bin/ffprobe")


def ctx() -> RpcContext:
    return RpcContext(emit_notification=lambda obj: None, jobs=None)


def clip(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "c1",
        "path": "C:/vids/a.mp4",
        "srcIn": 1.0,
        "srcOut": 3.0,
        "timelineStart": 0.0,
    }
    base.update(over)
    return base


# --------------------------------------------------------------------------- #
# THE TIMING CONTRACT (the hard requirement)
# --------------------------------------------------------------------------- #
class TestTimingContract:
    def test_duration_is_source_derived_not_stored(self):
        c = vt.normalize_video_clip(clip(srcIn=1.0, srcOut=3.0, timelineStart=5.0), fps=30)
        assert vt.clip_duration(c) == pytest.approx(2.0)
        assert vt.clip_timeline_end(c) == pytest.approx(7.0)

    @pytest.mark.parametrize("fps", FPS_CHOICES)
    def test_normalize_snaps_every_boundary_to_a_whole_frame(self, fps: int):
        # A deliberately off-grid input: 0.777s is not a frame boundary at any fps.
        c = vt.normalize_video_clip(
            clip(srcIn=0.777, srcOut=1.777, timelineStart=2.777),
            fps=fps,
        )
        for key in ("srcIn", "srcOut", "timelineStart"):
            frames = c[key] * fps
            assert frames == pytest.approx(round(frames)), f"{key} off the frame grid at {fps}fps"

    @pytest.mark.parametrize("fps", FPS_CHOICES)
    def test_trim_head_preserves_the_invariant_and_the_tail(self, fps: int):
        c = vt.normalize_video_clip(clip(srcIn=1.0, srcOut=3.0, timelineStart=4.0), fps=fps)
        end_before = vt.clip_timeline_end(c)
        moved = vt.trim_clip_edge(c, "start", 4.5, fps=fps)
        # the tail is PINNED (a head trim never moves the clip's out point)
        assert vt.clip_timeline_end(moved) == pytest.approx(end_before)
        # ... and the duration invariant holds exactly, in whole frames
        assert vt.frame_span(moved, fps) == vt.frame_source_span(moved, fps)

    @pytest.mark.parametrize("fps", FPS_CHOICES)
    def test_trim_tail_preserves_the_invariant_and_the_head(self, fps: int):
        c = vt.normalize_video_clip(clip(srcIn=1.0, srcOut=3.0, timelineStart=4.0), fps=fps)
        moved = vt.trim_clip_edge(c, "end", 5.5, fps=fps)
        assert moved["timelineStart"] == pytest.approx(4.0)
        assert vt.frame_span(moved, fps) == vt.frame_source_span(moved, fps)

    @pytest.mark.parametrize("fps", FPS_CHOICES)
    def test_split_is_lossless_the_halves_tile_the_original(self, fps: int):
        c = vt.normalize_video_clip(clip(srcIn=1.0, srcOut=3.0, timelineStart=4.0), fps=fps)
        left, right = vt.split_clip(c, 5.0, fps=fps)
        # no frame invented, no frame lost
        assert vt.frame_span(left, fps) + vt.frame_span(right, fps) == vt.frame_span(c, fps)
        # the cut point is shared exactly (no gap, no overlap)
        assert vt.clip_timeline_end(left) == pytest.approx(right["timelineStart"])
        assert left["srcOut"] == pytest.approx(right["srcIn"])
        # both halves still satisfy the duration invariant
        for half in (left, right):
            assert vt.frame_span(half, fps) == vt.frame_source_span(half, fps)

    @pytest.mark.parametrize("fps", FPS_CHOICES)
    def test_move_translates_without_changing_a_single_frame(self, fps: int):
        c = vt.normalize_video_clip(clip(srcIn=1.0, srcOut=3.0, timelineStart=4.0), fps=fps)
        moved = vt.move_clip(c, 9.0, fps=fps)
        assert moved["srcIn"] == c["srcIn"]
        assert moved["srcOut"] == c["srcOut"]
        assert vt.frame_span(moved, fps) == vt.frame_span(c, fps)

    @given(
        start_f=st.integers(min_value=0, max_value=200_000),
        span_f=st.integers(min_value=1, max_value=20_000),
        fps=st.sampled_from(FPS_CHOICES),
    )
    def test_render_argv_round_trips_the_exact_frame_index(self, start_f: int, span_f: int, fps: int):
        """The engine's 3-decimal argv MUST recover the same frame index.

        This is the falsifiable half of "frame-accurate": the model's frame index
        goes into the argv and the SAME index comes back out. Half a frame at the
        fastest supported rate (60fps) is 8.33 ms; the engine formats to 1 ms, so
        the recovered index is exact — asserted here rather than assumed.
        """
        src_in = start_f / fps
        src_out = (start_f + span_f) / fps
        c = vt.normalize_video_clip(clip(srcIn=src_in, srcOut=src_out, timelineStart=0.0), fps=fps)
        argv = vt.build_timeline_render_argv(
            vt.flatten_timeline([vt.normalize_video_track({"id": "v1", "clips": [c]}, fps=fps)], fps=fps),
            "out.mp4",
            settings=SETTINGS,
        )
        graph = argv[argv.index("-filter_complex") + 1]
        m = TRIM_RE.search(graph)
        assert m is not None, graph
        assert seconds_to_frames(float(m.group(1)), fps) == start_f
        assert seconds_to_frames(float(m.group(2)), fps) == start_f + span_f


# --------------------------------------------------------------------------- #
# WIRE THE SHIPPED ENGINE — do not rewrite it
# --------------------------------------------------------------------------- #
class TestEngineReuse:
    def test_single_source_argv_is_byte_identical_to_the_shipped_cutter(self):
        track = vt.normalize_video_track(
            {
                "id": "v1",
                "clips": [
                    clip(id="c1", srcIn=1.0, srcOut=3.0, timelineStart=0.0),
                    clip(id="c2", srcIn=10.0, srcOut=12.0, timelineStart=2.0),
                ],
            },
            fps=30,
        )
        segments = vt.flatten_timeline([track], fps=30)
        mine = vt.build_timeline_render_argv(segments, "out.mp4", settings=SETTINGS)
        theirs = _fillers.build_segment_cut_argv("C:/vids/a.mp4", "out.mp4", [(1.0, 3.0), (10.0, 12.0)], SETTINGS)
        assert mine == theirs

    def test_timeline_order_not_source_order_drives_the_concat(self):
        """LIST ORDER, no sort (fillers.py:361-391) — the timeline decides."""
        track = vt.normalize_video_track(
            {
                "id": "v1",
                "clips": [
                    # authored out of order; timelineStart is what orders them
                    clip(id="c2", srcIn=10.0, srcOut=12.0, timelineStart=2.0),
                    clip(id="c1", srcIn=1.0, srcOut=3.0, timelineStart=0.0),
                ],
            },
            fps=30,
        )
        segments = vt.flatten_timeline([track], fps=30)
        assert [s["srcIn"] for s in segments] == [1.0, 10.0]

    def test_multi_source_argv_keeps_one_input_per_distinct_path(self):
        tracks = [
            vt.normalize_video_track(
                {
                    "id": "v1",
                    "clips": [
                        clip(id="c1", path="C:/vids/a.mp4", srcIn=1.0, srcOut=2.0, timelineStart=0.0),
                        clip(id="c2", path="C:/vids/b with space.mp4", srcIn=5.0, srcOut=6.0, timelineStart=1.0),
                        clip(id="c3", path="C:/vids/a.mp4", srcIn=8.0, srcOut=9.0, timelineStart=2.0),
                    ],
                },
                fps=30,
            )
        ]
        argv = vt.build_timeline_render_argv(vt.flatten_timeline(tracks, fps=30), "out.mp4", settings=SETTINGS)
        inputs = [argv[i + 1] for i, a in enumerate(argv) if a == "-i"]
        assert inputs == ["C:/vids/a.mp4", "C:/vids/b with space.mp4"]  # deduped, order of first use
        graph = argv[argv.index("-filter_complex") + 1]
        # three segments, mapped onto inputs 0,1,0 in TIMELINE order
        assert [int(m.group(1)) for m in ANY_TRIM_RE.finditer(graph)] == [0, 1, 0]
        assert "concat=n=3:v=1:a=1" in graph
        assert isinstance(argv, list) and all(isinstance(a, str) for a in argv)


# --------------------------------------------------------------------------- #
# FAIL CLOSED — a dropped edit is the worst outcome
# --------------------------------------------------------------------------- #
class TestFailsClosed:
    def test_zero_length_trim_is_refused_not_clamped_to_nothing(self):
        c = vt.normalize_video_clip(clip(srcIn=1.0, srcOut=3.0, timelineStart=4.0), fps=30)
        with pytest.raises(vt.VideoTrackError, match="at least"):
            vt.trim_clip_edge(c, "end", 4.0, fps=30)

    def test_split_outside_the_clip_is_refused(self):
        c = vt.normalize_video_clip(clip(srcIn=1.0, srcOut=3.0, timelineStart=4.0), fps=30)
        with pytest.raises(vt.VideoTrackError, match="inside"):
            vt.split_clip(c, 99.0, fps=30)

    def test_overlapping_clips_on_one_lane_are_refused(self):
        track = vt.normalize_video_track(
            {
                "id": "v1",
                "clips": [
                    clip(id="c1", srcIn=0.0, srcOut=5.0, timelineStart=0.0),
                    clip(id="c2", srcIn=0.0, srcOut=5.0, timelineStart=1.0),
                ],
            },
            fps=30,
        )
        with pytest.raises(vt.VideoTrackError, match="overlap"):
            vt.flatten_timeline([track], fps=30)

    def test_cross_lane_overlap_is_refused_because_no_compositor_exists(self):
        a = vt.normalize_video_track({"id": "v1", "index": 0, "clips": [clip(id="c1", timelineStart=0.0)]}, fps=30)
        b = vt.normalize_video_track({"id": "v2", "index": 1, "clips": [clip(id="c2", timelineStart=1.0)]}, fps=30)
        with pytest.raises(vt.VideoTrackError, match="overlap"):
            vt.flatten_timeline([a, b], fps=30)

    def test_empty_timeline_render_is_refused(self):
        with pytest.raises(vt.VideoTrackError, match="at least one"):
            vt.build_timeline_render_argv([], "out.mp4", settings=SETTINGS)
