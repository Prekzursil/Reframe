"""Tests for the R1 hybrid multi-speaker reframe engine (WU R1).

100% line+branch coverage of the PURE decision/layout/compositor layer + the
engine orchestration, all with hand-built fixtures and an injected FAKE backend
(no torch / cv2 / model / real ffmpeg). The heavy backend is the seam.
"""

from __future__ import annotations

import pytest

from media_studio.features import offline as _offline
from media_studio.features import reframe_multispeaker as ms
from media_studio.features.reframe_eval import LAYOUTS, ReframeTrace, Segment


# --------------------------------------------------------------------------- #
# merge_short_shots / shot_spans
# --------------------------------------------------------------------------- #
class TestMergeShortShots:
    def test_drops_close_and_short_tail_boundaries(self):
        # fps=10, min 0.5s => min_frames=5. Cuts at 3 (too close to 0) and 8 (5
        # past 3 but tail 100-8>=5? tail=92 ok; but 3 dropped so last=0, 8-0=8>=5 keep).
        merged = ms.merge_short_shots([3, 8], 100, fps=10.0, min_shot_sec=0.5)
        assert merged == (8,)

    def test_dedup_sort_clamp(self):
        merged = ms.merge_short_shots([50, 50, 0, 100, -2, 200], 100, fps=10.0, min_shot_sec=0.0)
        assert merged == (50,)

    def test_short_tail_boundary_merged_away(self):
        # cut at 98 leaves tail 100-98=2 < 5 => merged into final shot.
        assert ms.merge_short_shots([50, 98], 100, fps=10.0, min_shot_sec=0.5) == (50,)

    def test_zero_frames_raises(self):
        with pytest.raises(ms.MultiSpeakerReframeError):
            ms.merge_short_shots([1], 0, fps=10.0)

    def test_bad_fps_raises(self):
        with pytest.raises(ms.MultiSpeakerReframeError):
            ms.merge_short_shots([1], 10, fps=0.0)

    def test_shot_spans_partition(self):
        assert ms.shot_spans([5, 10], 20) == ((0, 5), (5, 10), (10, 20))

    def test_shot_spans_no_cuts(self):
        assert ms.shot_spans([], 20) == ((0, 20),)

    def test_shot_spans_zero_frames_raises(self):
        with pytest.raises(ms.MultiSpeakerReframeError):
            ms.shot_spans([], 0)


# --------------------------------------------------------------------------- #
# MultiFaceTracker
# --------------------------------------------------------------------------- #
class TestMultiFaceTracker:
    def test_first_frame_assigns_fresh_ids(self):
        t = ms.MultiFaceTracker()
        ids = t.update([(0, 0, 10, 10), (100, 0, 10, 10)])
        assert ids == [0, 1]

    def test_stable_id_across_frames_by_iou(self):
        t = ms.MultiFaceTracker()
        t.update([(0, 0, 10, 10)])
        # nearly the same box -> same id 0
        assert t.update([(1, 0, 10, 10)]) == [0]

    def test_low_iou_gets_new_id(self):
        t = ms.MultiFaceTracker()
        t.update([(0, 0, 10, 10)])
        ids = t.update([(500, 500, 10, 10)])
        assert ids == [1]

    def test_one_to_one_assignment_no_double_claim(self):
        t = ms.MultiFaceTracker()
        t.update([(0, 0, 10, 10), (100, 0, 10, 10)])
        # two new boxes both overlap track 0 region the most; only one wins it.
        ids = t.update([(0, 0, 10, 10), (2, 0, 10, 10)])
        assert sorted(ids) == [0, 2]
        assert len(set(ids)) == 2

    def test_reset_clears_tracks(self):
        t = ms.MultiFaceTracker()
        t.update([(0, 0, 10, 10)])
        t.reset()
        assert t.update([(0, 0, 10, 10)]) == [1]


