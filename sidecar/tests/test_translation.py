"""Unit tests for media_studio.models.translation (T3 tiered translation).

Everything heavy is mocked: the model runner is a fake (or a real ModelRunner
driven by a fake popen — no process), providers are fakes (no network), and no
GGUF file is ever touched. Covers: routing table -> correct tier per language,
the fallback chain on tier failure, the SLOW labelling of tier2, cooperative
cancellation, the translate_track / line_translator seams, GGUF resolution from
settings, and the U4 manifest registration of the chosen MT GGUFs.
"""

from __future__ import annotations

import re
from typing import Any

import pytest
from media_studio.assets import manifest
from media_studio.models.provider import (
    CloudProvider,
    LocalServerProvider,
    ProviderError,
)
from media_studio.models.runner import ModelRunner
from media_studio.models.translation import (
    CONTEXT_MAX_CHARS,
    DEFAULT_TIER,
    MT_WEIGHT_LICENCES,
    PERMISSIVE_LICENCES,
    ROUTING_TABLE,
    SENTENCE_GROUP_MAX_CHARS,
    SENTENCE_GROUP_MAX_GAP_SEC,
    TIER1_ASSET_NAME,
    TIER1_GGUF_NAME,
    TIER2_ASSET_NAME,
    TIER2_GGUF_NAME,
    TIER2_GPU_LAYERS,
    TIER_HOSTED,
    TIER_LOCAL,
    TIER_LOCAL_HEAVY,
    TIERS,
    TieredTranslator,
    TierUnavailableError,
    TranslationError,
    build_messages,
    fallback_chain,
    get_translator,
    group_cues_for_translation,
    group_text,
    normalize_lang,
    route,
    route_pair,
)


