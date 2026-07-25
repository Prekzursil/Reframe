"""Tests for the Qwen3-VL backbone swap in the SmolVLM2 VLM re-rank seam (E.3).

Covers ONLY the PURE additions to :mod:`media_studio.features.smolvlm2`:
backbone resolution, the backbone->asset mapping, the default-factory selector,
the reranker's default-factory wiring (injected factory still wins), and the
Qwen3-VL asset registration (pinned 40-hex Apache-2.0 revisions). No
transformers / torch / model / video is imported anywhere — the heavy
``qwen3vl_backend.RealQwen3VlBackend`` is coverage-excluded, like its SmolVLM2
sibling. SmolVLM2 MUST remain the default (an unset ``vlmBackbone`` reproduces
today's behavior exactly).
"""

from __future__ import annotations

import re
from typing import Any

from media_studio.features import smolvlm2 as sv

_HEX40 = re.compile(r"^[0-9a-f]{40}$")


# --------------------------------------------------------------------------- #
# resolve_backbone (pure)
# --------------------------------------------------------------------------- #
class TestResolveBackbone:
    def test_none_settings_defaults_to_smolvlm2(self):
        assert sv.resolve_backbone(None) == sv.BACKBONE_SMOLVLM2

    def test_empty_settings_defaults_to_smolvlm2(self):
        assert sv.resolve_backbone({}) == sv.BACKBONE_SMOLVLM2
        assert sv.resolve_backbone({"vlmBackbone": ""}) == sv.BACKBONE_SMOLVLM2

    def test_explicit_smolvlm2(self):
        assert sv.resolve_backbone({"vlmBackbone": "smolvlm2"}) == sv.BACKBONE_SMOLVLM2

    def test_explicit_qwen_4b_and_8b(self):
        assert sv.resolve_backbone({"vlmBackbone": "qwen3vl-4b"}) == sv.BACKBONE_QWEN3VL_4B
        assert sv.resolve_backbone({"vlmBackbone": "qwen3vl-8b"}) == sv.BACKBONE_QWEN3VL_8B

    def test_bare_qwen_alias_maps_to_4b(self):
        # The bare "qwen3vl" alias picks the cheaper 4B ("large quality jump").
        assert sv.resolve_backbone({"vlmBackbone": "qwen3vl"}) == sv.BACKBONE_QWEN3VL_4B
        assert sv.resolve_backbone({"vlmBackbone": "qwen"}) == sv.BACKBONE_QWEN3VL_4B
        assert sv.resolve_backbone({"vlmBackbone": "qwen3-vl"}) == sv.BACKBONE_QWEN3VL_4B

    def test_instruct_suffix_aliases(self):
        assert sv.resolve_backbone({"vlmBackbone": "qwen3vl-4b-instruct"}) == sv.BACKBONE_QWEN3VL_4B
        assert sv.resolve_backbone({"vlmBackbone": "qwen3vl-8b-instruct"}) == sv.BACKBONE_QWEN3VL_8B

    def test_case_and_whitespace_insensitive(self):
        assert sv.resolve_backbone({"vlmBackbone": "  QWEN3VL-8B "}) == sv.BACKBONE_QWEN3VL_8B

    def test_unknown_falls_back_to_default(self):
        assert sv.resolve_backbone({"vlmBackbone": "gpt-5-vision"}) == sv.BACKBONE_SMOLVLM2

    def test_default_is_smolvlm2(self):
        assert sv.DEFAULT_BACKBONE == sv.BACKBONE_SMOLVLM2


# --------------------------------------------------------------------------- #
# backbone_asset_name (pure)
# --------------------------------------------------------------------------- #
class TestBackboneAssetName:
    def test_maps_each_backbone(self):
        assert sv.backbone_asset_name(sv.BACKBONE_SMOLVLM2) == sv.ASSET_NAME
        assert sv.backbone_asset_name(sv.BACKBONE_QWEN3VL_4B) == sv.QWEN3VL_4B_ASSET_NAME
        assert sv.backbone_asset_name(sv.BACKBONE_QWEN3VL_8B) == sv.QWEN3VL_8B_ASSET_NAME

    def test_unknown_backbone_falls_back_to_smolvlm2_asset(self):
        assert sv.backbone_asset_name("bogus") == sv.ASSET_NAME

    def test_backbone_vocabulary_frozen(self):
        assert frozenset({sv.BACKBONE_SMOLVLM2, sv.BACKBONE_QWEN3VL_4B, sv.BACKBONE_QWEN3VL_8B}) == sv.VLM_BACKBONES


