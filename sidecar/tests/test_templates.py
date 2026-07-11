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

import re
import time
from pathlib import Path
from typing import Any

import pytest
from media_studio.features import recipes, templates
from media_studio.jobs import JobRegistry
from media_studio.protocol import RpcContext, RpcError


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
            "convert.start",
            "audiomix.merge",
            "silence.trim",
            "tracks.audio.mux",
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
# guard: allowlist must not drift from the live method registry (G-10.6)
# --------------------------------------------------------------------------- #
class TestAllowlistMatchesRegistry:
    """Every allowlist entry must correspond to >=1 registered method.

    Falsifiable drift guard (the dropped ``"audio."`` prefix admitted nothing
    runnable). Scans the ``reg("name", ...)`` / ``register("name", ...)`` call
    sites across the live ``media_studio`` package and asserts each prefix +
    exact id in the allowlist matches at least one real registered method name,
    failing loud if any allowlist entry corresponds to zero real methods.
    """

    #: A method-registration call site: ``reg("x.y", ...)`` or ``register("x.y",
    #: ...)`` NOT preceded by ``.`` (so module ``foo.register(...)`` calls — which
    #: register a whole feature, not a method — are excluded) nor by a word char.
    _REG_CALL = re.compile(r"""(?:^|[^\w.])(?:reg|register)\(\s*["']([A-Za-z0-9_.]+)["']""")

    @classmethod
    def _registered_method_names(cls) -> set[str]:
        package_root = Path(templates.__file__).resolve().parent.parent
        names: set[str] = set()
        for py_file in package_root.rglob("*.py"):
            for match in cls._REG_CALL.finditer(py_file.read_text(encoding="utf-8")):
                names.add(match.group(1))
        return names

    def test_scan_finds_real_methods(self):
        # Guards the regex itself: a broken scan would return an empty set and make
        # every allowlist assertion below pass vacuously.
        names = self._registered_method_names()
        assert "shortmaker.export" in names
        assert "audiomix.merge" in names

    def test_every_exact_id_is_registered(self):
        names = self._registered_method_names()
        for method_id in templates.ALLOWED_METHOD_EXACT:
            assert method_id in names, f"allowlist exact id {method_id!r} matches no registered method"

    def test_every_prefix_matches_a_registered_method(self):
        names = self._registered_method_names()
        for prefix in templates.ALLOWED_METHOD_PREFIXES:
            assert any(name.startswith(prefix) for name in names), (
                f"allowlist prefix {prefix!r} matches no registered method"
            )


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


# --------------------------------------------------------------------------- #
# pure: bind_steps_to_source (WU5 — stamp the source videoId on every step)
# --------------------------------------------------------------------------- #
class TestBindStepsToSource:
    def test_stamps_video_id_on_every_step(self):
        steps = [{"method": "transcribe.start", "params": {}}, {"method": "phase8.select"}]
        out = templates.bind_steps_to_source(steps, "v9")
        assert all(s["params"]["videoId"] == "v9" for s in out)

    def test_does_not_clobber_explicit_video_id(self):
        steps = [{"method": "transcribe.start", "params": {"videoId": "explicit"}}]
        out = templates.bind_steps_to_source(steps, "v9")
        assert out[0]["params"]["videoId"] == "explicit"

    def test_preserves_other_params_and_step_fields(self):
        steps = [{"method": "shortmaker.export", "params": {"count": 3}, "label": "Export"}]
        out = templates.bind_steps_to_source(steps, "v9")
        assert out[0]["params"] == {"count": 3, "videoId": "v9"}
        assert out[0]["label"] == "Export"
        assert out[0]["method"] == "shortmaker.export"

    def test_does_not_mutate_input_steps(self):
        steps = [{"method": "transcribe.start", "params": {}}]
        templates.bind_steps_to_source(steps, "v9")
        assert steps[0]["params"] == {}  # original untouched (fresh copy)

    def test_empty_steps_yield_empty(self):
        assert templates.bind_steps_to_source([], "v9") == []

    def test_handles_step_without_params_key(self):
        out = templates.bind_steps_to_source([{"method": "phase8.select"}], "v9")
        assert out[0]["params"] == {"videoId": "v9"}


# --------------------------------------------------------------------------- #
# Templates — direct-return CRUD handlers
# --------------------------------------------------------------------------- #
def _ctx(registry: JobRegistry | None = None) -> RpcContext:
    return RpcContext(emit_notification=lambda *_: None, jobs=registry)


def _valid_template(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "tpl",
        "name": "Repurpose",
        "steps": [{"method": "shortmaker.export", "params": {"exportTargets": ["tiktok"]}}],
        "defaultControls": {"count": 3},
        "exportTargets": ["tiktok"],
    }
    base.update(overrides)
    return base