# --------------------------------------------------------------------------- #
# fakes
# --------------------------------------------------------------------------- #
class FakeRunner:
    """Records start_server calls; never spawns anything."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.current_model_path: str | None = None

    def start_server(self, *, gguf_path=None, gpu_layers=None, extra_args=None):
        self.calls.append({"gguf_path": gguf_path, "gpu_layers": gpu_layers})
        self.current_model_path = gguf_path
        return object()


class FakeProvider:
    """A chat seam that records calls and can fail on demand.

    ``fail_at`` (0-based call ordinal) makes that chat call raise; ``fail_all``
    makes every call raise — both with ProviderError, the real seam's error.
    """

    def __init__(self, *, prefix: str = "XX", fail_all: bool = False, fail_at: int | None = None):
        self.prefix = prefix
        self.fail_all = fail_all
        self.fail_at = fail_at
        self.chats: list[list[dict[str, str]]] = []

    def chat(self, messages, **kwargs: Any) -> str:
        ordinal = len(self.chats)
        self.chats.append([dict(m) for m in messages])
        if self.fail_all or (self.fail_at is not None and ordinal == self.fail_at):
            raise ProviderError("provider down")
        return f"{self.prefix}:{messages[-1]['content']}"


def make_factory(providers: list[Any]):
    """A provider factory that returns the given providers in order."""
    queue = list(providers)
    built: list[Any] = []

    def factory():
        provider = queue.pop(0)
        built.append(provider)
        return provider

    factory.built = built  # type: ignore[attr-defined]
    return factory


def cues2() -> list[dict[str, Any]]:
    """Two cues that are two INDEPENDENT sentences.

    The trailing full stops are load-bearing: translation is sentence-scoped (T1),
    so a cue that ends a sentence is its own translation unit and these two cues
    therefore still map 1:1 onto two provider calls. ``sentence_fragments()`` is the
    complementary fixture for the mid-sentence-split case.
    """
    return [
        {"index": 1, "start": 0.0, "end": 1.5, "text": "Hello there."},
        {"index": 2, "start": 1.5, "end": 3.0, "text": "Good night."},
    ]


SETTINGS = {"modelsDir": "D:/models"}
TIER1_PATH = f"D:/models/{TIER1_GGUF_NAME}"
TIER2_PATH = f"D:/models/{TIER2_GGUF_NAME}"


def make_translator(
    *,
    runner: Any | None = None,
    settings: dict[str, Any] | None = None,
    local: list[Any] | None = None,
    hosted: list[Any] | None = None,
    routing: dict[str, str] | None = None,
) -> TieredTranslator:
    return TieredTranslator(
        runner=runner,
        settings=SETTINGS if settings is None else settings,
        local_provider_factory=make_factory(local) if local is not None else None,
        hosted_provider_factory=make_factory(hosted) if hosted is not None else None,
        routing=routing,
    )


# --------------------------------------------------------------------------- #
# normalize_lang / route / fallback_chain (pure routing logic)
# --------------------------------------------------------------------------- #
def test_normalize_lang_strips_region_and_case():
    assert normalize_lang("pt-BR") == "pt"
    assert normalize_lang("PT_br") == "pt"
    assert normalize_lang("EN") == "en"
    assert normalize_lang("zh_Hant") == "zh"
    assert normalize_lang("  es  ") == "es"


def test_normalize_lang_empty_raises():
    with pytest.raises(ValueError):
        normalize_lang("")
    with pytest.raises(ValueError):
        normalize_lang("   ")


def test_route_high_resource_to_tier1():
    for lang in ("es", "de", "ja", "zh", "pt-BR", "EN"):
        assert route(lang) == TIER_LOCAL, lang


def test_route_low_resource_to_tier2():
    for lang in ("sw", "ta", "bn", "is", "ta-IN"):
        assert route(lang) == TIER_LOCAL_HEAVY, lang


def test_route_uncovered_to_tier3():
    for lang in ("yo", "yue", "bo", "und", "xx"):
        assert route(lang) == TIER_HOSTED, lang
    assert DEFAULT_TIER == TIER_HOSTED


def test_route_custom_table_wins():
    assert route("es", {"es": TIER_HOSTED}) == TIER_HOSTED


def test_routing_table_values_are_known_tiers():
    assert set(ROUTING_TABLE.values()) <= set(TIERS)


def test_fallback_chain_orders():
    assert fallback_chain("es") == [TIER_LOCAL, TIER_LOCAL_HEAVY, TIER_HOSTED]
    assert fallback_chain("sw") == [TIER_LOCAL_HEAVY, TIER_LOCAL, TIER_HOSTED]
    assert fallback_chain("yo") == [TIER_HOSTED, TIER_LOCAL, TIER_LOCAL_HEAVY]


def test_translator_route_and_chain_use_instance_routing():
    t = make_translator(routing={"es": TIER_HOSTED})
    assert t.route("es") == TIER_HOSTED
    assert t.chain_for("es")[0] == TIER_HOSTED


# --------------------------------------------------------------------------- #
# build_messages (prompt build)
# --------------------------------------------------------------------------- #
def test_build_messages_shape_and_target():
    msgs = build_messages("hello", "fr")
    assert [m["role"] for m in msgs] == ["system", "user"]
    assert "fr" in msgs[0]["content"]
    assert "ONLY the translation" in msgs[0]["content"]
    assert msgs[1]["content"] == "hello"


def test_build_messages_includes_source_lang_when_given():
    msgs = build_messages("hello", "fr", "en")
    assert "en" in msgs[0]["content"]
    no_src = build_messages("hello", "fr")
    assert "source language" not in no_src[0]["content"]


# --------------------------------------------------------------------------- #
# tier1: routed local translation
# --------------------------------------------------------------------------- #
def test_tier1_translates_and_starts_server_with_tier1_gguf():
    runner = FakeRunner()
    provider = FakeProvider()
    t = make_translator(runner=runner, local=[provider])
    out = t.translate(cues2(), "es")
    assert [c["text"] for c in out] == ["XX:Hello there.", "XX:Good night."]
    assert runner.calls == [{"gguf_path": TIER1_PATH, "gpu_layers": None}]


def test_tier1_preserves_timings_and_indices_immutably():
    runner = FakeRunner()
    src = cues2()
    t = make_translator(runner=runner, local=[FakeProvider()])
    out = t.translate(src, "de")
    assert [(c["index"], c["start"], c["end"]) for c in out] == [
        (1, 0.0, 1.5),
        (2, 1.5, 3.0),
    ]
    assert src[0]["text"] == "Hello there."  # input not mutated
    assert out[0] is not src[0]


def test_blank_cue_skips_provider_call():
    runner = FakeRunner()
    provider = FakeProvider()
    cues = [
        {"index": 1, "start": 0.0, "end": 1.0, "text": "   "},
        {"index": 2, "start": 1.0, "end": 2.0, "text": "hi"},
    ]
    t = make_translator(runner=runner, local=[provider])
    out = t.translate(cues, "es")
    assert out[0]["text"] == "   "  # passed through untranslated
    assert len(provider.chats) == 1  # only the non-blank cue hit the provider


def test_empty_cues_short_circuits_without_touching_runner():
    runner = FakeRunner()
    t = make_translator(runner=runner, local=[FakeProvider()])
    assert t.translate([], "es") == []
    assert runner.calls == []


def test_progress_emitted_with_pct_and_tier_label():
    runner = FakeRunner()
    seen: list[Any] = []
    t = make_translator(runner=runner, local=[FakeProvider()])
    t.translate(cues2(), "es", progress=lambda pct, msg: seen.append((pct, msg)))
    assert [p for p, _m in seen] == [50, 100]
    assert all("tier1" in m for _p, m in seen)


# --------------------------------------------------------------------------- #
# tier2: routed heavy local (offload + SLOW label)
# --------------------------------------------------------------------------- #
def test_tier2_routed_lang_uses_offload_and_slow_label():
    runner = FakeRunner()
    seen: list[str] = []
    t = make_translator(runner=runner, local=[FakeProvider()])
    out = t.translate(cues2(), "sw", progress=lambda _p, m: seen.append(m))
    assert len(out) == 2
    assert runner.calls == [{"gguf_path": TIER2_PATH, "gpu_layers": TIER2_GPU_LAYERS}]
    assert all("SLOW" in m for m in seen)


# --------------------------------------------------------------------------- #
# fallback chain on tier failure
# --------------------------------------------------------------------------- #
def test_tier1_failure_falls_back_to_tier2_full_batch():
    """A mid-batch tier1 failure discards the partial output: tier2 redoes ALL."""
    runner = FakeRunner()
    failing = FakeProvider(fail_at=1)  # dies on the SECOND cue
    working = FakeProvider(prefix="T2")
    t = make_translator(runner=runner, local=[failing, working])
    out = t.translate(cues2(), "es")
    # no mixed-tier patchwork: every cue came from the tier2 provider
    assert [c["text"] for c in out] == ["T2:Hello there.", "T2:Good night."]
    assert len(working.chats) == 2
    # server was started for tier1 first, then switched to tier2 with offload
    assert runner.calls[0] == {"gguf_path": TIER1_PATH, "gpu_layers": None}
    assert runner.calls[1] == {"gguf_path": TIER2_PATH, "gpu_layers": TIER2_GPU_LAYERS}


def test_local_failures_fall_back_to_hosted():
    runner = FakeRunner()
    hosted = FakeProvider(prefix="CLOUD")
    t = make_translator(
        runner=runner,
        local=[FakeProvider(fail_all=True), FakeProvider(fail_all=True)],
        hosted=[hosted],
    )
    out = t.translate(cues2(), "es")
    assert [c["text"] for c in out] == ["CLOUD:Hello there.", "CLOUD:Good night."]


def test_all_tiers_fail_raises_translation_error_with_reasons():
    runner = FakeRunner()
    t = make_translator(
        runner=runner,
        local=[FakeProvider(fail_all=True), FakeProvider(fail_all=True)],
        hosted=[FakeProvider(fail_all=True)],
    )
    with pytest.raises(TranslationError) as exc_info:
        t.translate(cues2(), "es")
    msg = str(exc_info.value)
    assert "tier1" in msg and "tier2" in msg and "tier3" in msg


def test_unavailable_local_tiers_skip_to_hosted():
    # No runner at all -> both local tiers unavailable -> hosted serves.
    hosted = FakeProvider(prefix="CLOUD")
    t = make_translator(runner=None, hosted=[hosted])
    out = t.translate(cues2(), "es")
    assert out[0]["text"] == "CLOUD:Hello there."


def test_nothing_available_raises():
    t = make_translator(runner=None, settings={})  # no runner, no key, no factory
    with pytest.raises(TranslationError):
        t.translate(cues2(), "es")


def test_tier3_routed_lang_never_touches_the_runner():
    runner = FakeRunner()
    t = make_translator(runner=runner, hosted=[FakeProvider(prefix="CLOUD")])
    out = t.translate(cues2(), "yo")
    assert out[0]["text"] == "CLOUD:Hello there."
    assert runner.calls == []


def test_hosted_unavailable_falls_back_to_local_for_tier3_lang():
    runner = FakeRunner()
    t = make_translator(runner=runner, local=[FakeProvider()])  # no hosted/no key
    out = t.translate(cues2(), "yo")
    assert out[0]["text"] == "XX:Hello there."
    assert runner.calls[0]["gguf_path"] == TIER1_PATH


def test_hosted_tier_unavailable_without_cloud_key():
    # Without a factory, tier3 builds a CloudProvider from cloudApiKey; with an
    # empty key it is unavailable (the real CloudProvider construction is
    # covered by test_provider.py).
    t = TieredTranslator(runner=None, settings={"cloudApiKey": ""})
    with pytest.raises(TranslationError):
        t.translate(cues2(), "yo")


def test_hosted_factory_returning_none_is_unavailable():
    t = TieredTranslator(runner=None, settings={}, hosted_provider_factory=lambda: None)
    with pytest.raises(TranslationError) as exc_info:
        t.translate(cues2(), "yo")
    assert "tier3" in str(exc_info.value)


# --------------------------------------------------------------------------- #
# sentence-level translation — the T1 keystone
#   `docs/plans/v1.5/captions-translation-audit-2026-08.md` §3.1 + §3.2 measured the
#   mechanical cause of the owner's "bad translations": cues are segmented for READING
#   SPEED, so one sentence spans several cues, and the translator was handed each
#   fragment alone. These tests pin the fixed shape: one call per SENTENCE, with the
#   neighbouring sentences supplied as context.
# --------------------------------------------------------------------------- #
def sentence_fragments() -> list[dict[str, Any]]:
    """Three cues that are ONE sentence split for reading speed (the defect shape).

    Only the LAST cue carries sentence-final punctuation, so a per-cue translator
    sees three context-free fragments and has to guess the clause each belongs to.
    """
    return [
        {"index": 1, "start": 0.0, "end": 1.2, "text": "When she finally opened"},
        {"index": 2, "start": 1.2, "end": 2.4, "text": "the letter her brother"},
        {"index": 3, "start": 2.4, "end": 3.6, "text": "had written, she cried."},
    ]


ONE_SENTENCE = "When she finally opened the letter her brother had written, she cried."


class TestGroupCuesForTranslation:
    def test_fragments_of_one_sentence_form_one_group(self):
        groups = group_cues_for_translation(sentence_fragments())
        assert [len(g) for g in groups] == [3]
        assert group_text(groups[0]) == ONE_SENTENCE

    def test_each_sentence_terminates_its_group(self):
        cues = [
            {"index": 1, "start": 0.0, "end": 1.0, "text": "One."},
            {"index": 2, "start": 1.0, "end": 2.0, "text": "Two"},
            {"index": 3, "start": 2.0, "end": 3.0, "text": "and a half!"},
        ]
        assert [[c["index"] for c in g] for g in group_cues_for_translation(cues)] == [[1], [2, 3]]

    def test_a_blank_cue_is_never_merged_into_a_group(self):
        cues = [
            {"index": 1, "start": 0.0, "end": 1.0, "text": "before"},
            {"index": 2, "start": 1.0, "end": 2.0, "text": "   "},
            {"index": 3, "start": 2.0, "end": 3.0, "text": "after"},
        ]
        assert [[c["index"] for c in g] for g in group_cues_for_translation(cues)] == [[1], [2], [3]]

    def test_a_speaker_change_closes_the_group(self):
        """Two speakers' fragments are never ONE sentence, punctuation or not."""
        cues = [
            {"index": 1, "start": 0.0, "end": 1.0, "text": "so I told him", "speaker": "SPEAKER_00"},
            {"index": 2, "start": 1.0, "end": 2.0, "text": "and what did he say", "speaker": "SPEAKER_01"},
        ]
        assert [[c["index"] for c in g] for g in group_cues_for_translation(cues)] == [[1], [2]]

    def test_absent_speaker_on_both_cues_is_not_a_change(self):
        cues = [
            {"index": 1, "start": 0.0, "end": 1.0, "text": "so I told"},
            {"index": 2, "start": 1.0, "end": 2.0, "text": "him the truth"},
        ]
        assert [len(g) for g in group_cues_for_translation(cues)] == [2]

    def test_a_long_pause_closes_the_group(self):
        cues = [
            {"index": 1, "start": 0.0, "end": 1.0, "text": "so I told him"},
            {"index": 2, "start": 9.0, "end": 10.0, "text": "anyway where were we"},
        ]
        assert [[c["index"] for c in g] for g in group_cues_for_translation(cues)] == [[1], [2]]

    def test_the_min_gap_between_cues_of_one_sentence_does_not_close_the_group(self):
        # `caption_polish.enforce_min_gap` leaves a 2-frame (~0.067s at 30fps) hole
        # between consecutive cues; that must NOT read as a pause.
        cues = [
            {"index": 1, "start": 0.0, "end": 0.933, "text": "so I told"},
            {"index": 2, "start": 1.0, "end": 2.0, "text": "him the truth"},
        ]
        assert [len(g) for g in group_cues_for_translation(cues)] == [2]

    def test_the_pause_threshold_is_configurable(self):
        cues = [
            {"index": 1, "start": 0.0, "end": 1.0, "text": "so I told him"},
            {"index": 2, "start": 2.0, "end": 3.0, "text": "the whole truth"},
        ]
        assert [len(g) for g in group_cues_for_translation(cues, max_gap_sec=0.5)] == [1, 1]
        assert [len(g) for g in group_cues_for_translation(cues, max_gap_sec=5.0)] == [2]
        assert SENTENCE_GROUP_MAX_GAP_SEC > 0.1

    def test_unparseable_timings_are_not_evidence_of_a_pause(self):
        """A malformed timing must not invent a boundary, and must not raise.

        Cues reach here from a persisted track that a user can hand-edit (SRT import,
        the cue editor), so a non-numeric `start`/`end` is reachable input rather than
        a theoretical one. Splitting on it would silently degrade translation quality
        for the whole file; raising would fail the render outright. Neither is right --
        an unreadable timing is simply no evidence, so grouping falls through to the
        punctuation and max_chars rules.
        """
        cues = [
            {"index": 1, "start": 0.0, "end": "not-a-number", "text": "so I told"},
            {"index": 2, "start": 1.0, "end": 2.0, "text": "him the truth"},
        ]
        assert [len(g) for g in group_cues_for_translation(cues)] == [2]

    def test_max_chars_bounds_the_group(self):
        cues = [{"index": i, "start": float(i), "end": i + 1.0, "text": "abcd"} for i in range(1, 6)]
        groups = group_cues_for_translation(cues, max_chars=10)
        # "abcd abcd" is 9 chars; a third would be 14 > 10.
        assert [len(g) for g in groups] == [2, 2, 1]

    def test_empty_input(self):
        assert group_cues_for_translation([]) == []

    def test_group_text_flattens_all_whitespace(self):
        group = [{"text": "a\nb"}, {"text": "  c   d "}]
        assert group_text(group) == "a b c d"

    def test_default_bound_is_the_module_constant(self):
        assert SENTENCE_GROUP_MAX_CHARS >= 100


