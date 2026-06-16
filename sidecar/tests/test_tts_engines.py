"""Tests for the three A4 TTS engines (kokoro / edgetts / chatterbox, T2).

DONE criteria covered: constructors + argv/url shapes with every heavy seam
mocked, and **NO heavy import at collection** — these tests run in the bare
sidecar env where kokoro-onnx / onnxruntime / edge-tts / torch are absent,
so any non-lazy import would fail loudly here.
"""

from __future__ import annotations

import json
import sys
import wave
from pathlib import Path

import pytest
from media_studio import ffmpeg
from media_studio.assets.manifest import get_asset
from media_studio.features.tts import chatterbox as cb
from media_studio.features.tts import chatterbox_runner as cbr
from media_studio.features.tts import edgetts as et
from media_studio.features.tts import engine as eng
from media_studio.features.tts import kokoro as kk

SETTINGS = {"ffmpegPath": "C:/tools/ffmpeg/ffmpeg.exe"}
CUES = [
    {"index": 1, "start": 0.0, "end": 2.0, "text": "Hello there."},
    {"index": 2, "start": 2.0, "end": 4.0, "text": "General Kenobi."},
]


@pytest.fixture(autouse=True)
def fake_ffmpeg(monkeypatch):
    """Pin binary resolution so tests never depend on a real ffmpeg install."""
    monkeypatch.setattr(ffmpeg, "ffmpeg_path", lambda settings=None: "/bin/ffmpeg")
    monkeypatch.setattr(ffmpeg, "ffprobe_path", lambda settings=None: "/bin/ffprobe")


def test_no_heavy_modules_imported_at_collection():
    """A6 lesson 1 guard: importing the engines must NOT pull native backends."""
    for banned in ("onnxruntime", "kokoro_onnx", "edge_tts", "torch", "aiohttp"):
        assert banned not in sys.modules, f"{banned} leaked into module import"


