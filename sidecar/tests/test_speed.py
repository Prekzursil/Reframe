"""Tests for features/speed.py — the ``speed.retime`` RPC (constant-factor re-time).

The re-time ENGINE already existed (``director_op_engines.build_retime_argv``:
``setpts`` + an ``atempo`` chain) but was reachable ONLY as an LLM-planned Director
op. These tests pin the user-driven RPC that exposes it: parameter validation, the
argv delegation (anti-drift against the Director builder), the job result shape,
and registration.

SCOPE (stated so no reader over-reads it): this covers a CONSTANT factor only. A
keyframed speed RAMP (piecewise ``setpts`` + segment-wise audio resampling) is a
different engine and is NOT built here — see the module docstring.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from media_studio import protocol
from media_studio.features import director_op_engines as _doe
from media_studio.features import speed as sp
from media_studio.jobs import JobRegistry
from media_studio.protocol import RpcContext, RpcError


class RecordingRun:
    """An ffmpeg ``run`` seam that records argv and reports success."""

    def __init__(self, code: int = 0) -> None:
        self.calls: list[list[str]] = []
        self._code = code

    def __call__(self, argv: list[str], **kwargs: Any) -> int:
        self.calls.append(list(argv))
        on_progress = kwargs.get("on_progress")
        if on_progress is not None:
            on_progress(50.0, "speed")
        return self._code


def _rpc_ctx(registry: JobRegistry) -> RpcContext:
    return RpcContext(emit_notification=lambda obj: None, jobs=registry)


def _svc(tmp_path: Path, **over: Any) -> sp.SpeedService:
    kwargs: dict[str, Any] = {
        "resolver": lambda vid: "/lib/in.mp4" if vid == "v1" else None,
        "out_dir": tmp_path / "speed",
        "settings_provider": lambda: {"ffmpegPath": "/usr/bin/ffmpeg"},
        "run": RecordingRun(),
        "duration": lambda p, s=None: 12.0,
    }
    kwargs.update(over)
    return sp.SpeedService(**kwargs)


# --------------------------------------------------------------------------- #
# resolve_factor — the boundary validator
# --------------------------------------------------------------------------- #
class TestResolveFactor:
    @pytest.mark.parametrize("raw", [0.5, 1.5, 2, "2.5", 0.1, 10.0])
    def test_accepts_valid_factors(self, raw: Any) -> None:
        assert sp.resolve_factor(raw) == float(raw)

    @pytest.mark.parametrize("raw", [None, "fast", {}, [], True])
    def test_rejects_non_numeric(self, raw: Any) -> None:
        with pytest.raises(RpcError, match="numeric"):
            sp.resolve_factor(raw)

    @pytest.mark.parametrize("raw", [0.0, -1.0, -0.5])
    def test_rejects_non_positive(self, raw: float) -> None:
        with pytest.raises(RpcError, match="greater than 0"):
            sp.resolve_factor(raw)

    def test_rejects_exactly_one_as_a_no_op(self) -> None:
        with pytest.raises(RpcError, match="no-op"):
            sp.resolve_factor(1.0)

    @pytest.mark.parametrize("raw", [0.09, 10.01, 100.0])
    def test_rejects_out_of_window(self, raw: float) -> None:
        with pytest.raises(RpcError, match="between"):
            sp.resolve_factor(raw)

    def test_window_constants_bracket_one(self) -> None:
        assert sp.SPEED_MIN < 1.0 < sp.SPEED_MAX


# --------------------------------------------------------------------------- #
# retimed_duration — the pure duration prediction the UI shows
# --------------------------------------------------------------------------- #
class TestRetimedDuration:
    def test_speed_up_shortens(self) -> None:
        assert sp.retimed_duration(60.0, 2.0) == 30.0

    def test_slow_down_lengthens(self) -> None:
        assert sp.retimed_duration(60.0, 0.5) == 120.0

    @pytest.mark.parametrize("src", [0.0, -3.0])
    def test_unknown_source_duration_is_zero(self, src: float) -> None:
        assert sp.retimed_duration(src, 2.0) == 0.0


# --------------------------------------------------------------------------- #
# argv — delegation to the audited Director builder (anti-drift)
# --------------------------------------------------------------------------- #
class TestArgv:
    def test_delegates_to_the_director_retime_builder(self) -> None:
        settings = {"ffmpegPath": "/usr/bin/ffmpeg"}
        mine = sp.build_speed_argv("/in.mp4", "/out.mp4", 2.0, settings)
        theirs = _doe.build_retime_argv("/in.mp4", "/out.mp4", 2.0, settings)
        assert mine == theirs

    def test_argv_carries_the_setpts_and_atempo_filtergraph(self) -> None:
        argv = sp.build_speed_argv("/in.mp4", "/out.mp4", 2.0, {"ffmpegPath": "/usr/bin/ffmpeg"})
        graph = argv[argv.index("-filter_complex") + 1]
        assert "setpts=0.500000*PTS" in graph
        assert "atempo=" in graph


# --------------------------------------------------------------------------- #
# output naming
# --------------------------------------------------------------------------- #
class TestOutputName:
    @pytest.mark.parametrize(
        ("factor", "expected"),
        [(0.5, "clip.speed-0p50x.mp4"), (2.0, "clip.speed-2p00x.mp4"), (1.5, "clip.speed-1p50x.mp4")],
    )
    def test_name_encodes_the_factor(self, factor: float, expected: str) -> None:
        assert sp.speed_output_name("/x/clip.mp4", factor) == expected

    def test_pathless_stem_falls_back(self) -> None:
        assert sp.speed_output_name("", 2.0) == "clip.speed-2p00x.mp4"


# --------------------------------------------------------------------------- #
# the RPC service
# --------------------------------------------------------------------------- #
class TestService:
    def test_run_resolves_videoId_and_returns_the_retimed_clip(self, tmp_path, registry) -> None:
        run = RecordingRun()
        svc = _svc(tmp_path, run=run)
        out = svc.run({"videoId": "v1", "factor": 2.0}, _rpc_ctx(registry))
        assert "jobId" in out
        job = registry.get(out["jobId"])
        job.wait(timeout=5)
        assert job.result["factor"] == 2.0
        assert job.result["sourceDurationSec"] == 12.0
        assert job.result["durationSec"] == 6.0
        assert job.result["path"].endswith("in.speed-2p00x.mp4")
        assert run.calls, "the ffmpeg seam was never invoked"

    def test_run_accepts_a_direct_path(self, tmp_path, registry) -> None:
        svc = _svc(tmp_path)
        out = svc.run({"path": "/x/clip.mp4", "factor": 0.5}, _rpc_ctx(registry))
        job = registry.get(out["jobId"])
        job.wait(timeout=5)
        assert job.result["durationSec"] == 24.0

    def test_run_rejects_a_bad_factor_before_enqueueing(self, tmp_path, registry) -> None:
        svc = _svc(tmp_path)
        with pytest.raises(RpcError, match="no-op"):
            svc.run({"videoId": "v1", "factor": 1.0}, _rpc_ctx(registry))

    def test_run_unknown_video_raises(self, tmp_path, registry) -> None:
        svc = _svc(tmp_path, resolver=lambda vid: None)
        with pytest.raises(RpcError, match="unknown video"):
            svc.run({"videoId": "ghost", "factor": 2.0}, _rpc_ctx(registry))

    def test_run_missing_video_id_raises(self, tmp_path, registry) -> None:
        svc = _svc(tmp_path)
        with pytest.raises(RpcError, match="videoId"):
            svc.run({"videoId": "", "factor": 2.0}, _rpc_ctx(registry))

    def test_run_without_job_registry_raises(self, tmp_path) -> None:
        svc = _svc(tmp_path)
        ctx = RpcContext(emit_notification=lambda obj: None, jobs=None)
        with pytest.raises(RpcError, match="no job registry"):
            svc.run({"videoId": "v1", "factor": 2.0}, ctx)

    def test_nonzero_ffmpeg_exit_fails_the_job(self, tmp_path, registry) -> None:
        svc = _svc(tmp_path, run=RecordingRun(code=3))
        out = svc.run({"videoId": "v1", "factor": 2.0}, _rpc_ctx(registry))
        job = registry.get(out["jobId"])
        job.wait(timeout=5)
        assert job.error is not None
        assert "exit 3" in str(job.error)

    def test_settings_provider_raising_yields_empty_settings(self, tmp_path, registry) -> None:
        def boom() -> dict[str, Any]:
            raise RuntimeError("settings exploded")

        svc = _svc(tmp_path, settings_provider=boom)
        out = svc.run({"path": "/x/clip.mp4", "factor": 2.0}, _rpc_ctx(registry))
        registry.get(out["jobId"]).wait(timeout=5)
        assert registry.get(out["jobId"]).result["factor"] == 2.0

    def test_probe_failure_only_coarsens_progress(self, tmp_path, registry) -> None:
        def boom(path: str, settings: Any = None) -> float:
            raise RuntimeError("ffprobe exploded")

        svc = _svc(tmp_path, duration=boom)
        out = svc.run({"path": "/x/clip.mp4", "factor": 2.0}, _rpc_ctx(registry))
        job = registry.get(out["jobId"])
        job.wait(timeout=5)
        # The op still renders; the duration prediction degrades to "unknown" (0.0)
        # rather than failing the whole re-time.
        assert job.result["sourceDurationSec"] == 0.0
        assert job.result["durationSec"] == 0.0

    def test_defaults_construct_without_injected_seams(self, tmp_path) -> None:
        svc = sp.SpeedService(resolver=lambda vid: None, out_dir=tmp_path)
        assert svc._settings() == {}


# --------------------------------------------------------------------------- #
# the un-injected default seams — an uncovered default is an unproven default
# --------------------------------------------------------------------------- #
class TestDefaultSeams:
    def test_default_run_is_the_shared_drained_ffmpeg_runner(self) -> None:
        # The 29-min-freeze lesson: the render MUST go through the shared drained
        # runner, never a re-implemented drain. Pin the identity.
        from media_studio import ffmpeg

        assert sp._default_run() is ffmpeg.run

    def test_default_duration_is_the_shared_ffprobe_seam(self) -> None:
        from media_studio import ffmpeg

        assert sp._default_duration() is ffmpeg.ffprobe_duration


# --------------------------------------------------------------------------- #
# registration
# --------------------------------------------------------------------------- #
class TestRegister:
    def test_register_binds_speed_retime(self, tmp_path) -> None:
        registered: dict[str, Any] = {}
        svc = sp.register(
            resolver=lambda vid: None,
            out_dir=tmp_path,
            register_fn=lambda name, fn: registered.__setitem__(name, fn),
        )
        assert "speed.retime" in registered
        assert registered["speed.retime"] == svc.run

    def test_register_default_uses_protocol(self, tmp_path) -> None:
        # The autouse conftest `_restore_methods` fixture snapshots/restores
        # protocol.METHODS around each test, so this registration is isolated.
        sp.register(resolver=lambda vid: None, out_dir=tmp_path)
        assert "speed.retime" in protocol.METHODS
