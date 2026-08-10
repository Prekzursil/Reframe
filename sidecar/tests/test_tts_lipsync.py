"""Tests for the lip-sync module (features/tts/lipsync.py, WU-B1).

DONE criteria covered:

* the VERIFIED licence facts are asserted as data (LatentSync openrail++ /
  MuseTalk creativeml-openrail-m / Wav2Lip permanently denied), so a future
  edit that loosens a licence claim fails a test rather than shipping;
* the build flag is OFF by default and the handler HARD-REFUSES when off
  (both states asserted);
* the likeness-consent gate FAILS CLOSED — absent, false, and truthy-but-not-
  ``True`` all refuse; only a literal ``True`` passes;
* the cloned-voice consent gate FAILS CLOSED on a legacy row that carries no
  attestation field at all (the sibling WU-A2 surface does not exist yet);
* the pure builders (job payload / remux argv) and the whole orchestration
  (with a deterministic fake backend that writes REAL bytes) are exercised
  branch-by-branch, including every cancel point and both failure modes of
  the subprocess seam.

NOT covered here (honest scope): nothing in this file runs a real diffusion
model, a real GPU, or a real ffmpeg. ``syncConfidence`` is therefore never
computed by this suite — it is ``None`` unless a probe seam is injected, and
the real SyncNet/LSE-C measurement is the separate opt-in ``@e2e`` gate.
"""

from __future__ import annotations

import json
import re
import sys
import threading
from pathlib import Path
from typing import Any

import pytest
from media_studio import ffmpeg
from media_studio.features.tts import lipsync as ls
from media_studio.features.tts import lipsync_runner as lsr
from media_studio.jobs import JobContext
from media_studio.protocol import RpcContext, RpcError

DUB_TRACK = {
    "id": "at-dub",
    "lang": "ro",
    "name": "Dub (kokoro, ro)",
    "kind": "dub",
    "path": "",  # filled per-test with a real file
    "isAiGenerated": True,
}


@pytest.fixture(autouse=True)
def fake_ffmpeg(monkeypatch):
    """Pin binary resolution so tests never depend on a real ffmpeg install."""
    monkeypatch.setattr(ffmpeg, "ffmpeg_path", lambda settings=None: "/bin/ffmpeg")


def make_job_ctx(cancel: threading.Event | None = None) -> JobContext:
    return JobContext(
        job_id="job-lipsync",
        _cancel_event=cancel or threading.Event(),
        _emit_progress=lambda job_id, pct, message: None,
    )


def write_file(path: str | Path, data: bytes = b"\x00\x01\x02\x03") -> str:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return str(p)


class FakeBackend:
    """Deterministic backend: records events + writes a REAL output file."""

    def __init__(self, events: list[str] | None = None, *, produce: bool = True):
        self.events = events if events is not None else []
        self._produce = produce

    def relip(self, payload: dict[str, Any]) -> str:
        self.events.append(f"relip:{payload['engine']}:{payload['quality']}")
        if self._produce:
            write_file(payload["outVideo"], b"relipped-frames")
        return str(payload["outVideo"])

    def release(self) -> None:
        self.events.append("release")


def passthrough_run(argv, **kwargs) -> int:
    """Fake ffmpeg: writes a real file at argv[-1] and reports success."""
    write_file(argv[-1], b"muxed")
    return 0


# --------------------------------------------------------------------------- #
# licence facts (verified 2026-08-08 — see the module docstring for the probes)
# --------------------------------------------------------------------------- #
class TestLicenceFacts:
    def test_latentsync_is_the_primary_engine_and_is_openrail_plusplus(self):
        spec = ls.engine_spec("latentsync")
        assert ls.DEFAULT_ENGINE == "latentsync"
        assert spec.weights_license == "openrail++"
        assert spec.code_license == "Apache-2.0"
        # OpenRAIL PERMITS commercial use; it attaches behavioural
        # use-restrictions. Those are two separate facts, both asserted.
        assert spec.commercial is True
        assert spec.use_restricted is True
        assert "ByteDance/LatentSync" in spec.repo

    def test_musetalk_is_the_second_engine_and_is_creativeml_openrail_m(self):
        spec = ls.engine_spec("musetalk")
        assert spec.weights_license == "creativeml-openrail-m"
        assert spec.commercial is True
        assert spec.use_restricted is True

    def test_wav2lip_is_permanently_denied_not_merely_absent(self):
        assert "wav2lip" not in ls.ENGINES
        assert "wav2lip" in ls.DENIED_ENGINES
        with pytest.raises(ls.LipSyncError, match="non-commercial"):
            ls.engine_spec("wav2lip")

    def test_unknown_engine_is_refused_with_the_known_ids(self):
        with pytest.raises(ls.LipSyncError, match="latentsync"):
            ls.engine_spec("nope")

    def test_every_engine_carries_a_user_facing_notice(self):
        for spec in ls.ENGINES.values():
            assert spec.notice.strip()
            assert spec.label.strip()


# --------------------------------------------------------------------------- #
# the build flag — BOTH STATES
# --------------------------------------------------------------------------- #
class TestFeatureFlag:
    def test_disabled_by_default_when_the_setting_is_absent(self):
        assert ls.lipsync_enabled({}) is False
        assert ls.lipsync_enabled(None) is False

    def test_explicit_false_and_non_bool_truthy_are_both_disabled(self):
        assert ls.lipsync_enabled({ls.SETTING_ENABLED: False}) is False
        assert ls.lipsync_enabled({ls.SETTING_ENABLED: "yes"}) is False
        assert ls.lipsync_enabled({ls.SETTING_ENABLED: 1}) is False

    def test_literal_true_enables(self):
        assert ls.lipsync_enabled({ls.SETTING_ENABLED: True}) is True

    def test_require_enabled_refuses_when_off_and_passes_when_on(self):
        with pytest.raises(ls.LipSyncError, match="lipSyncEnabled"):
            ls.require_enabled({})
        assert ls.require_enabled({ls.SETTING_ENABLED: True}) is None


