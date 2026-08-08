"""Vocabulary plumbing through media_studio.features.transcribe.

Covers the wiring the asr-vocabulary lane adds on top of the pure
``asr_vocabulary`` module (tested separately in ``test_asr_vocabulary.py``):

  * ``transcribe_file`` forwards ``initial_prompt`` / ``hotwords`` to the
    faster-whisper model ONLY when they are given, so the zero-vocabulary call
    shape is byte-identical to before this lane.
  * ``transcribe_with_engine`` derives both biasing strings from
    ``settings['asrVocabulary']`` for the whisper path, passes NOTHING extra to
    Parakeet (its adapter has no biasing hook), and post-corrects the transcript
    of EITHER engine — including the whisper fallback after a Parakeet degrade.

No model is ever loaded: the loader/runner seams are faked.
"""

from __future__ import annotations

from typing import Any

import pytest
from media_studio.features import transcribe

VOCAB = [{"term": "Reframe", "soundsLike": ["re frame"]}]


class _Word:
    def __init__(self, word: str, start: float, end: float):
        self.word = word
        self.start = start
        self.end = end


class _Segment:
    def __init__(self, start: float, end: float, text: str, words: list[_Word]):
        self.start = start
        self.end = end
        self.text = text
        self.words = words


class _Info:
    def __init__(self, language: str = "en", duration: float = 4.0):
        self.language = language
        self.duration = duration


class FakeModel:
    """A stand-in WhisperModel recording every transcribe kwarg it receives."""

    def __init__(self, text: str = " re frame is good"):
        pieces = text.split()
        self.calls: list[dict[str, Any]] = []
        words = [_Word(f" {p}", float(i), float(i + 1)) for i, p in enumerate(pieces)]
        self._segments = [_Segment(0.0, float(len(pieces)), text, words)]

    def transcribe(self, audio: str, **kwargs: Any):
        self.calls.append({"audio": audio, **kwargs})
        return (s for s in self._segments), _Info()


class FakeLoader:
    def __init__(self, model: FakeModel):
        self._model = model
        self.loads: list[tuple[str, str, str]] = []

    def load(self, model: str, device: str, compute_type: str):
        self.loads.append((model, device, compute_type))
        return self._model


def _cpu_settings(**extra: Any) -> dict[str, Any]:
    """Force the CPU target so no CUDA probe runs during the test."""
    return {transcribe.TRANSCRIBE_DEVICE_KEY: "cpu", **extra}


# --------------------------------------------------------------------------- #
# transcribe_file — the forwarding seam
# --------------------------------------------------------------------------- #
def test_transcribe_file_omits_biasing_kwargs_by_default():
    model = FakeModel()
    transcribe.transcribe_file("/v.mp4", loader=FakeLoader(model))
    assert "initial_prompt" not in model.calls[0]
    assert "hotwords" not in model.calls[0]


def test_transcribe_file_forwards_initial_prompt_when_given():
    model = FakeModel()
    transcribe.transcribe_file("/v.mp4", loader=FakeLoader(model), initial_prompt="Glossary: Reframe.")
    assert model.calls[0]["initial_prompt"] == "Glossary: Reframe."
    assert "hotwords" not in model.calls[0]


def test_transcribe_file_forwards_hotwords_when_given():
    model = FakeModel()
    transcribe.transcribe_file("/v.mp4", loader=FakeLoader(model), hotwords="Reframe")
    assert model.calls[0]["hotwords"] == "Reframe"
    assert "initial_prompt" not in model.calls[0]


def test_transcribe_file_does_not_post_correct_on_its_own():
    # transcribe_file stays a PURE ASR seam: biasing in, raw transcript out.
    # The rule pass belongs to the settings-aware transcribe_with_engine.
    model = FakeModel()
    out = transcribe.transcribe_file("/v.mp4", loader=FakeLoader(model), hotwords="Reframe")
    assert out["segments"][0]["text"] == " re frame is good"


# --------------------------------------------------------------------------- #
# transcribe_with_engine — whisper path
# --------------------------------------------------------------------------- #
def test_with_engine_sends_both_biasing_strings_from_settings():
    model = FakeModel()
    transcribe.transcribe_with_engine(
        "/v.mp4", loader=FakeLoader(model), settings=_cpu_settings(asrVocabulary=VOCAB)
    )
    assert model.calls[0]["initial_prompt"] == "Glossary: Reframe."
    assert model.calls[0]["hotwords"] == "Reframe"


def test_with_engine_sends_no_biasing_when_no_vocabulary_is_configured():
    model = FakeModel()
    transcribe.transcribe_with_engine("/v.mp4", loader=FakeLoader(model), settings=_cpu_settings())
    assert "initial_prompt" not in model.calls[0]
    assert "hotwords" not in model.calls[0]


