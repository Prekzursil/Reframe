"""Tests for the batched dub pipeline + tts.dub.start (features/tts/dub.py, T2).

DONE criteria covered:

* the BATCHED stage ORDER is asserted — translate-ALL strictly before any
  synthesis, with the MT model freed in between (A4, frozen);
* the degenerate empty track surfaces a typed error;
* handler validation (engine ids, chatterbox sampleId) and the end-to-end
  job (registry fixture) with every heavy seam faked.
"""

from __future__ import annotations

import threading
import wave
from pathlib import Path
from typing import Any

import pytest
from media_studio import ffmpeg
from media_studio.features.tts import dub as d
from media_studio.features.tts.engine import (
    DEFAULT_SAMPLE_RATE,
    TtsEngine,
    write_pcm_wav,
)
from media_studio.features.tts.voices import VoiceStore
from media_studio.jobs import JobContext
from media_studio.protocol import RpcContext, RpcError

CUES = [
    {"index": 1, "start": 0.0, "end": 2.0, "text": "First line."},
    {"index": 2, "start": 2.0, "end": 4.0, "text": "Second line."},
]


@pytest.fixture(autouse=True)
def fake_ffmpeg(monkeypatch):
    """Pin binary resolution so tests never depend on a real ffmpeg install."""
    monkeypatch.setattr(ffmpeg, "ffmpeg_path", lambda settings=None: "/bin/ffmpeg")
    monkeypatch.setattr(ffmpeg, "ffprobe_path", lambda settings=None: "/bin/ffprobe")


def make_job_ctx() -> JobContext:
    return JobContext(
        job_id="job-test",
        _cancel_event=threading.Event(),
        _emit_progress=lambda job_id, pct, message: None,
    )


def write_normalized_wav(path: str, seconds: float = 2.0) -> str:
    frames = b"\x01\x00" * int(seconds * DEFAULT_SAMPLE_RATE)
    return write_pcm_wav(path, frames)


class RecordingEngine(TtsEngine):
    """Fake engine: records events + writes real (normalized) wavs."""

    id = "fake"
    label = "fake"

    def __init__(self, events: list[str]):
        self.events = events

    def synth(self, cues, voice, lang, out_wav, *, rate=1.0):
        index = cues[0].get("index", "?")
        self.events.append(f"synth:{index}:{cues[0]['text']}")
        return write_normalized_wav(out_wav, 2.0)


class OnlineEngine(RecordingEngine):
    """A hosted/ONLINE engine (like edge-tts) — carries ``online = True``."""

    id = "online"
    label = "online"
    online = True


class RecordingTranslator:
    def __init__(self, events: list[str], result: list[str] | None = None):
        self.events = events
        self._result = result

    def translate(self, texts, target_lang, source_lang=None):
        self.events.append(f"translate:{len(texts)}:{target_lang}")
        if self._result is not None:
            return self._result
        return [f"[{target_lang}] {t}" for t in texts]

    def free(self):
        self.events.append("free")


def passthrough_run(argv, **kwargs) -> int:
    """Fake ffmpeg: 'aligns' by writing a real normalized wav at argv[-1]."""
    out = argv[-1]
    if str(out).endswith(".wav"):
        write_normalized_wav(out, 2.0)
    else:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_bytes(b"fake-aac")
    return 0


