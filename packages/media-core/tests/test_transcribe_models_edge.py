"""Edge-case coverage for transcription Word / TranscriptionResult models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from media_core.transcribe.models import TranscriptionResult, Word


def test_word_rejects_non_positive_duration():
    # end == start triggers the after-validator (model_validator) error path.
    with pytest.raises(ValidationError) as exc:
        Word(text="zero", start=1.0, end=1.0)
    assert "non-positive duration" in str(exc.value)


def test_word_duration_property():
    word = Word(text="hi", start=0.5, end=1.25)
    assert word.duration == pytest.approx(0.75)


def test_transcription_result_empty_words_duration_is_zero():
    result = TranscriptionResult(words=[])
    # Empty-words branch in the monotonic validator returns early.
    assert result.words == []
    assert result.duration == 0.0


def test_transcription_result_duration_spans_first_to_last():
    w1 = Word(text="a", start=0.0, end=0.4)
    w2 = Word(text="b", start=1.0, end=2.0)
    result = TranscriptionResult.from_iterable([w2, w1])
    # Words are sorted; duration spans first.start -> last.end.
    assert [w.text for w in result.words] == ["a", "b"]
    assert result.duration == pytest.approx(2.0)
