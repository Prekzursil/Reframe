from __future__ import absolute_import, division

import sys
import types
from pathlib import Path

import pytest

from media_core.diarize import (
    _diarize_pyannote,
    _diarize_speechbrain,
    _iter_pyannote_tracks,
    assign_speakers_to_lines,
    diarize_audio,
)
from media_core.diarize.config import DiarizationBackend, DiarizationConfig
from media_core.diarize.models import SpeakerSegment
from media_core.subtitles.builder import SubtitleLine
from media_core.transcribe.models import Word


def _expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


class _FakeTurn:
    def __init__(self, start: float, end: float):
        self.start = start
        self.end = end


class _FakeTracks:
    def __init__(self, rows):
        self._rows = rows

    def itertracks(self, yield_label: bool = True):
        _ = yield_label
        return iter(self._rows)


class _FakeBoundary:
    def __init__(self, values):
        self._values = list(values)

    def detach(self):
        return self

    def cpu(self):
        return self

    def tolist(self):
        return list(self._values)


class _FakeScalar:
    def __init__(self, value: float):
        self._value = value

    def item(self):
        return self._value


class _FakeTensor:
    def __init__(self, data):
        self.data = data

    @property
    def ndim(self):
        if isinstance(self.data, list) and self.data and isinstance(self.data[0], list):
            return 2
        return 1

    @property
    def shape(self):
        if self.ndim == 2:
            return (len(self.data), len(self.data[0]) if self.data[0] else 0)
        return (len(self.data), 0)

    def __getitem__(self, key):
        if isinstance(key, tuple):
            row_sel, col_sel = key
            if row_sel == slice(None):
                rows = self.data
            else:
                rows = [self.data[row_sel]]
            if isinstance(col_sel, slice):
                cols = [row[col_sel] for row in rows]
            else:
                cols = [[row[col_sel]] for row in rows]
            return _FakeTensor(cols)
        if self.ndim == 2:
            return _FakeTensor(self.data[key])
        return self.data[key]

    def to(self, _dtype):
        return self

    def detach(self):
        return self

    def mean(self, dim=0, keepdim=False):
        if self.ndim != 2:
            return self
        if dim != 0:
            raise ValueError("fake tensor only supports dim=0")
        cols = len(self.data[0]) if self.data else 0
        avg = []
        for idx in range(cols):
            avg.append(sum(row[idx] for row in self.data) / max(len(self.data), 1))
        if keepdim:
            return _FakeTensor([avg])
        return _FakeTensor(avg)

    def _binary_op(self, other, op):
        if isinstance(other, _FakeTensor):
            other_data = other.data
        else:
            other_data = other

        if self.ndim == 2:
            if isinstance(other_data, list) and other_data and isinstance(other_data[0], list):
                rows = []
                for left_row, right_row in zip(self.data, other_data):
                    rows.append([op(lv, rv) for lv, rv in zip(left_row, right_row)])
                return _FakeTensor(rows)
            return _FakeTensor([[op(v, other_data) for v in row] for row in self.data])

        if isinstance(other_data, list):
            return _FakeTensor([op(lv, rv) for lv, rv in zip(self.data, other_data)])
        return _FakeTensor([op(v, other_data) for v in self.data])

    def __mul__(self, other):
        return self._binary_op(other, lambda a, b: a * b)

    def __rmul__(self, other):
        return self.__mul__(other)

    def __add__(self, other):
        return self._binary_op(other, lambda a, b: a + b)

    def __truediv__(self, other):
        return self._binary_op(other, lambda a, b: a / b)


class _FakeNumpyLike:
    def __init__(self, values):
        self._values = values

    @property
    def T(self):
        return [list(row) for row in zip(*self._values)]


def _install_fake_pyannote(monkeypatch, *, pipeline_cls):
    pkg = types.ModuleType("pyannote")
    audio = types.ModuleType("pyannote.audio")
    audio.Pipeline = pipeline_cls
    monkeypatch.setitem(sys.modules, "pyannote", pkg)
    monkeypatch.setitem(sys.modules, "pyannote.audio", audio)