class TestCrudHandlers:
    def _svc(self, tmp_path, **kw: Any) -> templates.Templates:
        return templates.Templates(templates.TemplateStore(tmp_path / "templates.json"), **kw)

    def test_save_normalizes_and_persists(self, tmp_path):
        svc = self._svc(tmp_path)
        out = svc.save({"template": _valid_template()}, _ctx())
        assert out["template"]["name"] == "Repurpose"
        assert out["template"]["exportTargets"] == ["tiktok"]
        assert svc.list({}, _ctx())["templates"][0]["name"] == "Repurpose"

    def test_save_requires_object(self, tmp_path):
        svc = self._svc(tmp_path)
        with pytest.raises(RpcError):
            svc.save({"template": "nope"}, _ctx())

    def test_save_rejects_disallowed_method(self, tmp_path):
        svc = self._svc(tmp_path)
        with pytest.raises(RpcError):
            svc.save({"template": _valid_template(steps=[{"method": "shell.exec"}])}, _ctx())

    def test_list_empty(self, tmp_path):
        assert self._svc(tmp_path).list({}, _ctx())["templates"] == []

    def test_delete_handler(self, tmp_path):
        svc = self._svc(tmp_path)
        svc.save({"template": _valid_template()}, _ctx())
        assert svc.delete({"id": "tpl"}, _ctx())["ok"] is True
        assert svc.delete({"id": "tpl"}, _ctx())["ok"] is False

    def test_delete_requires_id(self, tmp_path):
        svc = self._svc(tmp_path)
        with pytest.raises(RpcError):
            svc.delete({}, _ctx())


