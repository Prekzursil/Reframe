"""Tests for WU-E1/E2/E3 — the reframe trace PRODUCER, its cache, and the
edited-plan re-render (``reframe.analyze`` / ``reframe.render``).

Everything here runs against a synthetic :class:`~media_studio.features.reframe_multispeaker.ShotAnalysis`
injected through the ``backend_factory`` seam and a fake ``runner`` — no torch, no
cv2, no weights, no real video, no real ffmpeg. That is REQUIRED for the 100%
branch gate but it is NOT evidence the pipeline works on real media: every
assertion below is about the decision/orchestration layer, never about pixels.
"""

from __future__ import annotations

import contextlib
import json
import logging
from collections.abc import Iterator
from typing import Any

import pytest
from media_studio.features import offline as _offline
from media_studio.features import reframe_analyze as ra
from media_studio.features import reframe_multispeaker as ms
from media_studio.features import reframe_override as ro
from media_studio.features.reframe_eval import ReframeTrace, Segment
from media_studio.jobs import JobRegistry
from media_studio.protocol import RpcContext, RpcError

ASPECT = "9:16"


@contextlib.contextmanager
def _captured_warnings() -> Iterator[list[str]]:
    """Collect WARNING records from the engine's module logger.

    ``util.get_logger`` sets ``propagate=False``, so pytest's ``caplog`` never sees
    these records; attaching a handler to the module logger is the sibling suite's
    established idiom.
    """
    seen: list[str] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            seen.append(record.getMessage())

    handler = _Capture(level=logging.WARNING)
    ms._log.addHandler(handler)
    try:
        yield seen
    finally:
        ms._log.removeHandler(handler)


# --------------------------------------------------------------------------- #
# Synthetic fixtures (hand-built; the spec's prescribed testing approach)
# --------------------------------------------------------------------------- #
def _analysis(*, total: int = 6, fps: float = 30.0, width: int = 1920, height: int = 1080, **kw: Any):
    """A synthetic ShotAnalysis: one confidently-talking face, no cuts."""
    boxes = kw.pop("boxes", None) or tuple(((100.0, 0.0, 200.0, 400.0),) for _ in range(total))
    scores = kw.pop("scores", None) or tuple((0.9,) for _ in range(total))
    diarize = kw.pop("diarize", None) or tuple("0" for _ in range(total))
    vad = kw.pop("vad", None) or tuple(1.0 for _ in range(total))
    return ms.ShotAnalysis(
        width=width,
        height=height,
        fps=fps,
        total_frames=total,
        shot_boundaries=tuple(kw.pop("shots", ())),
        boxes_per_frame=boxes,
        visual_scores_per_frame=scores,
        diarize_per_frame=diarize,
        vad_per_frame=vad,
    )


def _two_talker_analysis(*, total: int = 6, concurrent: int = 2):
    """An analysis where ``concurrent`` faces clear the ASD gate every frame.

    2 concurrent talkers -> ``split``; 3+ -> ``composite`` (``_concurrent_active``).
    """
    boxes = tuple(tuple((200.0 * i, 0.0, 180.0, 360.0) for i in range(concurrent)) for _ in range(total))
    scores = tuple(tuple(0.95 for _ in range(concurrent)) for _ in range(total))
    return _analysis(total=total, boxes=boxes, scores=scores)


def _trace(*, total: int = 6, layout: str = "single", speakers: tuple[str, ...] | None = None) -> ReframeTrace:
    speaker_per_frame = speakers if speakers is not None else tuple("0" for _ in range(total))
    return ReframeTrace(
        shot_boundaries=(),
        speaker_per_frame=speaker_per_frame,
        segments=(Segment(start_frame=0, end_frame=total, layout=layout),),
        crops=tuple((float(100 * (i % 2)), 0.0, 608.0, 1080.0) for i in range(total)),
    )


def _shot(index: int = 0, *, start: int = 0, end: int = 6, layout: str = "single", speaker: str = "0", crop=None):
    return ro.ShotDecision(
        index=index,
        start_frame=start,
        end_frame=end,
        speaker=speaker,
        layout=layout,
        crop=crop if crop is not None else (0.0, 0.0, 608.0, 1080.0),
        speakers=("0", "1"),
    )


def _plan(*shots: ro.ShotDecision, width: int = 1920, height: int = 1080, fps: float = 30.0) -> ro.ShotPlan:
    return ro.ShotPlan(
        source_width=width,
        source_height=height,
        fps=fps,
        shots=shots or (_shot(),),
    )


def _trace_two(second_x: float, *, total: int = 6, layout: str = "split") -> ReframeTrace:
    """A two-speaker trace where the NON-primary speaker sits at ``second_x``.

    Speaker ``"0"`` owns frame 0, ``"1"`` owns the rest, so
    :func:`~media_studio.features.reframe_multispeaker.other_speaker_centers` for a
    shot whose speaker is ``"0"`` resolves to ``"1"``'s crop centre — the ONLY thing
    that moves between two traces here.
    """
    return ReframeTrace(
        shot_boundaries=(),
        speaker_per_frame=tuple("0" if i == 0 else "1" for i in range(total)),
        segments=(Segment(start_frame=0, end_frame=total, layout=layout),),
        crops=tuple((0.0 if i == 0 else second_x, 0.0, 608.0, 1080.0) for i in range(total)),
    )


def _segments_for(plan: ro.ShotPlan, trace: ReframeTrace, aspect: str = ASPECT) -> tuple[ms.ShotSegment, ...]:
    """The segments a first (cache-less) render of ``plan`` would produce."""
    return ms.plan_shot_segments(
        plan,
        trace,
        aspect=aspect,
        root="out",
        ext=".mp4",
        affected_only=False,
        manifest=None,
        exists=lambda _p: False,
    )


def _manifest(plan: ro.ShotPlan, aspect: str = ASPECT, trace: ReframeTrace | None = None) -> dict[str, Any]:
    """The on-disk shot manifest a previous successful render would have left.

    Built through the PRODUCTION payload builder over the PRODUCTION segment
    planner, so a test manifest can never drift from what a real render writes.
    """
    return ms.shot_manifest_payload(plan, _segments_for(plan, trace or _trace(), aspect), aspect=aspect)


def _bare_manifest(**over: Any) -> dict[str, Any]:
    """A hand-built manifest whose top-level identity MATCHES ``_plan()`` at ASPECT.

    Needed so a test that probes the ``shots``-array branches cannot be silently
    short-circuited by the identity guard (aspect / fps / source dimensions) and
    pass for the wrong reason.
    """
    base = {
        "version": ms.SHOT_MANIFEST_VERSION,
        "aspect": ASPECT,
        "fps": 30.0,
        "sourceWidth": 1920,
        "sourceHeight": 1080,
        "shots": [],
    }
    return {**base, **over}


# --------------------------------------------------------------------------- #
# WU-E2 — the size-bounded, injectable analysis cache
# --------------------------------------------------------------------------- #
def _key(video_id="v", aspect=ASPECT, allow_split=True, allow_composite=True, diarize_backend=None) -> ra.AnalysisKey:
    return ra.AnalysisKey(
        video_id=video_id,
        aspect=aspect,
        allow_split=allow_split,
        allow_composite=allow_composite,
        diarize_backend=diarize_backend,
    )


def _bundle(analysis=None) -> ra.AnalysisBundle:
    return ra.build_bundle(
        analysis if analysis is not None else _analysis(), aspect=ASPECT, allow_split=True, allow_composite=True
    )