class TestRoutePair:
    def test_no_source_is_target_only_routing(self):
        assert route_pair(None, "es") == TIER_LOCAL
        assert route_pair("", "sw") == TIER_LOCAL_HEAVY
        assert route_pair("   ", "yo") == TIER_HOSTED

    def test_low_resource_source_escalates_a_tier1_target(self):
        # ro->en used to route tier1 purely because `en` is tier1 (audit §3.3).
        assert route_pair("sw", "en") == TIER_LOCAL_HEAVY
        assert route_pair("en", "en") == TIER_LOCAL

    def test_an_uncovered_source_escalates_only_to_the_heavy_LOCAL_tier(self):
        # Privacy posture: a low-resource SOURCE must never turn a locally-servable
        # translation into a hosted (network) one — tier3 stays a TARGET decision.
        assert route_pair("yo", "en") == TIER_LOCAL_HEAVY

    def test_a_hosted_target_stays_hosted(self):
        assert route_pair("en", "yo") == TIER_HOSTED

    def test_a_lighter_source_never_downgrades_the_target(self):
        assert route_pair("en", "sw") == TIER_LOCAL_HEAVY

    def test_custom_table_is_honoured(self):
        assert route_pair("es", "en", {"es": TIER_LOCAL_HEAVY, "en": TIER_LOCAL}) == TIER_LOCAL_HEAVY

    def test_unknown_tier_from_a_custom_table_cannot_escalate(self):
        assert route_pair("es", "en", {"es": "tierX", "en": TIER_LOCAL}) == TIER_LOCAL

    def test_fallback_chain_uses_pair_routing_when_a_source_is_given(self):
        assert fallback_chain("en") == [TIER_LOCAL, TIER_LOCAL_HEAVY, TIER_HOSTED]
        assert fallback_chain("en", source_lang="sw") == [TIER_LOCAL_HEAVY, TIER_LOCAL, TIER_HOSTED]

    def test_translator_chain_for_threads_the_source(self):
        t = make_translator()
        assert t.chain_for("en", source_lang="sw")[0] == TIER_LOCAL_HEAVY