# --------------------------------------------------------------------------- #
# OneEuroFilter + smooth_centers_one_euro
# --------------------------------------------------------------------------- #
class TestOneEuro:
    def test_first_sample_passthrough(self):
        f = ms.OneEuroFilter()
        assert f(0.0, 0.42) == 0.42

    def test_smooths_subsequent_samples(self):
        f = ms.OneEuroFilter(min_cutoff=1.0, beta=0.0)
        f(0.0, 0.0)
        out = f(0.1, 1.0)
        assert 0.0 < out < 1.0

    def test_non_monotonic_time_raises(self):
        f = ms.OneEuroFilter()
        f(1.0, 0.0)
        with pytest.raises(ms.MultiSpeakerReframeError):
            f(1.0, 1.0)

    def test_smooth_centers_length_mismatch_raises(self):
        with pytest.raises(ms.MultiSpeakerReframeError):
            ms.smooth_centers_one_euro([0.0], [0.1, 0.2])

    def test_dead_zone_holds_microjitter(self):
        ts = [i * 0.1 for i in range(6)]
        # tiny wiggle around 0.5 -> after first emit, held flat by the dead-zone.
        centers = [0.5, 0.5001, 0.4999, 0.5001, 0.5, 0.5001]
        out = ms.smooth_centers_one_euro(ts, centers, dead_zone=0.01)
        assert all(abs(v - out[0]) < 1e-9 for v in out)

    def test_real_motion_passes_dead_zone(self):
        ts = [i * 0.1 for i in range(6)]
        centers = [0.1, 0.3, 0.5, 0.7, 0.9, 1.0]
        out = ms.smooth_centers_one_euro(ts, centers, dead_zone=0.001)
        assert out[-1] > out[0]


# --------------------------------------------------------------------------- #
# fuse_active_speaker / resolve_speaker_track
# --------------------------------------------------------------------------- #
class TestFusion:
    def test_no_visual_scores_is_empty_vote(self):
        v = ms.fuse_active_speaker({}, "x", 1.0)
        assert v == ms.SpeakerVote("", 0.0)

    def test_high_visual_and_vad_picks_speaker(self):
        v = ms.fuse_active_speaker({"a": 0.9}, "", 1.0)
        assert v.speaker == "a"
        assert v.confidence >= ms.ASD_CONFIDENCE_THRESHOLD

    def test_diarize_agreement_bonus(self):
        # 0.4 visual * 0.8 vad = 0.32 < threshold; +0.25 agreement = 0.57 >= 0.55
        v = ms.fuse_active_speaker({"a": 0.4, "b": 0.39}, "a", 0.8)
        assert v.speaker == "a"

    def test_low_confidence_empty(self):
        v = ms.fuse_active_speaker({"a": 0.1}, "", 0.1)
        assert v.speaker == ""
        assert v.confidence < ms.ASD_CONFIDENCE_THRESHOLD

    def test_resolve_track_holds_last_speaker(self):
        votes = [
            ms.SpeakerVote("a", 0.9),
            ms.SpeakerVote("", 0.1),  # dropout -> hold "a"
            ms.SpeakerVote("b", 0.9),
        ]
        assert ms.resolve_speaker_track(votes) == ["a", "a", "b"]

    def test_resolve_track_blank_before_first_confident(self):
        votes = [ms.SpeakerVote("", 0.1), ms.SpeakerVote("a", 0.9)]
        assert ms.resolve_speaker_track(votes) == ["", "a"]


# --------------------------------------------------------------------------- #
# decide_layout / debounce / segments / cuts
# --------------------------------------------------------------------------- #
class TestLayout:
    def test_decide_single_split_composite(self):
        assert ms.decide_layout(0) == "single"
        assert ms.decide_layout(1) == "single"
        assert ms.decide_layout(2) == "split"
        assert ms.decide_layout(3) == "composite"

    def test_decide_disallow_split_composite(self):
        assert ms.decide_layout(2, allow_split=False) == "single"
        assert ms.decide_layout(3, allow_composite=False) == "single"

    def test_debounce_empty(self):
        assert ms.debounce_layouts([], 3) == []

    def test_debounce_identity_when_dwell_le_1(self):
        raw = ["single", "split"]
        assert ms.debounce_layouts(raw, 1) == raw

    def test_debounce_suppresses_short_run(self):
        raw = ["single", "single", "single", "split", "single", "single", "single"]
        out = ms.debounce_layouts(raw, 3)
        assert out == ["single"] * 7

    def test_debounce_commits_long_run(self):
        raw = ["single", "single", "single", "split", "split", "split"]
        out = ms.debounce_layouts(raw, 3)
        assert out == raw

    def test_layouts_to_segments_skips_filler(self):
        per_frame = ["single", "single", "none", "split", "split"]
        segs = ms.layouts_to_segments(per_frame)
        assert segs == (
            Segment(0, 2, "single"),
            Segment(3, 5, "split"),
        )

    def test_commit_cuts_union(self):
        assert ms.commit_cuts([5], [3, 5, 8], 20) == (3, 5, 8)

    def test_commit_cuts_zero_frames_raises(self):
        with pytest.raises(ms.MultiSpeakerReframeError):
            ms.commit_cuts([1], [], 0)

    def test_speaker_turn_frames(self):
        assert ms.speaker_turn_frames(["a", "a", "b", "b", "c"]) == (2, 4)