class TestLruAnalysisCache:
    def test_rejects_a_non_positive_bound(self):
        with pytest.raises(ValueError, match="max_entries"):
            ra.LruAnalysisCache(max_entries=0)

    def test_accepts_a_bound_of_one(self):
        assert len(ra.LruAnalysisCache(max_entries=1)) == 0

    def test_get_miss_is_none(self):
        assert ra.LruAnalysisCache().get(_key()) is None

    def test_put_then_get_round_trips(self):
        cache = ra.LruAnalysisCache()
        bundle = _bundle()
        cache.put(_key(), bundle)
        assert cache.get(_key()) is bundle
        assert len(cache) == 1

    def test_putting_the_same_key_twice_replaces_it(self):
        cache = ra.LruAnalysisCache()
        first, second = _bundle(), _bundle()
        cache.put(_key(), first)
        cache.put(_key(), second)
        assert len(cache) == 1
        assert cache.get(_key()) is second

    def test_evicts_the_least_recently_used_entry(self):
        cache = ra.LruAnalysisCache(max_entries=2)
        cache.put(_key(video_id="a"), _bundle())
        cache.put(_key(video_id="b"), _bundle())
        cache.put(_key(video_id="c"), _bundle())
        assert len(cache) == 2
        assert cache.get(_key(video_id="a")) is None  # evicted
        assert cache.get(_key(video_id="c")) is not None

    def test_a_get_refreshes_recency(self):
        cache = ra.LruAnalysisCache(max_entries=2)
        cache.put(_key(video_id="a"), _bundle())
        cache.put(_key(video_id="b"), _bundle())
        cache.get(_key(video_id="a"))  # 'a' is now the most recent -> 'b' evicts
        cache.put(_key(video_id="c"), _bundle())
        assert cache.get(_key(video_id="b")) is None
        assert cache.get(_key(video_id="a")) is not None

    def test_the_layout_flags_are_part_of_the_key(self):
        cache = ra.LruAnalysisCache()
        cache.put(_key(allow_split=True), _bundle())
        assert cache.get(_key(allow_split=False)) is None

    def test_the_diarize_backend_is_part_of_the_key(self):
        # REFUTED-OBJECTION FIX: diarizeBackend selects WHICH diarizer runs, so it
        # changes the ShotAnalysis and therefore the whole bundle. Keying without it
        # served backend A's plan to every later request for backend B.
        cache = ra.LruAnalysisCache()
        cache.put(_key(diarize_backend="alpha"), _bundle())
        assert cache.get(_key(diarize_backend="beta")) is None
        assert cache.get(_key(diarize_backend=None)) is None
        assert cache.get(_key(diarize_backend="alpha")) is not None

    def test_find_returns_the_most_recent_match_for_video_and_aspect(self):
        cache = ra.LruAnalysisCache()
        older, newer = _bundle(), _bundle()
        cache.put(_key(allow_split=True), older)
        cache.put(_key(allow_split=False), newer)
        assert cache.find("v", ASPECT) is newer

    def test_find_ignores_another_video(self):
        cache = ra.LruAnalysisCache()
        cache.put(_key(video_id="other"), _bundle())
        assert cache.find("v", ASPECT) is None

    def test_find_ignores_another_aspect(self):
        cache = ra.LruAnalysisCache()
        cache.put(_key(aspect="1:1"), _bundle())
        assert cache.find("v", ASPECT) is None

    def test_find_on_an_empty_cache_is_none(self):
        assert ra.LruAnalysisCache().find("v", ASPECT) is None


class TestBuildBundle:
    def test_produces_a_trace_and_a_matching_editable_plan(self):
        bundle = ra.build_bundle(_analysis(), aspect=ASPECT, allow_split=True, allow_composite=True)
        assert isinstance(bundle.trace, ReframeTrace)
        assert isinstance(bundle.plan, ro.ShotPlan)
        assert bundle.plan.source_width == 1920
        assert bundle.plan.source_height == 1080
        assert bundle.plan.fps == 30.0
        assert len(bundle.plan.shots) == 1  # no cuts -> one shot

    def test_allow_split_false_collapses_a_two_talker_shot_to_single(self):
        analysis = _two_talker_analysis()
        split = ra.build_bundle(analysis, aspect=ASPECT, allow_split=True, allow_composite=True)
        collapsed = ra.build_bundle(analysis, aspect=ASPECT, allow_split=False, allow_composite=True)
        assert {s.layout for s in split.plan.shots} == {"split"}
        assert {s.layout for s in collapsed.plan.shots} == {"single"}

    def test_allow_composite_false_collapses_a_three_talker_shot_to_single(self):
        analysis = _two_talker_analysis(concurrent=3)
        composite = ra.build_bundle(analysis, aspect=ASPECT, allow_split=True, allow_composite=True)
        collapsed = ra.build_bundle(analysis, aspect=ASPECT, allow_split=True, allow_composite=False)
        assert {s.layout for s in composite.plan.shots} == {"composite"}
        assert {s.layout for s in collapsed.plan.shots} == {"single"}


# --------------------------------------------------------------------------- #
# WU-E3 (pure half) — the shot manifest + the per-shot reuse decision
# --------------------------------------------------------------------------- #
class TestManifestShotDecisions:
    def test_no_manifest_is_empty(self):
        assert ms.manifest_shot_decisions(None, _plan(), aspect=ASPECT) == {}

    def test_a_different_aspect_is_empty(self):
        assert ms.manifest_shot_decisions(_manifest(_plan(), aspect="1:1"), _plan(), aspect=ASPECT) == {}

    @pytest.mark.parametrize(
        ("field", "value"),
        [("fps", 60.0), ("sourceWidth", 1280), ("sourceHeight", 720)],
        ids=["fps", "width", "height"],
    )
    def test_a_manifest_written_for_a_different_source_identity_is_empty(self, field, value):
        # The aspect guard's own rationale ("the geometry would be wrong") applies
        # verbatim to fps and the source dimensions: regions_for_shot is fed
        # plan.source_width/height and every segment's -ss/-t is frame/fps. Omitting
        # them let a relinked source at a new resolution republish stale segments.
        assert ms.manifest_shot_decisions(_bare_manifest(**{field: value}), _plan(), aspect=ASPECT) == {}

    def test_shots_that_are_not_a_list_are_empty(self):
        assert ms.manifest_shot_decisions(_bare_manifest(shots="nope"), _plan(), aspect=ASPECT) == {}

    def test_a_valid_manifest_is_keyed_by_shot_index(self):
        plan = _plan(_shot(0, start=0, end=3), _shot(1, start=3, end=6))
        decisions = ms.manifest_shot_decisions(_manifest(plan), plan, aspect=ASPECT)
        assert sorted(decisions) == [0, 1]
        assert decisions[1]["startFrame"] == 3
        assert decisions[1]["regions"], "a manifest entry must record the regions it rendered"

    def test_a_non_object_entry_is_skipped(self):
        assert ms.manifest_shot_decisions(_bare_manifest(shots=["nope"]), _plan(), aspect=ASPECT) == {}

    def test_an_entry_without_an_integer_index_is_skipped(self):
        assert ms.manifest_shot_decisions(_bare_manifest(shots=[{"index": "0"}]), _plan(), aspect=ASPECT) == {}