def test_translate_routes_on_the_language_pair():
    runner = FakeRunner()
    t = make_translator(runner=runner, local=[FakeProvider()])
    t.translate(cues2(), "en", source_lang="sw")
    assert runner.calls == [{"gguf_path": TIER2_PATH, "gpu_layers": TIER2_GPU_LAYERS}]


def test_build_messages_carries_neighbouring_context_in_the_system_message():
    msgs = build_messages("middle", "fr", "en", context_before="left", context_after="right")
    system = msgs[0]["content"]
    assert 'Preceding text: "left"' in system
    assert 'Following text: "right"' in system
    assert "CONTEXT ONLY" in system
    assert msgs[1]["content"] == "middle"


def test_build_messages_without_context_is_unchanged():
    system = build_messages("solo", "fr")[0]["content"]
    assert "Preceding text:" not in system
    assert "Following text:" not in system
    assert "CONTEXT ONLY" not in system


def test_build_messages_clips_context_toward_the_translated_text():
    before = " ".join(f"b{i}" for i in range(400))
    after = " ".join(f"a{i}" for i in range(400))
    system = build_messages("x", "fr", context_before=before, context_after=after)[0]["content"]
    assert len(system) < 2 * CONTEXT_MAX_CHARS + 600
    # `before` keeps its TAIL (the words nearest the cue), `after` keeps its HEAD.
    assert "b399" in system and "b0 " not in system
    assert "a0 " in system and "a399" not in system


