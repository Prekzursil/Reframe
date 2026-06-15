"""Coverage for transcription backend helpers and entry functions.

Heavy/optional backends (faster-whisper, openai, whispercpp, whisper-timestamped)
are exercised by injecting fake modules into ``sys.modules`` so the real packages
are never required, mirroring the existing diarize backend tests.
"""

from __future__ import annotations

import json
import sys
import types

import pytest

from media_core.transcribe.backends import faster_whisper as fw
from media_core.transcribe.backends import openai_whisper as ow
from media_core.transcribe.backends import whisper_cpp as wc
from media_core.transcribe.backends import whisper_timestamped as wt
from media_core.transcribe.config import TranscriptionConfig


# ---------------------------------------------------------------------------
# faster_whisper
# ---------------------------------------------------------------------------
def test_normalize_model_name_empty_returns_empty():
    assert fw._normalize_model_name("") == ""
    assert fw._normalize_model_name("   ") == ""


def test_ensure_faster_whisper_returns_class(monkeypatch):
    fake_module = types.ModuleType("faster_whisper")
    sentinel = object()
    fake_module.WhisperModel = sentinel
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_module)
    assert fw._ensure_faster_whisper() is sentinel


def test_extract_segment_fields_object_branch():
    class Seg:
        text = "  hi there  "
        words = ["w"]

    text, words = fw._extract_segment_fields(Seg())
    assert text == "hi there"
    assert words == ["w"]


def test_coerce_probability_handles_bad_value():
    assert fw._coerce_probability("not-a-number") is None
    assert fw._coerce_probability(None) is None
    assert fw._coerce_probability("0.5") == pytest.approx(0.5)


def test_parse_word_object_branch_and_malformed():
    class GoodWord:
        word = " hello "
        start = 0.0
        end = 0.5
        probability = 0.9

    parsed = fw._parse_word(GoodWord())
    assert parsed is not None and parsed.text == "hello"

    class BadWord:
        # Missing numeric start/end -> float() raises -> returns None.
        word = "x"
        start = "bad"
        end = "bad"

    assert fw._parse_word(BadWord()) is None


def test_normalize_faster_whisper_skips_empty_and_unparseable():
    segments = [
        {"text": "", "words": None},  # no text, no words
        {"text": "kept", "words": []},  # text but empty words
        {
            "text": "more",
            "words": [
                {"start": "bad", "end": "bad", "word": "drop"},  # unparseable
                {"start": 1.0, "end": 1.5, "word": "good"},
            ],
        },
    ]
    result = fw.normalize_faster_whisper(segments, model="m", language="en")
    assert result.text == "kept more"
    assert [w.text for w in result.words] == ["good"]


def test_transcribe_faster_whisper_happy_path(monkeypatch, tmp_path):
    media = tmp_path / "clip.wav"
    media.write_bytes(b"audio")

    captured = {}

    class FakeModel:
        def __init__(self, name, **kwargs):
            captured["name"] = name
            captured["kwargs"] = kwargs

        def transcribe(self, path, language=None):
            captured["path"] = path
            captured["language"] = language
            seg = {
                "text": "hello world",
                "words": [
                    {"start": 0.0, "end": 0.4, "word": "hello", "probability": 0.9},
                    {"start": 0.5, "end": 0.9, "word": "world", "probability": 0.8},
                ],
            }
            return [seg], {"info": True}

    fake_module = types.ModuleType("faster_whisper")
    fake_module.WhisperModel = FakeModel
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_module)

    config = TranscriptionConfig(model="whisper-large-v3", language="en", device="cpu")
    result = fw.transcribe_faster_whisper(media, config)

    assert captured["name"] == "large-v3"  # alias normalized
    assert captured["kwargs"] == {"device": "cpu"}
    assert result.model == "large-v3"
    assert [w.text for w in result.words] == ["hello", "world"]