# --------------------------------------------------------------------------- #
# the pipeline — stage ORDER (frozen) + degenerate cases
# --------------------------------------------------------------------------- #
class TestPipelineOrder:
    def test_translate_all_before_any_synth_and_mt_freed_between(self, tmp_path):
        events: list[str] = []
        engine = RecordingEngine(events)
        translator = RecordingTranslator(events)
        result = d.run_dub_pipeline(
            make_job_ctx(),
            cues=CUES,
            engine=engine,
            voice="af_sarah",
            lang="en",
            work_dir=str(tmp_path / "work"),
            out_wav=str(tmp_path / "dub.wav"),
            target_lang="de",
            translator=translator,
            run=passthrough_run,
            duration=lambda p: 2.0,
        )
        # ONE batched translate call covering ALL cues
        translate_idx = [i for i, e in enumerate(events) if e.startswith("translate")]
        assert translate_idx == [0]
        assert events[0] == "translate:2:de"
        # MT freed BEFORE the first synthesis (never interleave model swaps)
        free_idx = events.index("free")
        synth_idx = [i for i, e in enumerate(events) if e.startswith("synth")]
        assert len(synth_idx) == len(CUES)
        assert free_idx < min(synth_idx)
        assert max(translate_idx) < min(synth_idx)
        # synthesis consumed the TRANSLATED text
        assert events[synth_idx[0]] == "synth:1:[de] First line."
        # the pipeline's cues carry the translation for downstream consumers
        assert [c["text"] for c in result["cues"]] == [
            "[de] First line.",
            "[de] Second line.",
        ]
        assert Path(result["path"]).is_file()

    def test_no_target_lang_never_touches_the_translator(self, tmp_path):
        events: list[str] = []
        translator = RecordingTranslator(events)
        d.run_dub_pipeline(
            make_job_ctx(),
            cues=CUES,
            engine=RecordingEngine(events),
            voice="v",
            lang="en",
            work_dir=str(tmp_path / "w"),
            out_wav=str(tmp_path / "o.wav"),
            translator=translator,
            run=passthrough_run,
            duration=lambda p: 2.0,
        )
        assert all(not e.startswith(("translate", "free")) for e in events)

    def test_empty_track_is_a_typed_error(self, tmp_path):
        with pytest.raises(d.DubError, match="no cues"):
            d.run_dub_pipeline(
                make_job_ctx(),
                cues=[],
                engine=RecordingEngine([]),
                voice="v",
                lang="en",
                work_dir=str(tmp_path / "w"),
                out_wav=str(tmp_path / "o.wav"),
                run=passthrough_run,
                duration=lambda p: 2.0,
            )

    def test_mismatched_translation_count_raises(self, tmp_path):
        events: list[str] = []
        with pytest.raises(d.DubError, match="mismatched"):
            d.run_dub_pipeline(
                make_job_ctx(),
                cues=CUES,
                engine=RecordingEngine(events),
                voice="v",
                lang="en",
                work_dir=str(tmp_path / "w"),
                out_wav=str(tmp_path / "o.wav"),
                target_lang="de",
                translator=RecordingTranslator(events, result=["only one"]),
                run=passthrough_run,
                duration=lambda p: 2.0,
            )
        # MT is freed even on the failure path (a retry starts clean)
        assert "free" in events

    def test_target_lang_without_backend_surfaces(self, tmp_path, monkeypatch):
        def no_backend():
            raise d.DubError("translation backend unavailable")

        monkeypatch.setattr(d, "_default_translator_factory", no_backend)
        with pytest.raises(d.DubError, match="translation backend"):
            d.run_dub_pipeline(
                make_job_ctx(),
                cues=CUES,
                engine=RecordingEngine([]),
                voice="v",
                lang="en",
                work_dir=str(tmp_path / "w"),
                out_wav=str(tmp_path / "o.wav"),
                target_lang="de",
                translator=None,
                run=passthrough_run,
                duration=lambda p: 2.0,
            )

    def test_concat_spans_total_duration(self, tmp_path):
        result = d.run_dub_pipeline(
            make_job_ctx(),
            cues=CUES,
            engine=RecordingEngine([]),
            voice="v",
            lang="en",
            work_dir=str(tmp_path / "w"),
            out_wav=str(tmp_path / "o.wav"),
            run=passthrough_run,
            duration=lambda p: 2.0,
            total_sec=6.0,
        )
        with wave.open(result["path"], "rb") as wf:
            duration = wf.getnframes() / wf.getframerate()
        assert duration == pytest.approx(6.0, abs=0.05)

    def test_translate_failure_is_wrapped_and_mt_freed(self, tmp_path):
        events: list[str] = []

        class ExplodingTranslator(RecordingTranslator):
            def translate(self, texts, target_lang, source_lang=None):
                self.events.append("translate-attempt")
                raise RuntimeError("MT crashed")

        with pytest.raises(d.DubError, match="translation failed"):
            d.run_dub_pipeline(
                make_job_ctx(),
                cues=CUES,
                engine=RecordingEngine(events),
                voice="v",
                lang="en",
                work_dir=str(tmp_path / "w"),
                out_wav=str(tmp_path / "o.wav"),
                target_lang="de",
                translator=ExplodingTranslator(events),
                run=passthrough_run,
                duration=lambda p: 2.0,
            )
        # MT still freed on the failure path so a retry starts clean
        assert "free" in events

    def test_translator_raising_dub_error_propagates_unwrapped(self, tmp_path):
        events: list[str] = []

        class DubErrorTranslator(RecordingTranslator):
            def translate(self, texts, target_lang, source_lang=None):
                raise d.DubError("already a dub error")

        with pytest.raises(d.DubError, match="already a dub error"):
            d.run_dub_pipeline(
                make_job_ctx(),
                cues=CUES,
                engine=RecordingEngine(events),
                voice="v",
                lang="en",
                work_dir=str(tmp_path / "w"),
                out_wav=str(tmp_path / "o.wav"),
                target_lang="de",
                translator=DubErrorTranslator(events),
                run=passthrough_run,
                duration=lambda p: 2.0,
            )
        # still freed on this path too
        assert "free" in events

    def test_translator_free_failure_is_swallowed(self, tmp_path):
        events: list[str] = []

        class FreeBoomTranslator(RecordingTranslator):
            def free(self):
                raise RuntimeError("free exploded")

        result = d.run_dub_pipeline(
            make_job_ctx(),
            cues=CUES,
            engine=RecordingEngine(events),
            voice="v",
            lang="en",
            work_dir=str(tmp_path / "w"),
            out_wav=str(tmp_path / "o.wav"),
            target_lang="de",
            translator=FreeBoomTranslator(events),
            run=passthrough_run,
            duration=lambda p: 2.0,
        )
        # the dub still completes despite free() raising
        assert Path(result["path"]).is_file()

    def test_resynth_closure_re_synthesizes_off_target_cue(self, tmp_path):
        """An off-target first take triggers the engine re-synth seam (line 193)."""
        synth_rates: list[float] = []

        class RateRecordingEngine(TtsEngine):
            id = "fake"
            label = "fake"

            def synth(self, cues, voice, lang, out_wav, *, rate=1.0):
                synth_rates.append(rate)
                return write_normalized_wav(out_wav, 2.0)

        # first probe says the raw take is far off target -> needs_resynth True;
        # the re-synth wav then reads close enough.
        def fake_duration(path):
            return 1.0 if str(path).endswith("-raw.wav") else 2.0

        d.run_dub_pipeline(
            make_job_ctx(),
            cues=[{"index": 1, "start": 0.0, "end": 2.0, "text": "Line."}],
            engine=RateRecordingEngine(),
            voice="v",
            lang="en",
            work_dir=str(tmp_path / "w"),
            out_wav=str(tmp_path / "o.wav"),
            run=passthrough_run,
            duration=fake_duration,
        )
        # the second synth call carries a non-default rate (the re-synth ask)
        assert any(r != 1.0 for r in synth_rates)


