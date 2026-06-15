"""Coverage for the SpeechBrain diarization helper functions.

These helpers normally consume torch tensors. We drive them with lightweight
vector stand-ins that implement just the operations the code touches, so torch
is never required.
"""

from __future__ import annotations

import math

import pytest

from media_core.diarize import (
    DiarizationConfig,
    SpeakerSegment,
    _assign_centroid,
    _build_speaker_segments,
    _cluster_speech_regions,
    _load_mono_waveform,
)


# ---------------------------------------------------------------------------
# Fake tensor / functional infrastructure
# ---------------------------------------------------------------------------
class FakeVec:
    """A tiny 1-D vector supporting the ops used by the diarize helpers."""

    def __init__(self, values, ndim=1):
        self.values = list(values)
        self.ndim = ndim

    def to(self, _dtype):
        return self

    def detach(self):
        return self

    def __getitem__(self, idx):
        # Used when emb.ndim == 2 -> emb[0] selects the first row.
        return FakeVec(self.values, ndim=1)

    def __mul__(self, scalar):
        return FakeVec([v * scalar for v in self.values], ndim=self.ndim)

    __rmul__ = __mul__

    def __add__(self, other):
        return FakeVec([a + b for a, b in zip(self.values, other.values)], ndim=self.ndim)

    def __truediv__(self, scalar):
        return FakeVec([v / scalar for v in self.values], ndim=self.ndim)


class FakeFunctional:
    @staticmethod
    def cosine_similarity(a, b, dim=0):  # noqa: ARG004
        dot = sum(x * y for x, y in zip(a.values, b.values))
        na = math.sqrt(sum(x * x for x in a.values)) or 1.0
        nb = math.sqrt(sum(y * y for y in b.values)) or 1.0
        return FakeScalar(dot / (na * nb))

    @staticmethod
    def normalize(vec, dim=0):  # noqa: ARG004
        norm = math.sqrt(sum(x * x for x in vec.values)) or 1.0
        return FakeVec([x / norm for x in vec.values], ndim=vec.ndim)


class FakeScalar:
    def __init__(self, value):
        self.value = value

    def item(self):
        return self.value


class FakeTorch:
    float32 = "float32"

    @staticmethod
    def from_numpy(arr):
        return arr


# ---------------------------------------------------------------------------
# _assign_centroid
# ---------------------------------------------------------------------------
def test_assign_centroid_creates_first_cluster():
    functional = FakeFunctional()
    centroids: list = []
    counts: list = []
    emb = FakeVec([1.0, 0.0])
    idx = _assign_centroid(emb, centroids, counts, 0.65, functional)
    assert idx == 0
    assert len(centroids) == 1 and counts == [1]


def test_assign_centroid_creates_new_cluster_below_threshold():
    functional = FakeFunctional()
    centroids = [FakeVec([1.0, 0.0])]
    counts = [1]
    # Orthogonal vector -> cosine similarity 0 < 0.65 -> new cluster.
    idx = _assign_centroid(FakeVec([0.0, 1.0]), centroids, counts, 0.65, functional)
    assert idx == 1
    assert len(centroids) == 2


def test_assign_centroid_merges_into_existing_cluster():
    functional = FakeFunctional()
    centroids = [FakeVec([1.0, 0.0])]
    counts = [1]
    # Identical vector -> similarity 1.0 >= threshold -> merge + online update.
    idx = _assign_centroid(FakeVec([1.0, 0.0]), centroids, counts, 0.65, functional)
    assert idx == 0
    assert counts == [2]


def test_assign_centroid_keeps_best_when_later_is_less_similar():
    functional = FakeFunctional()
    # First centroid is the perfect match; second is orthogonal (lower similarity),
    # exercising the `sim > best_sim` False branch on the second iteration.
    centroids = [FakeVec([1.0, 0.0]), FakeVec([0.0, 1.0])]
    counts = [1, 1]
    idx = _assign_centroid(FakeVec([1.0, 0.0]), centroids, counts, 0.65, functional)
    assert idx == 0
    assert counts == [2, 1]


# ---------------------------------------------------------------------------
# _build_speaker_segments
# ---------------------------------------------------------------------------
def test_build_speaker_segments_merges_adjacent_same_speaker():
    regions = [(0.0, 1.0), (1.05, 2.0), (2.5, 3.0)]
    assignments = [0, 0, 1]  # first two same speaker and close -> merged
    config = DiarizationConfig()
    segments = _build_speaker_segments(regions, assignments, config)
    assert len(segments) == 2
    assert segments[0] == SpeakerSegment(start=0.0, end=2.0, speaker="SPEAKER_00")
    assert segments[1].speaker == "SPEAKER_01"


def test_build_speaker_segments_filters_short_when_min_duration_set():
    regions = [(0.0, 0.05), (1.0, 3.0)]
    assignments = [0, 1]
    config = DiarizationConfig(min_segment_duration=0.5)
    segments = _build_speaker_segments(regions, assignments, config)
    assert [s.speaker for s in segments] == ["SPEAKER_01"]


def test_build_speaker_segments_does_not_merge_when_gap_too_large():
    regions = [(0.0, 1.0), (5.0, 6.0)]
    assignments = [0, 0]  # same speaker but far apart -> not merged
    config = DiarizationConfig()
    segments = _build_speaker_segments(regions, assignments, config)
    assert len(segments) == 2


# ---------------------------------------------------------------------------
# _cluster_speech_regions
# ---------------------------------------------------------------------------
class FakeSpk:
    def __init__(self, embeddings):
        self._embeddings = list(embeddings)
        self._i = 0

    def encode_batch(self, _segment_wav):
        emb = self._embeddings[self._i]
        self._i += 1
        return emb


