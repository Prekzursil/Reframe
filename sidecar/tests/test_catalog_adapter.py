"""Tests for the catalog->presets adapter (WU-presets carryforward #1).

``presets.py`` is PURE and duck-types its catalog as ``.all()`` returning entries
whose ``per_task_tier`` is keyed by the FUNCTION NAME (``"select"`` / ``"vision"``
…) string. The REAL :mod:`media_studio.models.catalog` keys ``per_task_tier`` by
the :class:`catalog.Task` ENUM and exposes no ``all()``. Without an adapter every
grade would resolve to ``"na"`` and the presets would degrade everything to local.

The adapter under test bridges the two so ``apply_preset`` /
``suggest_for_function`` consume the REAL catalog correctly.
"""

from __future__ import annotations

from media_studio.models import catalog as C
from media_studio.models import presets as P


def _adapter() -> P.CatalogLike:
    return P.CatalogAdapter()


# --------------------------------------------------------------------------- #
# Shape: .all() + string-keyed per_task_tier
# --------------------------------------------------------------------------- #


def test_adapter_all_returns_every_catalog_entry() -> None:
    entries = _adapter().all()
    assert len(entries) == len(C.CATALOG)
    assert {e.id for e in entries} == {e.id for e in C.CATALOG}


def test_adapter_entries_satisfy_the_presets_duck_type() -> None:
    for entry in _adapter().all():
        assert isinstance(entry, P.CatalogEntryLike)


def test_adapter_per_task_tier_is_keyed_by_function_name_not_enum() -> None:
    # The whole point of the adapter: function-name keys (string), not Task enum.
    entry = next(e for e in _adapter().all() if e.id == "groq-gpt-oss-120b")
    assert set(entry.per_task_tier) == set(P.FUNCTIONS)
    # groq-gpt-oss-120b grades: T1=S, T2=A, T3=A, T4=na, T5=S (catalog seed).
    assert entry.per_task_tier["select"] == "S"
    assert entry.per_task_tier["subtitles"] == "A"
    assert entry.per_task_tier["translation"] == "A"
    assert entry.per_task_tier["vision"] == "na"
    assert entry.per_task_tier["editPlan"] == "S"


def test_adapter_capabilities_are_plain_strings() -> None:
    # presets checks ``"text"``/``"vision"`` membership in capabilities -> strings.
    vision_entry = next(e for e in _adapter().all() if e.id == "gemini-2.5-flash-lite")
    assert "text" in vision_entry.capabilities
    assert "vision" in vision_entry.capabilities
    text_entry = next(e for e in _adapter().all() if e.id == "groq-gpt-oss-120b")
    assert "vision" not in text_entry.capabilities


def test_adapter_privacy_tier_is_the_string_value() -> None:
    gemini = next(e for e in _adapter().all() if e.id == "gemini-2.5-flash-lite")
    assert gemini.privacy_tier == "AVOID"
    groq = next(e for e in _adapter().all() if e.id == "groq-gpt-oss-120b")
    assert groq.privacy_tier == "SAFE"


# --------------------------------------------------------------------------- #
# Integration: presets consume the REAL catalog through the adapter
# --------------------------------------------------------------------------- #


def test_bestfreecloud_over_real_catalog_resolves_real_picks_not_local() -> None:
    routing = P.apply_preset("bestFreeCloud", {}, _adapter())
    # If the adapter were missing, every grade would be "na" -> every slot local.
    # With it, text slots resolve to the catalog's top text picks (NOT local).
    assert routing["perFunction"]["select"]["provider"] == "groq-gpt-oss-120b"
    assert routing["perFunction"]["subtitles"]["provider"] == "groq-llama-3.3-70b"
    assert routing["perFunction"]["translation"]["provider"] == "groq-llama-3.3-70b"
    assert routing["perFunction"]["editPlan"]["provider"] == "groq-gpt-oss-120b"
    # vision resolves to a vision-capable cloud model, never local under cloud.
    assert routing["perFunction"]["vision"]["provider"] != P.LOCAL


def test_suggest_vision_over_real_catalog_excludes_text_only_models() -> None:
    out = P.suggest_for_function("vision", _adapter(), {})
    ids = {e.id for e in out}
    # Text-only Groq models are never proposed for vision (capability filter).
    assert "groq-gpt-oss-120b" not in ids
    assert "groq-llama-3.3-70b" not in ids
    # The vision-capable models ARE proposed.
    assert "gemini-2.5-flash-lite" in ids
    assert "github-gpt-4o-mini" in ids


def test_suggest_select_safe_only_drops_avoid_tier_real_catalog() -> None:
    out = P.suggest_for_function("select", _adapter(), {"requireSafePrivacy": True})
    for entry in out:
        assert entry.privacy_tier != "AVOID"


def test_balanced_over_real_catalog_is_mixed_cloud_text_local_vision() -> None:
    routing = P.apply_preset("balanced", {}, _adapter())
    assert routing["perFunction"]["select"]["provider"] != P.LOCAL
    assert routing["perFunction"]["vision"]["provider"] == P.LOCAL


def test_privacy_over_real_catalog_is_all_local() -> None:
    routing = P.apply_preset("privacy", {}, _adapter())
    for fn in P.FUNCTIONS:
        assert routing["perFunction"][fn]["provider"] == P.LOCAL


# --------------------------------------------------------------------------- #
# Adapter accepts a custom catalog tuple (so tests can pin a tiny one)
# --------------------------------------------------------------------------- #


def test_adapter_accepts_a_custom_catalog_tuple() -> None:
    one = (C.CATALOG[0],)
    adapter = P.CatalogAdapter(catalog=one)
    entries = adapter.all()
    assert len(entries) == 1
    assert entries[0].id == C.CATALOG[0].id


def test_function_to_task_mapping_covers_all_five_functions() -> None:
    # The adapter's function->Task map must be total over FUNCTIONS (no KeyError).
    mapping = P.function_tasks()
    assert set(mapping) == set(P.FUNCTIONS)
    assert mapping["vision"] is C.Task.VISION
    assert mapping["editPlan"] is C.Task.EDIT_PLAN