def test_transcribe_faster_whisper_without_device(monkeypatch, tmp_path):
    media = tmp_path / "clip.wav"
    media.write_bytes(b"audio")

    captured = {}

    class FakeModel:
        def __init__(self, name, **kwargs):
            captured["kwargs"] = kwargs

        def transcribe(self, _path, language=None):  # noqa: ARG002
            return [], {}

    fake_module = types.ModuleType("faster_whisper")
    fake_module.WhisperModel = FakeModel
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_module)

    # device=None -> the `if config.device` branch is skipped (no device kwarg).
    config = TranscriptionConfig(model="base", language=None, device=None)
    result = fw.transcribe_faster_whisper(media, config)
    assert captured["kwargs"] == {}
    assert result.words == []


# ---------------------------------------------------------------------------
# openai_whisper
# ---------------------------------------------------------------------------
def test_ensure_openai_returns_module(monkeypatch):
    fake_module = types.ModuleType("openai")
    monkeypatch.setitem(sys.modules, "openai", fake_module)
    assert ow._ensure_openai() is fake_module


def test_normalize_verbose_json_skips_malformed_words():
    verbose = {
        "text": "hello",
        "segments": [
            {
                "words": [
                    {"word": "hello", "start": 0.0, "end": 0.5, "probability": "bad"},
                    {"word": "skip", "start": "x", "end": "y"},  # malformed -> skipped
                    {"word": "world", "start": 0.6, "end": 1.0, "probability": None},
                ]
            },
            {"words": None},  # empty words branch
        ],
    }
    result = ow.normalize_verbose_json(verbose, model="whisper-1", language="en")
    assert [w.text for w in result.words] == ["hello", "world"]
    # "bad" probability coerces to None rather than raising.
    assert result.words[0].probability is None


def test_transcribe_openai_offline_mode_refuses(monkeypatch, tmp_path):
    media = tmp_path / "clip.wav"
    media.write_bytes(b"audio")
    monkeypatch.setenv("REFRAME_OFFLINE_MODE", "1")
    config = TranscriptionConfig(model="whisper-1")
    with pytest.raises(RuntimeError, match="REFRAME_OFFLINE_MODE"):
        ow.transcribe_openai_file(media, config)


def test_transcribe_openai_happy_path(monkeypatch, tmp_path):
    media = tmp_path / "clip.wav"
    media.write_bytes(b"audio")
    monkeypatch.delenv("REFRAME_OFFLINE_MODE", raising=False)

    verbose = {
        "text": "hi",
        "segments": [{"words": [{"word": "hi", "start": 0.0, "end": 0.5}]}],
    }

    class FakeTranscriptions:
        @staticmethod
        def create(**kwargs):
            assert kwargs["response_format"] == "verbose_json"
            return verbose

    class FakeAudio:
        transcriptions = FakeTranscriptions()

    class FakeClient:
        audio = FakeAudio()

    fake_openai = types.ModuleType("openai")
    fake_openai.OpenAI = lambda: FakeClient()
    monkeypatch.setitem(sys.modules, "openai", fake_openai)

    config = TranscriptionConfig(model="whisper-1", language="en", temperature=0.0)
    result = ow.transcribe_openai_file(media, config)
    assert result.text == "hi"
    assert [w.text for w in result.words] == ["hi"]


# ---------------------------------------------------------------------------
# whisper_cpp
# ---------------------------------------------------------------------------
def test_ensure_whispercpp_returns_module(monkeypatch):
    fake_module = types.ModuleType("whispercpp")
    monkeypatch.setitem(sys.modules, "whispercpp", fake_module)
    assert wc._ensure_whispercpp() is fake_module


def test_parse_segment_word_dict_and_empty():
    word = wc._parse_segment_word({"t_start": 0.0, "t_end": 0.5, "text": " word "})
    assert word is not None and word.text == "word"

    # Whitespace-only text -> rejected (the `if not text` branch).
    assert wc._parse_segment_word({"t_start": 0.0, "t_end": 0.5, "text": "   "}) is None

    # Missing timing keys -> float(None) raises -> returns None (except branch).
    assert wc._parse_segment_word({"text": "x"}) is None