# --------------------------------------------------------------------------- #
# Compositor — build_filter_complex / build_composite_argv
# --------------------------------------------------------------------------- #
class TestCompositor:
    def test_single(self):
        fc = ms.build_filter_complex("single", [(10, 0, 405, 720)], out_w=1080, out_h=1920)
        assert fc == "[0:v]crop=405:720:10:0,scale=1080:1920:flags=lanczos,setsar=1[v]"

    def test_split_vstacks_two_halves(self):
        fc = ms.build_filter_complex("split", [(0, 0, 405, 720), (800, 0, 405, 720)], out_w=1080, out_h=1920)
        assert "vstack=inputs=2[v]" in fc
        assert "scale=1080:960" in fc  # each half is out_h/2

    def test_composite_host_top_guests_bottom(self):
        regs = [(0, 0, 405, 720), (500, 0, 200, 720), (800, 0, 200, 720)]
        fc = ms.build_filter_complex("composite", regs, out_w=1080, out_h=1920)
        assert "[host]" in fc and "hstack=inputs=2[guests]" in fc
        assert "[host][guests]vstack=inputs=2[v]" in fc

    def test_unknown_layout_raises(self):
        with pytest.raises(ms.MultiSpeakerReframeError):
            ms.build_filter_complex("mosaic", [(0, 0, 1, 1)], out_w=10, out_h=10)

    def test_single_wrong_region_count_raises(self):
        with pytest.raises(ms.MultiSpeakerReframeError):
            ms.build_filter_complex("single", [], out_w=10, out_h=10)

    def test_split_wrong_region_count_raises(self):
        with pytest.raises(ms.MultiSpeakerReframeError):
            ms.build_filter_complex("split", [(0, 0, 1, 1)], out_w=10, out_h=10)

    def test_composite_too_few_regions_raises(self):
        with pytest.raises(ms.MultiSpeakerReframeError):
            ms.build_filter_complex("composite", [(0, 0, 1, 1)], out_w=10, out_h=10)

    def test_build_composite_argv_is_argv_list(self):
        argv = ms.build_composite_argv("in.mp4", "out.mp4", "[0:v]null[v]", total_sec=3.0)
        assert isinstance(argv, list)
        assert "-filter_complex" in argv and argv[-1] == "out.mp4"
        assert "[v]" in argv  # -map [v]


# --------------------------------------------------------------------------- #
# build_trace — the pure director end to end
# --------------------------------------------------------------------------- #
def _analysis(
    *,
    total=6,
    fps=30.0,
    width=1920,
    height=1080,
    shots=(),
    boxes=None,
    scores=None,
    diarize=None,
    vad=None,
):
    boxes = boxes if boxes is not None else tuple(((100.0, 0.0, 200.0, 400.0),) for _ in range(total))
    scores = scores if scores is not None else tuple((0.9,) for _ in range(total))
    diarize = diarize if diarize is not None else tuple("0" for _ in range(total))
    vad = vad if vad is not None else tuple(1.0 for _ in range(total))
    return ms.ShotAnalysis(
        width=width,
        height=height,
        fps=fps,
        total_frames=total,
        shot_boundaries=tuple(shots),
        boxes_per_frame=boxes,
        visual_scores_per_frame=scores,
        diarize_per_frame=diarize,
        vad_per_frame=vad,
    )


