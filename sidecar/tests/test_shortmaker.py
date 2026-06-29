"""Unit tests for the short-maker orchestrator (features/shortmaker.py).

These tests are deliberately heavy-ML-free: every stage (select / boundary /
cut / reframe / caption / export) is mocked at the :class:`Stages` seam, so no
provider / whisper / verthor / scenedetect / ffmpeg import ever happens. They
assert:

  * the pipeline ORDER (select -> snap on SELECT; cut -> reframe -> caption ->
    export on EXPORT, per CONTRACTS.md §5);
  * ``sourceStart`` PROPAGATION from the snapped candidate all the way to the
    caption stage (§3/§4 — captions re-base by subtracting sourceStart);
  * every DEGENERATE path (no speech, zero candidates, too few candidates, a
    candidate with no valid boundary, and the verthor no-subject center-crop
    fallback as exercised through the reframe seam);
  * the RPC handlers (shortmaker.select / shortmaker.export) start jobs and
    return ``{jobId}`` per §2.

The snap seam mirrors the as-built boundary unit: a BATCH call returning
``(kept, dropped)`` where dropped entries are ``{"candidate", "reason"}``.
"""

from __future__ import annotations

import json
import threading
from typing import Any

import pytest
from media_studio import protocol
from media_studio.features import shortmaker as sm
from media_studio.features import shorts as shorts_mod
from media_studio.jobs import JobCancelled, JobContext, JobRegistry
from media_studio.protocol import RpcContext, RpcError


# ---------------------------------------------------------------------------
# test doubles
# ---------------------------------------------------------------------------
class RecordingStages:
    """A Stages-compatible recorder.

    Logs each stage call into ``calls`` (a shared, ordered list) so tests can
    assert the exact pipeline order, and captures the kwargs passed to caption
    (to verify ``source_start`` propagation).
    """

    def __init__(
        self,
        calls: list[str],
        *,
        select_return: list[dict[str, Any]] | None = None,
        snap_impl=None,
        reframe_impl=None,
        filler_impl=None,
        trim_impl=None,
        stabilize_impl=None,
        reframe_notice=None,
        trim_notice=None,
    ):
        self.calls = calls
        self._reframe_notice = reframe_notice
        self._trim_notice = trim_notice
        self._select_return = select_return if select_return is not None else []
        self._snap_impl = snap_impl
        self._reframe_impl = reframe_impl
        self._filler_impl = filler_impl
        self._trim_impl = trim_impl
        self._stabilize_impl = stabilize_impl
        self.caption_kwargs: list[dict[str, Any]] = []
        self.cut_args: list[tuple] = []
        self.mux_kwargs: list[dict[str, Any]] = []
        self.filler_kwargs: list[dict[str, Any]] = []
        self.zoom_kwargs: list[dict[str, Any]] = []
        self.brand_kwargs: list[dict[str, Any]] = []
        self.trim_args: list[tuple] = []
        self.stabilize_args: list[tuple] = []

    def as_stages(self) -> sm.Stages:
        return sm.Stages(
            select_candidates=self.select_candidates,
            snap_candidates=self.snap_candidates,
            cut_clip=self.cut_clip,
            trim_silence=self.trim_silence,
            stabilize=self.stabilize,
            remove_fillers=self.remove_fillers,
            reframe=self.reframe,
            apply_zoom=self.apply_zoom,
            render_caption=self.render_caption,
            export_clip=self.export_clip,
            brand_overlay=self.brand_overlay,
            mux_audio=self.mux_audio,
        )

    # -- audio-stabilize group stages --------------------------------------
    def trim_silence(self, in_path, out_path, *, settings=None, on_notice=None):
        self.calls.append("trim_silence")
        self.trim_args.append((in_path, out_path))
        if self._trim_notice is not None and on_notice is not None:
            on_notice(self._trim_notice)
        if self._trim_impl is not None:
            return self._trim_impl(in_path, out_path)
        # Default stub: "removed 2.5s of dead air", returns the new path + keeps.
        # The default keeps cover the whole clip (no interior removal to remap), so
        # the base ordering tests stay timeline-neutral.
        return out_path, 2.5, [(0.0, 30.0)]

    def stabilize(self, in_path, out_path, *, settings=None, on_notice=None):
        self.calls.append("stabilize")
        self.stabilize_args.append((in_path, out_path))
        if self._stabilize_impl is not None:
            return self._stabilize_impl(in_path, out_path, on_notice)
        return out_path

    # -- SELECT phase ------------------------------------------------------
    def select_candidates(self, transcript, prompt, controls, *, settings=None):
        self.calls.append("select")
        return list(self._select_return)

    def snap_candidates(self, candidates, transcript, *, controls=None, settings=None):
        self.calls.append("snap")
        self.snap_controls = controls
        if self._snap_impl is not None:
            return self._snap_impl(list(candidates))
        # Default: a no-op pass-through snap that fixes sourceStart=start and
        # drops nothing.
        kept = []
        for c in candidates:
            out = dict(c)
            out["sourceStart"] = out["start"]
            kept.append(out)
        return kept, []

    # -- EXPORT phase ------------------------------------------------------
    def cut_clip(self, in_path, out_path, start, end, *, settings=None):
        self.calls.append("cut")
        self.cut_args.append((in_path, out_path, start, end))
        return out_path

    def remove_fillers(self, in_path, out_path, words, cues, *, lang=None, settings=None):
        self.calls.append("remove_fillers")
        self.filler_kwargs.append(
            {
                "in_path": in_path,
                "out_path": out_path,
                "words": words,
                "cues": cues,
                "lang": lang,
            }
        )
        if self._filler_impl is not None:
            return self._filler_impl(in_path, out_path, words, cues)
        # Default: a stub that "removes one filler word", returns the cues
        # unchanged (mock), and reports deterministic stats.
        stats = {"fillersRemoved": 1, "fillerSeconds": 0.4}
        return out_path, list(cues), stats

    def reframe(self, in_path, out_path, aspect, *, settings=None, on_notice=None):
        self.calls.append("reframe")
        if self._reframe_notice is not None and on_notice is not None:
            on_notice(self._reframe_notice)
        if self._reframe_impl is not None:
            return self._reframe_impl(in_path, out_path, aspect)
        return out_path

    def apply_zoom(self, in_path, out_path, cues, *, source_start, duration_sec, settings=None):
        self.calls.append("zoom")
        self.zoom_kwargs.append(
            {
                "in_path": in_path,
                "out_path": out_path,
                "cues": cues,
                "source_start": source_start,
                "duration_sec": duration_sec,
            }
        )
        return out_path

    def brand_overlay(self, in_path, out_path, logo_path, *, settings=None):
        self.calls.append("brand_overlay")
        self.brand_kwargs.append({"in_path": in_path, "out_path": out_path, "logo_path": logo_path})
        return out_path

    def render_caption(
        self,
        clip_path,
        cues,
        out_path,
        *,
        source_start,
        burn,
        width,
        height,
        settings=None,
        hook_title=None,
        hook_card=False,
        hook_card_sec=0.0,
    ):
        self.calls.append("caption")
        self.caption_kwargs.append(
            {
                "clip_path": clip_path,
                "cues": cues,
                "out_path": out_path,
                "source_start": source_start,
                "burn": burn,
                "width": width,
                "height": height,
                "hook_title": hook_title,
                "hook_card": hook_card,
                "hook_card_sec": hook_card_sec,
                "settings": settings,
            }
        )
        return out_path

    def export_clip(self, in_path, out_path, *, settings=None):
        self.calls.append("export")
        return out_path

    def mux_audio(self, clip_path, audio_track, out_path, *, start, end, settings=None):
        self.calls.append("mux_audio")
        self.mux_kwargs.append(
            {
                "clip_path": clip_path,
                "audio_track": audio_track,
                "out_path": out_path,
                "start": start,
                "end": end,
            }
        )
        return out_path


def make_ctx(job_id: str = "t-1") -> JobContext:
    """A standalone JobContext that records progress into ``progress_log``."""
    log: list[tuple] = []

    def emit(jid, pct, msg):
        log.append((jid, pct, msg))

    ctx = JobContext(job_id=job_id, _cancel_event=threading.Event(), _emit_progress=emit)
    ctx.progress_log = log  # type: ignore[attr-defined]
    return ctx


def drop_only(_candidates):
    """A snap_impl that drops every candidate (no valid boundary)."""
    dropped = [{"candidate": c, "reason": "no valid boundary"} for c in _candidates]
    return [], dropped


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------
@pytest.fixture()
def transcript() -> dict[str, Any]:
    """A small transcript with word timing spanning ~0-60s."""
    return {
        "language": "en",
        "durationSec": 60.0,
        "segments": [
            {
                "start": 0.0,
                "end": 30.0,
                "text": "people don't buy what you do",
                "words": [
                    {"text": "people", "start": 5.0, "end": 5.5},
                    {"text": "buy", "start": 25.0, "end": 25.4},
                ],
            },
            {
                "start": 30.0,
                "end": 60.0,
                "text": "they buy why you do it",
                "words": [
                    {"text": "why", "start": 40.0, "end": 40.5},
                ],
            },
        ],
    }


@pytest.fixture()
def empty_transcript() -> dict[str, Any]:
    """A no-speech transcript (segments present but all blank text)."""
    return {
        "language": "en",
        "durationSec": 10.0,
        "segments": [{"start": 0.0, "end": 10.0, "text": "   ", "words": []}],
    }


@pytest.fixture()
def two_candidates() -> list[dict[str, Any]]:
    return [
        {"rank": 1, "start": 10.0, "end": 40.0, "hook": "a", "why": "x", "score": 90},
        {"rank": 2, "start": 41.0, "end": 58.0, "hook": "b", "why": "y", "score": 80},
    ]


def loader_for(path: str, transcript: dict[str, Any] | None, **extra):
    """Build a ContextLoader returning a fixed context dict."""

    def _load(video_id: str) -> dict[str, Any]:
        ctx = {"path": path, "transcript": transcript}
        ctx.update(extra)
        return ctx

    return _load


# ---------------------------------------------------------------------------
# SELECT phase — happy path + ORDER
# ---------------------------------------------------------------------------
def test_run_select_orders_select_then_snap(transcript, two_candidates):
    calls: list[str] = []
    rec = RecordingStages(calls, select_return=two_candidates)
    out = sm.run_select(
        make_ctx(),
        video_id="v1",
        prompt="best clips",
        controls={"count": 2},
        load_context=loader_for("/src.mp4", transcript),
        stages=rec.as_stages(),
    )
    # select runs once, then snap runs once (batch).
    assert calls == ["select", "snap"]
    assert len(out["candidates"]) == 2
    assert "reason" not in out


def test_run_select_normalizes_full_candidate_schema(transcript):
    """Every §3 Candidate field is present + typed, incl. sourceStart."""
    calls: list[str] = []
    rec = RecordingStages(
        calls,
        select_return=[{"start": 10.0, "end": 35.0, "hook": "h", "score": 88}],
    )
    out = sm.run_select(
        make_ctx(),
        video_id="v1",
        prompt="p",
        controls={"count": 1},
        load_context=loader_for("/src.mp4", transcript),
        stages=rec.as_stages(),
    )
    cand = out["candidates"][0]
    for key in ("rank", "start", "end", "durationSec", "hook", "why", "score", "sourceStart"):
        assert key in cand
    assert cand["durationSec"] == pytest.approx(25.0)  # end - start when omitted
    assert isinstance(cand["score"], int)
    assert cand["sourceStart"] == pytest.approx(10.0)  # snap set it to start


def test_run_select_passes_coerced_candidates_to_snap(transcript):
    """select output is normalized to full §3 candidates BEFORE snap sees them."""
    seen: dict[str, Any] = {}

    def snap_impl(cands):
        seen["candidates"] = cands
        return cands, []

    rec = RecordingStages(
        [],
        select_return=[{"start": 1.0, "end": 25.0}],  # missing rank/score/hook
        snap_impl=snap_impl,
    )
    sm.run_select(
        make_ctx(),
        video_id="v1",
        prompt="p",
        controls={"count": 1},
        load_context=loader_for("/src.mp4", transcript),
        stages=rec.as_stages(),
    )
    passed = seen["candidates"][0]
    assert passed["rank"] == 1 and passed["score"] == 0 and "sourceStart" in passed


# ---------------------------------------------------------------------------
# SELECT phase — durationMode threads SELECT<->BOUNDARY (V1.1 WU SEL1)
# ---------------------------------------------------------------------------
def _long_clip_transcript(span_sec: float = 155.0) -> dict[str, Any]:
    """A transcript whose words span ~0..span_sec with NO sentence punctuation.

    With no sentence terminators the only boundary targets are the injected
    silences, so a long-clip request snaps cleanly to a single silence pair —
    the same shape the boundary-unit mid-form test uses, lifted to the pipeline.
    """
    words = [{"text": "w", "start": float(i), "end": float(i) + 0.5} for i in range(int(span_sec))]
    return {
        "language": "en",
        "durationSec": span_sec,
        "segments": [
            {"start": 0.0, "end": span_sec, "text": "w " * int(span_sec), "words": words},
        ],
    }


def _long_clip_select(*_args, **_kwargs):
    """A SELECT stage that emits ONE ~150 s mid-form candidate (too long for 20-60)."""
    return [{"rank": 1, "start": 0.1, "end": 150.5, "hook": "h", "why": "w", "score": 95}]


def test_run_select_midform_keeps_long_clip_through_pipeline():
    """SEL1 BLOCKER fix: durationMode='midform' survives SELECT -> BOUNDARY-SNAP.

    Uses the REAL default ``snap_candidates`` (``_lazy_snap``) so the wiring from
    controls into ``boundary.snap_from_lists`` is exercised end-to-end — not the
    in-isolation unit. A 150 s clip would be dropped under the standard 20-60
    window; the mid-form envelope (16-180 s) must keep it WHOLE.
    """
    stages = sm.Stages(select_candidates=_long_clip_select)
    out = sm.run_select(
        make_ctx(),
        video_id="v1",
        prompt="best clips",
        controls={"durationMode": "midform", "count": 1},
        load_context=loader_for("/src.mp4", _long_clip_transcript()),
        stages=stages,
        settings={"silences": [0.0, 150.0]},
    )
    assert "reason" not in out
    assert len(out["candidates"]) == 1
    cand = out["candidates"][0]
    assert cand["start"] == pytest.approx(0.0)
    assert cand["end"] == pytest.approx(150.0)
    assert cand["durationSec"] == pytest.approx(150.0)


