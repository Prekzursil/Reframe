"""Tests for features/nle_export.py (captions-export: CMX3600 EDL + CSV).

Pure-logic unit tests — no subprocess, no NLE, no network. They assert the
timecode math at each selectable fps, the contiguous-record EDL layout, reel
sanitizing, per-clip reel names, the CSV shape, and the file-writing ``export``.
Mirrors the style of test_subtitles.py / test_shorts.py.
"""

from __future__ import annotations

import csv as _csv
import io
from pathlib import Path

import pytest
from media_studio.features import nle_export as nle


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #
def make_clips() -> list[dict]:
    """Two approved clips ({candidate, path}) with source windows + hooks."""
    return [
        {
            "candidate": {"rank": 1, "sourceStart": 10.0, "end": 25.0, "hook": "Crazy moment"},
            "path": "/footage/clip_one.mp4",
        },
        {
            "candidate": {
                "rank": 2,
                "sourceStart": 40.0,
                "end": 52.0,
                "hook": "Big reveal",
                "reel": "tape-02",
            },
            "path": "/footage/clip_two.mp4",
        },
    ]


# --------------------------------------------------------------------------- #
# fps + timecode
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("fps", nle.FPS_CHOICES)
def test_normalize_fps_accepts_all_choices(fps: int) -> None:
    assert nle.normalize_fps(fps) == fps
    assert nle.normalize_fps(str(fps)) == fps  # string coercion


@pytest.mark.parametrize("bad", [0, 23, 29, 120, "thirty", None, 23.976])
def test_normalize_fps_rejects_others(bad: object) -> None:
    with pytest.raises(ValueError):
        nle.normalize_fps(bad)


def test_seconds_to_timecode_per_fps() -> None:
    # 10s is a whole second -> :00 frames at every rate.
    assert nle.seconds_to_timecode(10.0, 24) == "00:00:10:00"
    assert nle.seconds_to_timecode(10.0, 60) == "00:00:10:00"
    # Half a second -> half the fps in frames.
    assert nle.seconds_to_timecode(0.5, 30) == "00:00:00:15"
    assert nle.seconds_to_timecode(0.5, 24) == "00:00:00:12"
    assert nle.seconds_to_timecode(0.5, 60) == "00:00:00:30"


def test_timecode_hours_minutes_rollover() -> None:
    # 1h 2m 3s 4f at 30fps.
    total = (1 * 3600 + 2 * 60 + 3) * 30 + 4
    assert nle.frames_to_timecode(total, 30) == "01:02:03:04"


def test_seconds_to_timecode_clamps_negative() -> None:
    assert nle.seconds_to_timecode(-5.0, 30) == "00:00:00:00"


# --------------------------------------------------------------------------- #
# reel sanitizing
# --------------------------------------------------------------------------- #
def test_sanitize_reel_uppercases_strips_truncates() -> None:
    assert nle.sanitize_reel("tape-02") == "TAPE02"
    assert nle.sanitize_reel("my reel name here") == "MYREELNA"  # <= 8 chars
    assert nle.sanitize_reel("") == nle.DEFAULT_REEL
    assert nle.sanitize_reel(None) == nle.DEFAULT_REEL
    assert nle.sanitize_reel("!!!") == nle.DEFAULT_REEL  # all-stripped -> default


# --------------------------------------------------------------------------- #
# clips -> events
# --------------------------------------------------------------------------- #
def test_clips_to_events_contiguous_record() -> None:
    events = nle.clips_to_events(make_clips(), 30)
    assert [e["index"] for e in events] == [1, 2]
    # Record side is back-to-back: event 2 record-in == event 1 record-out.
    assert events[0]["recordInFrames"] == 0
    assert events[1]["recordInFrames"] == events[0]["recordOutFrames"]
    # Source windows come from sourceStart -> end.
    assert events[0]["sourceInFrames"] == 10 * 30
    assert events[0]["sourceOutFrames"] == 25 * 30


def test_clips_to_events_per_clip_reel() -> None:
    events = nle.clips_to_events(make_clips(), 30)
    assert events[0]["reel"] == "AX"  # first clip, no explicit reel
    assert events[1]["reel"] == "TAPE02"  # candidate.reel sanitized


def test_clips_to_events_uses_duration_when_end_missing() -> None:
    clips = [{"candidate": {"rank": 1, "sourceStart": 5.0, "durationSec": 10.0}, "path": "/a.mp4"}]
    events = nle.clips_to_events(clips, 30)
    assert events[0]["sourceOutFrames"] == events[0]["sourceInFrames"] + 10 * 30


def test_clips_to_events_minimum_one_frame() -> None:
    # A zero-length clip still yields a real (>=1 frame) event.
    clips = [{"candidate": {"rank": 1, "sourceStart": 5.0, "end": 5.0}, "path": "/a.mp4"}]
    events = nle.clips_to_events(clips, 30)
    assert events[0]["sourceOutFrames"] - events[0]["sourceInFrames"] == 1


def test_clips_to_events_skips_non_dict() -> None:
    events = nle.clips_to_events(["bad", None, make_clips()[0]], 30)  # type: ignore[list-item]
    assert len(events) == 1


def test_clips_to_events_flat_candidate_shape() -> None:
    # A flat candidate dict (no {candidate} wrapper) also works.
    events = nle.clips_to_events([{"rank": 1, "sourceStart": 1.0, "end": 2.0, "path": "/x.mp4"}], 30)
    assert events[0]["clipName"] == "x.mp4"


