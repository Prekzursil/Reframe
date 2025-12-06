import pytest

from media_core.transcribe import TranscriptionResult, Word
from media_core.transcribe.backends.openai_whisper import normalize_verbose_json
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
