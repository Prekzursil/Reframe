"""Tests for features/stabilize.py (audio-stabilize group — vidstab 2-pass).

Everything heavy is mocked at the documented seams: the ffmpeg ``run`` is a
recording fake (no subprocess), the libvidstab availability probe is a fabricated
``-filters`` output (``probe_runner`` seam), and the binaries resolve from a tmp
dir of stub ffmpeg files. No subprocess is ever spawned, no network.

Mirrors the test style of test_shorts.py / test_tracks_audio.py.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from media_studio import ffmpeg, protocol
from media_studio.features import stabilize as st
from media_studio.jobs import JobRegistry
from media_studio.protocol import RpcContext, RpcError


# --------------------------------------------------------------------------- #
# fixtures + seams
# --------------------------------------------------------------------------- #
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


def ctx() -> RpcContext:
    return RpcContext(emit_notification=lambda obj: None, jobs=None)


class RecordingRun:
    """A drained-run fake: records argv and writes the output (last argv arg)."""

    def __init__(self, code: int = 0, write_output: bool = True) -> None:
        self.code = code
        self.write_output = write_output
        self.calls: list[list[str]] = []
        self.cwds: list[str | None] = []

    def __call__(
        self, argv, *, total_sec: float = 0.0, on_progress=None, should_cancel=None, cwd=None
    ) -> int:
        self.calls.append(list(argv))
        self.cwds.append(cwd)
        if self.write_output and self.code == 0 and argv[-1] != "-":
            # Mirror the real runner: the .trf/output filename in the filtergraph is
            # a BARE basename resolved against cwd, so write the output there too.
            out = argv[-1]
            if cwd is not None and not Path(out).is_absolute():
                out = str(Path(cwd) / out)
            Path(out).write_bytes(b"\x00mp4")
        if on_progress is not None:
            on_progress(100.0, "done")
        return self.code


def probe_with(out: str) -> st.ProbeRunner:
    """A ``-filters`` probe runner returning fabricated stdout."""

    class Completed:
        returncode = 0
        stdout = out
        stderr = ""

    return lambda argv, **kw: Completed()


VIDSTAB_FILTERS = " .. vidstabdetect ...\n .. vidstabtransform ...\n"
NO_VIDSTAB_FILTERS = " .. scale ...\n .. crop ...\n"


# --------------------------------------------------------------------------- #
# pure argv builders
# --------------------------------------------------------------------------- #
class TestArgvBuilders:
    def test_detect_argv_is_pass1_to_null(self, settings):
        argv = st.build_detect_argv("/in.mp4", "C:/out/clip.trf", settings=settings)
        assert isinstance(argv, list)
        vf = argv[argv.index("-vf") + 1]
        assert vf.startswith("vidstabdetect=")
        # The .trf is referenced by BARE basename (the engine runs ffmpeg with
        # cwd=<trf dir>); an absolute Windows path's drive colon would break the -vf
        # filtergraph parser, and no escaping form works (verified against ffmpeg 8).
        assert "result=clip.trf" in vf
        assert "C:/out/clip.trf" not in vf and "/out/" not in vf
        # PASS 1 decodes to null (no output video).
        assert argv[-1] == "-" and "null" in argv

    def test_transform_argv_is_pass2_reads_trf(self, settings):
        argv = st.build_transform_argv("/in.mp4", "/out.trf", "/out.mp4", settings=settings)
        vf = argv[argv.index("-vf") + 1]
        assert vf.startswith("vidstabtransform=")
        # BARE basename (see the detect test) — ffmpeg runs with cwd=<trf dir>.
        assert "input=out.trf" in vf
        # audio copied through; video re-encoded h264.
        assert argv[argv.index("-c:a") + 1] == "copy"
        assert argv[argv.index("-c:v") + 1] == "libx264"
        assert argv[-1] == "/out.mp4"

    def test_tunables_flow_into_filter(self, settings):
        s = {**settings, "stabShakiness": 8, "stabSmoothing": 30, "stabOptzoom": 0}
        det = st.build_detect_argv("/in.mp4", "/t.trf", settings=s)
        assert "shakiness=8" in det[det.index("-vf") + 1]
        tr = st.build_transform_argv("/in.mp4", "/t.trf", "/o.mp4", settings=s)
        assert "smoothing=30" in tr[tr.index("-vf") + 1]
        assert "optzoom=0" in tr[tr.index("-vf") + 1]

    def test_bad_tunable_falls_back_to_default(self, settings):
        s = {**settings, "stabShakiness": "wat"}
        det = st.build_detect_argv("/in.mp4", "/t.trf", settings=s)
        assert f"shakiness={st.DEFAULT_SHAKINESS}" in det[det.index("-vf") + 1]


# --------------------------------------------------------------------------- #
# libvidstab availability probe
# --------------------------------------------------------------------------- #
class TestAvailability:
    def test_available_when_both_filters_listed(self, settings):
        assert st.vidstab_available(settings, probe_with(VIDSTAB_FILTERS)) is True

    def test_unavailable_when_filters_missing(self, settings):
        assert st.vidstab_available(settings, probe_with(NO_VIDSTAB_FILTERS)) is False

    def test_probe_spawn_failure_is_unavailable(self, settings):
        def boom(argv, **kw):
            raise OSError("no ffmpeg")

        assert st.vidstab_available(settings, boom) is False

    def test_no_ffmpeg_resolvable_is_unavailable(self, monkeypatch):
        def boom(name, settings=None):
            raise ffmpeg.FfmpegNotFound("nope")

        monkeypatch.setattr(ffmpeg, "ffmpeg_path", boom)
        assert st.vidstab_available({}, probe_with(VIDSTAB_FILTERS)) is False

    def test_notice_names_the_bundling_requirement(self):
        notice = st.make_unavailable_notice()
        assert notice["type"] == st.STABILIZE_UNAVAILABLE_NOTICE
        assert "libvidstab" in notice["message"]
        assert "enable-libvidstab" in notice["message"]


# --------------------------------------------------------------------------- #
# the engine
# --------------------------------------------------------------------------- #
class TestEngine:
    def test_stabilize_runs_both_passes_and_cleans_trf(self, settings, tmp_path):
        run = RecordingRun()
        engine = st.StabilizeEngine(
            settings,
            run=run,
            duration=lambda p, s=None: 30.0,
            probe_runner=probe_with(VIDSTAB_FILTERS),
        )
        out = str(tmp_path / "clip.stabilized.mp4")
        result = engine.stabilize("/in.mp4", out)
        assert result == out
        assert len(run.calls) == 2  # detect + transform
        assert "vidstabdetect=" in run.calls[0][run.calls[0].index("-vf") + 1]
        assert "vidstabtransform=" in run.calls[1][run.calls[1].index("-vf") + 1]
        # The intermediate .trf was cleaned up.
        assert not Path(out).with_suffix(".trf").exists()

    def test_stabilize_runs_ffmpeg_in_trf_dir_with_bare_basename(self, settings, tmp_path):
        # Windows regression (v1.4): an absolute drive-colon .trf path breaks the
        # -vf filtergraph parser and NO escaping form works, so BOTH ffmpeg passes
        # must run with cwd=<trf dir> and reference the .trf by BARE basename.
        run = RecordingRun()
        engine = st.StabilizeEngine(
            settings, run=run, duration=lambda p, s=None: 5.0, probe_runner=probe_with(VIDSTAB_FILTERS)
        )
        out = str(tmp_path / "clip.stabilized.mp4")
        engine.stabilize(str(tmp_path / "in.mp4"), out)
        trf_dir = str(tmp_path)
        trf_name = Path(out).with_suffix(".trf").name
        assert run.cwds == [trf_dir, trf_dir]
        det_vf = run.calls[0][run.calls[0].index("-vf") + 1]
        tr_vf = run.calls[1][run.calls[1].index("-vf") + 1]
        assert f"result={trf_name}" in det_vf and trf_dir not in det_vf
        assert f"input={trf_name}" in tr_vf and trf_dir not in tr_vf

    def test_stabilize_absolutizes_relative_in_out(self, settings, tmp_path, monkeypatch):
        # Guard: ffmpeg runs with cwd=<trf dir>, so a RELATIVE in/out must be
        # absolutized first or it would misresolve against that cwd.
        monkeypatch.chdir(tmp_path)
        run = RecordingRun()
        engine = st.StabilizeEngine(
            settings, run=run, duration=lambda p, s=None: 1.0, probe_runner=probe_with(VIDSTAB_FILTERS)
        )
        engine.stabilize("in.mp4", "sub/out.mp4")  # both relative
        det = run.calls[0]
        assert Path(det[det.index("-i") + 1]).is_absolute()  # input absolutized
        assert Path(run.calls[1][-1]).is_absolute()  # transform output absolutized

    def test_stabilize_raises_when_unavailable(self, settings):
        engine = st.StabilizeEngine(settings, run=RecordingRun(), probe_runner=probe_with(NO_VIDSTAB_FILTERS))
        with pytest.raises(st.StabilizeError, match="libvidstab"):
            engine.stabilize("/in.mp4", "/out.mp4")

    def test_detect_failure_raises_and_cleans_trf(self, settings, tmp_path):
        run = RecordingRun(code=1, write_output=False)
        engine = st.StabilizeEngine(
            settings, run=run, duration=lambda p, s=None: 1.0, probe_runner=probe_with(VIDSTAB_FILTERS)
        )
        out = str(tmp_path / "c.mp4")
        with pytest.raises(st.StabilizeError, match="vidstabdetect"):
            engine.stabilize("/in.mp4", out)
        assert not Path(out).with_suffix(".trf").exists()

    def test_transform_failure_raises_after_detect_succeeds(self, settings, tmp_path):
        # PASS 1 succeeds (code 0), PASS 2 fails (code 1) -> vidstabtransform error.
        class TwoStageRun:
            def __init__(self) -> None:
                self.calls: list[list[str]] = []

            def __call__(
                self, argv, *, total_sec=0.0, on_progress=None, should_cancel=None, cwd=None
            ) -> int:
                self.calls.append(list(argv))
                return 0 if len(self.calls) == 1 else 1

        run = TwoStageRun()
        engine = st.StabilizeEngine(
            settings, run=run, duration=lambda p, s=None: 1.0, probe_runner=probe_with(VIDSTAB_FILTERS)
        )
        out = str(tmp_path / "c.mp4")
        with pytest.raises(st.StabilizeError, match="vidstabtransform"):
            engine.stabilize("/in.mp4", out)
        assert not Path(out).with_suffix(".trf").exists()

    def test_duration_probe_failure_coarsens_progress(self, settings, tmp_path):
        # A probe failure only coarsens progress (total_sec 0.0); both passes run.
        def boom_duration(p, s=None):
            raise OSError("ffprobe died")

        run = RecordingRun()
        engine = st.StabilizeEngine(settings, run=run, duration=boom_duration, probe_runner=probe_with(VIDSTAB_FILTERS))
        out = str(tmp_path / "clip.stabilized.mp4")
        assert engine.stabilize("/in.mp4", out) == out
        assert len(run.calls) == 2


# --------------------------------------------------------------------------- #
# pipeline pre-step adapter
# --------------------------------------------------------------------------- #
class TestStabilizeClip:
    def test_passthrough_emits_notice_when_unavailable(self, settings, tmp_path):
        notices: list[dict[str, str]] = []
        out = str(tmp_path / "o.mp4")
        result = st.stabilize_clip(
            "/in.mp4",
            out,
            settings=settings,
            run=RecordingRun(),
            duration=lambda p, s=None: 5.0,
            probe_runner=probe_with(NO_VIDSTAB_FILTERS),
            on_notice=notices.append,
        )
        # Pass-through: returns the ORIGINAL input, never silently skips.
        assert result == "/in.mp4"
        assert notices and notices[0]["type"] == st.STABILIZE_UNAVAILABLE_NOTICE

    def test_runs_when_available(self, settings, tmp_path):
        run = RecordingRun()
        out = str(tmp_path / "o.mp4")
        result = st.stabilize_clip(
            "/in.mp4",
            out,
            settings=settings,
            run=run,
            duration=lambda p, s=None: 5.0,
            probe_runner=probe_with(VIDSTAB_FILTERS),
        )
        assert result == out
        assert len(run.calls) == 2

    def test_passthrough_without_on_notice_callback(self, settings, tmp_path):
        # Unavailable AND no on_notice callback supplied (the `if on_notice is not
        # None` false branch) -> still passes through the original input.
        result = st.stabilize_clip(
            "/in.mp4",
            str(tmp_path / "o.mp4"),
            settings=settings,
            run=RecordingRun(),
            duration=lambda p, s=None: 5.0,
            probe_runner=probe_with(NO_VIDSTAB_FILTERS),
        )
        assert result == "/in.mp4"


# --------------------------------------------------------------------------- #
# the RPC service (stabilize.run -> job) — uses the shared conftest `registry`
# --------------------------------------------------------------------------- #
def _rpc_ctx(registry: JobRegistry) -> RpcContext:
    return RpcContext(emit_notification=lambda obj: None, jobs=registry)


class TestService:
    def test_run_resolves_videoId_and_returns_jobId(self, settings, tmp_path, registry):
        run = RecordingRun()
        svc = st.StabilizeService(
            resolver=lambda vid: "/lib/in.mp4" if vid == "v1" else None,
            out_dir=tmp_path / "stab",
            settings_provider=lambda: settings,
            run=run,
            duration=lambda p, s=None: 12.0,
            probe_runner=probe_with(VIDSTAB_FILTERS),
        )
        out = svc.run({"videoId": "v1"}, _rpc_ctx(registry))
        assert "jobId" in out
        job = registry.get(out["jobId"])
        job.wait(timeout=5)
        assert job.result["stabilized"] is True
        assert job.result["path"].endswith(".stabilized.mp4")

    def test_run_unknown_video_raises(self, settings, tmp_path, registry):
        svc = st.StabilizeService(
            resolver=lambda vid: None,
            out_dir=tmp_path,
            settings_provider=lambda: settings,
        )
        with pytest.raises(RpcError, match="unknown video"):
            svc.run({"videoId": "ghost"}, _rpc_ctx(registry))

    def test_run_missing_video_id_raises(self, settings, tmp_path, registry):
        # Neither `path` nor a non-empty `videoId` -> _require_str raises.
        svc = st.StabilizeService(
            resolver=lambda vid: "/lib/in.mp4",
            out_dir=tmp_path,
            settings_provider=lambda: settings,
        )
        with pytest.raises(RpcError, match="videoId"):
            svc.run({"videoId": ""}, _rpc_ctx(registry))

    def test_run_settings_provider_raising_yields_empty(self, settings, tmp_path, registry):
        def boom() -> dict[str, Any]:
            raise RuntimeError("settings exploded")

        svc = st.StabilizeService(
            resolver=lambda vid: "/lib/in.mp4",
            out_dir=tmp_path,
            settings_provider=boom,
            run=RecordingRun(),
            probe_runner=probe_with(NO_VIDSTAB_FILTERS),
        )
        # _settings swallows the error -> {} -> the op still runs (here it reports
        # unavailable because the empty-settings probe lists no vidstab filters).
        out = svc.run({"videoId": "v1"}, _rpc_ctx(registry))
        registry.get(out["jobId"]).wait(timeout=5)
        assert registry.get(out["jobId"]).result["stabilized"] is False

    def test_run_without_job_registry_raises(self, settings, tmp_path):
        svc = st.StabilizeService(
            resolver=lambda vid: "/lib/in.mp4",
            out_dir=tmp_path,
            settings_provider=lambda: settings,
        )
        c = RpcContext(emit_notification=lambda obj: None, jobs=None)
        with pytest.raises(RpcError, match="no job registry"):
            svc.run({"videoId": "v1"}, c)

    def test_run_unavailable_returns_source_with_notice(self, settings, tmp_path, registry):
        svc = st.StabilizeService(
            resolver=lambda vid: "/lib/in.mp4",
            out_dir=tmp_path,
            settings_provider=lambda: settings,
            run=RecordingRun(),
            probe_runner=probe_with(NO_VIDSTAB_FILTERS),
        )
        out = svc.run({"path": "/x/clip.mp4"}, _rpc_ctx(registry))
        job = registry.get(out["jobId"])
        job.wait(timeout=5)
        assert job.result["stabilized"] is False
        assert job.result["path"] == "/x/clip.mp4"
        assert job.result["notice"]["type"] == st.STABILIZE_UNAVAILABLE_NOTICE


# --------------------------------------------------------------------------- #
# registration
# --------------------------------------------------------------------------- #
class TestRegister:
    def test_register_binds_stabilize_run(self, tmp_path):
        registered: dict[str, Any] = {}
        svc = st.register(
            resolver=lambda vid: None,
            out_dir=tmp_path,
            register_fn=lambda name, fn: registered.__setitem__(name, fn),
        )
        assert "stabilize.run" in registered
        assert registered["stabilize.run"] == svc.run

    def test_register_default_uses_protocol(self, tmp_path):
        # The autouse conftest `_restore_methods` fixture snapshots/restores
        # protocol.METHODS around each test, so this registration is isolated.
        st.register(resolver=lambda vid: None, out_dir=tmp_path)
        assert "stabilize.run" in protocol.METHODS
