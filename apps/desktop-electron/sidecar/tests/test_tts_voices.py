"""Tests for the voice catalog + sample store (features/tts/voices.py, T2)."""
from __future__ import annotations

from pathlib import Path

import pytest

from media_studio.features.tts import register as tts_register
from media_studio.features.tts import voices as v
from media_studio.features.tts.engine import TtsEngine, TtsError
from media_studio.protocol import RpcContext, RpcError


def ctx() -> RpcContext:
    return RpcContext(emit_notification=lambda obj: None, jobs=None)


@pytest.fixture()
def store(tmp_path):
    return v.VoiceStore(tmp_path / "voices", duration_probe=lambda p: 3.5)


@pytest.fixture()
def sample_file(tmp_path):
    f = tmp_path / "my voice.wav"
    f.write_bytes(b"RIFF0000WAVEfake")
    return f


# --------------------------------------------------------------------------- #
# VoiceStore
# --------------------------------------------------------------------------- #
class TestVoiceStore:
    def test_add_copies_and_persists(self, store, sample_file, tmp_path):
        sample = store.add(str(sample_file))
        # A3 VoiceSample shape (frozen field names)
        assert set(sample) == {"id", "name", "path", "durationSec"}
        assert sample["name"] == "my voice"
        assert sample["durationSec"] == 3.5
        copied = Path(sample["path"])
        assert copied.is_file()
        assert copied.parent == tmp_path / "voices"
        # persists across a NEW store instance (round-trip)
        again = v.VoiceStore(tmp_path / "voices", duration_probe=lambda p: 0.0)
        assert [s["id"] for s in again.list()] == [sample["id"]]
        assert again.get(sample["id"])["path"] == sample["path"]

    def test_add_missing_file_raises(self, store, tmp_path):
        with pytest.raises(TtsError, match="not found"):
            store.add(str(tmp_path / "ghost.wav"))

    def test_add_unsupported_format_raises(self, store, tmp_path):
        bad = tmp_path / "notes.txt"
        bad.write_text("hi", encoding="utf-8")
        with pytest.raises(TtsError, match="unsupported"):
            store.add(str(bad))

    def test_probe_failure_stores_zero(self, tmp_path, sample_file):
        def boom(path):
            raise RuntimeError("no ffprobe")

        store = v.VoiceStore(tmp_path / "voices", duration_probe=boom)
        assert store.add(str(sample_file))["durationSec"] == 0.0

    def test_corrupt_index_starts_empty(self, tmp_path):
        d = tmp_path / "voices"
        d.mkdir()
        (d / "voices.json").write_text("{broken", encoding="utf-8")
        assert v.VoiceStore(d, duration_probe=lambda p: 0.0).list() == []

    def test_get_unknown_returns_none(self, store):
        assert store.get("nope") is None


# --------------------------------------------------------------------------- #
# handlers
# --------------------------------------------------------------------------- #
class StaticEngine(TtsEngine):
    id = "kokoro"
    label = "fake"

    def __init__(self, rows):
        self._rows = rows

    def synth(self, cues, voice, lang, out_wav, *, rate=1.0):
        raise AssertionError("catalog handlers must never synthesize")

    def voices(self):
        return list(self._rows)


class TestHandlers:
    def test_voices_aggregates_engines_and_samples(self, store, sample_file):
        sample = store.add(str(sample_file))
        rows = [{"id": "af_x", "engine": "kokoro", "lang": "en-us", "name": "X"}]
        handler = v.make_voices_handler([StaticEngine(rows)], store)
        result = handler({}, ctx())
        ids = [(row["engine"], row["id"]) for row in result["voices"]]
        assert ("kokoro", "af_x") in ids
        assert ("chatterbox", sample["id"]) in ids
        for row in result["voices"]:
            assert set(row) == {"id", "engine", "lang", "name"}

    def test_sample_add_handler_shape_and_validation(self, store, sample_file):
        handler = v.make_sample_add_handler(store)
        result = handler({"path": str(sample_file)}, ctx())
        assert set(result) == {"sample"}
        assert set(result["sample"]) == {"id", "name", "path", "durationSec"}
        with pytest.raises(RpcError):
            handler({}, ctx())
        with pytest.raises(RpcError):
            handler({"path": "C:/nope.wav"}, ctx())


# --------------------------------------------------------------------------- #
# the package register() (frozen A2 method names)
# --------------------------------------------------------------------------- #
class TestRegister:
    def test_registers_exactly_the_a2_names(self, tmp_path):
        registered = {}

        def fake_reg(name, handler):
            registered[name] = handler

        service = tts_register(
            resolver=lambda vid: None,
            load_track=lambda vid, tid: {},
            audio_tracks=object(),
            voice_store=v.VoiceStore(tmp_path / "voices", duration_probe=lambda p: 0.0),
            register_fn=fake_reg,
        )
        assert set(registered) == {"tts.voices", "tts.sample.add", "tts.dub.start"}
        assert service is not None

    def test_registered_voices_handler_serves_all_three_engines(self, tmp_path):
        registered = {}
        tts_register(
            resolver=lambda vid: None,
            load_track=lambda vid, tid: {},
            audio_tracks=object(),
            voice_store=v.VoiceStore(tmp_path / "voices", duration_probe=lambda p: 0.0),
            register_fn=lambda name, h: registered.__setitem__(name, h),
        )
        result = registered["tts.voices"]({}, ctx())
        engines = {row["engine"] for row in result["voices"]}
        # kokoro + edgetts ship static catalogs; chatterbox rows appear once
        # samples exist (none here).
        assert {"kokoro", "edgetts"} <= engines