def test_build_messages_keeps_short_context_whole():
    system = build_messages("x", "fr", context_before="short one", context_after="short two")[0]["content"]
    assert 'Preceding text: "short one"' in system
    assert 'Following text: "short two"' in system


def test_sentence_fragments_translate_in_one_context_bearing_call():
    provider = FakeProvider()
    t = make_translator(runner=FakeRunner(), local=[provider])
    t.translate(sentence_fragments(), "de")
    assert len(provider.chats) == 1, "the cues were still translated in isolation"
    assert provider.chats[0][-1]["content"] == ONE_SENTENCE


def test_grouped_translation_preserves_every_cue_timing_exactly():
    """Timing fidelity is the HARD contract: re-segmentation may rewrite TEXT only."""
    src = sentence_fragments()
    t = make_translator(runner=FakeRunner(), local=[FakeProvider(prefix="DE")])
    out = t.translate(src, "de")
    assert [(c["index"], c["start"], c["end"]) for c in out] == [(c["index"], c["start"], c["end"]) for c in src]


def test_redistribution_loses_no_characters_of_the_translation():
    """Every non-whitespace character of the model's reply lands in exactly one cue."""
    provider = FakeProvider(prefix="DE")
    t = make_translator(runner=FakeRunner(), local=[provider])
    out = t.translate(sentence_fragments(), "de")
    reply = f"DE:{ONE_SENTENCE}"
    assert "".join("".join(str(c["text"]).split()) for c in out) == "".join(reply.split())


def test_every_cue_of_a_group_receives_text():
    provider = FakeProvider(prefix="DE")
    t = make_translator(runner=FakeRunner(), local=[provider])
    out = t.translate(sentence_fragments(), "de")
    assert len(out) == 3
    assert all(str(c["text"]).strip() for c in out)


def test_polished_hard_wraps_are_flattened_before_the_model_sees_them():
    """``caption_polish.wrap_two_lines`` puts a hard newline INSIDE the cue text.

    Because ``captionPolish`` runs at GENERATE time (``handlers/media_ops.py``
    ``subtitles_generate``) and translation runs later over the persisted track, the
    model was being fed embedded line breaks — the audit's suspected fourth root
    cause, CONFIRMED by that call order.
    """
    cues = [
        {"index": 1, "start": 0.0, "end": 1.0, "text": "the quick brown\nfox jumps"},
        {"index": 2, "start": 1.0, "end": 2.0, "text": "over the lazy dog."},
    ]
    provider = FakeProvider()
    t = make_translator(runner=FakeRunner(), local=[provider])
    t.translate(cues, "fr")
    assert len(provider.chats) == 1
    assert provider.chats[0][-1]["content"] == "the quick brown fox jumps over the lazy dog."


def test_neighbouring_sentences_are_supplied_as_context():
    provider = FakeProvider()
    cues = [
        {"index": 1, "start": 0.0, "end": 1.0, "text": "She left."},
        {"index": 2, "start": 1.0, "end": 2.0, "text": "He stayed."},
        {"index": 3, "start": 2.0, "end": 3.0, "text": "Nobody spoke."},
    ]
    t = make_translator(runner=FakeRunner(), local=[provider])
    t.translate(cues, "ro")
    assert len(provider.chats) == 3
    # context rides the SYSTEM message; the USER message stays the bare sentence so
    # the "reply with ONLY the translation" instruction is never diluted.
    first, middle, last = (chat[0]["content"] for chat in provider.chats)
    assert [chat[-1]["content"] for chat in provider.chats] == [
        "She left.",
        "He stayed.",
        "Nobody spoke.",
    ]
    assert "Preceding text:" not in first and "He stayed." in first
    assert "She left." in middle and "Nobody spoke." in middle
    assert "He stayed." in last and "Following text:" not in last


# --------------------------------------------------------------------------- #
# cooperative cancellation (the job seam)
# --------------------------------------------------------------------------- #
def test_cancelled_mid_batch_returns_partial():
    runner = FakeRunner()
    provider = FakeProvider()
    flags = iter([False, True])  # allow cue 1, cancel before cue 2
    t = make_translator(runner=runner, local=[provider])
    out = t.translate(cues2(), "es", cancelled=lambda: next(flags))
    assert len(out) == 1
    assert len(provider.chats) == 1


def test_cancelled_before_start_returns_empty():
    runner = FakeRunner()
    provider = FakeProvider()
    t = make_translator(runner=runner, local=[provider])
    out = t.translate(cues2(), "es", cancelled=lambda: True)
    assert out == []
    assert provider.chats == []


# --------------------------------------------------------------------------- #
# translate_track (the subtitles.translate job body)
# --------------------------------------------------------------------------- #
def test_translate_track_returns_new_track_with_lang():
    runner = FakeRunner()
    track = {
        "id": "trk1",
        "lang": "en",
        "name": "English",
        "format": "srt",
        "kind": "soft",
        "cues": cues2(),
    }
    t = make_translator(runner=runner, local=[FakeProvider()])
    out = t.translate_track(track, "es")
    assert out["lang"] == "es"
    assert out["id"] == "trk1"
    assert [c["text"] for c in out["cues"]] == ["XX:Hello there.", "XX:Good night."]
    assert track["lang"] == "en"  # input not mutated
    assert track["cues"][0]["text"] == "Hello there."