# --------------------------------------------------------------------------- #
# the ABC
# --------------------------------------------------------------------------- #
class TestEngineAbc:
    def test_cannot_instantiate_abstract(self):
        with pytest.raises(TypeError):
            eng.TtsEngine()  # type: ignore[abstract]

    def test_float_to_int16_clamps_and_packs(self):
        data = eng.float_samples_to_int16_bytes([0.0, 1.0, -1.0, 2.0, -2.0])
        assert len(data) == 10
        import struct

        values = struct.unpack("<5h", data)
        assert values[0] == 0
        assert values[1] == 32767
        assert values[2] == -32767
        assert values[3] == 32767  # clamped
        assert values[4] == -32767  # clamped

    def test_wav_helpers_round_trip(self, tmp_path):
        frames = b"\x01\x00" * 24000
        path = eng.write_pcm_wav(str(tmp_path / "x.wav"), frames)
        assert eng.wav_duration_sec(path) == pytest.approx(1.0)

    def test_wav_duration_unreadable_is_zero(self, tmp_path):
        assert eng.wav_duration_sec(str(tmp_path / "missing.wav")) == 0.0

    def test_base_voices_default_empty(self):
        """The ABC's default voices() returns an empty catalog."""

        class _MinimalEngine(eng.TtsEngine):
            id = "minimal"

            def synth(self, cues, voice, lang, out_wav, *, rate=1.0):  # pragma: no cover - unused
                return out_wav

        assert _MinimalEngine().voices() == []

    def test_cues_text_joins_and_strips(self):
        assert (
            eng.cues_text(
                [
                    {"text": "  Hello there.  "},
                    {"text": "General Kenobi."},
                    {"no_text": "skipped"},
                ]
            )
            == "Hello there. General Kenobi."
        )
        assert eng.cues_text([]) == ""

    def test_float_to_int16_numpy_fast_path(self):
        """A numpy array takes the astype/tobytes fast path (clamped)."""
        np = pytest.importorskip("numpy")
        import struct

        arr = np.asarray([0.0, 1.0, -1.0, 2.0, -2.0], dtype=np.float64)
        data = eng.float_samples_to_int16_bytes(arr)
        values = struct.unpack("<5h", data)
        assert values[0] == 0
        assert values[1] == 32767
        assert values[2] == -32767
        assert values[3] == 32767  # clamped from 2.0
        assert values[4] == -32767  # clamped from -2.0

    def test_float_to_int16_numpy_path_falls_back_on_error(self, monkeypatch):
        """A broken astype fast path falls through to the pure loop."""
        import struct

        class _Weird:
            """Exposes astype (entering the fast path) but breaks numpy ops."""

            def astype(self, *_a, **_k):  # pragma: no cover - presence only
                return self

            def __iter__(self):
                return iter([0.0, 1.0, -1.0])

        # Force the numpy fast path to raise so we exercise the fall-through.
        import numpy as np

        monkeypatch.setattr(np, "asarray", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        data = eng.float_samples_to_int16_bytes(_Weird())
        values = struct.unpack("<3h", data)
        assert values == (0, 32767, -32767)

    def test_wav_duration_zero_framerate_is_zero(self, tmp_path, monkeypatch):
        """A WAV whose framerate reads as <= 0 yields 0.0, not a divide error."""

        class _ZeroRate:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def getframerate(self):
                return 0

            def getnframes(self):  # pragma: no cover - guarded out by rate<=0
                return 10

        monkeypatch.setattr(eng.wave, "open", lambda *a, **k: _ZeroRate())
        assert eng.wav_duration_sec(str(tmp_path / "z.wav")) == 0.0


# --------------------------------------------------------------------------- #
# kokoro (default local — onnx weights as PINNED U4 assets)
# --------------------------------------------------------------------------- #
class FakeKokoro:
    def __init__(self):
        self.calls = []

    def create(self, text, voice=None, speed=1.0, lang=None):
        self.calls.append({"text": text, "voice": voice, "speed": speed, "lang": lang})
        return [0.0, 0.5, -0.5, 0.25] * 100, 24000


class TestKokoro:
    def test_assets_registered_pinned(self):
        model = get_asset(kk.KOKORO_MODEL_ASSET)
        voices = get_asset(kk.KOKORO_VOICES_ASSET)
        assert model is not None and voices is not None
        assert model.kind == "model" and voices.kind == "model"
        # PINNED to an immutable release tag (A6 lesson 5)
        assert "model-files-v1.0" in (model.url or "")
        assert "model-files-v1.0" in (voices.url or "")
        assert model.dest == kk.KOKORO_MODEL_DEST

    def test_constructor_resolves_default_paths(self, tmp_path):
        engine = kk.KokoroEngine(assets_root=str(tmp_path))
        assert engine.model_path == str(tmp_path / kk.KOKORO_MODEL_DEST)
        assert engine.voices_path == str(tmp_path / kk.KOKORO_VOICES_DEST)
        assert engine.id == "kokoro" and engine.online is False

    def test_voices_catalog_shape(self):
        for voice in kk.KokoroEngine(assets_root="X").voices():
            assert set(voice) == {"id", "engine", "lang", "name"}
            assert voice["engine"] == "kokoro"

    def test_missing_weights_raise_with_asset_hint(self, tmp_path):
        engine = kk.KokoroEngine(assets_root=str(tmp_path), factory=lambda m, v: FakeKokoro())
        with pytest.raises(eng.TtsError, match=kk.KOKORO_MODEL_ASSET):
            engine.synth(CUES, "af_sarah", "en-us", str(tmp_path / "out.wav"))

    def test_synth_via_fake_factory(self, tmp_path):
        (tmp_path / "models").mkdir()
        (tmp_path / kk.KOKORO_MODEL_DEST).write_bytes(b"onnx")
        (tmp_path / kk.KOKORO_VOICES_DEST).write_bytes(b"voices")
        fake = FakeKokoro()
        built = []

        def factory(model_path, voices_path):
            built.append((model_path, voices_path))
            return fake

        engine = kk.KokoroEngine(assets_root=str(tmp_path), factory=factory)
        out = engine.synth(CUES, "af_sarah", "en-us", str(tmp_path / "o.wav"), rate=1.2)
        assert built == [(engine.model_path, engine.voices_path)]
        assert [c["text"] for c in fake.calls] == ["Hello there.", "General Kenobi."]
        assert all(c["voice"] == "af_sarah" for c in fake.calls)
        assert all(c["speed"] == pytest.approx(1.2) for c in fake.calls)
        assert all(c["lang"] == "en-us" for c in fake.calls)
        with wave.open(out, "rb") as wf:
            assert wf.getframerate() == 24000
            assert wf.getnframes() == 800  # 2 cues x 400 samples

    def test_synth_validation(self, tmp_path):
        engine = kk.KokoroEngine(assets_root=str(tmp_path), factory=lambda m, v: FakeKokoro())
        with pytest.raises(eng.TtsError, match="no cues"):
            engine.synth([], "af_sarah", "en-us", str(tmp_path / "o.wav"))
        with pytest.raises(eng.TtsError, match="voice"):
            engine.synth(CUES, "", "en-us", str(tmp_path / "o.wav"))

    def _ready_engine(self, tmp_path, fake):
        (tmp_path / kk.KOKORO_MODEL_DEST).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / kk.KOKORO_MODEL_DEST).write_bytes(b"onnx")
        (tmp_path / kk.KOKORO_VOICES_DEST).write_bytes(b"voices")
        return kk.KokoroEngine(assets_root=str(tmp_path), factory=lambda m, v: fake)

    def test_session_is_cached_across_synths(self, tmp_path):
        fake = FakeKokoro()
        builds = []
        engine = self._ready_engine(tmp_path, fake)
        engine._factory = lambda m, v: builds.append((m, v)) or fake
        engine.synth(CUES, "af_sarah", "en-us", str(tmp_path / "a.wav"))
        engine.synth(CUES, "af_sarah", "en-us", str(tmp_path / "b.wav"))
        assert len(builds) == 1  # session built once, reused on the second call

    def test_factory_load_failure_is_typed(self, tmp_path):
        def boom(model_path, voices_path):
            raise RuntimeError("onnx load exploded")

        engine = self._ready_engine(tmp_path, FakeKokoro())
        engine._factory = boom
        with pytest.raises(eng.TtsError, match="failed to load kokoro-onnx"):
            engine.synth(CUES, "af_sarah", "en-us", str(tmp_path / "o.wav"))

    def test_empty_cue_text_is_skipped(self, tmp_path):
        fake = FakeKokoro()
        engine = self._ready_engine(tmp_path, fake)
        cues = [{"text": "  "}, {"text": "Real line."}, {"text": ""}]
        engine.synth(cues, "af_sarah", "en-us", str(tmp_path / "o.wav"))
        # only the one non-empty cue reached the model
        assert [c["text"] for c in fake.calls] == ["Real line."]

    def test_all_cue_text_empty_raises(self, tmp_path):
        engine = self._ready_engine(tmp_path, FakeKokoro())
        with pytest.raises(eng.TtsError, match="no speakable text"):
            engine.synth([{"text": "   "}], "af_sarah", "en-us", str(tmp_path / "o.wav"))

    def test_model_create_failure_is_typed(self, tmp_path):
        class BoomKokoro:
            def create(self, *a, **k):
                raise RuntimeError("inference failed")

        engine = self._ready_engine(tmp_path, BoomKokoro())
        with pytest.raises(eng.TtsError, match="kokoro synthesis failed"):
            engine.synth(CUES, "af_sarah", "en-us", str(tmp_path / "o.wav"))


