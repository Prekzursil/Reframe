"""Coverage for diarize_audio dispatch, assignment, and the pyannote backend."""

from __future__ import annotations

import sys
import types

import pytest

from media_core.diarize import (
    DiarizationBackend,
    DiarizationConfig,
    SpeakerSegment,
    _iter_pyannote_tracks,
    assign_speakers_to_lines,
    diarize_audio,
)
from media_core.subtitles.builder import SubtitleLine
from media_core.transcribe.models import Word


# ---------------------------------------------------------------------------
# diarize_audio dispatch + assignment
# ---------------------------------------------------------------------------
def test_diarize_audio_noop_returns_empty():
    config = DiarizationConfig(backend=DiarizationBackend.NOOP)
    assert diarize_audio("anything.wav", config) == []


def test_diarize_audio_unknown_backend_raises(monkeypatch):
    config = DiarizationConfig(backend=DiarizationBackend.NOOP)
    # Bypass enum validation to force the final "unknown backend" guard.
    object.__setattr__(config, "backend", "mystery-backend")
    with pytest.raises(ValueError, match="Unknown diarization backend"):
        diarize_audio("anything.wav", config)


def test_assign_speakers_to_lines_without_segments_copies_lines():
    lines = [
        SubtitleLine(start=0.0, end=1.0, words=[Word(text="hi", start=0.0, end=1.0)], speaker="X"),
    ]
    out = assign_speakers_to_lines(lines, [])
    assert len(out) == 1
    # No segments -> existing speaker labels are preserved on fresh copies.
    assert out[0].speaker == "X"
    assert out[0] is not lines[0]


# ---------------------------------------------------------------------------
# _iter_pyannote_tracks shapes
# ---------------------------------------------------------------------------
def test_iter_pyannote_tracks_nested_attribute_skips_non_callable():
    class Turn:
        start, end = 0.0, 1.0

    class Inner:
        def itertracks(self, *, yield_label=False):  # noqa: ARG002
            yield Turn(), None, "SPEAKER_00"

    class Outer:
        # First nested attr is present but its itertracks is NOT callable -> skipped;
        # the loop continues to a later attr that works.
        speaker_diarization = object()  # no itertracks
        diarization = Inner()

    tracks = list(_iter_pyannote_tracks(Outer()))
    assert tracks[0][2] == "SPEAKER_00"


def test_iter_pyannote_tracks_to_annotation_shape():
    class Turn:
        start, end = 0.0, 1.0

    class Annotation:
        def itertracks(self, *, yield_label=False):  # noqa: ARG002
            yield Turn(), None, "SPEAKER_01"

    class Output:
        def to_annotation(self):
            return Annotation()

    tracks = list(_iter_pyannote_tracks(Output()))
    assert tracks[0][2] == "SPEAKER_01"


def test_iter_pyannote_tracks_unsupported_raises():
    class Weird:
        pass

    with pytest.raises(RuntimeError, match="Unsupported pyannote"):
        _iter_pyannote_tracks(Weird())


def test_iter_pyannote_tracks_to_annotation_without_itertracks_raises():
    # to_annotation() returns an object whose itertracks is not callable -> raise.
    class Output:
        def to_annotation(self):
            return object()  # no callable itertracks

    with pytest.raises(RuntimeError, match="Unsupported pyannote"):
        _iter_pyannote_tracks(Output())


# ---------------------------------------------------------------------------
# pyannote backend error/branch paths
# ---------------------------------------------------------------------------
def test_pyannote_missing_dependency_raises(monkeypatch):
    # Ensure importing pyannote.audio fails.
    real_import = __import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("pyannote"):
            raise ImportError("pyannote not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)
    config = DiarizationConfig(backend=DiarizationBackend.PYANNOTE)
    with pytest.raises(RuntimeError, match="pyannote diarization backend selected"):
        diarize_audio("fake.wav", config)


def _install_fake_pyannote(monkeypatch, Pipeline):
    pyannote = types.ModuleType("pyannote")
    pyannote_audio = types.ModuleType("pyannote.audio")
    pyannote_audio.Pipeline = Pipeline
    monkeypatch.setitem(sys.modules, "pyannote", pyannote)
    monkeypatch.setitem(sys.modules, "pyannote.audio", pyannote_audio)


class _Turn:
    def __init__(self, start, end):
        self.start = start
        self.end = end


class _Diarization:
    def __init__(self, turns):
        self._turns = turns

    def itertracks(self, *, yield_label=False):  # noqa: ARG002
        for start, end, spk in self._turns:
            yield _Turn(start, end), None, spk


def test_pyannote_without_token_uses_plain_from_pretrained(monkeypatch):
    class Pipeline:
        called_with = None

        @classmethod
        def from_pretrained(cls, model, **kwargs):
            cls.called_with = (model, kwargs)
            return cls()

        def __call__(self, _path):
            return _Diarization([(0.0, 1.0, "SPEAKER_00")])

    _install_fake_pyannote(monkeypatch, Pipeline)
    config = DiarizationConfig(backend=DiarizationBackend.PYANNOTE)  # no token
    segments = diarize_audio("fake.wav", config)
    assert [s.speaker for s in segments] == ["SPEAKER_00"]
    assert Pipeline.called_with[1] == {}  # plain from_pretrained, no auth kwargs


def test_pyannote_filters_short_segments(monkeypatch):
    class Pipeline:
        @classmethod
        def from_pretrained(cls, model, **kwargs):  # noqa: ARG003
            return cls()

        def __call__(self, _path):
            return _Diarization(
                [(0.0, 0.05, "SPEAKER_SHORT"), (1.0, 3.0, "SPEAKER_LONG")]
            )

    _install_fake_pyannote(monkeypatch, Pipeline)
    config = DiarizationConfig(
        backend=DiarizationBackend.PYANNOTE, min_segment_duration=0.5
    )
    segments = diarize_audio("fake.wav", config)
    # The 0.05s segment is dropped by min_segment_duration.
    assert [s.speaker for s in segments] == ["SPEAKER_LONG"]


def test_pyannote_load_failure_includes_gated_hint(monkeypatch):
    class Pipeline:
        @classmethod
        def from_pretrained(cls, model, **kwargs):  # noqa: ARG003
            raise RuntimeError("403 Forbidden: model is gated")

        def __call__(self, _path):  # pragma: no cover - never reached
            return _Diarization([])

    _install_fake_pyannote(monkeypatch, Pipeline)
    config = DiarizationConfig(backend=DiarizationBackend.PYANNOTE)
    with pytest.raises(RuntimeError) as exc:
        diarize_audio("fake.wav", config)
    assert "gated on Hugging Face" in str(exc.value)


def test_pyannote_load_failure_without_hint(monkeypatch):
    class Pipeline:
        @classmethod
        def from_pretrained(cls, model, **kwargs):  # noqa: ARG003
            raise RuntimeError("some unrelated error")

        def __call__(self, _path):  # pragma: no cover - never reached
            return _Diarization([])

    _install_fake_pyannote(monkeypatch, Pipeline)
    config = DiarizationConfig(backend=DiarizationBackend.PYANNOTE)
    with pytest.raises(RuntimeError) as exc:
        diarize_audio("fake.wav", config)
    msg = str(exc.value)
    assert "Failed to load pyannote pipeline" in msg
    assert "gated on Hugging Face" not in msg