def test_segment_words_fallback_to_segment_word():
    # Segment with no tokens falls back to a single word from the segment itself.
    seg = {"text": "fallback", "t_start": 0.0, "t_end": 1.0}
    words = wc._segment_words(seg)
    assert [w.text for w in words] == ["fallback"]


def test_join_segment_text_handles_exception():
    class Weird:
        @property
        def text(self):
            raise RuntimeError("explode")

        def get(self, *_a, **_k):
            raise RuntimeError("explode")

    assert wc._join_segment_text([Weird()]) is None


def test_transcribe_whisper_cpp_happy_path(monkeypatch, tmp_path):
    media = tmp_path / "clip.wav"
    media.write_bytes(b"audio")

    class FakeWhisper:
        def __init__(self, name):
            self.name = name

        def transcribe(self, _path):
            return [
                {
                    "text": "hello",
                    "t_start": 0.0,
                    "t_end": 0.5,
                    "tokens": [{"text": "hello", "t_start": 0.0, "t_end": 0.5}],
                }
            ]

    fake_module = types.ModuleType("whispercpp")
    fake_module.Whisper = FakeWhisper
    monkeypatch.setitem(sys.modules, "whispercpp", fake_module)

    config = TranscriptionConfig(model="ggml-base.en", language="en")
    result = wc.transcribe_whisper_cpp(media, config)
    assert [w.text for w in result.words] == ["hello"]
    assert result.model == "ggml-base.en"


# ---------------------------------------------------------------------------
# whisper_timestamped
# ---------------------------------------------------------------------------
def test_wt_coerce_probability():
    assert wt._coerce_probability(None) is None
    assert wt._coerce_probability("bad") is None
    assert wt._coerce_probability("0.5") == pytest.approx(0.5)


def test_wt_parse_word_malformed_returns_none():
    assert wt._parse_word({"start": "x", "end": "y", "word": "z"}) is None
    parsed = wt._parse_word({"start": 0.0, "end": 0.5, "text": "via-text", "score": 0.7})
    assert parsed is not None and parsed.text == "via-text"
    assert parsed.probability == pytest.approx(0.7)


def test_wt_extract_words_skips_unparseable():
    segments = [
        {"words": [{"start": "bad", "end": "bad", "word": "drop"}, {"start": 0.0, "end": 0.4, "word": "keep"}]},
    ]
    words = wt._extract_words(segments)
    assert [w.text for w in words] == ["keep"]


def test_wt_resolve_full_text_non_dict_returns_none():
    assert wt._resolve_full_text([{"text": "x"}], [{"text": "x"}]) is None


def test_wt_resolve_full_text_joins_segments_when_no_top_text():
    response = {"segments": [{"text": "a"}, {"text": "b"}, {"text": ""}]}
    text = wt._resolve_full_text(response, response["segments"])
    assert text == "a b"


def test_transcribe_whisper_timestamped_reads_json_file(tmp_path):
    payload = {
        "text": "hello world",
        "segments": [
            {
                "text": "hello world",
                "words": [
                    {"word": "hello", "start": 0.0, "end": 0.4},
                    {"word": "world", "start": 0.5, "end": 1.0},
                ],
            }
        ],
    }
    json_path = tmp_path / "transcript.json"
    json_path.write_text(json.dumps(payload), encoding="utf-8")

    config = TranscriptionConfig(model="whisperx", language="en")
    result = wt.transcribe_whisper_timestamped(json_path, config)
    assert result.text == "hello world"
    assert [w.text for w in result.words] == ["hello", "world"]


def test_transcribe_whisper_timestamped_stub_fallback(monkeypatch, tmp_path):
    media = tmp_path / "clip.wav"
    media.write_bytes(b"audio")

    # Ensure the optional import path raises so we hit the stub fallback.
    real_import = __import__

    def fake_import(name, *args, **kwargs):
        if name == "whisper_timestamped":
            raise ImportError("not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)

    config = TranscriptionConfig(model="base", language="en")
    result = wt.transcribe_whisper_timestamped(media, config)
    # Stub returns the filename as the single word.
    assert [w.text for w in result.words] == ["clip.wav"]
    assert result.model == "base"