# --------------------------------------------------------------------------- #
# edgetts (hosted — ONLINE label; mp3 -> wav argv)
# --------------------------------------------------------------------------- #
class FakeCommunicate:
    def __init__(self, record):
        self._record = record

    async def save(self, path):
        Path(path).write_bytes(b"ID3 fake mp3")
        self._record["saved"] = path


class TestEdgeTts:
    def test_engine_is_labeled_online(self):
        engine = et.EdgeTtsEngine()
        assert engine.online is True
        assert "ONLINE" in engine.label

    def test_rate_to_percent_shapes(self):
        assert et.rate_to_percent(1.0) == "+0%"
        assert et.rate_to_percent(1.15) == "+15%"
        assert et.rate_to_percent(0.9) == "-10%"
        assert et.rate_to_percent(5.0) == "+50%"  # clamped
        assert et.rate_to_percent(0.1) == "-50%"  # clamped
        assert et.rate_to_percent("garbage") == "+0%"  # type: ignore[arg-type]

    def test_mp3_to_wav_argv_shape(self):
        argv = et.build_mp3_to_wav_argv("C:/t mp/take.mp3", "C:/t mp/out.wav", SETTINGS)
        assert isinstance(argv, list)
        assert argv[argv.index("-i") + 1] == "C:/t mp/take.mp3"
        assert argv[argv.index("-c:a") + 1] == "pcm_s16le"
        assert argv[-1] == "C:/t mp/out.wav"

    def test_voices_catalog_shape(self):
        voices = et.EdgeTtsEngine().voices()
        assert voices, "edgetts must ship a built-in catalog"
        for voice in voices:
            assert set(voice) == {"id", "engine", "lang", "name"}
            assert voice["engine"] == "edgetts"

    def test_synth_uses_factory_and_ffmpeg_seam(self, tmp_path):
        record = {}
        argvs = []

        def factory(text, voice, rate_str):
            record["args"] = (text, voice, rate_str)
            return FakeCommunicate(record)

        def fake_run(argv, **kwargs):
            argvs.append(list(argv))
            Path(argv[-1]).write_bytes(b"RIFFwav")
            return 0

        engine = et.EdgeTtsEngine(communicate_factory=factory, run=fake_run, settings_provider=lambda: SETTINGS)
        out = engine.synth(CUES, "en-US-AriaNeural", "en-US", str(tmp_path / "o.wav"), rate=1.1)
        assert record["args"] == (
            "Hello there. General Kenobi.",
            "en-US-AriaNeural",
            "+10%",
        )
        assert record["saved"].endswith("take.mp3")
        assert len(argvs) == 1 and argvs[0][-1] == str(tmp_path / "o.wav")
        assert out == str(tmp_path / "o.wav")

    def test_synth_surfaces_ffmpeg_failure(self, tmp_path):
        engine = et.EdgeTtsEngine(
            communicate_factory=lambda t, v, r: FakeCommunicate({}),
            run=lambda argv, **kw: 1,
        )
        with pytest.raises(eng.TtsError, match="decode failed"):
            engine.synth(CUES, "en-US-AriaNeural", "en-US", str(tmp_path / "o.wav"))

    def test_synth_validation(self, tmp_path):
        engine = et.EdgeTtsEngine(communicate_factory=lambda t, v, r: FakeCommunicate({}))
        with pytest.raises(eng.TtsError, match="no cues"):
            engine.synth([], "v", "en", str(tmp_path / "o.wav"))
        with pytest.raises(eng.TtsError, match="voice"):
            engine.synth(CUES, "", "en", str(tmp_path / "o.wav"))

    def test_no_speakable_text_raises(self, tmp_path):
        engine = et.EdgeTtsEngine(communicate_factory=lambda t, v, r: FakeCommunicate({}))
        with pytest.raises(eng.TtsError, match="no speakable text"):
            engine.synth([{"text": "   "}], "v", "en", str(tmp_path / "o.wav"))

    def test_network_failure_is_wrapped_as_tts_error(self, tmp_path):
        class BoomCommunicate:
            async def save(self, path):
                raise RuntimeError("service 503")

        engine = et.EdgeTtsEngine(communicate_factory=lambda t, v, r: BoomCommunicate())
        with pytest.raises(eng.TtsError, match="edge-tts synthesis failed"):
            engine.synth(CUES, "v", "en", str(tmp_path / "o.wav"))

    def test_inner_tts_error_propagates_unwrapped(self, tmp_path):
        def factory(t, v, r):
            raise eng.TtsError("already typed")

        engine = et.EdgeTtsEngine(communicate_factory=factory)
        with pytest.raises(eng.TtsError, match="already typed"):
            engine.synth(CUES, "v", "en", str(tmp_path / "o.wav"))

    def test_no_audio_produced_raises(self, tmp_path):
        class SilentCommunicate:
            async def save(self, path):
                return None  # writes nothing — mp3 file never appears

        engine = et.EdgeTtsEngine(communicate_factory=lambda t, v, r: SilentCommunicate())
        with pytest.raises(eng.TtsError, match="produced no audio"):
            engine.synth(CUES, "v", "en", str(tmp_path / "o.wav"))

    def test_settings_provider_failure_is_swallowed(self, tmp_path):
        argvs = []

        def fake_run(argv, **kw):
            argvs.append(list(argv))
            Path(argv[-1]).write_bytes(b"RIFFwav")
            return 0

        def boom_settings():
            raise RuntimeError("settings unavailable")

        engine = et.EdgeTtsEngine(
            communicate_factory=lambda t, v, r: FakeCommunicate({}),
            run=fake_run,
            settings_provider=boom_settings,
        )
        out = engine.synth(CUES, "v", "en", str(tmp_path / "o.wav"))
        assert out == str(tmp_path / "o.wav")
        assert argvs  # the ffmpeg pass still ran (settings failure ignored)

    def test_settings_provider_none_result_is_empty(self, tmp_path):
        engine = et.EdgeTtsEngine(settings_provider=lambda: None)
        assert engine._settings() == {}