# --------------------------------------------------------------------------- #
# Templates.apply — single-source run over the EXISTING recipe runner
# --------------------------------------------------------------------------- #
class TestApply:
    def _registry(self):
        events: list[tuple] = []

        def on_prog(jid, pct, msg):
            events.append(("progress", jid, pct, msg))

        def on_done(jid, result):
            events.append(("done", jid, result))

        return JobRegistry(emit_progress=on_prog, emit_done=on_done), events

    def _svc(self, tmp_path, *, methods, presets=None) -> templates.Templates:
        return templates.Templates(
            templates.TemplateStore(tmp_path / "templates.json"),
            methods_provider=lambda: methods,
            presets_provider=(lambda: presets) if presets is not None else None,
        )

    def test_apply_requires_template_id(self, tmp_path):
        svc = self._svc(tmp_path, methods={})
        with pytest.raises(RpcError):
            svc.apply({"videoId": "v1"}, _ctx())

    def test_apply_requires_video_id(self, tmp_path):
        svc = self._svc(tmp_path, methods={})
        with pytest.raises(RpcError):
            svc.apply({"templateId": "tpl"}, _ctx())

    def test_apply_unknown_template_raises(self, tmp_path):
        reg, _ = self._registry()
        svc = self._svc(tmp_path, methods={})
        with pytest.raises(RpcError):
            svc.apply({"templateId": "nope", "videoId": "v1"}, _ctx(reg))

    def test_apply_requires_registry(self, tmp_path):
        svc = self._svc(tmp_path, methods={}, presets={"tiktok": _preset("tiktok")})
        svc.save({"template": _valid_template()}, _ctx())
        with pytest.raises(RpcError):
            svc.apply({"templateId": "tpl", "videoId": "v1"}, _ctx(None))

    def test_apply_runs_steps_in_order_via_live_registry(self, tmp_path):
        reg, _ = self._registry()
        calls: list[tuple[str, dict]] = []

        def transcribe(params, ctx):
            calls.append(("transcribe", params))
            return {"ok": True}

        def export(params, ctx):
            calls.append(("export", params))
            return {"clips": []}

        presets = {"tiktok": _preset("tiktok")}
        svc = self._svc(
            tmp_path, methods={"transcribe.start": transcribe, "shortmaker.export": export}, presets=presets
        )
        svc.save(
            {
                "template": _valid_template(
                    steps=[
                        {"method": "transcribe.start", "params": {}},
                        {"method": "shortmaker.export", "params": {"exportTargets": ["tiktok"]}},
                    ]
                )
            },
            _ctx(),
        )
        out = svc.apply({"templateId": "tpl", "videoId": "vid42"}, _ctx(reg))
        assert "jobId" in out
        reg.get(out["jobId"]).wait(5)
        assert reg.get(out["jobId"]).status.value == "done"
        # steps ran in order, each bound to the source video id.
        assert calls[0][0] == "transcribe"
        assert calls[0][1]["videoId"] == "vid42"
        assert calls[1][0] == "export"
        assert calls[1][1]["videoId"] == "vid42"
        assert calls[1][1]["presetId"] == "tiktok"

    def test_apply_three_targets_produce_three_export_invocations(self, tmp_path):
        reg, _ = self._registry()
        exports: list[str] = []

        def export(params, ctx):
            exports.append(params["presetId"])
            return {"clips": []}

        presets = {pid: _preset(pid) for pid in ("tiktok", "reels", "shorts")}
        svc = self._svc(tmp_path, methods={"shortmaker.export": export}, presets=presets)
        svc.save(
            {
                "template": _valid_template(
                    steps=[{"method": "shortmaker.export", "params": {"exportTargets": ["tiktok", "reels", "shorts"]}}]
                )
            },
            _ctx(),
        )
        out = svc.apply({"templateId": "tpl", "videoId": "v1"}, _ctx(reg))
        reg.get(out["jobId"]).wait(5)
        assert reg.get(out["jobId"]).status.value == "done"
        assert exports == ["tiktok", "reels", "shorts"]

    def test_apply_subjob_export_is_awaited_and_unwrapped(self, tmp_path):
        reg, _ = self._registry()

        def export(params, ctx):
            def body(job_ctx):
                job_ctx.progress(50.0, "half")
                return {"clips": [params["presetId"]]}

            sub = ctx.jobs.start(body)
            return {"jobId": sub.id}

        presets = {"tiktok": _preset("tiktok")}
        svc = self._svc(tmp_path, methods={"shortmaker.export": export}, presets=presets)
        svc.save({"template": _valid_template()}, _ctx())
        out = svc.apply({"templateId": "tpl", "videoId": "v1"}, _ctx(reg))
        reg.get(out["jobId"]).wait(10)
        job = reg.get(out["jobId"])
        assert job.status.value == "done"
        # the inner sub-job result was unwrapped as the step result (recipe runner reuse).
        assert job.result["results"][0] == {"clips": ["tiktok"]}

    def test_apply_cancellation_propagates_via_existing_path(self, tmp_path):
        # Cancelling the parent job mid-run surfaces as a cancelled job through the
        # reused recipe runner's raise_if_cancelled (no new cancel machinery).
        reg, _ = self._registry()
        started = {"flag": False}

        def slow_export(params, ctx):
            def body(job_ctx):
                started["flag"] = True
                while not job_ctx.cancelled:
                    time.sleep(0.01)
                job_ctx.raise_if_cancelled()

            sub = ctx.jobs.start(body)
            return {"jobId": sub.id}

        presets = {"tiktok": _preset("tiktok")}
        svc = self._svc(tmp_path, methods={"shortmaker.export": slow_export}, presets=presets)
        svc.save({"template": _valid_template()}, _ctx())
        out = svc.apply({"templateId": "tpl", "videoId": "v1"}, _ctx(reg))
        while not started["flag"]:  # wait for the sub-job to actually be running
            reg.get(out["jobId"]).wait(0.01)
        reg.cancel(out["jobId"])
        reg.get(out["jobId"]).wait(10)
        assert reg.get(out["jobId"]).status.value == "cancelled"

    def test_apply_template_without_export_targets_runs_passthrough(self, tmp_path):
        # A template whose export step names no targets runs the step as-is (no
        # fan-out) — and the default empty preset catalog is fine.
        reg, _ = self._registry()
        calls: list[dict] = []

        def export(params, ctx):
            calls.append(params)
            return {"ok": 1}

        svc = templates.Templates(
            templates.TemplateStore(tmp_path / "templates.json"),
            methods_provider=lambda: {"shortmaker.export": export},
        )
        svc.save(
            {"template": _valid_template(steps=[{"method": "shortmaker.export", "params": {}}], exportTargets=[])},
            _ctx(),
        )
        out = svc.apply({"templateId": "tpl", "videoId": "v1"}, _ctx(reg))
        reg.get(out["jobId"]).wait(5)
        assert reg.get(out["jobId"]).status.value == "done"
        assert calls[0]["videoId"] == "v1"


# --------------------------------------------------------------------------- #
# register
# --------------------------------------------------------------------------- #
def test_register_installs_four_methods(tmp_path):
    registered: dict[str, Any] = {}
    templates.register(path=tmp_path / "templates.json", register_fn=lambda n, f: registered.__setitem__(n, f))
    assert set(registered) == {"templates.list", "templates.save", "templates.delete", "templates.apply"}


def test_register_returns_service_bound_to_path(tmp_path):
    svc = templates.register(path=tmp_path / "templates.json", register_fn=lambda *_: None)
    assert isinstance(svc, templates.Templates)
    svc.save({"template": _valid_template()}, _ctx())
    assert (tmp_path / "templates.json").exists()
