"""Tests for features/audiomix.py (audio-stabilize group — A/V merge + duck + loudnorm).

Heavy work is mocked at the documented seams: the ffmpeg ``run`` is a recording
fake (no subprocess), binaries resolve from a tmp dir of stub ffmpeg files. No
subprocess is ever spawned, no network. Mirrors test_tracks_audio.py.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from media_studio import protocol
from media_studio.features import audiomix as am
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


@pytest.fixture()
def bg_file(tmp_path: Path) -> str:
    f = tmp_path / "bed.m4a"
    f.write_bytes(b"\x00aac")
    return str(f)


class RecordingRun:
    def __init__(self, code: int = 0) -> None:
        self.code = code
        self.calls: list[list[str]] = []

    def __call__(self, argv, *, total_sec: float = 0.0, on_progress=None, should_cancel=None) -> int:
        self.calls.append(list(argv))
        if self.code == 0:
            Path(argv[-1]).write_bytes(b"\x00mp4")
        if on_progress is not None:
            on_progress(100.0, "done")
        return self.code


def _rpc_ctx(registry: JobRegistry) -> RpcContext:
    return RpcContext(emit_notification=lambda obj: None, jobs=registry)


# --------------------------------------------------------------------------- #
# pure: the filter graph
# --------------------------------------------------------------------------- #
class TestFilterGraph:
    def test_graph_chains_duck_mix_loudnorm(self):
        flt = am.build_mix_filter()
        # sidechain DUCK keyed off the foreground.
        assert "sidechaincompress=" in flt
        # mix foreground + ducked bed.
        assert "amix=inputs=2" in flt
        # EBU R128 loudnorm on the summed mix.
        assert "loudnorm=" in flt
        # The output is labelled [out] (mapped in the argv).
        assert flt.endswith("[out]")

    def test_tunables_flow_into_graph(self):
        flt = am.build_mix_filter(bg_gain_db=-6.0, duck_threshold=0.1, duck_ratio=12.0, loudness_target=-16.0)
        assert "volume=-6.0dB" in flt
        assert "threshold=0.1" in flt
        assert "ratio=12.0" in flt
        assert "I=-16.0" in flt

    def test_mix_argv_keeps_video_copy_encodes_audio(self, settings):
        argv = am.build_mix_argv("/clip.mp4", "/bed.m4a", "/out.mp4", settings=settings)
        assert isinstance(argv, list)
        # two inputs: clip + bed.
        assert argv.count("-i") == 2
        # video stream-copied, mixed audio re-encoded AAC.
        assert argv[argv.index("-c:v") + 1] == "copy"
        assert argv[argv.index("-c:a") + 1] == "aac"
        # filter output mapped, output is shortest (bed trimmed to the clip).
        assert "[out]" in argv
        assert "-shortest" in argv
        assert argv[-1] == "/out.mp4"

    def test_loudnorm_argv_no_bed(self, settings):
        argv = am.build_loudnorm_argv("/clip.mp4", "/out.mp4", settings=settings)
        assert argv.count("-i") == 1
        af = argv[argv.index("-af") + 1]
        assert af.startswith("loudnorm=")


# --------------------------------------------------------------------------- #
# the service
# --------------------------------------------------------------------------- #
class TestMergeService:
    def test_merge_returns_jobId_and_runs_ffmpeg(self, settings, tmp_path, bg_file, registry):
        run = RecordingRun()
        svc = am.AudioMix(
            resolver=lambda vid: "/lib/clip.mp4",
            out_dir=tmp_path / "mix",
            settings_provider=lambda: settings,
            run=run,
            duration=lambda p, s=None: 20.0,
        )
        out = svc.merge({"videoId": "v1", "bgPath": bg_file}, _rpc_ctx(registry))
        assert "jobId" in out
        job = registry.get(out["jobId"])
        job.wait(timeout=5)
        assert job.result["path"].endswith(".mp4")
        # The single ffmpeg call carried the duck+mix+loudnorm filter graph.
        argv = run.calls[0]
        assert "sidechaincompress=" in argv[argv.index("-filter_complex") + 1]

    def test_merge_tunables_override_defaults(self, settings, tmp_path, bg_file, registry):
        run = RecordingRun()
        svc = am.AudioMix(
            resolver=lambda vid: "/lib/clip.mp4",
            out_dir=tmp_path,
            settings_provider=lambda: settings,
            run=run,
            duration=lambda p, s=None: 1.0,
        )
        out = svc.merge(
            {"videoId": "v1", "bgPath": bg_file, "loudnessTarget": -23, "duckRatio": 20},
            _rpc_ctx(registry),
        )
        registry.get(out["jobId"]).wait(timeout=5)
        flt = run.calls[0][run.calls[0].index("-filter_complex") + 1]
        assert "I=-23.0" in flt and "ratio=20.0" in flt

    def test_merge_missing_bg_raises(self, settings, tmp_path, registry):
        svc = am.AudioMix(
            resolver=lambda vid: "/lib/clip.mp4",
            out_dir=tmp_path,
            settings_provider=lambda: settings,
        )
        with pytest.raises(RpcError, match="background audio not found"):
            svc.merge({"videoId": "v1", "bgPath": "/nope.m4a"}, _rpc_ctx(registry))

    def test_merge_unknown_video_raises(self, settings, tmp_path, bg_file, registry):
        svc = am.AudioMix(
            resolver=lambda vid: None,
            out_dir=tmp_path,
            settings_provider=lambda: settings,
        )
        with pytest.raises(RpcError, match="unknown video"):
            svc.merge({"videoId": "ghost", "bgPath": bg_file}, _rpc_ctx(registry))

    def test_merge_ffmpeg_failure_surfaces_in_job(self, settings, tmp_path, bg_file, registry):
        svc = am.AudioMix(
            resolver=lambda vid: "/lib/clip.mp4",
            out_dir=tmp_path,
            settings_provider=lambda: settings,
            run=RecordingRun(code=1),
            duration=lambda p, s=None: 1.0,
        )
        out = svc.merge({"videoId": "v1", "bgPath": bg_file}, _rpc_ctx(registry))
        job = registry.get(out["jobId"])
        job.wait(timeout=5)
        assert job.error is not None

    def test_normalize_returns_jobId(self, settings, tmp_path, registry):
        run = RecordingRun()
        svc = am.AudioMix(
            resolver=lambda vid: "/lib/clip.mp4",
            out_dir=tmp_path,
            settings_provider=lambda: settings,
            run=run,
            duration=lambda p, s=None: 5.0,
        )
        out = svc.normalize({"path": "/x/clip.mp4"}, _rpc_ctx(registry))
        registry.get(out["jobId"]).wait(timeout=5)
        af = run.calls[0][run.calls[0].index("-af") + 1]
        assert af.startswith("loudnorm=")


# --------------------------------------------------------------------------- #
# param coercion + settings/job edge cases (branch coverage)
# --------------------------------------------------------------------------- #
class TestEdges:
    def test_require_str_missing_bgpath_raises(self, settings, tmp_path, registry):
        # videoId resolves, but bgPath is absent/empty -> _require_str raises.
        svc = am.AudioMix(
            resolver=lambda vid: "/lib/clip.mp4",
            out_dir=tmp_path,
            settings_provider=lambda: settings,
        )
        with pytest.raises(RpcError, match="bgPath"):
            svc.merge({"videoId": "v1", "bgPath": ""}, _rpc_ctx(registry))

    def test_float_garbage_falls_back_to_default(self, settings, tmp_path, bg_file, registry):
        run = RecordingRun()
        svc = am.AudioMix(
            resolver=lambda vid: "/lib/clip.mp4",
            out_dir=tmp_path,
            settings_provider=lambda: settings,
            run=run,
            duration=lambda p, s=None: 1.0,
        )
        # A non-numeric tunable is coerced back to the default (no crash).
        out = svc.merge({"videoId": "v1", "bgPath": bg_file, "duckRatio": "wat"}, _rpc_ctx(registry))
        registry.get(out["jobId"]).wait(timeout=5)
        flt = run.calls[0][run.calls[0].index("-filter_complex") + 1]
        assert f"ratio={am.DEFAULT_DUCK_RATIO}" in flt

    def test_settings_provider_raising_yields_empty(self, tmp_path, bg_file, registry):
        run = RecordingRun()

        def boom() -> dict[str, Any]:
            raise RuntimeError("settings exploded")

        svc = am.AudioMix(
            resolver=lambda vid: "/lib/clip.mp4",
            out_dir=tmp_path,
            settings_provider=boom,
            run=run,
            duration=lambda p, s=None: 1.0,
        )
        # _settings swallows the error -> {} -> the op still runs.
        out = svc.merge({"videoId": "v1", "bgPath": bg_file}, _rpc_ctx(registry))
        registry.get(out["jobId"]).wait(timeout=5)
        assert run.calls  # ffmpeg still invoked despite the bad settings provider

    def test_duration_probe_failure_coarsens_progress(self, settings, tmp_path, bg_file, registry):
        run = RecordingRun()

        def boom_duration(path, s=None) -> float:
            raise OSError("ffprobe died")

        svc = am.AudioMix(
            resolver=lambda vid: "/lib/clip.mp4",
            out_dir=tmp_path,
            settings_provider=lambda: settings,
            run=run,
            duration=boom_duration,
        )
        out = svc.merge({"videoId": "v1", "bgPath": bg_file}, _rpc_ctx(registry))
        job = registry.get(out["jobId"])
        job.wait(timeout=5)
        # Probe failure only coarsens progress -> total_sec 0.0, job still succeeds.
        assert job.result["path"].endswith(".mp4")
        assert run.calls[0][run.calls[0].index("-progress") + 1] == "pipe:1"

    def test_merge_without_job_registry_raises(self, settings, tmp_path, bg_file):
        svc = am.AudioMix(
            resolver=lambda vid: "/lib/clip.mp4",
            out_dir=tmp_path,
            settings_provider=lambda: settings,
        )
        ctx = RpcContext(emit_notification=lambda obj: None, jobs=None)
        with pytest.raises(RpcError, match="no job registry"):
            svc.merge({"videoId": "v1", "bgPath": bg_file}, ctx)

    def test_normalize_without_job_registry_raises(self, settings, tmp_path):
        svc = am.AudioMix(
            resolver=lambda vid: "/lib/clip.mp4",
            out_dir=tmp_path,
            settings_provider=lambda: settings,
        )
        ctx = RpcContext(emit_notification=lambda obj: None, jobs=None)
        with pytest.raises(RpcError, match="no job registry"):
            svc.normalize({"path": "/x/clip.mp4"}, ctx)


# --------------------------------------------------------------------------- #
# registration
# --------------------------------------------------------------------------- #
class TestRegister:
    def test_register_binds_both_methods(self, tmp_path):
        registered: dict[str, Any] = {}
        svc = am.register(
            resolver=lambda vid: None,
            out_dir=tmp_path,
            register_fn=lambda name, fn: registered.__setitem__(name, fn),
        )
        assert registered["audiomix.merge"] == svc.merge
        assert registered["audiomix.normalize"] == svc.normalize

    def test_register_default_uses_protocol(self, tmp_path):
        am.register(resolver=lambda vid: None, out_dir=tmp_path)
        assert "audiomix.merge" in protocol.METHODS
        assert "audiomix.normalize" in protocol.METHODS