def _install_fake_speechbrain(monkeypatch, tmp_path: Path, *, use_pretrained: bool = False, torchaudio_fails: bool = False):
    hub = types.ModuleType("huggingface_hub")

    def hf_hub_download(*_args, token=None, **_kwargs):
        return token

    def snapshot_download(repo_id: str, local_dir: str, local_dir_use_symlinks: bool = False):
        _ = (repo_id, local_dir_use_symlinks)
        p = Path(local_dir)
        p.mkdir(parents=True, exist_ok=True)
        (p / "hyperparams.yaml").write_text("ok: true\n", encoding="utf-8")
        return str(p)

    setattr(hub, "hf_hub_download", hf_hub_download)
    setattr(hub, "snapshot_download", snapshot_download)
    monkeypatch.setitem(sys.modules, "huggingface_hub", hub)

    fake_torch = types.ModuleType("torch")
    setattr(fake_torch, "float32", "float32")

    def from_numpy(values):
        return _FakeTensor(values)

    setattr(fake_torch, "from_numpy", from_numpy)

    functional = types.ModuleType("torch.nn.functional")

    def normalize(tensor, dim=0):
        _ = dim
        return tensor

    def cosine_similarity(_left, _right, dim=0):
        _ = dim
        return _FakeScalar(0.9)

    setattr(functional, "normalize", normalize)
    setattr(functional, "cosine_similarity", cosine_similarity)

    fake_torch_nn = types.ModuleType("torch.nn")
    setattr(fake_torch_nn, "functional", functional)

    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "torch.nn", fake_torch_nn)
    monkeypatch.setitem(sys.modules, "torch.nn.functional", functional)

    torchaudio = types.ModuleType("torchaudio")

    def load(_path):
        if torchaudio_fails:
            raise RuntimeError("torchaudio failure")
        return _FakeTensor([[0.1, 0.2, 0.3, 0.4]]), 10

    setattr(torchaudio, "load", load)
    monkeypatch.setitem(sys.modules, "torchaudio", torchaudio)

    if torchaudio_fails:
        sf = types.ModuleType("soundfile")

        def read(_path, dtype="float32", always_2d=True):
            _ = (dtype, always_2d)
            return _FakeNumpyLike([[0.1], [0.2], [0.3], [0.4]]), 10

        setattr(sf, "read", read)
        monkeypatch.setitem(sys.modules, "soundfile", sf)

    class FakeVAD:
        @classmethod
        def from_hparams(cls, **_kwargs):
            return cls()

        def get_speech_segments(self, _path):
            return _FakeBoundary([0.0, 0.2, 0.2, 0.4])

    class FakeSpeakerRecognition:
        @classmethod
        def from_hparams(cls, **_kwargs):
            return cls()

        def encode_batch(self, _segment):
            return _FakeTensor([0.6, 0.4])

    utils_fetching = types.ModuleType("speechbrain.utils.fetching")
    setattr(utils_fetching, "LocalStrategy", types.SimpleNamespace(NO_LINK="NO_LINK"))
    monkeypatch.setitem(sys.modules, "speechbrain.utils.fetching", utils_fetching)

    if use_pretrained:
        pretrained = types.ModuleType("speechbrain.pretrained")
        setattr(pretrained, "VAD", FakeVAD)
        setattr(pretrained, "SpeakerRecognition", FakeSpeakerRecognition)
        monkeypatch.setitem(sys.modules, "speechbrain.pretrained", pretrained)
        monkeypatch.delitem(sys.modules, "speechbrain.inference.VAD", raising=False)
        monkeypatch.delitem(sys.modules, "speechbrain.inference.speaker", raising=False)
    else:
        vad_mod = types.ModuleType("speechbrain.inference.VAD")
        setattr(vad_mod, "VAD", FakeVAD)
        spk_mod = types.ModuleType("speechbrain.inference.speaker")
        setattr(spk_mod, "SpeakerRecognition", FakeSpeakerRecognition)
        monkeypatch.setitem(sys.modules, "speechbrain.inference.VAD", vad_mod)
        monkeypatch.setitem(sys.modules, "speechbrain.inference.speaker", spk_mod)

    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf-home"))


def test_diarize_audio_noop_and_unknown_backend():
    cfg = DiarizationConfig(backend=DiarizationBackend.NOOP)
    _expect(diarize_audio("audio.wav", cfg) == [], "Expected NOOP backend to yield no segments")

    cfg_unknown = types.SimpleNamespace(backend="unknown")
    with pytest.raises(ValueError):
        diarize_audio("audio.wav", cfg_unknown)


def test_assign_speakers_to_lines_with_and_without_segments():
    word = Word(start=0.0, end=0.2, text="hi")
    lines = [SubtitleLine(start=0.0, end=0.5, words=[word]), SubtitleLine(start=1.0, end=1.5, words=[word])]

    copied = assign_speakers_to_lines(lines, [])
    _expect(copied[0].speaker is None, "Expected no speaker when no segments are provided")

    segments = [
        SpeakerSegment(start=0.0, end=0.4, speaker="SPEAKER_00"),
        SpeakerSegment(start=1.0, end=1.4, speaker="SPEAKER_01"),
    ]
    assigned = assign_speakers_to_lines(lines, segments)
    _expect(assigned[0].speaker == "SPEAKER_00", "Expected first line speaker assignment")
    _expect(assigned[1].speaker == "SPEAKER_01", "Expected second line speaker assignment")


