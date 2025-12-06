import pytest

from media_core.transcribe import TranscriptionResult, Word
from media_core.transcribe.backends.openai_whisper import normalize_verbose_json
from media_core.transcribe.backends.faster_whisper import normalize_faster_whisper
from media_core.transcribe.backends.whisper_cpp import normalize_whisper_cpp
from pydantic import ValidationError


def test_words_are_sorted_and_non_overlapping():
    w1 = Word(text="hello", start=0.0, end=0.5)
    w2 = Word(text="world", start=0.6, end=1.0)
    result = TranscriptionResult.from_iterable([w2, w1])
    assert [w.text for w in result.words] == ["hello", "world"]
    assert result.duration == 1.0


def test_overlapping_words_raise():
    w1 = Word(text="first", start=0.0, end=1.0)
    w2 = Word(text="second", start=0.5, end=1.5)
    with pytest.raises(ValidationError):
        TranscriptionResult(words=[w1, w2])


def test_normalize_verbose_json_maps_words_and_text():
    verbose = {
        "text": "hello world",
        "segments": [
            {
                "id": 0,
                "words": [
                    {"word": "hello", "start": 0.0, "end": 0.5, "probability": 0.9},
                    {"word": "world", "start": 0.5, "end": 1.0, "probability": 0.8},
                ],
            }
        ],
    }
    result = normalize_verbose_json(verbose, model="whisper-1", language="en")
    assert result.text == "hello world"
    assert [w.text for w in result.words] == ["hello", "world"]
    assert result.model == "whisper-1"
    assert result.language == "en"


def test_normalize_faster_whisper_accepts_segment_like_objects():
    class DummyWord:
        def __init__(self, word, start, end, probability):
            self.word = word
            self.start = start
            self.end = end
            self.probability = probability

    class DummySeg:
        def __init__(self, text, words):
            self.text = text
            self.words = words

    segs = [
        DummySeg(
            text="hello world",
            words=[DummyWord("hello", 0.0, 0.5, 0.9), DummyWord("world", 0.5, 1.0, 0.8)],
        )
    ]
    result = normalize_faster_whisper(segs, model="faster-whisper-large-v3", language="en")
    assert result.text == "hello world"
    assert [w.text for w in result.words] == ["hello", "world"]
    assert result.model == "faster-whisper-large-v3"
    assert result.language == "en"


def test_normalize_whisper_cpp_fallback_on_segments():
    segments = [
        {
            "text": "hello",
            "t_start": 0.0,
            "t_end": 0.5,
            "tokens": [
                {"text": "hello", "t_start": 0.0, "t_end": 0.5},
            ],
        },
        {
            "text": "world",
            "t_start": 0.6,
            "t_end": 1.0,
            "tokens": [
                {"text": "world", "t_start": 0.6, "t_end": 1.0},
            ],
        },
    ]
    result = normalize_whisper_cpp(segments, model="ggml-base.en", language="en")
    assert [w.text for w in result.words] == ["hello", "world"]
    assert result.model == "ggml-base.en"
    assert result.language == "en"
