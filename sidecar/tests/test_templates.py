"""Tests for media_studio.features.templates — saved repurpose templates.

A *template* is a recipe (frozen ``recipes`` wire shape) PLUS two additive
fields — ``defaultControls`` and ``exportTargets:[presetId]`` — and a **method
allowlist** so a saved template can only name the curated repurpose verbs. The
module REUSES ``recipes.RecipeStore``/``recipes.normalize_recipe`` by import
(no fork of the wire shape), so these tests pin the additive behavior + the
allowlist guard, and assert the reuse contract.

Storage-only + pure logic: no media work, no providers, no jobs (WU3). The
``templates.*`` RPC + the export-step fan-out arrive in later WUs.
"""

from __future__ import annotations

from typing import Any

import pytest
from media_studio.features import recipes, templates
from media_studio.protocol import RpcError


# --------------------------------------------------------------------------- #
# pure: normalize_template (reuses recipes.normalize_recipe + additive fields)
# --------------------------------------------------------------------------- #
class TestNormalizeTemplate:
    def _valid(self, **overrides: Any) -> dict[str, Any]:
        base: dict[str, Any] = {
            "name": "Repurpose",
            "steps": [{"method": "shortmaker.export", "params": {"count": 3}}],
            "defaultControls": {"count": 3, "captionStyle": "libass"},
            "exportTargets": ["tiktok", "shorts"],
        }
        base.update(overrides)
        return base

    def test_valid_template_keeps_additive_fields(self):
        t = templates.normalize_template(self._valid())
        assert t["defaultControls"] == {"count": 3, "captionStyle": "libass"}
        assert t["exportTargets"] == ["tiktok", "shorts"]
        # recipe shape preserved (id assigned, steps normalized)
        assert t["id"]
        assert t["name"] == "Repurpose"
        assert t["steps"][0]["method"] == "shortmaker.export"
        assert t["steps"][0]["label"] == "shortmaker.export"

    def test_id_preserved_when_given(self):
        t = templates.normalize_template(self._valid(id="fixed"))
        assert t["id"] == "fixed"

    def test_id_assigned_when_absent(self):
        t = templates.normalize_template(self._valid())
        assert isinstance(t["id"], str) and t["id"]

    def test_default_controls_default_to_empty_dict(self):
        raw = self._valid()
        del raw["defaultControls"]
        t = templates.normalize_template(raw)
        assert t["defaultControls"] == {}

    def test_export_targets_default_to_empty_list(self):
        raw = self._valid()
        del raw["exportTargets"]
        t = templates.normalize_template(raw)
        assert t["exportTargets"] == []

    def test_default_controls_copied_not_aliased(self):
        raw = self._valid()
        t = templates.normalize_template(raw)
        raw["defaultControls"]["count"] = 99
        assert t["defaultControls"]["count"] == 3

    def test_export_targets_copied_not_aliased(self):
        raw = self._valid()
        t = templates.normalize_template(raw)
        raw["exportTargets"].append("reels")
        assert t["exportTargets"] == ["tiktok", "shorts"]

    @pytest.mark.parametrize(
        "method",
        [
            "transcribe.start",
            "subtitles.generate",
            "shortmaker.export",
            "phase8.select",
            "nle.export",
            "package.export",
            "convert.run",
            "audio.mix",
        ],
    )
    def test_allowlisted_methods_accepted(self, method):
        t = templates.normalize_template(self._valid(steps=[{"method": method}]))
        assert t["steps"][0]["method"] == method

    @pytest.mark.parametrize(
        "method",
        ["shell.exec", "recipes.run", "os.system", "reframe.start", "phase8.other"],
    )
    def test_unknown_method_rejected_by_allowlist(self, method):
        with pytest.raises(RpcError):
            templates.normalize_template(self._valid(steps=[{"method": method}]))

    def test_malformed_export_targets_non_list_rejected(self):
        with pytest.raises(RpcError):
            templates.normalize_template(self._valid(exportTargets="tiktok"))

    def test_malformed_export_targets_non_string_id_rejected(self):
        with pytest.raises(RpcError):
            templates.normalize_template(self._valid(exportTargets=["tiktok", 7]))

    def test_malformed_export_targets_empty_string_id_rejected(self):
        with pytest.raises(RpcError):
            templates.normalize_template(self._valid(exportTargets=["tiktok", ""]))

    def test_malformed_default_controls_non_dict_rejected(self):
        with pytest.raises(RpcError):
            templates.normalize_template(self._valid(defaultControls=["nope"]))

    @pytest.mark.parametrize("bad", ["nope", None, 7, ["steps"]])
    def test_non_dict_template_rejected(self, bad):
        with pytest.raises(RpcError):
            templates.normalize_template(bad)

    def test_recipe_shape_errors_propagate(self):
        # A missing name is a recipes.normalize_recipe failure, surfaced verbatim.
        raw = self._valid()
        del raw["name"]
        with pytest.raises(RpcError):
            templates.normalize_template(raw)

    def test_reuses_recipes_normalize_recipe(self, monkeypatch: pytest.MonkeyPatch):
        # Falsifiable-acceptance #3: recipes.normalize_recipe is the ONLY recipe
        # validation path — assert it is actually invoked (no re-implementation).
        calls: list[dict[str, Any]] = []
        real = recipes.normalize_recipe

        def spy(raw: dict[str, Any]):
            calls.append(raw)
            return real(raw)

        monkeypatch.setattr(templates.recipes, "normalize_recipe", spy)
        templates.normalize_template(self._valid())
        assert len(calls) == 1


# --------------------------------------------------------------------------- #
# storage: TemplateStore is recipes.RecipeStore over templates.json
# --------------------------------------------------------------------------- #
class TestTemplateStore:
    def _store(self, tmp_path):
        return templates.TemplateStore(tmp_path / "templates.json")

    def test_store_is_a_recipe_store(self, tmp_path):
        store = self._store(tmp_path)
        assert isinstance(store, recipes.RecipeStore)

    def test_empty_store_lists_nothing(self, tmp_path):
        assert self._store(tmp_path).list() == []

    def test_save_list_get_delete_round_trip(self, tmp_path):
        store = self._store(tmp_path)
        t = templates.normalize_template(
            {
                "id": "tpl",
                "name": "T",
                "steps": [{"method": "shortmaker.export"}],
                "defaultControls": {"count": 2},
                "exportTargets": ["tiktok"],
            }
        )
        store.save(t)
        assert store.get("tpl") == t
        assert store.list() == [t]
        assert store.delete("tpl") is True
        assert store.list() == []

    def test_delete_missing_returns_false(self, tmp_path):
        assert self._store(tmp_path).delete("nope") is False

    def test_corrupt_file_treated_as_empty(self, tmp_path):
        path = tmp_path / "templates.json"
        path.write_text("{ not json", encoding="utf-8")
        assert templates.TemplateStore(path).list() == []