class TestPlanShotSegments:
    def _segments(self, plan, *, manifest=None, exists=False, affected_only=True, trace=None):
        return ms.plan_shot_segments(
            plan,
            trace if trace is not None else _trace(),
            aspect=ASPECT,
            root="out",
            ext=".mp4",
            affected_only=affected_only,
            manifest=manifest,
            exists=lambda _p: exists,
        )

    def test_without_a_manifest_every_shot_is_re_encoded(self):
        segments = self._segments(_plan(_shot(0, start=0, end=3), _shot(1, start=3, end=6)))
        assert [s.reuse for s in segments] == [False, False]
        assert [s.path for s in segments] == ["out.multispeaker.shot000.mp4", "out.multispeaker.shot001.mp4"]

    def test_an_unchanged_shot_with_an_existing_segment_is_reused(self):
        plan = _plan(_shot(0, start=0, end=3), _shot(1, start=3, end=6))
        segments = self._segments(plan, manifest=_manifest(plan), exists=True)
        assert [s.reuse for s in segments] == [True, True]

    def test_an_unchanged_shot_whose_segment_file_vanished_is_re_encoded(self):
        plan = _plan(_shot(0, start=0, end=3))
        segments = self._segments(plan, manifest=_manifest(plan), exists=False)
        assert [s.reuse for s in segments] == [False]

    def test_a_changed_shot_is_re_encoded_and_its_sibling_reused(self):
        before = _plan(_shot(0, start=0, end=3), _shot(1, start=3, end=6))
        edited = _plan(_shot(0, start=0, end=3), _shot(1, start=3, end=6, layout="split"))
        segments = self._segments(edited, manifest=_manifest(before), exists=True)
        assert [s.reuse for s in segments] == [True, False]

    def test_affected_only_false_re_encodes_everything(self):
        plan = _plan(_shot(0, start=0, end=3))
        segments = self._segments(plan, manifest=_manifest(plan), exists=True, affected_only=False)
        assert [s.reuse for s in segments] == [False]

    def test_a_single_layout_shot_has_one_region(self):
        segments = self._segments(_plan(_shot(0, layout="single")))
        assert len(segments[0].regions) == 1

    def test_a_split_layout_shot_has_two_cells(self):
        segments = self._segments(_plan(_shot(0, layout="split")))
        assert len(segments[0].regions) == 2

    def test_a_moved_other_speaker_forces_a_re_encode(self):
        # THE reuse hole. A segment's PIXELS also depend on `other_centers`, which
        # comes from the TRACE (speaker_per_frame + crops), and shot.to_dict()
        # records only index/span/speaker/layout/crop/speakers — never the other
        # speaker's rectangle. So a re-analysis that moves a NON-primary speaker
        # while leaving the majority speaker, layout and crop untouched produced a
        # byte-identical decision dict, and the stale segment was concat-copied.
        plan = _plan(_shot(0, layout="split"))
        before, after = _trace_two(0.0), _trace_two(705.0)
        stale = _manifest(plan, trace=before)
        moved = self._segments(plan, manifest=stale, exists=True, trace=after)
        assert moved[0].regions != _segments_for(plan, before)[0].regions, "the fixture must move a cell"
        assert [s.reuse for s in moved] == [False], "a moved cell must NOT be concat-copied"

    def test_an_unmoved_other_speaker_still_reuses(self):
        # Detector control for the test above: the SAME trace must still reuse, so
        # the assertion above is measuring the trace change and not a broken key.
        plan = _plan(_shot(0, layout="split"))
        trace = _trace_two(0.0)
        segments = self._segments(plan, manifest=_manifest(plan, trace=trace), exists=True, trace=trace)
        assert [s.reuse for s in segments] == [True]


# --------------------------------------------------------------------------- #
# Engine extensions — analyze() (no render) and render_shot_plan()
# --------------------------------------------------------------------------- #
class _FakeBackend:
    def __init__(self, analysis, *, raise_on_analyze: BaseException | None = None):
        self._analysis = analysis
        self._raise = raise_on_analyze
        self.released = 0
        self.progress: list[tuple[float, str]] = []
        self.calls = 0

    def analyze(self, media_path, *, on_progress=None, should_cancel=None):
        self.calls += 1
        if on_progress is not None:
            on_progress(50.0, "detecting faces")
            # A backend that reports 100% of ITS OWN work must not make the job
            # look finished — the handler clamps the analysis stage below the
            # plan stage. Over-report so a dropped clamp is observable.
            on_progress(150.0, "over-reporting on purpose")
        if should_cancel is not None:
            should_cancel()
        if self._raise is not None:
            raise self._raise
        return self._analysis

    def release(self):
        self.released += 1


def _engine(**kw):
    """An engine with every heavy/IO seam faked and the host reported available."""
    defaults: dict[str, Any] = {
        "which": lambda _x: "/wsl",
        "models_present": lambda _s: True,
        "replace_fn": lambda _a, _b: None,
        "remove_fn": lambda _p: None,
        "write_text_fn": lambda _p, _t: None,
        "write_concat_fn": lambda _lp, _sp: None,
        "exists_fn": lambda _p: False,
        "runner": lambda _argv, **_kw: 0,
    }
    defaults.update(kw)
    return ms.MultiSpeakerReframeEngine({}, **defaults)


class TestEngineAnalyze:
    def test_returns_the_backend_bundle_and_releases(self):
        backend = _FakeBackend(_analysis())
        eng = _engine(backend_factory=lambda _s: backend)
        assert eng.analyze("in.mp4") is backend._analysis
        assert backend.released == 1

    def test_releases_even_when_the_backend_raises(self):
        backend = _FakeBackend(_analysis(), raise_on_analyze=RuntimeError("CUDA OOM"))
        eng = _engine(backend_factory=lambda _s: backend)
        with pytest.raises(RuntimeError):
            eng.analyze("in.mp4")
        assert backend.released == 1

    def test_forwards_the_progress_and_cancel_seams(self):
        seen: list[tuple[float, str]] = []
        backend = _FakeBackend(_analysis())
        eng = _engine(backend_factory=lambda _s: backend)
        eng.analyze("in.mp4", on_progress=lambda p, m: seen.append((p, m)), should_cancel=lambda: False)
        # The ENGINE forwards the backend's reports verbatim; clamping to a stage
        # ceiling is the RPC handler's job, not the engine's.
        assert seen[0] == (50.0, "detecting faces")
        assert seen[-1] == (150.0, "over-reporting on purpose")