# --------------------------------------------------------------------------- #
# the likeness-consent gate — FAIL CLOSED
# --------------------------------------------------------------------------- #
class TestLikenessConsentGate:
    @pytest.mark.parametrize("params", [{}, {ls.CONSENT_PARAM: False}, {ls.CONSENT_PARAM: None}])
    def test_absent_or_false_refuses(self, params):
        with pytest.raises(ls.LikenessConsentError, match="likenessConsentAttested"):
            ls.require_likeness_consent(params)

    @pytest.mark.parametrize("value", ["true", "yes", 1, [1], {"a": 1}])
    def test_truthy_but_not_literal_true_refuses(self, value):
        with pytest.raises(ls.LikenessConsentError):
            ls.require_likeness_consent({ls.CONSENT_PARAM: value})

    def test_literal_true_passes(self):
        assert ls.require_likeness_consent({ls.CONSENT_PARAM: True}) is None

    def test_the_refusal_names_what_the_user_must_attest(self):
        with pytest.raises(ls.LikenessConsentError) as exc:
            ls.require_likeness_consent({})
        assert "likeness" in str(exc.value).lower()


# --------------------------------------------------------------------------- #
# the cloned-voice consent gate — the SIBLING-LANE dependency, fail-closed
# --------------------------------------------------------------------------- #
class TestSampleConsentGate:
    def test_legacy_row_without_the_field_is_not_attested(self):
        # WU-A2 is not on this branch: VoiceSample carries no consent field.
        # An absent field must read as NOT attested, never as "fine".
        assert ls.sample_consent_attested({"id": "s1", "name": "me"}) is False

    def test_explicit_false_and_truthy_non_bool_are_not_attested(self):
        assert ls.sample_consent_attested({ls.SAMPLE_CONSENT_FIELD: False}) is False
        assert ls.sample_consent_attested({ls.SAMPLE_CONSENT_FIELD: "yes"}) is False

    def test_a_missing_or_empty_sample_is_not_attested(self):
        assert ls.sample_consent_attested(None) is False
        assert ls.sample_consent_attested({}) is False

    def test_literal_true_is_attested(self):
        assert ls.sample_consent_attested({ls.SAMPLE_CONSENT_FIELD: True}) is True

    def test_require_refuses_a_missing_sample(self):
        with pytest.raises(ls.LikenessConsentError, match="s-ghost"):
            ls.require_sample_consent("s-ghost", None)

    def test_require_refuses_an_unattested_sample_and_names_the_gate(self):
        with pytest.raises(ls.LikenessConsentError, match="consentAttested"):
            ls.require_sample_consent("s1", {"id": "s1"})

    def test_require_passes_an_attested_sample(self):
        assert ls.require_sample_consent("s1", {"id": "s1", ls.SAMPLE_CONSENT_FIELD: True}) is None


# --------------------------------------------------------------------------- #
# the face-box gate — the LICENCE-critical one (never S3FD)
# --------------------------------------------------------------------------- #
class TestFaceBoxGate:
    def test_no_probe_refuses_rather_than_letting_the_engine_detect(self):
        # Returning [] here would let a MuseTalk-class backend fall back to its
        # bundled S3FD weight, which ships under NO licence — silently
        # reintroducing exactly what #287 removed. So it must refuse.
        with pytest.raises(ls.LipSyncError, match="S3FD"):
            ls.require_face_boxes(None, "v.mp4")

    def test_an_empty_detection_refuses_instead_of_relipping_nothing(self):
        with pytest.raises(ls.LipSyncError, match="no faces"):
            ls.require_face_boxes(lambda p: [], "v.mp4")

    def test_boxes_are_coerced_to_ints_and_passed_through(self):
        seen: list[str] = []

        def probe(path):
            seen.append(path)
            return [(1.7, 2.2, 3.9, 4.0), [5, 6, 7, 8]]

        assert ls.require_face_boxes(probe, "v.mp4") == [[1, 2, 3, 4], [5, 6, 7, 8]]
        assert seen == ["v.mp4"]


# --------------------------------------------------------------------------- #
# pure builders
# --------------------------------------------------------------------------- #
class TestJobPayload:
    def test_payload_carries_every_field_the_runner_parses(self, tmp_path):
        payload = ls.build_relip_job_payload(
            video_path=str(tmp_path / "in.mp4"),
            audio_path=str(tmp_path / "dub.m4a"),
            out_video=str(tmp_path / "out.mp4"),
            engine_id="latentsync",
            quality="quality",
            boxes=((10, 20, 30, 40), (11, 21, 31, 41)),
        )
        assert payload["engine"] == "latentsync"
        assert payload["quality"] == "quality"
        assert payload["boxes"] == [[10, 20, 30, 40], [11, 21, 31, 41]]
        # round-trips through JSON (it is written to a file for the subprocess)
        assert json.loads(json.dumps(payload)) == payload

    def test_boxes_default_to_empty_meaning_detect_in_the_backend(self, tmp_path):
        payload = ls.build_relip_job_payload(
            video_path=str(tmp_path / "in.mp4"),
            audio_path=str(tmp_path / "a.m4a"),
            out_video=str(tmp_path / "o.mp4"),
            engine_id="musetalk",
            quality="fast",
        )
        assert payload["boxes"] == []


class TestRemuxArgv:
    def test_argv_takes_video_from_the_relip_and_audio_from_the_dub(self, tmp_path):
        argv = ls.build_remux_argv("relip.mp4", "dub.m4a", str(tmp_path / "final.mp4"))
        assert argv[0] == "/bin/ffmpeg"
        assert argv[-1] == str(tmp_path / "final.mp4")
        # the two inputs, in order
        assert argv.index("relip.mp4") < argv.index("dub.m4a")
        # video from input 0, audio from input 1
        assert argv[argv.index("-map") + 1] == "0:v:0"
        assert argv[argv.index("-map", argv.index("-map") + 1) + 1] == "1:a:0"
        # stream copy: re-encoding the freshly generated frames would be a
        # second generational loss for zero benefit
        assert argv[argv.index("-c:v") + 1] == "copy"
        assert "-shortest" in argv

    def test_every_argv_element_is_a_string(self, tmp_path):
        argv = ls.build_remux_argv("a.mp4", "b.m4a", str(tmp_path / "c.mp4"), {"ffmpegPath": "/x/ffmpeg"})
        assert all(isinstance(a, str) for a in argv)


