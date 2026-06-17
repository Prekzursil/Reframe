"""Unit tests for media_studio.models.catalog (WU-catalog).

Pure data + pure helpers — no network, no model, no fakes needed. Asserts the
catalog was seeded VERBATIM from ``docs/providers/CATALOG-SEED.md`` (13 entries,
>=3 distinct providers, every one of the 5 Reframe tasks ranked, dated guidance,
privacy/train-on-input axis), and that the filter/order/top-pick helpers behave.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest
from media_studio.models.catalog import (
    CATALOG,
    Capability,
    CatalogEntry,
    CostClass,
    PrivacyTier,
    Task,
    TierGrade,
    Unit,
    filter_by_capability,
    order_by,
    top_pick_for_task,
)

# --------------------------------------------------------------------------- #
# Shape / completeness invariants
# --------------------------------------------------------------------------- #


def test_catalog_is_a_tuple_of_entries() -> None:
    assert isinstance(CATALOG, tuple)
    assert all(isinstance(e, CatalogEntry) for e in CATALOG)
    # 13 seeded models per CATALOG-SEED.md.
    assert len(CATALOG) == 13


def test_catalog_ids_are_unique() -> None:
    ids = [e.id for e in CATALOG]
    assert len(ids) == len(set(ids))


def test_catalog_spans_at_least_three_distinct_providers() -> None:
    # Acceptance (a): >=3 distinct providers.
    providers = {e.provider for e in CATALOG}
    assert len(providers) >= 3
    # The seed's headline providers must all be present.
    assert {"Groq", "Cerebras", "Google AI Studio"} <= providers


def test_every_entry_ranks_all_five_tasks() -> None:
    # Acceptance (a): ranks each model per the 5 tasks.
    for entry in CATALOG:
        assert set(entry.per_task_tier.keys()) == set(Task)
        for grade in entry.per_task_tier.values():
            assert isinstance(grade, TierGrade)


def test_every_entry_has_a_privacy_tier_unit_and_asofdate() -> None:
    # Acceptance (d): every label is dated guidance.
    for entry in CATALOG:
        assert isinstance(entry.privacy_tier, PrivacyTier)
        assert isinstance(entry.unit, Unit)
        assert isinstance(entry.cost_class, CostClass)
        assert entry.as_of_date  # non-empty dated guidance
        # capabilities is a non-empty tuple of Capability.
        assert entry.capabilities
        assert all(isinstance(c, Capability) for c in entry.capabilities)


def test_entries_are_frozen_immutable() -> None:
    entry = CATALOG[0]
    with pytest.raises(FrozenInstanceError):
        entry.id = "mutated"  # type: ignore[misc]


def test_trains_on_input_is_bool_or_conditional() -> None:
    for entry in CATALOG:
        assert entry.trains_on_input in (True, False, "conditional")


# --------------------------------------------------------------------------- #
# Verbatim seed facts (privacy / train-on-input axis)
# --------------------------------------------------------------------------- #


def _by_id(entry_id: str) -> CatalogEntry:
    return next(e for e in CATALOG if e.id == entry_id)


def test_groq_gpt_oss_is_safe_no_train() -> None:
    # Acceptance (c): Groq flagged SAFE no-train.
    groq = _by_id("groq-gpt-oss-120b")
    assert groq.provider == "Groq"
    assert groq.privacy_tier is PrivacyTier.SAFE
    assert groq.trains_on_input is False
    assert groq.context_tokens == 128_000
    assert groq.unit is Unit.TOKEN


def test_gemini_free_trains_and_is_avoid() -> None:
    # Acceptance (b): Gemini-free flagged trainsOnInput=True / privacyTier=AVOID.
    flash = _by_id("gemini-2.5-flash")
    assert flash.provider == "Google AI Studio"
    assert flash.trains_on_input is True
    assert flash.privacy_tier is PrivacyTier.AVOID
    lite = _by_id("gemini-2.5-flash-lite")
    assert lite.trains_on_input is True
    assert lite.privacy_tier is PrivacyTier.AVOID


def test_mistral_pixtral_is_conditional() -> None:
    pixtral = _by_id("mistral-pixtral")
    assert pixtral.trains_on_input == "conditional"
    assert pixtral.privacy_tier is PrivacyTier.CONDITIONAL


def test_openrouter_free_entries_are_conditional() -> None:
    text = _by_id("openrouter-free-text")
    vision = _by_id("openrouter-free-vision")
    assert text.privacy_tier is PrivacyTier.CONDITIONAL
    assert vision.privacy_tier is PrivacyTier.CONDITIONAL
    assert text.trains_on_input == "conditional"
    assert vision.trains_on_input == "conditional"


def test_cerebras_is_unverified_train_policy() -> None:
    qwen = _by_id("cerebras-qwen3-235b")
    # Unverified -> conservatively marked conditional (not asserted SAFE).
    assert qwen.trains_on_input == "conditional"
    assert qwen.context_tokens == 128_000
    assert qwen.unit is Unit.TOKEN


def test_cloudflare_has_limiting_small_context() -> None:
    cf = _by_id("cloudflare-workers-ai")
    # Seed flags 2K-8K as limiting; we encode the upper bound 8K.
    assert cf.context_tokens == 8_000
    assert cf.privacy_tier is PrivacyTier.SAFE


def test_vision_entries_declare_vision_capability() -> None:
    for entry_id in (
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
        "github-gpt-4o-mini",
        "mistral-pixtral",
        "openrouter-free-vision",
        "openai-api",
    ):
        entry = _by_id(entry_id)
        assert Capability.VISION in entry.capabilities


def test_text_only_entries_have_no_vision_capability() -> None:
    for entry_id in (
        "groq-gpt-oss-120b",
        "groq-llama-3.3-70b",
        "cerebras-qwen3-235b",
        "cerebras-llama-3.3-70b",
        "sambanova-llama-3.1-405b",
        "cloudflare-workers-ai",
        "openrouter-free-text",
    ):
        entry = _by_id(entry_id)
        assert Capability.VISION not in entry.capabilities
        assert Capability.TEXT in entry.capabilities


# --------------------------------------------------------------------------- #
# filter_by_capability
# --------------------------------------------------------------------------- #


def test_filter_by_capability_vision() -> None:
    vision = filter_by_capability(Capability.VISION)
    assert all(Capability.VISION in e.capabilities for e in vision)
    # 6 vision entries per the seed.
    assert len(vision) == 6


def test_filter_by_capability_text_includes_all_text_models() -> None:
    text = filter_by_capability(Capability.TEXT)
    # Every entry can do text (vision models are multimodal).
    assert len(text) == len(CATALOG)


def test_filter_by_capability_accepts_custom_catalog() -> None:
    subset = (CATALOG[0],)
    assert filter_by_capability(Capability.TEXT, catalog=subset) == list(subset)


# --------------------------------------------------------------------------- #
# order_by
# --------------------------------------------------------------------------- #


def test_order_by_quality_uses_best_task_grade() -> None:
    ordered = order_by("quality")
    assert len(ordered) == len(CATALOG)
    # Groq GPT-OSS-120B (two S grades) ranks at/near the top.
    assert ordered[0].id in {"groq-gpt-oss-120b", "gemini-2.5-flash"}


def test_order_by_context_descending() -> None:
    ordered = order_by("context")
    ctx = [e.context_tokens for e in ordered]
    assert ctx == sorted(ctx, reverse=True)
    # Gemini's ~1M context wins.
    assert ordered[0].context_tokens == 1_000_000


def test_order_by_limit_descending() -> None:
    ordered = order_by("limit")
    scores = [e.free_limit_score for e in ordered]
    assert scores == sorted(scores, reverse=True)


def test_order_by_accepts_custom_catalog() -> None:
    subset = (CATALOG[1], CATALOG[0])
    ordered = order_by("context", catalog=subset)
    assert {e.id for e in ordered} == {CATALOG[0].id, CATALOG[1].id}


def test_order_by_rejects_unknown_key() -> None:
    with pytest.raises(ValueError, match="unknown order key"):
        order_by("nonsense")  # type: ignore[arg-type]


def test_order_by_is_stable_and_nonmutating() -> None:
    before = list(CATALOG)
    order_by("quality")
    assert list(CATALOG) == before  # source untouched


# --------------------------------------------------------------------------- #
# top_pick_for_task
# --------------------------------------------------------------------------- #


def test_top_pick_task1_is_groq_gpt_oss() -> None:
    # Seed "Top pick per task": task1 -> Groq GPT-OSS-120B.
    pick = top_pick_for_task(Task.MOMENT_FIND)
    assert pick.id == "groq-gpt-oss-120b"


def test_top_pick_task2_is_groq_llama() -> None:
    pick = top_pick_for_task(Task.CAPTION)
    assert pick.id == "groq-llama-3.3-70b"


def test_top_pick_task4_is_gemini_flash_lite_with_avoid_flag() -> None:
    # Seed: task4 -> Gemini 2.5 Flash-Lite (best free OCR) with AVOID-private.
    pick = top_pick_for_task(Task.VISION)
    assert pick.id == "gemini-2.5-flash-lite"
    assert pick.privacy_tier is PrivacyTier.AVOID
    assert pick.trains_on_input is True


def test_top_pick_task5_is_groq_gpt_oss() -> None:
    pick = top_pick_for_task(Task.EDIT_PLAN)
    assert pick.id == "groq-gpt-oss-120b"


def test_top_pick_ranks_all_five_tasks() -> None:
    # Acceptance: ranks all 5 tasks (every task yields a pick).
    picks = {task: top_pick_for_task(task) for task in Task}
    assert len(picks) == 5
    assert all(isinstance(p, CatalogEntry) for p in picks.values())


def test_top_pick_accepts_custom_catalog() -> None:
    # A custom catalog with a single text model returns that model.
    only = (_by_id("groq-llama-3.3-70b"),)
    pick = top_pick_for_task(Task.CAPTION, catalog=only)
    assert pick.id == "groq-llama-3.3-70b"


def test_top_pick_falls_back_to_grade_ranking_when_preferred_absent() -> None:
    # Custom catalog WITHOUT the seed's CAPTION top pick (groq-llama-3.3-70b):
    # the helper falls back to grade -> free-limit -> context ranking. Both are
    # grade A on CAPTION, so the higher free-limit GPT-OSS (80) beats SambaNova.
    subset = (_by_id("groq-gpt-oss-120b"), _by_id("sambanova-llama-3.1-405b"))
    pick = top_pick_for_task(Task.CAPTION, catalog=subset)
    assert pick.id == "groq-gpt-oss-120b"


def test_top_pick_raises_when_no_entry_can_serve_task() -> None:
    # A vision-only task against a catalog with no eligible (non-"na") entry.
    text_only = (_by_id("cloudflare-workers-ai"),)
    # Cloudflare is "na" for vision (task4) -> no eligible pick.
    with pytest.raises(ValueError, match="no catalog entry serves task"):
        top_pick_for_task(Task.VISION, catalog=text_only)