class TestRenderShotPlan:
    def test_an_empty_plan_is_loud(self):
        eng = _engine()
        with pytest.raises(ms.MultiSpeakerReframeError, match="no shots"):
            eng.render_shot_plan("in.mp4", "out.mp4", ro.ShotPlan(1920, 1080, 30.0, ()), _trace())

    def test_renders_every_shot_then_concats_and_atomically_renames(self):
        runs: list[list[str]] = []
        moves: list[tuple[str, str]] = []
        eng = _engine(
            runner=lambda argv, **_kw: runs.append(list(argv)) or 0,
            replace_fn=lambda a, b: moves.append((a, b)),
        )
        plan = _plan(_shot(0, start=0, end=3), _shot(1, start=3, end=6))
        out, reencoded = eng.render_shot_plan("in.mp4", "out.mp4", plan, _trace())
        assert out == "out.mp4"
        assert reencoded == (0, 1)
        # two per-shot encodes + one concat pass
        assert len(runs) == 3
        # Every ffmpeg target is a .part; the cache entries only ever appear as the
        # DESTINATION of an atomic rename (see the temp-path test below).
        assert runs[0][-1] == "out.multispeaker.shot000.part.mp4"
        assert runs[1][-1] == "out.multispeaker.shot001.part.mp4"
        assert runs[2][-1] == "out.multispeaker.part.mp4"
        assert moves == [
            ("out.multispeaker.shot000.part.mp4", "out.multispeaker.shot000.mp4"),
            ("out.multispeaker.shot001.part.mp4", "out.multispeaker.shot001.mp4"),
            ("out.multispeaker.part.mp4", "out.mp4"),
        ]

    def test_a_reused_shot_is_not_re_encoded(self):
        runs: list[list[str]] = []
        plan = _plan(_shot(0, start=0, end=3), _shot(1, start=3, end=6))
        eng = _engine(
            runner=lambda argv, **_kw: runs.append(list(argv)) or 0,
            read_text_fn=lambda _p: json.dumps(_manifest(plan)),
            exists_fn=lambda _p: True,
        )
        edited = _plan(_shot(0, start=0, end=3), _shot(1, start=3, end=6, layout="split"))
        _out, reencoded = eng.render_shot_plan("in.mp4", "out.mp4", edited, _trace())
        assert reencoded == (1,)
        assert len(runs) == 2  # ONE shot re-encoded + the concat
        assert runs[0][-1] == "out.multispeaker.shot001.part.mp4"

    def test_the_concat_manifest_is_removed_but_the_shot_segments_are_kept(self):
        removed: list[str] = []
        eng = _engine(remove_fn=lambda p: removed.append(p))
        eng.render_shot_plan("in.mp4", "out.mp4", _plan(_shot(0)), _trace())
        assert removed == ["out.multispeaker.concat.mp4.txt"]

    def test_a_concat_manifest_write_failure_cleans_up_and_raises(self):
        removed: list[str] = []

        def boom(_lp, _sp):
            raise OSError("read-only volume")

        eng = _engine(write_concat_fn=boom, remove_fn=lambda p: removed.append(p))
        with pytest.raises(ms.MultiSpeakerRenderError, match="concat manifest"):
            eng.render_shot_plan("in.mp4", "out.mp4", _plan(_shot(0)), _trace())
        assert "out.multispeaker.shot000.mp4" in removed

    def test_an_encode_failure_removes_only_the_freshly_written_segments(self):
        # A first-shot failure now removes ONLY this run's .part — never the cache
        # entry at shot000.mp4, which (if it exists at all) is a PREVIOUS render's
        # still-valid piece that this run has not replaced yet.
        removed: list[str] = []
        plan = _plan(_shot(0, start=0, end=3), _shot(1, start=3, end=6))
        eng = _engine(
            runner=lambda _argv, **_kw: 1,  # non-zero exit on the FIRST shot
            remove_fn=lambda p: removed.append(p),
        )
        with pytest.raises(ms.MultiSpeakerRenderError, match="exit 1"):
            eng.render_shot_plan("in.mp4", "out.mp4", plan, _trace())
        assert removed == ["out.multispeaker.shot000.part.mp4"]

    def test_an_extensionless_output_defaults_to_mp4(self):
        runs: list[list[str]] = []
        eng = _engine(runner=lambda argv, **_kw: runs.append(list(argv)) or 0)
        eng.render_shot_plan("in.mp4", "out", _plan(_shot(0)), _trace())
        assert runs[0][-1] == "out.multispeaker.shot000.part.mp4"

    def test_the_shot_manifest_is_written_after_a_successful_render(self):
        writes: list[tuple[str, str]] = []
        eng = _engine(write_text_fn=lambda p, t: writes.append((p, t)))
        plan = _plan(_shot(0))
        eng.render_shot_plan("in.mp4", "out.mp4", plan, _trace())
        assert writes[0][0] == "out.mp4.shots.json"
        payload = json.loads(writes[0][1])
        assert payload["version"] == ms.SHOT_MANIFEST_VERSION
        assert payload["aspect"] == ASPECT
        # The SOURCE IDENTITY is recorded too: fps and the source dimensions decide a
        # segment's timing and geometry exactly as much as the aspect does.
        assert (payload["fps"], payload["sourceWidth"], payload["sourceHeight"]) == (30.0, 1920, 1080)
        # And each row carries the regions it rendered, so a trace change that moves
        # a split/composite cell cannot present as an unchanged decision.
        assert payload["shots"] == [ms.shot_manifest_entry(plan.shots[0], _segments_for(plan, _trace())[0].regions)]
        assert payload["shots"][0]["regions"] == [[0.0, 0.0, 608.0, 1080.0]]

    def test_a_shot_manifest_write_failure_is_logged_not_fatal(self):
        # `util.get_logger` sets propagate=False, so caplog cannot see this record —
        # attach a handler to the module logger instead. Verified to FIRE on the
        # current implementation; it goes quiet if the except arm ever becomes a
        # silent `pass`.
        def boom(_p, _t):
            raise OSError("disk full")

        with _captured_warnings() as seen:
            out, _ = _engine(write_text_fn=boom).render_shot_plan("in.mp4", "out.mp4", _plan(_shot(0)), _trace())
        assert out == "out.mp4"
        assert any("shot manifest" in m for m in seen)

    def test_a_shot_manifest_write_failure_DROPS_the_stale_manifest(self):
        # The consequence of a failed write is NOT "re-encodes every shot" unless the
        # PREVIOUS manifest is removed: this render already overwrote the segment
        # files, so a surviving manifest describes bytes that are gone. Executed
        # repro before the fix: render(split) -> render(single, manifest write
        # fails) -> render(split) REUSED the file, delivering the single render
        # while reporting `reencoded: []`.
        removed: list[str] = []

        def boom(_p, _t):
            raise OSError("disk full")

        eng = _engine(write_text_fn=boom, remove_fn=lambda p: removed.append(p))
        eng.render_shot_plan("in.mp4", "out.mp4", _plan(_shot(0)), _trace())
        assert "out.mp4.shots.json" in removed

    def test_a_failed_stale_manifest_drop_is_also_logged(self):
        def boom_write(_p, _t):
            raise OSError("disk full")

        def boom_remove(path):
            if path.endswith(".shots.json"):
                raise OSError("read-only volume")

        with _captured_warnings() as seen:
            out, _ = _engine(write_text_fn=boom_write, remove_fn=boom_remove).render_shot_plan(
                "in.mp4", "out.mp4", _plan(_shot(0)), _trace()
            )
        assert out == "out.mp4"
        assert any("stale" in m for m in seen)

    def test_a_manifest_from_a_different_trace_does_not_license_reuse(self):
        # End-to-end through the SHIPPED render path, not just the pure planner.
        runs: list[list[str]] = []
        plan = _plan(_shot(0, layout="split"))
        eng = _engine(
            runner=lambda argv, **_kw: runs.append(list(argv)) or 0,
            read_text_fn=lambda _p: json.dumps(_manifest(plan, trace=_trace_two(0.0))),
            exists_fn=lambda _p: True,
        )
        _out, reencoded = eng.render_shot_plan("in.mp4", "out.mp4", plan, _trace_two(705.0))
        assert reencoded == (0,)
        assert len(runs) == 2, "the moved cell must be re-encoded, then concatenated"

    def test_a_manifest_from_a_different_fps_re_encodes_everything(self):
        # Executed repro: a plan carrying fps 60 / 1280x720 over a manifest written
        # at fps 30 / 1920x1080 previously reported reencoded=() and ran exactly ONE
        # ffmpeg pass (the concat), republishing the stale segment at the old
        # geometry and timing.
        runs: list[list[str]] = []
        old = _plan(_shot(0), width=1920, height=1080, fps=30.0)
        new = _plan(_shot(0), width=1280, height=720, fps=60.0)
        eng = _engine(
            runner=lambda argv, **_kw: runs.append(list(argv)) or 0,
            read_text_fn=lambda _p: json.dumps(_manifest(old)),
            exists_fn=lambda _p: True,
        )
        _out, reencoded = eng.render_shot_plan("in.mp4", "out.mp4", new, _trace())
        assert reencoded == (0,)
        assert len(runs) == 2

    def test_each_segment_is_encoded_to_a_temp_path_then_atomically_renamed(self):
        # The segment IS the cache, so encoding straight to its final path made the
        # cache entry and the in-flight write target the same file: an OOM-KILLED
        # process (no Python cleanup runs) left a truncated segment that the next
        # render's bare exists() check happily concat-copied.
        runs: list[list[str]] = []
        moves: list[tuple[str, str]] = []
        eng = _engine(
            runner=lambda argv, **_kw: runs.append(list(argv)) or 0,
            replace_fn=lambda a, b: moves.append((a, b)),
        )
        eng.render_shot_plan("in.mp4", "out.mp4", _plan(_shot(0)), _trace())
        assert runs[0][-1] == "out.multispeaker.shot000.part.mp4", "ffmpeg must write the .part, not the cache entry"
        assert moves == [
            ("out.multispeaker.shot000.part.mp4", "out.multispeaker.shot000.mp4"),
            ("out.multispeaker.part.mp4", "out.mp4"),
        ]

    def test_a_later_encode_failure_removes_this_runs_segments_and_its_part(self):
        removed: list[str] = []
        calls = {"n": 0}

        def runner(_argv, **_kw):
            calls["n"] += 1
            return 0 if calls["n"] == 1 else 1  # the SECOND shot fails

        eng = _engine(runner=runner, remove_fn=lambda p: removed.append(p))
        plan = _plan(_shot(0, start=0, end=3), _shot(1, start=3, end=6))
        with pytest.raises(ms.MultiSpeakerRenderError, match="exit 1"):
            eng.render_shot_plan("in.mp4", "out.mp4", plan, _trace())
        assert removed == ["out.multispeaker.shot000.mp4", "out.multispeaker.shot001.part.mp4"]

    def test_the_per_shot_encode_receives_the_progress_and_cancel_seams(self):
        # Both seams were passed to the CONCAT pass but nothing asserted they reach
        # the per-shot encode, so mutants that replaced either with None survived
        # the whole suite.
        seen: list[dict[str, Any]] = []
        sink: list[tuple[float, str]] = []

        def runner(_argv, **kw):
            seen.append(kw)
            return 0

        _engine(runner=runner).render_shot_plan(
            "in.mp4",
            "out.mp4",
            _plan(_shot(0)),
            _trace(),
            on_progress=lambda p, m: sink.append((p, m)),
            should_cancel=lambda: True,
        )
        assert seen[0]["should_cancel"] is not None and seen[0]["should_cancel"]() is True
        seen[0]["on_progress"](7.0, "encoding shot 0")
        assert sink == [(7.0, "encoding shot 0")]

    @pytest.mark.parametrize(
        "raw",
        ["{not json", json.dumps([1, 2]), json.dumps({"version": 999, "aspect": ASPECT, "shots": []})],
        ids=["corrupt", "not-an-object", "unknown-version"],
    )
    def test_an_unusable_shot_manifest_falls_back_to_re_encoding_everything(self, raw):
        # The degrade is LOUD (a warning) and conservative (re-encode), never a
        # silent reuse of a piece whose provenance we cannot establish.
        eng = _engine(read_text_fn=lambda _p: raw, exists_fn=lambda _p: True)
        with _captured_warnings() as seen:
            _out, reencoded = eng.render_shot_plan("in.mp4", "out.mp4", _plan(_shot(0)), _trace())
        assert reencoded == (0,)
        assert any("shot manifest" in m for m in seen)

    def test_a_missing_shot_manifest_falls_back_to_re_encoding_everything(self):
        def missing(_p):
            raise OSError("no such file")

        eng = _engine(read_text_fn=missing, exists_fn=lambda _p: True)
        _out, reencoded = eng.render_shot_plan("in.mp4", "out.mp4", _plan(_shot(0)), _trace())
        assert reencoded == (0,)


