"""Unit tests for transcript-native editing (features/transcript_edit.py, v1.5 T1/T3).

The flagship "delete a word -> the video cuts" vertical slice. Three tiers, all
hermetic (no ffmpeg, no model, no real I/O):

1. **Addressing (T1, pure).** ``address_transcript`` stamps a stable ``wordId``
   onto every word without mutating the input, so the renderer can address a
   token and the backend can resolve it back to ``[start, end]`` seconds.
2. **Translator (T3, pure).** ``resolve_edits`` turns EditSpans into removed
   spans (dropping impossible/unknown ones with a TYPED reason, never raising --
   mirroring ``edit_validate.validate_and_reject``), and
   ``plan_transcript_edit`` unions them with the SHIPPED filler/silence math
   (``refine.plan_refine``) into ONE keep-list + stats + re-timed cues.
3. **Service (T3).** ``transcript.get`` / ``previewEdit`` / ``applyEdit`` /
   ``undoEdit`` over fully-injected seams. ``applyEdit`` renders ONCE through the
   fake ``run`` seam (writing ``*.edited.mp4`` -- the original is never touched)
   and records a reversible edit entry; ``undoEdit`` pops it back.

Assertions are on VALUES the real pure functions compute (the exact keep-list,
the exact argv trim times, the exact remapped cue seconds) -- never on "was this
called", which stays green even when the value is wrong.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from media_studio import library as lib
from media_studio import protocol
from media_studio.features import refine as rf
from media_studio.features import transcript_edit as te
from media_studio.jobs import JobRegistry
from media_studio.protocol import RpcContext, RpcError

# --------------------------------------------------------------------------- #
# fixtures / builders
# --------------------------------------------------------------------------- #
SILENCE_STDERR = (
    "[silencedetect @ 0x1] silence_start: 5.0\n[silencedetect @ 0x1] silence_end: 7.0 | silence_duration: 2.0\n"
)


def w(text: str, start: float, end: float) -> dict[str, Any]:
    return {"text": text, "start": start, "end": end}


def _transcript(words: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """A §3 transcript with ONE segment carrying ``words``."""
    return {
        "language": "en",
        "durationSec": 10.0,
        "segments": [
            {
                "start": 0.0,
                "end": 3.5,
                "text": "we um should ship",
                "words": words
                if words is not None
                else [
                    w("we", 0.0, 0.5),
                    w("um", 1.0, 1.4),
                    w("should", 2.0, 2.5),
                    w("ship", 3.0, 3.5),
                ],
            }
        ],
    }


class RecordingRun:
    """A fake ffmpeg ``run`` seam recording every argv it is handed."""

    def __init__(self, code: int = 0) -> None:
        self.calls: list[list[str]] = []
        self.code = code

    def __call__(self, argv, **kw) -> int:
        self.calls.append(list(argv))
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


def _service(
    *,
    tmp_path: Path,
    settings: dict[str, Any],
    project: dict[str, Any] | None = None,
    resolver=None,
    run=None,
    duration=None,
    detect_run=None,
):
    """A TranscriptEditService over fully-faked seams + the live project dict."""
    data = project if project is not None else {"id": "p1", "transcript": _transcript()}

    def load_project(video_id: str) -> dict[str, Any]:
        return data

    def save_project(video_id: str, payload: dict[str, Any]) -> None:
        data.clear()
        data.update(payload)

    svc = te.TranscriptEditService(
        resolver=resolver if resolver is not None else (lambda vid: "/lib/in.mp4"),
        out_dir=tmp_path / "edited",
        load_project=load_project,
        save_project=save_project,
        settings_provider=lambda: settings,
        run=run if run is not None else RecordingRun(),
        duration=duration if duration is not None else (lambda p, s=None: 10.0),
        detect_run=detect_run if detect_run is not None else detect_with(SILENCE_STDERR),
    )
    return svc, data


# --------------------------------------------------------------------------- #
# T1 — stable word addressing (pure, immutable)
# --------------------------------------------------------------------------- #
class TestAddressing:
    def test_word_id_is_segment_and_word_index(self):
        assert te.word_id(0, 3) == "w0-3"
        assert te.word_id(2, 11) == "w2-11"

    def test_address_transcript_stamps_ids_without_mutating_input(self):
        src = _transcript()
        out = te.address_transcript(src)
        assert out is not None
        stamped = out["segments"][0]["words"]
        assert [x["wordId"] for x in stamped] == ["w0-0", "w0-1", "w0-2", "w0-3"]
        assert stamped[3] == {
            "text": "ship",
            "start": 3.0,
            "end": 3.5,
            "wordId": "w0-3",
            "segmentIndex": 0,
            "wordIndex": 3,
        }
        # the SOURCE transcript is untouched (immutability rule)
        assert "wordId" not in src["segments"][0]["words"][3]

    def test_address_transcript_preserves_an_existing_word_id(self):
        src = _transcript([{"text": "hi", "start": 0.0, "end": 0.4, "wordId": "legacy-7"}])
        out = te.address_transcript(src)
        assert out is not None
        assert out["segments"][0]["words"][0]["wordId"] == "legacy-7"

    def test_address_transcript_of_none_is_none(self):
        assert te.address_transcript(None) is None

    def test_address_transcript_tolerates_junk_segments_and_words(self):
        src = {"segments": [None, {"words": None}, {"words": ["not-a-dict", w("ok", 1.0, 2.0)]}]}
        out = te.address_transcript(src)
        assert out is not None
        # a non-mapping segment passes through VERBATIM; a non-mapping word too;
        # only the real word is stamped, and its index reflects its true slot.
        assert out["segments"] == [
            None,
            {"words": None},
            {
                "words": [
                    "not-a-dict",
                    {"text": "ok", "start": 1.0, "end": 2.0, "wordId": "w2-1", "segmentIndex": 2, "wordIndex": 1},
                ]
            },
        ]
        # ...and the flat view skips both junk entries
        assert [x["wordId"] for x in te.addressed_words(src)] == ["w2-1"]

    def test_addressed_words_flattens_across_segments(self):
        src = {
            "segments": [
                {"words": [w("a", 0.0, 0.2)]},
                {"words": [w("b", 1.0, 1.2), w("c", 2.0, 2.2)]},
            ]
        }
        assert [x["wordId"] for x in te.addressed_words(src)] == ["w0-0", "w1-0", "w1-1"]

    def test_addressed_words_of_empty_transcript_is_empty(self):
        assert te.addressed_words(None) == []


# --------------------------------------------------------------------------- #
# T3a — the pure EditSpan -> removed-span translator
# --------------------------------------------------------------------------- #
class TestResolveEdits:
    def test_delete_by_word_id_resolves_to_the_word_span(self):
        removed, rejected = te.resolve_edits([{"op": "delete", "wordId": "w0-3"}], _transcript(), 10.0)
        assert removed == [(3.0, 3.5)]
        assert rejected == []

    def test_delete_by_segment_and_word_index_resolves(self):
        removed, rejected = te.resolve_edits([{"op": "delete", "segmentIndex": 0, "wordIndex": 1}], _transcript(), 10.0)
        assert removed == [(1.0, 1.4)]
        assert rejected == []

    def test_delete_defaults_the_op_when_absent(self):
        removed, _ = te.resolve_edits([{"wordId": "w0-0"}], _transcript(), 10.0)
        assert removed == [(0.0, 0.5)]

    def test_trim_uses_explicit_millisecond_bounds(self):
        removed, rejected = te.resolve_edits([{"op": "trim", "startMs": 3200, "endMs": 3400}], _transcript(), 10.0)
        assert removed == [(3.2, 3.4)]
        assert rejected == []

    def test_trim_clamps_to_the_clip_duration(self):
        removed, _ = te.resolve_edits([{"op": "trim", "startMs": -500, "endMs": 99000}], _transcript(), 10.0)
        assert removed == [(0.0, 10.0)]

    def test_delete_with_explicit_bounds_beats_a_missing_address(self):
        removed, rejected = te.resolve_edits([{"op": "delete", "startMs": 1000, "endMs": 1400}], _transcript(), 10.0)
        assert removed == [(1.0, 1.4)]
        assert rejected == []

    def test_unknown_word_id_is_dropped_with_a_typed_reason(self):
        removed, rejected = te.resolve_edits([{"op": "delete", "wordId": "w9-9"}], _transcript(), 10.0)
        assert removed == []
        assert rejected == [{"index": 0, "op": "delete", "reason": te.REASON_UNKNOWN_WORD}]

    def test_out_of_range_word_index_is_dropped(self):
        removed, rejected = te.resolve_edits(
            [{"op": "delete", "segmentIndex": 0, "wordIndex": 99}], _transcript(), 10.0
        )
        assert removed == []
        assert rejected[0]["reason"] == te.REASON_UNKNOWN_WORD

    def test_delete_with_no_address_at_all_is_dropped(self):
        removed, rejected = te.resolve_edits([{"op": "delete"}], _transcript(), 10.0)
        assert removed == []
        assert rejected[0]["reason"] == te.REASON_MISSING_SPAN

    def test_trim_without_bounds_is_dropped(self):
        removed, rejected = te.resolve_edits([{"op": "trim", "wordId": "w0-0"}], _transcript(), 10.0)
        assert removed == []
        assert rejected[0]["reason"] == te.REASON_MISSING_SPAN

    def test_zero_length_span_is_dropped(self):
        removed, rejected = te.resolve_edits([{"op": "trim", "startMs": 2000, "endMs": 2000}], _transcript(), 10.0)
        assert removed == []
        assert rejected[0]["reason"] == te.REASON_EMPTY_SPAN

    def test_span_entirely_past_the_clip_end_is_dropped(self):
        removed, rejected = te.resolve_edits([{"op": "trim", "startMs": 20000, "endMs": 21000}], _transcript(), 10.0)
        assert removed == []
        assert rejected[0]["reason"] == te.REASON_EMPTY_SPAN

    def test_reorder_is_dropped_as_deferred_not_silently_applied(self):
        removed, rejected = te.resolve_edits([{"op": "reorder", "wordId": "w0-3", "toIndex": 0}], _transcript(), 10.0)
        assert removed == []
        assert rejected == [{"index": 0, "op": "reorder", "reason": te.REASON_REORDER_DEFERRED}]

    def test_unknown_op_is_dropped(self):
        removed, rejected = te.resolve_edits([{"op": "teleport", "wordId": "w0-0"}], _transcript(), 10.0)
        assert removed == []
        assert rejected[0]["reason"] == te.REASON_UNKNOWN_OP

    def test_non_mapping_edit_is_dropped(self):
        removed, rejected = te.resolve_edits(["nope"], _transcript(), 10.0)
        assert removed == []
        assert rejected == [{"index": 0, "op": "", "reason": te.REASON_UNKNOWN_OP}]

    def test_non_numeric_bounds_are_dropped_not_raised(self):
        removed, rejected = te.resolve_edits([{"op": "trim", "startMs": "x", "endMs": 500}], _transcript(), 10.0)
        assert removed == []
        assert rejected[0]["reason"] == te.REASON_MISSING_SPAN

    def test_no_edits_yields_no_spans(self):
        assert te.resolve_edits(None, _transcript(), 10.0) == ([], [])

    def test_word_with_junk_timings_is_dropped(self):
        bad = _transcript([{"text": "ghost", "start": "a", "end": "b"}])
        removed, rejected = te.resolve_edits([{"op": "delete", "wordId": "w0-0"}], bad, 10.0)
        assert removed == []
        assert rejected[0]["reason"] == te.REASON_EMPTY_SPAN


# --------------------------------------------------------------------------- #
# T3b — the composed plan (delete UNION shipped filler/silence math)
# --------------------------------------------------------------------------- #
class TestPlan:
    def test_delete_one_word_cuts_exactly_that_span(self):
        plan = te.plan_transcript_edit(
            _transcript(),
            [{"op": "delete", "wordId": "w0-3"}],
            10.0,
            [],
            remove_fillers=False,
            remove_silence=False,
        )
        assert plan["keeps"] == [[0.0, 3.0], [3.5, 10.0]]
        assert plan["stats"]["wordsDeleted"] == 1
        assert plan["stats"]["deletedSec"] == 0.5
        assert plan["stats"]["keptSec"] == 9.5
        assert plan["stats"]["removedSec"] == 0.5
        assert plan["rejected"] == []

    def test_two_deletes_produce_three_keeps(self):
        plan = te.plan_transcript_edit(
            _transcript(),
            [{"op": "delete", "wordId": "w0-1"}, {"op": "delete", "wordId": "w0-3"}],
            10.0,
            [],
            remove_fillers=False,
            remove_silence=False,
        )
        assert plan["keeps"] == [[0.0, 1.0], [1.4, 3.0], [3.5, 10.0]]
        assert plan["stats"]["wordsDeleted"] == 2

    def test_overlapping_deletes_are_unioned_not_double_counted(self):
        plan = te.plan_transcript_edit(
            _transcript(),
            [
                {"op": "delete", "wordId": "w0-3"},
                {"op": "trim", "startMs": 3200, "endMs": 3800},
            ],
            10.0,
            [],
            remove_fillers=False,
            remove_silence=False,
        )
        assert plan["keeps"] == [[0.0, 3.0], [3.8, 10.0]]
        assert plan["stats"]["deletedSec"] == 0.8  # 3.0..3.8, NOT 0.5 + 0.6

    def test_no_edits_and_no_toggles_keeps_the_whole_clip(self):
        plan = te.plan_transcript_edit(_transcript(), [], 10.0, [], remove_fillers=False, remove_silence=False)
        assert plan["keeps"] == [[0.0, 10.0]]
        assert plan["stats"]["removedSec"] == 0.0

    def test_zero_duration_yields_an_empty_plan(self):
        plan = te.plan_transcript_edit(_transcript(), [], 0.0, [], remove_fillers=False, remove_silence=False)
        assert plan["keeps"] == []
        assert plan["stats"]["keptSec"] == 0.0

    def test_delete_composes_with_the_shipped_filler_and_silence_math(self):
        edits = [{"op": "delete", "wordId": "w0-3"}]
        plan = te.plan_transcript_edit(
            _transcript(),
            edits,
            10.0,
            [(5.0, 7.0)],
            remove_fillers=True,
            remove_silence=True,
            lang="en",
            pad_sec=0.0,
        )
        base = rf.plan_refine(
            [w("we", 0.0, 0.5), w("um", 1.0, 1.4), w("should", 2.0, 2.5), w("ship", 3.0, 3.5)],
            "en",
            10.0,
            [(5.0, 7.0)],
            remove_fillers=True,
            remove_silence=True,
            pad_sec=0.0,
        )
        # the filler ("um") and silence stats are the SHIPPED numbers, unchanged
        assert plan["stats"]["fillersRemoved"] == base["stats"]["fillersRemoved"] == 1
        assert plan["stats"]["silenceRemovedSec"] == base["stats"]["silenceRemovedSec"]
        # ...and the word delete removed 0.5s MORE than refine alone
        assert plan["stats"]["keptSec"] == round(base["stats"]["keptSec"] - 0.5, 3)
        assert [3.0, 3.5] not in plan["keeps"]

    def test_cues_are_retimed_onto_the_cut_timeline(self):
        plan = te.plan_transcript_edit(
            _transcript(),
            [{"op": "delete", "wordId": "w0-3"}],
            10.0,
            [],
            remove_fillers=False,
            remove_silence=False,
            cues=[
                {"index": 1, "start": 0.0, "end": 1.0, "text": "we"},
                {"index": 2, "start": 4.0, "end": 5.0, "text": "after"},
            ],
        )
        # the second cue slides EARLIER by exactly the 0.5s that was cut
        assert plan["cues"] == [
            {"index": 1, "start": 0.0, "end": 1.0, "text": "we"},
            {"index": 2, "start": 3.5, "end": 4.5, "text": "after"},
        ]

    def test_absent_cues_yields_an_empty_cue_list(self):
        plan = te.plan_transcript_edit(_transcript(), [], 10.0, [], remove_fillers=False, remove_silence=False)
        assert plan["cues"] == []

    def test_rejections_survive_into_the_plan(self):
        plan = te.plan_transcript_edit(
            _transcript(),
            [{"op": "reorder", "wordId": "w0-0"}],
            10.0,
            [],
            remove_fillers=False,
            remove_silence=False,
        )
        assert plan["rejected"] == [{"index": 0, "op": "reorder", "reason": te.REASON_REORDER_DEFERRED}]
        assert plan["keeps"] == [[0.0, 10.0]]  # nothing cut

    def test_deleting_everything_still_leaves_a_legal_keep_list(self):
        plan = te.plan_transcript_edit(
            _transcript(),
            [{"op": "trim", "startMs": 0, "endMs": 10000}],
            10.0,
            [],
            remove_fillers=False,
            remove_silence=False,
        )
        assert plan["keeps"] == [[0.0, 10.0]]  # a full-clip delete degrades to a no-op
        assert plan["stats"]["removedSec"] == 0.0


# --------------------------------------------------------------------------- #
# T3c — the service: get / previewEdit / applyEdit / undoEdit
# --------------------------------------------------------------------------- #
class TestGet:
    def test_get_returns_the_addressed_transcript(self, tmp_path, settings):
        svc, _ = _service(tmp_path=tmp_path, settings=settings)
        out = svc.get({"videoId": "v1"}, _ctx(None))
        assert out["transcript"]["segments"][0]["words"][2]["wordId"] == "w0-2"

    def test_get_without_a_transcript_returns_none(self, tmp_path, settings):
        svc, _ = _service(tmp_path=tmp_path, settings=settings, project={"id": "p1"})
        assert svc.get({"videoId": "v1"}, _ctx(None)) == {"transcript": None}

    def test_get_requires_a_video_id(self, tmp_path, settings):
        svc, _ = _service(tmp_path=tmp_path, settings=settings)
        with pytest.raises(RpcError, match="videoId"):
            svc.get({}, _ctx(None))


class TestPreviewEdit:
    def test_preview_plans_without_encoding(self, tmp_path, settings):
        run = RecordingRun()
        svc, _ = _service(tmp_path=tmp_path, settings=settings, run=run)
        out = svc.previewEdit(
            {"videoId": "v1", "edits": [{"op": "delete", "wordId": "w0-3"}], "totalSec": 10.0},
            _ctx(None),
        )
        assert out["plan"]["keeps"] == [[0.0, 3.0], [3.5, 10.0]]
        assert run.calls == []  # ZERO encodes

    def test_preview_probes_the_duration_when_not_supplied(self, tmp_path, settings):
        svc, _ = _service(tmp_path=tmp_path, settings=settings, duration=lambda p, s=None: 12.0)
        out = svc.previewEdit({"videoId": "v1", "edits": []}, _ctx(None))
        assert out["plan"]["keeps"] == [[0.0, 12.0]]

    def test_preview_accepts_an_explicit_path(self, tmp_path, settings):
        svc, _ = _service(tmp_path=tmp_path, settings=settings, resolver=lambda vid: None)
        out = svc.previewEdit({"path": "/x/explicit.mp4", "videoId": "v1", "totalSec": 10.0}, _ctx(None))
        assert out["plan"]["keeps"] == [[0.0, 10.0]]

    def test_preview_unknown_video_raises(self, tmp_path, settings):
        svc, _ = _service(tmp_path=tmp_path, settings=settings, resolver=lambda vid: None)
        with pytest.raises(RpcError, match="unknown video"):
            svc.previewEdit({"videoId": "ghost"}, _ctx(None))

    def test_preview_settings_provider_failure_is_swallowed(self, tmp_path, bin_dir):
        def boom() -> dict[str, Any]:
            raise RuntimeError("settings exploded")

        data = {"id": "p1", "transcript": _transcript()}
        svc = te.TranscriptEditService(
            resolver=lambda vid: "/lib/in.mp4",
            out_dir=tmp_path / "edited",
            load_project=lambda vid: data,
            save_project=lambda vid, payload: None,
            settings_provider=boom,
            run=RecordingRun(),
            duration=lambda p, s=None: 10.0,
            detect_run=detect_with(SILENCE_STDERR),
        )
        out = svc.previewEdit({"videoId": "v1", "edits": [{"op": "delete", "wordId": "w0-3"}]}, _ctx(None))
        assert out["plan"]["stats"]["wordsDeleted"] == 1

    def test_preview_default_settings_provider_is_empty(self, tmp_path):
        data = {"id": "p1", "transcript": _transcript()}
        svc = te.TranscriptEditService(
            resolver=lambda vid: "/lib/in.mp4",
            out_dir=tmp_path / "edited",
            load_project=lambda vid: data,
            save_project=lambda vid, payload: None,
            duration=lambda p, s=None: 10.0,
            detect_run=detect_with(""),
        )
        out = svc.previewEdit({"videoId": "v1", "totalSec": 10.0}, _ctx(None))
        assert out["plan"]["keeps"] == [[0.0, 10.0]]

    def test_preview_missing_project_plans_on_an_empty_transcript(self, tmp_path, settings):
        svc, _ = _service(tmp_path=tmp_path, settings=settings, project={})
        out = svc.previewEdit(
            {"videoId": "v1", "edits": [{"op": "delete", "wordId": "w0-3"}], "totalSec": 10.0},
            _ctx(None),
        )
        assert out["plan"]["rejected"][0]["reason"] == te.REASON_UNKNOWN_WORD

    def test_preview_with_no_video_id_and_a_path_reads_no_project(self, tmp_path, settings):
        def boom_load(video_id: str):  # pragma: no cover - must NOT be called
            raise AssertionError("load_project must not run without a videoId")

        svc = te.TranscriptEditService(
            resolver=lambda vid: None,
            out_dir=tmp_path / "edited",
            load_project=boom_load,
            save_project=lambda vid, payload: None,
            settings_provider=lambda: settings,
            run=RecordingRun(),
            duration=lambda p, s=None: 10.0,
            detect_run=detect_with(""),
        )
        out = svc.previewEdit({"path": "/x/explicit.mp4", "totalSec": 10.0}, _ctx(None))
        assert out["plan"]["keeps"] == [[0.0, 10.0]]


class TestApplyEdit:
    def _apply(self, svc, registry, params):
        out = svc.applyEdit(params, _ctx(registry))
        job = registry.get(out["jobId"])
        job.wait(timeout=5)
        assert job.status.value == "done", job.error
        return job.result

    def test_apply_renders_once_and_writes_an_edited_sibling(self, tmp_path, settings, registry):
        run = RecordingRun()
        svc, data = _service(tmp_path=tmp_path, settings=settings, run=run)
        result = self._apply(svc, registry, {"videoId": "v1", "edits": [{"op": "delete", "wordId": "w0-3"}]})

        assert result["path"].endswith(".edited.mp4")
        assert result["path"] != "/lib/in.mp4"  # the ORIGINAL is never overwritten
        assert result["removedSec"] == 0.5
        assert result["editId"] == "tedit-1"
        assert len(run.calls) == 1  # exactly ONE encode
        argv = run.calls[0]
        # the argv carries the REAL keep-list values, not a mock's say-so
        assert "[0:v]trim=start=0.000:end=3.000,setpts=PTS-STARTPTS[v0]" in argv[argv.index("-filter_complex") + 1]
        assert "[0:v]trim=start=3.500:end=10.000,setpts=PTS-STARTPTS[v1]" in argv[argv.index("-filter_complex") + 1]
        # ...and the edit is recorded on the project for undo
        assert data["transcriptEdits"] == [
            {
                "editId": "tedit-1",
                "path": result["path"],
                "sourcePath": "/lib/in.mp4",
                "removedSec": 0.5,
                "keeps": [[0.0, 3.0], [3.5, 10.0]],
            }
        ]

    def test_apply_with_nothing_removed_passes_through_untouched(self, tmp_path, settings, registry):
        run = RecordingRun()
        svc, data = _service(tmp_path=tmp_path, settings=settings, run=run)
        result = self._apply(
            svc, registry, {"videoId": "v1", "edits": [], "removeFillers": False, "removeSilence": False}
        )
        assert result["path"] == "/lib/in.mp4"
        assert result["removedSec"] == 0.0
        assert result["editId"] is None
        assert run.calls == []  # NO re-encode
        assert "transcriptEdits" not in data  # nothing recorded

    def test_apply_on_a_zero_duration_clip_passes_through(self, tmp_path, settings, registry):
        run = RecordingRun()
        svc, _ = _service(tmp_path=tmp_path, settings=settings, run=run, duration=lambda p, s=None: 0.0)
        result = self._apply(svc, registry, {"videoId": "v1", "edits": [{"op": "delete", "wordId": "w0-3"}]})
        assert result["path"] == "/lib/in.mp4"
        assert result["removedSec"] == 0.0
        assert run.calls == []

    def test_apply_surfaces_an_ffmpeg_failure(self, tmp_path, settings, registry):
        svc, _ = _service(tmp_path=tmp_path, settings=settings, run=RecordingRun(code=1))
        out = svc.applyEdit({"videoId": "v1", "edits": [{"op": "delete", "wordId": "w0-3"}]}, _ctx(registry))
        job = registry.get(out["jobId"])
        job.wait(timeout=5)
        assert job.status.value == "error"
        assert "ffmpeg exit 1" in str(job.error)

    def test_apply_remaps_cues_when_supplied(self, tmp_path, settings, registry):
        svc, _ = _service(tmp_path=tmp_path, settings=settings)
        result = self._apply(
            svc,
            registry,
            {
                "videoId": "v1",
                "edits": [{"op": "delete", "wordId": "w0-3"}],
                "cues": [{"index": 1, "start": 4.0, "end": 5.0, "text": "after"}],
            },
        )
        assert result["cues"] == [{"index": 1, "start": 3.5, "end": 4.5, "text": "after"}]

    def test_apply_without_a_job_registry_raises(self, tmp_path, settings):
        svc, _ = _service(tmp_path=tmp_path, settings=settings)
        with pytest.raises(RpcError, match="no job registry"):
            svc.applyEdit({"videoId": "v1"}, _ctx(None))

    def test_second_apply_increments_the_edit_id(self, tmp_path, settings, registry):
        svc, data = _service(tmp_path=tmp_path, settings=settings)
        first = self._apply(svc, registry, {"videoId": "v1", "edits": [{"op": "delete", "wordId": "w0-3"}]})
        second = self._apply(svc, registry, {"videoId": "v1", "edits": [{"op": "delete", "wordId": "w0-1"}]})
        assert (first["editId"], second["editId"]) == ("tedit-1", "tedit-2")
        assert [e["editId"] for e in data["transcriptEdits"]] == ["tedit-1", "tedit-2"]

    def test_apply_ignores_a_corrupt_edit_history(self, tmp_path, settings, registry):
        svc, data = _service(
            tmp_path=tmp_path,
            settings=settings,
            project={"id": "p1", "transcript": _transcript(), "transcriptEdits": "not-a-list"},
        )
        result = self._apply(svc, registry, {"videoId": "v1", "edits": [{"op": "delete", "wordId": "w0-3"}]})
        assert result["editId"] == "tedit-1"
        assert len(data["transcriptEdits"]) == 1

    def test_apply_by_path_only_records_nothing_but_still_cuts(self, tmp_path, settings, registry):
        # No videoId -> no project to write a ledger entry to. The cut STILL
        # happens (silence removal needs no transcript) and editId is None, so a
        # caller cannot later "undo" an edit that was never recorded.
        run = RecordingRun()
        svc, data = _service(tmp_path=tmp_path, settings=settings, run=run)
        result = self._apply(svc, registry, {"path": "/lib/in.mp4", "removeSilence": True, "padSec": 0.0})
        assert result["path"].endswith(".edited.mp4")
        assert result["removedSec"] > 0.0
        assert result["editId"] is None
        assert len(run.calls) == 1
        assert te.EDITS_KEY not in data


class TestDefaultSeams:
    def test_default_run_is_ffmpeg_run(self):
        from media_studio import ffmpeg as _ffmpeg

        assert te._default_run() is _ffmpeg.run

    def test_default_duration_is_ffprobe_duration(self):
        from media_studio import ffmpeg as _ffmpeg

        assert te._default_duration() is _ffmpeg.ffprobe_duration

    def test_apply_uses_the_default_duration_seam_when_none(self, tmp_path, settings, registry):
        # duration=None -> the REAL ffprobe seam runs on a bogus path, throws,
        # _probe_total returns 0.0 -> pass-through (the fake run is never hit).
        run = RecordingRun()
        data = {"id": "p1", "transcript": _transcript()}
        svc = te.TranscriptEditService(
            resolver=lambda vid: "/no/such/clip.mp4",
            out_dir=tmp_path / "edited",
            load_project=lambda vid: data,
            save_project=lambda vid, payload: None,
            settings_provider=lambda: settings,
            run=run,
            duration=None,  # exercises _default_duration() + the probe-failure branch
            detect_run=detect_with(SILENCE_STDERR),
        )
        out = svc.applyEdit({"videoId": "v1", "edits": [{"op": "delete", "wordId": "w0-3"}]}, _ctx(registry))
        job = registry.get(out["jobId"])
        job.wait(timeout=5)
        assert job.result["path"] == "/no/such/clip.mp4"
        assert job.result["removedSec"] == 0.0
        assert run.calls == []

    def test_apply_uses_the_default_run_seam_when_none(self, tmp_path, settings, registry):
        # run=None -> _default_run() resolves the real ffmpeg.run; the duration
        # probe returns 0.0 first, so the pass-through short-circuits BEFORE any
        # subprocess is spawned (the seam is resolved, never invoked).
        data = {"id": "p1", "transcript": _transcript()}
        svc = te.TranscriptEditService(
            resolver=lambda vid: "/lib/in.mp4",
            out_dir=tmp_path / "edited",
            load_project=lambda vid: data,
            save_project=lambda vid, payload: None,
            settings_provider=lambda: settings,
            run=None,  # exercises _default_run()
            duration=lambda p, s=None: 0.0,
            detect_run=detect_with(""),
        )
        out = svc.applyEdit({"videoId": "v1", "edits": []}, _ctx(registry))
        job = registry.get(out["jobId"])
        job.wait(timeout=5)
        assert job.result["path"] == "/lib/in.mp4"


class TestUndoEdit:
    def _apply(self, svc, registry, params):
        out = svc.applyEdit(params, _ctx(registry))
        job = registry.get(out["jobId"])
        job.wait(timeout=5)
        return job.result

    def test_undo_pops_the_last_edit_and_restores_the_source(self, tmp_path, settings, registry):
        svc, data = _service(tmp_path=tmp_path, settings=settings)
        applied = self._apply(svc, registry, {"videoId": "v1", "edits": [{"op": "delete", "wordId": "w0-3"}]})
        out = svc.undoEdit({"videoId": "v1"}, _ctx(None))
        assert out["editId"] == "tedit-1"
        assert out["path"] == "/lib/in.mp4"  # back to the untouched ORIGINAL
        assert out["undone"]["path"] == applied["path"]
        assert data["transcriptEdits"] == []

    def test_undo_walks_back_one_edit_at_a_time(self, tmp_path, settings, registry):
        svc, data = _service(tmp_path=tmp_path, settings=settings)
        first = self._apply(svc, registry, {"videoId": "v1", "edits": [{"op": "delete", "wordId": "w0-3"}]})
        self._apply(svc, registry, {"videoId": "v1", "edits": [{"op": "delete", "wordId": "w0-1"}]})
        out = svc.undoEdit({"videoId": "v1"}, _ctx(None))
        assert out["editId"] == "tedit-2"
        assert out["path"] == first["path"]  # the previous edit is now current
        assert [e["editId"] for e in data["transcriptEdits"]] == ["tedit-1"]

    def test_undo_of_a_named_edit_id_is_honoured(self, tmp_path, settings, registry):
        svc, _ = _service(tmp_path=tmp_path, settings=settings)
        self._apply(svc, registry, {"videoId": "v1", "edits": [{"op": "delete", "wordId": "w0-3"}]})
        out = svc.undoEdit({"videoId": "v1", "editId": "tedit-1"}, _ctx(None))
        assert out["editId"] == "tedit-1"

    def test_undo_of_a_stale_edit_id_raises(self, tmp_path, settings, registry):
        svc, _ = _service(tmp_path=tmp_path, settings=settings)
        self._apply(svc, registry, {"videoId": "v1", "edits": [{"op": "delete", "wordId": "w0-3"}]})
        with pytest.raises(RpcError, match="tedit-9"):
            svc.undoEdit({"videoId": "v1", "editId": "tedit-9"}, _ctx(None))

    def test_undo_with_no_history_raises(self, tmp_path, settings):
        svc, _ = _service(tmp_path=tmp_path, settings=settings)
        with pytest.raises(RpcError, match="nothing to undo"):
            svc.undoEdit({"videoId": "v1"}, _ctx(None))

    def test_undo_requires_a_video_id(self, tmp_path, settings):
        svc, _ = _service(tmp_path=tmp_path, settings=settings)
        with pytest.raises(RpcError, match="videoId"):
            svc.undoEdit({}, _ctx(None))


# --------------------------------------------------------------------------- #
# persistence — the edit ledger must SURVIVE a manifest round-trip
# --------------------------------------------------------------------------- #
def test_transcript_edits_survive_a_project_manifest_round_trip(tmp_path):
    """A recorded edit is worthless if ``Project.open`` drops it on reload."""
    manifest = tmp_path / "project.json"
    project = lib.Project(
        {
            "id": "p1",
            "video": {"id": "v1", "path": "/lib/in.mp4"},
            "tracks": [],
            "clips": [],
            "settings": {},
            "transcriptEdits": [{"editId": "tedit-1", "path": "/out/in.edited.mp4", "sourcePath": "/lib/in.mp4"}],
        },
        manifest_path=manifest,
    )
    project.save()
    reopened = lib.Project.open(manifest)
    assert reopened.data["transcriptEdits"] == [
        {"editId": "tedit-1", "path": "/out/in.edited.mp4", "sourcePath": "/lib/in.mp4"}
    ]


def test_project_without_transcript_edits_omits_the_key(tmp_path):
    manifest = tmp_path / "project.json"
    lib.Project(
        {"id": "p1", "video": {}, "tracks": [], "clips": [], "settings": {}},
        manifest_path=manifest,
    ).save()
    assert "transcriptEdits" not in lib.Project.open(manifest).data


# --------------------------------------------------------------------------- #
# registration
# --------------------------------------------------------------------------- #
def test_register_binds_the_four_transcript_methods(tmp_path, settings):
    seen: dict[str, Any] = {}
    svc = te.register(
        resolver=lambda vid: "/lib/in.mp4",
        out_dir=tmp_path / "edited",
        load_project=lambda vid: {"transcript": _transcript()},
        save_project=lambda vid, payload: None,
        settings_provider=lambda: settings,
        run=RecordingRun(),
        duration=lambda p, s=None: 10.0,
        detect_run=detect_with(""),
        register_fn=lambda name, fn: seen.__setitem__(name, fn),
    )
    assert sorted(seen) == [
        "transcript.applyEdit",
        "transcript.get",
        "transcript.previewEdit",
        "transcript.undoEdit",
    ]
    assert seen["transcript.get"].__self__ is svc


def test_register_defaults_to_the_real_protocol_registrar(tmp_path, settings, monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(protocol, "register", lambda name, fn: calls.append(name))
    te.register(
        resolver=lambda vid: "/lib/in.mp4",
        out_dir=tmp_path / "edited",
        load_project=lambda vid: {},
        save_project=lambda vid, payload: None,
    )
    assert "transcript.applyEdit" in calls