# --------------------------------------------------------------------------- #
# select_backend_factory (pure) — the default-factory chooser
# --------------------------------------------------------------------------- #
class TestSelectBackendFactory:
    def test_default_selects_smolvlm2_factory(self):
        assert sv.select_backend_factory(None) is sv._default_backend_factory
        assert sv.select_backend_factory({}) is sv._default_backend_factory
        assert sv.select_backend_factory({"vlmBackbone": "smolvlm2"}) is sv._default_backend_factory

    def test_qwen_selects_qwen_factory(self):
        assert sv.select_backend_factory({"vlmBackbone": "qwen3vl-4b"}) is sv._default_qwen3vl_backend_factory
        assert sv.select_backend_factory({"vlmBackbone": "qwen3vl-8b"}) is sv._default_qwen3vl_backend_factory
        assert sv.select_backend_factory({"vlmBackbone": "qwen3vl"}) is sv._default_qwen3vl_backend_factory

    def test_unknown_selects_smolvlm2_factory(self):
        assert sv.select_backend_factory({"vlmBackbone": "nope"}) is sv._default_backend_factory


# --------------------------------------------------------------------------- #
# SmolVlmReranker default-factory wiring (injected factory still wins)
# --------------------------------------------------------------------------- #
class TestRerankerFactoryWiring:
    def test_default_settings_use_smolvlm2_factory(self):
        r = sv.SmolVlmReranker(settings={})
        assert r._factory is sv._default_backend_factory

    def test_qwen_settings_use_qwen_factory(self):
        r = sv.SmolVlmReranker(settings={"vlmBackbone": "qwen3vl-8b"})
        assert r._factory is sv._default_qwen3vl_backend_factory

    def test_injected_factory_wins_over_backbone(self):
        sentinel = lambda settings: None  # noqa: E731 - trivial fake factory
        r = sv.SmolVlmReranker(settings={"vlmBackbone": "qwen3vl-4b"}, backend_factory=sentinel)
        assert r._factory is sentinel

    def test_backbone_setting_does_not_break_rerank(self):
        # With an injected fake backend the re-rank behaves identically regardless
        # of the backbone setting (the swap only changes the DEFAULT factory).
        record: dict[str, Any] = {}

        class FakeBackend:
            def rank_clips(self, frames_per_clip: Any, prompt: str) -> list[float]:
                record["n"] = len(list(frames_per_clip))
                return [0.1, 0.9]  # clip 1 beats clip 0

        def factory(settings: Any) -> Any:
            return FakeBackend()

        def loader(path: str, spans: Any) -> list[Any]:
            return [[f"f@{lo}"] for lo, _hi in spans]

        cands = [{"start": 0.0, "end": 5.0, "hook": "a"}, {"start": 5.0, "end": 10.0, "hook": "b"}]
        r = sv.SmolVlmReranker(
            settings={"vlmBackbone": "qwen3vl-4b"},
            backend_factory=factory,
            clip_frame_loader=loader,
            media_path="x.mp4",
        )
        out = r.rerank_top_k(cands, top_k=2)
        assert [c["hook"] for c in out] == ["b", "a"]
        assert record["n"] == 2


# --------------------------------------------------------------------------- #
# asset registration — Qwen3-VL backbones registered with pinned Apache-2.0 revs
# --------------------------------------------------------------------------- #
class TestQwenAssetRegistration:
    def test_assets_registered_at_import(self):
        from media_studio.assets import manifest

        for name, model_id, revision in (
            (sv.QWEN3VL_4B_ASSET_NAME, sv.QWEN3VL_4B_MODEL_ID, sv.QWEN3VL_4B_REVISION),
            (sv.QWEN3VL_8B_ASSET_NAME, sv.QWEN3VL_8B_MODEL_ID, sv.QWEN3VL_8B_REVISION),
        ):
            entry = manifest.get_asset(name)
            assert entry is not None, f"{name} not registered"
            assert entry.kind == "model"
            assert entry.installer == "hf"
            assert entry.hf_repo == model_id
            assert entry.hf_revision == revision
            assert "Apache-2.0" in entry.label

    def test_revisions_are_pinned_40_hex(self):
        assert _HEX40.match(sv.QWEN3VL_4B_REVISION)
        assert _HEX40.match(sv.QWEN3VL_8B_REVISION)
        assert sv.QWEN3VL_4B_REVISION != sv.QWEN3VL_8B_REVISION

    def test_model_ids_are_qwen3_vl_instruct(self):
        assert sv.QWEN3VL_4B_MODEL_ID == "Qwen/Qwen3-VL-4B-Instruct"
        assert sv.QWEN3VL_8B_MODEL_ID == "Qwen/Qwen3-VL-8B-Instruct"

    def test_register_is_idempotent(self):
        # Re-registering the identical entries must not raise (module re-import safe).
        sv.register_qwen3vl_assets()
        sv.register_qwen3vl_assets()
