"""Tests for media_studio.features.parakeet_asr — Parakeet ASR loader seam.

The PURE half (chunk-span math, per-chunk merge with absolute offsets, the §3
segment/word normalizers, CPU fallback, duration resolution, the offline
degrade) is tested with hand-built dicts + a FAKE loader/model — no NeMo, no
torch, no model weights, no audio. A "Romanian" transcript is produced through
the injected seam to prove the drop-in shape. No heavy import anywhere.
"""

from __future__ import annotations

from typing import Any

import pytest
from media_studio.features import parakeet_asr as pk


# --------------------------------------------------------------------------- #
# fakes (the injected seams)
# --------------------------------------------------------------------------- #
class FakeModel:
    """A ParakeetModel whose transcribe returns a canned per-chunk result."""

    def __init__(
        self,
        *,
        results: dict[tuple[float, float], Any] | None = None,
        default: Any = None,
        record: list[dict[str, Any]] | None = None,
    ) -> None:
        self._results = results or {}
        self._default = default if default is not None else {"segments": [], "info": {"language": "ro"}}
        self._record = record if record is not None else []

    def transcribe(self, audio: str, **kwargs: Any) -> Any:
        span = (kwargs.get("offset"), kwargs.get("duration"))
        self._record.append({"audio": audio, **kwargs})
        return self._results.get(span, self._default)


class FakeLoader:
    """A ParakeetLoader that returns a canned model, optionally failing on GPU."""

    def __init__(
        self,
        model: Any,
        *,
        fail_devices: set[str] | None = None,
        record: list[tuple[str, str, str]] | None = None,
    ) -> None:
        self._model = model
        self._fail_devices = fail_devices or set()
        self._record = record if record is not None else []

    def load(self, model: str, device: str, compute_type: str) -> Any:
        self._record.append((model, device, compute_type))
        if device in self._fail_devices:
            raise RuntimeError(f"no {device}")
        return self._model


def seg(start: float, end: float, text: str, words: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"start": start, "end": end, "text": text, "words": words or []}


def word(text: str, start: float, end: float) -> dict[str, Any]:
    return {"text": text, "start": start, "end": end}


# --------------------------------------------------------------------------- #
# pure: chunk_audio_spans
# --------------------------------------------------------------------------- #
class TestChunkAudioSpans:
    def test_single_short_chunk(self):
        assert pk.chunk_audio_spans(120.0, chunk_sec=300.0) == ((0.0, 120.0),)

    def test_exact_multiple(self):
        assert pk.chunk_audio_spans(600.0, chunk_sec=300.0) == ((0.0, 300.0), (300.0, 600.0))

    def test_ragged_last_chunk_clamped(self):
        assert pk.chunk_audio_spans(700.0, chunk_sec=300.0) == (
            (0.0, 300.0),
            (300.0, 600.0),
            (600.0, 700.0),
        )

    def test_zero_duration_no_spans(self):
        assert pk.chunk_audio_spans(0.0) == ()

    def test_negative_duration_no_spans(self):
        assert pk.chunk_audio_spans(-5.0) == ()

    def test_nonpositive_chunk_sec_raises(self):
        with pytest.raises(ValueError, match="chunk_sec must be positive"):
            pk.chunk_audio_spans(100.0, chunk_sec=0.0)


# --------------------------------------------------------------------------- #
# pure: merge_chunk_transcripts
# --------------------------------------------------------------------------- #
class TestMergeChunkTranscripts:
    def test_offsets_folded_into_segments_and_words(self):
        part0 = {
            "language": "ro",
            "segments": [seg(0.0, 2.0, "salut", [word("salut", 0.0, 2.0)])],
            "durationSec": 300.0,
        }
        part1 = {
            "language": "ro",
            "segments": [seg(1.0, 3.0, "lume", [word("lume", 1.0, 3.0)])],
            "durationSec": 100.0,
        }
        merged = pk.merge_chunk_transcripts([(0.0, part0), (300.0, part1)])
        assert merged["language"] == "ro"
        assert merged["segments"][0]["start"] == 0.0
        assert merged["segments"][1]["start"] == 301.0
        assert merged["segments"][1]["end"] == 303.0
        assert merged["segments"][1]["words"][0] == {"text": "lume", "start": 301.0, "end": 303.0}
        # durationSec = max(offset + part_dur)
        assert merged["durationSec"] == 400.0

    def test_language_taken_from_first_nonempty(self):
        part0 = {"language": "", "segments": [], "durationSec": 10.0}
        part1 = {"language": "ro", "segments": [], "durationSec": 10.0}
        merged = pk.merge_chunk_transcripts([(0.0, part0), (10.0, part1)])
        assert merged["language"] == "ro"

    def test_missing_keys_default(self):
        # A part missing language/segments/durationSec must not raise.
        merged = pk.merge_chunk_transcripts([(0.0, {})])
        assert merged == {"language": "", "segments": [], "durationSec": 0.0}

    def test_segment_missing_word_fields_default(self):
        part = {"language": "ro", "segments": [{}], "durationSec": 5.0}
        merged = pk.merge_chunk_transcripts([(2.0, part)])
        s = merged["segments"][0]
        assert s == {"start": 2.0, "end": 2.0, "text": "", "words": []}

    def test_empty_parts(self):
        assert pk.merge_chunk_transcripts([]) == {"language": "", "segments": [], "durationSec": 0.0}