# --------------------------------------------------------------------------- #
# the subprocess backend seam
# --------------------------------------------------------------------------- #
class TestDefaultRunCmd:
    """The real drained-subprocess seam (no torch, no GPU — just a python -c)."""

    def test_runs_argv_and_drains_output(self):
        code, output = ls._default_run_cmd([sys.executable, "-c", "print('hello-from-relip')"])
        assert code == 0
        assert "hello-from-relip" in output

    def test_merges_stderr_and_applies_extra_env(self):
        script = "import os,sys; sys.stderr.write('ENV='+os.environ.get('MS_LS_TOK','')); print('out')"
        code, output = ls._default_run_cmd([sys.executable, "-c", script], {"MS_LS_TOK": "tok9"})
        assert code == 0
        # stderr merges into stdout so the failure tail lands in one place
        assert "ENV=tok9" in output
        assert "out" in output

    def test_nonzero_exit_is_reported(self):
        code, _ = ls._default_run_cmd([sys.executable, "-c", "raise SystemExit(4)"])
        assert code == 4


class TestSubprocessBackend:
    def test_argv_is_a_list_invoking_the_runner_module(self):
        argv = ls.build_relip_argv("/py/python.exe", "/tmp/job.json")
        assert argv == ["/py/python.exe", "-m", "lipsync_runner", "/tmp/job.json"]

    def test_extra_env_puts_the_isolated_env_first_on_pythonpath(self, tmp_path):
        env = ls.runner_extra_env(str(tmp_path / "envs" / "latentsync"))
        assert env["PYTHONPATH"].startswith(str(tmp_path / "envs" / "latentsync"))
        assert ls.runner_dir() in env["PYTHONPATH"]

    def test_missing_env_dir_refuses_before_spawning(self, tmp_path):
        backend = ls.SubprocessLipSyncBackend(
            env_dir=str(tmp_path / "absent"),
            python_exe="/py/python.exe",
            run_cmd=lambda argv, env=None: pytest.fail("must not spawn"),
        )
        with pytest.raises(ls.LipSyncError, match="env missing"):
            backend.relip(
                ls.build_relip_job_payload(
                    video_path="a.mp4", audio_path="b.m4a", out_video=str(tmp_path / "o.mp4"), engine_id="latentsync"
                )
            )

    def test_the_refusal_does_not_point_at_an_asset_that_cannot_install(self, tmp_path):
        """The env has NO manifest entry, so the message must not send the user to
        ``assets.ensure`` — that would fail with "unknown asset" and read as a bug
        in the installer rather than as unfinished provisioning.

        This pairs the message with the manifest state, so registering the asset
        later forces this message to be updated in the same commit.
        """
        from media_studio.assets import manifest

        assert ls.LIPSYNC_ENV_ASSET not in manifest.registry_snapshot(), (
            "the env is now a real asset — update the refusal message to point at assets.ensure"
        )
        backend = ls.SubprocessLipSyncBackend(
            env_dir=str(tmp_path / "absent"),
            python_exe="/py/python.exe",
            run_cmd=lambda argv, env=None: pytest.fail("must not spawn"),
        )
        with pytest.raises(ls.LipSyncError) as exc:
            backend.relip(
                ls.build_relip_job_payload(
                    video_path="a.mp4", audio_path="b.m4a", out_video=str(tmp_path / "o.mp4"), engine_id="latentsync"
                )
            )
        message = str(exc.value)
        assert "NOT YET PROVISIONED" in message
        assert "assets.ensure cannot install it" in message

    def test_nonzero_exit_surfaces_the_output_tail(self, tmp_path):
        env_dir = tmp_path / "env"
        env_dir.mkdir()
        backend = ls.SubprocessLipSyncBackend(
            env_dir=str(env_dir),
            python_exe="/py/python.exe",
            run_cmd=lambda argv, env=None: (7, "\n".join(f"line{i}" for i in range(30))),
        )
        with pytest.raises(ls.LipSyncError) as exc:
            backend.relip(
                ls.build_relip_job_payload(
                    video_path="a.mp4", audio_path="b.m4a", out_video=str(tmp_path / "o.mp4"), engine_id="latentsync"
                )
            )
        assert "exit 7" in str(exc.value)
        assert "line29" in str(exc.value)
        assert "line0" not in str(exc.value)  # tail only

    def test_zero_exit_with_no_output_file_is_still_a_failure(self, tmp_path):
        env_dir = tmp_path / "env"
        env_dir.mkdir()
        backend = ls.SubprocessLipSyncBackend(
            env_dir=str(env_dir), python_exe="/py/python.exe", run_cmd=lambda argv, env=None: (0, "")
        )
        with pytest.raises(ls.LipSyncError, match="produced no video"):
            backend.relip(
                ls.build_relip_job_payload(
                    video_path="a.mp4", audio_path="b.m4a", out_video=str(tmp_path / "o.mp4"), engine_id="latentsync"
                )
            )

    def test_success_returns_the_output_path_and_writes_the_job_json(self, tmp_path):
        env_dir = tmp_path / "env"
        env_dir.mkdir()
        seen: dict[str, Any] = {}

        def run_cmd(argv, env=None):
            seen["job"] = json.loads(Path(argv[-1]).read_text(encoding="utf-8"))
            seen["env"] = env
            write_file(seen["job"]["outVideo"], b"frames")
            return 0, "ok"

        backend = ls.SubprocessLipSyncBackend(env_dir=str(env_dir), python_exe="/py/python.exe", run_cmd=run_cmd)
        payload = ls.build_relip_job_payload(
            video_path="a.mp4", audio_path="b.m4a", out_video=str(tmp_path / "o.mp4"), engine_id="latentsync"
        )
        assert backend.relip(payload) == str(tmp_path / "o.mp4")
        assert seen["job"]["engine"] == "latentsync"
        assert "PYTHONPATH" in seen["env"]
        assert backend.release() is None

    def test_default_env_dir_and_python_are_derivable_without_an_install(self, tmp_path):
        assert ls.default_env_dir(str(tmp_path)).endswith(
            ls.LIPSYNC_ENV_DEST.replace("/", str(Path("/"))[0]).split("/")[-1]
        )
        backend = ls.SubprocessLipSyncBackend(assets_root=str(tmp_path))
        assert backend.env_dir.startswith(str(tmp_path))
        assert backend.python_exe