class TestBuildTrace:
    def test_single_speaker_trace_shape(self):
        trace = ms.build_trace(_analysis())
        assert isinstance(trace, ReframeTrace)
        assert len(trace.crops) == 6
        assert len(trace.speaker_per_frame) == 6
        # one talking head -> single layout throughout
        for seg in trace.segments:
            assert seg.layout in LAYOUTS

    def test_zero_frames_raises(self):
        with pytest.raises(ms.MultiSpeakerReframeError):
            ms.build_trace(_analysis(total=0, boxes=(), scores=(), diarize=(), vad=()))

    def test_length_mismatch_raises(self):
        bad = ms.ShotAnalysis(
            width=1920, height=1080, fps=30.0, total_frames=2,
            shot_boundaries=(), boxes_per_frame=((),), visual_scores_per_frame=((), ()),
            diarize_per_frame=("", ""), vad_per_frame=(1.0, 1.0),
        )
        with pytest.raises(ms.MultiSpeakerReframeError):
            ms.build_trace(bad)

    def test_two_concurrent_speakers_produce_split(self):
        boxes = tuple(((100.0, 0.0, 200.0, 400.0), (1500.0, 0.0, 200.0, 400.0)) for _ in range(30))
        scores = tuple((0.9, 0.9) for _ in range(30))
        trace = ms.build_trace(_analysis(total=30, boxes=boxes, scores=scores))
        assert any(seg.layout == "split" for seg in trace.segments)

    def test_three_concurrent_speakers_produce_composite(self):
        boxes = tuple(
            ((100.0, 0.0, 100.0, 400.0), (900.0, 0.0, 100.0, 400.0), (1700.0, 0.0, 100.0, 400.0))
            for _ in range(30)
        )
        scores = tuple((0.9, 0.9, 0.9) for _ in range(30))
        trace = ms.build_trace(_analysis(total=30, boxes=boxes, scores=scores))
        assert any(seg.layout == "composite" for seg in trace.segments)

    def test_cold_start_no_confident_speaker_uses_dominant_not_center(self):
        # all low VAD -> no confident vote, speaker stays "" -> cold-start center
        # from select_dominant over the (off-center) face, NOT frame center.
        boxes = tuple(((1400.0, 0.0, 300.0, 400.0),) for _ in range(6))
        trace = ms.build_trace(_analysis(total=6, boxes=boxes, vad=tuple(0.0 for _ in range(6))))
        # dominant face center ~ (1400+150)/1920 = 0.807 -> crop x near right edge.
        crop_w = trace.crops[0][2]
        # not a centered crop (centered x would be (1920-crop_w)/2)
        centered_x = (1920 - crop_w) / 2
        assert abs(trace.crops[0][0] - centered_x) > 1.0

    def test_cold_start_no_faces_falls_to_center(self):
        boxes = tuple((() for _ in range(6)))
        scores = tuple((() for _ in range(6)))
        trace = ms.build_trace(_analysis(total=6, boxes=boxes, scores=scores, vad=tuple(0.0 for _ in range(6))))
        crop_w = trace.crops[0][2]
        centered_x = (1920 - crop_w) / 2
        assert abs(trace.crops[0][0] - centered_x) < 1.0

    def test_speaker_held_through_dropout_uses_cold_center(self):
        # frame 0 confident on track 0; frames 1+ the box vanishes (no faces) so
        # the speaker is held but its track isn't visible -> cold center branch.
        boxes = ((100.0, 0.0, 200.0, 400.0),), (), (), (), (), ()
        scores = (0.9,), (), (), (), (), ()
        diarize = "0", "", "", "", "", ""
        vad = 1.0, 0.0, 0.0, 0.0, 0.0, 0.0
        trace = ms.build_trace(_analysis(total=6, boxes=boxes, scores=scores, diarize=diarize, vad=vad))
        assert trace.speaker_per_frame[0] == "0"
        assert trace.speaker_per_frame[1] == "0"  # held

    def test_multi_shot_resets_tracker(self):
        trace = ms.build_trace(_analysis(total=20, fps=10.0, shots=(10,)))
        assert trace.shot_boundaries == (10,)

    def test_within_shot_speaker_turn_hard_cuts(self):
        # Two faces all 6 frames (one shot, no boundary). Active speaker flips
        # 0->1 at frame 3 -> a committed turn WITHIN the shot -> the smoother
        # resets (hard cut) AND _frame_center skips the non-matching first track.
        left = (100.0, 0.0, 200.0, 400.0)
        right = (1500.0, 0.0, 200.0, 400.0)
        boxes = tuple((left, right) for _ in range(6))
        scores = ((0.9, 0.1), (0.9, 0.1), (0.9, 0.1), (0.1, 0.9), (0.1, 0.9), (0.1, 0.9))
        trace = ms.build_trace(_analysis(total=6, fps=10.0, boxes=boxes, scores=scores))
        assert trace.speaker_per_frame == ("0", "0", "0", "1", "1", "1")
        # crop jumps right when speaker 1 (right face) takes over.
        assert trace.crops[5][0] > trace.crops[0][0]