def test_run_select_standard_drops_long_clip_through_pipeline():
    """Control for the SEL1 fix: the SAME long clip is DROPPED under standard.

    Locks the SELECT<->BOUNDARY envelope agreement — if the mid-form window
    leaked into the standard path (or vice versa) one of these two asserts breaks.
    """
    stages = sm.Stages(select_candidates=_long_clip_select)
    out = sm.run_select(
        make_ctx(),
        video_id="v1",
        prompt="best clips",
        controls={"durationMode": "standard", "count": 1},
        load_context=loader_for("/src.mp4", _long_clip_transcript()),
        stages=stages,
        settings={"silences": [0.0, 150.0]},
    )
    assert out["candidates"] == []
    assert out["reason"] == "no clips"


# ---------------------------------------------------------------------------
# SELECT phase — DEGENERATE paths
# ---------------------------------------------------------------------------
def test_run_select_no_speech_gives_no_clips(empty_transcript):
    calls: list[str] = []
    rec = RecordingStages(calls, select_return=[{"start": 0, "end": 30}])
    out = sm.run_select(
        make_ctx(),
        video_id="v1",
        prompt="p",
        controls={},
        load_context=loader_for("/src.mp4", empty_transcript),
        stages=rec.as_stages(),
    )
    assert out["candidates"] == []
    assert out["reason"] == "no clips"
    # select must NOT even be called when there's no speech.
    assert calls == []


def test_run_select_missing_transcript_gives_no_clips():
    calls: list[str] = []
    rec = RecordingStages(calls)
    out = sm.run_select(
        make_ctx(),
        video_id="v1",
        prompt="p",
        controls={},
        load_context=loader_for("/src.mp4", None),
        stages=rec.as_stages(),
    )
    assert out["candidates"] == []
    assert out["reason"] == "no clips"
    assert calls == []


def test_run_select_zero_candidates_gives_reason(transcript):
    calls: list[str] = []
    rec = RecordingStages(calls, select_return=[])  # select returns nothing
    out = sm.run_select(
        make_ctx(),
        video_id="v1",
        prompt="p",
        controls={"count": 5},
        load_context=loader_for("/src.mp4", transcript),
        stages=rec.as_stages(),
    )
    assert out["candidates"] == []
    assert out["reason"] == "no candidates"
    assert calls == ["select"]  # tried select, no snap


def test_run_select_too_few_candidates_gives_reason(transcript, two_candidates):
    calls: list[str] = []
    rec = RecordingStages(calls, select_return=two_candidates)
    out = sm.run_select(
        make_ctx(),
        video_id="v1",
        prompt="p",
        controls={"count": 5},  # asked for 5, only 2 produced
        load_context=loader_for("/src.mp4", transcript),
        stages=rec.as_stages(),
    )
    assert len(out["candidates"]) == 2
    assert out["reason"] == "too few candidates"


def test_run_select_drops_candidate_with_no_valid_boundary(transcript, two_candidates):
    """A candidate dropped by snap is surfaced with a per-candidate reason."""

    def snap_impl(cands):
        kept, dropped = [], []
        for c in cands:
            if c["rank"] == 2:  # rank-2 has no valid boundary
                dropped.append({"candidate": c, "reason": "no valid boundary"})
            else:
                out = dict(c)
                out["sourceStart"] = out["start"]
                kept.append(out)
        return kept, dropped

    rec = RecordingStages([], select_return=two_candidates, snap_impl=snap_impl)
    out = sm.run_select(
        make_ctx(),
        video_id="v1",
        prompt="p",
        controls={"count": 2},
        load_context=loader_for("/src.mp4", transcript),
        stages=rec.as_stages(),
    )
    assert len(out["candidates"]) == 1
    assert out["candidates"][0]["hook"] == "a"
    assert "dropped" in out
    assert out["dropped"][0]["reason"] == "no valid boundary"
    assert out["dropped"][0]["rank"] == 2
    assert out["dropped"][0]["hook"] == "b"


def test_run_select_all_dropped_gives_no_clips(transcript, two_candidates):
    rec = RecordingStages([], select_return=two_candidates, snap_impl=drop_only)
    out = sm.run_select(
        make_ctx(),
        video_id="v1",
        prompt="p",
        controls={"count": 2},
        load_context=loader_for("/src.mp4", transcript),
        stages=rec.as_stages(),
    )
    assert out["candidates"] == []
    assert out["reason"] == "no clips"
    assert len(out["dropped"]) == 2


def test_drop_record_handles_non_dict():
    assert sm._drop_record("boom") == {"reason": "boom"}


# ---------------------------------------------------------------------------
# EXPORT phase — ORDER + sourceStart propagation
# ---------------------------------------------------------------------------
def test_run_export_orders_cut_reframe_caption_export(transcript, tmp_path):
    calls: list[str] = []
    rec = RecordingStages(calls)
    candidate = {
        "rank": 1,
        "start": 10.0,
        "end": 40.0,
        "durationSec": 30.0,
        "hook": "h",
        "why": "w",
        "score": 90,
        "sourceStart": 10.0,
    }
    out = sm.run_export(
        make_ctx(),
        video_id="v1",
        candidates=[candidate],
        load_context=loader_for(str(tmp_path / "src.mp4"), transcript),
        out_dir=str(tmp_path / "out"),
        stages=rec.as_stages(),
    )
    # Exact §5 order for a single clip.
    assert calls == ["cut", "stabilize", "reframe", "caption", "export"]
    assert out["clips"] == [{"path": str(tmp_path / "out" / "01-src.mp4")}]


def _one_candidate() -> dict:
    return {"rank": 1, "start": 10.0, "end": 40.0, "durationSec": 30.0, "hook": "h", "sourceStart": 10.0}


def test_run_export_skips_notice_when_engine_resolves_clean(transcript, tmp_path, monkeypatch):
    # resolve_engine_name's notice is OS-dependent (verthor/WSL availability), so
    # pin it: no notice -> run_export takes the no-progress arc deterministically.
    monkeypatch.setattr(
        "media_studio.features.reframe.resolve_engine_name",
        lambda _requested, _settings: ("verthor", None),
    )
    ctx = make_ctx()
    out = sm.run_export(
        ctx,
        video_id="v1",
        candidates=[_one_candidate()],
        load_context=loader_for(str(tmp_path / "src.mp4"), transcript),
        out_dir=str(tmp_path / "out"),
        stages=RecordingStages([]).as_stages(),
    )
    assert out["clips"]
    assert all("verthor" not in str(msg).lower() for _, _, msg in ctx.progress_log)


def test_run_export_propagates_sourceStart_to_caption(transcript, tmp_path):
    """The candidate's sourceStart is handed to the caption stage (re-base seam)."""
    rec = RecordingStages([])
    candidate = {
        "rank": 3,
        "start": 12.5,
        "end": 50.0,
        "durationSec": 37.5,
        "hook": "h",
        "why": "w",
        "score": 77,
        "sourceStart": 12.5,
    }
    sm.run_export(
        make_ctx(),
        video_id="v1",
        candidates=[candidate],
        load_context=loader_for(str(tmp_path / "src.mp4"), transcript),
        out_dir=str(tmp_path / "out"),
        stages=rec.as_stages(),
    )
    assert len(rec.caption_kwargs) == 1
    cap = rec.caption_kwargs[0]
    assert cap["source_start"] == pytest.approx(12.5)
    assert cap["burn"] is True
    assert cap["width"] == sm.OUT_WIDTH == 1080
    assert cap["height"] == sm.OUT_HEIGHT == 1920


def test_run_export_cut_uses_sourceStart_and_end(transcript, tmp_path):
    rec = RecordingStages([])
    candidate = {
        "rank": 1,
        "start": 99.0,
        "end": 130.0,
        "sourceStart": 100.0,
        "score": 1,
    }
    sm.run_export(
        make_ctx(),
        video_id="v1",
        candidates=[candidate],
        load_context=loader_for(str(tmp_path / "src.mp4"), transcript),
        out_dir=str(tmp_path / "out"),
        stages=rec.as_stages(),
    )
    # cut carves [sourceStart, end), not [start, end).
    _in, _out, start, end = rec.cut_args[0]
    assert start == pytest.approx(100.0)
    assert end == pytest.approx(130.0)


def test_run_export_caption_cues_only_overlap_clip(transcript, tmp_path):
    """Cues handed to caption are limited to the clip's source window."""
    rec = RecordingStages([])
    # Clip window [20, 45): only the "buy" (25.0) and "why" (40.0) words overlap.
    candidate = {"rank": 1, "start": 20.0, "end": 45.0, "sourceStart": 20.0, "score": 9}
    sm.run_export(
        make_ctx(),
        video_id="v1",
        candidates=[candidate],
        load_context=loader_for(str(tmp_path / "src.mp4"), transcript),
        out_dir=str(tmp_path / "out"),
        stages=rec.as_stages(),
    )
    cues = rec.caption_kwargs[0]["cues"]
    texts = [c["text"] for c in cues]
    assert "buy" in texts
    assert "why" in texts
    assert "people" not in texts  # 5.0s is before the clip window


def _emphasis_transcript() -> dict[str, Any]:
    """Transcript whose words trigger §8a emphasis (keyword + number)."""
    return {
        "language": "en",
        "durationSec": 60.0,
        "segments": [
            {
                "start": 0.0,
                "end": 30.0,
                "text": "the secret made 100x",
                "words": [
                    {"text": "the", "start": 5.0, "end": 5.3},
                    {"text": "secret", "start": 6.0, "end": 6.6},
                    {"text": "made", "start": 7.0, "end": 7.4},
                    {"text": "100x", "start": 8.0, "end": 8.5},
                ],
            },
        ],
    }


def test_run_export_annotates_cues_with_emphasis_when_on(tmp_path):
    """§8a: with emphasis ON (OpusClip-style template) the cues handed to caption
    carry per-cue emphasis spans + (where applicable) a trailing emoji."""
    rec = RecordingStages([])
    candidate = {"rank": 1, "start": 0.0, "end": 30.0, "sourceStart": 0.0, "score": 9}
    sm.run_export(
        make_ctx(),
        video_id="v1",
        candidates=[candidate],
        load_context=loader_for(str(tmp_path / "src.mp4"), _emphasis_transcript()),
        out_dir=str(tmp_path / "out"),
        stages=rec.as_stages(),
        settings={"captionStyle": "hormozi"},  # OpusClip-style -> emphasis ON
    )
    cues = rec.caption_kwargs[0]["cues"]
    by_text = {c["text"]: c for c in cues}
    # "secret" is a keyword; "100x" contains a digit -> both emphasised.
    assert by_text["secret"]["emphasis"] and by_text["secret"]["emphasis"][0]["kind"] == "keyword"
    assert by_text["100x"]["emphasis"] and by_text["100x"]["emphasis"][0]["kind"] == "number"
    # "secret" maps to a trailing emoji (deterministic).
    assert by_text["secret"]["emoji"]


def test_run_export_emphasis_off_for_clean_template(tmp_path):
    """§8a: a clean/minimal template defaults emphasis OFF (empty spans/emoji)."""
    rec = RecordingStages([])
    candidate = {"rank": 1, "start": 0.0, "end": 30.0, "sourceStart": 0.0, "score": 9}
    sm.run_export(
        make_ctx(),
        video_id="v1",
        candidates=[candidate],
        load_context=loader_for(str(tmp_path / "src.mp4"), _emphasis_transcript()),
        out_dir=str(tmp_path / "out"),
        stages=rec.as_stages(),
        settings={"captionStyle": "clean"},  # clean -> emphasis OFF
    )
    cues = rec.caption_kwargs[0]["cues"]
    assert all(c["emphasis"] == [] and c["emoji"] == "" for c in cues)


def test_run_export_emphasis_explicit_flag_overrides_style_default(tmp_path):
    """An explicit emphasis=False beats an OpusClip style's ON default."""
    rec = RecordingStages([])
    candidate = {"rank": 1, "start": 0.0, "end": 30.0, "sourceStart": 0.0, "score": 9}
    sm.run_export(
        make_ctx(),
        video_id="v1",
        candidates=[candidate],
        load_context=loader_for(str(tmp_path / "src.mp4"), _emphasis_transcript()),
        out_dir=str(tmp_path / "out"),
        stages=rec.as_stages(),
        settings={"captionStyle": "hormozi", "emphasis": False},
    )
    cues = rec.caption_kwargs[0]["cues"]
    assert all(c["emphasis"] == [] and c["emoji"] == "" for c in cues)


# ---------------------------------------------------------------------------
# §8b auto punch-in zoom — the stage is wired between reframe and caption (C16)
# ---------------------------------------------------------------------------
def test_run_export_zoom_off_by_default(transcript, tmp_path):
    """autoZoom defaults OFF: the zoom stage never runs, order is unchanged."""
    calls: list[str] = []
    rec = RecordingStages(calls)
    candidate = {"rank": 1, "start": 0.0, "end": 30.0, "sourceStart": 0.0, "score": 9}
    sm.run_export(
        make_ctx(),
        video_id="v1",
        candidates=[candidate],
        load_context=loader_for(str(tmp_path / "src.mp4"), transcript),
        out_dir=str(tmp_path / "out"),
        stages=rec.as_stages(),
    )
    assert "zoom" not in calls
    assert calls == ["cut", "stabilize", "reframe", "caption", "export"]
    assert rec.zoom_kwargs == []


def test_run_export_zoom_inserted_between_reframe_and_caption(transcript, tmp_path):
    """autoZoom ON: zoom runs AFTER reframe and BEFORE caption (the proven order)."""
    calls: list[str] = []
    rec = RecordingStages(calls)
    candidate = {"rank": 1, "start": 10.0, "end": 40.0, "sourceStart": 10.0, "score": 9}
    sm.run_export(
        make_ctx(),
        video_id="v1",
        candidates=[candidate],
        load_context=loader_for(str(tmp_path / "src.mp4"), transcript),
        out_dir=str(tmp_path / "out"),
        stages=rec.as_stages(),
        settings={"autoZoom": True},
    )
    assert calls == ["cut", "stabilize", "reframe", "zoom", "caption", "export"]
    # The zoom stage consumes the reframed clip and feeds caption its output.
    z = rec.zoom_kwargs[0]
    assert z["in_path"].endswith(".reframed.mp4")
    assert z["out_path"].endswith(".zoomed.mp4")
    # Caption then runs on the ZOOMED clip (not the bare reframed one).
    assert rec.caption_kwargs[0]["clip_path"] == z["out_path"]