# --------------------------------------------------------------------------- #
# the pipeline
# --------------------------------------------------------------------------- #
def run_pipeline(tmp_path, **overrides):
    kwargs: dict[str, Any] = {
        "video_path": write_file(tmp_path / "in.mp4"),
        "audio_path": write_file(tmp_path / "dub.m4a"),
        "out_path": str(tmp_path / "out" / "relipped.mp4"),
        "work_dir": str(tmp_path / "work"),
        "backend": FakeBackend(),
        "run": passthrough_run,
    }
    kwargs.update(overrides)
    job_ctx = kwargs.pop("job_ctx", None) or make_job_ctx()
    return ls.run_lipsync_pipeline(job_ctx, **kwargs)


class TestPipeline:
    def test_happy_path_produces_the_muxed_video_and_releases_the_backend(self, tmp_path):
        events: list[str] = []
        result = run_pipeline(tmp_path, backend=FakeBackend(events))
        assert Path(result["path"]).is_file()
        assert Path(result["path"]).read_bytes() == b"muxed"
        assert result["engine"] == "latentsync"
        # the backend is released even on success (one model on a 6 GB GPU)
        assert events == [f"relip:latentsync:{ls.DEFAULT_QUALITY}", "release"]

    def test_sync_confidence_is_none_when_no_probe_is_injected(self, tmp_path):
        # HONEST: we do not measure lip-sync quality in-process. A caller that
        # wants a number must inject a probe; otherwise the field is None.
        assert run_pipeline(tmp_path)["syncConfidence"] is None

    def test_sync_confidence_comes_from_the_injected_probe(self, tmp_path):
        seen: list[tuple[str, str]] = []

        def probe(video: str, audio: str) -> float:
            seen.append((video, audio))
            return 7.25

        result = run_pipeline(tmp_path, confidence_probe=probe)
        assert result["syncConfidence"] == 7.25
        assert len(seen) == 1

    def test_missing_source_video_refuses_before_the_backend_runs(self, tmp_path):
        events: list[str] = []
        with pytest.raises(ls.LipSyncError, match="source video not found"):
            run_pipeline(tmp_path, video_path=str(tmp_path / "ghost.mp4"), backend=FakeBackend(events))
        assert events == []

    def test_missing_dub_audio_refuses_before_the_backend_runs(self, tmp_path):
        events: list[str] = []
        with pytest.raises(ls.LipSyncError, match="dub audio not found"):
            run_pipeline(tmp_path, audio_path=str(tmp_path / "ghost.m4a"), backend=FakeBackend(events))
        assert events == []

    def test_a_backend_that_reports_success_but_writes_nothing_fails(self, tmp_path):
        with pytest.raises(ls.LipSyncError, match="no re-lipped video"):
            run_pipeline(tmp_path, backend=FakeBackend(produce=False))

    def test_remux_failure_surfaces_the_exit_code(self, tmp_path):
        with pytest.raises(ls.LipSyncError, match="exit 3"):
            run_pipeline(tmp_path, run=lambda argv, **kw: 3)

    def test_remux_exit_zero_without_a_file_still_fails(self, tmp_path):
        with pytest.raises(ls.LipSyncError, match="produced no output"):
            run_pipeline(tmp_path, run=lambda argv, **kw: 0)

    def test_a_typed_backend_refusal_passes_through_unwrapped(self, tmp_path):
        # A LipSyncError from the backend (e.g. "env missing") already carries a
        # user-actionable message; re-wrapping it as "re-lip failed: ..." would
        # bury the instruction.
        class Refusing(FakeBackend):
            def relip(self, payload):
                raise ls.LipSyncError("lip-sync env missing at /nope")

        with pytest.raises(ls.LipSyncError, match="^lip-sync env missing"):
            run_pipeline(tmp_path, backend=Refusing())

    def test_backend_is_released_when_the_relip_raises(self, tmp_path):
        events: list[str] = []

        class Boom(FakeBackend):
            def relip(self, payload):
                self.events.append("relip")
                raise RuntimeError("cuda oom")

        with pytest.raises(ls.LipSyncError, match="cuda oom"):
            run_pipeline(tmp_path, backend=Boom(events))
        assert events == ["relip", "release"]

    def test_a_release_failure_never_masks_the_result(self, tmp_path):
        class BadRelease(FakeBackend):
            def release(self):
                raise RuntimeError("release blew up")

        assert Path(run_pipeline(tmp_path, backend=BadRelease())["path"]).is_file()

    @pytest.mark.parametrize("after", [0, 1, 2])
    def test_cancel_is_cooperative_at_every_stage(self, tmp_path, after):
        cancel = threading.Event()
        calls = {"n": 0}
        job_ctx = JobContext(
            job_id="job-cancel",
            _cancel_event=cancel,
            _emit_progress=lambda job_id, pct, message: None,
        )

        original = ls._checkpoint

        def counting(ctx, band, frac, message):
            if calls["n"] == after:
                cancel.set()
            calls["n"] += 1
            original(ctx, band, frac, message)

        ls._checkpoint = counting
        try:
            with pytest.raises(Exception):  # noqa: B017,PT011 - JobCancelled is framework-typed
                run_pipeline(tmp_path, job_ctx=job_ctx)
        finally:
            ls._checkpoint = original

    def test_unknown_engine_is_refused_by_the_pipeline_too(self, tmp_path):
        with pytest.raises(ls.LipSyncError, match="nope"):
            run_pipeline(tmp_path, engine_id="nope")

    def test_unknown_quality_is_refused(self, tmp_path):
        with pytest.raises(ls.LipSyncError, match="quality"):
            run_pipeline(tmp_path, quality="ultra")


# --------------------------------------------------------------------------- #
# the service + tts.lipsync.start handler
# --------------------------------------------------------------------------- #
def make_service(tmp_path, **overrides):
    video = write_file(tmp_path / "media" / "v1.mp4")
    dub = write_file(tmp_path / "media" / "dub.m4a")
    track = {**DUB_TRACK, "path": dub}
    kwargs: dict[str, Any] = {
        "resolver": lambda vid: video if vid == "v1" else None,
        "load_audio_track": lambda vid, tid: track if tid == track["id"] else None,
        "get_sample": lambda sid: None,
        "backend_factory": lambda engine_id, settings: FakeBackend(),
        "settings_provider": lambda: {ls.SETTING_ENABLED: True},
        "run": passthrough_run,
        # Stands in for the vendored MIT YuNet output the real wiring supplies.
        "face_boxes_probe": lambda path: [(10, 20, 30, 40)],
        "out_dir": str(tmp_path / "lipsync"),
    }
    kwargs.update(overrides)
    return ls.LipSyncService(**kwargs)


