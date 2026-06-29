"""Tests for media_studio.features.ctc_align — word-timing forced alignment seam.

The PURE half (token flattening, span->word-timing normalization, merging timings
back onto a transcript, model-id resolution) is tested with hand-built
transcripts + canned :class:`WordSpan` lists — no model, no audio. The runner is
tested with a FAKE backend whose ``align`` returns canned spans and a FAKE
audio_loader returning synthetic numpy samples, plus the offline / empty / cancel
/ backend-failure degrade gates. No torch / ctc-forced-aligner import anywhere.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest
from media_studio.assets import manifest
from media_studio.features import ctc_align as ca


# --------------------------------------------------------------------------- #
# fakes (the injected seams)
# --------------------------------------------------------------------------- #
class FakeBackend:
    """A CtcAlignBackend whose ``align`` returns a canned WordSpan list."""

    def __init__(
        self,
        spans: list[ca.WordSpan],
        *,
        record: dict[str, Any] | None = None,
        raises: Exception | None = None,
    ) -> None:
        self._spans = spans
        self._record = record if record is not None else {}
        self._raises = raises

    def align(
        self,
        samples: np.ndarray,
        sr: int,
        tokens: Any,
        *,
        language: Any = None,
        on_progress: Any = None,
        should_cancel: Any = None,
    ) -> list[ca.WordSpan]:
        self._record["tokens"] = list(tokens)
        self._record["sr"] = sr
        self._record["language"] = language
        self._record["samples_len"] = int(np.asarray(samples).size)
        if on_progress is not None:
            on_progress(50.0, "aligning")
        if self._raises is not None:
            raise self._raises
        return self._spans


def make_factory(
    spans: list[ca.WordSpan],
    record: dict[str, Any] | None = None,
    raises: Exception | None = None,
) -> Any:
    return lambda settings, model_id: FakeBackend(spans, record=record, raises=raises)


def make_loader(samples: Any = (0.1, 0.2, 0.3, 0.4), sr: int = 16000) -> Any:
    return lambda path: (np.asarray(samples, dtype=np.float64), sr)


def transcript_with_words() -> dict[str, Any]:
    """A 2-segment transcript with per-word timings (3 words total)."""
    return {
        "language": "ro",
        "durationSec": 4.0,
        "segments": [
            {
                "start": 0.0,
                "end": 2.0,
                "text": "salut lume",
                "words": [
                    {"text": "salut", "start": 0.0, "end": 1.0},
                    {"text": "lume", "start": 1.0, "end": 2.0},
                ],
            },
            {
                "start": 2.0,
                "end": 4.0,
                "text": "azi",
                "words": [{"text": "azi", "start": 2.0, "end": 4.0}],
            },
        ],
    }


# --------------------------------------------------------------------------- #
# asset isolation (registration runs at import; keep the global registry clean)
# --------------------------------------------------------------------------- #
@pytest.fixture(autouse=True)
def _restore_registry():
    snap = manifest.registry_snapshot()
    yield
    manifest.registry_restore(snap)


# --------------------------------------------------------------------------- #
# pure: tokens_from_segments
# --------------------------------------------------------------------------- #
class TestTokensFromSegments:
    def test_prefers_word_text(self):
        assert ca.tokens_from_segments(transcript_with_words()) == ["salut", "lume", "azi"]

    def test_falls_back_to_whitespace_split(self):
        t = {"segments": [{"text": "one two three", "words": []}]}
        assert ca.tokens_from_segments(t) == ["one", "two", "three"]

    def test_drops_blank_word_tokens(self):
        t = {"segments": [{"words": [{"text": " "}, {"text": "kept"}, {"text": ""}]}]}
        assert ca.tokens_from_segments(t) == ["kept"]

    def test_drops_blank_split_tokens(self):
        # multiple spaces -> split() already drops empties; the .strip() guard is
        # exercised by a tab-only piece surviving split on a non-space separator.
        t = {"segments": [{"text": "   ", "words": []}]}
        assert ca.tokens_from_segments(t) == []

    def test_missing_segments_key(self):
        assert ca.tokens_from_segments({}) == []

    def test_segment_missing_text_and_words(self):
        assert ca.tokens_from_segments({"segments": [{}]}) == []


# --------------------------------------------------------------------------- #
# pure: emissions_to_word_timings
# --------------------------------------------------------------------------- #
class TestEmissionsToWordTimings:
    def test_basic_mapping(self):
        spans = [ca.WordSpan("hi", 0.0, 0.5, 0.9), ca.WordSpan("there", 0.5, 1.2)]
        words = ca.emissions_to_word_timings(spans)
        assert words == [
            {"text": "hi", "start": 0.0, "end": 0.5, "score": 0.9},
            {"text": "there", "start": 0.5, "end": 1.2, "score": 1.0},
        ]

    def test_clamps_to_duration(self):
        spans = [ca.WordSpan("x", -1.0, 9.0)]
        words = ca.emissions_to_word_timings(spans, duration=2.0)
        assert words[0]["start"] == 0.0
        assert words[0]["end"] == 2.0

    def test_no_duration_floors_at_zero(self):
        spans = [ca.WordSpan("x", -3.0, -1.0)]
        words = ca.emissions_to_word_timings(spans, duration=None)
        # both floored to 0.0; end >= start preserved
        assert words[0]["start"] == 0.0
        assert words[0]["end"] == 0.0

    def test_zero_duration_treated_as_no_cap(self):
        # duration <= 0 -> hi is None (no upper clamp), values floored at 0.
        spans = [ca.WordSpan("x", 0.5, 8.0)]
        words = ca.emissions_to_word_timings(spans, duration=0.0)
        assert words[0]["end"] == 8.0

    def test_end_floored_at_start(self):
        spans = [ca.WordSpan("x", 1.5, 1.0)]
        words = ca.emissions_to_word_timings(spans)
        assert words[0]["start"] == 1.5
        assert words[0]["end"] == 1.5

    def test_score_clamped(self):
        spans = [ca.WordSpan("x", 0.0, 1.0, 5.0)]
        assert ca.emissions_to_word_timings(spans)[0]["score"] == 1.0

    def test_empty_spans(self):
        assert ca.emissions_to_word_timings([]) == []


# --------------------------------------------------------------------------- #
# pure: merge_word_times_into_transcript
# --------------------------------------------------------------------------- #
class TestMerge:
    def test_full_coverage_retimes_and_preserves_grouping(self):
        t = transcript_with_words()
        word_times = [
            {"text": "salut", "start": 0.1, "end": 0.9, "score": 1.0},
            {"text": "lume", "start": 0.9, "end": 1.8, "score": 1.0},
            {"text": "azi", "start": 2.1, "end": 3.7, "score": 1.0},
        ]
        out = ca.merge_word_times_into_transcript(t, word_times)
        segs = out["segments"]
        assert len(segs[0]["words"]) == 2
        assert segs[0]["start"] == 0.1
        assert segs[0]["end"] == 1.8
        assert segs[1]["start"] == 2.1
        assert segs[1]["end"] == 3.7

    def test_does_not_mutate_input(self):
        t = transcript_with_words()
        original_first_word = dict(t["segments"][0]["words"][0])
        ca.merge_word_times_into_transcript(
            t,
            [
                {"text": "a", "start": 9.0, "end": 9.5},
                {"text": "b", "start": 9.5, "end": 9.9},
                {"text": "c", "start": 10.0, "end": 10.5},
            ],
        )
        assert t["segments"][0]["words"][0] == original_first_word
        assert t["segments"][0]["start"] == 0.0

    def test_short_word_list_leaves_remaining_segments_unchanged(self):
        t = transcript_with_words()
        # only 2 words supplied -> first segment retimed, second left unchanged
        out = ca.merge_word_times_into_transcript(
            t,
            [
                {"text": "salut", "start": 0.2, "end": 0.8},
                {"text": "lume", "start": 0.8, "end": 1.5},
            ],
        )
        assert out["segments"][0]["start"] == 0.2
        assert out["segments"][1] == t["segments"][1]

    def test_partial_segment_coverage_keeps_segment_unchanged(self):
        # first segment needs 2 words but only 1 is available -> unchanged.
        t = transcript_with_words()
        out = ca.merge_word_times_into_transcript(t, [{"text": "salut", "start": 0.2, "end": 0.8}])
        assert out["segments"][0] == t["segments"][0]

    def test_zero_word_segment_passes_through(self):
        t = {"segments": [{"start": 0.0, "end": 1.0, "text": "", "words": []}], "language": "x"}
        out = ca.merge_word_times_into_transcript(t, [{"text": "a", "start": 0.0, "end": 0.5}])
        assert out["segments"][0] == t["segments"][0]

    def test_no_segments_key(self):
        out = ca.merge_word_times_into_transcript({"language": "x"}, [])
        assert out == {"language": "x", "segments": []}


# --------------------------------------------------------------------------- #
# pure: _segment_word_count
# --------------------------------------------------------------------------- #
class TestSegmentWordCount:
    def test_counts_nonblank_words(self):
        assert ca._segment_word_count({"words": [{"text": "a"}, {"text": " "}, {"text": "b"}]}) == 2

    def test_falls_back_to_split(self):
        assert ca._segment_word_count({"text": "a b c"}) == 3

    def test_empty(self):
        assert ca._segment_word_count({}) == 0


# --------------------------------------------------------------------------- #
# pure: _resolve_model_id + _asset_for_model (Decision #1 switch)
# --------------------------------------------------------------------------- #
class TestResolveModelId:
    def test_default(self):
        assert ca._resolve_model_id({}, None) == ca.DEFAULT_MODEL_ID

    def test_explicit_arg_full_id_wins(self):
        assert ca._resolve_model_id({"ctcModelId": "x"}, "facebook/custom") == "facebook/custom"

    def test_explicit_arg_alias_resolved(self):
        assert ca._resolve_model_id({}, "wav2vec2-960h-lv60") == ca.MIT_MODEL_IDS["wav2vec2-960h-lv60"]

    def test_settings_alias_resolved(self):
        assert ca._resolve_model_id({"ctcModelId": "hubert-large"}, None) == ca.MIT_MODEL_IDS["hubert-large"]

    def test_settings_full_id(self):
        assert ca._resolve_model_id({"ctcModelId": "my/model"}, None) == "my/model"

    def test_settings_non_string_ignored(self):
        assert ca._resolve_model_id({"ctcModelId": 123}, None) == ca.DEFAULT_MODEL_ID

    def test_settings_empty_string_ignored(self):
        assert ca._resolve_model_id({"ctcModelId": ""}, None) == ca.DEFAULT_MODEL_ID

    def test_asset_for_default_model(self):
        assert ca._asset_for_model(ca.DEFAULT_MODEL_ID) == ca.ASSET_NAME

    def test_asset_for_mit_model(self):
        assert ca._asset_for_model("facebook/anything") == ca.MIT_ASSET_NAME

    # M5 — RO alignment opt-in (gigant/romanian-wav2vec2); MMS-300m stays default.
    def test_default_path_unchanged_when_no_ctc_model(self):
        assert ca._resolve_model_id({}, None) == ca.DEFAULT_MODEL_ID
        assert ca._asset_for_model(ca.DEFAULT_MODEL_ID) == ca.ASSET_NAME

    def test_ro_settings_alias_resolved(self):
        resolved = ca._resolve_model_id({"ctcModelId": "romanian-wav2vec2"}, None)
        assert resolved == ca.RO_MODEL_IDS["romanian-wav2vec2"]
        assert resolved == "gigant/romanian-wav2vec2"

    def test_ro_explicit_arg_alias_resolved(self):
        assert ca._resolve_model_id({}, "romanian-wav2vec2") == "gigant/romanian-wav2vec2"

    def test_ro_full_id_passthrough(self):
        assert ca._resolve_model_id({"ctcModelId": "gigant/romanian-wav2vec2"}, None) == (
            "gigant/romanian-wav2vec2"
        )

    def test_asset_for_ro_model_is_its_own_asset(self):
        ro_id = ca.RO_MODEL_IDS["romanian-wav2vec2"]
        assert ca._asset_for_model(ro_id) == ca.RO_ASSET_NAME
        # the RO asset is distinct from BOTH the default MMS and the MIT wav2vec2.
        assert ca.RO_ASSET_NAME not in {ca.ASSET_NAME, ca.MIT_ASSET_NAME}


# --------------------------------------------------------------------------- #
# runner: align_words happy path + seams
# --------------------------------------------------------------------------- #
class TestAlignWordsHappyPath:
    def test_refines_word_timings(self):
        t = transcript_with_words()
        record: dict[str, Any] = {}
        spans = [
            ca.WordSpan("salut", 0.05, 0.95),
            ca.WordSpan("lume", 0.95, 1.85),
            ca.WordSpan("azi", 2.05, 3.9),
        ]
        out = ca.align_words(
            t,
            "a.wav",
            backend_factory=make_factory(spans, record),
            audio_loader=make_loader(),
            models_present=lambda s, m: True,
        )
        assert out["segments"][0]["words"][0]["start"] == 0.05
        assert out["segments"][1]["words"][0]["end"] == 3.9
        # tokens passed to the backend are the flattened transcript words
        assert record["tokens"] == ["salut", "lume", "azi"]
        # language defaults to the transcript language
        assert record["language"] == "ro"

    def test_progress_and_cancel_seam_invoked(self):
        events: list[tuple[float, str]] = []
        t = transcript_with_words()
        ca.align_words(
            t,
            "a.wav",
            backend_factory=make_factory([ca.WordSpan("salut", 0.0, 1.0)] * 3),
            audio_loader=make_loader(),
            models_present=lambda s, m: True,
            on_progress=lambda p, m: events.append((p, m)),
            should_cancel=lambda: False,
        )
        assert any(m == "done" for _, m in events)
        assert events[-1][0] == 100.0

    def test_explicit_language_override(self):
        record: dict[str, Any] = {}
        ca.align_words(
            transcript_with_words(),
            "a.wav",
            backend_factory=make_factory([ca.WordSpan("x", 0.0, 1.0)] * 3, record),
            audio_loader=make_loader(),
            models_present=lambda s, m: True,
            language="eng",
        )
        assert record["language"] == "eng"

    def test_mit_model_override_selects_mit_asset(self):
        # models_present receives the RESOLVED model id; assert the override flows.
        seen: dict[str, Any] = {}

        def present(settings: dict[str, Any], model_id: str) -> bool:
            seen["model_id"] = model_id
            return True

        ca.align_words(
            transcript_with_words(),
            "a.wav",
            backend_factory=make_factory([ca.WordSpan("x", 0.0, 1.0)] * 3),
            audio_loader=make_loader(),
            models_present=present,
            model_id="wav2vec2-960h-lv60",
        )
        assert seen["model_id"] == ca.MIT_MODEL_IDS["wav2vec2-960h-lv60"]

    def test_duration_from_samples_when_no_duration_sec(self):
        # transcript without durationSec -> duration derived from samples/sr.
        t = transcript_with_words()
        del t["durationSec"]
        out = ca.align_words(
            t,
            "a.wav",
            # span end past the sample-derived duration gets clamped.
            backend_factory=make_factory(
                [ca.WordSpan("salut", 0.0, 99.0), ca.WordSpan("lume", 0.0, 0.0001), ca.WordSpan("azi", 0.0, 0.0001)]
            ),
            audio_loader=make_loader((0.1, 0.2), sr=4),  # 2 samples / 4 Hz = 0.5s
            models_present=lambda s, m: True,
        )
        assert out["segments"][0]["words"][0]["end"] == 0.5


# --------------------------------------------------------------------------- #
# runner: degrade paths (never raise, never drop text)
# --------------------------------------------------------------------------- #
class TestAlignWordsDegrade:
    def test_empty_transcript_returned_unchanged(self):
        t = {"language": "x", "segments": []}
        out = ca.align_words(t, "a.wav", models_present=lambda s, m: True, audio_loader=make_loader())
        assert out == t
        assert out is not t  # immutable copy

    def test_offline_and_model_missing_returns_unchanged(self):
        t = transcript_with_words()
        out = ca.align_words(
            t,
            "a.wav",
            settings={"offline": True},
            models_present=lambda s, m: False,
            audio_loader=make_loader(),
            backend_factory=make_factory([ca.WordSpan("x", 0.0, 1.0)] * 3),
        )
        # unchanged: original word timings preserved
        assert out["segments"][0]["words"][0]["start"] == 0.0

    def test_offline_but_model_present_runs(self):
        t = transcript_with_words()
        out = ca.align_words(
            t,
            "a.wav",
            settings={"offline": True},
            models_present=lambda s, m: True,
            audio_loader=make_loader(),
            backend_factory=make_factory(
                [ca.WordSpan("salut", 0.3, 0.7), ca.WordSpan("lume", 0.7, 1.1), ca.WordSpan("azi", 2.2, 3.3)]
            ),
        )
        assert out["segments"][0]["words"][0]["start"] == 0.3

    def test_online_and_model_missing_still_runs(self):
        # online + missing -> NOT degraded (a real factory would download).
        t = transcript_with_words()
        out = ca.align_words(
            t,
            "a.wav",
            settings={"offline": False},
            models_present=lambda s, m: False,
            audio_loader=make_loader(),
            backend_factory=make_factory(
                [ca.WordSpan("salut", 0.4, 0.6), ca.WordSpan("lume", 0.6, 1.0), ca.WordSpan("azi", 2.0, 3.0)]
            ),
        )
        assert out["segments"][0]["words"][0]["start"] == 0.4

    def test_cancelled_before_alignment_returns_unchanged(self):
        t = transcript_with_words()
        out = ca.align_words(
            t,
            "a.wav",
            models_present=lambda s, m: True,
            audio_loader=make_loader(),
            backend_factory=make_factory([ca.WordSpan("x", 0.0, 1.0)] * 3),
            should_cancel=lambda: True,
        )
        assert out["segments"][0]["words"][0]["start"] == 0.0

    def test_empty_audio_returns_unchanged(self):
        t = transcript_with_words()
        out = ca.align_words(
            t,
            "a.wav",
            models_present=lambda s, m: True,
            audio_loader=make_loader(samples=()),
            backend_factory=make_factory([ca.WordSpan("x", 0.0, 1.0)] * 3),
        )
        assert out["segments"][0]["words"][0]["start"] == 0.0

    def test_backend_failure_returns_unchanged(self):
        t = transcript_with_words()
        out = ca.align_words(
            t,
            "a.wav",
            models_present=lambda s, m: True,
            audio_loader=make_loader(),
            backend_factory=make_factory([], raises=RuntimeError("boom")),
        )
        assert out["segments"][0]["words"][0]["start"] == 0.0
        assert out is not t

    # -- F3b: a backend/decode failure surfaces a one-line notice -------------
    def test_backend_failure_surfaces_skip_notice(self):
        events: list[tuple[float, str]] = []
        ca.align_words(
            transcript_with_words(),
            "a.wav",
            models_present=lambda s, m: True,
            audio_loader=make_loader(),
            backend_factory=make_factory([], raises=RuntimeError("boom")),
            on_progress=lambda p, m: events.append((p, m)),
        )
        assert any(msg == ca.ALIGN_SKIPPED_NOTICE for _, msg in events)

    def test_audio_decode_failure_surfaces_notice_and_returns_unchanged(self):
        events: list[tuple[float, str]] = []

        def boom_loader(_path: str) -> Any:
            raise ca.AudioDecodeError("ffmpeg audio decode failed (exit 1): bad input")

        out = ca.align_words(
            transcript_with_words(),
            "a.wav",
            models_present=lambda s, m: True,
            audio_loader=boom_loader,
            backend_factory=make_factory([ca.WordSpan("x", 0.0, 1.0)] * 3),
            on_progress=lambda p, m: events.append((p, m)),
        )
        # text + original timings preserved (never dropped)
        assert out["segments"][0]["words"][0]["start"] == 0.0
        assert any(msg == ca.ALIGN_SKIPPED_NOTICE for _, msg in events)

    def test_empty_transcript_emits_no_skip_notice(self):
        # a GENUINELY empty transcript is not a failure -> no alarming notice.
        events: list[tuple[float, str]] = []
        ca.align_words(
            {"language": "x", "segments": []},
            "a.wav",
            models_present=lambda s, m: True,
            audio_loader=make_loader(),
            on_progress=lambda p, m: events.append((p, m)),
        )
        assert all(msg != ca.ALIGN_SKIPPED_NOTICE for _, msg in events)


# --------------------------------------------------------------------------- #
# F3b: ffmpeg returncode check in the default audio decoder (pure helper)
# --------------------------------------------------------------------------- #
class TestDecodePcmOrRaise:
    def test_nonzero_returncode_raises_with_stderr_tail(self):
        with pytest.raises(ca.AudioDecodeError) as ei:
            ca._decode_pcm_or_raise(1, b"", b"line one\nffmpeg: Invalid data found", target_sr=16000)
        message = str(ei.value)
        assert "exit 1" in message
        assert "Invalid data found" in message  # stderr tail surfaced

    def test_success_returns_float64_samples(self):
        raw = np.asarray([0.25, -0.5], dtype=np.float32).tobytes()
        samples, sr = ca._decode_pcm_or_raise(0, raw, b"", target_sr=16000)
        assert sr == 16000
        assert samples.dtype == np.float64
        assert samples.shape[0] == 2
        assert samples[0] == pytest.approx(0.25)

    def test_success_with_empty_stdout_yields_empty_array(self):
        samples, sr = ca._decode_pcm_or_raise(0, b"", b"", target_sr=8000)
        assert sr == 8000
        assert samples.shape[0] == 0


# --------------------------------------------------------------------------- #
# defaults: factory / loader / probe wiring (no heavy import at module load)
# --------------------------------------------------------------------------- #
class TestDefaults:
    def test_default_factory_is_lazy_callable(self):
        # The default factory is wired but NOT invoked here (it imports torch).
        assert callable(ca._default_backend_factory)

    def test_align_uses_default_probe_when_none(self, monkeypatch):
        # With no models_present injected, the default probe runs. Force it to
        # report "missing" + offline so we hit the degrade WITHOUT a backend.
        monkeypatch.setattr(ca, "default_models_present", lambda s, m: False)
        t = transcript_with_words()
        out = ca.align_words(
            t,
            "a.wav",
            settings={"offline": True},
            audio_loader=make_loader(),
        )
        assert out["segments"][0]["words"][0]["start"] == 0.0


# --------------------------------------------------------------------------- #
# asset registration
# --------------------------------------------------------------------------- #
class TestAssetRegistration:
    def test_registers_both_models(self):
        manifest.registry_restore({})
        ca.register_ctc_align_assets()
        default = manifest.get_asset(ca.ASSET_NAME)
        mit = manifest.get_asset(ca.MIT_ASSET_NAME)
        assert default is not None and default.hf_repo == ca.DEFAULT_MODEL_ID
        assert mit is not None and mit.hf_repo == ca.MIT_MODEL_IDS["wav2vec2-960h-lv60"]
        assert default.installer == "hf"

    def test_idempotent(self):
        manifest.registry_restore({})
        ca.register_ctc_align_assets()
        ca.register_ctc_align_assets()  # no raise on identical re-register
        assert manifest.get_asset(ca.ASSET_NAME) is not None

    def test_registers_ro_model(self):
        manifest.registry_restore({})
        ca.register_ctc_align_assets()
        ro = manifest.get_asset(ca.RO_ASSET_NAME)
        assert ro is not None
        assert ro.hf_repo == ca.RO_MODEL_IDS["romanian-wav2vec2"]
        assert ro.installer == "hf"
        # F3c: the snapshot revision must be a pinned 40-hex commit hash.
        assert len(ro.hf_revision) == 40