def test_run_export_zoom_passes_cues_and_duration(transcript, tmp_path):
    """The zoom stage receives the clip's cues + window for sentence-start beats."""
    rec = RecordingStages([])
    candidate = {"rank": 1, "start": 10.0, "end": 40.0, "sourceStart": 10.0, "score": 9}
    sm.run_export(
        make_ctx(),
        video_id="v1",
        candidates=[candidate],
        load_context=loader_for(str(tmp_path / "src.mp4"), transcript),
        out_dir=str(tmp_path / "out"),
        stages=rec.as_stages(),
        settings={"autoZoom": True},
    )
    z = rec.zoom_kwargs[0]
    # duration = end - sourceStart; source_start is the caption re-base (no fillers
    # -> the candidate's sourceStart).
    assert z["duration_sec"] == pytest.approx(30.0)
    assert z["source_start"] == pytest.approx(10.0)
    assert isinstance(z["cues"], list)


# ---------------------------------------------------------------------------
# audio-stabilize group — silence-trim + stabilize pre-steps (after CUT)
# ---------------------------------------------------------------------------
def _stab_candidate() -> dict[str, Any]:
    return {"rank": 1, "start": 0.0, "end": 30.0, "sourceStart": 0.0, "score": 9}


def test_run_export_stabilize_on_by_default(transcript, tmp_path):
    """No toggle set: stabilize is DEFAULT-ON in the reframe path (it runs after
    cut, before reframe); silence-trim stays off (it remains opt-in)."""
    calls: list[str] = []
    rec = RecordingStages(calls)
    sm.run_export(
        make_ctx(),
        video_id="v1",
        candidates=[_stab_candidate()],
        load_context=loader_for(str(tmp_path / "src.mp4"), transcript),
        out_dir=str(tmp_path / "out"),
        stages=rec.as_stages(),
    )
    assert "trim_silence" not in calls  # silence-trim is still opt-in
    assert "stabilize" in calls  # stabilization is now default-on
    assert calls == ["cut", "stabilize", "reframe", "caption", "export"]


def test_run_export_stabilize_disabled_by_explicit_false(transcript, tmp_path):
    """An EXPLICIT ``stabilize: False`` disables the default-on stabilization."""
    calls: list[str] = []
    rec = RecordingStages(calls)
    sm.run_export(
        make_ctx(),
        video_id="v1",
        candidates=[_stab_candidate()],
        load_context=loader_for(str(tmp_path / "src.mp4"), transcript),
        out_dir=str(tmp_path / "out"),
        stages=rec.as_stages(),
        settings={"stabilize": False},
    )
    assert "stabilize" not in calls
    assert calls == ["cut", "reframe", "caption", "export"]


def test_run_export_silence_trim_runs_after_cut(transcript, tmp_path):
    """silenceTrim ON: trim runs on the cut clip, BEFORE reframe."""
    calls: list[str] = []
    rec = RecordingStages(calls)
    out = sm.run_export(
        make_ctx(),
        video_id="v1",
        candidates=[_stab_candidate()],
        load_context=loader_for(str(tmp_path / "src.mp4"), transcript),
        out_dir=str(tmp_path / "out"),
        stages=rec.as_stages(),
        settings={"silenceTrim": True},
    )
    assert calls == ["cut", "trim_silence", "stabilize", "reframe", "caption", "export"]
    # The trimmed clip (not the raw cut) is what reframe receives.
    trimmed_out = rec.trim_args[0][1]
    # silenceRemovedSec is surfaced on the clip payload (default stub removed 2.5s).
    assert out["items"][0]["silenceRemovedSec"] == pytest.approx(2.5)
    assert trimmed_out.endswith(".trimmed.mp4")


def test_run_export_silence_trim_remaps_caption_cues(tmp_path):
    """BUG FIX: trimming interior silence MUST remap caption cues to the new timeline.

    A candidate [sourceStart=0, end=30] with two cues — one BEFORE the removed
    silence and one AFTER. Silence-trim removes the interior span [6, 16) (10s),
    so the kept clip-local timeline is [(0,6), (16,30)]. The cue after the gap must
    shift earlier by the removed 10s; without remapping it would drift by 10s and
    the captions would desync. The caption stage must receive clip-local cues and
    ``source_start == 0`` (already re-based), exactly like the remove-fillers path.
    """
    calls: list[str] = []
    # Cues in ORIGINAL-video time (sourceStart=0 so they are already clip-local):
    #   cue1 [2,4]  (before the removed silence) -> stays [2,4]
    #   cue2 [20,22] (after a 10s removal at [6,16)) -> shifts to [10,12]
    cue_transcript = {
        "language": "en",
        "durationSec": 30.0,
        "segments": [
            {
                "start": 0.0,
                "end": 30.0,
                "text": "intro then outro",
                "words": [
                    {"text": "intro", "start": 2.0, "end": 4.0},
                    {"text": "outro", "start": 20.0, "end": 22.0},
                ],
            }
        ],
    }

    def trim_impl(in_path, out_path):
        # Removed interior silence [6,16): keeps the talking parts around it.
        return out_path, 10.0, [(0.0, 6.0), (16.0, 30.0)]

    rec = RecordingStages(calls, trim_impl=trim_impl)
    sm.run_export(
        make_ctx(),
        video_id="v1",
        candidates=[_stab_candidate()],
        load_context=loader_for(str(tmp_path / "src.mp4"), cue_transcript),
        out_dir=str(tmp_path / "out"),
        stages=rec.as_stages(),
        settings={"silenceTrim": True},
    )
    cap = rec.caption_kwargs[0]
    # The clip is already clip-local after the remap, so the caption re-base is 0.
    assert cap["source_start"] == pytest.approx(0.0)
    remapped = {(round(c["start"], 3), round(c["end"], 3)) for c in cap["cues"]}
    # cue1 unchanged; cue2 pulled 10s earlier onto the compacted timeline.
    assert remapped == {(2.0, 4.0), (10.0, 12.0)}


def test_run_export_stabilize_runs_after_cut_warp_only(transcript, tmp_path):
    """stabilize ON: stabilize runs after CUT, BEFORE reframe; timeline unchanged."""
    calls: list[str] = []
    rec = RecordingStages(calls)
    sm.run_export(
        make_ctx(),
        video_id="v1",
        candidates=[_stab_candidate()],
        load_context=loader_for(str(tmp_path / "src.mp4"), transcript),
        out_dir=str(tmp_path / "out"),
        stages=rec.as_stages(),
        settings={"stabilize": True},
    )
    assert calls == ["cut", "stabilize", "reframe", "caption", "export"]
    assert rec.stabilize_args[0][1].endswith(".stabilized.mp4")


def test_run_export_trim_then_stabilize_compose(transcript, tmp_path):
    """Both ON: trim FIRST (timeline edit), then stabilize (warp) on its output."""
    calls: list[str] = []
    rec = RecordingStages(calls)
    sm.run_export(
        make_ctx(),
        video_id="v1",
        candidates=[_stab_candidate()],
        load_context=loader_for(str(tmp_path / "src.mp4"), transcript),
        out_dir=str(tmp_path / "out"),
        stages=rec.as_stages(),
        settings={"silenceTrim": True, "stabilize": True},
    )
    assert calls == ["cut", "trim_silence", "stabilize", "reframe", "caption", "export"]
    # Stabilize consumes the TRIMMED clip (composition), not the raw cut.
    assert rec.stabilize_args[0][0] == rec.trim_args[0][1]


def test_run_export_stabilize_unavailable_notice_surfaced(transcript, tmp_path):
    """A missing libvidstab passes the clip through + surfaces the typed notice."""
    calls: list[str] = []
    progress: list[tuple[int, str]] = []

    def passthrough(in_path, out_path, on_notice):
        # Mimic stabilize_clip's unavailable branch: notify + return the input.
        if on_notice is not None:
            on_notice({"type": "stabilize.unavailable", "message": "no libvidstab — skipped"})
        return in_path

    rec = RecordingStages(calls, stabilize_impl=passthrough)
    ctx = JobContext(
        job_id="j1",
        _cancel_event=threading.Event(),
        _emit_progress=lambda jid, pct, msg: progress.append((pct, msg)),
    )
    sm.run_export(
        ctx,
        video_id="v1",
        candidates=[_stab_candidate()],
        load_context=loader_for(str(tmp_path / "src.mp4"), transcript),
        out_dir=str(tmp_path / "out"),
        stages=rec.as_stages(),
        settings={"stabilize": True},
    )
    # The clip passed through unchanged (reframe got the raw cut), and the
    # unavailable notice was surfaced via job.progress (never silently skipped).
    assert "stabilize" in calls
    assert any("libvidstab" in msg for _pct, msg in progress)


def test_run_export_reframe_degraded_surfaced_on_clip_and_progress(transcript, tmp_path):
    """WU-3: when reframe degrades to a center crop (no trackable subject), the
    per-clip degraded signal is surfaced BOTH on the clip payload/item (so the UI
    can show a real/degraded badge) AND via job.progress — never swallowed."""
    calls: list[str] = []
    progress: list[tuple[int, str]] = []
    degraded = {
        "type": "reframe.degraded",
        "message": "reframe: speaker tracking unavailable — used center crop",
        "reason": "no trackable subject located",
    }
    rec = RecordingStages(calls, reframe_notice=degraded)
    ctx = JobContext(
        job_id="j1",
        _cancel_event=threading.Event(),
        _emit_progress=lambda jid, pct, msg: progress.append((pct, msg)),
    )
    out = sm.run_export(
        ctx,
        video_id="v1",
        candidates=[{"rank": 1, "start": 0.0, "end": 30.0, "sourceStart": 0.0, "score": 9}],
        load_context=loader_for(str(tmp_path / "src.mp4"), transcript),
        out_dir=str(tmp_path / "out"),
        stages=rec.as_stages(),
        settings={"stabilize": False},
    )
    # surfaced on the full item record ...
    assert out["items"][0]["reframeDegraded"] == degraded
    # ... AND on the §2 clip payload (the UI badge source) ...
    assert out["clips"][0]["reframeDegraded"] == degraded
    # ... AND announced via progress (not silently swallowed).
    assert any("speaker tracking unavailable" in msg for _pct, msg in progress)


def test_run_export_reframe_ok_has_no_degraded_badge(transcript, tmp_path):
    """A healthy reframe must NOT stamp a degraded badge (no false positive)."""
    calls: list[str] = []
    rec = RecordingStages(calls)  # no reframe_notice -> reframe does not degrade
    out = sm.run_export(
        make_ctx(),
        video_id="v1",
        candidates=[{"rank": 1, "start": 0.0, "end": 30.0, "sourceStart": 0.0, "score": 9}],
        load_context=loader_for(str(tmp_path / "src.mp4"), transcript),
        out_dir=str(tmp_path / "out"),
        stages=rec.as_stages(),
        settings={"stabilize": False},
    )
    assert "reframeDegraded" not in out["items"][0]
    assert "reframeDegraded" not in out["clips"][0]


def test_run_export_silence_trim_unavailable_notice_surfaced(transcript, tmp_path):
    """WU-3: a swallowed silence-trim failure (e.g. no ffmpeg for silencedetect)
    is surfaced via job.progress instead of silently no-op'ing the step."""
    calls: list[str] = []
    progress: list[tuple[int, str]] = []
    notice = {
        "type": "silencetrim.unavailable",
        "message": "silence-trim skipped: ffmpeg not found; the clip was passed through unchanged",
        "reason": "ffmpeg not found",
    }
    rec = RecordingStages(calls, trim_notice=notice)
    ctx = JobContext(
        job_id="j1",
        _cancel_event=threading.Event(),
        _emit_progress=lambda jid, pct, msg: progress.append((pct, msg)),
    )
    sm.run_export(
        ctx,
        video_id="v1",
        candidates=[_stab_candidate()],
        load_context=loader_for(str(tmp_path / "src.mp4"), transcript),
        out_dir=str(tmp_path / "out"),
        stages=rec.as_stages(),
        settings={"silenceTrim": True, "stabilize": False},
    )
    assert "trim_silence" in calls
    assert any("silence-trim skipped" in msg for _pct, msg in progress)


def test_run_export_silence_trim_excludes_fillers(transcript, tmp_path):
    """silenceTrim wins over removeFillers (mutually exclusive timeline edits)."""
    calls: list[str] = []
    rec = RecordingStages(calls)
    sm.run_export(
        make_ctx(),
        video_id="v1",
        candidates=[_stab_candidate()],
        load_context=loader_for(str(tmp_path / "src.mp4"), transcript),
        out_dir=str(tmp_path / "out"),
        stages=rec.as_stages(),
        settings={"silenceTrim": True, "removeFillers": True},
    )
    assert "trim_silence" in calls
    assert "remove_fillers" not in calls


# ---------------------------------------------------------------------------
# §8d brand-logo overlay — applied on export only when brandLogoPath is set
# ---------------------------------------------------------------------------
def test_run_export_no_brand_overlay_without_logo(transcript, tmp_path):
    """No brandLogoPath -> the brand overlay stage never runs."""
    calls: list[str] = []
    rec = RecordingStages(calls)
    candidate = {"rank": 1, "start": 0.0, "end": 30.0, "sourceStart": 0.0, "score": 9}
    sm.run_export(
        make_ctx(),
        video_id="v1",
        candidates=[candidate],
        load_context=loader_for(str(tmp_path / "src.mp4"), transcript),
        out_dir=str(tmp_path / "out"),
        stages=rec.as_stages(),
    )
    assert "brand_overlay" not in calls
    assert rec.brand_kwargs == []


def test_run_export_brand_overlay_after_caption_before_export(transcript, tmp_path):
    """brandLogoPath set -> overlay runs AFTER caption, BEFORE export (§8d)."""
    calls: list[str] = []
    rec = RecordingStages(calls)
    candidate = {"rank": 1, "start": 0.0, "end": 30.0, "sourceStart": 0.0, "score": 9}
    sm.run_export(
        make_ctx(),
        video_id="v1",
        candidates=[candidate],
        load_context=loader_for(str(tmp_path / "src.mp4"), transcript),
        out_dir=str(tmp_path / "out"),
        stages=rec.as_stages(),
        settings={"brandLogoPath": "C:/brand/logo.png"},
    )
    assert calls == ["cut", "stabilize", "reframe", "caption", "brand_overlay", "export"]
    b = rec.brand_kwargs[0]
    assert b["in_path"].endswith(".captioned.mp4")
    assert b["out_path"].endswith(".branded.mp4")
    assert b["logo_path"] == "C:/brand/logo.png"