def ok_params(**extra) -> dict[str, Any]:
    return {"videoId": "v1", "audioTrackId": "at-dub", ls.CONSENT_PARAM: True, **extra}


class TestHandler:
    def test_disabled_build_refuses_before_any_validation(self, tmp_path, registry):
        service = make_service(tmp_path, settings_provider=lambda: {})
        ctx = RpcContext(emit_notification=lambda o: None, jobs=registry)
        with pytest.raises(RpcError, match="lipSyncEnabled"):
            service.lipsync_start({}, ctx)

    def test_consent_is_required_even_on_an_enabled_build(self, tmp_path, registry):
        service = make_service(tmp_path)
        ctx = RpcContext(emit_notification=lambda o: None, jobs=registry)
        with pytest.raises(RpcError, match="likenessConsentAttested"):
            service.lipsync_start({"videoId": "v1", "audioTrackId": "at-dub"}, ctx)

    @pytest.mark.parametrize("missing", ["videoId", "audioTrackId"])
    def test_required_params(self, tmp_path, registry, missing):
        service = make_service(tmp_path)
        ctx = RpcContext(emit_notification=lambda o: None, jobs=registry)
        params = ok_params()
        del params[missing]
        with pytest.raises(RpcError, match=missing):
            service.lipsync_start(params, ctx)

    def test_unknown_engine_and_quality_refused(self, tmp_path, registry):
        service = make_service(tmp_path)
        ctx = RpcContext(emit_notification=lambda o: None, jobs=registry)
        with pytest.raises(RpcError, match="(?i)wav2lip"):
            service.lipsync_start(ok_params(engine="wav2lip"), ctx)
        with pytest.raises(RpcError, match="quality"):
            service.lipsync_start(ok_params(quality="ultra"), ctx)

    def test_non_string_engine_is_refused(self, tmp_path, registry):
        service = make_service(tmp_path)
        ctx = RpcContext(emit_notification=lambda o: None, jobs=registry)
        with pytest.raises(RpcError, match="engine"):
            service.lipsync_start(ok_params(engine=7), ctx)

    def test_non_string_quality_is_refused(self, tmp_path, registry):
        service = make_service(tmp_path)
        ctx = RpcContext(emit_notification=lambda o: None, jobs=registry)
        with pytest.raises(RpcError, match="quality must be a string"):
            service.lipsync_start(ok_params(quality=2), ctx)

    def test_unknown_video_refused(self, tmp_path, registry):
        service = make_service(tmp_path)
        ctx = RpcContext(emit_notification=lambda o: None, jobs=registry)
        with pytest.raises(RpcError, match="unknown video"):
            service.lipsync_start(ok_params(videoId="ghost"), ctx)

    def test_unknown_audio_track_refused(self, tmp_path, registry):
        service = make_service(tmp_path)
        ctx = RpcContext(emit_notification=lambda o: None, jobs=registry)
        with pytest.raises(RpcError, match="unknown audio track"):
            service.lipsync_start(ok_params(audioTrackId="ghost"), ctx)

    def test_a_non_dub_track_is_refused(self, tmp_path, registry):
        original = {**DUB_TRACK, "kind": "original", "path": write_file(tmp_path / "orig.m4a")}
        service = make_service(tmp_path, load_audio_track=lambda vid, tid: original)
        ctx = RpcContext(emit_notification=lambda o: None, jobs=registry)
        with pytest.raises(RpcError, match="dub"):
            service.lipsync_start(ok_params(), ctx)

    def test_a_track_whose_audio_file_is_gone_is_refused(self, tmp_path, registry):
        gone = {**DUB_TRACK, "path": str(tmp_path / "gone.m4a")}
        service = make_service(tmp_path, load_audio_track=lambda vid, tid: gone)
        ctx = RpcContext(emit_notification=lambda o: None, jobs=registry)
        with pytest.raises(RpcError, match="dub audio not found"):
            service.lipsync_start(ok_params(), ctx)

    def test_a_cloned_voice_without_a_consent_record_is_refused(self, tmp_path, registry):
        cloned = {**DUB_TRACK, "voice": "s1", "path": write_file(tmp_path / "d.m4a")}
        service = make_service(
            tmp_path,
            load_audio_track=lambda vid, tid: cloned,
            get_sample=lambda sid: {"id": "s1", "name": "me"},  # legacy row, no attestation
        )
        ctx = RpcContext(emit_notification=lambda o: None, jobs=registry)
        with pytest.raises(RpcError, match="consentAttested"):
            service.lipsync_start(ok_params(), ctx)

    def test_a_cloned_voice_with_a_consent_record_is_allowed(self, tmp_path, registry):
        cloned = {**DUB_TRACK, "voice": "s1", "path": write_file(tmp_path / "d.m4a")}
        service = make_service(
            tmp_path,
            load_audio_track=lambda vid, tid: cloned,
            get_sample=lambda sid: {"id": "s1", ls.SAMPLE_CONSENT_FIELD: True},
        )
        ctx = RpcContext(emit_notification=lambda o: None, jobs=registry)
        assert set(service.lipsync_start(ok_params(), ctx)) == {"jobId"}
        registry.join(timeout=10)

    def test_a_named_catalog_voice_needs_no_sample_record(self, tmp_path, registry):
        named = {**DUB_TRACK, "voice": "af_sarah", "path": write_file(tmp_path / "d.m4a")}
        service = make_service(
            tmp_path,
            load_audio_track=lambda vid, tid: named,
            get_sample=lambda sid: None,  # not a stored clone
        )
        ctx = RpcContext(emit_notification=lambda o: None, jobs=registry)
        assert set(service.lipsync_start(ok_params(), ctx)) == {"jobId"}
        registry.join(timeout=10)

    def test_no_job_registry_is_an_internal_error(self, tmp_path):
        service = make_service(tmp_path)
        ctx = RpcContext(emit_notification=lambda o: None, jobs=None)
        with pytest.raises(RpcError, match="job registry"):
            service.lipsync_start(ok_params(), ctx)

    def test_settings_provider_failure_never_breaks_the_gate(self, tmp_path, registry):
        def boom():
            raise RuntimeError("settings gone")

        service = make_service(tmp_path, settings_provider=boom)
        ctx = RpcContext(emit_notification=lambda o: None, jobs=registry)
        # a broken settings read must FAIL CLOSED (the flag defaults OFF)
        with pytest.raises(RpcError, match="lipSyncEnabled"):
            service.lipsync_start(ok_params(), ctx)

    def test_full_job_returns_the_relipped_path(self, tmp_path, registry, collected):
        service = make_service(tmp_path)
        ctx = RpcContext(emit_notification=lambda o: None, jobs=registry)
        assert set(service.lipsync_start(ok_params(), ctx)) == {"jobId"}
        registry.join(timeout=10)
        done = [payload for kind, payload in collected if kind == "done"]
        assert len(done) == 1
        _job_id, payload = done[0]
        assert Path(payload["path"]).is_file()
        assert payload["engine"] == "latentsync"
        # HONEST: no SyncNet ran, so the field is None rather than a number.
        assert payload["syncConfidence"] is None

    def test_the_job_is_gpu_tagged_so_it_never_co_resides(self, tmp_path, registry):
        service = make_service(tmp_path)
        ctx = RpcContext(emit_notification=lambda o: None, jobs=registry)
        job_id = service.lipsync_start(ok_params(), ctx)["jobId"]
        assert registry.get(job_id).gpu is True
        registry.join(timeout=10)

    def test_default_out_dir_is_derived_when_none_is_injected(self, tmp_path, monkeypatch):
        from media_studio import settings_store

        monkeypatch.setattr(settings_store, "default_config_dir", lambda: tmp_path / "cfg")
        service = make_service(tmp_path, out_dir=None)
        assert str(tmp_path / "cfg") in str(service._out_dir_for("v1"))

    def test_default_backend_factory_builds_the_subprocess_backend(self, tmp_path):
        backend = ls.default_backend_factory("latentsync", {})
        assert isinstance(backend, ls.SubprocessLipSyncBackend)

    def test_an_unwired_face_box_probe_fails_the_JOB_not_the_request(self, tmp_path, registry, collected):
        # It is unfinished WIRING, not bad user input, so it must surface as a
        # job failure naming S3FD — never as a silent run with no boxes.
        service = make_service(tmp_path, face_boxes_probe=None)
        ctx = RpcContext(emit_notification=lambda o: None, jobs=registry)
        job_id = service.lipsync_start(ok_params(), ctx)["jobId"]
        registry.join(timeout=10)
        done = [payload for kind, payload in collected if kind == "done"]
        assert len(done) == 1
        _job_id, payload = done[0]
        # A failure emits job.done WITH an error payload (never a hang, never a
        # payload that looks like success).
        assert "path" not in payload
        assert payload["error"]["type"] == "LipSyncError"
        assert "S3FD" in payload["error"]["message"]
        assert "S3FD" in str(registry.get(job_id).error)

    def test_the_boxes_reach_the_backend_payload(self, tmp_path, registry):
        seen: list[dict[str, Any]] = []

        class Recording(FakeBackend):
            def relip(self, payload):
                seen.append(payload)
                return super().relip(payload)

        service = make_service(
            tmp_path,
            backend_factory=lambda engine_id, settings: Recording(),
            face_boxes_probe=lambda path: [(1, 2, 3, 4), (5, 6, 7, 8)],
        )
        ctx = RpcContext(emit_notification=lambda o: None, jobs=registry)
        service.lipsync_start(ok_params(), ctx)
        registry.join(timeout=10)
        assert seen and seen[0]["boxes"] == [[1, 2, 3, 4], [5, 6, 7, 8]]


