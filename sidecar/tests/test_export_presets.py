"""Tests for media_studio.features.export_presets — the export-preset catalog.

Pure store + pure normalization logic over a ``tmp_path`` JSON document (no I/O
seam to fake; storage is filesystem-only, mirroring ``test_recipes.py``'s
``RecipeStore`` tests). Covers seeding, upsert/delete/reset, the 20-60 s window
clamp, the ``captionStyle`` id-guard, corrupt-file recovery, and the atomic
temp+rename write (a simulated ``os.replace`` failure must leave the prior file
intact — no truncation).
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from media_studio.features import export_presets
from media_studio.protocol import RpcContext, RpcError


def _ctx() -> RpcContext:
    """The ``test_recipes.py`` direct-return idiom: no job registry needed."""
    return RpcContext(emit_notification=lambda *_: None, jobs=None)


# --------------------------------------------------------------------------- #
# pure: normalize_preset (window clamp + captionStyle guard + shaping)
# --------------------------------------------------------------------------- #
class TestNormalizePreset:
    def test_full_preset_normalized(self):
        p = export_presets.normalize_preset(
            {
                "id": "fixed",
                "label": "  My Preset  ",
                "aspect": "9:16",
                "minSec": 25,
                "maxSec": 45,
                "count": 4,
                "captionStyle": "bold",
                "reframeEngine": "verthor",
            }
        )
        assert p == {
            "id": "fixed",
            "label": "My Preset",
            "aspect": "9:16",
            "minSec": 25,
            "maxSec": 45,
            "count": 4,
            "captionStyle": "bold",
            "reframeEngine": "verthor",
        }

    def test_id_generated_when_absent(self):
        p = export_presets.normalize_preset(
            {"label": "x", "aspect": "9:16", "minSec": 20, "maxSec": 60, "count": 1, "captionStyle": "libass"}
        )
        assert p["id"]  # generated, non-empty

    def test_max_sec_clamped_above_window(self):
        p = export_presets.normalize_preset(
            {"label": "x", "aspect": "9:16", "minSec": 20, "maxSec": 600, "count": 1, "captionStyle": "libass"}
        )
        assert p["maxSec"] == export_presets.MAX_CLIP_SEC == 60

    def test_min_sec_clamped_below_window(self):
        p = export_presets.normalize_preset(
            {"label": "x", "aspect": "9:16", "minSec": 5, "maxSec": 60, "count": 1, "captionStyle": "libass"}
        )
        assert p["minSec"] == export_presets.MIN_CLIP_SEC == 20

    def test_max_sec_clamped_below_min_floor(self):
        # a maxSec below the window floor lands at the floor (never inverts).
        p = export_presets.normalize_preset(
            {"label": "x", "aspect": "9:16", "minSec": 20, "maxSec": 1, "count": 1, "captionStyle": "libass"}
        )
        assert p["maxSec"] == export_presets.MIN_CLIP_SEC == 20

    def test_min_sec_never_exceeds_clamped_max(self):
        # minSec is held at-or-below the (clamped) maxSec so the window can't invert.
        p = export_presets.normalize_preset(
            {"label": "x", "aspect": "9:16", "minSec": 55, "maxSec": 30, "count": 1, "captionStyle": "libass"}
        )
        assert p["minSec"] == 30
        assert p["maxSec"] == 30

    def test_in_range_window_preserved(self):
        p = export_presets.normalize_preset(
            {"label": "x", "aspect": "9:16", "minSec": 30, "maxSec": 50, "count": 1, "captionStyle": "libass"}
        )
        assert (p["minSec"], p["maxSec"]) == (30, 50)

    def test_count_floored_to_one(self):
        p = export_presets.normalize_preset(
            {"label": "x", "aspect": "9:16", "minSec": 20, "maxSec": 60, "count": 0, "captionStyle": "libass"}
        )
        assert p["count"] == 1

    @pytest.mark.parametrize("style", ["libass", "none", "bold", "neon", "mrbeast"])
    def test_valid_caption_style_accepted(self, style):
        p = export_presets.normalize_preset(
            {"label": "x", "aspect": "9:16", "minSec": 20, "maxSec": 60, "count": 1, "captionStyle": style}
        )
        assert p["captionStyle"] == style

    def test_invalid_caption_style_rejected(self):
        with pytest.raises(RpcError):
            export_presets.normalize_preset(
                {
                    "label": "x",
                    "aspect": "9:16",
                    "minSec": 20,
                    "maxSec": 60,
                    "count": 1,
                    "captionStyle": "__nope__",
                }
            )

    @pytest.mark.parametrize(("raw", "norm"), [("1:1", "1:1"), ("4:5", "4:5"), ("9x16", "9:16")])
    def test_multi_aspect_accepted_and_canonicalized(self, raw, norm):
        # WU R3: 1:1 + 4:5 are now valid export aspects alongside 9:16, and an
        # "WxH" form is canonicalized to "W:H".
        p = export_presets.normalize_preset(
            {"label": "x", "aspect": raw, "minSec": 20, "maxSec": 60, "count": 1, "captionStyle": "libass"}
        )
        assert p["aspect"] == norm

    @pytest.mark.parametrize("bad_aspect", ["16:9", "3:4", "potato", "9", "0:0"])
    def test_unsupported_or_garbage_aspect_rejected(self, bad_aspect):
        # A parseable-but-uncurated ratio (16:9) AND outright garbage both fail loud.
        with pytest.raises(RpcError):
            export_presets.normalize_preset(
                {"label": "x", "aspect": bad_aspect, "minSec": 20, "maxSec": 60, "count": 1, "captionStyle": "libass"}
            )

    @pytest.mark.parametrize(
        "bad",
        [
            {"aspect": "9:16", "minSec": 20, "maxSec": 60, "count": 1, "captionStyle": "libass"},  # no label
            {"label": "", "aspect": "9:16", "minSec": 20, "maxSec": 60, "count": 1, "captionStyle": "libass"},
            {"label": "x", "minSec": 20, "maxSec": 60, "count": 1, "captionStyle": "libass"},  # no aspect
            {"label": "x", "aspect": "", "minSec": 20, "maxSec": 60, "count": 1, "captionStyle": "libass"},
            {"label": "x", "aspect": "9:16", "maxSec": 60, "count": 1, "captionStyle": "libass"},  # no minSec
            {"label": "x", "aspect": "9:16", "minSec": "no", "maxSec": 60, "count": 1, "captionStyle": "libass"},
            {"label": "x", "aspect": "9:16", "minSec": 20, "count": 1, "captionStyle": "libass"},  # no maxSec
            {"label": "x", "aspect": "9:16", "minSec": 20, "maxSec": "no", "count": 1, "captionStyle": "libass"},
            {"label": "x", "aspect": "9:16", "minSec": 20, "maxSec": 60, "captionStyle": "libass"},  # no count
            {"label": "x", "aspect": "9:16", "minSec": 20, "maxSec": 60, "count": "no", "captionStyle": "libass"},
            {"label": "x", "aspect": "9:16", "minSec": 20, "maxSec": 60, "count": 1},  # no captionStyle
            {"label": "x", "aspect": "9:16", "minSec": 20, "maxSec": 60, "count": 1, "captionStyle": 7},  # not a str
            "nope",  # not an object
        ],
    )
    def test_rejects_malformed(self, bad: Any):
        with pytest.raises(RpcError):
            export_presets.normalize_preset(bad)

    def test_reframe_engine_defaults_to_auto(self):
        p = export_presets.normalize_preset(
            {"label": "x", "aspect": "9:16", "minSec": 20, "maxSec": 60, "count": 1, "captionStyle": "libass"}
        )
        assert p["reframeEngine"] == "auto"

    def test_invalid_reframe_engine_rejected(self):
        with pytest.raises(RpcError):
            export_presets.normalize_preset(
                {
                    "label": "x",
                    "aspect": "9:16",
                    "minSec": 20,
                    "maxSec": 60,
                    "count": 1,
                    "captionStyle": "libass",
                    "reframeEngine": "imovie",
                }
            )


# --------------------------------------------------------------------------- #
# seeds
# --------------------------------------------------------------------------- #
class TestSeeds:
    def test_seed_ids_are_the_three_vertical_platforms(self):
        ids = {s["id"] for s in export_presets.seed_presets()}
        assert ids == {"tiktok", "reels", "shorts"}

    def test_all_seeds_are_vertical_9x16(self):
        assert all(s["aspect"] == "9:16" for s in export_presets.seed_presets())

    def test_seeds_normalize_clean(self):
        # every seed survives normalize_preset unchanged (already in-window/valid).
        for s in export_presets.seed_presets():
            assert export_presets.normalize_preset(s) == s


# --------------------------------------------------------------------------- #
# PresetStore
# --------------------------------------------------------------------------- #
class TestPresetStore:
    def test_empty_store_seeds_three_vertical_presets(self, tmp_path):
        store = export_presets.PresetStore(tmp_path / "p.json")
        listed = store.list()
        assert {p["id"] for p in listed} == {"tiktok", "reels", "shorts"}
        assert all(p["aspect"] == "9:16" for p in listed)

    def test_seed_persisted_on_first_list(self, tmp_path):
        path = tmp_path / "p.json"
        export_presets.PresetStore(path).list()
        on_disk = json.loads(path.read_text(encoding="utf-8"))
        assert {p["id"] for p in on_disk} == {"tiktok", "reels", "shorts"}

    def test_save_upserts_by_id(self, tmp_path):
        store = export_presets.PresetStore(tmp_path / "p.json")
        store.save(
            {
                "id": "tiktok",
                "label": "TT2",
                "aspect": "9:16",
                "minSec": 20,
                "maxSec": 60,
                "count": 9,
                "captionStyle": "libass",
            }
        )
        listed = {p["id"]: p for p in store.list()}
        assert listed["tiktok"]["label"] == "TT2"
        assert listed["tiktok"]["count"] == 9

    def test_save_appends_new_id(self, tmp_path):
        store = export_presets.PresetStore(tmp_path / "p.json")
        saved = store.save(
            {
                "id": "custom",
                "label": "C",
                "aspect": "1:1",
                "minSec": 30,
                "maxSec": 600,
                "count": 2,
                "captionStyle": "libass",
            }
        )
        assert saved["maxSec"] == 60  # clamped on save
        assert any(p["id"] == "custom" for p in store.list())

    def test_save_rejects_invalid_caption_style_and_writes_nothing(self, tmp_path):
        path = tmp_path / "p.json"
        store = export_presets.PresetStore(path)
        store.list()  # seed first
        before = path.read_text(encoding="utf-8")
        with pytest.raises(RpcError):
            store.save(
                {
                    "id": "x",
                    "label": "x",
                    "aspect": "9:16",
                    "minSec": 20,
                    "maxSec": 60,
                    "count": 1,
                    "captionStyle": "__nope__",
                }
            )
        assert path.read_text(encoding="utf-8") == before  # untouched

    def test_delete_removes_and_reports(self, tmp_path):
        store = export_presets.PresetStore(tmp_path / "p.json")
        assert store.delete("tiktok") is True
        assert store.delete("tiktok") is False
        assert "tiktok" not in {p["id"] for p in store.list()}

    def test_reset_restores_seeds(self, tmp_path):
        store = export_presets.PresetStore(tmp_path / "p.json")
        store.delete("tiktok")
        restored = store.reset()
        ids = {p["id"] for p in restored}
        assert ids == {"tiktok", "reels", "shorts"}
        assert {p["id"] for p in store.list()} == {"tiktok", "reels", "shorts"}

    def test_corrupt_file_reseeds(self, tmp_path):
        path = tmp_path / "p.json"
        path.write_text("not json{", encoding="utf-8")
        # a corrupt catalog recovers to the seeds (never crashes the list).
        assert {p["id"] for p in export_presets.PresetStore(path).list()} == {"tiktok", "reels", "shorts"}

    def test_non_list_file_reseeds(self, tmp_path):
        path = tmp_path / "p.json"
        path.write_text('{"oops": 1}', encoding="utf-8")
        assert {p["id"] for p in export_presets.PresetStore(path).list()} == {"tiktok", "reels", "shorts"}

    def test_non_dict_entries_filtered(self, tmp_path):
        path = tmp_path / "p.json"
        path.write_text(
            json.dumps(
                [
                    {"id": "keep", "label": "K", "aspect": "9:16", "minSec": 20, "maxSec": 60, "count": 1},
                    "garbage",
                ]
            ),
            encoding="utf-8",
        )
        assert [p["id"] for p in export_presets.PresetStore(path).list()] == ["keep"]

    def test_atomic_write_failure_leaves_prior_file_intact(self, tmp_path, monkeypatch):
        path = tmp_path / "p.json"
        store = export_presets.PresetStore(path)
        store.list()  # seed + write a valid file
        before = path.read_text(encoding="utf-8")

        def boom(_src: Any, _dst: Any) -> None:
            raise OSError("disk full")

        monkeypatch.setattr(export_presets.os, "replace", boom)
        with pytest.raises(OSError):
            store.save(
                {
                    "id": "custom",
                    "label": "C",
                    "aspect": "9:16",
                    "minSec": 20,
                    "maxSec": 60,
                    "count": 1,
                    "captionStyle": "libass",
                }
            )
        # the original file is byte-for-byte intact (temp+rename never truncates it).
        assert path.read_text(encoding="utf-8") == before


# --------------------------------------------------------------------------- #
# ExportPresets — direct-return CRUD handlers (WU2 RPC surface)
# --------------------------------------------------------------------------- #
class TestExportPresetsHandlers:
    def _svc(self, tmp_path) -> export_presets.ExportPresets:
        return export_presets.ExportPresets(export_presets.PresetStore(tmp_path / "p.json"))

    def test_list_returns_seeded_presets(self, tmp_path):
        out = self._svc(tmp_path).list({}, _ctx())
        assert {p["id"] for p in out["presets"]} == {"tiktok", "reels", "shorts"}

    def test_save_returns_clamped_preset_and_list_reflects_it(self, tmp_path):
        svc = self._svc(tmp_path)
        out = svc.save(
            {
                "preset": {
                    "id": "custom",
                    "label": "C",
                    "aspect": "9:16",
                    "minSec": 30,
                    "maxSec": 600,  # clamped to 60
                    "count": 2,
                    "captionStyle": "libass",
                }
            },
            _ctx(),
        )
        assert out["preset"]["maxSec"] == 60  # clamped on save
        listed = {p["id"] for p in svc.list({}, _ctx())["presets"]}
        assert "custom" in listed

    def test_save_requires_object(self, tmp_path):
        svc = self._svc(tmp_path)
        with pytest.raises(RpcError):
            svc.save({"preset": "nope"}, _ctx())

    def test_save_missing_preset_key_errors(self, tmp_path):
        svc = self._svc(tmp_path)
        with pytest.raises(RpcError):
            svc.save({}, _ctx())

    def test_delete_then_reset_restores_seed(self, tmp_path):
        svc = self._svc(tmp_path)
        assert svc.delete({"id": "tiktok"}, _ctx()) == {"ok": True}
        assert "tiktok" not in {p["id"] for p in svc.list({}, _ctx())["presets"]}
        restored = svc.reset({}, _ctx())
        assert {p["id"] for p in restored["presets"]} == {"tiktok", "reels", "shorts"}
        assert "tiktok" in {p["id"] for p in svc.list({}, _ctx())["presets"]}

    def test_delete_unknown_reports_false(self, tmp_path):
        svc = self._svc(tmp_path)
        assert svc.delete({"id": "__nope__"}, _ctx()) == {"ok": False}

    def test_delete_requires_id(self, tmp_path):
        svc = self._svc(tmp_path)
        with pytest.raises(RpcError):
            svc.delete({}, _ctx())


# --------------------------------------------------------------------------- #
# register — the module owns its own register() (mirrors recipes.register)
# --------------------------------------------------------------------------- #
def test_register_installs_four_methods(tmp_path):
    registered: dict[str, Any] = {}
    export_presets.register(
        path=tmp_path / "export-presets.json",
        register_fn=lambda n, f: registered.__setitem__(n, f),
    )
    assert set(registered) == {
        "exportPresets.list",
        "exportPresets.save",
        "exportPresets.delete",
        "exportPresets.reset",
    }


def test_register_returns_service_bound_to_path(tmp_path):
    path = tmp_path / "export-presets.json"
    svc = export_presets.register(path=path, register_fn=lambda _n, _f: None)
    # the returned service writes to the bound path on first list (self-seed).
    svc.list({}, _ctx())
    assert path.exists()