def test_run_export_brand_defaults_caption_style_when_unset(transcript, tmp_path):
    """brandCaptionTemplate fills in captionStyle when the user didn't pick one."""
    rec = RecordingStages([])
    candidate = {"rank": 1, "start": 0.0, "end": 30.0, "sourceStart": 0.0, "score": 9}
    sm.run_export(
        make_ctx(),
        video_id="v1",
        candidates=[candidate],
        load_context=loader_for(str(tmp_path / "src.mp4"), transcript),
        out_dir=str(tmp_path / "out"),
        stages=rec.as_stages(),
        settings={"brandCaptionTemplate": "hormozi"},
    )
    # The persisted metadata records the resolved (brand-defaulted) template.
    meta_path = tmp_path / "out" / "01-src.mp4.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["template"] == "hormozi"


def test_run_export_user_caption_style_beats_brand_default(transcript, tmp_path):
    """An explicit captionStyle wins over the brand-kit default."""
    rec = RecordingStages([])
    candidate = {"rank": 1, "start": 0.0, "end": 30.0, "sourceStart": 0.0, "score": 9}
    sm.run_export(
        make_ctx(),
        video_id="v1",
        candidates=[candidate],
        load_context=loader_for(str(tmp_path / "src.mp4"), transcript),
        out_dir=str(tmp_path / "out"),
        stages=rec.as_stages(),
        settings={"captionStyle": "neon", "brandCaptionTemplate": "hormozi"},
    )
    meta_path = tmp_path / "out" / "01-src.mp4.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["template"] == "neon"


def test_run_export_multiple_clips_order_and_paths(transcript, tmp_path):
    calls: list[str] = []
    rec = RecordingStages(calls)
    cands = [
        {"rank": 1, "start": 0.0, "end": 25.0, "sourceStart": 0.0, "score": 9},
        {"rank": 2, "start": 30.0, "end": 55.0, "sourceStart": 30.0, "score": 8},
    ]
    out = sm.run_export(
        make_ctx(),
        video_id="v1",
        candidates=cands,
        load_context=loader_for(str(tmp_path / "talk.mp4"), transcript),
        out_dir=str(tmp_path / "out"),
        stages=rec.as_stages(),
    )
    # Two full pipelines back-to-back.
    assert calls == [
        "cut",
        "stabilize",
        "reframe",
        "caption",
        "export",
        "cut",
        "stabilize",
        "reframe",
        "caption",
        "export",
    ]
    paths = [c["path"] for c in out["clips"]]
    assert paths == [
        str(tmp_path / "out" / "01-talk.mp4"),
        str(tmp_path / "out" / "02-talk.mp4"),
    ]
    # The full {candidate, path} records survive for the manifest (§3).
    assert out["items"][0]["candidate"]["rank"] == 1
    assert out["items"][0]["path"].endswith("01-talk.mp4")


def test_run_export_empty_batch_gives_no_clips(transcript, tmp_path):
    calls: list[str] = []
    rec = RecordingStages(calls)
    out = sm.run_export(
        make_ctx(),
        video_id="v1",
        candidates=[],
        load_context=loader_for(str(tmp_path / "src.mp4"), transcript),
        out_dir=str(tmp_path / "out"),
        stages=rec.as_stages(),
    )
    assert out["clips"] == []
    assert out["reason"] == "no clips"
    assert calls == []  # no stage ran


def test_run_export_defaults_sourceStart_when_absent(transcript, tmp_path):
    """A candidate missing sourceStart falls back to start for cut + caption."""
    rec = RecordingStages([])
    candidate = {"rank": 1, "start": 7.0, "end": 30.0, "score": 5}  # no sourceStart
    sm.run_export(
        make_ctx(),
        video_id="v1",
        candidates=[candidate],
        load_context=loader_for(str(tmp_path / "src.mp4"), transcript),
        out_dir=str(tmp_path / "out"),
        stages=rec.as_stages(),
    )
    _in, _out, start, _end = rec.cut_args[0]
    assert start == pytest.approx(7.0)
    assert rec.caption_kwargs[0]["source_start"] == pytest.approx(7.0)


# ---------------------------------------------------------------------------
# EXPORT phase — verthor no-subject center-crop fallback (still ONE engine)
# ---------------------------------------------------------------------------
def test_run_export_reframe_no_subject_uses_center_crop_fallback(transcript, tmp_path):
    """When verthor finds no subject it falls back to a center crop INTERNALLY.

    The orchestrator stays oblivious — it calls ONE reframe seam. We model the
    adapter choosing the fallback and assert the pipeline still completes with a
    single reframe call (no second engine).
    """
    calls: list[str] = []
    fallback_marker: list[str] = []

    def reframe_impl(in_path, out_path, aspect):
        # The verthor adapter: no subject detected -> center-crop fallback.
        fallback_marker.append("center-crop")
        return out_path

    rec = RecordingStages(calls, reframe_impl=reframe_impl)
    candidate = {"rank": 1, "start": 0.0, "end": 25.0, "sourceStart": 0.0, "score": 9}
    out = sm.run_export(
        make_ctx(),
        video_id="v1",
        candidates=[candidate],
        load_context=loader_for(str(tmp_path / "src.mp4"), transcript),
        out_dir=str(tmp_path / "out"),
        stages=rec.as_stages(),
    )
    assert calls.count("reframe") == 1  # exactly ONE engine call
    assert fallback_marker == ["center-crop"]
    assert out["clips"][0]["path"].endswith(".mp4")


# ---------------------------------------------------------------------------
# pure helpers
# ---------------------------------------------------------------------------
def test_is_empty_transcript_variants():
    assert sm._is_empty_transcript(None) is True
    assert sm._is_empty_transcript({}) is True
    assert sm._is_empty_transcript({"segments": []}) is True
    assert sm._is_empty_transcript({"segments": [{"text": "  "}]}) is True
    assert sm._is_empty_transcript({"segments": [{"text": "hi"}]}) is False


def test_words_of_flattens_segments():
    transcript = {
        "segments": [
            {"words": [{"text": "a", "start": 0, "end": 1}]},
            {"words": [{"text": "b", "start": 1, "end": 2}]},
            {"words": []},
        ]
    }
    words = sm._words_of(transcript)
    assert [w["text"] for w in words] == ["a", "b"]
    assert sm._words_of(None) == []


def test_cues_for_clip_falls_back_to_segment_span():
    """Segments without word timing still yield a single span cue."""
    transcript = {
        "segments": [
            {"start": 5.0, "end": 15.0, "text": "no words here", "words": []},
        ]
    }
    cand = {"sourceStart": 0.0, "end": 30.0}
    cues = sm._cues_for_clip(transcript, cand)
    assert len(cues) == 1
    assert cues[0]["text"] == "no words here"
    assert cues[0]["start"] == pytest.approx(5.0)


def test_cues_for_clip_empty_transcript():
    assert sm._cues_for_clip(None, {"sourceStart": 0, "end": 10}) == []


def test_coerce_candidate_fills_defaults():
    c = sm._coerce_candidate({"start": 4.0, "end": 30.0}, fallback_rank=7)
    assert c["rank"] == 7
    assert c["durationSec"] == pytest.approx(26.0)
    assert c["sourceStart"] == pytest.approx(4.0)
    assert c["hook"] == "" and c["why"] == "" and c["score"] == 0


# ---------------------------------------------------------------------------
# RPC handlers (shortmaker.select / shortmaker.export) — §2 {jobId}
# ---------------------------------------------------------------------------
def _rpc_ctx(registry: JobRegistry) -> RpcContext:
    return RpcContext(emit_notification=lambda obj: None, jobs=registry)


def test_shortmaker_select_handler_returns_jobId(registry, transcript):
    calls: list[str] = []
    rec = RecordingStages(
        calls,
        select_return=[{"rank": 1, "start": 0.0, "end": 25.0, "score": 9}],
    )
    maker = sm.ShortMaker(
        load_context=loader_for("/src.mp4", transcript),
        out_dir_for=lambda vid: "/out",
        stages=rec.as_stages(),
    )
    out = maker.select(
        {"videoId": "v1", "prompt": "best", "controls": {"count": 1}},
        _rpc_ctx(registry),
    )
    assert "jobId" in out
    job = registry.get(out["jobId"])
    assert job is not None
    job.wait(timeout=5)
    assert job.result["candidates"][0]["rank"] == 1
    assert calls[0] == "select"


def test_shortmaker_export_handler_returns_jobId(registry, transcript, tmp_path):
    calls: list[str] = []
    rec = RecordingStages(calls)
    maker = sm.ShortMaker(
        load_context=loader_for(str(tmp_path / "src.mp4"), transcript),
        out_dir_for=lambda vid: str(tmp_path / "out"),
        stages=rec.as_stages(),
    )
    candidate = {"rank": 1, "start": 0.0, "end": 25.0, "sourceStart": 0.0, "score": 9}
    out = maker.export(
        {"videoId": "v1", "candidateIds": ["c1"], "candidates": [candidate]},
        _rpc_ctx(registry),
    )
    assert "jobId" in out
    job = registry.get(out["jobId"])
    assert job is not None
    job.wait(timeout=5)
    assert job.result["clips"][0]["path"].endswith(".mp4")
    assert calls == ["cut", "stabilize", "reframe", "caption", "export"]


def test_shortmaker_select_requires_videoId(registry):
    maker = sm.ShortMaker(
        load_context=loader_for("/src.mp4", None),
        out_dir_for=lambda vid: "/out",
        stages=sm.Stages(),
    )
    with pytest.raises(RpcError):
        maker.select({"prompt": "x"}, _rpc_ctx(registry))


def test_shortmaker_export_requires_videoId(registry):
    maker = sm.ShortMaker(
        load_context=loader_for("/src.mp4", None),
        out_dir_for=lambda vid: "/out",
        stages=sm.Stages(),
    )
    with pytest.raises(RpcError):
        maker.export({"candidateIds": ["c1"]}, _rpc_ctx(registry))


def test_resolve_candidates_prefers_inline_list(registry):
    maker = sm.ShortMaker(
        load_context=loader_for("/src.mp4", None),
        out_dir_for=lambda vid: "/out",
    )
    inline = [{"rank": 1, "start": 0, "end": 25, "score": 9}]
    resolved = maker._resolve_candidates("v1", ["c1"], inline)
    assert resolved == inline


def test_resolve_candidates_by_id_from_context(registry):
    by_id = {"c1": {"rank": 1, "start": 0, "end": 25}, "c2": {"rank": 2, "start": 30, "end": 55}}
    maker = sm.ShortMaker(
        load_context=loader_for("/src.mp4", None, candidates=by_id),
        out_dir_for=lambda vid: "/out",
    )
    resolved = maker._resolve_candidates("v1", ["c2", "missing"], [])
    assert len(resolved) == 1
    assert resolved[0]["rank"] == 2  # unknown id skipped


def test_resolve_candidates_empty_when_nothing_given(registry):
    maker = sm.ShortMaker(
        load_context=loader_for("/src.mp4", None),
        out_dir_for=lambda vid: "/out",
    )
    assert maker._resolve_candidates("v1", [], []) == []


def test_register_wires_both_methods(registry):
    registered: dict[str, Any] = {}
    maker = sm.ShortMaker(
        load_context=loader_for("/src.mp4", None),
        out_dir_for=lambda vid: "/out",
    )
    maker.register(lambda name, handler: registered.__setitem__(name, handler))
    assert set(registered) == {"shortmaker.select", "shortmaker.export"}


def test_register_with_protocol_register_exposes_methods(registry):
    """register() integrates with the real protocol.register (method table)."""
    maker = sm.ShortMaker(
        load_context=loader_for("/src.mp4", None),
        out_dir_for=lambda vid: "/out",
    )
    maker.register(protocol.register)
    assert "shortmaker.select" in protocol.METHODS
    assert "shortmaker.export" in protocol.METHODS


# ---------------------------------------------------------------------------
# cancellation cooperates with the Job seam
# ---------------------------------------------------------------------------
def test_run_select_honors_cancellation(transcript, two_candidates):
    calls: list[str] = []
    rec = RecordingStages(calls, select_return=two_candidates)
    cancel = threading.Event()
    cancel.set()  # cancelled before select runs
    ctx = JobContext(job_id="c1", _cancel_event=cancel, _emit_progress=lambda *a: None)

    with pytest.raises(JobCancelled):
        sm.run_select(
            ctx,
            video_id="v1",
            prompt="p",
            controls={"count": 2},
            load_context=loader_for("/src.mp4", transcript),
            stages=rec.as_stages(),
        )
    assert calls == []  # cancelled before select even ran


def test_run_export_honors_cancellation(transcript, tmp_path):
    calls: list[str] = []
    rec = RecordingStages(calls)
    cancel = threading.Event()
    cancel.set()
    ctx = JobContext(job_id="c2", _cancel_event=cancel, _emit_progress=lambda *a: None)
    candidate = {"rank": 1, "start": 0.0, "end": 25.0, "sourceStart": 0.0, "score": 9}
    with pytest.raises(JobCancelled):
        sm.run_export(
            ctx,
            video_id="v1",
            candidates=[candidate],
            load_context=loader_for(str(tmp_path / "src.mp4"), transcript),
            out_dir=str(tmp_path / "out"),
            stages=rec.as_stages(),
        )
    assert calls == []  # cancelled before any stage ran


# -- provider seam (Phase-0 regression) -------------------------------------


def test_default_provider_builds_real_provider_from_settings():
    # Phase-0 spine finding: this seam guessed a nonexistent factory name and
    # fell back to a positional ctor call (TypeError at runtime, invisible to
    # the suite behind "pragma: no cover"). Pin it to the REAL factory.
    from media_studio.features.shortmaker import _default_provider
    from media_studio.models.provider import LocalServerProvider

    p = _default_provider({})
    assert isinstance(p, LocalServerProvider)
    assert callable(getattr(p, "chat", None))


def test_default_provider_routes_cloud_when_configured():
    from media_studio.features.shortmaker import _default_provider
    from media_studio.models.provider import CloudProvider

    p = _default_provider({"useCloud": True, "cloudApiKey": "k"})
    assert isinstance(p, CloudProvider)


# -- caption-stage routing (punch #2: Remotion wired into export) ------------


