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


# --------------------------------------------------------------------------- #
# pure: expand_export_steps (preset fan-out — WU4)
# --------------------------------------------------------------------------- #
def _preset(preset_id: str, **overrides: Any) -> dict[str, Any]:
    """A minimal normalized-shape ExportPreset for fan-out tests (in-memory)."""
    base: dict[str, Any] = {
        "id": preset_id,
        "label": preset_id.title(),
        "aspect": "9:16",
        "minSec": 20,
        "maxSec": 60,
        "count": 5,
        "captionStyle": "libass",
        "reframeEngine": "auto",
    }
    base.update(overrides)
    return base


def _presets(*items: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {p["id"]: p for p in items}


class TestExpandExportSteps:
    def test_single_target_yields_one_export_step(self):
        steps = [{"method": "shortmaker.export", "params": {"exportTargets": ["tiktok"]}, "label": "Export"}]
        out = templates.expand_export_steps(steps, {}, _presets(_preset("tiktok")))
        assert len(out) == 1
        assert out[0]["method"] == "shortmaker.export"

    def test_three_targets_yield_three_export_steps_with_merged_fields(self):
        steps = [{"method": "shortmaker.export", "params": {"exportTargets": ["tiktok", "reels", "shorts"]}}]
        presets = _presets(
            _preset("tiktok", maxSec=45, count=5, captionStyle="libass"),
            _preset("reels", maxSec=30, count=3, captionStyle="none"),
            _preset("shorts", maxSec=60, count=8, captionStyle="libass"),
        )
        out = templates.expand_export_steps(steps, {"language": "en"}, presets)
        assert len(out) == 3
        # Each fanned-out step carries the preset's controls merged onto defaults.
        by_target = {s["params"]["presetId"]: s for s in out}
        assert by_target["tiktok"]["params"]["aspect"] == "9:16"
        assert by_target["tiktok"]["params"]["maxSec"] == 45
        assert by_target["tiktok"]["params"]["captionStyle"] == "libass"
        assert by_target["reels"]["params"]["maxSec"] == 30
        assert by_target["reels"]["params"]["captionStyle"] == "none"
        assert by_target["shorts"]["params"]["maxSec"] == 60
        # defaultControls is the base for every fanned step.
        assert all(s["params"]["language"] == "en" for s in out)

    def test_preset_fields_override_default_controls(self):
        steps = [{"method": "shortmaker.export", "params": {"exportTargets": ["tiktok"]}}]
        controls = {"maxSec": 99, "captionStyle": "none", "count": 1}
        out = templates.expand_export_steps(
            steps, controls, _presets(_preset("tiktok", maxSec=45, captionStyle="libass", count=5))
        )
        assert out[0]["params"]["maxSec"] == 45
        assert out[0]["params"]["captionStyle"] == "libass"
        assert out[0]["params"]["count"] == 5

    def test_window_clamp_from_preset_is_honored(self):
        # The preset carries the already-clamped [20,60] window; expansion must
        # surface those exact values (no re-derivation, no silent correction).
        steps = [{"method": "shortmaker.export", "params": {"exportTargets": ["tiktok"]}}]
        out = templates.expand_export_steps(steps, {}, _presets(_preset("tiktok", minSec=25, maxSec=55)))
        assert out[0]["params"]["minSec"] == 25
        assert out[0]["params"]["maxSec"] == 55

    def test_preset_id_attached_for_gallery_grouping(self):
        steps = [{"method": "shortmaker.export", "params": {"exportTargets": ["tiktok", "shorts"]}}]
        out = templates.expand_export_steps(steps, {}, _presets(_preset("tiktok"), _preset("shorts")))
        assert [s["params"]["presetId"] for s in out] == ["tiktok", "shorts"]

    def test_unknown_target_id_raises_and_yields_no_partial_expansion(self):
        steps = [{"method": "shortmaker.export", "params": {"exportTargets": ["tiktok", "__nope__"]}}]
        with pytest.raises(RpcError):
            templates.expand_export_steps(steps, {}, _presets(_preset("tiktok")))

    def test_empty_export_targets_passthrough_drops_no_export_step(self):
        # Documented rule: an export step with no targets passes through unchanged
        # (the runner still runs it against the template's defaultControls).
        steps = [{"method": "shortmaker.export", "params": {"exportTargets": []}, "label": "Export"}]
        out = templates.expand_export_steps(steps, {"count": 3}, {})
        assert out == steps

    def test_export_step_without_export_targets_key_passthrough(self):
        steps = [{"method": "shortmaker.export", "params": {"count": 3}}]
        out = templates.expand_export_steps(steps, {}, {})
        assert out == steps

    def test_non_export_steps_pass_through_unchanged_and_in_order(self):
        steps = [
            {"method": "transcribe.start", "params": {"videoId": "v1"}, "label": "Transcribe"},
            {"method": "phase8.select", "params": {}, "label": "Select"},
            {"method": "shortmaker.export", "params": {"exportTargets": ["tiktok"]}, "label": "Export"},
        ]
        out = templates.expand_export_steps(steps, {}, _presets(_preset("tiktok")))
        assert out[0] == steps[0]
        assert out[1] == steps[1]
        assert out[2]["method"] == "shortmaker.export"
        assert out[2]["params"]["presetId"] == "tiktok"

    def test_idempotent_on_already_flat_step_lists(self):
        # A list with no fan-out (single/no target) is returned shape-stable.
        steps = [{"method": "transcribe.start", "params": {}, "label": "T"}]
        out = templates.expand_export_steps(steps, {}, {})
        assert out == steps

    def test_label_carries_preset_for_multi_target_steps(self):
        steps = [{"method": "shortmaker.export", "params": {"exportTargets": ["tiktok", "shorts"]}, "label": "Export"}]
        out = templates.expand_export_steps(
            steps, {}, _presets(_preset("tiktok", label="TikTok"), _preset("shorts", label="Shorts"))
        )
        assert out[0]["label"] == "Export · TikTok"
        assert out[1]["label"] == "Export · Shorts"

    def test_export_targets_not_leaked_into_merged_params(self):
        # The control field that drove the fan-out is consumed, not forwarded to
        # the export handler (which has no use for it).
        steps = [{"method": "shortmaker.export", "params": {"exportTargets": ["tiktok"]}}]
        out = templates.expand_export_steps(steps, {}, _presets(_preset("tiktok")))
        assert "exportTargets" not in out[0]["params"]

    def test_multiple_export_steps_each_fan_out(self):
        steps = [
            {"method": "shortmaker.export", "params": {"exportTargets": ["tiktok", "shorts"]}, "label": "A"},
            {"method": "shortmaker.export", "params": {"exportTargets": ["reels"]}, "label": "B"},
        ]
        presets = _presets(_preset("tiktok"), _preset("shorts"), _preset("reels"))
        out = templates.expand_export_steps(steps, {}, presets)
        assert len(out) == 3
        assert [s["params"]["presetId"] for s in out] == ["tiktok", "shorts", "reels"]

    def test_partial_preset_only_merges_present_fields(self):
        # A preset missing a control field (e.g. reframeEngine) must NOT inject a
        # key — only the fields actually present override defaultControls.
        steps = [{"method": "shortmaker.export", "params": {"exportTargets": ["bare"]}}]
        bare = {"id": "bare", "label": "Bare", "maxSec": 40}
        out = templates.expand_export_steps(steps, {"reframeEngine": "auto"}, {"bare": bare})
        assert out[0]["params"]["maxSec"] == 40
        # reframeEngine stays the default-controls value (preset didn't carry one).
        assert out[0]["params"]["reframeEngine"] == "auto"
        assert "aspect" not in out[0]["params"]

    def test_source_step_params_preserved_alongside_preset_merge(self):
        # Non-fan-out params on the export step (e.g. a $N.key ref) survive.
        steps = [
            {
                "method": "shortmaker.export",
                "params": {"exportTargets": ["tiktok"], "videoId": "v1", "trackId": "$0.track.id"},
            }
        ]
        out = templates.expand_export_steps(steps, {}, _presets(_preset("tiktok")))
        assert out[0]["params"]["videoId"] == "v1"
        assert out[0]["params"]["trackId"] == "$0.track.id"