class TestEncodeArgv:
    def test_aac_argv_shape(self):
        argv = d.build_encode_aac_argv("C:/d ubs/dub.wav", "C:/d ubs/dub.m4a", {"ffmpegPath": "C:/ff/ffmpeg.exe"})
        assert argv[argv.index("-i") + 1] == "C:/d ubs/dub.wav"
        assert argv[argv.index("-c:a") + 1] == "aac"
        assert argv[-1] == "C:/d ubs/dub.m4a"


# --------------------------------------------------------------------------- #
# the service + handler
# --------------------------------------------------------------------------- #
class FakeAudioTracks:
    def __init__(self):
        self.calls: list[dict[str, Any]] = []

    def mux_for_dub(self, video_id, audio_path, *, lang, name, voice=None):
        call = {
            "videoId": video_id,
            "path": audio_path,
            "lang": lang,
            "name": name,
            "voice": voice,
        }
        self.calls.append(call)
        return {
            "id": "at-1",
            "lang": lang,
            "name": name,
            "kind": "dub",
            "path": audio_path,
            **({"voice": voice} if voice else {}),
        }


def make_service(tmp_path, *, engines=None, voice_store=None, audio_tracks=None):
    track = {"id": "t1", "lang": "en", "name": "EN", "format": "srt", "kind": "soft", "cues": CUES}
    return d.DubService(
        resolver=lambda vid: str(tmp_path / "video.mp4") if vid == "v1" else None,
        load_track=lambda vid, tid: dict(track),
        engines=engines or {"fake": lambda: RecordingEngine([])},
        voice_store=voice_store or VoiceStore(tmp_path / "voices", duration_probe=lambda p: 1.0),
        audio_tracks=audio_tracks or FakeAudioTracks(),
        run=passthrough_run,
        duration=lambda p: 2.0,
        out_dir=str(tmp_path / "dubs"),
    )