class TestCaptionStageRouting:
    def _route(self, monkeypatch, style):
        """Run _lazy_caption with both engines faked; return which fired."""
        from media_studio.features import shortmaker as sm

        fired = {}

        class FakeLibass:
            def __init__(self, settings):
                fired["engine"] = "libass"

            def render(self, clip, cues, out, **kw):
                fired["kw"] = kw
                return out

        class FakeRemotion:
            def __init__(self, settings):
                fired["engine"] = "remotion"

            def render(self, clip, cues, out, **kw):
                fired["kw"] = kw
                return out

        import media_studio.features.caption as cap
        import media_studio.features.caption_remotion as rem

        monkeypatch.setattr(cap, "CaptionEngine", FakeLibass)
        monkeypatch.setattr(rem, "RemotionCaptionEngine", FakeRemotion)
        out = sm._lazy_caption(
            "clip.mp4",
            [],
            "out.mp4",
            source_start=5.0,
            burn=True,
            width=1080,
            height=1920,
            settings={"captionStyle": style} if style is not None else {},
        )
        return fired, out

    def test_default_routes_to_libass(self, monkeypatch):
        fired, out = self._route(monkeypatch, None)
        assert fired["engine"] == "libass"
        assert out == "out.mp4"

    def test_remotion_styles_route_to_remotion(self, monkeypatch):
        for style in ("bold", "bounce", "clean", "karaoke"):
            fired, out = self._route(monkeypatch, style)
            assert fired["engine"] == "remotion", style
            assert fired["kw"]["style"] == style
            assert fired["kw"]["source_start"] == 5.0
            assert out == "out.mp4"

    def test_none_skips_captioning(self, monkeypatch):
        fired, out = self._route(monkeypatch, "none")
        assert "engine" not in fired  # neither engine constructed
        assert out == "clip.mp4"  # pass-through of the uncaptioned clip

    def test_unknown_style_falls_back_to_libass(self, monkeypatch):
        fired, out = self._route(monkeypatch, "comic-sans")
        assert fired["engine"] == "libass"
        assert out == "out.mp4"
        # a non-karaoke libass route passes karaoke=False.
        assert fired["kw"]["karaoke"] is False

    def test_opusclip_karaoke_routes_to_libass_with_karaoke_flag(self, monkeypatch):
        # WU SP1: the "opusclip-karaoke" preset is a libass style (not a Remotion
        # template) and selects the word-by-word karaoke ASS via karaoke=True.
        fired, out = self._route(monkeypatch, "opusclip-karaoke")
        assert fired["engine"] == "libass"
        assert fired["kw"]["karaoke"] is True
        assert out == "out.mp4"


# -- audioTrackId through export (punch #4 — the frozen A2 line) --------------


DUB_TRACK = {
    "id": "aud-dub-1",
    "lang": "ro",
    "name": "Romanian dub",
    "kind": "dub",
    "voice": "kokoro:ro",
    "path": "/dubs/ro.m4a",
}
ORIGINAL_TRACK = {
    "id": "aud-orig-0",
    "lang": "en",
    "name": "Audio 1",
    "kind": "original",
    "path": "/videos/talk.mp4",
}


class TestBuildAudioMuxArgv:
    @pytest.fixture(autouse=True)
    def _fake_ffmpeg_path(self, monkeypatch):
        from media_studio import ffmpeg

        monkeypatch.setattr(ffmpeg, "ffmpeg_path", lambda settings=None: "/bin/ffmpeg")

    def test_maps_clip_video_and_track_audio_window(self):
        argv = sm.build_audio_mux_argv(
            "C:/out/clip 1.mp4",
            "/dubs/ro.m4a",
            "C:/out/final 1.mp4",
            start=97.0,
            end=131.0,
        )
        assert isinstance(argv, list)  # A6.4: argv list, never a shell string
        assert argv[0] == "/bin/ffmpeg"
        # video of input 0 kept under stream copy; clip's own audio dropped.
        assert argv[argv.index("-map") : argv.index("-map") + 2] == ["-map", "0:v"]
        assert "1:a:0" in argv
        assert argv[argv.index("-c:v") + 1] == "copy"
        assert argv[argv.index("-c:a") + 1] == "aac"
        # the window seeks the AUDIO input (input-side -ss/-to before its -i).
        i_audio = argv.index("/dubs/ro.m4a")
        assert argv[i_audio - 1] == "-i"
        i_ss = argv.index("-ss")
        i_to = argv.index("-to")
        assert i_ss < i_to < i_audio
        assert argv[i_ss + 1] == "97.000"
        assert argv[i_to + 1] == "131.000"
        # progress stream + the output last (paths with spaces stay intact).
        assert argv[argv.index("-progress") : argv.index("-progress") + 2] == ["-progress", "pipe:1"]
        assert argv[-1] == "C:/out/final 1.mp4"

    def test_stream_index_selects_the_container_audio_lane(self):
        argv = sm.build_audio_mux_argv(
            "clip.mp4",
            "/videos/talk.mp4",
            "out.mp4",
            start=10.0,
            end=40.0,
            stream_index=2,
        )
        assert "1:a:2" in argv

    def test_rejects_inverted_window_and_negative_index(self):
        with pytest.raises(ValueError):
            sm.build_audio_mux_argv("c.mp4", "a.m4a", "o.mp4", start=40.0, end=40.0)
        with pytest.raises(ValueError):
            sm.build_audio_mux_argv("c.mp4", "a.m4a", "o.mp4", start=0.0, end=10.0, stream_index=-1)


class TestResolveAudioTrack:
    def test_dub_track_resolves_with_stream_index_zero(self):
        context = {"audioTracks": [ORIGINAL_TRACK, DUB_TRACK]}
        track = sm._resolve_audio_track(context, "aud-dub-1")
        assert track is not None
        assert track["path"] == "/dubs/ro.m4a"
        assert track["streamIndex"] == 0  # standalone dub file: its only stream

    def test_original_track_stream_index_is_its_list_position(self):
        second_original = {**ORIGINAL_TRACK, "id": "aud-orig-1", "name": "Audio 2"}
        context = {"audioTracks": [ORIGINAL_TRACK, second_original, DUB_TRACK]}
        track = sm._resolve_audio_track(context, "aud-orig-1")
        assert track is not None
        assert track["streamIndex"] == 1  # originals seeded first, list order = a:<n>

    def test_unknown_id_and_malformed_lists_resolve_none(self):
        assert sm._resolve_audio_track({"audioTracks": [DUB_TRACK]}, "nope") is None
        assert sm._resolve_audio_track({}, "aud-dub-1") is None
        assert sm._resolve_audio_track({"audioTracks": "junk"}, "aud-dub-1") is None

    def test_does_not_mutate_the_manifest_row(self):
        row = dict(DUB_TRACK)
        sm._resolve_audio_track({"audioTracks": [row]}, "aud-dub-1")
        assert "streamIndex" not in row


class TestExportWithAudioTrack:
    def _export(self, tmp_path, transcript, *, audio_track_id, tracks):
        calls: list[str] = []
        rec = RecordingStages(calls)
        candidate = {
            "rank": 1,
            "start": 97.0,
            "end": 131.0,
            "durationSec": 34.0,
            "hook": "h",
            "why": "w",
            "score": 95,
            "sourceStart": 97.0,
        }
        out = sm.run_export(
            make_ctx(),
            video_id="v1",
            candidates=[candidate],
            load_context=loader_for(str(tmp_path / "talk.mp4"), transcript, audioTracks=tracks),
            out_dir=str(tmp_path / "out"),
            stages=rec.as_stages(),
            audio_track_id=audio_track_id,
        )
        return out, rec, calls

    def test_mux_runs_last_and_final_path_is_unchanged(self, transcript, tmp_path):
        out, rec, calls = self._export(tmp_path, transcript, audio_track_id="aud-dub-1", tracks=[DUB_TRACK])
        assert calls == ["cut", "stabilize", "reframe", "caption", "export", "mux_audio"]
        # The §2 contract path is the SAME with or without the audio carry.
        assert out["clips"] == [{"path": str(tmp_path / "out" / "01-talk.mp4")}]
        mux = rec.mux_kwargs[0]
        assert mux["out_path"] == str(tmp_path / "out" / "01-talk.mp4")
        assert mux["clip_path"] == str(tmp_path / "out" / "talk-1.encoded.mp4")

    def test_mux_receives_resolved_track_and_source_window(self, transcript, tmp_path):
        _out, rec, _calls = self._export(tmp_path, transcript, audio_track_id="aud-dub-1", tracks=[DUB_TRACK])
        mux = rec.mux_kwargs[0]
        assert mux["audio_track"]["id"] == "aud-dub-1"
        assert mux["audio_track"]["kind"] == "dub"
        assert mux["audio_track"]["streamIndex"] == 0
        # window = the candidate's sourceStart -> end (original-video time).
        assert mux["start"] == pytest.approx(97.0)
        assert mux["end"] == pytest.approx(131.0)

    def test_no_audio_track_id_skips_the_mux_stage(self, transcript, tmp_path):
        _out, rec, calls = self._export(tmp_path, transcript, audio_track_id=None, tracks=[DUB_TRACK])
        assert calls == ["cut", "stabilize", "reframe", "caption", "export"]
        assert rec.mux_kwargs == []

    def test_unknown_audio_track_id_fails_before_any_stage(self, transcript, tmp_path):
        # A6.3: raised inside the job body -> surfaces via job.done error payload.
        with pytest.raises(ValueError, match="unknown audio track"):
            self._export(tmp_path, transcript, audio_track_id="ghost", tracks=[DUB_TRACK])

    def test_mux_runs_per_clip_for_a_batch(self, transcript, tmp_path):
        calls: list[str] = []
        rec = RecordingStages(calls)
        cands = [
            {"rank": 1, "start": 0.0, "end": 25.0, "sourceStart": 0.0, "score": 9},
            {"rank": 2, "start": 30.0, "end": 55.0, "sourceStart": 30.0, "score": 8},
        ]
        sm.run_export(
            make_ctx(),
            video_id="v1",
            candidates=cands,
            load_context=loader_for(str(tmp_path / "talk.mp4"), transcript, audioTracks=[DUB_TRACK]),
            out_dir=str(tmp_path / "out"),
            stages=rec.as_stages(),
            audio_track_id="aud-dub-1",
        )
        assert calls == [
            "cut",
            "stabilize",
            "reframe",
            "caption",
            "export",
            "mux_audio",
            "cut",
            "stabilize",
            "reframe",
            "caption",
            "export",
            "mux_audio",
        ]
        assert [m["start"] for m in rec.mux_kwargs] == [0.0, 30.0]


class TestExportHandlerAudioTrackParam:
    def _maker(self, tmp_path, transcript, rec, tracks):
        return sm.ShortMaker(
            load_context=loader_for(str(tmp_path / "talk.mp4"), transcript, audioTracks=tracks),
            out_dir_for=lambda vid: str(tmp_path / "out"),
            stages=rec.as_stages(),
        )

    def test_export_threads_audioTrackId_to_the_mux_stage(self, registry, transcript, tmp_path):
        calls: list[str] = []
        rec = RecordingStages(calls)
        maker = self._maker(tmp_path, transcript, rec, [DUB_TRACK])
        candidate = {"rank": 1, "start": 0.0, "end": 25.0, "sourceStart": 0.0, "score": 9}
        out = maker.export(
            {
                "videoId": "v1",
                "candidateIds": ["1@0"],
                "candidates": [candidate],
                "audioTrackId": "aud-dub-1",
            },
            _rpc_ctx(registry),
        )
        job = registry.get(out["jobId"])
        job.wait(timeout=5)
        assert calls == ["cut", "stabilize", "reframe", "caption", "export", "mux_audio"]
        assert rec.mux_kwargs[0]["audio_track"]["id"] == "aud-dub-1"

    def test_export_rejects_a_non_string_audioTrackId(self, registry, transcript, tmp_path):
        rec = RecordingStages([])
        maker = self._maker(tmp_path, transcript, rec, [DUB_TRACK])
        with pytest.raises(RpcError):
            maker.export(
                {"videoId": "v1", "candidates": [], "audioTrackId": 42},
                _rpc_ctx(registry),
            )

    def test_export_treats_empty_audioTrackId_as_absent(self, registry, transcript, tmp_path):
        calls: list[str] = []
        rec = RecordingStages(calls)
        maker = self._maker(tmp_path, transcript, rec, [DUB_TRACK])
        candidate = {"rank": 1, "start": 0.0, "end": 25.0, "sourceStart": 0.0, "score": 9}
        out = maker.export(
            {
                "videoId": "v1",
                "candidates": [candidate],
                "audioTrackId": "",  # the UI's "Original" choice sends nothing
            },
            _rpc_ctx(registry),
        )
        registry.get(out["jobId"]).wait(timeout=5)
        assert calls == ["cut", "stabilize", "reframe", "caption", "export"]


class TestLazyMuxAudioStage:
    def test_builds_argv_from_the_track_and_runs_it(self, monkeypatch):
        from media_studio import ffmpeg

        ran: dict[str, Any] = {}
        monkeypatch.setattr(ffmpeg, "ffmpeg_path", lambda settings=None: "/bin/ffmpeg")
        monkeypatch.setattr(ffmpeg, "run", lambda argv, **kw: ran.setdefault("argv", argv) and 0 or 0)
        track = {**DUB_TRACK, "streamIndex": 0}
        out = sm._lazy_mux_audio("clip.mp4", track, "final.mp4", start=10.0, end=40.0, settings={})
        assert out == "final.mp4"
        assert ran["argv"][0] == "/bin/ffmpeg"
        assert "/dubs/ro.m4a" in ran["argv"]
        assert "1:a:0" in ran["argv"]

    def test_track_without_a_path_raises(self):
        with pytest.raises(ValueError, match="no path"):
            sm._lazy_mux_audio(
                "clip.mp4",
                {"id": "x", "kind": "dub"},
                "final.mp4",
                start=0.0,
                end=10.0,
            )


# -- P3-B filler stage through export (CRITICAL #4) --------------------------