# --------------------------------------------------------------------------- #
# load_model_with_cpu_fallback
# --------------------------------------------------------------------------- #
class TestCpuFallback:
    def test_gpu_success_no_fallback(self):
        rec: list[tuple[str, str, str]] = []
        loader = FakeLoader(FakeModel(), record=rec)
        model, device = pk.load_model_with_cpu_fallback(loader)
        assert device == pk.DEFAULT_DEVICE
        assert rec == [(pk.DEFAULT_MODEL, "cuda", "float16")]
        assert model is loader._model

    def test_gpu_fail_falls_back_to_cpu(self):
        rec: list[tuple[str, str, str]] = []
        loader = FakeLoader(FakeModel(), fail_devices={"cuda"}, record=rec)
        model, device = pk.load_model_with_cpu_fallback(loader)
        assert device == pk.CPU_DEVICE
        assert rec[-1] == (pk.DEFAULT_MODEL, "cpu", "int8")

    def test_cpu_request_failure_reraises(self):
        loader = FakeLoader(FakeModel(), fail_devices={"cpu"})
        with pytest.raises(RuntimeError, match="no cpu"):
            pk.load_model_with_cpu_fallback(loader, device="cpu", compute_type="int8")


# --------------------------------------------------------------------------- #
# _resolve_duration (via transcribe_file paths) + direct
# --------------------------------------------------------------------------- #
class TestResolveDuration:
    def test_explicit_duration_wins(self):
        assert pk._resolve_duration("a.wav", 42.0, None) == 42.0

    def test_probe_used_when_no_explicit(self):
        assert pk._resolve_duration("a.wav", None, lambda p: 17.0) == 17.0

    def test_probe_failure_degrades_to_zero(self):
        def boom(_p: str) -> float:
            raise OSError("ffprobe gone")

        assert pk._resolve_duration("a.wav", None, boom) == 0.0

    def test_probe_negative_clamped_to_zero(self):
        assert pk._resolve_duration("a.wav", None, lambda p: -3.0) == 0.0

    def test_no_duration_no_probe_is_zero(self):
        assert pk._resolve_duration("a.wav", None, None) == 0.0

    def test_zero_explicit_falls_through_to_probe(self):
        assert pk._resolve_duration("a.wav", 0.0, lambda p: 9.0) == 9.0


# --------------------------------------------------------------------------- #
# default_models_present
# --------------------------------------------------------------------------- #
class TestDefaultModelsPresent:
    def test_missing_asset_machinery_returns_false(self):
        # No asset registered for parakeet in the test env -> graceful False.
        assert pk.default_models_present({}) is False


# --------------------------------------------------------------------------- #
# backend module is import-light (no heavy deps pulled at import time)
# --------------------------------------------------------------------------- #
class TestBackendImportLight:
    def test_backend_imports_without_heavy_deps(self):
        # The whole point of the seam: importing the backend module must NOT
        # drag in nemo/torch (those live inside the methods). Tests run in a
        # venv WITHOUT nemo/torch, so a heavy import here would ImportError.
        from media_studio.features import parakeet_asr_backend as be

        assert hasattr(be, "RealParakeetLoader")


# --------------------------------------------------------------------------- #
# transcribe_file — the full runner (drop-in §3 Transcript)
# --------------------------------------------------------------------------- #
def _ro_model() -> FakeModel:
    """A model that returns Romanian segments for two chunks."""
    return FakeModel(
        results={
            (0.0, 300.0): {
                "segments": [seg(0.0, 2.0, "Bună ziua", [word("Bună", 0.0, 1.0), word("ziua", 1.0, 2.0)])],
                "info": {"language": "ro"},
            },
            (300.0, 100.0): {
                "segments": [seg(0.0, 1.5, "mulțumesc", [word("mulțumesc", 0.0, 1.5)])],
                "info": {"language": "ro"},
            },
        }
    )