def test_iter_pyannote_tracks_supports_multiple_shapes():
    direct = _FakeTracks([(_FakeTurn(0.0, 1.0), None, "A")])
    _expect(bool(list(_iter_pyannote_tracks(direct))), "Expected direct itertracks support")

    nested = types.SimpleNamespace(speaker_diarization=_FakeTracks([(_FakeTurn(0.0, 1.0), None, "B")]))
    _expect(bool(list(_iter_pyannote_tracks(nested))), "Expected nested speaker_diarization support")

    annotation_obj = _FakeTracks([(_FakeTurn(0.0, 1.0), None, "C")])
    def _to_annotation():
        return annotation_obj

    to_annotation = types.SimpleNamespace(to_annotation=_to_annotation)
    _expect(bool(list(_iter_pyannote_tracks(to_annotation))), "Expected to_annotation fallback support")

    with pytest.raises(RuntimeError):
        list(_iter_pyannote_tracks(object()))


def test_diarize_pyannote_import_error_and_gated_hint(monkeypatch):
    monkeypatch.delitem(sys.modules, "pyannote", raising=False)
    monkeypatch.delitem(sys.modules, "pyannote.audio", raising=False)

    cfg = DiarizationConfig(backend=DiarizationBackend.PYANNOTE, model="pyannote/speaker-diarization-3.1")
    with pytest.raises(RuntimeError):
        _diarize_pyannote("audio.wav", cfg)

    class FailingPipeline:
        @classmethod
        def from_pretrained(cls, *_args, **_kwargs):
            raise RuntimeError("403 gated")

    _install_fake_pyannote(monkeypatch, pipeline_cls=FailingPipeline)
    with pytest.raises(RuntimeError) as exc:
        _diarize_pyannote("audio.wav", cfg)
    _expect("Hint:" in str(exc.value), "Expected gated-access hint in pyannote failure")


def test_diarize_pyannote_token_fallback_and_segment_filter(monkeypatch):
    calls = []

    class FakePipeline:
        @classmethod
        def from_pretrained(cls, model, token=None, use_auth_token=None):
            calls.append((model, token, use_auth_token))
            if token is not None:
                raise TypeError("token kw not supported")
            return cls()

        def __call__(self, _path):
            return _FakeTracks([
                (_FakeTurn(0.0, 0.1), None, "A"),
                (_FakeTurn(0.1, 0.6), None, "B"),
            ])

    _install_fake_pyannote(monkeypatch, pipeline_cls=FakePipeline)
    cfg = DiarizationConfig(
        backend=DiarizationBackend.PYANNOTE,
        model="pyannote/model",
        huggingface_token="fixture-token",
        min_segment_duration=0.2,
    )

    segments = _diarize_pyannote("audio.wav", cfg)
    _expect(len(segments) == 1, "Expected min-segment-duration filtering to retain one segment")
    _expect(segments[0].speaker == "B", "Expected retained segment speaker label")
    _expect(any(call[1] == "fixture-token" for call in calls), "Expected token kwarg fallback to include fixture token")
    _expect(any(call[2] == "fixture-token" for call in calls), "Expected use_auth_token fallback to include fixture token")


def test_diarize_speechbrain_import_error(monkeypatch):
    monkeypatch.delitem(sys.modules, "torch", raising=False)
    monkeypatch.delitem(sys.modules, "torchaudio", raising=False)

    original_import = __import__

    def fake_import(name, *args, **kwargs):
        if name in {"torch", "torchaudio"}:
            raise ImportError("missing")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)
    cfg = DiarizationConfig(backend=DiarizationBackend.SPEECHBRAIN, model="speechbrain/model")
    with pytest.raises(RuntimeError):
        _diarize_speechbrain("audio.wav", cfg)


def test_diarize_speechbrain_main_path_and_pretrained_fallback(monkeypatch, tmp_path):
    cfg = DiarizationConfig(
        backend=DiarizationBackend.SPEECHBRAIN,
        model="speechbrain/spkrec-ecapa-voxceleb",
        min_segment_duration=0.05,
    )

    _install_fake_speechbrain(monkeypatch, tmp_path, use_pretrained=False, torchaudio_fails=False)
    segments = _diarize_speechbrain("audio.wav", cfg)
    _expect(bool(segments), "Expected non-empty speechbrain segments")
    _expect(segments[0].speaker.startswith("SPEAKER_"), "Expected synthetic speaker labels")

    _install_fake_speechbrain(monkeypatch, tmp_path, use_pretrained=True, torchaudio_fails=False)
    segments_fallback = _diarize_speechbrain("audio.wav", cfg)
    _expect(bool(segments_fallback), "Expected pretrained fallback to produce segments")


def test_diarize_speechbrain_torchaudio_failure_uses_soundfile(monkeypatch, tmp_path):
    cfg = DiarizationConfig(backend=DiarizationBackend.SPEECHBRAIN, model="speechbrain/spkrec-ecapa-voxceleb")
    _install_fake_speechbrain(monkeypatch, tmp_path, use_pretrained=False, torchaudio_fails=True)
    segments = _diarize_speechbrain("audio.wav", cfg)
    _expect(bool(segments), "Expected non-empty speechbrain segments")