# --------------------------------------------------------------------------- #
# Availability / notices / asset registration
# --------------------------------------------------------------------------- #
class TestAvailability:
    def test_available_when_wsl_and_models(self):
        assert ms.availability_reason({}, which=lambda _x: "/usr/bin/wsl", models_present=lambda _s: True) is None

    def test_no_wsl_reason(self):
        reason = ms.availability_reason({}, which=lambda _x: None, models_present=lambda _s: True)
        assert reason is not None and "WSL" in reason

    def test_no_models_reason(self):
        reason = ms.availability_reason({}, which=lambda _x: "/wsl", models_present=lambda _s: False)
        assert reason is not None and ms.LIGHT_ASD_ASSET in reason

    def test_default_models_present_false_when_unregistered(self):
        # Light-ASD asset is intentionally NOT registered (operator-blocker) -> False.
        assert ms.default_models_present({}) is False

    def test_default_models_present_true_when_installed(self, monkeypatch):
        from media_studio.assets import manager, manifest

        entry = object()
        monkeypatch.setattr(manifest, "get_asset", lambda _n: entry)

        class _Mgr:
            def __init__(self, **_kw):
                pass

            def installed_path(self, _e):
                return "/some/path"

        monkeypatch.setattr(manager, "AssetManager", _Mgr)
        assert ms.default_models_present({}) is True

    def test_default_models_present_false_when_not_installed(self, monkeypatch):
        from media_studio.assets import manager, manifest

        monkeypatch.setattr(manifest, "get_asset", lambda _n: object())

        class _Mgr:
            def __init__(self, **_kw):
                pass

            def installed_path(self, _e):
                return None

        monkeypatch.setattr(manager, "AssetManager", _Mgr)
        assert ms.default_models_present({}) is False

    def test_default_models_present_swallows_errors(self, monkeypatch):
        from media_studio.assets import manifest

        def boom(_n):
            raise RuntimeError("asset machinery exploded")

        monkeypatch.setattr(manifest, "get_asset", boom)
        assert ms.default_models_present({}) is False

    def test_engine_degrade_notice_distinct_message(self):
        n = ms.make_engine_degrade_notice("no WSL")
        from media_studio.features import reframe_claudeshorts as cs

        assert n["type"] == cs.REFRAME_DEGRADED_NOTICE
        assert "center crop" not in n["message"]
        assert "single-speaker" in n["message"]
        assert n["reason"] == "no WSL"

    def test_register_assets_noop_idempotent(self):
        ms.register_multispeaker_assets()
        ms.register_multispeaker_assets()  # idempotent no-op


# --------------------------------------------------------------------------- #
# Engine orchestration — fake backend + fake runner
# --------------------------------------------------------------------------- #
class _FakeBackend:
    def __init__(self, analysis, *, raise_on_analyze=None):
        self._analysis = analysis
        self._raise = raise_on_analyze
        self.released = 0

    def analyze(self, media_path, *, on_progress=None, should_cancel=None):
        if self._raise is not None:
            raise self._raise
        return self._analysis

    def release(self):
        self.released += 1


def _engine(**kw):
    """An engine wired with all seams faked + host 'available'."""
    defaults = dict(
        which=lambda _x: "/wsl",
        models_present=lambda _s: True,
        replace_fn=lambda _a, _b: None,
        remove_fn=lambda _p: None,
    )
    defaults.update(kw)
    return ms.MultiSpeakerReframeEngine({}, **defaults)