# --------------------------------------------------------------------------- #
# line_translator (the features.subtitles LineTranslator seam)
# --------------------------------------------------------------------------- #
def test_line_translator_translates_and_binds_tier_once():
    runner = FakeRunner()
    provider = FakeProvider()
    factory = make_factory([provider])
    t = TieredTranslator(runner=runner, settings=SETTINGS, local_provider_factory=factory)
    line = t.line_translator("es")
    assert line("hello") == "XX:hello"
    assert line("bye") == "XX:bye"
    assert len(factory.built) == 1  # provider bound once, reused per line
    assert runner.calls == [{"gguf_path": TIER1_PATH, "gpu_layers": None}]


def test_line_translator_blank_passthrough():
    t = make_translator(runner=FakeRunner(), local=[FakeProvider()])
    line = t.line_translator("es")
    assert line("") == ""
    assert line("   ") == "   "


def test_line_translator_escalates_and_stays_on_next_tier():
    runner = FakeRunner()
    failing = FakeProvider(fail_all=True)
    working = FakeProvider(prefix="T2")
    factory = make_factory([failing, working])
    t = TieredTranslator(runner=runner, settings=SETTINGS, local_provider_factory=factory)
    line = t.line_translator("es")
    assert line("hello") == "T2:hello"  # tier1 failed -> tier2 answered
    assert line("bye") == "T2:bye"  # stays on tier2 (no re-bind)
    assert len(factory.built) == 2
    # the escalation switched the server to the tier2 GGUF with offload
    assert runner.calls[-1] == {"gguf_path": TIER2_PATH, "gpu_layers": TIER2_GPU_LAYERS}


def test_line_translator_raises_when_chain_exhausted():
    t = make_translator(
        runner=FakeRunner(),
        local=[FakeProvider(fail_all=True), FakeProvider(fail_all=True)],
        hosted=[FakeProvider(fail_all=True)],
    )
    line = t.line_translator("es")
    with pytest.raises(TranslationError):
        line("hello")


# --------------------------------------------------------------------------- #
# GGUF resolution from settings
# --------------------------------------------------------------------------- #
def test_tier_gguf_path_from_models_dir_normalizes():
    t = TieredTranslator(settings={"modelsDir": "D:\\models\\"})
    assert t.tier_gguf_path(TIER_LOCAL) == TIER1_PATH
    assert t.tier_gguf_path(TIER_LOCAL_HEAVY) == TIER2_PATH


def test_tier_gguf_path_explicit_overrides_win():
    t = TieredTranslator(
        settings={
            "modelsDir": "D:/models",
            "translateGgufPath": "/x/a.gguf",
            "translateTier2GgufPath": "/x/b.gguf",
        }
    )
    assert t.tier_gguf_path(TIER_LOCAL) == "/x/a.gguf"
    assert t.tier_gguf_path(TIER_LOCAL_HEAVY) == "/x/b.gguf"


def test_tier_gguf_path_none_when_unconfigured_and_unprovisioned(tmp_path, monkeypatch):
    # No override, no modelsDir, AND no provisioned model at <configDir>/models -> None.
    # The config dir is pinned to an EMPTY temp dir so this never depends on whether the
    # dev/CI machine happens to have a translategemma model at its default location.
    import media_studio.settings_store as _ss

    monkeypatch.setattr(_ss, "default_config_dir", lambda: tmp_path)  # empty: no models/
    t = TieredTranslator(settings={})
    assert t.tier_gguf_path(TIER_LOCAL) is None
    assert t.tier_gguf_path(TIER_HOSTED) is None


def test_tier_gguf_path_falls_back_to_config_dir_models(tmp_path, monkeypatch):
    # A DEFAULT install leaves modelsDir empty; a provisioned local MT tier lives at
    # <configDir>/models/<name>. tier_gguf_path must find it there (same fallback as
    # runner.resolve_gguf_path) so local translation/dubbing works out of the box.
    import os

    import media_studio.settings_store as _ss

    monkeypatch.setattr(_ss, "default_config_dir", lambda: tmp_path)
    models = tmp_path / "models"
    models.mkdir()
    (models / TIER1_GGUF_NAME).write_bytes(b"gguf")
    t = TieredTranslator(settings={})
    got = t.tier_gguf_path(TIER_LOCAL)
    assert got is not None
    assert "/" in got and os.path.samefile(got, models / TIER1_GGUF_NAME)


def test_get_translator_factory():
    t = get_translator({"modelsDir": "D:/models"}, runner=FakeRunner())
    assert isinstance(t, TieredTranslator)
    assert t.tier_gguf_path(TIER_LOCAL) == TIER1_PATH


# --------------------------------------------------------------------------- #
# integration: the REAL ModelRunner switches models across the fallback chain
# --------------------------------------------------------------------------- #
class SpawnRecorder:
    """An argv-list popen seam (mirrors test_runner's FakePopen)."""

    def __init__(self) -> None:
        self.spawned: list[list[str]] = []
        self.procs: list[Any] = []

    def __call__(self, argv, *args: Any, **kwargs: Any):
        assert isinstance(argv, list)

        class Proc:
            def __init__(self) -> None:
                self.terminated = False

            def terminate(self) -> None:
                self.terminated = True

            def wait(self, timeout=None) -> int:
                return 0

            def kill(self) -> None:
                pass

            def poll(self):
                return None

        proc = Proc()
        self.spawned.append(list(argv))
        self.procs.append(proc)
        return proc


def test_real_runner_model_switch_through_fallback():
    popen = SpawnRecorder()
    runner = ModelRunner(settings={}, popen=popen)
    t = TieredTranslator(
        runner=runner,
        settings=SETTINGS,
        local_provider_factory=make_factory([FakeProvider(fail_all=True), FakeProvider(prefix="T2")]),
    )
    out = t.translate(cues2(), "es")
    assert [c["text"] for c in out] == ["T2:Hello there.", "T2:Good night."]
    # two launches: tier1 GGUF first, then the tier2 GGUF with partial offload
    assert len(popen.spawned) == 2
    assert TIER1_PATH in popen.spawned[0]
    assert TIER2_PATH in popen.spawned[1]
    idx = popen.spawned[1].index("--n-gpu-layers")
    assert popen.spawned[1][idx + 1] == str(TIER2_GPU_LAYERS)
    # the tier1 server was gracefully stopped during the model switch
    assert popen.procs[0].terminated is True
    assert runner.current_model_path == TIER2_PATH