# --------------------------------------------------------------------------- #
# WU-E1 / WU-E3 — the two RPC handlers
# --------------------------------------------------------------------------- #
def _registry() -> tuple[JobRegistry, list[tuple]]:
    events: list[tuple] = []
    return (
        JobRegistry(
            emit_progress=lambda j, p, m: events.append(("progress", j, p, m)),
            emit_done=lambda j, r: events.append(("done", j, r)),
        ),
        events,
    )


def _ctx(reg) -> RpcContext:
    return RpcContext(emit_notification=lambda *_: None, jobs=reg)


class _RecordingEngine:
    """A whole-engine fake: records render_shot_plan kwargs and pokes its callbacks."""

    def __init__(self, analysis):
        self._analysis = analysis
        self.render_calls: list[dict[str, Any]] = []

    def analyze(self, _in_path, *, on_progress=None, should_cancel=None):
        del on_progress, should_cancel
        return self._analysis

    def render_shot_plan(self, _in_path, out_path, _plan, _trace, **kw):
        self.render_calls.append(kw)
        kw["on_progress"](150.0, "over-reporting on purpose")  # must be clamped
        kw["should_cancel"]()
        return out_path, ()


def _service(
    tmp_path,
    *,
    analysis=None,
    cache=None,
    settings=None,
    available=True,
    engine_kw=None,
    seen=None,
    engine=None,
):
    """A service with a fake engine (fake backend + fake runner) and a real cache."""
    backend = _FakeBackend(analysis if analysis is not None else _analysis())

    def engine_factory(engine_settings: dict[str, Any]):
        if seen is not None:
            seen.append(engine_settings)
        if engine is not None:
            return engine
        return _engine(backend_factory=lambda _s: backend, **(engine_kw or {}))

    service = ra.ReframeAnalyzeService(
        resolver=lambda vid: None if vid == "missing" else "/videos/in.mp4",
        out_dir=tmp_path / "reframed",
        settings_provider=lambda: settings or {},
        cache=cache,
        engine_factory=engine_factory,
        which=lambda _x: "/wsl" if available else None,
        models_present=lambda _s: True,
    )
    return service, backend


def _run(reg, out) -> Any:
    job = reg.get(out["jobId"])
    job.wait(10)
    return reg.get(out["jobId"])