class TestExportRemoveFillers:
    """The remove_fillers stage runs only when removeFillers is ON, threads its
    remapped cues into CAPTION, and surfaces per-clip stats on the payload."""

    def _candidate(self):
        return {
            "rank": 1,
            "start": 20.0,
            "end": 45.0,
            "durationSec": 25.0,
            "hook": "the hook",
            "why": "w",
            "score": 95,
            "sourceStart": 20.0,
        }

    def test_filler_stage_skipped_when_off(self, transcript, tmp_path):
        calls: list[str] = []
        rec = RecordingStages(calls)
        sm.run_export(
            make_ctx(),
            video_id="v1",
            candidates=[self._candidate()],
            load_context=loader_for(str(tmp_path / "src.mp4"), transcript),
            out_dir=str(tmp_path / "out"),
            stages=rec.as_stages(),
            settings={"removeFillers": False},
        )
        # OFF: byte-identical base order, no filler stage, no stats on payload.
        assert calls == ["cut", "stabilize", "reframe", "caption", "export"]
        assert rec.filler_kwargs == []

    def test_filler_stage_absent_setting_is_off(self, transcript, tmp_path):
        calls: list[str] = []
        rec = RecordingStages(calls)
        out = sm.run_export(
            make_ctx(),
            video_id="v1",
            candidates=[self._candidate()],
            load_context=loader_for(str(tmp_path / "src.mp4"), transcript),
            out_dir=str(tmp_path / "out"),
            stages=rec.as_stages(),
            settings={},  # removeFillers absent -> OFF (default)
        )
        assert "remove_fillers" not in calls
        assert "fillersRemoved" not in out["clips"][0]

    def test_filler_stage_runs_after_cut_when_on(self, transcript, tmp_path):
        calls: list[str] = []
        rec = RecordingStages(calls)
        sm.run_export(
            make_ctx(),
            video_id="v1",
            candidates=[self._candidate()],
            load_context=loader_for(str(tmp_path / "src.mp4"), transcript),
            out_dir=str(tmp_path / "out"),
            stages=rec.as_stages(),
            settings={"removeFillers": True},
        )
        # ON: the de-fill runs AFTER cut, BEFORE reframe.
        assert calls == [
            "cut",
            "stabilize",
            "remove_fillers",
            "reframe",
            "caption",
            "export",
        ]

    def test_filler_stage_gets_clip_local_words_and_cues(self, transcript, tmp_path):
        """Words/cues handed to the filler stage are re-based to the cut clip's
        t=0 (sourceStart subtracted) — clip window [20, 45) over the fixture."""
        rec = RecordingStages([])
        sm.run_export(
            make_ctx(),
            video_id="v1",
            candidates=[self._candidate()],
            load_context=loader_for(str(tmp_path / "src.mp4"), transcript),
            out_dir=str(tmp_path / "out"),
            stages=rec.as_stages(),
            settings={"removeFillers": True},
        )
        fk = rec.filler_kwargs[0]
        # "buy" @25.0 -> 5.0 clip-local; "why" @40.0 -> 20.0 clip-local.
        starts = sorted(w["start"] for w in fk["words"])
        assert starts == pytest.approx([5.0, 20.0])
        assert all(w["start"] >= 0.0 for w in fk["words"])
        assert fk["lang"] == "en"  # transcript language flows to the filler set
        # cues handed in are clip-local too (re-based, renumbered from 1).
        assert all(c["index"] >= 1 for c in fk["cues"])
        assert min(c["start"] for c in fk["cues"]) >= 0.0

    def test_filler_remapped_cues_and_zero_source_start_reach_caption(self, transcript, tmp_path):
        """CAPTION receives the filler stage's REMAPPED cues with source_start=0
        (the de-filled clip is already clip-local)."""
        sentinel_cues = [{"index": 1, "start": 0.0, "end": 2.0, "text": "remapped"}]

        def filler_impl(in_path, out_path, words, cues):
            return out_path, sentinel_cues, {"fillersRemoved": 3, "fillerSeconds": 1.2}

        rec = RecordingStages([], filler_impl=filler_impl)
        sm.run_export(
            make_ctx(),
            video_id="v1",
            candidates=[self._candidate()],
            load_context=loader_for(str(tmp_path / "src.mp4"), transcript),
            out_dir=str(tmp_path / "out"),
            stages=rec.as_stages(),
            settings={"removeFillers": True},
        )
        cap = rec.caption_kwargs[0]
        # The REMAPPED cues reach caption (the filler stage's output, not the
        # originals). §8a then annotates them with emphasis/emoji fields, so
        # compare the contract cue fields rather than full dict equality (this
        # transcript/style defaults emphasis OFF -> empty spans, blank emoji).
        assert [{k: c[k] for k in ("index", "start", "end", "text")} for c in cap["cues"]] == sentinel_cues
        assert all(c["emphasis"] == [] and c["emoji"] == "" for c in cap["cues"])
        assert cap["source_start"] == pytest.approx(0.0)  # already clip-local
        # The de-filled clip (filler out_path) is what REFRAME/CAPTION consume.
        assert cap["clip_path"].endswith(".reframed.mp4")

    def test_filler_stats_surface_on_clip_payload(self, transcript, tmp_path):
        def filler_impl(in_path, out_path, words, cues):
            return out_path, list(cues), {"fillersRemoved": 4, "fillerSeconds": 2.5}

        rec = RecordingStages([], filler_impl=filler_impl)
        out = sm.run_export(
            make_ctx(),
            video_id="v1",
            candidates=[self._candidate()],
            load_context=loader_for(str(tmp_path / "src.mp4"), transcript),
            out_dir=str(tmp_path / "out"),
            stages=rec.as_stages(),
            settings={"removeFillers": True},
        )
        clip = out["clips"][0]
        assert clip["fillersRemoved"] == 4
        assert clip["fillerSeconds"] == pytest.approx(2.5)
        # The full {candidate, path, stats} record also carries them.
        assert out["items"][0]["fillersRemoved"] == 4

    def test_filler_off_clip_payload_is_path_only(self, transcript, tmp_path):
        rec = RecordingStages([])
        out = sm.run_export(
            make_ctx(),
            video_id="v1",
            candidates=[self._candidate()],
            load_context=loader_for(str(tmp_path / "src.mp4"), transcript),
            out_dir=str(tmp_path / "out"),
            stages=rec.as_stages(),
            settings={"removeFillers": False},
        )
        # §2 base shape preserved exactly when filler removal didn't run.
        assert out["clips"][0] == {"path": str(tmp_path / "out" / "01-src.mp4")}


# -- P3-A hook-title threading through CAPTION (CRITICAL #2 P3-A) -------------


class TestExportHookTitle:
    def _candidate(self, hook="As it turns out, there is a pattern"):
        return {
            "rank": 1,
            "start": 0.0,
            "end": 25.0,
            "durationSec": 25.0,
            "hook": hook,
            "why": "w",
            "score": 9,
            "sourceStart": 0.0,
        }

    def test_hook_threads_to_caption_by_default(self, transcript, tmp_path):
        rec = RecordingStages([])
        sm.run_export(
            make_ctx(),
            video_id="v1",
            candidates=[self._candidate()],
            load_context=loader_for(str(tmp_path / "src.mp4"), transcript),
            out_dir=str(tmp_path / "out"),
            stages=rec.as_stages(),
            settings={},  # hookTitle absent -> default ON
        )
        assert rec.caption_kwargs[0]["hook_title"] == ("As it turns out, there is a pattern")

    def test_hook_threads_when_explicitly_on(self, transcript, tmp_path):
        rec = RecordingStages([])
        sm.run_export(
            make_ctx(),
            video_id="v1",
            candidates=[self._candidate("Big claim")],
            load_context=loader_for(str(tmp_path / "src.mp4"), transcript),
            out_dir=str(tmp_path / "out"),
            stages=rec.as_stages(),
            settings={"hookTitle": True},
        )
        assert rec.caption_kwargs[0]["hook_title"] == "Big claim"

    def test_hook_suppressed_when_off(self, transcript, tmp_path):
        rec = RecordingStages([])
        sm.run_export(
            make_ctx(),
            video_id="v1",
            candidates=[self._candidate()],
            load_context=loader_for(str(tmp_path / "src.mp4"), transcript),
            out_dir=str(tmp_path / "out"),
            stages=rec.as_stages(),
            settings={"hookTitle": False},
        )
        assert rec.caption_kwargs[0]["hook_title"] is None

    def test_blank_hook_is_none_even_when_on(self, transcript, tmp_path):
        rec = RecordingStages([])
        sm.run_export(
            make_ctx(),
            video_id="v1",
            candidates=[self._candidate(hook="   ")],
            load_context=loader_for(str(tmp_path / "src.mp4"), transcript),
            out_dir=str(tmp_path / "out"),
            stages=rec.as_stages(),
            settings={"hookTitle": True},
        )
        assert rec.caption_kwargs[0]["hook_title"] is None


# -- WU SP2: hook CARD gating (top-N by virality rank) + rank-ordered names ---


class TestExportHookCard:
    """The hook CARD is applied to the TOP-N clips by virality rank only; the rest
    keep the plain hook title. Carded clips get the first-~5 s time-box, and ALL
    clips export with a rank-ordered ``NN-`` filename prefix."""

    def _cand(self, rank, hook="The hook"):
        return {
            "rank": rank,
            "start": float(rank) * 30.0,
            "end": float(rank) * 30.0 + 25.0,
            "durationSec": 25.0,
            "hook": hook,
            "sourceStart": float(rank) * 30.0,
            "score": 9,
        }

    def _run(self, tmp_path, transcript, cands, settings):
        rec = RecordingStages([])
        out = sm.run_export(
            make_ctx(),
            video_id="v1",
            candidates=cands,
            load_context=loader_for(str(tmp_path / "talk.mp4"), transcript),
            out_dir=str(tmp_path / "out"),
            stages=rec.as_stages(),
            settings=settings,
        )
        return rec, out

    def test_card_gated_to_top_n_by_rank(self, transcript, tmp_path):
        # 3 clips, top-N=2 -> ranks 1 & 2 carded; rank 3 keeps the plain title.
        cands = [self._cand(1), self._cand(2), self._cand(3)]
        rec, _ = self._run(tmp_path, transcript, cands, {"hookCardTopN": 2})
        flags = [k["hook_card"] for k in rec.caption_kwargs]
        assert flags == [True, True, False]
        # carded clips carry the first-~5 s time-box; the non-carded clip does not.
        assert rec.caption_kwargs[0]["hook_card_sec"] == 5.0

    def test_card_disabled_no_clip_carded(self, transcript, tmp_path):
        cands = [self._cand(1), self._cand(2)]
        rec, _ = self._run(tmp_path, transcript, cands, {"hookCard": False})
        assert [k["hook_card"] for k in rec.caption_kwargs] == [False, False]

    def test_card_respects_custom_window(self, transcript, tmp_path):
        rec, _ = self._run(tmp_path, transcript, [self._cand(1)], {"hookCardSec": 4})
        assert rec.caption_kwargs[0]["hook_card"] is True
        assert rec.caption_kwargs[0]["hook_card_sec"] == 4.0

    def test_card_not_applied_without_hook_text(self, transcript, tmp_path):
        # No hook text -> hookTitle is None so there is no card to draw.
        rec, _ = self._run(tmp_path, transcript, [self._cand(1, hook="  ")], {})
        assert rec.caption_kwargs[0]["hook_card"] is False

    def test_card_suppressed_when_hook_title_off(self, transcript, tmp_path):
        rec, _ = self._run(tmp_path, transcript, [self._cand(1)], {"hookTitle": False})
        assert rec.caption_kwargs[0]["hook_card"] is False

    def test_rank_ordered_filename_prefix(self, transcript, tmp_path):
        # Output files carry a zero-padded NN- prefix (sorts by virality rank).
        cands = [self._cand(1), self._cand(2)]
        _, out = self._run(tmp_path, transcript, cands, {})
        paths = [c["path"] for c in out["clips"]]
        assert paths == [
            str(tmp_path / "out" / "01-talk.mp4"),
            str(tmp_path / "out" / "02-talk.mp4"),
        ]


# -- P3 toggle extraction params->settings (CRITICAL #2) ---------------------


class TestExportTogglesFlowToSettings:
    """The export handler pulls hookTitle/removeFillers off params into settings
    (exactly like captionStyle/reframeEngine), and they reach the stages."""

    def _maker(self, tmp_path, transcript, rec):
        return sm.ShortMaker(
            load_context=loader_for(str(tmp_path / "src.mp4"), transcript),
            out_dir_for=lambda vid: str(tmp_path / "out"),
            stages=rec.as_stages(),
        )

    def test_removeFillers_true_triggers_the_filler_stage(self, registry, transcript, tmp_path):
        calls: list[str] = []
        rec = RecordingStages(calls)
        maker = self._maker(tmp_path, transcript, rec)
        candidate = {
            "rank": 1,
            "start": 0.0,
            "end": 25.0,
            "sourceStart": 0.0,
            "hook": "h",
            "score": 9,
        }
        out = maker.export(
            {
                "videoId": "v1",
                "candidates": [candidate],
                "hookTitle": True,
                "removeFillers": True,
            },
            _rpc_ctx(registry),
        )
        registry.get(out["jobId"]).wait(timeout=5)
        assert "remove_fillers" in calls
        assert rec.caption_kwargs[0]["hook_title"] == "h"

    def test_emphasis_param_threads_into_settings(self, registry, tmp_path):
        """§8a: the export handler pulls the `emphasis` bool off params into
        settings (like hookTitle/removeFillers), reaching the annotation."""
        calls: list[str] = []
        rec = RecordingStages(calls)
        maker = sm.ShortMaker(
            load_context=loader_for(str(tmp_path / "src.mp4"), _emphasis_transcript()),
            out_dir_for=lambda vid: str(tmp_path / "out"),
            stages=rec.as_stages(),
        )
        candidate = {
            "rank": 1,
            "start": 0.0,
            "end": 30.0,
            "sourceStart": 0.0,
            "hook": "h",
            "score": 9,
        }
        # captionStyle "clean" defaults emphasis OFF; explicit emphasis=True must
        # override that default (proving the param reached settings).
        out = maker.export(
            {
                "videoId": "v1",
                "candidates": [candidate],
                "captionStyle": "clean",
                "emphasis": True,
            },
            _rpc_ctx(registry),
        )
        registry.get(out["jobId"]).wait(timeout=5)
        cues = rec.caption_kwargs[0]["cues"]
        by_text = {c["text"]: c for c in cues}
        assert by_text["secret"]["emphasis"]  # emphasis ON despite clean default

    def test_autoZoom_param_threads_into_settings(self, registry, transcript, tmp_path):
        """§8b: the export handler pulls the `autoZoom` bool off params into
        settings (like hookTitle/removeFillers/emphasis), so the zoom stage runs
        between reframe and caption (proving the param reached run_export)."""
        calls: list[str] = []
        rec = RecordingStages(calls)
        maker = self._maker(tmp_path, transcript, rec)
        candidate = {
            "rank": 1,
            "start": 0.0,
            "end": 30.0,
            "sourceStart": 0.0,
            "hook": "h",
            "score": 9,
        }
        out = maker.export(
            {
                "videoId": "v1",
                "candidates": [candidate],
                "autoZoom": True,
            },
            _rpc_ctx(registry),
        )
        registry.get(out["jobId"]).wait(timeout=5)
        # The zoom stage ran (param threaded to settings -> run_export gate).
        assert "zoom" in calls
        assert calls.index("reframe") < calls.index("zoom") < calls.index("caption")

    def test_autoZoom_default_off_when_absent_from_params(self, registry, transcript, tmp_path):
        """§8b: with no `autoZoom` param the zoom stage never runs (default OFF)."""
        calls: list[str] = []
        rec = RecordingStages(calls)
        maker = self._maker(tmp_path, transcript, rec)
        candidate = {
            "rank": 1,
            "start": 0.0,
            "end": 30.0,
            "sourceStart": 0.0,
            "hook": "h",
            "score": 9,
        }
        out = maker.export(
            {"videoId": "v1", "candidates": [candidate]},  # no autoZoom
            _rpc_ctx(registry),
        )
        registry.get(out["jobId"]).wait(timeout=5)
        assert "zoom" not in calls

    def test_toggles_default_when_absent_from_params(self, registry, transcript, tmp_path):
        calls: list[str] = []
        rec = RecordingStages(calls)
        maker = self._maker(tmp_path, transcript, rec)
        candidate = {
            "rank": 1,
            "start": 0.0,
            "end": 25.0,
            "sourceStart": 0.0,
            "hook": "h",
            "score": 9,
        }
        out = maker.export(
            {"videoId": "v1", "candidates": [candidate]},  # no toggles
            _rpc_ctx(registry),
        )
        registry.get(out["jobId"]).wait(timeout=5)
        # Default: hookTitle ON (hook threaded), removeFillers OFF (no stage).
        assert "remove_fillers" not in calls
        assert rec.caption_kwargs[0]["hook_title"] == "h"

    def test_non_bool_toggles_are_ignored(self, registry, transcript, tmp_path):
        """A non-bool toggle (junk) does not poison settings — removeFillers stays
        OFF and the export still runs."""
        calls: list[str] = []
        rec = RecordingStages(calls)
        maker = self._maker(tmp_path, transcript, rec)
        candidate = {
            "rank": 1,
            "start": 0.0,
            "end": 25.0,
            "sourceStart": 0.0,
            "hook": "h",
            "score": 9,
        }
        out = maker.export(
            {
                "videoId": "v1",
                "candidates": [candidate],
                "removeFillers": "yes",  # not a bool -> ignored -> default OFF
                "hookTitle": 1,  # not a bool -> ignored -> default ON
            },
            _rpc_ctx(registry),
        )
        registry.get(out["jobId"]).wait(timeout=5)
        assert "remove_fillers" not in calls
        assert rec.caption_kwargs[0]["hook_title"] == "h"  # default ON