# --------------------------------------------------------------------------- #
# U4 manifest entries (pinned MT GGUFs)
# --------------------------------------------------------------------------- #
def test_mt_assets_registered_with_pinned_urls():
    for name, gguf in ((TIER1_ASSET_NAME, TIER1_GGUF_NAME), (TIER2_ASSET_NAME, TIER2_GGUF_NAME)):
        entry = manifest.get_asset(name)
        assert entry is not None, name
        assert entry.kind == "model"
        assert entry.installer == "download"
        assert entry.url is not None and entry.url.startswith("https://huggingface.co/")
        # SCOPE FIX (WU-A1) — the assertion here used to be `entry.url.endswith(gguf)`,
        # i.e. "the local filename equals the remote filename". That happened to hold
        # for the two MT-owned Gemma assets, but it is NOT a property of the SHARED
        # Qwen3-4B asset tier1 now reuses: `manifest.QWEN_DEST` deliberately renames
        # Qwen3-4B-Q4_K_M.gguf -> qwen3-4b.gguf so `runner.DEFAULT_GGUF_NAME` resolves
        # it, and that rename predates WU-A1. Replaced with a STRICTLY STRONGER
        # integrity assertion (this also pins F3c, which endswith() never checked):
        # the url must resolve a 40-hex COMMIT — never a branch/tag — and name a .gguf.
        assert re.fullmatch(r"https://huggingface\.co/[^/]+/[^/]+/resolve/[0-9a-f]{40}/\S+\.gguf", entry.url), entry.url
        assert entry.dest == f"models/{gguf}"
        assert entry.size_mb > 0


def test_mt_asset_detect_finds_existing_copy(tmp_path):
    gguf = tmp_path / TIER1_GGUF_NAME
    gguf.write_bytes(b"GGUF")
    entry = manifest.get_asset(TIER1_ASSET_NAME)
    assert entry.detect({"modelsDir": str(tmp_path)}) == str(gguf)
    assert entry.detect({"modelsDir": str(tmp_path / "missing")}) is None
    assert entry.detect({}) is None


def test_mt_asset_detect_explicit_path(tmp_path):
    gguf = tmp_path / "anywhere.gguf"
    gguf.write_bytes(b"GGUF")
    entry = manifest.get_asset(TIER2_ASSET_NAME)
    assert entry.detect({"translateTier2GgufPath": str(gguf)}) == str(gguf)
    assert entry.detect({"translateTier2GgufPath": str(tmp_path / "nope.gguf")}) is None


# --------------------------------------------------------------------------- #
# WU-A1 licence gate — the commercial blocker, stated as executable properties
#
# docs/plans/v1.5/flagship-lip-sync-dub.md:94 grades the in-tree TranslateGemma
# tiers a BLOCKER: `license:gemma` is "Open Weights", NOT OSI-permissive — it is
# gated, carries a Prohibited-Use Policy and a downstream pass-through duty. The
# owner's constraint is MIT/Apache/BSD ONLY for anything a commercial build
# ships. These tests fail on the pre-swap tree (that is the point).
# --------------------------------------------------------------------------- #
def test_no_gemma_licensed_weight_is_registered():
    """No MT tier may pin a Gemma-licensed artifact into the shipping manifest."""
    for asset_name in (TIER1_ASSET_NAME, TIER2_ASSET_NAME):
        entry = manifest.get_asset(asset_name)
        assert entry is not None, asset_name
        assert "gemma" not in (entry.url or "").lower(), f"{asset_name} still pins a Gemma repo: {entry.url}"
        assert "gemma" not in (entry.label or "").lower(), f"{asset_name} still labelled Gemma: {entry.label}"
        assert "gemma" not in asset_name.lower(), f"asset name still names Gemma: {asset_name}"


def test_tier1_reuses_the_shipped_qwen_asset_zero_new_download():
    """tier1 is the ALREADY-SHIPPED Apache Qwen3-4B GGUF — not a second copy.

    `docs/plans/v1.5/flagship-lip-sync-dub.md:10` calls the swap "a
    **zero-new-download** drop-in". A distinct MT asset for the same weights pulls a
    redundant ~2.5 GB and occupy a second dest, so tier1 must resolve the very
    asset the general-LLM seam already installs (`manifest.QWEN_ASSET_NAME`).
    """
    assert TIER1_ASSET_NAME == manifest.QWEN_ASSET_NAME
    assert f"models/{TIER1_GGUF_NAME}" == manifest.QWEN_DEST


def test_mt_weight_licences_are_permissive():
    """Every SHIPPED MT weight is MIT/Apache/BSD, and the record matches the pin.

    The second half is the load-bearing half: a licence table that is not tied to
    the URL actually registered is just a claim. Re-deriving the repo from the
    REGISTERED url means the record cannot drift away from what is downloaded.
    """
    assert set(MT_WEIGHT_LICENCES) == {TIER1_ASSET_NAME, TIER2_ASSET_NAME}
    for asset_name, (repo, spdx) in MT_WEIGHT_LICENCES.items():
        assert spdx in PERMISSIVE_LICENCES, f"{asset_name}: {spdx} is outside MIT/Apache/BSD"
        entry = manifest.get_asset(asset_name)
        assert entry is not None, asset_name
        assert entry.url.startswith(f"https://huggingface.co/{repo}/resolve/"), (
            f"{asset_name}: licence record names {repo} but the pin is {entry.url}"
        )