# --------------------------------------------------------------------------- #
# the package register() wiring
# --------------------------------------------------------------------------- #
class FakeAudioTracksService:
    """Only the ``list`` shape register() derives its loader from."""

    def __init__(self, rows):
        self._rows = rows

    def list(self, params, ctx):
        assert params["videoId"] == "v1"
        return {"audioTracks": list(self._rows)}


class TestRegisterWiring:
    def test_lipsync_start_is_registered_alongside_the_dub_methods(self, tmp_path):
        from media_studio.features import tts as tts_pkg
        from media_studio.features.tts.voices import VoiceStore

        registered: dict[str, Any] = {}
        tts_pkg.register(
            resolver=lambda vid: str(tmp_path / "v.mp4"),
            load_track=lambda vid, tid: {"cues": [], "lang": "en"},
            audio_tracks=FakeAudioTracksService([]),
            voice_store=VoiceStore(tmp_path / "voices", duration_probe=lambda p: 1.0),
            register_fn=lambda name, handler: registered.__setitem__(name, handler),
        )
        assert "tts.lipsync.start" in registered
        assert {"tts.voices", "tts.sample.add", "tts.dub.start"} <= set(registered)

    def test_the_registered_handler_is_disabled_by_default(self, tmp_path, registry):
        from media_studio.features import tts as tts_pkg
        from media_studio.features.tts.voices import VoiceStore

        registered: dict[str, Any] = {}
        tts_pkg.register(
            resolver=lambda vid: str(tmp_path / "v.mp4"),
            load_track=lambda vid, tid: {"cues": [], "lang": "en"},
            audio_tracks=FakeAudioTracksService([]),
            voice_store=VoiceStore(tmp_path / "voices", duration_probe=lambda p: 1.0),
            register_fn=lambda name, handler: registered.__setitem__(name, handler),
        )
        ctx = RpcContext(emit_notification=lambda o: None, jobs=registry)
        # No settings_provider was passed, so the flag is absent -> refused.
        with pytest.raises(RpcError, match="lipSyncEnabled"):
            registered["tts.lipsync.start"](ok_params(), ctx)

    def test_the_derived_loader_finds_the_track_by_id(self, tmp_path, registry):
        from media_studio.features import tts as tts_pkg
        from media_studio.features.tts.voices import VoiceStore

        dub = write_file(tmp_path / "dub.m4a")
        rows = [{"id": "other", "kind": "original"}, {**DUB_TRACK, "path": dub}]
        registered: dict[str, Any] = {}
        tts_pkg.register(
            resolver=lambda vid: write_file(tmp_path / "v.mp4"),
            load_track=lambda vid, tid: {"cues": [], "lang": "en"},
            audio_tracks=FakeAudioTracksService(rows),
            voice_store=VoiceStore(tmp_path / "voices", duration_probe=lambda p: 1.0),
            settings_provider=lambda: {ls.SETTING_ENABLED: True},
            lipsync_backend_factory=lambda engine_id, settings: FakeBackend(),
            lipsync_face_boxes_probe=lambda path: [(1, 2, 3, 4)],
            out_dir=str(tmp_path / "out"),
            register_fn=lambda name, handler: registered.__setitem__(name, handler),
        )
        ctx = RpcContext(emit_notification=lambda o: None, jobs=registry)
        # 'other' resolves but is not a dub; 'at-dub' resolves and is.
        with pytest.raises(RpcError, match="not a dub"):
            registered["tts.lipsync.start"](ok_params(audioTrackId="other"), ctx)
        with pytest.raises(RpcError, match="unknown audio track"):
            registered["tts.lipsync.start"](ok_params(audioTrackId="ghost"), ctx)
        assert set(registered["tts.lipsync.start"](ok_params(), ctx)) == {"jobId"}
        registry.join(timeout=10)