class FakeWaveform:
    def __init__(self, length):
        self.shape = (1, length)

    def __getitem__(self, _key):
        return "segment-wav"


def test_cluster_speech_regions_assigns_two_speakers():
    # Two distinct embeddings -> two clusters.
    spk = FakeSpk([FakeVec([1.0, 0.0], ndim=2), FakeVec([0.0, 1.0], ndim=2)])
    waveform = FakeWaveform(length=48000)
    config = DiarizationConfig()
    boundaries = [0.0, 1.0, 1.2, 2.0]  # two regions

    regions, assignments = _cluster_speech_regions(
        boundaries, waveform, 16000, spk, config, FakeTorch(), FakeFunctional()
    )
    assert len(regions) == 2
    assert assignments == [0, 1]


def test_cluster_speech_regions_skips_invalid_and_short_regions():
    spk = FakeSpk([FakeVec([1.0, 0.0], ndim=1)])
    waveform = FakeWaveform(length=16000 * 6)  # 6s of audio at 16kHz
    config = DiarizationConfig(min_segment_duration=0.5)
    # region 1: end <= start (invalid); region 2: too short; region 3: valid.
    boundaries = [2.0, 1.0, 3.0, 3.1, 4.0, 5.0]

    regions, assignments = _cluster_speech_regions(
        boundaries, waveform, 16000, spk, config, FakeTorch(), FakeFunctional()
    )
    assert regions == [(4.0, 5.0)]
    assert assignments == [0]


def test_cluster_speech_regions_skips_unparseable_boundary_pair():
    spk = FakeSpk([FakeVec([1.0, 0.0], ndim=1)])
    waveform = FakeWaveform(length=48000)
    config = DiarizationConfig()
    # A non-numeric boundary triggers the (TypeError, ValueError, IndexError) skip.
    boundaries = ["bad", 1.0, 2.0, 3.0]

    regions, assignments = _cluster_speech_regions(
        boundaries, waveform, 16000, spk, config, FakeTorch(), FakeFunctional()
    )
    assert regions == [(2.0, 3.0)]
    assert assignments == [0]


def test_cluster_speech_regions_skips_when_sample_window_empty():
    spk = FakeSpk([FakeVec([1.0, 0.0], ndim=1)])
    waveform = FakeWaveform(length=5)  # very short waveform
    config = DiarizationConfig()
    # start*sr and end*sr collapse to the same index -> end_idx <= start_idx skip.
    boundaries = [10.0, 10.0001]

    regions, assignments = _cluster_speech_regions(
        boundaries, waveform, 16000, spk, config, FakeTorch(), FakeFunctional()
    )
    assert regions == []
    assert assignments == []


# ---------------------------------------------------------------------------
# _load_mono_waveform
# ---------------------------------------------------------------------------
class MeanableWaveform:
    def __init__(self, shape, ndim=2):
        self.shape = shape
        self.ndim = ndim
        self.meaned = False

    def mean(self, dim=0, keepdim=False):  # noqa: ARG002
        self.meaned = True
        return MeanableWaveform((1, self.shape[1]), ndim=2)


def test_load_mono_waveform_downmixes_multichannel():
    multi = MeanableWaveform((2, 1000), ndim=2)

    class FakeTorchAudio:
        @staticmethod
        def load(_path):
            return multi, 16000

    waveform, sr = _load_mono_waveform("clip.wav", FakeTorch(), FakeTorchAudio())
    assert sr == 16000
    assert waveform.shape[0] == 1  # downmixed to mono


def test_load_mono_waveform_already_mono():
    mono = MeanableWaveform((1, 1000), ndim=2)

    class FakeTorchAudio:
        @staticmethod
        def load(_path):
            return mono, 22050

    waveform, sr = _load_mono_waveform("clip.wav", FakeTorch(), FakeTorchAudio())
    assert sr == 22050
    assert waveform is mono  # single channel left untouched


def test_load_mono_waveform_rejects_bad_shape():
    weird = MeanableWaveform((1000,), ndim=1)

    class FakeTorchAudio:
        @staticmethod
        def load(_path):
            return weird, 16000

    with pytest.raises(ValueError, match="Unexpected waveform shape"):
        _load_mono_waveform("clip.wav", FakeTorch(), FakeTorchAudio())


def test_load_mono_waveform_falls_back_to_soundfile(monkeypatch):
    import sys
    import types

    class FailingTorchAudio:
        @staticmethod
        def load(_path):
            raise RuntimeError("no backend")

    class FakeNumpyAudio:
        def __init__(self):
            self.ndim = 2
            self.shape = (1000, 2)

        @property
        def T(self):
            # Transposed -> channels-first (2, 1000); from_numpy returns it as-is.
            t = MeanableWaveform((2, 1000), ndim=2)
            return t

    fake_sf = types.ModuleType("soundfile")
    fake_sf.read = lambda *_a, **_k: (FakeNumpyAudio(), 16000)
    monkeypatch.setitem(sys.modules, "soundfile", fake_sf)

    waveform, sr = _load_mono_waveform("clip.wav", FakeTorch(), FailingTorchAudio())
    assert sr == 16000
    assert waveform.shape[0] == 1  # multichannel -> downmixed


def test_load_mono_waveform_soundfile_missing_raises(monkeypatch):
    class FailingTorchAudio:
        @staticmethod
        def load(_path):
            raise RuntimeError("no backend")

    real_import = __import__

    def fake_import(name, *args, **kwargs):
        if name == "soundfile":
            raise ImportError("soundfile not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)
    with pytest.raises(RuntimeError, match="soundfile.*not"):
        _load_mono_waveform("clip.wav", FakeTorch(), FailingTorchAudio())