def test_with_engine_post_corrects_the_whisper_transcript():
    model = FakeModel()
    out = transcribe.transcribe_with_engine(
        "/v.mp4", loader=FakeLoader(model), settings=_cpu_settings(asrVocabulary=VOCAB)
    )
    assert out["segments"][0]["text"] == " Reframe is good"
    assert [w["text"] for w in out["segments"][0]["words"]] == [" Reframe", " is", " good"]


def test_with_engine_leaves_the_transcript_alone_without_a_vocabulary():
    model = FakeModel()
    out = transcribe.transcribe_with_engine("/v.mp4", loader=FakeLoader(model), settings=_cpu_settings())
    assert out["segments"][0]["text"] == " re frame is good"


# --------------------------------------------------------------------------- #
# transcribe_with_engine — parakeet path
# --------------------------------------------------------------------------- #
def _parakeet_transcript() -> dict[str, Any]:
    return {
        "language": "en",
        "segments": [
            {
                "start": 0.0,
                "end": 3.0,
                "text": " re frame is good",
                "words": [
                    {"text": " re", "start": 0.0, "end": 0.5},
                    {"text": " frame", "start": 0.5, "end": 1.0},
                    {"text": " is", "start": 1.0, "end": 2.0},
                    {"text": " good", "start": 2.0, "end": 3.0},
                ],
            }
        ],
        "durationSec": 3.0,
    }


def test_with_engine_post_corrects_the_parakeet_transcript():
    calls: list[dict[str, Any]] = []

    def runner(audio_path: str, **kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return _parakeet_transcript()

    out = transcribe.transcribe_with_engine(
        "/v.mp4",
        loader=FakeLoader(FakeModel()),
        settings=_cpu_settings(asrEngine="parakeet", asrVocabulary=VOCAB),
        parakeet_runner=runner,
    )
    assert out["segments"][0]["text"] == " Reframe is good"
    assert [w["text"] for w in out["segments"][0]["words"]] == [" Reframe", " is", " good"]


def test_with_engine_sends_no_biasing_kwargs_to_parakeet():
    # Its adapter (parakeet_asr_backend._RealParakeetModel.transcribe) forwards
    # only the audio path + timestamps, so there is nothing to bias with.
    calls: list[dict[str, Any]] = []

    def runner(audio_path: str, **kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return _parakeet_transcript()

    transcribe.transcribe_with_engine(
        "/v.mp4",
        loader=FakeLoader(FakeModel()),
        settings=_cpu_settings(asrEngine="parakeet", asrVocabulary=VOCAB),
        parakeet_runner=runner,
    )
    assert "initial_prompt" not in calls[0]
    assert "hotwords" not in calls[0]


def test_with_engine_corrects_the_whisper_fallback_after_a_parakeet_degrade():
    model = FakeModel()

    def degraded(audio_path: str, **kwargs: Any) -> dict[str, Any]:
        return {"language": "", "segments": [], "durationSec": 0.0}

    out = transcribe.transcribe_with_engine(
        "/v.mp4",
        loader=FakeLoader(model),
        settings=_cpu_settings(asrEngine="parakeet", asrVocabulary=VOCAB),
        parakeet_runner=degraded,
    )
    assert out["segments"][0]["text"] == " Reframe is good"
    assert model.calls[0]["hotwords"] == "Reframe"


def test_with_engine_returns_a_cancelled_parakeet_result_untouched():
    empty = {"language": "en", "segments": [], "durationSec": 0.0}

    def cancelled(audio_path: str, **kwargs: Any) -> dict[str, Any]:
        return empty

    out = transcribe.transcribe_with_engine(
        "/v.mp4",
        loader=FakeLoader(FakeModel()),
        settings=_cpu_settings(asrEngine="parakeet", asrVocabulary=VOCAB),
        parakeet_runner=cancelled,
        should_cancel=lambda: True,
    )
    # No whisper model is loaded for an already-cancelled job (the multi-GB
    # fallback must not fire), and the empty result is returned as-is.
    assert out is empty


def test_with_engine_tolerates_a_malformed_vocabulary_setting():
    model = FakeModel()
    out = transcribe.transcribe_with_engine(
        "/v.mp4", loader=FakeLoader(model), settings=_cpu_settings(asrVocabulary="not-a-list")
    )
    assert out["segments"][0]["text"] == " re frame is good"
    assert "hotwords" not in model.calls[0]


def test_with_engine_biasing_survives_a_none_settings_object():
    model = FakeModel()
    out = transcribe.transcribe_with_engine("/v.mp4", loader=FakeLoader(model), settings=None)
    assert out["segments"][0]["text"] == " re frame is good"
    assert model.calls[0]["language"] is None


@pytest.mark.parametrize("engine", ["whisper", "parakeet"])
def test_vocabulary_key_is_the_documented_settings_key(engine: str):
    # One spelling, shared by both engines and by the settings surface.
    from media_studio.features import asr_vocabulary

    assert asr_vocabulary.VOCAB_SETTINGS_KEY == "asrVocabulary"
    assert engine in transcribe.ASR_ENGINES
