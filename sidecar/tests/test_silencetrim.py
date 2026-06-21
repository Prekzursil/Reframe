"""Tests for features/silencetrim.py (audio-stabilize group — dead-air removal).

Pure span math is tested directly; detection + the re-cut go through the
documented seams (a fabricated silencedetect stderr ``detect_run`` and a
recording ffmpeg ``run``). No subprocess is ever spawned. Mirrors test_shorts.py.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from media_studio import protocol
from media_studio.features import silencetrim as stm
from media_studio.jobs import JobRegistry
from media_studio.protocol import RpcContext, RpcError


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


class RecordingRun:
    def __init__(self, code: int = 0) -> None:
        self.code = code
        self.calls: list[list[str]] = []

    def __call__(self, argv, *, total_sec: float = 0.0, on_progress=None, should_cancel=None) -> int:
        self.calls.append(list(argv))
        if self.code == 0:
            Path(argv[-1]).write_bytes(b"\x00mp4")
        return self.code


def detect_with(stderr: str) -> stm.DetectRunner:
    class Completed:
        returncode = 0
        stdout = ""

    def runner(argv, **kw):
        c = Completed()
        c.stderr = stderr
        return c

    return runner


# A silencedetect stderr with two silent gaps: [3,5] and [12,15].
SILENCE_STDERR = (
    "[silencedetect @ 0x1] silence_start: 3.0\n"
    "[silencedetect @ 0x1] silence_end: 5.0 | silence_duration: 2.0\n"
    "[silencedetect @ 0x1] silence_start: 12.0\n"
    "[silencedetect @ 0x1] silence_end: 15.0 | silence_duration: 3.0\n"
)


def _rpc_ctx(registry: JobRegistry) -> RpcContext:
    return RpcContext(emit_notification=lambda obj: None, jobs=registry)


# --------------------------------------------------------------------------- #
# pure: parse + invert + accounting
# --------------------------------------------------------------------------- #
class TestPureSpans:
    def test_parse_pairs_starts_and_ends(self):
        spans = stm.parse_silence_spans(SILENCE_STDERR)
        assert spans == [(3.0, 5.0), (12.0, 15.0)]

    def test_unpaired_trailing_start_ignored(self):
        s = "silence_start: 10.0\n"  # no matching end before EOF
        assert stm.parse_silence_spans(s) == []

    def test_keep_spans_invert_with_padding(self):
        # total=20, silences [3,5] & [12,15], pad 0.1 -> keeps leave 0.1 on edges.
        keeps = stm.keep_spans([(3.0, 5.0), (12.0, 15.0)], 20.0, pad_sec=0.1)
        assert keeps == [(0.0, 3.1), (4.9, 12.1), (14.9, 20.0)]

    def test_keep_spans_no_silence_is_full_clip(self):
        assert stm.keep_spans([], 10.0) == [(0.0, 10.0)]

    def test_keep_spans_zero_total_is_empty(self):
        assert stm.keep_spans([(1.0, 2.0)], 0.0) == []

    def test_keep_spans_coalesce_when_pad_covers_gap(self):
        # A tiny silence [5, 5.05] with pad 0.1 collapses (the pads overlap) so
        # the two keeps coalesce into one.
        keeps = stm.keep_spans([(5.0, 5.05)], 10.0, pad_sec=0.1)
        assert keeps == [(0.0, 10.0)]

    def test_removed_seconds(self):
        keeps = [(0.0, 3.0), (5.0, 12.0), (15.0, 20.0)]
        # kept = 3 + 7 + 5 = 15; total 20 -> 5 removed.
        assert stm.removed_seconds(keeps, 20.0) == pytest.approx(5.0)

    def test_parse_skips_zero_or_negative_span(self):
        # A silence_end <= silence_start is dropped (end > start is False) — the
        # paired but degenerate span never becomes a keep boundary.
        s = (
            "silence_start: 5.0\n"
            "silence_end: 5.0 | silence_duration: 0.0\n"  # end == start -> skipped
            "silence_start: 8.0\n"
            "silence_end: 10.0 | silence_duration: 2.0\n"
        )
        assert stm.parse_silence_spans(s) == [(8.0, 10.0)]

    def test_keep_spans_pad_swallows_leading_keep(self):
        # A silence at the very start (0..2) with a large pad makes keep_end<=cursor
        # for the first span, so no leading keep is appended (133->135 false branch).
        keeps = stm.keep_spans([(0.0, 2.0)], 10.0, pad_sec=0.0)
        assert keeps == [(2.0, 10.0)]

    def test_keep_spans_trailing_silence_to_eof_no_tail_keep(self):
        # Silence runs to the clip end: cursor reaches total, so the
        # `if cursor < total` tail-keep is skipped (136->140 false branch).
        keeps = stm.keep_spans([(3.0, 10.0)], 10.0, pad_sec=0.0)
        assert keeps == [(0.0, 3.0)]


# --------------------------------------------------------------------------- #
# detection
# --------------------------------------------------------------------------- #
class TestDetect:
    def test_detect_uses_silencedetect_argv(self, settings):
        spans = stm.detect_silence_spans("/in.mp4", settings=settings, run=detect_with(SILENCE_STDERR))
        assert spans == [(3.0, 5.0), (12.0, 15.0)]

    def test_detect_failure_returns_empty(self, settings):
        def boom(argv, **kw):
            raise OSError("ffmpeg died")

        assert stm.detect_silence_spans("/in.mp4", settings=settings, run=boom) == []

    def test_detect_no_ffmpeg_resolvable_returns_empty(self, monkeypatch):
        # ffmpeg.ffmpeg_path raising (no binary) -> [] (a detection miss must not
        # fail the pipeline) without ever spawning the runner.
        from media_studio import ffmpeg as _ffmpeg

        def boom_path(s=None):
            raise _ffmpeg.FfmpegNotFound("nope")

        monkeypatch.setattr(_ffmpeg, "ffmpeg_path", boom_path)
        assert stm.detect_silence_spans("/in.mp4", settings={}, run=detect_with("")) == []


# --------------------------------------------------------------------------- #
# pipeline pre-step adapter
# --------------------------------------------------------------------------- #
class TestTrimClip:
    def test_trim_recuts_keeps_and_reports_removed(self, settings, tmp_path):
        run = RecordingRun()
        out = str(tmp_path / "out.mp4")
        path, removed, keeps = stm.trim_clip(
            "/in.mp4",
            out,
            settings=settings,
            detect_run=detect_with(SILENCE_STDERR),
            run=run,
            duration=lambda p, s=None: 20.0,
        )
        assert path == out
        # 5s of dead air removed (2 + 3, minus the small padding kept).
        assert removed > 4.0
        # The re-cut used a filter_complex concat (fillers.build_segment_cut_argv).
        assert "-filter_complex" in run.calls[0]
        # The clip-local KEEP spans are returned (>1 keep, since interior silence
        # was removed) so the caller can remap caption cues onto the new timeline.
        assert len(keeps) > 1

    def test_trim_passthrough_when_no_silence(self, settings, tmp_path):
        run = RecordingRun()
        path, removed, keeps = stm.trim_clip(
            "/in.mp4",
            str(tmp_path / "out.mp4"),
            settings=settings,
            detect_run=detect_with(""),  # no silence detected
            run=run,
            duration=lambda p, s=None: 20.0,
        )
        # Pass-through: original path returned, no re-encode, nothing removed. The
        # keeps cover the whole clip (identity remap -> cues map through unchanged).
        assert path == "/in.mp4"
        assert removed == 0.0
        assert run.calls == []
        assert keeps == [(0.0, 20.0)]

    def test_trim_passthrough_when_duration_probe_raises(self, settings, tmp_path):
        # A probe failure means we can't trim safely -> pass through unchanged.
        def boom_duration(p, s=None):
            raise OSError("ffprobe died")

        path, removed, keeps = stm.trim_clip(
            "/in.mp4",
            str(tmp_path / "out.mp4"),
            settings=settings,
            detect_run=detect_with(SILENCE_STDERR),
            run=RecordingRun(),
            duration=boom_duration,
        )
        assert path == "/in.mp4" and removed == 0.0
        assert keeps == []  # no timeline -> nothing to remap

    def test_trim_passthrough_when_duration_unknown(self, settings, tmp_path):
        path, removed, keeps = stm.trim_clip(
            "/in.mp4",
            str(tmp_path / "out.mp4"),
            settings=settings,
            detect_run=detect_with(SILENCE_STDERR),
            run=RecordingRun(),
            duration=lambda p, s=None: 0.0,
        )
        assert path == "/in.mp4" and removed == 0.0
        assert keeps == []

    def test_trim_ffmpeg_failure_raises(self, settings, tmp_path):
        with pytest.raises(stm.SilenceTrimError, match="silence-trim re-cut"):
            stm.trim_clip(
                "/in.mp4",
                str(tmp_path / "out.mp4"),
                settings=settings,
                detect_run=detect_with(SILENCE_STDERR),
                run=RecordingRun(code=1),
                duration=lambda p, s=None: 20.0,
            )


# --------------------------------------------------------------------------- #
# the service
# --------------------------------------------------------------------------- #
class TestService:
    def test_trim_returns_jobId_and_result(self, settings, tmp_path, registry):
        svc = stm.SilenceTrim(
            resolver=lambda vid: "/lib/in.mp4",
            out_dir=tmp_path / "trim",
            settings_provider=lambda: settings,
            run=RecordingRun(),
            duration=lambda p, s=None: 20.0,
            detect_run=detect_with(SILENCE_STDERR),
        )
        out = svc.trim({"videoId": "v1"}, _rpc_ctx(registry))
        assert "jobId" in out
        job = registry.get(out["jobId"])
        job.wait(timeout=5)
        assert job.result["removedSec"] > 4.0
        assert job.result["path"].endswith(".trimmed.mp4")

    def test_trim_unknown_video_raises(self, settings, tmp_path, registry):
        svc = stm.SilenceTrim(
            resolver=lambda vid: None,
            out_dir=tmp_path,
            settings_provider=lambda: settings,
        )
        with pytest.raises(RpcError, match="unknown video"):
            svc.trim({"videoId": "ghost"}, _rpc_ctx(registry))

    def test_trim_resolves_explicit_path(self, settings, tmp_path, registry):
        # An explicit `path` short-circuits the resolver (the path branch in
        # _resolve) — no videoId required.
        svc = stm.SilenceTrim(
            resolver=lambda vid: None,
            out_dir=tmp_path / "trim",
            settings_provider=lambda: settings,
            run=RecordingRun(),
            duration=lambda p, s=None: 20.0,
            detect_run=detect_with(SILENCE_STDERR),
        )
        out = svc.trim({"path": "/x/explicit.mp4"}, _rpc_ctx(registry))
        job = registry.get(out["jobId"])
        job.wait(timeout=5)
        assert job.result["path"].endswith(".trimmed.mp4")

    def test_trim_settings_provider_raising_yields_empty(self, tmp_path, registry):
        def boom() -> dict[str, Any]:
            raise RuntimeError("settings exploded")

        svc = stm.SilenceTrim(
            resolver=lambda vid: "/lib/in.mp4",
            out_dir=tmp_path / "trim",
            settings_provider=boom,
            run=RecordingRun(),
            duration=lambda p, s=None: 20.0,
            detect_run=detect_with(SILENCE_STDERR),
        )
        # _settings swallows the error -> {} -> the op still runs.
        out = svc.trim({"videoId": "v1"}, _rpc_ctx(registry))
        registry.get(out["jobId"]).wait(timeout=5)
        assert registry.get(out["jobId"]).status.value == "done"

    def test_trim_missing_video_id_raises(self, settings, tmp_path, registry):
        # Neither `path` nor a non-empty `videoId` -> _require_str raises.
        svc = stm.SilenceTrim(
            resolver=lambda vid: "/lib/in.mp4",
            out_dir=tmp_path,
            settings_provider=lambda: settings,
        )
        with pytest.raises(RpcError, match="videoId"):
            svc.trim({"videoId": ""}, _rpc_ctx(registry))

    def test_trim_garbage_tunable_falls_back_to_default(self, settings, tmp_path, registry):
        # A non-numeric tunable is coerced back to the default (_float except).
        svc = stm.SilenceTrim(
            resolver=lambda vid: "/lib/in.mp4",
            out_dir=tmp_path / "trim",
            settings_provider=lambda: settings,
            run=RecordingRun(),
            duration=lambda p, s=None: 20.0,
            detect_run=detect_with(SILENCE_STDERR),
        )
        out = svc.trim({"videoId": "v1", "noiseDb": "loud"}, _rpc_ctx(registry))
        registry.get(out["jobId"]).wait(timeout=5)
        assert registry.get(out["jobId"]).status.value == "done"

    def test_trim_without_job_registry_raises(self, settings, tmp_path):
        svc = stm.SilenceTrim(
            resolver=lambda vid: "/lib/in.mp4",
            out_dir=tmp_path,
            settings_provider=lambda: settings,
        )
        ctx = RpcContext(emit_notification=lambda obj: None, jobs=None)
        with pytest.raises(RpcError, match="no job registry"):
            svc.trim({"videoId": "v1"}, ctx)


# --------------------------------------------------------------------------- #
# registration
# --------------------------------------------------------------------------- #
class TestRegister:
    def test_register_binds_silence_trim(self, tmp_path):
        registered: dict[str, Any] = {}
        svc = stm.register(
            resolver=lambda vid: None,
            out_dir=tmp_path,
            register_fn=lambda name, fn: registered.__setitem__(name, fn),
        )
        assert registered["silence.trim"] == svc.trim

    def test_register_default_uses_protocol(self, tmp_path):
        stm.register(resolver=lambda vid: None, out_dir=tmp_path)
        assert "silence.trim" in protocol.METHODS