class TestSettingParity:
    def test_the_flag_is_off_in_the_shipped_defaults(self):
        from media_studio.settings_store import DEFAULT_SETTINGS

        assert DEFAULT_SETTINGS[ls.SETTING_ENABLED] is False
        assert ls.lipsync_enabled(DEFAULT_SETTINGS) is False


# --------------------------------------------------------------------------- #
# cross-file licence drift guard
# --------------------------------------------------------------------------- #
_REPO_ROOT = Path(__file__).resolve().parents[2]
_NOTICES_TSX = _REPO_ROOT / "app" / "renderer" / "src" / "features" / "ThirdPartyNotices.tsx"
_PANEL_TSX = _REPO_ROOT / "app" / "renderer" / "src" / "features" / "LipSync.tsx"
_LICENSES_DOC = _REPO_ROOT / "docs/THIRD-PARTY-LICENSES.md"  # ssot-allow: this IS the path, joined for the gate's r5


def _tsx_prose(path: Path) -> str:
    """A .tsx file's user-facing sentences, with concat seams closed up.

    A long sentence in a .tsx file is written as several quoted literals joined
    with ``+`` across lines, so a raw substring search for the sentence reports a
    FALSE ABSENCE. This rejoins ``' + '`` seams and collapses whitespace so a
    clause can be searched as the user reads it. Controlled by
    ``test_the_prose_normaliser_can_find_a_known_present_clause``.
    """
    return " ".join(re.sub(r"'\s*\+\s*'", "", path.read_text(encoding="utf-8")).split())


class TestLicenceDriftGuard:
    """The same licence fact lives in FOUR files. Assert it agrees in all four.

    A licence claim is precisely the kind of duplicated fact that must not drift:
    the engine registry decides what runs, the notices component is the reference
    list the user can browse, the licences doc is where the pass-through
    obligation is recorded, and ``features/LipSync.tsx`` shows it AT THE POINT OF
    USE (the panel where the user clicks "Re-lip to this dub"). A silent
    disagreement between them is a misrepresentation, so this reads the other
    three files rather than trusting a comment to keep them in step.

    W19/W20 UPDATE — this guard was written for THREE files and an adversarial
    review caught the gap: the new panel introduced a fourth copy of the same
    facts (weights licence, engine label, the OpenRAIL pass-on obligation) that
    the guard did not read, so its own premise had gone stale. The panel copy is
    the one a user actually reads before consenting, which makes it the worst
    place for a drifted licence, not the most forgivable.
    """

    def test_the_renderer_notice_quotes_the_same_weights_licences(self):
        source = _NOTICES_TSX.read_text(encoding="utf-8")
        for spec in ls.ENGINES.values():
            assert f"weightsLicense: '{spec.weights_license}'" in source, (
                f"{spec.id}: the notices component does not carry weights licence {spec.weights_license!r}"
            )
            assert f"codeLicense: '{spec.code_license}'" in source
            assert f"commercial: {str(spec.commercial).lower()}" in source
            assert f"useRestricted: {str(spec.use_restricted).lower()}" in source

    def test_the_renderer_notice_never_calls_these_models_non_commercial(self):
        # The plan doc's original verdict. If it reappears in the shipped UI the
        # user is told something the licence text contradicts.
        source = _NOTICES_TSX.read_text(encoding="utf-8")
        optin = source.split("OPT_IN_MODEL_NOTICES")[-1]
        assert "commercial: false" not in optin
        assert "useRestricted: false" not in optin

    def test_the_licences_doc_records_both_engines_and_the_denied_one(self):
        # Whitespace-normalised: the quoted clause is wrapped across markdown
        # lines (and the blob is LF while the worktree is CRLF), so a raw
        # substring search would report a false absence on a pure re-flow.
        doc = " ".join(_LICENSES_DOC.read_text(encoding="utf-8").replace(">", " ").split())
        for spec in ls.ENGINES.values():
            assert spec.weights_license in doc, f"{spec.id}: licence absent from docs/THIRD-PARTY-LICENSES.md"
        assert "Wav2Lip is excluded" in doc
        # The flow-down clause is the obligation an attribution block does NOT
        # discharge, so it must be quoted somewhere durable.
        assert "MUST be included as an enforceable provision" in doc

    def test_the_setting_name_is_the_same_string_in_the_ui_and_the_gate(self):
        assert f"gatedBy: '{ls.SETTING_ENABLED}'" in _NOTICES_TSX.read_text(encoding="utf-8")

    def test_the_lipsync_PANEL_quotes_the_same_engines_labels_and_licences(self):
        # The panel is the FOURTH copy and the one shown at the point of consent.
        # Field-shaped assertions (`id: '...'`, not a bare substring) so a mention
        # in a comment cannot satisfy the gate — the use-vs-mention discipline.
        source = _PANEL_TSX.read_text(encoding="utf-8")
        for spec in ls.ENGINES.values():
            assert f"id: '{spec.id}'" in source, f"{spec.id}: the lip-sync panel does not offer this engine"
            assert f"label: '{spec.label}'" in source, f"{spec.id}: the panel's label has drifted from ENGINES"
            assert f"weightsLicense: '{spec.weights_license}'" in source, (
                f"{spec.id}: the panel does not carry weights licence {spec.weights_license!r}"
            )

    def test_the_lipsync_PANEL_never_offers_a_denied_engine(self):
        # `wav2lip` is genuinely non-commercial and permanently denied. It IS named
        # in the panel's comments (explaining the absence), so the assertion is on
        # the offered FIELD, never on the document.
        source = _PANEL_TSX.read_text(encoding="utf-8")
        for denied in ls.DENIED_ENGINES:
            assert f"id: '{denied}'" not in source, f"{denied} is DENIED but the panel offers it"

    def test_the_panel_carries_the_openrail_pass_on_obligation_verbatim(self):
        # The obligation is the half of an OpenRAIL licence an attribution block
        # does NOT discharge: it binds the USER and must be passed downstream. The
        # panel rewords the sentence around it for a user reading it mid-task, so
        # only the load-bearing clause is pinned verbatim in both files.
        clause = "must pass on to anyone you give the output or the model to"
        assert clause in ls._OPENRAIL_NOTICE
        source = _tsx_prose(_PANEL_TSX)
        assert clause in source
        # ...and it must not be softened into the "non-commercial" misreading the
        # sidecar module exists to correct.
        assert "Commercial use IS permitted" in source

    def test_the_prose_normaliser_can_find_a_known_present_clause(self):
        # DETECTOR CONTROL for the test above. `_tsx_prose` exists because a
        # user-facing sentence in a .tsx file is written as several string literals
        # joined with `+` across lines, so a raw substring search reports a FALSE
        # ABSENCE — measured: the first draft of that assertion failed against a
        # panel that carries the clause. Prove the reassembly works on a literal
        # that IS split, and that the raw source does NOT contain it.
        clause = "must pass on to anyone you give the output or the model to"
        assert clause not in _PANEL_TSX.read_text(encoding="utf-8")
        assert clause in _tsx_prose(_PANEL_TSX)