# -- P3-B default filler adapter (_lazy_remove_fillers) ----------------------


class TestLazyRemoveFillersStage:
    def test_builds_cutlist_runs_argv_and_remaps_cues(self, monkeypatch):
        from media_studio import ffmpeg

        ran: dict[str, Any] = {}
        monkeypatch.setattr(ffmpeg, "ffmpeg_path", lambda settings=None: "/bin/ffmpeg")
        monkeypatch.setattr(ffmpeg, "run", lambda argv, **kw: ran.setdefault("argv", argv) and 0 or 0)

        # Two real words with an "um" filler in the middle (clip-local).
        words = [
            {"text": "people", "start": 0.0, "end": 0.5},
            {"text": "um", "start": 0.6, "end": 1.0},
            {"text": "buy", "start": 2.0, "end": 2.4},
        ]
        cues = [{"index": 1, "start": 0.0, "end": 2.4, "text": "people um buy"}]
        out_path, remapped, stats = sm._lazy_remove_fillers("in.mp4", "out.mp4", words, cues, lang="en", settings={})
        assert out_path == "out.mp4"
        assert ran["argv"][0] == "/bin/ffmpeg"
        # The "um" filler was removed -> at least one filler word counted.
        assert stats["fillersRemoved"] >= 1
        assert stats["fillerSeconds"] > 0.0
        # Cues survive (remapped onto the compressed timeline).
        assert isinstance(remapped, list)

    def test_no_keeps_degenerate_returns_input_unchanged(self, monkeypatch):
        from media_studio.features import fillers

        # Force an empty keep-list (degenerate) — the stage returns the input.
        monkeypatch.setattr(fillers, "build_cutlist_with_stats", lambda *a, **k: ([], {}))
        cues = [{"index": 1, "start": 0.0, "end": 1.0, "text": "x"}]
        out_path, remapped, stats = sm._lazy_remove_fillers("in.mp4", "out.mp4", [], cues, lang="en", settings={})
        assert out_path == "in.mp4"  # no cut made
        assert remapped == cues
        assert stats == {"fillersRemoved": 0, "fillerSeconds": 0.0}


# -- P4 §3/C5: the export writes a primary <clip>.json metadata sidecar --------


class TestExportWritesShortMetadata:
    """``_export_one`` writes ``<clip>.json`` next to the mp4 (PLAN-P4 C5 — the
    PRIMARY path that makes ``shorts.list`` non-empty), carrying the §3 export
    fields with hook / template / viralityPct / duration all in scope."""

    def _candidate(self, **over):
        cand = {
            "rank": 1,
            "start": 0.0,
            "end": 25.0,
            "durationSec": 25.0,
            "hook": "A bold hook",
            "why": "w",
            "score": 9,
            "sourceStart": 0.0,
            "viralityPct": 87,
        }
        cand.update(over)
        return cand

    def test_metadata_json_written_next_to_mp4(self, transcript, tmp_path):
        rec = RecordingStages([])
        sm.run_export(
            make_ctx(),
            video_id="v1",
            candidates=[self._candidate()],
            load_context=loader_for(str(tmp_path / "src.mp4"), transcript, sourceTitle="My Talk"),
            out_dir=str(tmp_path / "out"),
            stages=rec.as_stages(),
            settings={"captionStyle": "hormozi"},
        )
        clip = tmp_path / "out" / "01-src.mp4"
        json_path = shorts_mod.metadata_path(clip)
        assert json_path.exists(), "the <clip>.json sidecar must be written"
        meta = json.loads(json_path.read_text(encoding="utf-8"))
        assert meta["videoId"] == "v1"
        assert meta["sourceTitle"] == "My Talk"
        assert meta["template"] == "hormozi"
        assert meta["viralityPct"] == 87
        assert meta["durationSec"] == pytest.approx(25.0)
        assert meta["hook"] == "A bold hook"
        assert meta["createdAt"] > 0.0

    def test_metadata_fields_match_section3_schema(self, transcript, tmp_path):
        rec = RecordingStages([])
        sm.run_export(
            make_ctx(),
            video_id="v1",
            candidates=[self._candidate()],
            load_context=loader_for(str(tmp_path / "src.mp4"), transcript),
            out_dir=str(tmp_path / "out"),
            stages=rec.as_stages(),
            settings={"captionStyle": "bold"},
        )
        meta = json.loads(shorts_mod.metadata_path(tmp_path / "out" / "01-src.mp4").read_text("utf-8"))
        assert set(meta) == set(shorts_mod.META_FIELDS)

    def test_metadata_template_blank_when_no_caption_style(self, transcript, tmp_path):
        rec = RecordingStages([])
        sm.run_export(
            make_ctx(),
            video_id="v1",
            candidates=[self._candidate()],
            load_context=loader_for(str(tmp_path / "src.mp4"), transcript),
            out_dir=str(tmp_path / "out"),
            stages=rec.as_stages(),
            settings={},  # no captionStyle override
        )
        meta = json.loads(shorts_mod.metadata_path(tmp_path / "out" / "01-src.mp4").read_text("utf-8"))
        assert meta["template"] == ""

    def test_metadata_prefers_calibrated_pct_over_virality(self, transcript, tmp_path):
        """calibratedPct REPLACES viralityPct in the candidate (features.feedback)."""
        rec = RecordingStages([])
        sm.run_export(
            make_ctx(),
            video_id="v1",
            candidates=[self._candidate(calibratedPct=42)],
            load_context=loader_for(str(tmp_path / "src.mp4"), transcript),
            out_dir=str(tmp_path / "out"),
            stages=rec.as_stages(),
            settings={"captionStyle": "neon"},
        )
        meta = json.loads(shorts_mod.metadata_path(tmp_path / "out" / "01-src.mp4").read_text("utf-8"))
        assert meta["viralityPct"] == 42

    def test_metadata_virality_null_when_absent(self, transcript, tmp_path):
        rec = RecordingStages([])
        sm.run_export(
            make_ctx(),
            video_id="v1",
            candidates=[self._candidate(viralityPct=None)],
            load_context=loader_for(str(tmp_path / "src.mp4"), transcript),
            out_dir=str(tmp_path / "out"),
            stages=rec.as_stages(),
            settings={},
        )
        meta = json.loads(shorts_mod.metadata_path(tmp_path / "out" / "01-src.mp4").read_text("utf-8"))
        assert meta["viralityPct"] is None

    def test_metadata_hook_falls_back_to_candidate_when_hooktitle_off(self, transcript, tmp_path):
        # Even with hookTitle OFF (no burned title), the metadata still records
        # the candidate's hook text for the gallery.
        rec = RecordingStages([])
        sm.run_export(
            make_ctx(),
            video_id="v1",
            candidates=[self._candidate(hook="still recorded")],
            load_context=loader_for(str(tmp_path / "src.mp4"), transcript),
            out_dir=str(tmp_path / "out"),
            stages=rec.as_stages(),
            settings={"hookTitle": False},
        )
        meta = json.loads(shorts_mod.metadata_path(tmp_path / "out" / "01-src.mp4").read_text("utf-8"))
        assert meta["hook"] == "still recorded"

    def test_metadata_written_for_every_clip(self, transcript, tmp_path):
        rec = RecordingStages([])
        cands = [
            self._candidate(rank=1, start=0.0, end=25.0, sourceStart=0.0),
            self._candidate(rank=2, start=30.0, end=55.0, sourceStart=30.0),
        ]
        sm.run_export(
            make_ctx(),
            video_id="v1",
            candidates=cands,
            load_context=loader_for(str(tmp_path / "talk.mp4"), transcript),
            out_dir=str(tmp_path / "out"),
            stages=rec.as_stages(),
            settings={"captionStyle": "bold"},
        )
        for rank in (1, 2):
            clip = tmp_path / "out" / f"{rank:02d}-talk.mp4"
            assert shorts_mod.metadata_path(clip).exists()

    def test_listing_reconstructs_short_from_written_metadata(self, transcript, tmp_path):
        # End-to-end with no mock between writer and reader: export writes the
        # .json, shorts.list reads it back into a ShortInfo (the C5 contract).
        rec = RecordingStages([])
        out_dir = tmp_path / "exports" / "shorts-v1"
        sm.run_export(
            make_ctx(),
            video_id="v1",
            candidates=[self._candidate()],
            load_context=loader_for(str(tmp_path / "src.mp4"), transcript, sourceTitle="My Talk"),
            out_dir=str(out_dir),
            stages=rec.as_stages(),
            settings={"captionStyle": "hormozi"},
        )
        # The mocked export stage doesn't actually encode an mp4; materialize the
        # final file so shorts.list (which globs *.mp4) can pick it up. The .json
        # the real pipeline writes is already on disk.
        (out_dir / "01-src.mp4").write_bytes(b"\x00fake-mp4")
        svc = shorts_mod.Shorts(
            exports_dir=tmp_path / "exports",
            probe=lambda p, s=None: (1080, 1920),
        )
        result = svc.list(
            {"videoId": "v1"},
            RpcContext(emit_notification=lambda obj: None, jobs=None),
        )
        assert len(result["shorts"]) == 1
        info = result["shorts"][0]
        assert info["videoId"] == "v1"
        assert info["sourceTitle"] == "My Talk"
        assert info["template"] == "hormozi"
        assert info["viralityPct"] == 87
        assert info["hook"] == "A bold hook"


# ---------------------------------------------------------------------------
# default stage adapters (_lazy_*) — the production seam bindings.
#
# Each default adapter binds to a sibling feature module / ffmpeg lazily. We
# patch those collaborators (no provider / verthor / scenedetect / real ffmpeg)
# and assert the adapter wires args through + returns the contract shape.
# ---------------------------------------------------------------------------
class TestLazySelectStage:
    def test_builds_provider_and_normalizes_candidates_to_dicts(self, monkeypatch):
        import media_studio.features.select as sel
        from media_studio.models import provider as prov

        seen: dict[str, Any] = {}
        sentinel_provider = object()
        monkeypatch.setattr(prov, "get_provider", lambda settings: sentinel_provider)

        def fake_select(transcript, prompt, controls, provider):
            seen["provider"] = provider
            seen["prompt"] = prompt
            # select returns its own TypedDict rows; the seam must dict()-copy them.
            return [{"rank": 1, "start": 0.0, "end": 25.0, "score": 9}]

        monkeypatch.setattr(sel, "select", fake_select)
        out = sm._lazy_select({"segments": []}, "best", {"count": 1}, settings={"useCloud": False})
        assert seen["provider"] is sentinel_provider
        assert seen["prompt"] == "best"
        assert out == [{"rank": 1, "start": 0.0, "end": 25.0, "score": 9}]
        assert all(isinstance(c, dict) for c in out)

    def test_settings_none_defaults_to_empty(self, monkeypatch):
        import media_studio.features.select as sel
        from media_studio.models import provider as prov

        got_settings: dict[str, Any] = {}
        monkeypatch.setattr(prov, "get_provider", lambda settings: got_settings.update(settings) or object())
        monkeypatch.setattr(sel, "select", lambda *a, **k: [])
        sm._lazy_select({"segments": []}, "p", {}, settings=None)
        assert got_settings == {}  # None -> {}


