import sys
import types

from media_core.diarize import DiarizationBackend, DiarizationConfig, diarize_audio


class _Turn:
    def __init__(self, start: float, end: float):
        self.start = start
        self.end = end


class _Diarization:
    def itertracks(self, *, yield_label: bool = False):  # noqa: ARG002 - match pyannote API surface
        yield _Turn(0.0, 1.0), None, "SPEAKER_00"


def _install_fake_pyannote(monkeypatch, *, Pipeline):
    pyannote = types.ModuleType("pyannote")
    pyannote_audio = types.ModuleType("pyannote.audio")
    pyannote_audio.Pipeline = Pipeline
    monkeypatch.setitem(sys.modules, "pyannote", pyannote)
    monkeypatch.setitem(sys.modules, "pyannote.audio", pyannote_audio)


def test_pyannote_uses_token_kw_when_supported(monkeypatch):
    class TokenOnlyPipeline:
        called_kwargs = None

        @classmethod
        def from_pretrained(cls, _model, **kwargs):
            if "use_auth_token" in kwargs:
                raise TypeError("unexpected keyword argument 'use_auth_token'")
            cls.called_kwargs = dict(kwargs)
            return cls()

        def __call__(self, _path):
            return _Diarization()

    _install_fake_pyannote(monkeypatch, Pipeline=TokenOnlyPipeline)

    config = DiarizationConfig(backend=DiarizationBackend.PYANNOTE, huggingface_token="hf_dummy")
    segments = diarize_audio("fake.wav", config)
    assert [s.speaker for s in segments] == ["SPEAKER_00"]
    assert TokenOnlyPipeline.called_kwargs == {"token": "hf_dummy"}


def test_pyannote_falls_back_to_use_auth_token(monkeypatch):
    class UseAuthTokenOnlyPipeline:
        called_kwargs = None

        @classmethod
        def from_pretrained(cls, _model, **kwargs):
            if "token" in kwargs:
                raise TypeError("unexpected keyword argument 'token'")
            cls.called_kwargs = dict(kwargs)
            return cls()

        def __call__(self, _path):
            return _Diarization()

    _install_fake_pyannote(monkeypatch, Pipeline=UseAuthTokenOnlyPipeline)

    config = DiarizationConfig(backend=DiarizationBackend.PYANNOTE, huggingface_token="hf_dummy")
    segments = diarize_audio("fake.wav", config)
    assert [s.speaker for s in segments] == ["SPEAKER_00"]
    assert UseAuthTokenOnlyPipeline.called_kwargs == {"use_auth_token": "hf_dummy"}

