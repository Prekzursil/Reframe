"""Tests for the provider-Hub presets seam (``media_studio.models.presets``).

PURE module under test: presets + per-function routing resolved against an
INJECTED catalog (faked here) and a settings mapping. No network, no heavy
deps, no cross-import of the real ``catalog.py`` (a LATER WU). The fake catalog
below mirrors only the duck-typed surface ``presets`` actually consumes:
``id``, ``provider``, ``capabilities``, ``per_task_tier`` and ``privacy_tier``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest
from media_studio.models import presets as P

# --------------------------------------------------------------------------- #
# Fake catalog (duck-typed; only the attributes presets reads)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class FakeEntry:
    """A minimal stand-in for the real ``CatalogEntry`` (LATER WU)."""

    id: str
    provider: str
    capabilities: tuple[str, ...]
    # per-function task tier: function-name -> S/A/B/C/na grade
    per_task_tier: dict[str, str]
    privacy_tier: str = "SAFE"


@dataclass
class FakeCatalog:
    """A tiny catalog the presets module ranks/filters over."""

    entries: tuple[FakeEntry, ...] = field(default_factory=tuple)

    def all(self) -> tuple[FakeEntry, ...]:
        return self.entries


def _catalog() -> FakeCatalog:
    """A representative multi-provider catalog spanning all six functions."""
    return FakeCatalog(
        entries=(
            FakeEntry(
                id="groq-gpt-oss-120b",
                provider="groq",
                capabilities=("text",),
                per_task_tier={
                    "select": "S",
                    "subtitles": "A",
                    "translation": "A",
                    "vision": "na",
                    "editPlan": "S",
                    # WU-A3: "index" reuses the MOMENT_FIND task (== "select"'s
                    # task), so its grade mirrors "select" — exactly how the real
                    # CatalogAdapter flattens it (every text row already grades it).
                    "index": "S",
                },
                privacy_tier="SAFE",
            ),
            FakeEntry(
                id="groq-llama-3.3-70b",
                provider="groq",
                capabilities=("text",),
                per_task_tier={
                    "select": "A",
                    "subtitles": "S",
                    "translation": "S",
                    "vision": "na",
                    "editPlan": "A",
                    "index": "A",
                },
                privacy_tier="SAFE",
            ),
            FakeEntry(
                id="gemini-2.5-flash-lite",
                provider="google",
                capabilities=("text", "vision"),
                per_task_tier={
                    "select": "A",
                    "subtitles": "S",
                    "translation": "A",
                    "vision": "S",
                    "editPlan": "A",
                    "index": "A",
                },
                privacy_tier="AVOID",
            ),
            FakeEntry(
                id="github-gpt-4o-mini",
                provider="github",
                capabilities=("text", "vision"),
                per_task_tier={
                    "select": "B",
                    "subtitles": "A",
                    "translation": "A",
                    "vision": "A",
                    "editPlan": "B",
                    "index": "B",
                },
                privacy_tier="SAFE",
            ),
        )
    )


# --------------------------------------------------------------------------- #
# PRESETS registry shape
# --------------------------------------------------------------------------- #


def test_presets_registry_has_exactly_the_three_named_presets() -> None:
    assert set(P.PRESETS) == {"privacy", "bestFreeCloud", "balanced"}


def test_every_preset_maps_all_functions() -> None:
    for descriptor in P.PRESETS.values():
        assert set(descriptor) == set(P.FUNCTIONS)


def test_functions_constant_is_the_task_seams_including_index() -> None:
    # WU-A3 promotes embeddings to a first-class routable function ("index").
    assert P.FUNCTIONS == ("select", "subtitles", "translation", "vision", "editPlan", "index")


def test_index_is_a_text_capability_function() -> None:
    # WU-A3 AC-(a): "index" requires the "text" capability (not vision).
    assert "index" in P.FUNCTIONS
    assert P._REQUIRED_CAPABILITY["index"] == "text"


def test_index_maps_to_existing_moment_find_task() -> None:
    # WU-A3 AC-(a): "index" reuses the EXISTING MOMENT_FIND catalog task so the
    # bracket lookup resolves against every seed row with zero catalog edits.
    assert P._FUNCTION_TASK_NAMES["index"] == "MOMENT_FIND"


def test_apply_preset_produces_an_index_route_for_every_preset() -> None:
    # WU-A3 AC-(b): every preset yields a routing.perFunction["index"] slot with
    # NO KeyError at _AdaptedEntry.__init__ (the task resolves on all rows).
    for name in P.PRESETS:
        routing = P.apply_preset(name, {}, _catalog())
        slot = routing["perFunction"]["index"]
        assert "provider" in slot
        assert "fallback" in slot


def test_index_routes_local_under_privacy_and_cloud_under_bestfreecloud() -> None:
    # AC-(b): under privacy the index route is local (no egress); under cloud it
    # resolves to the catalog's top index pick (mirrors "select" via MOMENT_FIND).
    assert P.apply_preset("privacy", {}, _catalog())["perFunction"]["index"]["provider"] == P.LOCAL
    cloud = P.apply_preset("bestFreeCloud", {}, _catalog())["perFunction"]["index"]
    assert cloud["provider"] == "groq-gpt-oss-120b"
    assert cloud["fallback"][-1] == P.LOCAL


# --------------------------------------------------------------------------- #
# apply_preset — privacy -> all-local
# --------------------------------------------------------------------------- #


def test_privacy_preset_routes_every_function_to_local_no_cloud() -> None:
    routing = P.apply_preset("privacy", {}, _catalog())
    assert routing["activePreset"] == "privacy"
    for fn in P.FUNCTIONS:
        slot = routing["perFunction"][fn]
        assert slot["provider"] == P.LOCAL
        # no cloud egress at all: the fallback chain is local-only too.
        assert slot["fallback"] == []


def test_privacy_preset_has_zero_cloud_provider_ids_anywhere() -> None:
    routing = P.apply_preset("privacy", {}, _catalog())
    seen: set[str] = set()
    for slot in routing["perFunction"].values():
        seen.add(slot["provider"])
        seen.update(slot["fallback"])
    assert seen == {P.LOCAL}


# --------------------------------------------------------------------------- #
# apply_preset — bestFreeCloud -> cloud primary + local fallback
# --------------------------------------------------------------------------- #


def test_best_free_cloud_is_cloud_primary_with_local_fallback() -> None:
    routing = P.apply_preset("bestFreeCloud", {}, _catalog())
    assert routing["activePreset"] == "bestFreeCloud"
    for fn in P.FUNCTIONS:
        slot = routing["perFunction"][fn]
        assert slot["provider"] != P.LOCAL  # a concrete cloud model id
        assert slot["fallback"][-1] == P.LOCAL  # local always the backstop


def test_best_free_cloud_picks_catalog_top_pick_per_function() -> None:
    routing = P.apply_preset("bestFreeCloud", {}, _catalog())
    # select top grade S -> groq-gpt-oss-120b; subtitles top S -> groq-llama-3.3-70b
    assert routing["perFunction"]["select"]["provider"] == "groq-gpt-oss-120b"
    assert routing["perFunction"]["subtitles"]["provider"] == "groq-llama-3.3-70b"
    # vision top S is gemini but AVOID-private -> bestFreeCloud still allows it
    assert routing["perFunction"]["vision"]["provider"] == "gemini-2.5-flash-lite"


# --------------------------------------------------------------------------- #
# apply_preset — balanced -> mixed (text cloud, vision local)
# --------------------------------------------------------------------------- #


def test_balanced_preset_is_mixed_cloud_text_local_vision() -> None:
    routing = P.apply_preset("balanced", {}, _catalog())
    assert routing["activePreset"] == "balanced"
    # text functions go cloud...
    assert routing["perFunction"]["select"]["provider"] != P.LOCAL
    assert routing["perFunction"]["translation"]["provider"] != P.LOCAL
    # ...privacy-sensitive vision stays local (a genuinely mixed routing).
    assert routing["perFunction"]["vision"]["provider"] == P.LOCAL


def test_balanced_avoids_privacy_avoid_providers_for_text() -> None:
    routing = P.apply_preset("balanced", {}, _catalog())
    # balanced is privacy-aware: it never picks an AVOID model as a text primary.
    for fn in ("select", "subtitles", "translation", "editPlan"):
        pid = routing["perFunction"][fn]["provider"]
        if pid != P.LOCAL:
            entry = next(e for e in _catalog().all() if e.id == pid)
            assert entry.privacy_tier != "AVOID"


# --------------------------------------------------------------------------- #
# apply_preset — error path
# --------------------------------------------------------------------------- #


def test_apply_preset_unknown_name_raises() -> None:
    with pytest.raises(ValueError, match="unknown preset"):
        P.apply_preset("nope", {}, _catalog())


def test_best_free_cloud_with_empty_catalog_degrades_to_local() -> None:
    # If a function has no capable cloud candidate, that slot falls back to local
    # (never proposes a model the catalog cannot supply).
    routing = P.apply_preset("bestFreeCloud", {}, FakeCatalog(entries=()))
    for fn in P.FUNCTIONS:
        assert routing["perFunction"][fn]["provider"] == P.LOCAL


# --------------------------------------------------------------------------- #
# suggest_for_function — catalog-ranked, capability-filtered
# --------------------------------------------------------------------------- #


def test_suggest_returns_catalog_ranked_candidates() -> None:
    out = P.suggest_for_function("select", _catalog(), {})
    ids = [c.id for c in out]
    # select grades: S(groq-gpt-oss) > A(groq-llama, gemini) > B(github)
    assert ids[0] == "groq-gpt-oss-120b"
    assert ids[-1] == "github-gpt-4o-mini"


def test_suggest_excludes_capability_mismatch() -> None:
    # vision requires a vision-capable model -> text-only groq entries excluded.
    out = P.suggest_for_function("vision", _catalog(), {})
    ids = {c.id for c in out}
    assert "groq-gpt-oss-120b" not in ids
    assert "groq-llama-3.3-70b" not in ids
    assert ids == {"gemini-2.5-flash-lite", "github-gpt-4o-mini"}


def test_suggest_never_proposes_na_grade() -> None:
    # vision tier 'na' on groq entries must never be proposed even before the
    # capability filter (defence in depth).
    out = P.suggest_for_function("vision", _catalog(), {})
    for c in out:
        assert c.per_task_tier["vision"] != "na"


def test_suggest_respects_privacy_pref_excluding_avoid() -> None:
    # prefs can demand SAFE-only -> AVOID-tier gemini dropped from vision.
    out = P.suggest_for_function("vision", _catalog(), {"requireSafePrivacy": True})
    ids = {c.id for c in out}
    assert "gemini-2.5-flash-lite" not in ids
    assert ids == {"github-gpt-4o-mini"}


def test_suggest_unknown_function_raises() -> None:
    with pytest.raises(ValueError, match="unknown function"):
        P.suggest_for_function("bogus", _catalog(), {})


def test_suggest_empty_catalog_returns_empty_list() -> None:
    assert P.suggest_for_function("select", FakeCatalog(entries=()), {}) == []


def test_suggest_stable_order_for_equal_grade() -> None:
    # gemini and github-gpt-4o-mini both grade A on translation in a 2-entry
    # catalog; equal grades preserve catalog order (stable sort).
    cat = FakeCatalog(
        entries=(
            FakeEntry(
                id="first-A",
                provider="p1",
                capabilities=("text",),
                per_task_tier={"translation": "A"},
            ),
            FakeEntry(
                id="second-A",
                provider="p2",
                capabilities=("text",),
                per_task_tier={"translation": "A"},
            ),
        )
    )
    out = [c.id for c in P.suggest_for_function("translation", cat, {})]
    assert out == ["first-A", "second-A"]


# --------------------------------------------------------------------------- #
# first_run_default — local-safe pre-choice
# --------------------------------------------------------------------------- #


def test_first_run_default_is_privacy_before_any_choice() -> None:
    assert P.first_run_default({}) == "privacy"
    assert P.first_run_default({"firstRunChoiceMade": False}) == "privacy"


def test_first_run_default_honors_recorded_cloud_choice() -> None:
    settings: dict[str, Any] = {
        "firstRunChoiceMade": True,
        "activePreset": "bestFreeCloud",
    }
    assert P.first_run_default(settings) == "bestFreeCloud"


def test_first_run_default_choice_made_but_local_preset_stays_privacy() -> None:
    settings: dict[str, Any] = {
        "firstRunChoiceMade": True,
        "activePreset": "privacy",
    }
    assert P.first_run_default(settings) == "privacy"


def test_first_run_default_choice_made_balanced_counts_as_cloud() -> None:
    settings: dict[str, Any] = {
        "firstRunChoiceMade": True,
        "activePreset": "balanced",
    }
    # any non-privacy active preset after a choice -> the cloud-capable default.
    assert P.first_run_default(settings) == "bestFreeCloud"


def test_first_run_default_choice_made_without_preset_is_privacy() -> None:
    # a choice flag without a recorded preset is still local-safe.
    assert P.first_run_default({"firstRunChoiceMade": True}) == "privacy"
