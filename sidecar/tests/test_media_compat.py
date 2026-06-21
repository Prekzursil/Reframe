"""Tests for features/media_compat.py (P2 U1: media.playable + media.proxy.start).

Everything heavy is mocked at the documented seams: the ffprobe sniff is a
fabricated JSON payload (``probe`` seam), the ffmpeg encode is a recording
fake (``run`` seam) that writes the output file, and binaries resolve from a
tmp dir of stub ffmpeg/ffprobe files. No subprocess is ever spawned.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from media_studio import protocol
from media_studio.features import media_compat as mc
from media_studio.protocol import RpcContext, RpcError


# --------------------------------------------------------------------------- #
# fixtures + probe payload builders
# --------------------------------------------------------------------------- #
@pytest.fixture()
def bin_dir(tmp_path: Path) -> Path:
    """A fake ffmpeg/ffprobe install dir (both plain + .exe for cross-OS)."""
    d = tmp_path / "bin"
    d.mkdir()
    for name in ("ffmpeg", "ffprobe", "ffmpeg.exe", "ffprobe.exe"):
        (d / name).write_text("", encoding="utf-8")
    return d


@pytest.fixture()
def settings(bin_dir: Path) -> dict[str, Any]:
    return {"ffmpegPath": str(bin_dir)}


def vstream(codec: str, attached_pic: bool = False) -> dict[str, Any]:
    return {
        "codec_type": "video",
        "codec_name": codec,
        "disposition": {"attached_pic": 1 if attached_pic else 0},
    }


def astream(codec: str) -> dict[str, Any]:
    return {"codec_type": "audio", "codec_name": codec, "disposition": {}}


def sstream(codec: str = "subrip") -> dict[str, Any]:
    return {"codec_type": "subtitle", "codec_name": codec, "disposition": {}}


MP4_FAMILY = "mov,mp4,m4a,3gp,3g2,mj2"
MKV_FAMILY = "matroska,webm"


def probe_payload(
    format_name: str,
    streams: list[dict[str, Any]],
    duration: float = 120.0,
) -> dict[str, Any]:
    return {
        "streams": streams,
        "format": {"format_name": format_name, "duration": str(duration)},
    }


# --------------------------------------------------------------------------- #
# classify(): the codec-driven verdict matrix (the DONE-WHEN core)
# --------------------------------------------------------------------------- #
class TestClassify:
    def test_h264_aac_in_mp4_is_playable(self):
        verdict, _ = mc.classify(probe_payload(MP4_FAMILY, [vstream("h264"), astream("aac")]), "C:/v/talk.mp4")
        assert verdict == mc.VERDICT_PLAYABLE

    def test_h264_aac_in_mkv_needs_remux(self):
        verdict, reason = mc.classify(probe_payload(MKV_FAMILY, [vstream("h264"), astream("aac")]), "C:/v/talk.mkv")
        assert verdict == mc.VERDICT_REMUX
        assert "container" in reason

    def test_hevc_in_mkv_needs_proxy(self):
        verdict, reason = mc.classify(probe_payload(MKV_FAMILY, [vstream("hevc"), astream("aac")]), "C:/v/talk.mkv")
        assert verdict == mc.VERDICT_PROXY
        assert "hevc" in reason

    def test_hevc_in_mp4_still_needs_proxy(self):
        # Codec-driven, NOT container-driven: a good container can't save hevc.
        verdict, _ = mc.classify(probe_payload(MP4_FAMILY, [vstream("hevc"), astream("aac")]), "C:/v/talk.mp4")
        assert verdict == mc.VERDICT_PROXY

    @pytest.mark.parametrize("codec", ["wmv3", "mpeg2video", "msmpeg4v3", "prores"])
    def test_legacy_video_codecs_need_proxy(self, codec: str):
        verdict, _ = mc.classify(probe_payload("avi", [vstream(codec), astream("mp3")]), "C:/v/old.avi")
        assert verdict == mc.VERDICT_PROXY

    def test_unplayable_audio_forces_proxy(self):
        verdict, reason = mc.classify(probe_payload(MKV_FAMILY, [vstream("h264"), astream("dts")]), "C:/v/talk.mkv")
        assert verdict == mc.VERDICT_PROXY
        assert "dts" in reason

    def test_vp9_opus_webm_is_playable(self):
        verdict, _ = mc.classify(probe_payload(MKV_FAMILY, [vstream("vp9"), astream("opus")]), "C:/v/clip.webm")
        assert verdict == mc.VERDICT_PLAYABLE

    def test_vp9_opus_in_mkv_extension_needs_remux(self):
        # Same ffprobe family ("matroska,webm") — the extension disambiguates.
        verdict, _ = mc.classify(probe_payload(MKV_FAMILY, [vstream("vp9"), astream("opus")]), "C:/v/clip.mkv")
        assert verdict == mc.VERDICT_REMUX

    def test_attached_pic_cover_art_is_ignored(self):
        verdict, _ = mc.classify(
            probe_payload(
                MP4_FAMILY,
                [vstream("h264"), vstream("mjpeg", attached_pic=True), astream("aac")],
            ),
            "C:/v/talk.mp4",
        )
        assert verdict == mc.VERDICT_PLAYABLE

    def test_subtitle_and_data_streams_do_not_gate_playback(self):
        verdict, _ = mc.classify(
            probe_payload(MP4_FAMILY, [vstream("h264"), astream("aac"), sstream()]),
            "C:/v/talk.mp4",
        )
        assert verdict == mc.VERDICT_PLAYABLE

    def test_pcm_audio_is_playable(self):
        verdict, _ = mc.classify(
            probe_payload(MKV_FAMILY, [vstream("h264"), astream("pcm_s16le")]),
            "C:/v/talk.mkv",
        )
        assert verdict == mc.VERDICT_REMUX  # pcm passes; only the container blocks

    def test_audio_only_mp3_is_playable(self):
        verdict, _ = mc.classify(probe_payload("mp3", [astream("mp3")]), "C:/v/pod.mp3")
        assert verdict == mc.VERDICT_PLAYABLE

    def test_empty_probe_is_proxy(self):
        verdict, reason = mc.classify({}, "C:/v/broken.bin")
        assert verdict == mc.VERDICT_PROXY
        assert "no streams" in reason

    def test_malformed_stream_entry_is_proxy(self):
        verdict, _ = mc.classify({"streams": ["garbage"]}, "C:/v/broken.mp4")
        assert verdict == mc.VERDICT_PROXY

    def test_unknown_codec_name_is_proxy(self):
        verdict, _ = mc.classify(probe_payload(MP4_FAMILY, [{"codec_type": "video"}]), "C:/v/odd.mp4")
        assert verdict == mc.VERDICT_PROXY


# --------------------------------------------------------------------------- #
# probe_media(): the ffprobe seam
# --------------------------------------------------------------------------- #
class FakeCompleted:
    def __init__(self, returncode: int, stdout: str):
        self.returncode = returncode
        self.stdout = stdout


class TestProbeMedia:
    def test_parses_json_from_a_successful_probe(self, settings):
        seen: list[list[str]] = []

        def runner(argv, capture_output, text, check):  # noqa: ANN001
            seen.append(list(argv))
            return FakeCompleted(0, '{"streams": [], "format": {}}')

        out = mc.probe_media("C:/v/talk.mp4", settings, runner=runner)
        assert out == {"streams": [], "format": {}}
        argv = seen[0]
        assert argv[-1] == "C:/v/talk.mp4"
        assert "-show_streams" in argv and "-show_format" in argv
        assert "json" in argv

    def test_nonzero_exit_yields_empty(self, settings):
        out = mc.probe_media("x.mp4", settings, runner=lambda *a, **k: FakeCompleted(1, "{}"))
        assert out == {}

    def test_garbage_stdout_yields_empty(self, settings):
        out = mc.probe_media("x.mp4", settings, runner=lambda *a, **k: FakeCompleted(0, "not json"))
        assert out == {}

    def test_non_dict_json_yields_empty(self, settings):
        out = mc.probe_media("x.mp4", settings, runner=lambda *a, **k: FakeCompleted(0, "[1,2]"))
        assert out == {}


# --------------------------------------------------------------------------- #
# argv builders (pure)
# --------------------------------------------------------------------------- #
class TestArgvBuilders:
    def test_remux_argv_is_a_stream_copy_to_mp4(self, settings):
        argv = mc.build_remux_argv("C:/in dir/a video.mkv", "C:/out dir/a video.mp4", settings)
        assert isinstance(argv, list) and all(isinstance(a, str) for a in argv)
        # -c copy adjacency + faststart + progress for run()'s parser
        i = argv.index("-c")
        assert argv[i + 1] == "copy"
        assert "+faststart" in argv
        assert "-progress" in argv and "pipe:1" in argv
        # paths with spaces stay single argv elements; out is last, in follows -i
        assert argv[argv.index("-i") + 1] == "C:/in dir/a video.mkv"
        assert argv[-1] == "C:/out dir/a video.mp4"
        # subtitle/data/attachment streams dropped (mp4-illegal under -c copy)
        assert "-0:s" in argv and "-0:d" in argv and "-0:t" in argv

    def test_proxy_argv_is_h264_720p(self, settings):
        argv = mc.build_proxy_argv("C:/v/in.mkv", "C:/p/out.mp4", settings)
        assert "libx264" in argv
        assert "scale=-2:720" in argv
        assert "aac" in argv
        assert "yuv420p" in argv
        assert "+faststart" in argv
        assert argv[argv.index("-i") + 1] == "C:/v/in.mkv"
        assert argv[-1] == "C:/p/out.mp4"

    def test_builders_resolve_ffmpeg_from_settings(self, settings, bin_dir):
        argv = mc.build_proxy_argv("in.mkv", "out.mp4", settings)
        assert Path(argv[0]).parent == bin_dir


# --------------------------------------------------------------------------- #
# cache path derivation
# --------------------------------------------------------------------------- #
class TestProxyCachePath:
    def test_keyed_by_video_id_and_mtime(self, tmp_path):
        p1 = mc.proxy_cache_path(tmp_path, "abc123", 111)
        p2 = mc.proxy_cache_path(tmp_path, "abc123", 222)
        assert p1 != p2
        assert p1.name == "abc123-111.mp4"
        assert p1.parent == tmp_path

    def test_video_id_is_sanitized_for_the_filesystem(self, tmp_path):
        p = mc.proxy_cache_path(tmp_path, "../../evil id", 5)
        assert p.parent == tmp_path
        assert "/" not in p.name and ".." not in p.name


# --------------------------------------------------------------------------- #
# the service: media.playable
# --------------------------------------------------------------------------- #
def make_service(
    tmp_path: Path,
    settings: dict[str, Any],
    sources: dict[str, str],
    probe_result: dict[str, Any] | None = None,
    run=None,
) -> mc.MediaCompat:
    return mc.MediaCompat(
        resolver=lambda vid: sources.get(vid),
        settings_provider=lambda: settings,
        proxies_dir=tmp_path / "proxies",
        probe=(lambda path, s: probe_result) if probe_result is not None else None,
        run=run,
    )


@pytest.fixture()
def direct_ctx() -> RpcContext:
    return RpcContext(emit_notification=lambda obj: None, jobs=None)


class TestPlayable:
    def test_playable_verdict_for_h264_mp4(self, tmp_path, settings, direct_ctx):
        src = tmp_path / "talk.mp4"
        src.write_bytes(b"x")
        svc = make_service(
            tmp_path,
            settings,
            {"v1": str(src)},
            probe_payload(MP4_FAMILY, [vstream("h264"), astream("aac")]),
        )
        assert svc.playable({"videoId": "v1"}, direct_ctx) == {"playable": True}

    def test_remux_needed_reports_not_playable_with_reason(self, tmp_path, settings, direct_ctx):
        src = tmp_path / "talk.mkv"
        src.write_bytes(b"x")
        svc = make_service(
            tmp_path,
            settings,
            {"v1": str(src)},
            probe_payload(MKV_FAMILY, [vstream("h264"), astream("aac")]),
        )
        out = svc.playable({"videoId": "v1"}, direct_ctx)
        assert out["playable"] is False
        assert "container" in out["reason"]

    def test_proxy_needed_reports_not_playable_with_reason(self, tmp_path, settings, direct_ctx):
        src = tmp_path / "talk.mkv"
        src.write_bytes(b"x")
        svc = make_service(
            tmp_path,
            settings,
            {"v1": str(src)},
            probe_payload(MKV_FAMILY, [vstream("hevc"), astream("aac")]),
        )
        out = svc.playable({"videoId": "v1"}, direct_ctx)
        assert out["playable"] is False
        assert "hevc" in out["reason"]

    def test_cached_proxy_short_circuits_to_proxy_path(self, tmp_path, settings, direct_ctx):
        src = tmp_path / "talk.mkv"
        src.write_bytes(b"x")
        proxies = tmp_path / "proxies"
        proxies.mkdir()
        cached = mc.proxy_cache_path(proxies, "v1", os.stat(src).st_mtime_ns)
        cached.write_bytes(b"proxy")
        svc = make_service(
            tmp_path,
            settings,
            {"v1": str(src)},
            probe_payload(MKV_FAMILY, [vstream("hevc")]),
        )
        out = svc.playable({"videoId": "v1"}, direct_ctx)
        assert out == {"playable": True, "proxyPath": str(cached)}

    def test_source_mtime_change_invalidates_the_cache(self, tmp_path, settings, direct_ctx):
        src = tmp_path / "talk.mkv"
        src.write_bytes(b"x")
        proxies = tmp_path / "proxies"
        proxies.mkdir()
        stale = mc.proxy_cache_path(proxies, "v1", os.stat(src).st_mtime_ns - 1)
        stale.write_bytes(b"old proxy")
        svc = make_service(
            tmp_path,
            settings,
            {"v1": str(src)},
            probe_payload(MKV_FAMILY, [vstream("hevc")]),
        )
        out = svc.playable({"videoId": "v1"}, direct_ctx)
        assert out["playable"] is False  # stale cache ignored -> fresh verdict

    def test_unknown_video_id_raises_invalid_params(self, tmp_path, settings, direct_ctx):
        svc = make_service(tmp_path, settings, {})
        with pytest.raises(RpcError):
            svc.playable({"videoId": "nope"}, direct_ctx)
        with pytest.raises(RpcError):
            svc.playable({}, direct_ctx)

    def test_missing_source_file_is_not_playable(self, tmp_path, settings, direct_ctx):
        svc = make_service(tmp_path, settings, {"v1": str(tmp_path / "gone.mp4")})
        out = svc.playable({"videoId": "v1"}, direct_ctx)
        assert out["playable"] is False
        assert "not found" in out["reason"]

    def test_probe_crash_is_not_playable_never_a_server_error(self, tmp_path, settings, direct_ctx):
        src = tmp_path / "talk.mp4"
        src.write_bytes(b"x")

        def exploding_probe(path, s):  # noqa: ANN001
            raise OSError("boom")

        svc = mc.MediaCompat(
            resolver=lambda vid: str(src),
            settings_provider=lambda: settings,
            proxies_dir=tmp_path / "proxies",
            probe=exploding_probe,
        )
        out = svc.playable({"videoId": "v1"}, direct_ctx)
        assert out["playable"] is False


# --------------------------------------------------------------------------- #
# the service: media.proxy.start (job behavior, argv, caching)
# --------------------------------------------------------------------------- #
class RecordingRun:
    """A fake ffmpeg.run that records argv and writes the output file."""

    def __init__(self, exit_code: int = 0):
        self.exit_code = exit_code
        self.calls: list[list[str]] = []

    def __call__(self, argv, total_sec=0.0, on_progress=None, should_cancel=None, **kw):
        self.calls.append(list(argv))
        out = Path(argv[-1])
        out.parent.mkdir(parents=True, exist_ok=True)
        if self.exit_code == 0:
            out.write_bytes(b"derivative-bytes")
        if on_progress is not None:
            on_progress(50.0, "halfway")
        return self.exit_code


def run_job(svc: mc.MediaCompat, registry, video_id: str = "v1") -> Any:
    ctx = RpcContext(emit_notification=lambda obj: None, jobs=registry)
    res = svc.proxy_start({"videoId": video_id}, ctx)
    assert set(res) == {"jobId"}
    job = registry.get(res["jobId"])
    assert job is not None and job.wait(5.0)
    return job


class TestProxyStart:
    def test_hevc_source_builds_a_transcode_proxy_and_caches_it(self, tmp_path, settings, registry, collected):
        src = tmp_path / "talk.mkv"
        src.write_bytes(b"x")
        run = RecordingRun()
        svc = make_service(
            tmp_path,
            settings,
            {"v1": str(src)},
            probe_payload(MKV_FAMILY, [vstream("hevc"), astream("aac")]),
            run=run,
        )

        job = run_job(svc, registry)

        expected = mc.proxy_cache_path(tmp_path / "proxies", "v1", os.stat(src).st_mtime_ns)
        assert job.status.value == "done"
        assert job.result == {"path": str(expected)}
        assert expected.exists() and expected.read_bytes() == b"derivative-bytes"

        # transcode argv: h264 720p; built into the .partial then published
        argv = run.calls[0]
        assert "libx264" in argv and "scale=-2:720" in argv
        assert argv[-1].endswith(".partial.mp4")
        assert not Path(argv[-1]).exists()  # partial was atomically replaced

        # job.done carried the result through the registry sink
        done = [payload for kind, payload in collected if kind == "done"]
        assert done and done[0][1] == {"path": str(expected)}

    def test_h264_mkv_source_remuxes_with_stream_copy(self, tmp_path, settings, registry):
        src = tmp_path / "talk.mkv"
        src.write_bytes(b"x")
        run = RecordingRun()
        svc = make_service(
            tmp_path,
            settings,
            {"v1": str(src)},
            probe_payload(MKV_FAMILY, [vstream("h264"), astream("aac")]),
            run=run,
        )

        job = run_job(svc, registry)

        argv = run.calls[0]
        i = argv.index("-c")
        assert argv[i + 1] == "copy"
        assert "libx264" not in argv
        assert job.status.value == "done"

    def test_second_request_reuses_the_cache_without_re_encoding(self, tmp_path, settings, registry):
        src = tmp_path / "talk.mkv"
        src.write_bytes(b"x")
        run = RecordingRun()
        svc = make_service(
            tmp_path,
            settings,
            {"v1": str(src)},
            probe_payload(MKV_FAMILY, [vstream("hevc")]),
            run=run,
        )

        first = run_job(svc, registry)
        second = run_job(svc, registry)

        assert len(run.calls) == 1  # cache hit: ffmpeg ran exactly once
        assert second.result == first.result

    def test_playable_reports_the_built_proxy_afterwards(self, tmp_path, settings, registry, direct_ctx):
        src = tmp_path / "talk.mkv"
        src.write_bytes(b"x")
        svc = make_service(
            tmp_path,
            settings,
            {"v1": str(src)},
            probe_payload(MKV_FAMILY, [vstream("hevc")]),
            run=RecordingRun(),
        )

        job = run_job(svc, registry)
        out = svc.playable({"videoId": "v1"}, direct_ctx)
        assert out == {"playable": True, "proxyPath": job.result["path"]}

    def test_already_playable_source_returns_the_original_path(self, tmp_path, settings, registry):
        src = tmp_path / "talk.mp4"
        src.write_bytes(b"x")
        run = RecordingRun()
        svc = make_service(
            tmp_path,
            settings,
            {"v1": str(src)},
            probe_payload(MP4_FAMILY, [vstream("h264"), astream("aac")]),
            run=run,
        )

        job = run_job(svc, registry)
        assert job.result == {"path": str(src)}
        assert run.calls == []  # nothing to build

    def test_stale_cache_files_are_evicted_after_a_build(self, tmp_path, settings, registry):
        src = tmp_path / "talk.mkv"
        src.write_bytes(b"x")
        proxies = tmp_path / "proxies"
        proxies.mkdir()
        stale = mc.proxy_cache_path(proxies, "v1", 12345)
        stale.write_bytes(b"old")
        svc = make_service(
            tmp_path,
            settings,
            {"v1": str(src)},
            probe_payload(MKV_FAMILY, [vstream("hevc")]),
            run=RecordingRun(),
        )

        job = run_job(svc, registry)
        assert not stale.exists()
        assert Path(job.result["path"]).exists()

    def test_ffmpeg_failure_surfaces_via_the_job_done_error_payload(self, tmp_path, settings, registry, collected):
        src = tmp_path / "talk.mkv"
        src.write_bytes(b"x")
        svc = make_service(
            tmp_path,
            settings,
            {"v1": str(src)},
            probe_payload(MKV_FAMILY, [vstream("hevc")]),
            run=RecordingRun(exit_code=1),
        )

        job = run_job(svc, registry)

        assert job.status.value == "error"
        done = [payload for kind, payload in collected if kind == "done"]
        assert done, "a FAILED job must still emit job.done (A6 lesson 3)"
        error = done[0][1]["error"]
        assert "ffmpeg exited" in error["message"]
        assert error["type"] == "RuntimeError"
        # the half-written partial was cleaned up
        assert list((tmp_path / "proxies").glob("*.partial.mp4")) == []

    def test_cancellation_unwinds_and_cleans_the_partial(self, tmp_path, settings, registry, collected):
        src = tmp_path / "talk.mkv"
        src.write_bytes(b"x")

        def cancelling_run(argv, total_sec=0.0, on_progress=None, should_cancel=None, **kw):
            # Simulate the user cancelling mid-encode: flag the (only) job.
            for job_id in registry.all():
                registry.cancel(job_id)
            Path(argv[-1]).parent.mkdir(parents=True, exist_ok=True)
            Path(argv[-1]).write_bytes(b"partial-bytes")
            assert should_cancel is not None and should_cancel()
            return 255  # what a terminated ffmpeg would return

        svc = make_service(
            tmp_path,
            settings,
            {"v1": str(src)},
            probe_payload(MKV_FAMILY, [vstream("hevc")]),
            run=cancelling_run,
        )

        job = run_job(svc, registry)

        assert job.status.value == "cancelled"
        assert list((tmp_path / "proxies").glob("*")) == []  # no leftovers
        assert [k for k, _ in collected if k == "done"] == []  # no done on cancel

    def test_unknown_video_fails_the_request_not_the_job(self, tmp_path, settings, registry):
        svc = make_service(tmp_path, settings, {})
        ctx = RpcContext(emit_notification=lambda obj: None, jobs=registry)
        with pytest.raises(RpcError):
            svc.proxy_start({"videoId": "nope"}, ctx)
        assert registry.all() == {}

    def test_requires_a_job_registry(self, tmp_path, settings):
        src = tmp_path / "talk.mkv"
        src.write_bytes(b"x")
        svc = make_service(tmp_path, settings, {"v1": str(src)})
        with pytest.raises(RpcError):
            svc.proxy_start(
                {"videoId": "v1"},
                RpcContext(emit_notification=lambda obj: None, jobs=None),
            )


# --------------------------------------------------------------------------- #
# default_proxies_dir() + _settings() fallback + _build_derivative edges
# --------------------------------------------------------------------------- #
class TestProxiesDirAndSettings:
    def test_default_proxies_dir_is_under_config_dir(self, monkeypatch, tmp_path):
        monkeypatch.setenv("MEDIA_STUDIO_CONFIG_DIR", str(tmp_path))
        assert mc.default_proxies_dir() == tmp_path / "proxies"

    def test_settings_provider_crash_falls_back_to_empty(self, tmp_path, direct_ctx):
        src = tmp_path / "talk.mp4"
        src.write_bytes(b"x")

        def exploding_settings():
            raise RuntimeError("settings backend down")

        svc = mc.MediaCompat(
            resolver=lambda vid: str(src),
            settings_provider=exploding_settings,
            proxies_dir=tmp_path / "proxies",
            probe=lambda path, s: probe_payload(MP4_FAMILY, [vstream("h264"), astream("aac")]),
        )
        # A crashing settings provider must not break the verdict ({} is used).
        assert svc.playable({"videoId": "v1"}, direct_ctx) == {"playable": True}


class TestBuildDerivativeEdges:
    def test_unreadable_source_in_job_surfaces_runtime_error(
        self, tmp_path, settings, registry, collected, monkeypatch
    ):
        src = tmp_path / "talk.mkv"
        src.write_bytes(b"x")
        run = RecordingRun()
        svc = make_service(
            tmp_path,
            settings,
            {"v1": str(src)},
            probe_payload(MKV_FAMILY, [vstream("hevc")]),
            run=run,
        )

        # os.stat raising inside _build_derivative (source became unreadable after
        # the up-front resolve) must surface as the job's RuntimeError, never a 500.
        real_stat = os.stat

        def boom_stat(path, *a, **k):
            if str(path) == str(src):
                raise OSError("device gone")
            return real_stat(path, *a, **k)

        monkeypatch.setattr(mc.os, "stat", boom_stat)
        job = run_job(svc, registry)
        assert job.status.value == "error"
        done = [payload for kind, payload in collected if kind == "done"]
        assert "not readable" in done[0][1]["error"]["message"]
        assert run.calls == []  # never reached the ffmpeg run

    def test_non_numeric_probe_duration_defaults_total_to_zero(self, tmp_path, settings, registry):
        src = tmp_path / "talk.mkv"
        src.write_bytes(b"x")

        class TotalCapturingRun(RecordingRun):
            def __init__(self):
                super().__init__()
                self.totals: list[float] = []

            def __call__(self, argv, total_sec=0.0, on_progress=None, should_cancel=None, **kw):
                self.totals.append(total_sec)
                return super().__call__(argv, total_sec, on_progress, should_cancel, **kw)

        run = TotalCapturingRun()
        # A garbage (non-numeric) duration must coerce to 0.0, never crash.
        bad_probe = {
            "streams": [vstream("hevc"), astream("aac")],
            "format": {"format_name": MKV_FAMILY, "duration": "not-a-number"},
        }
        svc = make_service(tmp_path, settings, {"v1": str(src)}, bad_probe, run=run)
        job = run_job(svc, registry)
        assert job.status.value == "done"
        assert run.totals == [0.0]


# --------------------------------------------------------------------------- #
# register()
# --------------------------------------------------------------------------- #
class TestRegister:
    def test_registers_both_a2_methods_on_a_fake_registrar(self, tmp_path):
        registered: dict[str, Any] = {}
        svc = mc.register(
            resolver=lambda vid: None,
            proxies_dir=tmp_path,
            register_fn=lambda name, fn: registered.__setitem__(name, fn),
        )
        assert set(registered) == {"media.playable", "media.proxy.start"}
        assert registered["media.playable"] == svc.playable
        assert registered["media.proxy.start"] == svc.proxy_start

    def test_registers_on_the_real_protocol_registry_by_default(self, tmp_path):
        # conftest's autouse fixture snapshots/restores METHODS around this.
        mc.register(resolver=lambda vid: None, proxies_dir=tmp_path)
        assert "media.playable" in protocol.METHODS
        assert "media.proxy.start" in protocol.METHODS

    def test_duplicate_registration_fails_loudly(self, tmp_path):
        mc.register(resolver=lambda vid: None, proxies_dir=tmp_path)
        with pytest.raises(ValueError):
            mc.register(resolver=lambda vid: None, proxies_dir=tmp_path)