# --------------------------------------------------------------------------- #
# chatterbox (voice clone — subprocess into the ISOLATED env)
# --------------------------------------------------------------------------- #
class TestChatterbox:
    def test_env_asset_registered_with_pinned_torch_cuda12(self):
        entry = get_asset(cb.CHATTERBOX_ENV_ASSET)
        assert entry is not None
        assert entry.kind == "env" and entry.installer == "env"
        assert entry.dest == cb.CHATTERBOX_ENV_DEST
        # A6 lesson 5: every requirement is PINNED
        assert all("==" in req for req in entry.requirements)
        torch_pins = [r for r in entry.requirements if r.startswith("torch==")]
        assert torch_pins and "+cu124" in torch_pins[0]
        assert any(r.startswith("chatterbox-tts==") for r in entry.requirements)

    def test_synth_argv_shape(self):
        argv = cb.build_synth_argv("C:/py dir/python.exe", "C:/jobs/job.json")
        assert argv == [
            "C:/py dir/python.exe",
            "-m",
            "chatterbox_runner",
            "C:/jobs/job.json",
        ]

    def test_runner_env_points_at_isolated_env_first(self):
        import os

        env = cb.runner_extra_env("D:/envs/chatterbox")
        paths = env["PYTHONPATH"].split(os.pathsep)
        assert paths[0] == "D:/envs/chatterbox"
        assert paths[1] == cb.runner_dir()

    def test_default_env_dir_uses_config_dir(self, monkeypatch):
        from pathlib import Path

        monkeypatch.setattr(cb, "default_config_dir", lambda: Path("C:/cfg"))
        assert cb.default_env_dir() == str(Path("C:/cfg") / cb.CHATTERBOX_ENV_DEST)
        assert cb.default_env_dir("D:/root") == str(Path("D:/root") / cb.CHATTERBOX_ENV_DEST)

    def test_engine_has_no_static_voice_catalog(self):
        # Voice-clone: catalog is the user's stored samples, surfaced elsewhere.
        assert cb.ChatterboxEngine(env_dir="X").voices() == []

    def test_job_payload_shape(self):
        payload = cb.build_job_payload(CUES, "C:/voices/s.wav", "en", "C:/o.wav", 1.1)
        assert payload["samplePath"] == "C:/voices/s.wav"
        assert payload["outWav"] == "C:/o.wav"
        assert payload["rate"] == pytest.approx(1.1)
        assert payload["cues"][0] == {"start": 0.0, "end": 2.0, "text": "Hello there."}

    def test_synth_runs_runner_and_returns_wav(self, tmp_path):
        env_dir = tmp_path / "envs" / "chatterbox"
        env_dir.mkdir(parents=True)
        sample = tmp_path / "sample.wav"
        sample.write_bytes(b"RIFF")
        out_wav = tmp_path / "out.wav"
        seen = {}

        def fake_run_cmd(argv, extra_env=None):
            seen["argv"] = list(argv)
            seen["env"] = dict(extra_env or {})
            job = json.loads(Path(argv[-1]).read_text(encoding="utf-8"))
            seen["job"] = job
            Path(job["outWav"]).write_bytes(b"RIFFfake")
            return 0, "ok"

        engine = cb.ChatterboxEngine(env_dir=str(env_dir), python_exe="C:/py/python.exe", run_cmd=fake_run_cmd)
        out = engine.synth(CUES, str(sample), "en", str(out_wav), rate=0.95)
        assert out == str(out_wav)
        assert seen["argv"][:3] == ["C:/py/python.exe", "-m", "chatterbox_runner"]
        assert str(env_dir) in seen["env"]["PYTHONPATH"]
        assert seen["job"]["samplePath"] == str(sample)
        assert seen["job"]["rate"] == pytest.approx(0.95)

    def test_failures_surface_with_output_tail(self, tmp_path):
        env_dir = tmp_path / "env"
        env_dir.mkdir()
        sample = tmp_path / "s.wav"
        sample.write_bytes(b"RIFF")
        engine = cb.ChatterboxEngine(
            env_dir=str(env_dir),
            run_cmd=lambda argv, extra_env=None: (1, "boom: CUDA out of memory"),
        )
        with pytest.raises(eng.TtsError, match="CUDA out of memory"):
            engine.synth(CUES, str(sample), "en", str(tmp_path / "o.wav"))

    def test_missing_env_raises_with_asset_hint(self, tmp_path):
        sample = tmp_path / "s.wav"
        sample.write_bytes(b"RIFF")
        engine = cb.ChatterboxEngine(env_dir=str(tmp_path / "nope"), run_cmd=lambda a, e=None: (0, ""))
        with pytest.raises(eng.TtsError, match=cb.CHATTERBOX_ENV_ASSET):
            engine.synth(CUES, str(sample), "en", str(tmp_path / "o.wav"))

    def test_missing_sample_raises(self, tmp_path):
        engine = cb.ChatterboxEngine(env_dir=str(tmp_path))
        with pytest.raises(eng.TtsError, match="reference sample"):
            engine.synth(CUES, str(tmp_path / "ghost.wav"), "en", str(tmp_path / "o.wav"))

    def test_no_cues_raises(self, tmp_path):
        engine = cb.ChatterboxEngine(env_dir=str(tmp_path))
        with pytest.raises(eng.TtsError, match="no cues"):
            engine.synth([], str(tmp_path / "s.wav"), "en", str(tmp_path / "o.wav"))

    def test_runner_exited_zero_without_wav_raises(self, tmp_path):
        env_dir = tmp_path / "env"
        env_dir.mkdir()
        sample = tmp_path / "s.wav"
        sample.write_bytes(b"RIFF")
        engine = cb.ChatterboxEngine(env_dir=str(env_dir), run_cmd=lambda a, e=None: (0, "silent"))
        with pytest.raises(eng.TtsError, match="no wav"):
            engine.synth(CUES, str(sample), "en", str(tmp_path / "o.wav"))