class TestAnalyzeHandler:
    def test_requires_a_video_id(self, tmp_path):
        reg, _ = _registry()
        svc, _ = _service(tmp_path)
        with pytest.raises(RpcError, match="videoId"):
            svc.analyze({}, _ctx(reg))

    def test_an_unknown_video_is_refused(self, tmp_path):
        reg, _ = _registry()
        svc, _ = _service(tmp_path)
        with pytest.raises(RpcError, match="unknown video"):
            svc.analyze({"videoId": "missing"}, _ctx(reg))

    def test_a_missing_job_registry_is_an_internal_error(self, tmp_path):
        svc, _ = _service(tmp_path)
        with pytest.raises(RpcError, match="no job registry"):
            svc.analyze({"videoId": "v"}, RpcContext(emit_notification=lambda *_: None, jobs=None))

    @pytest.mark.parametrize("field", ["allowSplit", "allowComposite", "allowDegrade"])
    def test_a_non_boolean_flag_is_refused(self, tmp_path, field):
        reg, _ = _registry()
        svc, _ = _service(tmp_path)
        with pytest.raises(RpcError, match=field):
            svc.analyze({"videoId": "v", field: "yes"}, _ctx(reg))

    def test_an_unsupported_aspect_is_refused(self, tmp_path):
        reg, _ = _registry()
        svc, _ = _service(tmp_path)
        with pytest.raises(RpcError, match="aspect"):
            svc.analyze({"videoId": "v", "aspect": "banana"}, _ctx(reg))

    def test_a_non_string_aspect_is_refused(self, tmp_path):
        reg, _ = _registry()
        svc, _ = _service(tmp_path)
        with pytest.raises(RpcError, match="aspect"):
            svc.analyze({"videoId": "v", "aspect": 916}, _ctx(reg))

    def test_a_blank_diarize_backend_is_refused(self, tmp_path):
        reg, _ = _registry()
        svc, _ = _service(tmp_path)
        with pytest.raises(RpcError, match="diarizeBackend"):
            svc.analyze({"videoId": "v", "diarizeBackend": ""}, _ctx(reg))

    def test_the_diarize_backend_is_overlaid_onto_the_engine_settings(self, tmp_path):
        reg, _ = _registry()
        seen: list[dict[str, Any]] = []
        svc, _ = _service(tmp_path, seen=seen)
        out = svc.analyze({"videoId": "v", "diarizeBackend": "pyannote"}, _ctx(reg))
        assert _run(reg, out).status.value == "done"
        assert seen[0]["diarizeBackend"] == "pyannote"

    def test_without_a_diarize_backend_the_settings_are_untouched(self, tmp_path):
        reg, _ = _registry()
        seen: list[dict[str, Any]] = []
        svc, _ = _service(tmp_path, seen=seen)
        out = svc.analyze({"videoId": "v"}, _ctx(reg))
        assert _run(reg, out).status.value == "done"
        assert "diarizeBackend" not in seen[0]

    def test_returns_a_trace_and_a_plan_without_rendering(self, tmp_path):
        reg, _ = _registry()
        runs: list[list[str]] = []
        svc, backend = _service(tmp_path, engine_kw={"runner": lambda argv, **_kw: runs.append(list(argv)) or 0})
        out = svc.analyze({"videoId": "v"}, _ctx(reg))
        job = _run(reg, out)
        assert job.status.value == "done"
        assert job.result["degraded"] is None
        assert set(job.result["trace"]) == {"shotBoundaries", "speakerPerFrame", "segments", "crops"}
        assert job.result["plan"]["sourceWidth"] == 1920
        assert job.result["plan"]["shots"]
        assert backend.calls == 1
        assert runs == [], "reframe.analyze must not run ffmpeg"

    def test_a_second_call_reuses_the_cached_bundle(self, tmp_path):
        reg, _ = _registry()
        cache = ra.LruAnalysisCache()
        svc, backend = _service(tmp_path, cache=cache)
        first = _run(reg, svc.analyze({"videoId": "v"}, _ctx(reg)))
        second = _run(reg, svc.analyze({"videoId": "v"}, _ctx(reg)))
        assert first.result["plan"] == second.result["plan"]
        assert backend.calls == 1, "the cached analysis must not re-run the GPU stage"

    def test_a_different_aspect_is_a_cache_miss(self, tmp_path):
        reg, _ = _registry()
        cache = ra.LruAnalysisCache()
        svc, backend = _service(tmp_path, cache=cache)
        _run(reg, svc.analyze({"videoId": "v"}, _ctx(reg)))
        _run(reg, svc.analyze({"videoId": "v", "aspect": "1:1"}, _ctx(reg)))
        assert backend.calls == 2

    def test_a_different_diarize_backend_is_a_cache_miss(self, tmp_path):
        # The ONLY parameter this WU newly wired must not be the one the cache
        # silently ignores: a second analyze naming a different diarizer has to
        # actually re-run the analysis stage.
        reg, _ = _registry()
        cache = ra.LruAnalysisCache()
        svc, backend = _service(tmp_path, cache=cache)
        _run(reg, svc.analyze({"videoId": "v", "diarizeBackend": "alpha"}, _ctx(reg)))
        _run(reg, svc.analyze({"videoId": "v", "diarizeBackend": "beta"}, _ctx(reg)))
        assert backend.calls == 2

    def test_the_same_diarize_backend_still_hits_the_cache(self, tmp_path):
        reg, _ = _registry()
        cache = ra.LruAnalysisCache()
        svc, backend = _service(tmp_path, cache=cache)
        _run(reg, svc.analyze({"videoId": "v", "diarizeBackend": "alpha"}, _ctx(reg)))
        _run(reg, svc.analyze({"videoId": "v", "diarizeBackend": "alpha"}, _ctx(reg)))
        assert backend.calls == 1

    def test_the_default_cache_is_used_when_none_is_injected(self, tmp_path):
        reg, _ = _registry()
        svc, backend = _service(tmp_path, cache=None)
        _run(reg, svc.analyze({"videoId": "v"}, _ctx(reg)))
        _run(reg, svc.analyze({"videoId": "v"}, _ctx(reg)))
        assert backend.calls == 1

    def test_an_explicit_request_on_an_unavailable_host_is_a_typed_rpc_error(self, tmp_path):
        reg, _ = _registry()
        svc, _ = _service(tmp_path, available=False)
        with pytest.raises(RpcError, match="unavailable"):
            svc.analyze({"videoId": "v"}, _ctx(reg))

    def test_auto_degrade_yields_an_honest_null_plan_and_a_notice(self, tmp_path):
        reg, _ = _registry()
        svc, backend = _service(tmp_path, available=False)
        out = svc.analyze({"videoId": "v", "allowDegrade": True}, _ctx(reg))
        job = _run(reg, out)
        assert job.status.value == "done"
        assert job.result["plan"] is None
        assert job.result["trace"] is None
        assert job.result["degraded"]["type"]
        assert backend.calls == 0

    def test_offline_and_unavailable_raises_the_offline_error(self, tmp_path):
        reg, _ = _registry()
        svc, _ = _service(tmp_path, available=False, settings={"offline": True})
        with pytest.raises(_offline.OfflineError, match="Offline mode"):
            svc.analyze({"videoId": "v", "allowDegrade": True}, _ctx(reg))

    def test_offline_with_an_available_host_still_runs(self, tmp_path):
        reg, _ = _registry()
        svc, _ = _service(tmp_path, settings={"offline": True})
        assert _run(reg, svc.analyze({"videoId": "v"}, _ctx(reg))).status.value == "done"

    def test_a_failing_settings_provider_degrades_to_empty_settings(self, tmp_path):
        def boom():
            raise RuntimeError("settings store is wedged")

        reg, _ = _registry()
        svc = ra.ReframeAnalyzeService(
            resolver=lambda _v: "/videos/in.mp4",
            out_dir=tmp_path / "reframed",
            settings_provider=boom,
            engine_factory=lambda _s: _engine(backend_factory=lambda _s2: _FakeBackend(_analysis())),
            which=lambda _x: "/wsl",
            models_present=lambda _s: True,
        )
        assert _run(reg, svc.analyze({"videoId": "v"}, _ctx(reg))).status.value == "done"

    def test_the_backend_progress_is_clamped_below_the_plan_stage(self, tmp_path):
        reg, events = _registry()
        svc, _ = _service(tmp_path, analysis=_analysis())
        out = svc.analyze({"videoId": "v"}, _ctx(reg))
        assert _run(reg, out).status.value == "done"
        pcts = [e[2] for e in events if e[0] == "progress"]
        assert 50 in pcts, "an in-range backend report must pass through untouched"
        assert 90 in pcts, "the backend's over-reported 150% must be clamped to the stage ceiling"
        assert pcts[-1] == 100  # only the handler's own terminal step reports 100

    def test_cancelling_at_the_shots_checkpoint_aborts_before_the_plan_stage(self, tmp_path):
        # Cooperative cancel: the progress sink cancels at the "detecting shots"
        # checkpoint, so the post-analysis raise_if_cancelled aborts the job and no
        # bundle is ever cached (deterministic — mirrors test_diarize's sink trick).
        holder: dict[str, Any] = {}

        def emit_progress(job_id, pct, _msg):
            if pct == 2:
                holder["reg"].cancel(job_id)

        reg = JobRegistry(emit_progress=emit_progress, emit_done=lambda *_a: None)
        holder["reg"] = reg
        cache = ra.LruAnalysisCache()
        svc, _backend = _service(tmp_path, cache=cache)
        out = svc.analyze({"videoId": "v"}, _ctx(reg))
        reg.get(out["jobId"]).wait(10)
        assert reg.get(out["jobId"]).status.value == "cancelled"
        assert cache.find("v", ASPECT) is None