def test_clips_to_events_empty_path_yields_blank_clipname() -> None:
    # No path on the clip OR candidate -> _clip_basename("") returns "".
    events = nle.clips_to_events([{"candidate": {"sourceStart": 1.0, "end": 2.0}}], 30)
    assert events[0]["clipName"] == ""
    assert events[0]["sourcePath"] == ""


def test_clips_to_events_end_before_start_clamps_to_start() -> None:
    # An inverted window (end < sourceStart) clamps source_out up to source_in
    # (then the >=1-frame floor makes it a single-frame event).
    events = nle.clips_to_events([{"candidate": {"sourceStart": 10.0, "end": 4.0}, "path": "/a.mp4"}], 30)
    assert events[0]["sourceInFrames"] == 10 * 30
    assert events[0]["sourceOutFrames"] == 10 * 30 + 1


# --------------------------------------------------------------------------- #
# EDL
# --------------------------------------------------------------------------- #
def test_build_edl_header_and_events() -> None:
    edl = nle.build_edl(nle.clips_to_events(make_clips(), 30), title="My Cut", fps=30)
    lines = edl.splitlines()
    assert lines[0] == "TITLE: My Cut"
    assert lines[1] == "FCM: NON-DROP FRAME"
    assert "001  AX" in edl
    assert "002  TAPE02" in edl
    assert "* FROM CLIP NAME: clip_one.mp4" in edl
    assert "* COMMENT: Crazy moment" in edl
    # Contiguous record: event 1 rec-out becomes event 2 rec-in.
    assert "00:00:00:00 00:00:15:00" in edl  # rec window of event 1


def test_build_edl_event_line_columns() -> None:
    edl = nle.build_edl(nle.clips_to_events(make_clips()[:1], 30), fps=30)
    cut = next(line for line in edl.splitlines() if line.startswith("001"))
    # num reel chan transition src-in src-out rec-in rec-out
    assert "V" in cut and "C" in cut
    assert "00:00:10:00" in cut  # src-in
    assert "00:00:25:00" in cut  # src-out


def test_build_edl_title_sanitizes_whitespace() -> None:
    edl = nle.build_edl([], title="line one\nline two\t  end")
    assert edl.splitlines()[0] == "TITLE: line one line two end"


def test_build_edl_omits_comment_lines_when_clipname_and_hook_blank() -> None:
    # A clip with neither a name nor a hook emits only the cut line — both the
    # "* FROM CLIP NAME:" and "* COMMENT:" comment lines are skipped.
    events = nle.clips_to_events([{"candidate": {"sourceStart": 1.0, "end": 2.0}}], 30)
    edl = nle.build_edl(events, fps=30)
    assert "* FROM CLIP NAME:" not in edl
    assert "* COMMENT:" not in edl
    cut_lines = [line for line in edl.splitlines() if line.startswith("001")]
    assert len(cut_lines) == 1


# --------------------------------------------------------------------------- #
# CSV
# --------------------------------------------------------------------------- #
def test_build_csv_header_and_rows() -> None:
    text = nle.build_csv(nle.clips_to_events(make_clips(), 25), fps=25)
    rows = list(_csv.reader(io.StringIO(text)))
    assert rows[0] == list(nle.CSV_COLUMNS)
    assert len(rows) == 3  # header + 2 clips
    assert rows[1][1] == "AX"  # reel
    assert rows[2][1] == "TAPE02"
    assert rows[1][4] == "00:00:10:00"  # sourceIn at 25fps


def test_build_csv_crlf_lineterminator() -> None:
    text = nle.build_csv(nle.clips_to_events(make_clips()[:1], 30), fps=30)
    assert "\r\n" in text


# --------------------------------------------------------------------------- #
# format dispatch
# --------------------------------------------------------------------------- #
def test_normalize_format() -> None:
    assert nle.normalize_format("EDL") == "edl"
    assert nle.normalize_format(".csv") == "csv"
    with pytest.raises(ValueError):
        nle.normalize_format("xml")


def test_serialize_dispatch() -> None:
    events = nle.clips_to_events(make_clips(), 30)
    assert nle.serialize(events, "edl", fps=30).startswith("TITLE:")
    assert nle.serialize(events, "csv", fps=30).startswith("index,")


# --------------------------------------------------------------------------- #
# export (file I/O)
# --------------------------------------------------------------------------- #
def test_export_writes_edl(tmp_path: Path) -> None:
    out = tmp_path / "seq.edl"
    path = nle.export(make_clips(), out, fmt="edl", fps=24, title="Cut")
    assert Path(path) == out
    body = out.read_text(encoding="utf-8")
    assert body.startswith("TITLE: Cut")
    assert "FCM: NON-DROP FRAME" in body


def test_export_writes_csv(tmp_path: Path) -> None:
    out = tmp_path / "seq.csv"
    path = nle.export(make_clips(), out, fmt="csv", fps=60)
    assert Path(path).exists()
    assert out.read_text(encoding="utf-8").startswith("index,")


def test_export_empty_clips_still_writes(tmp_path: Path) -> None:
    out = tmp_path / "empty.edl"
    nle.export([], out, fmt="edl", fps=30)
    # Header-only but importable.
    assert out.read_text(encoding="utf-8").startswith("TITLE:")


def test_export_creates_parent_dirs(tmp_path: Path) -> None:
    out = tmp_path / "nested" / "deep" / "seq.csv"
    nle.export(make_clips(), out, fmt="csv", fps=30)
    assert out.exists()


def test_export_rejects_bad_format(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        nle.export(make_clips(), tmp_path / "x.xml", fmt="xml")


def test_export_rejects_bad_fps(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        nle.export(make_clips(), tmp_path / "x.edl", fmt="edl", fps=99)
