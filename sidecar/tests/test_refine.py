"""Unit tests for the refine planner + service (features/refine.py, WU-1/WU-2).

``plan_refine`` (WU-1) is PURE timeline math: it composes the already-shipped
filler cut-list (:func:`fillers.build_cutlist_with_stats`) and silence keep-spans
(:func:`silencetrim.keep_spans`) into ONE union keep-list plus mirrored stats.
No subprocess, no model, no I/O — so every branch is exercised with hand-built
``words``/``silences`` and the bundled default filler sets.

``RefineService`` (WU-2) wraps that pure plan in ``preview`` (direct, NO encode)
and ``apply`` (a job that re-cuts via the injected ffmpeg ``run`` seam). Every
seam — ``resolver``, ``detect_run``, ``run``, ``duration``, ``load_project``,
``save_project`` — is faked, so no real ffmpeg / model / I/O is touched.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from media_studio import protocol
from media_studio.features import fillers as fl
from media_studio.features import refine as rf
from media_studio.jobs import JobRegistry
from media_studio.protocol import RpcContext, RpcError


def w(text: str, start: float, end: float) -> dict[str, Any]:
    return {"text": text, "start": start, "end": end}


def _kept_seconds(keeps: list[list[float]]) -> float:
    return round(sum(b - a for a, b in keeps), 3)


# ---------------------------------------------------------------------------
# both-off pass-through (acceptance #1)
# ---------------------------------------------------------------------------
def test_both_off_keeps_whole_clip_and_zero_stats():
    words = [w("um", 2.0, 2.4), w("hello", 3.0, 3.5)]
    plan = rf.plan_refine(
        words,
        "en",
        10.0,
        [(5.0, 7.0)],
        remove_fillers=False,
        remove_silence=False,
    )
    assert plan["keeps"] == [[0.0, 10.0]]
    stats = plan["stats"]
    assert stats["fillersRemoved"] == 0
    assert stats["fillerSeconds"] == 0.0
    assert stats["silenceRemovedSec"] == 0.0
    assert stats["keptSec"] == 10.0


# ---------------------------------------------------------------------------
# disjoint filler + silence (acceptance #2 — no double-count)
# ---------------------------------------------------------------------------
def test_disjoint_filler_and_silence_excluded_no_double_count():
    words = [
        w("people", 0.0, 0.5),
        w("um", 2.0, 2.4),
        w("buy", 3.0, 3.5),
    ]
    plan = rf.plan_refine(
        words,
        "en",
        10.0,
        [(5.0, 7.0)],
        remove_fillers=True,
        remove_silence=True,
        pad_sec=0.0,
    )
    keeps = plan["keeps"]
    # The filler [2.0,2.4] and the silence [5.0,7.0] are both removed.
    for start, end in keeps:
        assert not (start <= 2.0 < end), keeps
        assert not (start < 7.0 and end > 5.0 and start >= 5.0), keeps
    stats = plan["stats"]
    assert abs(stats["fillerSeconds"] - 0.4) < 1e-6
    assert abs(stats["silenceRemovedSec"] - 2.0) < 1e-6
    assert abs(stats["keptSec"] - 7.6) < 1e-6
    assert stats["fillersRemoved"] == 1


# ---------------------------------------------------------------------------
# overlapping filler-inside-silence collapses (acceptance #3)
# ---------------------------------------------------------------------------
def test_overlapping_filler_inside_silence_single_removed_region():
    # The filler word sits INSIDE the silent span: the removed region is ONE,
    # not the sum of both, so kept == total - removed (no double subtraction).
    words = [
        w("people", 0.0, 0.5),
        w("um", 5.5, 5.9),
        w("buy", 8.0, 8.5),
    ]
    plan = rf.plan_refine(
        words,
        "en",
        10.0,
        [(5.0, 7.0)],
        remove_fillers=True,
        remove_silence=True,
        pad_sec=0.0,
    )
    keeps = plan["keeps"]
    removed = round(10.0 - _kept_seconds(keeps), 3)
    assert removed <= 10.0
    assert abs(plan["stats"]["keptSec"] - _kept_seconds(keeps)) < 1e-6
    # The combined removed region equals the single 2.0s silence (filler subset).
    assert abs(removed - 2.0) < 1e-6


# ---------------------------------------------------------------------------
# edge silences (head at 0.0 / tail at total) — full-window inversion
# ---------------------------------------------------------------------------
def test_leading_silence_removed_from_clip_start():
    plan = rf.plan_refine(
        [],
        "en",
        10.0,
        [(0.0, 2.0)],
        remove_fillers=False,
        remove_silence=True,
        pad_sec=0.0,
    )
    assert plan["keeps"] == [[2.0, 10.0]]
    assert abs(plan["stats"]["silenceRemovedSec"] - 2.0) < 1e-6
    assert abs(plan["stats"]["keptSec"] - 8.0) < 1e-6


def test_trailing_silence_removed_to_clip_end():
    plan = rf.plan_refine(
        [],
        "en",
        10.0,
        [(8.0, 10.0)],
        remove_fillers=False,
        remove_silence=True,
        pad_sec=0.0,
    )
    assert plan["keeps"] == [[0.0, 8.0]]
    assert abs(plan["stats"]["silenceRemovedSec"] - 2.0) < 1e-6
    assert abs(plan["stats"]["keptSec"] - 8.0) < 1e-6


# ---------------------------------------------------------------------------
# fillers-only / silence-only branch matrix
# ---------------------------------------------------------------------------
def test_fillers_only_ignores_silence():
    words = [w("people", 0.0, 0.5), w("um", 2.0, 2.4), w("buy", 3.0, 3.5)]
    plan = rf.plan_refine(
        words,
        "en",
        10.0,
        [(5.0, 7.0)],
        remove_fillers=True,
        remove_silence=False,
    )
    assert plan["stats"]["silenceRemovedSec"] == 0.0
    assert plan["stats"]["fillerSeconds"] > 0.0
    # The silence span is NOT removed when remove_silence is off.
    assert any(start <= 6.0 < end for start, end in plan["keeps"])


def test_silence_only_ignores_fillers():
    words = [w("people", 0.0, 0.5), w("um", 2.0, 2.4), w("buy", 3.0, 3.5)]
    plan = rf.plan_refine(
        words,
        "en",
        10.0,
        [(5.0, 7.0)],
        remove_fillers=False,
        remove_silence=True,
        pad_sec=0.0,
    )
    assert plan["stats"]["fillerSeconds"] == 0.0
    assert plan["stats"]["fillersRemoved"] == 0
    assert abs(plan["stats"]["silenceRemovedSec"] - 2.0) < 1e-6
    # The filler is NOT removed when remove_fillers is off.
    assert any(start <= 2.2 < end for start, end in plan["keeps"])


# ---------------------------------------------------------------------------
# empty inputs + degenerate edges
# ---------------------------------------------------------------------------
def test_empty_words_and_empty_silences():
    plan = rf.plan_refine(
        [],
        "en",
        10.0,
        [],
        remove_fillers=True,
        remove_silence=True,
    )
    assert plan["keeps"] == [[0.0, 10.0]]
    assert plan["stats"]["fillersRemoved"] == 0
    assert plan["stats"]["silenceRemovedSec"] == 0.0
    assert plan["stats"]["keptSec"] == 10.0


def test_zero_length_total_sec_yields_empty_keeps():
    plan = rf.plan_refine(
        [],
        "en",
        0.0,
        [],
        remove_fillers=True,
        remove_silence=True,
    )
    assert plan["keeps"] == []
    assert plan["stats"]["keptSec"] == 0.0


def test_lang_none_falls_back_to_en():
    words = [w("people", 0.0, 0.5), w("um", 2.0, 2.4), w("buy", 3.0, 3.5)]
    plan = rf.plan_refine(
        words,
        None,
        10.0,
        [],
        remove_fillers=True,
        remove_silence=False,
    )
    # 'en' "um" is an always-filler, so it is removed under the en fallback.
    assert plan["stats"]["fillersRemoved"] == 1


# ---------------------------------------------------------------------------
# filler-set override threading (acceptance #4)
# ---------------------------------------------------------------------------
def test_filler_sets_override_changes_cut_math_for_ro():
    # A word that is NOT a default 'ro' filler; standing alone (pause-bounded).
    words = [
        w("bună", 0.0, 0.5),
        w("totuși", 2.0, 2.5),  # custom-only filler; pause-bounded both sides
        w("lume", 4.0, 4.5),
    ]
    base = rf.plan_refine(
        words,
        "ro",
        10.0,
        [],
        remove_fillers=True,
        remove_silence=False,
    )
    assert base["stats"]["fillersRemoved"] == 0  # default 'ro' keeps it
    assert any(start <= 2.2 < end for start, end in base["keeps"])

    custom = {
        "ro": {
            "always": frozenset({"totuși"}),
            "standalone": frozenset(),
        }
    }
    over = rf.plan_refine(
        words,
        "ro",
        10.0,
        [],
        remove_fillers=True,
        remove_silence=False,
        filler_sets=custom,
    )
    assert over["stats"]["fillersRemoved"] == base["stats"]["fillersRemoved"] + 1
    assert not any(start <= 2.2 < end for start, end in over["keeps"])


def test_filler_sets_none_uses_default_sets():
    words = [w("people", 0.0, 0.5), w("um", 2.0, 2.4), w("buy", 3.0, 3.5)]
    explicit = rf.plan_refine(
        words,
        "en",
        10.0,
        [],
        remove_fillers=True,
        remove_silence=False,
        filler_sets=None,
    )
    default = rf.plan_refine(
        words,
        "en",
        10.0,
        [],
        remove_fillers=True,
        remove_silence=False,
        filler_sets=fl.DEFAULT_SETS,
    )
    assert explicit == default


# ---------------------------------------------------------------------------
# RefinePlan typing surface
# ---------------------------------------------------------------------------
def test_refineplan_keys_and_all():
    plan = rf.plan_refine([], "en", 1.0, [], remove_fillers=False, remove_silence=False)
    assert set(plan) == {"keeps", "stats"}
    assert set(plan["stats"]) == {
        "fillersRemoved",
        "fillerSeconds",
        "silenceRemovedSec",
        "keptSec",
    }
    assert "plan_refine" in rf.__all__
    assert "RefinePlan" in rf.__all__


# ===========================================================================
# WU-2 — RefineService (preview + apply) over injected seams
# ===========================================================================

# A silencedetect stderr with one silent gap: [5.0, 7.0].
SILENCE_STDERR = (
    "[silencedetect @ 0x1] silence_start: 5.0\n[silencedetect @ 0x1] silence_end: 7.0 | silence_duration: 2.0\n"
)


class RecordingRun:
    """A fake ``ffmpeg.run`` seam: records argv, writes the output, no subprocess."""

    def __init__(self, code: int = 0) -> None:
        self.code = code
        self.calls: list[list[str]] = []

    def __call__(self, argv, *, total_sec: float = 0.0, on_progress=None, should_cancel=None) -> int:
        self.calls.append(list(argv))
        if self.code == 0:
            Path(argv[-1]).write_bytes(b"\x00mp4")
        return self.code


def detect_with(stderr: str):
    """A fake ``detect_run`` (subprocess.run-shaped) returning canned stderr."""

    class Completed:
        returncode = 0
        stdout = ""

    def runner(argv, **kw):
        c = Completed()
        c.stderr = stderr
        return c

    return runner


@pytest.fixture()
def bin_dir(tmp_path: Path) -> Path:
    d = tmp_path / "bin"
    d.mkdir()
    for name in ("ffmpeg", "ffprobe", "ffmpeg.exe", "ffprobe.exe"):
        (d / name).write_text("", encoding="utf-8")
    return d


@pytest.fixture()
def settings(bin_dir: Path) -> dict[str, Any]:
    return {"ffmpegPath": str(bin_dir)}


def _ctx(registry: JobRegistry | None) -> RpcContext:
    return RpcContext(emit_notification=lambda obj: None, jobs=registry)


def _transcript_with_words(words: list[dict[str, Any]]) -> dict[str, Any]:
    """A project transcript whose single segment carries ``words`` (§3 shape)."""
    return {
        "transcript": {
            "segments": [
                {"start": 0.0, "end": 10.0, "text": "people um buy", "words": words},
            ]
        }
    }


def _store(project: dict[str, Any]):
    """A (load_project, save_project, saved) triple over an in-memory project."""
    saved: dict[str, Any] = {}

    def load_project(video_id: str) -> dict[str, Any]:
        return project

    def save_project(video_id: str, data: dict[str, Any]) -> None:
        saved["video_id"] = video_id
        saved["data"] = data

    return load_project, save_project, saved


def _service(
    *,
    tmp_path: Path,
    settings: dict[str, Any],
    words: list[dict[str, Any]] | None = None,
    resolver=None,
    run=None,
    duration=None,
    detect_run=None,
):
    """Build a RefineService over fully-faked seams (no real ffmpeg / I/O)."""
    project = _transcript_with_words(words if words is not None else [w("um", 5.5, 5.9)])
    load_project, save_project, saved = _store(project)
    svc = rf.RefineService(
        resolver=resolver if resolver is not None else (lambda vid: "/lib/in.mp4"),
        out_dir=tmp_path / "refined",
        settings_provider=lambda: settings,
        run=run if run is not None else RecordingRun(),
        duration=duration if duration is not None else (lambda p, s=None: 10.0),
        detect_run=detect_run if detect_run is not None else detect_with(SILENCE_STDERR),
        load_project=load_project,
        save_project=save_project,
    )
    return svc, saved


# ---------------------------------------------------------------------------
# preview — direct, NO encode (acceptance #1)
# ---------------------------------------------------------------------------
class TestPreview:
    def test_preview_detects_once_and_never_encodes(self, tmp_path, settings):
        run = RecordingRun()
        detect_calls: list[Any] = []

        def detect_run(argv, **kw):
            detect_calls.append(argv)
            return detect_with(SILENCE_STDERR)(argv, **kw)

        svc, _ = _service(
            tmp_path=tmp_path,
            settings=settings,
            run=run,
            detect_run=detect_run,
        )
        out = svc.preview(
            {"videoId": "v1", "removeFillers": True, "removeSilence": True},
            _ctx(None),
        )
        assert "plan" in out
        assert len(detect_calls) == 1  # detect exactly once
        assert run.calls == []  # ZERO encodes

    def test_preview_plan_equals_plan_refine(self, tmp_path, settings):
        words = [w("people", 0.0, 0.5), w("um", 2.0, 2.4), w("buy", 3.0, 3.5)]
        svc, _ = _service(tmp_path=tmp_path, settings=settings, words=words)
        out = svc.preview(
            {"videoId": "v1", "removeFillers": True, "removeSilence": True, "padSec": 0.0},
            _ctx(None),
        )
        expected = rf.plan_refine(
            words,
            "en",
            10.0,
            [(5.0, 7.0)],
            remove_fillers=True,
            remove_silence=True,
            pad_sec=0.0,
        )
        assert out["plan"] == expected

    def test_preview_unknown_video_raises(self, tmp_path, settings):
        svc, _ = _service(tmp_path=tmp_path, settings=settings, resolver=lambda vid: None)
        with pytest.raises(RpcError, match="unknown video"):
            svc.preview({"videoId": "ghost"}, _ctx(None))

    def test_preview_explicit_path_short_circuits_resolver(self, tmp_path, settings):
        svc, _ = _service(tmp_path=tmp_path, settings=settings, resolver=lambda vid: None)
        out = svc.preview({"path": "/x/explicit.mp4", "removeSilence": True}, _ctx(None))
        assert "plan" in out

    def test_preview_missing_video_id_raises(self, tmp_path, settings):
        svc, _ = _service(tmp_path=tmp_path, settings=settings)
        with pytest.raises(RpcError, match="videoId"):
            svc.preview({"videoId": ""}, _ctx(None))

    def test_preview_forwards_filler_sets(self, tmp_path, settings):
        words = [w("bună", 0.0, 0.5), w("totuși", 2.0, 2.5), w("lume", 4.0, 4.5)]
        custom = {"ro": {"always": frozenset({"totuși"}), "standalone": frozenset()}}
        svc, _ = _service(tmp_path=tmp_path, settings=settings, words=words)
        base = svc.preview(
            {"videoId": "v1", "lang": "ro", "removeFillers": True},
            _ctx(None),
        )
        over = svc.preview(
            {"videoId": "v1", "lang": "ro", "removeFillers": True, "fillerSets": custom},
            _ctx(None),
        )
        # The override forwards to plan_refine -> one more filler removed.
        assert over["plan"]["stats"]["fillersRemoved"] == base["plan"]["stats"]["fillersRemoved"] + 1

    def test_preview_explicit_total_sec_skips_probe(self, tmp_path, settings):
        # A caller-supplied totalSec short-circuits the duration probe (the
        # `if total <= 0.0` false branch); the duration seam is never called.
        def boom_duration(p, s=None):  # pragma: no cover - must NOT be called
            raise AssertionError("duration probe should be skipped")

        svc, _ = _service(tmp_path=tmp_path, settings=settings, duration=boom_duration)
        out = svc.preview(
            {"videoId": "v1", "totalSec": 12.0, "removeSilence": True, "padSec": 0.0},
            _ctx(None),
        )
        assert out["plan"]["keeps"][-1][-1] == 12.0

    def test_preview_garbage_tunable_falls_back_to_default(self, tmp_path, settings):
        # A non-numeric tunable is coerced back to the default (_float except).
        svc, _ = _service(tmp_path=tmp_path, settings=settings)
        out = svc.preview(
            {"videoId": "v1", "noiseDb": "loud", "removeSilence": True},
            _ctx(None),
        )
        assert "plan" in out

    def test_preview_settings_provider_raising_yields_empty(self, tmp_path, bin_dir):
        # _settings swallows the error -> {} -> ffmpeg unresolvable -> no silences,
        # so the plan still computes (silence keeps whole clip).
        project = _transcript_with_words([w("um", 2.0, 2.4)])
        load_project, save_project, _ = _store(project)

        def boom() -> dict[str, Any]:
            raise RuntimeError("settings exploded")

        svc = rf.RefineService(
            resolver=lambda vid: "/lib/in.mp4",
            out_dir=tmp_path / "refined",
            settings_provider=boom,
            run=RecordingRun(),
            duration=lambda p, s=None: 10.0,
            detect_run=detect_with(SILENCE_STDERR),
            load_project=load_project,
            save_project=save_project,
        )
        out = svc.preview({"videoId": "v1", "removeFillers": True}, _ctx(None))
        assert "plan" in out


# ---------------------------------------------------------------------------
# apply — a job; writes *.refined.mp4 (acceptance #2/#3)
# ---------------------------------------------------------------------------
class TestApply:
    def test_apply_with_real_cuts_writes_refined_sibling(self, tmp_path, settings, registry):
        run = RecordingRun()
        svc, _ = _service(tmp_path=tmp_path, settings=settings, run=run)
        out = svc.apply(
            {"videoId": "v1", "removeFillers": True, "removeSilence": True, "padSec": 0.0},
            _ctx(registry),
        )
        assert "jobId" in out
        job = registry.get(out["jobId"])
        job.wait(timeout=5)
        assert job.status.value == "done"
        result = job.result
        assert result["path"].endswith(".refined.mp4")
        assert result["path"] != "/lib/in.mp4"
        assert result["removedSec"] > 0.0
        assert result["stats"]["silenceRemovedSec"] > 0.0
        # The recorded argv carved the WU-1 keep-list and wrote the refined sibling.
        assert run.calls
        assert run.calls[-1][-1].endswith(".refined.mp4")

    def test_apply_nothing_to_cut_passes_through(self, tmp_path, settings, registry):
        run = RecordingRun()
        # both toggles off -> keeps == [[0,total]] -> nothing removed -> pass-through.
        svc, _ = _service(tmp_path=tmp_path, settings=settings, run=run)
        out = svc.apply(
            {"videoId": "v1", "removeFillers": False, "removeSilence": False},
            _ctx(registry),
        )
        job = registry.get(out["jobId"])
        job.wait(timeout=5)
        result = job.result
        assert result["path"] == "/lib/in.mp4"  # ORIGINAL, untouched
        assert result["removedSec"] == 0.0
        assert run.calls == []  # NO re-encode

    def test_apply_remaps_cues_when_present(self, tmp_path, settings, registry):
        run = RecordingRun()
        svc, _ = _service(tmp_path=tmp_path, settings=settings, run=run)
        input_cues = [
            {"index": 1, "start": 0.0, "end": 4.0, "text": "hello"},
            {"index": 2, "start": 8.0, "end": 9.0, "text": "world"},
        ]
        out = svc.apply(
            {
                "videoId": "v1",
                "removeFillers": True,
                "removeSilence": True,
                "padSec": 0.0,
                "cues": input_cues,
            },
            _ctx(registry),
        )
        job = registry.get(out["jobId"])
        job.wait(timeout=5)
        result = job.result
        expected_cues = fl.remap_cues(input_cues, [tuple(k) for k in result["plan"]["keeps"]])
        assert result["cues"] == expected_cues

    def test_apply_without_cues_omits_cues_key(self, tmp_path, settings, registry):
        svc, _ = _service(tmp_path=tmp_path, settings=settings)
        out = svc.apply(
            {"videoId": "v1", "removeFillers": True, "removeSilence": True, "padSec": 0.0},
            _ctx(registry),
        )
        job = registry.get(out["jobId"])
        job.wait(timeout=5)
        assert "cues" not in job.result

    def test_apply_forwards_filler_sets(self, tmp_path, settings, registry):
        words = [w("bună", 0.0, 0.5), w("totuși", 2.0, 2.5), w("lume", 4.0, 4.5)]
        custom = {"ro": {"always": frozenset({"totuși"}), "standalone": frozenset()}}
        svc, _ = _service(tmp_path=tmp_path, settings=settings, words=words)
        out = svc.apply(
            {
                "videoId": "v1",
                "lang": "ro",
                "removeFillers": True,
                "removeSilence": False,
                "fillerSets": custom,
            },
            _ctx(registry),
        )
        job = registry.get(out["jobId"])
        job.wait(timeout=5)
        # The custom 'ro' filler set removed 'totuși' -> one filler removed.
        assert job.result["stats"]["fillersRemoved"] == 1

    def test_apply_ffmpeg_failure_errors_job(self, tmp_path, settings, registry):
        svc, _ = _service(tmp_path=tmp_path, settings=settings, run=RecordingRun(code=1))
        out = svc.apply(
            {"videoId": "v1", "removeFillers": True, "removeSilence": True, "padSec": 0.0},
            _ctx(registry),
        )
        job = registry.get(out["jobId"])
        job.wait(timeout=5)
        assert job.status.value == "error"

    def test_apply_cancelled_before_run_skips_encode(self, tmp_path, settings, registry):
        # Deterministic cancel: the duration probe sets the cancel flag, so the
        # post-plan ``raise_if_cancelled`` checkpoint fires before any encode —
        # no timing race on when the worker thread observes the flag.
        run = RecordingRun()

        def cancelling_duration(p, s=None):
            # The registry holds exactly this one job; cancel it from inside the
            # worker so the post-plan checkpoint fires deterministically.
            for job in registry.all().values():
                job.request_cancel()
            return 10.0

        svc, _ = _service(tmp_path=tmp_path, settings=settings, run=run, duration=cancelling_duration)
        out = svc.apply(
            {"videoId": "v1", "removeFillers": True, "removeSilence": True, "padSec": 0.0},
            _ctx(registry),
        )
        job = registry.get(out["jobId"])
        job.wait(timeout=5)
        assert job.status.value == "cancelled"
        assert run.calls == []  # the checkpoint short-circuited before encode

    def test_apply_unknown_video_raises(self, tmp_path, settings, registry):
        svc, _ = _service(tmp_path=tmp_path, settings=settings, resolver=lambda vid: None)
        with pytest.raises(RpcError, match="unknown video"):
            svc.apply({"videoId": "ghost"}, _ctx(registry))

    def test_apply_without_job_registry_raises(self, tmp_path, settings):
        svc, _ = _service(tmp_path=tmp_path, settings=settings)
        with pytest.raises(RpcError, match="no job registry"):
            svc.apply({"videoId": "v1"}, _ctx(None))

    def test_apply_zero_duration_passes_through(self, tmp_path, settings, registry):
        run = RecordingRun()
        svc, _ = _service(
            tmp_path=tmp_path,
            settings=settings,
            run=run,
            duration=lambda p, s=None: 0.0,
        )
        out = svc.apply(
            {"videoId": "v1", "removeFillers": True, "removeSilence": True},
            _ctx(registry),
        )
        job = registry.get(out["jobId"])
        job.wait(timeout=5)
        assert job.result["path"] == "/lib/in.mp4"
        assert job.result["removedSec"] == 0.0
        assert run.calls == []

    def test_apply_duration_probe_failure_passes_through(self, tmp_path, settings, registry):
        run = RecordingRun()

        def boom_duration(p, s=None):
            raise RuntimeError("probe failed")

        svc, _ = _service(tmp_path=tmp_path, settings=settings, run=run, duration=boom_duration)
        out = svc.apply(
            {"videoId": "v1", "removeFillers": True, "removeSilence": True},
            _ctx(registry),
        )
        job = registry.get(out["jobId"])
        job.wait(timeout=5)
        assert job.result["path"] == "/lib/in.mp4"
        assert run.calls == []


# ---------------------------------------------------------------------------
# words extraction + transcript edges
# ---------------------------------------------------------------------------
class TestWords:
    def test_no_transcript_yields_empty_words(self, tmp_path, settings, registry):
        # A project with no transcript -> no filler words -> silence-only plan.
        load_project, save_project, _ = _store({})
        svc = rf.RefineService(
            resolver=lambda vid: "/lib/in.mp4",
            out_dir=tmp_path / "refined",
            settings_provider=lambda: settings,
            run=RecordingRun(),
            duration=lambda p, s=None: 10.0,
            detect_run=detect_with(SILENCE_STDERR),
            load_project=load_project,
            save_project=save_project,
        )
        out = svc.preview(
            {"videoId": "v1", "removeFillers": True, "removeSilence": True, "padSec": 0.0},
            _ctx(None),
        )
        assert out["plan"]["stats"]["fillersRemoved"] == 0
        assert out["plan"]["stats"]["silenceRemovedSec"] > 0.0


# ---------------------------------------------------------------------------
# registration (refine.preview direct + refine.apply job)
# ---------------------------------------------------------------------------
class TestRegister:
    def test_register_wires_preview_and_apply(self, tmp_path, settings):
        registered: dict[str, Any] = {}
        load_project, save_project, _ = _store(_transcript_with_words([w("um", 5.5, 5.9)]))
        svc = rf.register(
            resolver=lambda vid: "/lib/in.mp4",
            out_dir=tmp_path / "refined",
            settings_provider=lambda: settings,
            run=RecordingRun(),
            duration=lambda p, s=None: 10.0,
            detect_run=detect_with(SILENCE_STDERR),
            load_project=load_project,
            save_project=save_project,
            register_fn=lambda name, fn: registered.__setitem__(name, fn),
        )
        assert set(registered) == {"refine.preview", "refine.apply"}
        # Bound methods compare by __func__/__self__ (a fresh `svc.preview`
        # access yields a new object, so identity would falsely fail).
        assert registered["refine.preview"] == svc.preview
        assert registered["refine.apply"] == svc.apply
        assert registered["refine.preview"].__self__ is svc

    def test_register_defaults_to_protocol_register(self, tmp_path, settings):
        load_project, save_project, _ = _store(_transcript_with_words([w("um", 5.5, 5.9)]))
        rf.register(
            resolver=lambda vid: "/lib/in.mp4",
            out_dir=tmp_path / "refined",
            settings_provider=lambda: settings,
            run=RecordingRun(),
            duration=lambda p, s=None: 10.0,
            detect_run=detect_with(SILENCE_STDERR),
            load_project=load_project,
            save_project=save_project,
        )
        assert "refine.preview" in protocol.METHODS
        assert "refine.apply" in protocol.METHODS

    def test_register_is_in_all(self):
        assert "RefineService" in rf.__all__
        assert "register" in rf.__all__


# ---------------------------------------------------------------------------
# default ffmpeg seams (lazy real impls) — identity, no subprocess
# ---------------------------------------------------------------------------
class TestDefaultSeams:
    def test_default_run_is_ffmpeg_run(self):
        from media_studio import ffmpeg as _ffmpeg

        assert rf._default_run() is _ffmpeg.run

    def test_default_duration_is_ffprobe_duration(self):
        from media_studio import ffmpeg as _ffmpeg

        assert rf._default_duration() is _ffmpeg.ffprobe_duration

    def test_apply_uses_default_duration_when_none(self, tmp_path, settings, registry):
        # ``duration=None`` -> the real ffprobe seam runs on a bogus path, fails,
        # _probe_total returns 0.0 -> pass-through (the real ``run`` is never hit).
        run = RecordingRun()
        project = _transcript_with_words([w("um", 5.5, 5.9)])
        load_project, save_project, _ = _store(project)
        svc = rf.RefineService(
            resolver=lambda vid: "/no/such/clip.mp4",
            out_dir=tmp_path / "refined",
            settings_provider=lambda: settings,
            run=run,
            duration=None,  # exercises _default_duration()
            detect_run=detect_with(SILENCE_STDERR),
            load_project=load_project,
            save_project=save_project,
        )
        out = svc.apply({"videoId": "v1", "removeSilence": True}, _ctx(registry))
        job = registry.get(out["jobId"])
        job.wait(timeout=5)
        assert job.result["path"] == "/no/such/clip.mp4"
        assert run.calls == []