class TestRenderHandler:
    def _seeded(self, tmp_path, *, analysis=None, engine_kw=None):
        """A service whose cache already holds an analyze() bundle for ``v``."""
        reg, _ = _registry()
        cache = ra.LruAnalysisCache()
        svc, backend = _service(tmp_path, analysis=analysis, cache=cache, engine_kw=engine_kw)
        seeded = _run(reg, svc.analyze({"videoId": "v"}, _ctx(reg)))
        assert seeded.status.value == "done"
        return svc, cache, seeded.result["plan"], backend

    def test_requires_a_video_id(self, tmp_path):
        reg, _ = _registry()
        svc, _ = _service(tmp_path)
        with pytest.raises(RpcError, match="videoId"):
            svc.render({}, _ctx(reg))

    def test_a_missing_job_registry_is_an_internal_error(self, tmp_path):
        svc, _ = _service(tmp_path)
        with pytest.raises(RpcError, match="no job registry"):
            svc.render({"videoId": "v"}, RpcContext(emit_notification=lambda *_: None, jobs=None))

    def test_an_unknown_video_is_refused(self, tmp_path):
        reg, _ = _registry()
        svc, _ = _service(tmp_path)
        with pytest.raises(RpcError, match="unknown video"):
            svc.render({"videoId": "missing", "plan": _plan().to_dict()}, _ctx(reg))

    def test_a_malformed_plan_is_refused(self, tmp_path):
        reg, _ = _registry()
        svc, _ = _service(tmp_path)
        with pytest.raises(RpcError, match="plan"):
            svc.render({"videoId": "v", "plan": {"sourceWidth": 0}}, _ctx(reg))

    def test_a_non_boolean_affected_only_is_refused(self, tmp_path):
        reg, _ = _registry()
        svc, _ = _service(tmp_path)
        with pytest.raises(RpcError, match="affectedOnly"):
            svc.render({"videoId": "v", "plan": _plan().to_dict(), "affectedOnly": "yes"}, _ctx(reg))

    def test_without_a_cached_analysis_the_render_is_loud(self, tmp_path):
        reg, _ = _registry()
        svc, _ = _service(tmp_path)
        with pytest.raises(RpcError, match="reframe.analyze"):
            svc.render({"videoId": "v", "plan": _plan().to_dict()}, _ctx(reg))

    def test_a_plan_with_a_different_shot_count_is_refused(self, tmp_path):
        reg, _ = _registry()
        svc, _cache, plan, _b = self._seeded(tmp_path)
        wrong = {**plan, "shots": [*plan["shots"], {**plan["shots"][0], "index": 1}]}
        with pytest.raises(RpcError, match="shots"):
            svc.render({"videoId": "v", "plan": wrong}, _ctx(reg))

    def test_renders_the_edited_plan_and_reports_the_affected_shots(self, tmp_path):
        reg, _ = _registry()
        runs: list[list[str]] = []
        svc, _cache, plan, _b = self._seeded(
            tmp_path, engine_kw={"runner": lambda argv, **_kw: runs.append(list(argv)) or 0}
        )
        edited = {**plan, "shots": [{**plan["shots"][0], "layout": "split"}]}
        out = svc.render({"videoId": "v", "plan": edited}, _ctx(reg))
        job = _run(reg, out)
        assert job.status.value == "done", job.error
        assert job.result["outPath"].endswith("v.multispeaker.9x16.mp4")
        assert job.result["affected"] == [0]
        assert job.result["reencoded"] == [0]
        assert runs, "the edited plan must actually be encoded"

    def test_an_unedited_plan_renders_with_an_empty_affected_set(self, tmp_path):
        reg, _ = _registry()
        svc, _cache, plan, _b = self._seeded(tmp_path)
        job = _run(reg, svc.render({"videoId": "v", "plan": plan}, _ctx(reg)))
        assert job.status.value == "done", job.error
        assert job.result["affected"] == []
        # first render: no manifest on disk yet -> the shot is still encoded once
        assert job.result["reencoded"] == [0]

    def test_the_render_seams_are_threaded_to_the_engine(self, tmp_path):
        reg, events = _registry()
        recorder = _RecordingEngine(_analysis())
        cache = ra.LruAnalysisCache()
        svc, _b = _service(tmp_path, cache=cache, engine=recorder)
        _run(reg, svc.analyze({"videoId": "v"}, _ctx(reg)))
        plan = cache.find("v", ASPECT).plan.to_dict()
        job = _run(reg, svc.render({"videoId": "v", "plan": plan, "affectedOnly": False}, _ctx(reg)))
        assert job.status.value == "done", job.error
        kw = recorder.render_calls[0]
        assert kw["affected_only"] is False
        assert kw["aspect"] == ASPECT
        # the engine's over-reported 150% is clamped below the terminal 100
        assert 99 in [e[2] for e in events if e[0] == "progress"]

    def test_affected_only_defaults_to_true(self, tmp_path):
        reg, _ = _registry()
        recorder = _RecordingEngine(_analysis())
        cache = ra.LruAnalysisCache()
        svc, _b = _service(tmp_path, cache=cache, engine=recorder)
        _run(reg, svc.analyze({"videoId": "v"}, _ctx(reg)))
        plan = cache.find("v", ASPECT).plan.to_dict()
        _run(reg, svc.render({"videoId": "v", "plan": plan}, _ctx(reg)))
        assert recorder.render_calls[0]["affected_only"] is True

    def test_the_output_directory_is_created(self, tmp_path):
        reg, _ = _registry()
        svc, _cache, plan, _b = self._seeded(tmp_path)
        _run(reg, svc.render({"videoId": "v", "plan": plan}, _ctx(reg)))
        assert (tmp_path / "reframed").is_dir()

    # ----------------------------------------------------------------- #
    # The caller-supplied plan's SPANS + geometry are boundary-guarded too
    # ----------------------------------------------------------------- #
    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("endFrame", 10_000_000),  # past the analysed trace -> was an IndexError leak
            ("endFrame", 2),  # end < start
            ("startFrame", -4),  # negative -> was a wrap-around crop + a negative -ss
        ],
    )
    def test_a_plan_whose_frame_span_was_edited_is_refused(self, tmp_path, field, value):
        # These four scalars are NOT user-editable: they come from the analysis.
        # Before the guard, endFrame=10_000_000 crashed INSIDE the job with a bare
        # `IndexError: tuple index out of range` (an untyped internal message, not
        # the typed RPC error the contract advertises), and a negative startFrame
        # was ACCEPTED and reported done after building `-ss -0.133333`.
        reg, _ = _registry()
        svc, _cache, plan, _b = self._seeded(tmp_path)
        edited = {**plan, "shots": [{**plan["shots"][0], field: value}]}
        with pytest.raises(RpcError, match="frame span"):
            svc.render({"videoId": "v", "plan": edited}, _ctx(reg))

    @pytest.mark.parametrize(
        ("field", "value"),
        [("sourceWidth", 99_999), ("sourceHeight", 4), ("fps", 1.0)],
    )
    def test_a_plan_whose_source_geometry_was_edited_is_refused(self, tmp_path, field, value):
        # sourceWidth/Height drive every crop region and fps drives every -ss/-t,
        # and none of them is part of the segment reuse key, so accepting an edit
        # republished stale segments at the old geometry/timing.
        reg, _ = _registry()
        svc, _cache, plan, _b = self._seeded(tmp_path)
        with pytest.raises(RpcError, match="source geometry"):
            svc.render({"videoId": "v", "plan": {**plan, field: value}}, _ctx(reg))

    def test_the_output_path_carries_the_aspect(self, tmp_path):
        reg, _ = _registry()
        svc, _cache, plan, _b = self._seeded(tmp_path)
        job = _run(reg, svc.render({"videoId": "v", "plan": plan}, _ctx(reg)))
        assert job.status.value == "done", job.error
        assert job.result["outPath"].endswith("v.multispeaker.9x16.mp4")

    def test_a_second_aspect_renders_to_its_own_path_and_segment_cache(self, tmp_path):
        # Without the aspect in the name, a 1:1 render os.replace()d onto the 9:16
        # clip AND overwrote its segment cache.
        reg, _ = _registry()
        runs: list[list[str]] = []
        cache = ra.LruAnalysisCache()
        svc, _b = _service(
            tmp_path, cache=cache, engine_kw={"runner": lambda argv, **_kw: runs.append(list(argv)) or 0}
        )
        wide = _run(reg, svc.analyze({"videoId": "v", "aspect": "9:16"}, _ctx(reg))).result["plan"]
        square = _run(reg, svc.analyze({"videoId": "v", "aspect": "1:1"}, _ctx(reg))).result["plan"]
        first = _run(reg, svc.render({"videoId": "v", "aspect": "9:16", "plan": wide}, _ctx(reg)))
        second = _run(reg, svc.render({"videoId": "v", "aspect": "1:1", "plan": square}, _ctx(reg)))
        assert first.status.value == "done", first.error
        assert second.status.value == "done", second.error
        assert first.result["outPath"] != second.result["outPath"]
        encoded = [argv[-1] for argv in runs]
        assert len({p for p in encoded if "shot000" in p}) == 2, "each aspect needs its OWN segment cache"

    def test_the_layout_flags_select_the_exact_cached_bundle(self, tmp_path):
        # Two analyses of the same (videoId, aspect) differing only in allowSplit
        # leave two bundles. A flag-insensitive most-recently-used lookup diffed the
        # UNTOUCHED allowSplit=True plan against the allowSplit=False bundle and
        # reported affected=[0] — a shot the caller never edited.
        reg, _ = _registry()
        cache = ra.LruAnalysisCache()
        svc, _b = _service(tmp_path, analysis=_two_talker_analysis(), cache=cache)
        split = _run(reg, svc.analyze({"videoId": "v", "allowSplit": True}, _ctx(reg))).result["plan"]
        collapsed = _run(reg, svc.analyze({"videoId": "v", "allowSplit": False}, _ctx(reg))).result["plan"]
        assert split["shots"][0]["layout"] != collapsed["shots"][0]["layout"], "the fixture must differ"
        job = _run(reg, svc.render({"videoId": "v", "plan": split, "allowSplit": True}, _ctx(reg)))
        assert job.status.value == "done", job.error
        assert job.result["affected"] == []

    def test_an_omitted_flag_set_still_falls_back_to_the_most_recent_bundle(self, tmp_path):
        # Backward compatibility for the documented fallback: with only ONE cached
        # bundle for (videoId, aspect) the flag-insensitive lookup is unambiguous.
        reg, _ = _registry()
        cache = ra.LruAnalysisCache()
        svc, _b = _service(tmp_path, analysis=_two_talker_analysis(), cache=cache)
        collapsed = _run(reg, svc.analyze({"videoId": "v", "allowSplit": False}, _ctx(reg))).result["plan"]
        job = _run(reg, svc.render({"videoId": "v", "plan": collapsed}, _ctx(reg)))
        assert job.status.value == "done", job.error
        assert job.result["affected"] == []

    def test_a_non_boolean_render_flag_is_refused(self, tmp_path):
        reg, _ = _registry()
        svc, _ = _service(tmp_path)
        with pytest.raises(RpcError, match="allowComposite"):
            svc.render({"videoId": "v", "plan": _plan().to_dict(), "allowComposite": "yes"}, _ctx(reg))

    def test_a_blank_render_diarize_backend_is_refused(self, tmp_path):
        reg, _ = _registry()
        svc, _ = _service(tmp_path)
        with pytest.raises(RpcError, match="diarizeBackend"):
            svc.render({"videoId": "v", "plan": _plan().to_dict(), "diarizeBackend": ""}, _ctx(reg))

    def test_the_diarize_backend_selects_the_exact_cached_bundle(self, tmp_path):
        reg, _ = _registry()
        cache = ra.LruAnalysisCache()
        svc, backend = _service(tmp_path, cache=cache)
        plan = _run(reg, svc.analyze({"videoId": "v", "diarizeBackend": "alpha"}, _ctx(reg))).result["plan"]
        _run(reg, svc.analyze({"videoId": "v", "diarizeBackend": "beta"}, _ctx(reg)))
        assert backend.calls == 2
        job = _run(reg, svc.render({"videoId": "v", "plan": plan, "diarizeBackend": "alpha"}, _ctx(reg)))
        assert job.status.value == "done", job.error


# --------------------------------------------------------------------------- #
# registration
# --------------------------------------------------------------------------- #
class TestRegister:
    def test_registers_both_new_methods(self, tmp_path):
        names: list[str] = []
        service = ra.register(
            resolver=lambda _v: "/videos/in.mp4",
            out_dir=tmp_path / "reframed",
            register_fn=lambda name, _handler: names.append(name),
        )
        assert names == ["reframe.analyze", "reframe.render"]
        assert isinstance(service, ra.ReframeAnalyzeService)

    def test_the_default_engine_factory_builds_the_multispeaker_engine(self):
        assert isinstance(ra._default_engine_factory({}), ms.MultiSpeakerReframeEngine)