class TestLazySnapStage:
    def test_flattens_words_and_passes_detectors(self, monkeypatch):
        import media_studio.features.boundary as boundary

        seen: dict[str, Any] = {}

        def fake_snap(candidates, words, *, silences, scene_cuts, duration_mode=None):
            seen.update(
                candidates=candidates,
                words=words,
                silences=silences,
                scene_cuts=scene_cuts,
                duration_mode=duration_mode,
            )
            return list(candidates), []

        monkeypatch.setattr(boundary, "snap_from_lists", fake_snap)
        transcript = {
            "segments": [
                {"words": [{"text": "a", "start": 0.0, "end": 1.0}]},
                {"words": [{"text": "b", "start": 1.0, "end": 2.0}]},
            ]
        }
        cands = [{"rank": 1, "start": 0.0, "end": 25.0}]
        kept, dropped = sm._lazy_snap(cands, transcript, settings={"silences": [(1, 2)], "sceneCuts": [3.0]})
        assert [w["text"] for w in seen["words"]] == ["a", "b"]
        assert seen["silences"] == [(1, 2)]
        assert seen["scene_cuts"] == [3.0]
        # No controls -> no duration_mode override (standard 20-60 window applies).
        assert seen["duration_mode"] is None
        assert kept == cands and dropped == []

    def test_threads_duration_mode_from_controls(self, monkeypatch):
        """SEL1: ``durationMode`` from controls reaches ``snap_from_lists`` (clamped)."""
        import media_studio.features.boundary as boundary

        seen: dict[str, Any] = {}

        def fake_snap(candidates, words, *, silences, scene_cuts, duration_mode=None):
            seen["duration_mode"] = duration_mode
            return list(candidates), []

        monkeypatch.setattr(boundary, "snap_from_lists", fake_snap)
        sm._lazy_snap([], {"segments": []}, controls={"durationMode": "midform"})
        assert seen["duration_mode"] == "midform"
        # A typo fails closed to the conservative standard envelope (shared clamp).
        sm._lazy_snap([], {"segments": []}, controls={"durationMode": "bogus"})
        assert seen["duration_mode"] == "standard"

    def test_settings_none_passes_none_detectors(self, monkeypatch):
        import media_studio.features.boundary as boundary

        seen: dict[str, Any] = {}
        monkeypatch.setattr(
            boundary,
            "snap_from_lists",
            lambda c, w, *, silences, scene_cuts, duration_mode=None: (
                seen.update(silences=silences, scene_cuts=scene_cuts) or (c, [])
            ),
        )
        sm._lazy_snap([], {"segments": []}, settings=None)
        assert seen["silences"] is None and seen["scene_cuts"] is None


class TestLazyCutStage:
    def test_builds_frame_accurate_argv_and_runs(self, monkeypatch):
        from media_studio import ffmpeg

        ran: dict[str, Any] = {}
        monkeypatch.setattr(ffmpeg, "ffmpeg_path", lambda settings=None: "/bin/ffmpeg")
        monkeypatch.setattr(ffmpeg, "run", lambda argv, **kw: ran.setdefault("argv", argv) and 0 or 0)
        out = sm._lazy_cut("/src.mp4", "/out.cut.mp4", 10.0, 40.0, settings={})
        assert out == "/out.cut.mp4"
        argv = ran["argv"]
        assert argv[0] == "/bin/ffmpeg"
        # accurate seek: -ss/-to AFTER -i (decode-then-trim).
        assert argv.index("-i") < argv.index("-ss") < argv.index("-to")
        assert argv[argv.index("-ss") + 1] == "10.000"
        assert argv[argv.index("-to") + 1] == "40.000"
        assert argv[argv.index("-c:v") + 1] == "libx264"
        assert argv[-1] == "/out.cut.mp4"


class TestLazyReframeStage:
    def test_resolves_engine_and_reframes(self, monkeypatch):
        import media_studio.features.reframe as reframe

        class FakeEngine:
            def __init__(self):
                self.calls: list[tuple] = []

            def reframe(self, in_path, out_path, aspect, *, on_notice=None):
                self.calls.append((in_path, out_path, aspect, on_notice))
                return out_path

        engine = FakeEngine()
        seen: dict[str, Any] = {}

        def fake_get_engine(name, settings):
            seen["name"] = name
            return engine, None

        monkeypatch.setattr(reframe, "get_engine", fake_get_engine)
        sink = lambda n: None  # noqa: E731 - stable identity for the assert
        out = sm._lazy_reframe(
            "/in.mp4", "/out.reframed.mp4", "9:16", settings={"reframeEngine": "verthor"}, on_notice=sink
        )
        assert out == "/out.reframed.mp4"
        assert seen["name"] == "verthor"
        # the on_notice sink is threaded through to the engine's reframe()
        assert engine.calls == [("/in.mp4", "/out.reframed.mp4", "9:16", sink)]

    def test_defaults_to_auto_when_unset(self, monkeypatch):
        import media_studio.features.reframe as reframe

        seen: dict[str, Any] = {}

        class _E:
            def reframe(self, *a, on_notice=None):
                return a[1]

        monkeypatch.setattr(reframe, "get_engine", lambda name, settings: seen.update(name=name) or (_E(), None))
        sm._lazy_reframe("/in.mp4", "/out.mp4", "9:16", settings=None)
        assert seen["name"] == "auto"


class TestLazyStabilizeStage:
    def test_delegates_to_stabilize_clip(self, monkeypatch):
        import media_studio.features.stabilize as stabilize

        seen: dict[str, Any] = {}

        def fake(in_path, out_path, *, settings=None, on_notice=None):
            seen.update(in_path=in_path, out_path=out_path, on_notice=on_notice)
            return out_path

        monkeypatch.setattr(stabilize, "stabilize_clip", fake)
        notices: list = []
        sentinel = lambda n: notices.append(n)  # noqa: E731 - stable identity for the assert
        out = sm._lazy_stabilize("/in.mp4", "/out.stab.mp4", settings={}, on_notice=sentinel)
        assert out == "/out.stab.mp4"
        assert seen["on_notice"] is sentinel  # the on_notice sink is threaded through


class TestLazyTrimSilenceStage:
    def test_delegates_to_trim_clip(self, monkeypatch):
        import media_studio.features.silencetrim as silencetrim

        # trim_clip now also returns the clip-local KEEP spans so the orchestrator
        # can remap caption cues onto the compacted timeline (cue-desync fix).
        seen: dict[str, Any] = {}
        monkeypatch.setattr(
            silencetrim,
            "trim_clip",
            lambda i, o, *, settings=None, on_notice=None: (
                seen.update(on_notice=on_notice) or (o, 3.25, [(0.0, 4.0), (6.0, 12.0)])
            ),
        )
        sink = lambda n: None  # noqa: E731 - stable identity for the assert
        out_path, removed, keeps = sm._lazy_trim_silence("/in.mp4", "/out.trim.mp4", settings={}, on_notice=sink)
        assert out_path == "/out.trim.mp4"
        assert removed == pytest.approx(3.25)
        assert keeps == [(0.0, 4.0), (6.0, 12.0)]
        assert seen["on_notice"] is sink  # the notice sink is threaded through


class TestLazyZoomStage:
    def test_builds_zoom_argv_and_runs(self, monkeypatch):
        from media_studio import ffmpeg
        from media_studio.features import zoom

        seen: dict[str, Any] = {}
        monkeypatch.setattr(
            zoom,
            "build_zoom_argv",
            lambda in_path, out_path, **kw: seen.update(kw, in_path=in_path, out_path=out_path) or ["ff", out_path],
        )
        monkeypatch.setattr(ffmpeg, "run", lambda argv, **kw: seen.setdefault("argv", argv) and 0 or 0)
        cues = [{"index": 1, "start": 0.0, "end": 2.0, "text": "hi"}]
        out = sm._lazy_zoom("/in.mp4", "/out.zoom.mp4", cues, source_start=5.0, duration_sec=30.0, settings={})
        assert out == "/out.zoom.mp4"
        assert seen["width"] == sm.OUT_WIDTH and seen["height"] == sm.OUT_HEIGHT
        assert seen["duration_sec"] == pytest.approx(30.0)
        assert seen["source_start"] == pytest.approx(5.0)
        assert seen["cues"] == cues
        assert seen["argv"][-1] == "/out.zoom.mp4"


class TestLazyBrandOverlayStage:
    def test_builds_overlay_argv_and_runs(self, monkeypatch):
        from media_studio import ffmpeg
        from media_studio.features import brandkit

        seen: dict[str, Any] = {}
        monkeypatch.setattr(
            brandkit,
            "build_logo_overlay_argv",
            lambda in_path, logo, out_path, *, settings=None: (
                seen.update(in_path=in_path, logo=logo, out_path=out_path) or ["ff", out_path]
            ),
        )
        monkeypatch.setattr(ffmpeg, "run", lambda argv, **kw: seen.setdefault("argv", argv) and 0 or 0)
        out = sm._lazy_brand_overlay("/in.mp4", "/out.brand.mp4", "/logo.png", settings={})
        assert out == "/out.brand.mp4"
        assert seen["logo"] == "/logo.png"
        assert seen["argv"][-1] == "/out.brand.mp4"


class TestLazyExportStage:
    def test_builds_convert_argv_and_runs(self, monkeypatch):
        from media_studio import ffmpeg

        seen: dict[str, Any] = {}

        def fake_convert(in_path, out_path, codecs, settings):
            seen.update(in_path=in_path, out_path=out_path, codecs=codecs)
            return ["ff", out_path]

        monkeypatch.setattr(ffmpeg, "build_convert_argv", fake_convert)
        monkeypatch.setattr(ffmpeg, "run", lambda argv, **kw: seen.setdefault("argv", argv) and 0 or 0)
        out = sm._lazy_export("/in.mp4", "/final.mp4", settings={})
        assert out == "/final.mp4"
        assert seen["codecs"] == {"vcodec": "libx264", "acodec": "aac"}
        assert seen["argv"][-1] == "/final.mp4"


# ---------------------------------------------------------------------------
# pure helper edge cases
# ---------------------------------------------------------------------------
def test_cues_for_clip_skips_blank_text_word_spans():
    # A word span with only whitespace text is skipped (no cue produced).
    transcript = {
        "segments": [
            {
                "start": 0.0,
                "end": 30.0,
                "text": "seg",
                "words": [
                    {"text": "   ", "start": 5.0, "end": 6.0},  # blank -> skipped
                    {"text": "real", "start": 7.0, "end": 8.0},
                ],
            }
        ]
    }
    cues = sm._cues_for_clip(transcript, {"sourceStart": 0.0, "end": 30.0})
    assert [c["text"] for c in cues] == ["real"]


def test_clip_local_words_skips_untimed_words():
    transcript = {
        "segments": [
            {
                "words": [
                    {"text": "ok", "start": 25.0, "end": 26.0},  # in window
                    {"text": "untimed", "start": None, "end": None},  # skipped
                    {"text": "early", "start": 1.0, "end": 2.0},  # before window
                ]
            }
        ]
    }
    out = sm._clip_local_words(transcript, source_start=20.0, end=45.0)
    assert [w["text"] for w in out] == ["ok"]
    assert out[0]["start"] == pytest.approx(5.0)  # 25 - 20 (re-based)


def test_rebase_cues_drops_cues_ending_before_in_point():
    cues = [
        {"start": 5.0, "end": 8.0, "text": "before"},  # wholly before in-point -> dropped
        {"start": 25.0, "end": 28.0, "text": "kept"},
    ]
    out = sm._rebase_cues(cues, source_start=20.0)
    assert [c["text"] for c in out] == ["kept"]
    assert out[0]["index"] == 1  # renumbered from 1
    assert out[0]["start"] == pytest.approx(5.0)  # 25 - 20


def test_candidate_virality_non_numeric_returns_none():
    # A non-numeric calibratedPct/viralityPct -> None (never crashes export).
    assert sm._candidate_virality({"viralityPct": "junk"}) is None
    assert sm._candidate_virality({"calibratedPct": object()}) is None
    assert sm._candidate_virality({}) is None
    assert sm._candidate_virality({"viralityPct": 42}) == 42


# ---------------------------------------------------------------------------
# run_export — reframe-engine fallback notice + per-export notice de-dup
# ---------------------------------------------------------------------------
def test_run_export_default_engine_is_claudeshorts_no_wsl(transcript, tmp_path, monkeypatch):
    """P3: with no reframeEngine set, run_export resolves the in-sidecar
    claudeshorts engine WITHOUT probing WSL (no wsl.exe needed), pins that
    CONCRETE name into the settings handed to the reframe stage, and surfaces no
    fallback notice."""
    import media_studio.features.reframe as reframe_mod

    # which() must NEVER run: auto -> claudeshorts is decided with zero WSL probe.
    def _never_which(_name):  # pragma: no cover - asserted by not being called
        raise AssertionError("WSL must not be probed for the default engine")

    monkeypatch.setattr(reframe_mod.shutil, "which", _never_which)

    seen: dict[str, object] = {}

    class _CaptureStages(RecordingStages):
        def reframe(self, in_path, out_path, aspect, *, settings=None, on_notice=None):
            seen["engine"] = (settings or {}).get("reframeEngine")
            return super().reframe(in_path, out_path, aspect, settings=settings, on_notice=on_notice)

    progress: list[tuple[int, str]] = []
    ctx = JobContext(
        job_id="j1",
        _cancel_event=threading.Event(),
        _emit_progress=lambda jid, pct, msg: progress.append((pct, msg)),
    )
    rec = _CaptureStages([])
    candidate = {"rank": 1, "start": 0.0, "end": 25.0, "sourceStart": 0.0, "score": 9}
    sm.run_export(
        ctx,
        video_id="v1",
        candidates=[candidate],
        load_context=loader_for(str(tmp_path / "src.mp4"), transcript),
        out_dir=str(tmp_path / "out"),
        stages=rec.as_stages(),
    )
    assert seen["engine"] == "claudeshorts"
    assert not any("fallback" in msg.lower() for _pct, msg in progress)


def test_run_export_dedupes_repeated_stabilize_notice(transcript, tmp_path):
    """The same notice across N clips is announced ONCE (de-dup by type)."""
    progress: list[tuple[int, str]] = []

    def passthrough(in_path, out_path, on_notice):
        if on_notice is not None:
            on_notice({"type": "stabilize.unavailable", "message": "no libvidstab — skipped"})
        return in_path

    rec = RecordingStages([], stabilize_impl=passthrough)
    ctx = JobContext(
        job_id="j1",
        _cancel_event=threading.Event(),
        _emit_progress=lambda jid, pct, msg: progress.append((pct, msg)),
    )
    cands = [
        {"rank": 1, "start": 0.0, "end": 25.0, "sourceStart": 0.0, "score": 9},
        {"rank": 2, "start": 30.0, "end": 55.0, "sourceStart": 30.0, "score": 8},
    ]
    sm.run_export(
        ctx,
        video_id="v1",
        candidates=cands,
        load_context=loader_for(str(tmp_path / "src.mp4"), transcript),
        out_dir=str(tmp_path / "out"),
        stages=rec.as_stages(),
        settings={"stabilize": True},
    )
    # Two clips both emit the same typed notice, but it is surfaced only once.
    libvidstab_msgs = [msg for _pct, msg in progress if "libvidstab" in msg]
    assert len(libvidstab_msgs) == 1