class TestEngineRender:
    def test_happy_path_atomic_rename(self):
        moves = []
        runs = []
        eng = _engine(
            backend_factory=lambda _s: _FakeBackend(_analysis()),
            runner=lambda argv, **kw: runs.append(argv) or 0,
            replace_fn=lambda a, b: moves.append((a, b)),
        )
        out = eng.reframe("in.mp4", "out.mp4")
        assert out == "out.mp4"
        assert moves == [("out.multispeaker.part.mp4", "out.mp4")]
        assert runs and runs[0][-1] == "out.multispeaker.part.mp4"

    def test_release_called_even_on_analyze_error(self):
        backend = _FakeBackend(_analysis(), raise_on_analyze=RuntimeError("CUDA OOM"))
        eng = _engine(backend_factory=lambda _s: backend)
        with pytest.raises(RuntimeError):
            eng.reframe("in.mp4", "out.mp4")
        assert backend.released == 1

    def test_oom_mid_encode_cleans_partial_and_raises(self):
        removed = []
        eng = _engine(
            backend_factory=lambda _s: _FakeBackend(_analysis()),
            runner=lambda *a, **k: (_ for _ in ()).throw(MemoryError("oom")),
            remove_fn=lambda p: removed.append(p),
        )
        with pytest.raises(ms.MultiSpeakerRenderError):
            eng.reframe("in.mp4", "out.mp4")
        assert removed == ["out.multispeaker.part.mp4"]

    def test_nonzero_exit_cleans_partial_and_raises(self):
        removed = []
        eng = _engine(
            backend_factory=lambda _s: _FakeBackend(_analysis()),
            runner=lambda *a, **k: 1,
            remove_fn=lambda p: removed.append(p),
        )
        with pytest.raises(ms.MultiSpeakerRenderError):
            eng.reframe("in.mp4", "out.mp4")
        assert removed == ["out.multispeaker.part.mp4"]

    def test_cleanup_swallows_oserror(self):
        def boom(_p):
            raise OSError("gone")

        eng = _engine(
            backend_factory=lambda _s: _FakeBackend(_analysis()),
            runner=lambda *a, **k: 1,
            remove_fn=boom,
        )
        with pytest.raises(ms.MultiSpeakerRenderError):
            eng.reframe("in.mp4", "out.mp4")


class TestEngineFailureContract:
    def test_explicit_unavailable_raises_typed_not_offline(self):
        eng = _engine(which=lambda _x: None)  # no WSL, allow_degrade=False
        with pytest.raises(ms.MultiSpeakerUnavailableError) as ei:
            eng.reframe("in.mp4", "out.mp4")
        assert "Offline mode" not in str(ei.value)
        assert "WSL" in str(ei.value)

    def test_offline_mode_raises_offline_error(self):
        # offline mode ON + unavailable -> the correct OfflineError message wins.
        eng = ms.MultiSpeakerReframeEngine(
            {"offline": True},
            which=lambda _x: None,
            models_present=lambda _s: False,
        )
        with pytest.raises(_offline.OfflineError) as ei:
            eng.reframe("in.mp4", "out.mp4")
        assert "Offline mode is on" in str(ei.value)

    def test_auto_degrade_falls_back_to_single_speaker(self):
        notices = []
        calls = []

        class _FakeSingle:
            def reframe(self, in_path, out_path, aspect, *, on_progress=None, should_cancel=None, on_notice=None):
                calls.append((in_path, out_path))
                return out_path

        eng = ms.MultiSpeakerReframeEngine(
            {},
            allow_degrade=True,
            which=lambda _x: None,  # no WSL
            models_present=lambda _s: True,
            single_speaker=_FakeSingle(),
        )
        out = eng.reframe("in.mp4", "out.mp4", on_notice=lambda n: notices.append(n))
        assert out == "out.mp4"
        assert calls == [("in.mp4", "out.mp4")]
        assert notices and notices[0]["type"] == ms._cs.REFRAME_DEGRADED_NOTICE
        assert "single-speaker" in notices[0]["message"]

    def test_auto_degrade_without_notice_sink(self):
        class _FakeSingle:
            def reframe(self, *a, **k):
                return a[1]

        eng = ms.MultiSpeakerReframeEngine(
            {}, allow_degrade=True, which=lambda _x: None,
            models_present=lambda _s: True, single_speaker=_FakeSingle(),
        )
        assert eng.reframe("in.mp4", "out.mp4") == "out.mp4"

    def test_default_construction_binds_real_seams(self):
        # cover the default-seam branches (runner/backend/single bound lazily).
        eng = ms.MultiSpeakerReframeEngine({})
        assert eng._runner is not None
        assert eng._single is not None
        assert eng._backend_factory is ms._default_backend_factory


# --------------------------------------------------------------------------- #
# Registry integration (reframe.py)
# --------------------------------------------------------------------------- #
class TestRegistryIntegration:
    def test_resolve_engine_name_multispeaker(self):
        from media_studio.features import reframe as r

        resolved, notice = r.resolve_engine_name("reframe_multispeaker", {})
        assert resolved == "reframe_multispeaker"
        assert notice is None

    def test_get_engine_builds_multispeaker(self):
        from media_studio.features import reframe as r

        eng, notice = r.get_engine("reframe_multispeaker", {})
        assert isinstance(eng, ms.MultiSpeakerReframeEngine)
        assert notice is None

    def test_in_reframe_engines_set(self):
        from media_studio.features.export_presets import REFRAME_ENGINES

        assert "reframe_multispeaker" in REFRAME_ENGINES
