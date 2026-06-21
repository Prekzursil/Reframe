"""Tests for the device-aware auto-recommender (``media_studio.features.recommender``).

PURE module under test (WU-B1): turns the EXISTING advisor output + installed-state
+ detected local servers + ASR engine list into an actionable ``Recommendation``
plan. No probe, no GPU, no socket, no network — every input is a plain dict / list
injected here, exactly the wire shapes the WU-B2 handler will forward:

* ``report``         — the advisor wire dict (``recommendedPreset`` + ``components``)
* ``present``        — ``_models_present_map`` (``{component: bool}``)
* ``detected_local`` — ``detect_local_servers`` (``[PoolEntry]``)
* ``asr_engines``    — ``asr.engines`` (``{"engines": [{id,label,installed}]}``)

The catalog is INJECTED (a fake duck-typed catalog mirroring only the surface
``presets`` reads) so the routing resolution stays 100%-testable with no real
``catalog.py`` dependency, the same pattern ``tests/test_presets.py`` uses.
100% line + branch coverage.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest
from media_studio.features import recommender
from media_studio.features.recommender import recommend
from media_studio.models.presets import FUNCTIONS as _PRESET_FUNCTIONS
from media_studio.models.presets import LOCAL

# --------------------------------------------------------------------------- #
# Fake catalog (duck-typed; only the attributes presets reads via recommender)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class FakeEntry:
    """A minimal stand-in for the real ``CatalogEntry``."""

    id: str
    provider: str
    capabilities: tuple[str, ...]
    per_task_tier: dict[str, str]
    privacy_tier: str = "SAFE"


@dataclass
class FakeCatalog:
    """A tiny catalog the presets routing ranks/filters over."""

    entries: tuple[FakeEntry, ...] = field(default_factory=tuple)

    def all(self) -> tuple[FakeEntry, ...]:
        return self.entries


def _catalog() -> FakeCatalog:
    """A representative catalog: one cloud text model + one cloud vision model."""
    return FakeCatalog(
        entries=(
            FakeEntry(
                id="cloud-text",
                provider="groq",
                capabilities=("text",),
                per_task_tier={
                    "select": "S",
                    "subtitles": "A",
                    "translation": "A",
                    "vision": "na",
                    "editPlan": "S",
                },
                privacy_tier="SAFE",
            ),
            FakeEntry(
                id="cloud-vision",
                provider="openai",
                capabilities=("text", "vision"),
                per_task_tier={
                    "select": "B",
                    "subtitles": "B",
                    "translation": "B",
                    "vision": "A",
                    "editPlan": "B",
                },
                privacy_tier="CONDITIONAL",
            ),
        )
    )


# --------------------------------------------------------------------------- #
# Input builders (the wire shapes the handler forwards)
# --------------------------------------------------------------------------- #

# Track the routable functions from the single source of truth so adding a new
# one (e.g. WU-A3's "index") keeps the recommender's perFunction shape assertions
# correct without silently dropping coverage of the new route.
_FUNCTIONS = _PRESET_FUNCTIONS


def _component(name: str, *, verdict: str = "ok", present: bool = True) -> dict[str, Any]:
    """One advisor component wire dict (camelCase, as ``_advisor_report_to_wire``)."""
    return {
        "name": name,
        "present": present,
        "verdict": verdict,
        "vramMb": 1000,
        "licenseCommercialOk": True,
        "reason": f"{name} reason",
    }


def _report(
    *,
    preset: str = "balanced",
    components: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """An advisor wire report dict."""
    return {
        "components": components if components is not None else [_component("saliency")],
        "tiers": [],
        "recommendedPreset": preset,
        "vramBudgetMb": 8000,
        "notes": [],
    }


def _asr(*, parakeet_installed: bool = False) -> dict[str, Any]:
    """The ``asr.engines`` wire shape."""
    return {
        "engines": [
            {"id": "whisper", "label": "Whisper large-v3-turbo", "installed": True},
            {"id": "parakeet", "label": "Parakeet-TDT-0.6b-v3", "installed": parakeet_installed},
        ]
    }


def _pool_entry(
    *, kind: str = "ollama", model: str = "llama3", capabilities: list[str] | None = None
) -> dict[str, Any]:
    """A ``detect_local_servers`` PoolEntry wire dict."""
    return {
        "id": kind,
        "kind": kind,
        "base_url": f"http://localhost/{kind}",
        "model": model,
        "capabilities": capabilities if capabilities is not None else ["chat"],
        "unit": "req",
    }


def _rec(**overrides: Any) -> dict[str, Any]:
    """Call ``recommend`` with sensible defaults + per-test overrides."""
    kwargs: dict[str, Any] = {
        "report": _report(),
        "present": {"saliency": True},
        "detected_local": [],
        "asr_engines": _asr(),
        "offline": False,
        "commercial": False,
        "catalog": _catalog(),
    }
    kwargs.update(overrides)
    return recommend(**kwargs)


# --------------------------------------------------------------------------- #
# Shape / typed contract
# --------------------------------------------------------------------------- #
def test_returns_full_recommendation_shape() -> None:
    rec = _rec()
    assert set(rec) == {"preset", "routing", "asrEngine", "downloads", "rationale"}
    assert set(rec["routing"]) == {"perFunction"}
    assert set(rec["routing"]["perFunction"]) == set(_FUNCTIONS)
    for slot in rec["routing"]["perFunction"].values():
        assert "provider" in slot
    assert isinstance(rec["rationale"], list)
    assert all(isinstance(line, str) for line in rec["rationale"])
    assert isinstance(rec["downloads"], list)


# --------------------------------------------------------------------------- #
# AC(a) — privacy preset => every route is the LOCAL sentinel
# --------------------------------------------------------------------------- #
def test_privacy_preset_routes_every_function_local() -> None:
    rec = _rec(report=_report(preset="privacy"))
    assert rec["preset"] == "privacy"
    for fn, slot in rec["routing"]["perFunction"].items():
        assert slot["provider"] == LOCAL, fn
    # FALSIFIABLE: not a single cloud provider id leaks into a slot.
    assert all(slot["provider"] == LOCAL for slot in rec["routing"]["perFunction"].values())


def test_balanced_preset_keeps_cloud_text_local_vision() -> None:
    rec = _rec(report=_report(preset="balanced"))
    assert rec["preset"] == "balanced"
    pf = rec["routing"]["perFunction"]
    assert pf["select"]["provider"] == "cloud-text"
    assert pf["vision"]["provider"] == LOCAL


def test_best_free_cloud_preset_routes_cloud() -> None:
    rec = _rec(report=_report(preset="bestFreeCloud"))
    assert rec["preset"] == "bestFreeCloud"
    assert rec["routing"]["perFunction"]["select"]["provider"] == "cloud-text"


# --------------------------------------------------------------------------- #
# preset normalisation — tier preset + unknown both map to a routing preset
# --------------------------------------------------------------------------- #
def test_tier0_preset_maps_to_privacy() -> None:
    rec = _rec(report=_report(preset="tier0-numeric"))
    assert rec["preset"] == "privacy"
    assert all(s["provider"] == LOCAL for s in rec["routing"]["perFunction"].values())


def test_tier1_preset_maps_to_balanced() -> None:
    rec = _rec(report=_report(preset="tier1-multimodal"))
    assert rec["preset"] == "balanced"


def test_tier2_preset_maps_to_best_free_cloud() -> None:
    rec = _rec(report=_report(preset="tier2-vlm"))
    assert rec["preset"] == "bestFreeCloud"


def test_unknown_preset_falls_back_to_privacy() -> None:
    rec = _rec(report=_report(preset="totally-unknown"))
    assert rec["preset"] == "privacy"
    assert all(s["provider"] == LOCAL for s in rec["routing"]["perFunction"].values())


# --------------------------------------------------------------------------- #
# AC(c) — a detected local server captures the routes it can serve
# --------------------------------------------------------------------------- #
def test_detected_local_server_captures_text_routes() -> None:
    rec = _rec(
        report=_report(preset="bestFreeCloud"),
        detected_local=[_pool_entry(kind="ollama", model="llama3")],
    )
    pf = rec["routing"]["perFunction"]
    # text functions now route to the detected server (provider == its kind id)
    assert pf["select"]["provider"] == "ollama"
    assert pf["subtitles"]["provider"] == "ollama"
    # a rationale line names the detected server
    assert any("ollama" in line.lower() for line in rec["rationale"])


def test_detected_local_server_with_vision_captures_vision() -> None:
    rec = _rec(
        report=_report(preset="bestFreeCloud"),
        detected_local=[_pool_entry(kind="lmstudio", capabilities=["chat", "vision"])],
    )
    assert rec["routing"]["perFunction"]["vision"]["provider"] == "lmstudio"


def test_detected_local_text_only_leaves_vision_on_preset_route() -> None:
    # text-only local server must NOT capture the vision slot.
    rec = _rec(
        report=_report(preset="bestFreeCloud"),
        detected_local=[_pool_entry(kind="ollama", capabilities=["chat"])],
    )
    assert rec["routing"]["perFunction"]["vision"]["provider"] == "cloud-vision"


# --------------------------------------------------------------------------- #
# offline => cloud routes are downgraded to the local backstop
# --------------------------------------------------------------------------- #
def test_offline_downgrades_cloud_routes_to_local() -> None:
    rec = _rec(report=_report(preset="bestFreeCloud"), offline=True)
    for slot in rec["routing"]["perFunction"].values():
        assert slot["provider"] == LOCAL
    assert any("cloud routes are downgraded" in line.lower() for line in rec["rationale"])


def test_offline_with_all_local_preset_adds_no_downgrade_note() -> None:
    # privacy is already all-local => no route is rewritten => no downgrade line.
    rec = _rec(report=_report(preset="privacy"), offline=True)
    assert all(slot["provider"] == LOCAL for slot in rec["routing"]["perFunction"].values())
    assert not any("downgraded" in line.lower() for line in rec["rationale"])


# --------------------------------------------------------------------------- #
# downloads — runnable-but-missing components (AC(b), AC(c))
# --------------------------------------------------------------------------- #
def test_runnable_missing_registered_component_has_full_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    # When the mapped asset HAS a manifest entry, its real label + size are used.
    # Pinned via monkeypatch so the populated branch is deterministic.
    from media_studio.assets import manifest as _manifest

    fake = SimpleNamespace(label="RapidOCR PP-OCRv5", size_mb=20)
    monkeypatch.setattr(_manifest, "get_asset", lambda _name: fake)
    rec = _rec(
        report=_report(components=[_component("ocr", verdict="ok")]),
        present={"ocr": False},
    )
    names = [d["assetName"] for d in rec["downloads"]]
    assert "rapidocr-onnx" in names
    item = next(d for d in rec["downloads"] if d["assetName"] == "rapidocr-onnx")
    assert set(item) == {"assetName", "label", "sizeMb", "reason"}
    assert item["sizeMb"] == 20
    assert item["label"] == "RapidOCR PP-OCRv5"


def test_download_uses_asset_name_when_manifest_label_blank(monkeypatch: pytest.MonkeyPatch) -> None:
    # An entry with a blank label falls back to the asset name (the `or` branch).
    from media_studio.assets import manifest as _manifest

    monkeypatch.setattr(_manifest, "get_asset", lambda _name: SimpleNamespace(label="", size_mb=12))
    rec = _rec(
        report=_report(components=[_component("ocr", verdict="ok")]),
        present={"ocr": False},
    )
    item = next(d for d in rec["downloads"] if d["assetName"] == "rapidocr-onnx")
    assert item["label"] == "rapidocr-onnx"
    assert item["sizeMb"] == 12


def test_runnable_missing_component_without_manifest_entry_falls_back_to_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # When the mapped asset has NO manifest entry, the proposal falls back to the
    # asset name + a zero size so it stays actionable. Pinned via monkeypatch so the
    # branch is deterministic regardless of which feature modules registered assets.
    from media_studio.assets import manifest as _manifest

    monkeypatch.setattr(_manifest, "get_asset", lambda _name: None)
    rec = _rec(
        report=_report(components=[_component("saliency", verdict="ok")]),
        present={"saliency": False},
    )
    item = next(d for d in rec["downloads"] if d["assetName"] == "vinet-s-saliency")
    assert set(item) == {"assetName", "label", "sizeMb", "reason"}
    assert item["sizeMb"] == 0
    assert item["label"] == "vinet-s-saliency"


def test_offline_drops_all_downloads() -> None:
    rec = _rec(
        report=_report(components=[_component("saliency", verdict="ok")]),
        present={"saliency": False},
        offline=True,
    )
    assert rec["downloads"] == []
    assert any("offline" in line.lower() for line in rec["rationale"])


def test_already_installed_component_is_not_proposed() -> None:
    rec = _rec(
        report=_report(components=[_component("saliency", verdict="ok")]),
        present={"saliency": True},
    )
    assert rec["downloads"] == []


def test_unavailable_component_is_not_proposed() -> None:
    # unavailable verdict = not runnable => no download proposal even if missing.
    rec = _rec(
        report=_report(components=[_component("saliency", verdict="unavailable")]),
        present={"saliency": False},
    )
    assert rec["downloads"] == []


def test_degraded_component_is_still_runnable_and_proposed() -> None:
    rec = _rec(
        report=_report(components=[_component("saliency", verdict="degraded")]),
        present={"saliency": False},
    )
    assert [d["assetName"] for d in rec["downloads"]] == ["vinet-s-saliency"]


def test_component_without_registered_asset_is_skipped() -> None:
    # "motion" is a numeric floor component with no asset MAPPING -> never a download.
    rec = _rec(
        report=_report(components=[_component("motion", verdict="ok")]),
        present={"motion": False},
    )
    assert rec["downloads"] == []


def test_missing_present_entry_treated_as_not_installed() -> None:
    # component absent from the present map => treated as missing => proposed.
    rec = _rec(
        report=_report(components=[_component("saliency", verdict="ok")]),
        present={},
    )
    assert [d["assetName"] for d in rec["downloads"]] == ["vinet-s-saliency"]


def test_download_covered_by_detected_server_is_dropped() -> None:
    # AC(c): a detected server serving the model => its asset is NOT in downloads.
    # vlm_backbone is a vision component; a vision-capable local server covers it.
    rec = _rec(
        report=_report(
            preset="bestFreeCloud",
            components=[_component("vlm_backbone", verdict="ok")],
        ),
        present={"vlm_backbone": False},
        detected_local=[_pool_entry(kind="ollama", capabilities=["chat", "vision"])],
    )
    assert "siglip2-so400m" not in [d["assetName"] for d in rec["downloads"]]


def test_text_component_download_not_covered_by_vision_only_server() -> None:
    # a text-only detected server does NOT cover a vision component's download.
    rec = _rec(
        report=_report(components=[_component("vlm_backbone", verdict="ok")]),
        present={"vlm_backbone": False},
        detected_local=[_pool_entry(kind="ollama", capabilities=["chat"])],
    )
    assert "siglip2-so400m" in [d["assetName"] for d in rec["downloads"]]


# --------------------------------------------------------------------------- #
# asrEngine pick
# --------------------------------------------------------------------------- #
def test_asr_engine_prefers_installed_non_default() -> None:
    rec = _rec(asr_engines=_asr(parakeet_installed=True))
    assert rec["asrEngine"] == "parakeet"
    assert any("parakeet" in line.lower() for line in rec["rationale"])


def test_asr_engine_falls_back_to_whisper_when_only_whisper_installed() -> None:
    rec = _rec(asr_engines=_asr(parakeet_installed=False))
    assert rec["asrEngine"] == "whisper"


def test_asr_engine_picks_first_installed_when_present() -> None:
    engines = {"engines": [{"id": "custom", "label": "Custom", "installed": True}]}
    rec = _rec(asr_engines=engines)
    assert rec["asrEngine"] == "custom"


def test_asr_engine_none_when_no_engine_installed() -> None:
    engines = {"engines": [{"id": "whisper", "label": "Whisper", "installed": False}]}
    rec = _rec(asr_engines=engines)
    assert rec["asrEngine"] is None


def test_asr_engine_none_when_no_engines_listed() -> None:
    rec = _rec(asr_engines={"engines": []})
    assert rec["asrEngine"] is None


# --------------------------------------------------------------------------- #
# AC(d) — malformed / empty report => typed "unavailable" recommendation
# --------------------------------------------------------------------------- #
def test_empty_report_returns_unavailable_recommendation() -> None:
    rec = recommend(
        report={},
        present={},
        detected_local=[],
        asr_engines=_asr(),
        offline=False,
        catalog=_catalog(),
    )
    assert rec["preset"] == "privacy"
    assert rec["downloads"] == []
    assert rec["routing"]["perFunction"] == {}
    assert any("could not detect" in line.lower() for line in rec["rationale"])


def test_report_missing_preset_key_is_unavailable() -> None:
    rec = recommend(
        report={"components": [_component("saliency")]},
        present={},
        detected_local=[],
        asr_engines=_asr(),
        offline=False,
        catalog=_catalog(),
    )
    assert rec["routing"]["perFunction"] == {}
    assert rec["downloads"] == []
    assert any("could not detect" in line.lower() for line in rec["rationale"])


def test_non_dict_report_is_unavailable() -> None:
    rec = recommend(
        report=None,  # type: ignore[arg-type]
        present={},
        detected_local=[],
        asr_engines=_asr(),
        offline=False,
        catalog=_catalog(),
    )
    assert rec["routing"]["perFunction"] == {}
    assert any("could not detect" in line.lower() for line in rec["rationale"])


# --------------------------------------------------------------------------- #
# commercial passthrough (rationale only — provider routing is catalog-driven)
# --------------------------------------------------------------------------- #
def test_commercial_flag_noted_in_rationale() -> None:
    rec = _rec(commercial=True)
    assert any("commercial" in line.lower() for line in rec["rationale"])


def test_non_commercial_does_not_add_commercial_note() -> None:
    rec = _rec(commercial=False)
    assert not any("commercial" in line.lower() for line in rec["rationale"])


# --------------------------------------------------------------------------- #
# default catalog path (no injected catalog -> real CatalogAdapter, still pure)
# --------------------------------------------------------------------------- #
def test_default_catalog_is_used_when_not_injected() -> None:
    rec = recommend(
        report=_report(preset="privacy"),
        present={"saliency": True},
        detected_local=[],
        asr_engines=_asr(),
        offline=False,
    )
    # privacy still routes everything local with the real catalog.
    assert all(s["provider"] == LOCAL for s in rec["routing"]["perFunction"].values())


# --------------------------------------------------------------------------- #
# rationale always explains the chosen preset
# --------------------------------------------------------------------------- #
def test_rationale_names_the_preset() -> None:
    rec = _rec(report=_report(preset="balanced"))
    assert any("balanced" in line.lower() for line in rec["rationale"])


def test_malformed_components_entry_is_ignored() -> None:
    # a non-dict component entry must not crash download derivation.
    rec = _rec(
        report=_report(components=[_component("saliency", present=False), "not-a-dict"]),  # type: ignore[list-item]
        present={"saliency": False},
    )
    assert [d["assetName"] for d in rec["downloads"]] == ["vinet-s-saliency"]


def test_component_missing_name_is_ignored() -> None:
    rec = _rec(
        report=_report(components=[{"verdict": "ok", "present": False}]),
        present={},
    )
    assert rec["downloads"] == []


def test_module_exposes_recommend() -> None:
    assert callable(recommender.recommend)


# --------------------------------------------------------------------------- #
# helper: a detected server that captures NOTHING adds no rationale line
# --------------------------------------------------------------------------- #
def test_capture_local_servers_captures_nothing_when_only_vision_slot() -> None:
    # a text-only server over a vision-only routing map captures zero functions
    # => no provider is rewritten and no rationale line is appended.
    per_function: dict[str, Any] = {"vision": {"provider": "cloud-vision", "fallback": []}}
    rationale: list[str] = []
    recommender._capture_local_servers(
        per_function,
        [_pool_entry(kind="ollama", capabilities=["chat"])],
        rationale,
    )
    assert per_function["vision"]["provider"] == "cloud-vision"
    assert rationale == []


def test_capture_local_servers_falls_back_to_local_id_when_unidentifiable() -> None:
    # an entry with neither id nor kind => the LOCAL sentinel is used as its id.
    per_function: dict[str, Any] = {"select": {"provider": "cloud-text", "fallback": []}}
    rationale: list[str] = []
    recommender._capture_local_servers(per_function, [{"capabilities": ["chat"]}], rationale)
    assert per_function["select"]["provider"] == LOCAL
    assert any(LOCAL in line for line in rationale)