def test_permissive_licences_excludes_the_known_blocker_tags():
    """The gate must REJECT the tags docs/plans/v1.5/flagship-lip-sync-dub.md §3.2 lists.

    Without this, `PERMISSIVE_LICENCES` could be widened to admit the very
    licences the commercial gate exists to keep out and every other test here
    would stay green.
    """
    for blocked in ("gemma", "cc-by-nc-4.0", "creativeml-openrail-m", "openrail++", "cc-by-4.0", "other"):
        assert blocked not in PERMISSIVE_LICENCES


def test_mt_tier2_asset_detect_covers_every_lookup_hop(tmp_path):
    """The heavy tier's detect probe: explicit -> modelsDir -> not-found.

    tier1 no longer owns an asset (it reuses the shared Qwen entry, whose detect
    is `manifest.detect_existing_gguf`), so the tier2 entry is now the only
    caller of `_detect_existing` and must exercise all of its hops itself.
    """
    entry = manifest.get_asset(TIER2_ASSET_NAME)
    gguf = tmp_path / TIER2_GGUF_NAME
    gguf.write_bytes(b"GGUF")
    assert entry.detect({"modelsDir": str(tmp_path)}) == str(gguf)
    assert entry.detect({"modelsDir": str(tmp_path / "missing")}) is None
    assert entry.detect({}) is None


# --------------------------------------------------------------------------- #
# _tier_provider / _local_provider / _hosted_provider — direct branch coverage
# --------------------------------------------------------------------------- #
def test_tier_provider_unknown_tier_raises():
    # An unrecognized tier matches neither hosted nor the two local tiers and
    # raises TierUnavailableError (line 415).
    t = TieredTranslator(runner=FakeRunner(), settings=SETTINGS)
    with pytest.raises(TierUnavailableError):
        t._tier_provider("tier-bogus")


def test_local_provider_raises_when_no_gguf_configured(tmp_path, monkeypatch):
    # A runner is present but no GGUF can be resolved (no modelsDir / no override /
    # nothing provisioned at the config dir) -> _local_provider raises
    # TierUnavailableError (line 422). The config dir is pinned to an empty temp dir so
    # the fallback can't resolve a real model on a machine that happens to have one.
    import media_studio.settings_store as _ss

    monkeypatch.setattr(_ss, "default_config_dir", lambda: tmp_path)  # empty: no models/
    t = TieredTranslator(runner=FakeRunner(), settings={})  # runner, but no gguf
    with pytest.raises(TierUnavailableError):
        t._local_provider(TIER_LOCAL)


def test_local_provider_builds_real_local_server_provider_without_factory():
    # No local_provider_factory -> _local_provider constructs a real
    # LocalServerProvider pointed at the configured base URL (line 433).
    runner = FakeRunner()
    t = TieredTranslator(
        runner=runner,
        settings={"modelsDir": "D:/models", "localBaseUrl": "http://127.0.0.1:9/v1"},
    )
    provider = t._local_provider(TIER_LOCAL)
    assert isinstance(provider, LocalServerProvider)
    assert provider.base_url == "http://127.0.0.1:9/v1"
    # The runner was asked to serve the tier1 GGUF.
    assert runner.calls[0]["gguf_path"] == TIER1_PATH


def test_local_provider_fires_ensure_after_start_server():
    # WU-B2: an injected ensure() runs AFTER start_server so the readiness probe
    # gates the local tier (fixes subtitles "LLM 10061" refused-connection).
    runner = FakeRunner()
    order: list[str] = []
    original_start = runner.start_server

    def _record_start(**kwargs: Any) -> Any:
        order.append("start")
        return original_start(**kwargs)

    runner.start_server = _record_start  # type: ignore[method-assign]
    provider = FakeProvider()
    t = TieredTranslator(
        runner=runner,
        settings=SETTINGS,
        local_provider_factory=make_factory([provider]),
        ensure=lambda: order.append("ensure"),
    )
    built = t._local_provider(TIER_LOCAL)
    assert built is provider
    assert order == ["start", "ensure"]  # ensure runs only after the server is asked to start


def test_local_provider_without_ensure_skips_the_probe():
    # ensure defaults to None -> the local tier is unchanged (back-compat).
    runner = FakeRunner()
    t = TieredTranslator(runner=runner, settings=SETTINGS, local_provider_factory=make_factory([FakeProvider()]))
    t._local_provider(TIER_LOCAL)  # no ensure -> no probe, no error
    assert runner.calls[0]["gguf_path"] == TIER1_PATH


def test_get_translator_threads_ensure_into_translator():
    # WU-B2: the factory the wiring layer calls forwards ensure to the translator.
    fired: list[str] = []
    t = get_translator(
        SETTINGS,
        runner=FakeRunner(),
        ensure=lambda: fired.append("e"),
        local_provider_factory=make_factory([FakeProvider()]),
    )
    t._local_provider(TIER_LOCAL)
    assert fired == ["e"]


def test_hosted_provider_builds_real_cloud_provider_without_factory():
    # No hosted_provider_factory + a cloudApiKey present -> _hosted_provider
    # constructs a real CloudProvider (line 448).
    t = TieredTranslator(
        runner=None,
        settings={"cloudApiKey": "sk-key", "cloudBaseUrl": "https://api.example/v1"},
    )
    provider = t._hosted_provider()
    assert isinstance(provider, CloudProvider)
    assert provider.base_url == "https://api.example/v1"


def test_line_translator_skips_unbindable_tier_then_uses_hosted():
    # tier1/tier2 cannot even materialize a provider (no runner) -> the binding
    # except in line_translator logs + records the failure + continues to the
    # next tier (lines 344-347); tier3 hosted then serves the line.
    hosted = FakeProvider(prefix="CLOUD")
    t = TieredTranslator(
        runner=None,  # both local tiers fail to bind
        settings={},
        hosted_provider_factory=lambda: hosted,
    )
    line = t.line_translator("es")  # tier1-routed lang
    assert line("hello") == "CLOUD:hello"