# --------------------------------------------------------------------------- #
# chatterbox_runner — import-light + pure job parsing
# --------------------------------------------------------------------------- #
class TestChatterboxRunner:
    def test_module_import_is_light(self):
        assert "torch" not in sys.modules
        assert "chatterbox" not in sys.modules

    def test_parse_job_valid(self):
        job = cbr.parse_job(cb.build_job_payload(CUES, "C:/s.wav", "en", "C:/o.wav", 1.0))
        assert job["texts"] == ["Hello there.", "General Kenobi."]
        assert job["samplePath"] == "C:/s.wav"
        assert job["outWav"] == "C:/o.wav"
        assert job["rate"] == 1.0

    @pytest.mark.parametrize(
        "raw",
        [
            "not a dict",
            {},
            {"cues": []},
            {"cues": [{"text": "x"}]},
            {"cues": [{"text": "x"}], "samplePath": "s"},
        ],
    )
    def test_parse_job_invalid(self, raw):
        with pytest.raises(ValueError):
            cbr.parse_job(raw)

    def test_main_rejects_bad_usage_and_bad_file(self, tmp_path):
        assert cbr.main([]) == 2
        bad = tmp_path / "bad.json"
        bad.write_text("{nope", encoding="utf-8")
        assert cbr.main([str(bad)]) == 2

    def test_parse_job_rejects_non_dict_cue_entry(self):
        with pytest.raises(ValueError, match="entries must be objects"):
            cbr.parse_job(
                {
                    "cues": ["not a dict"],
                    "samplePath": "s",
                    "outWav": "o",
                }
            )

    def test_parse_job_coerces_bad_rate_to_one(self):
        job = cbr.parse_job(
            {
                "cues": [{"text": "x"}],
                "samplePath": "s",
                "outWav": "o",
                "rate": "not-a-number",
            }
        )
        assert job["rate"] == 1.0

    def test_main_success_path_runs_synthesize_seam(self, tmp_path, monkeypatch):
        """A valid job reaches _synthesize; with no torch env it exits 1."""
        job_file = tmp_path / "job.json"
        payload = cb.build_job_payload(CUES, "C:/s.wav", "en", str(tmp_path / "o.wav"), 1.0)
        job_file.write_text(json.dumps(payload), encoding="utf-8")
        calls = []

        def fake_synth(job):
            calls.append(job)

        monkeypatch.setattr(cbr, "_synthesize", fake_synth)
        assert cbr.main([str(job_file)]) == 0
        assert calls and calls[0]["outWav"] == str(tmp_path / "o.wav")

    def test_main_synthesize_failure_returns_one(self, tmp_path, monkeypatch):
        job_file = tmp_path / "job.json"
        payload = cb.build_job_payload(CUES, "C:/s.wav", "en", str(tmp_path / "o.wav"), 1.0)
        job_file.write_text(json.dumps(payload), encoding="utf-8")

        def boom(job):
            raise RuntimeError("torch missing in this env")

        monkeypatch.setattr(cbr, "_synthesize", boom)
        assert cbr.main([str(job_file)]) == 1