class TestTranscribeFile:
    def test_romanian_via_seam_with_chunking_and_progress(self):
        progress: list[tuple[float, str]] = []
        loader = FakeLoader(_ro_model())
        out = pk.transcribe_file(
            "ro.wav",
            loader=loader,
            language="ro",
            duration=400.0,
            models_present=lambda s: True,
            on_progress=lambda pct, msg: progress.append((pct, msg)),
        )
        assert out["language"] == "ro"
        # two chunks -> two segments, second folded by +300s offset
        assert [s["text"] for s in out["segments"]] == ["Bună ziua", "mulțumesc"]
        assert out["segments"][1]["start"] == 300.0
        assert out["segments"][1]["words"][0]["start"] == 300.0
        assert out["durationSec"] == 400.0
        assert progress[0] == (0.0, "transcribing")
        assert progress[-1] == (100.0, "done")

    def test_duration_via_probe(self):
        loader = FakeLoader(_ro_model())
        out = pk.transcribe_file(
            "ro.wav",
            loader=loader,
            language="ro",
            duration_probe=lambda p: 400.0,
            models_present=lambda s: True,
        )
        assert len(out["segments"]) == 2

    def test_cancel_stops_after_first_chunk(self):
        calls = {"n": 0}

        def should_cancel() -> bool:
            # allow the first chunk, cancel before the second
            calls["n"] += 1
            return calls["n"] > 1

        loader = FakeLoader(_ro_model())
        out = pk.transcribe_file(
            "ro.wav",
            loader=loader,
            language="ro",
            duration=400.0,
            models_present=lambda s: True,
            should_cancel=should_cancel,
        )
        assert [s["text"] for s in out["segments"]] == ["Bună ziua"]

    def test_bare_iterable_segment_shape(self):
        # A backend that returns a bare list of segments (no segments/info keys).
        model = FakeModel(default=[seg(0.0, 1.0, "hi", [word("hi", 0.0, 1.0)])])
        loader = FakeLoader(model)
        out = pk.transcribe_file(
            "x.wav",
            loader=loader,
            language="en",
            duration=10.0,
            models_present=lambda s: True,
        )
        assert out["segments"][0]["text"] == "hi"
        assert out["language"] == "en"

    def test_detected_language_used_when_no_hint(self):
        model = FakeModel(default={"segments": [], "info": {"language": "ro"}})
        loader = FakeLoader(model)
        out = pk.transcribe_file(
            "x.wav",
            loader=loader,
            language=None,
            duration=5.0,
            models_present=lambda s: True,
        )
        assert out["language"] == "ro"

    def test_language_hint_backfilled_when_merge_empty(self):
        # Empty info language + no segments -> merge yields "" -> backfilled.
        model = FakeModel(default={"segments": [], "info": {"language": ""}})
        loader = FakeLoader(model)
        out = pk.transcribe_file(
            "x.wav",
            loader=loader,
            language="ro",
            duration=5.0,
            models_present=lambda s: True,
        )
        assert out["language"] == "ro"

    def test_zero_duration_yields_empty_no_progress_total(self):
        # duration 0 -> no spans -> empty transcript, progress 0 then 100.
        progress: list[tuple[float, str]] = []
        loader = FakeLoader(_ro_model())
        out = pk.transcribe_file(
            "x.wav",
            loader=loader,
            language="ro",
            duration=0.0,
            models_present=lambda s: True,
            on_progress=lambda pct, msg: progress.append((pct, msg)),
        )
        assert out["segments"] == []
        assert out["durationSec"] == 0.0
        assert progress == [(0.0, "transcribing"), (100.0, "done")]

    def test_offline_missing_weights_degrades_to_empty(self):
        # Offline + no weights -> empty transcript (whisper fallback path).
        out = pk.transcribe_file(
            "x.wav",
            loader=FakeLoader(_ro_model()),
            language="ro",
            duration=400.0,
            settings={"offline": True},
            models_present=lambda s: False,
        )
        assert out == {"language": "ro", "segments": [], "durationSec": 0.0}

    def test_online_missing_weights_still_attempts(self):
        # Not offline but weights "missing" by probe -> still runs (could fetch).
        loader = FakeLoader(_ro_model())
        out = pk.transcribe_file(
            "x.wav",
            loader=loader,
            language="ro",
            duration=400.0,
            settings={"offline": False},
            models_present=lambda s: False,
        )
        assert len(out["segments"]) == 2

    def test_default_loader_used_when_none_and_offline(self):
        # loader=None + offline + missing weights returns BEFORE building the
        # real loader, so no heavy import is triggered.
        out = pk.transcribe_file(
            "x.wav",
            language="ro",
            settings={"offline": True},
            models_present=lambda s: False,
        )
        assert out["segments"] == []


# --------------------------------------------------------------------------- #
# normalizers (_attr / _word_to_dict / _segment_to_dict via object inputs)
# --------------------------------------------------------------------------- #
class _Obj:
    def __init__(self, **kw: Any) -> None:
        self.__dict__.update(kw)


class TestNormalizers:
    def test_attr_reads_object_then_dict(self):
        assert pk._attr(_Obj(word="hi"), "word") == "hi"
        assert pk._attr({"text": "yo"}, "word", "text") == "yo"
        assert pk._attr(_Obj(x=1), "missing") is None
        assert pk._attr({"a": 1}, "b") is None

    def test_word_to_dict_object_with_nones(self):
        w = pk._word_to_dict(_Obj(word=None, start=None, end=None))
        assert w == {"text": "", "start": 0.0, "end": 0.0}

    def test_segment_to_dict_object_with_words(self):
        s = pk._segment_to_dict(_Obj(start=1.0, end=2.0, text="hey", words=[_Obj(word="hey", start=1.0, end=2.0)]))
        assert s["text"] == "hey"
        assert s["words"][0] == {"text": "hey", "start": 1.0, "end": 2.0}

    def test_segment_to_dict_object_missing_fields(self):
        s = pk._segment_to_dict(_Obj())
        assert s == {"start": 0.0, "end": 0.0, "text": "", "words": []}
