from media_core.transcribe import TranscriptionResult, Word
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
    try:
        TranscriptionResult(words=[w1, w2])
    except ValidationError as exc:
        assert "overlap" in str(exc).lower()
    else:
        raise AssertionError("Expected ValidationError for overlapping words")