# --------------------------------------------------------------------------- #
# the isolated-env runner (its heavy body is pragma-no-cover)
# --------------------------------------------------------------------------- #
class TestRunnerJobParsing:
    def test_valid_job_parses(self, tmp_path):
        job = lsr.parse_job(
            {
                "videoPath": "a.mp4",
                "audioPath": "b.m4a",
                "outVideo": "c.mp4",
                "engine": "latentsync",
                "quality": "fast",
                "boxes": [[1, 2, 3, 4]],
            }
        )
        assert job["engine"] == "latentsync"
        assert job["boxes"] == [(1, 2, 3, 4)]

    @pytest.mark.parametrize(
        ("raw", "match"),
        [
            ("nope", "JSON object"),
            ({}, "videoPath"),
            ({"videoPath": "a"}, "audioPath"),
            ({"videoPath": "a", "audioPath": "b"}, "outVideo"),
            ({"videoPath": "a", "audioPath": "b", "outVideo": "c", "engine": ""}, "engine"),
            (
                {"videoPath": "a", "audioPath": "b", "outVideo": "c", "engine": "latentsync", "boxes": "x"},
                "boxes",
            ),
            (
                {"videoPath": "a", "audioPath": "b", "outVideo": "c", "engine": "latentsync", "boxes": [[1, 2]]},
                "boxes",
            ),
        ],
    )
    def test_invalid_jobs_raise(self, raw, match):
        with pytest.raises(ValueError, match=match):
            lsr.parse_job(raw)

    def test_quality_defaults_when_absent_or_unknown(self):
        base = {"videoPath": "a", "audioPath": "b", "outVideo": "c", "engine": "latentsync"}
        assert lsr.parse_job(base)["quality"] == ls.DEFAULT_QUALITY
        assert lsr.parse_job({**base, "quality": "ultra"})["quality"] == ls.DEFAULT_QUALITY

    def test_the_runner_is_standalone_and_its_literals_have_not_drifted(self):
        # The runner is executed as a TOP-LEVEL module in the isolated env, so it
        # must not import the package — which means its selector literals are a
        # deliberate duplicate. This is the drift guard for that duplicate.
        assert lsr.QUALITIES == ls.QUALITIES
        assert lsr.DEFAULT_QUALITY == ls.DEFAULT_QUALITY
        source = Path(lsr.__file__).read_text(encoding="utf-8")
        assert "from .lipsync" not in source
        assert "from media_studio" not in source

    def test_main_reports_usage_without_exactly_one_arg(self, capsys):
        assert lsr.main([]) == 2
        assert "usage" in capsys.readouterr().err

    def test_main_reports_a_bad_job_file(self, tmp_path, capsys):
        bad = tmp_path / "job.json"
        bad.write_text("{ not json", encoding="utf-8")
        assert lsr.main([str(bad)]) == 2
        assert "bad job file" in capsys.readouterr().err

    def test_main_reports_a_relip_failure(self, tmp_path, monkeypatch, capsys):
        job = tmp_path / "job.json"
        job.write_text(
            json.dumps({"videoPath": "a", "audioPath": "b", "outVideo": "c", "engine": "latentsync"}),
            encoding="utf-8",
        )
        monkeypatch.setattr(lsr, "_relip", lambda job: (_ for _ in ()).throw(RuntimeError("no cuda")))
        assert lsr.main([str(job)]) == 1
        assert "no cuda" in capsys.readouterr().err

    def test_main_succeeds_when_the_relip_succeeds(self, tmp_path, monkeypatch):
        job = tmp_path / "job.json"
        job.write_text(
            json.dumps({"videoPath": "a", "audioPath": "b", "outVideo": "c", "engine": "latentsync"}),
            encoding="utf-8",
        )
        monkeypatch.setattr(lsr, "_relip", lambda job: None)
        assert lsr.main([str(job)]) == 0