class TestDubStartHandler:
    def test_unknown_engine_rejected(self, tmp_path, registry):
        service = make_service(tmp_path)
        ctx = RpcContext(emit_notification=lambda o: None, jobs=registry)
        with pytest.raises(RpcError, match="unknown engine"):
            service.dub_start({"videoId": "v1", "trackId": "t1", "engine": "espeak"}, ctx)

    def test_unknown_video_rejected(self, tmp_path, registry):
        service = make_service(tmp_path)
        ctx = RpcContext(emit_notification=lambda o: None, jobs=registry)
        with pytest.raises(RpcError, match="unknown video"):
            service.dub_start(
                {"videoId": "ghost", "trackId": "t1", "engine": "fake", "voice": "v"},
                ctx,
            )

    def test_chatterbox_requires_sample_id(self, tmp_path, registry):
        service = make_service(tmp_path, engines={"chatterbox": lambda: RecordingEngine([])})
        ctx = RpcContext(emit_notification=lambda o: None, jobs=registry)
        with pytest.raises(RpcError, match="sampleId"):
            service.dub_start({"videoId": "v1", "trackId": "t1", "engine": "chatterbox"}, ctx)
        with pytest.raises(RpcError, match="unknown sampleId"):
            service.dub_start(
                {
                    "videoId": "v1",
                    "trackId": "t1",
                    "engine": "chatterbox",
                    "sampleId": "ghost",
                },
                ctx,
            )

    def test_voice_required_for_named_voice_engines(self, tmp_path, registry):
        service = make_service(tmp_path)
        ctx = RpcContext(emit_notification=lambda o: None, jobs=registry)
        with pytest.raises(RpcError, match="voice is required"):
            service.dub_start({"videoId": "v1", "trackId": "t1", "engine": "fake"}, ctx)

    def test_full_job_resolves_audio_track_and_wav_path(self, tmp_path, registry, collected):
        audio_tracks = FakeAudioTracks()
        service = make_service(tmp_path, audio_tracks=audio_tracks)
        ctx = RpcContext(emit_notification=lambda o: None, jobs=registry)
        result = service.dub_start({"videoId": "v1", "trackId": "t1", "engine": "fake", "voice": "af_x"}, ctx)
        assert set(result) == {"jobId"}
        registry.join(timeout=10)
        done = [payload for kind, payload in collected if kind == "done"]
        assert len(done) == 1
        job_id, payload = done[0]
        assert job_id == result["jobId"]
        # A2: job.done.result = {audioTrack, path}
        assert set(payload) == {"audioTrack", "path"}
        assert payload["audioTrack"]["kind"] == "dub"
        assert payload["path"].endswith(".wav")
        # the muxed file is the AAC encode, recorded on the audioTrack
        assert audio_tracks.calls[0]["path"].endswith(".m4a")
        assert audio_tracks.calls[0]["lang"] == "en"

    def test_failures_surface_via_job_done_error_payload(self, tmp_path, registry, collected):
        class ExplodingEngine(RecordingEngine):
            def synth(self, cues, voice, lang, out_wav, *, rate=1.0):
                raise d.DubError("synthesis exploded")

        service = make_service(tmp_path, engines={"fake": lambda: ExplodingEngine([])})
        ctx = RpcContext(emit_notification=lambda o: None, jobs=registry)
        result = service.dub_start({"videoId": "v1", "trackId": "t1", "engine": "fake", "voice": "v"}, ctx)
        registry.join(timeout=10)
        done = [payload for kind, payload in collected if kind == "done"]
        assert len(done) == 1
        _, payload = done[0]
        # A3 (frozen): failures surface as {error:{message,type}}
        assert payload["error"]["message"] == "synthesis exploded"
        assert payload["error"]["type"] == "DubError"
        assert result["jobId"]

    def test_no_job_registry_rejected(self, tmp_path):
        service = make_service(tmp_path)
        ctx = RpcContext(emit_notification=lambda o: None, jobs=None)
        with pytest.raises(RpcError, match="no job registry"):
            service.dub_start({"videoId": "v1", "trackId": "t1", "engine": "fake", "voice": "v"}, ctx)

    def test_missing_required_string_param_rejected(self, tmp_path, registry):
        service = make_service(tmp_path)
        ctx = RpcContext(emit_notification=lambda o: None, jobs=registry)
        with pytest.raises(RpcError, match="videoId .str. is required"):
            service.dub_start({"trackId": "t1", "engine": "fake", "voice": "v"}, ctx)

    def test_non_string_target_lang_rejected(self, tmp_path, registry):
        service = make_service(tmp_path)
        ctx = RpcContext(emit_notification=lambda o: None, jobs=registry)
        with pytest.raises(RpcError, match="targetLang must be a string"):
            service.dub_start(
                {"videoId": "v1", "trackId": "t1", "engine": "fake", "voice": "v", "targetLang": 7},
                ctx,
            )

    def test_chatterbox_valid_sample_id_resolves_path(self, tmp_path, registry, collected):
        store = VoiceStore(tmp_path / "voices", duration_probe=lambda p: 1.0)
        sample_src = tmp_path / "ref.wav"
        sample_src.write_bytes(b"RIFF0000WAVEfake")
        sample = store.add(str(sample_src))
        seen_voice: list[str] = []

        class SampleEngine(RecordingEngine):
            def synth(self, cues, voice, lang, out_wav, *, rate=1.0):
                seen_voice.append(voice)
                return write_normalized_wav(out_wav, 2.0)

        service = make_service(
            tmp_path,
            engines={"chatterbox": lambda: SampleEngine([])},
            voice_store=store,
        )
        ctx = RpcContext(emit_notification=lambda o: None, jobs=registry)
        service.dub_start(
            {"videoId": "v1", "trackId": "t1", "engine": "chatterbox", "sampleId": sample["id"]},
            ctx,
        )
        registry.join(timeout=10)
        # the engine received the resolved on-disk sample path (line 291)
        assert seen_voice and seen_voice[0] == sample["path"]

    def test_settings_provider_failure_does_not_break_dub(self, tmp_path, registry, collected):
        def boom():
            raise RuntimeError("settings unavailable")

        service = d.DubService(
            resolver=lambda vid: str(tmp_path / "video.mp4") if vid == "v1" else None,
            load_track=lambda vid, tid: {"id": "t1", "lang": "en", "cues": CUES},
            engines={"fake": lambda: RecordingEngine([])},
            voice_store=VoiceStore(tmp_path / "voices", duration_probe=lambda p: 1.0),
            audio_tracks=FakeAudioTracks(),
            settings_provider=boom,
            run=passthrough_run,
            duration=lambda p: 2.0,
            out_dir=str(tmp_path / "dubs"),
        )
        ctx = RpcContext(emit_notification=lambda o: None, jobs=registry)
        result = service.dub_start({"videoId": "v1", "trackId": "t1", "engine": "fake", "voice": "v"}, ctx)
        registry.join(timeout=10)
        done = [p for k, p in collected if k == "done"]
        assert done and "path" in done[0][1]
        assert result["jobId"]

    def test_media_duration_probe_failure_is_best_effort(self, tmp_path, registry, collected):
        def boom_probe(path):
            raise RuntimeError("no ffprobe")

        service = make_service(tmp_path)
        service._media_duration = boom_probe
        ctx = RpcContext(emit_notification=lambda o: None, jobs=registry)
        service.dub_start({"videoId": "v1", "trackId": "t1", "engine": "fake", "voice": "v"}, ctx)
        registry.join(timeout=10)
        done = [p for k, p in collected if k == "done"]
        # the dub completes despite the media-duration probe raising
        assert done and "path" in done[0][1]

    def test_media_duration_probe_used_when_available(self, tmp_path, registry, collected):
        service = make_service(tmp_path)
        service._media_duration = lambda path: 8.0
        ctx = RpcContext(emit_notification=lambda o: None, jobs=registry)
        service.dub_start({"videoId": "v1", "trackId": "t1", "engine": "fake", "voice": "v"}, ctx)
        registry.join(timeout=10)
        done = [p for k, p in collected if k == "done"]
        assert done and "path" in done[0][1]

    def test_aac_encode_failure_surfaces_error(self, tmp_path, registry, collected):
        def run_wav_ok_aac_fail(argv, **kwargs):
            out = argv[-1]
            if str(out).endswith(".wav"):
                write_normalized_wav(out, 2.0)
                return 0
            return 1  # the AAC encode pass fails

        service = make_service(tmp_path)
        service._run = run_wav_ok_aac_fail
        ctx = RpcContext(emit_notification=lambda o: None, jobs=registry)
        service.dub_start({"videoId": "v1", "trackId": "t1", "engine": "fake", "voice": "v"}, ctx)
        registry.join(timeout=10)
        done = [p for k, p in collected if k == "done"]
        assert done and done[0][1]["error"]["message"].startswith("AAC encode failed")

    def test_offline_mode_blocks_online_engine_before_job(self, tmp_path):
        """Offline mode must refuse a HOSTED/ONLINE engine SYNCHRONOUSLY (typed
        OfflineError) and never spawn a job — so no cue text is sent to Microsoft."""
        from media_studio.features.offline import OfflineError

        class SpyJobs:
            def __init__(self):
                self.started = False

            def start(self, body):
                self.started = True
                return type("J", (), {"id": "job-x"})()

        jobs = SpyJobs()
        service = make_service(tmp_path, engines={"edgetts": lambda: OnlineEngine([])})
        service._settings_provider = lambda: {"offline": True}
        ctx = RpcContext(emit_notification=lambda o: None, jobs=jobs)
        with pytest.raises(OfflineError, match="Offline mode is on"):
            service.dub_start({"videoId": "v1", "trackId": "t1", "engine": "edgetts", "voice": "v"}, ctx)
        assert jobs.started is False  # no job spawned, no egress

    def test_offline_off_allows_online_engine(self, tmp_path, registry, collected):
        """With Offline OFF, the hosted engine is not blocked — the job proceeds."""
        service = make_service(tmp_path, engines={"edgetts": lambda: OnlineEngine([])})
        service._settings_provider = lambda: {"offline": False}
        ctx = RpcContext(emit_notification=lambda o: None, jobs=registry)
        result = service.dub_start({"videoId": "v1", "trackId": "t1", "engine": "edgetts", "voice": "v"}, ctx)
        assert set(result) == {"jobId"}
        registry.join(timeout=10)
        done = [p for k, p in collected if k == "done"]
        assert done and "path" in done[0][1]

    def test_offline_mode_does_not_block_local_engine(self, tmp_path, registry, collected):
        """A LOCAL engine (no ``online`` attr) is NEVER blocked, even Offline ON."""
        service = make_service(tmp_path)  # default engine is the local RecordingEngine
        service._settings_provider = lambda: {"offline": True}
        ctx = RpcContext(emit_notification=lambda o: None, jobs=registry)
        result = service.dub_start({"videoId": "v1", "trackId": "t1", "engine": "fake", "voice": "v"}, ctx)
        assert set(result) == {"jobId"}
        registry.join(timeout=10)
        done = [p for k, p in collected if k == "done"]
        assert done and "path" in done[0][1]

    def test_default_out_dir_uses_config_dir(self, tmp_path, registry, collected, monkeypatch):
        monkeypatch.setattr("media_studio.settings_store.default_config_dir", lambda: tmp_path / "cfg")
        service = d.DubService(
            resolver=lambda vid: str(tmp_path / "video.mp4") if vid == "v1" else None,
            load_track=lambda vid, tid: {"id": "t1", "lang": "en", "cues": CUES},
            engines={"fake": lambda: RecordingEngine([])},
            voice_store=VoiceStore(tmp_path / "voices", duration_probe=lambda p: 1.0),
            audio_tracks=FakeAudioTracks(),
            run=passthrough_run,
            duration=lambda p: 2.0,
            out_dir=None,  # exercise the lazy default_config_dir path
        )
        ctx = RpcContext(emit_notification=lambda o: None, jobs=registry)
        service.dub_start({"videoId": "v1", "trackId": "t1", "engine": "fake", "voice": "v"}, ctx)
        registry.join(timeout=10)
        done = [p for k, p in collected if k == "done"]
        assert done and str(tmp_path / "cfg") in done[0][1]["path"]
