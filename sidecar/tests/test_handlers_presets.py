"""WU-presets handlers: providers.applyPreset / setFunctionModel + routing wiring.

Tests the RPC surface (registered via ``register_all``) and the per-function
provider resolution: applying a preset persists ``routing.perFunction`` +
``activePreset``; ``setFunctionModel`` changes one slot; a per-function override
actually changes the provider id the corresponding seam prefers; the privacy
preset routes every function to local (zero cloud egress); the first-run chooser
is local-safe pre-choice and flips routing + sets ``firstRunChoiceMade`` on a
cloud choice.
"""

from __future__ import annotations

from typing import Any

import pytest
from media_studio import handlers as H
from media_studio import protocol
from media_studio.models import presets as presets_mod
from media_studio.models import provider as provider_mod


def _ctx() -> Any:
    return protocol.RpcContext(emit_notification=lambda _msg: None, jobs=None)


def _svc(tmp_path: Any) -> H.Services:
    return H.Services(data_dir=str(tmp_path))


# A configured pool whose ids match the catalog model-ids the presets pick.
def _configure_pool(svc: H.Services) -> None:
    svc.settings.set(
        {
            "providers": [
                {
                    "id": "groq-gpt-oss-120b",
                    "provider": "Groq",
                    "baseUrl": "https://groq.example/v1",
                    "model": "gpt-oss-120b",
                    "apiKeys": ["gk-aaaa1111"],
                    "capabilities": ["text"],
                    "unit": "token",
                },
                {
                    "id": "groq-llama-3.3-70b",
                    "provider": "GroqL",
                    "baseUrl": "https://groq.example/v1",
                    "model": "llama-3.3-70b",
                    "apiKeys": ["gk-bbbb2222"],
                    "capabilities": ["text"],
                    "unit": "token",
                },
            ]
        }
    )


# --------------------------------------------------------------------------- #
# Registration
# --------------------------------------------------------------------------- #


def test_applypreset_and_setfunctionmodel_registered(tmp_path: Any) -> None:
    registered: dict[str, Any] = {}
    H.register_all(_svc(tmp_path), register=lambda name, fn: registered.__setitem__(name, fn))
    assert "providers.applyPreset" in registered
    assert "providers.setFunctionModel" in registered


# --------------------------------------------------------------------------- #
# applyPreset
# --------------------------------------------------------------------------- #


def test_apply_privacy_preset_routes_every_function_to_local(tmp_path: Any) -> None:
    svc = _svc(tmp_path)
    _configure_pool(svc)
    out = svc.providers_apply_preset({"name": "privacy"}, _ctx())
    assert out["activePreset"] == "privacy"
    for fn in presets_mod.FUNCTIONS:
        assert out["routing"]["perFunction"][fn]["provider"] == presets_mod.LOCAL
    # Persisted.
    saved = svc.settings.get()
    assert saved["activePreset"] == "privacy"
    assert saved["routing"]["perFunction"]["select"]["provider"] == presets_mod.LOCAL


def test_apply_bestfreecloud_resolves_real_catalog_picks(tmp_path: Any) -> None:
    svc = _svc(tmp_path)
    _configure_pool(svc)
    out = svc.providers_apply_preset({"name": "bestFreeCloud"}, _ctx())
    pf = out["routing"]["perFunction"]
    # Real catalog top picks (NOT local) — proves the adapter is wired.
    assert pf["select"]["provider"] == "groq-gpt-oss-120b"
    assert pf["subtitles"]["provider"] == "groq-llama-3.3-70b"


def test_apply_unknown_preset_is_a_typed_error(tmp_path: Any) -> None:
    svc = _svc(tmp_path)
    with pytest.raises(protocol.RpcError):
        svc.providers_apply_preset({"name": "nope"}, _ctx())


def test_apply_preset_missing_name_is_invalid(tmp_path: Any) -> None:
    svc = _svc(tmp_path)
    with pytest.raises(protocol.RpcError):
        svc.providers_apply_preset({}, _ctx())


# --------------------------------------------------------------------------- #
# setFunctionModel
# --------------------------------------------------------------------------- #


def test_set_function_model_changes_one_slot(tmp_path: Any) -> None:
    svc = _svc(tmp_path)
    _configure_pool(svc)
    svc.providers_apply_preset({"name": "bestFreeCloud"}, _ctx())
    out = svc.providers_set_function_model({"function": "select", "provider": "groq-llama-3.3-70b"}, _ctx())
    assert out["routing"]["perFunction"]["select"]["provider"] == "groq-llama-3.3-70b"
    # Other slots untouched.
    assert out["routing"]["perFunction"]["subtitles"]["provider"] == "groq-llama-3.3-70b"
    # activePreset becomes "custom" once a slot is hand-edited.
    assert out["activePreset"] == "custom"


def test_set_function_model_to_local(tmp_path: Any) -> None:
    svc = _svc(tmp_path)
    _configure_pool(svc)
    out = svc.providers_set_function_model({"function": "vision", "provider": presets_mod.LOCAL}, _ctx())
    assert out["routing"]["perFunction"]["vision"]["provider"] == presets_mod.LOCAL


def test_set_function_model_unknown_function_is_invalid(tmp_path: Any) -> None:
    svc = _svc(tmp_path)
    with pytest.raises(protocol.RpcError):
        svc.providers_set_function_model({"function": "bogus", "provider": "x"}, _ctx())


def test_set_function_model_missing_provider_is_invalid(tmp_path: Any) -> None:
    svc = _svc(tmp_path)
    with pytest.raises(protocol.RpcError):
        svc.providers_set_function_model({"function": "select"}, _ctx())


# --------------------------------------------------------------------------- #
# Per-function override actually changes the provider the seam uses
# --------------------------------------------------------------------------- #


def test_function_prefer_resolves_routed_provider_id(tmp_path: Any) -> None:
    svc = _svc(tmp_path)
    _configure_pool(svc)
    svc.providers_set_function_model({"function": "select", "provider": "groq-llama-3.3-70b"}, _ctx())
    # The seam-resolution helper returns the routed provider id for "select".
    assert svc._function_prefer("select") == "groq-llama-3.3-70b"


def test_function_prefer_local_routes_local(tmp_path: Any) -> None:
    svc = _svc(tmp_path)
    _configure_pool(svc)
    svc.providers_apply_preset({"name": "privacy"}, _ctx())
    assert svc._function_prefer("select") == provider_mod.LOCAL_PROVIDER_ID


def test_function_prefer_unset_is_none(tmp_path: Any) -> None:
    svc = _svc(tmp_path)
    _configure_pool(svc)
    # No routing configured for this function -> no preference (pool order).
    assert svc._function_prefer("translation") is None


def test_function_prefer_malformed_routing_is_none(tmp_path: Any) -> None:
    # Defensive guard: a non-dict ``routing`` (corrupt settings) -> no preference.
    svc = _svc(tmp_path)
    svc.settings.set({"routing": "garbage"})
    assert svc._function_prefer("select") is None


def test_function_prefer_malformed_perfunction_is_none(tmp_path: Any) -> None:
    # Defensive guard: a non-dict ``perFunction`` -> no preference.
    svc = _svc(tmp_path)
    svc.settings.set({"routing": {"perFunction": "garbage"}})
    assert svc._function_prefer("select") is None


def test_function_prefer_malformed_slot_is_none(tmp_path: Any) -> None:
    # Defensive guard: a non-dict slot -> no preference.
    svc = _svc(tmp_path)
    svc.settings.set({"routing": {"perFunction": {"select": "garbage"}}})
    assert svc._function_prefer("select") is None


def test_select_seam_provider_prefers_routed_provider(tmp_path: Any) -> None:
    # The provider the select seam builds tries the routed provider FIRST. The M3
    # egress gate must ALLOW cloud first: with the RoutingPolicy global flipped to
    # cloud, the per-function route is honored (the gate only forces local when it
    # resolves to 'local').
    svc = _svc(tmp_path)
    _configure_pool(svc)
    svc.settings.set({"routingPolicy": {"global": "cloud"}})
    svc.providers_set_function_model({"function": "select", "provider": "groq-llama-3.3-70b"}, _ctx())
    pool = svc._provider_for_function("select")
    assert isinstance(pool, provider_mod.RotatingProvider)
    assert [e.provider for e in pool.entries][0] == "GroqL"  # the llama entry's provider name


# --------------------------------------------------------------------------- #
# M3 — RoutingPolicy egress gate at the _provider_for_function seam (GATE-2)
# --------------------------------------------------------------------------- #


def test_provider_for_function_local_policy_forces_local_pool(tmp_path: Any) -> None:
    # Even with a fully-configured cloud route for "select", the DEFAULT (and
    # explicit) RoutingPolicy global:'local' short-circuits to a LOCAL-ONLY pool —
    # NO cloud egress target is built (GATE-2 Risk #3, fail-closed by default).
    svc = _svc(tmp_path)
    _configure_pool(svc)
    svc.providers_set_function_model({"function": "select", "provider": "groq-llama-3.3-70b"}, _ctx())
    # no routingPolicy persisted -> the fail-closed local default applies
    pool = svc._provider_for_function("select")
    assert isinstance(pool, provider_mod.RotatingProvider)
    assert all(e.local for e in pool.entries), "local policy still carried a cloud egress target"


def test_provider_for_function_corrupt_policy_forces_local_pool(tmp_path: Any) -> None:
    # A corrupt persisted RoutingPolicy fails CLOSED to local at the egress seam,
    # never silently to cloud.
    svc = _svc(tmp_path)
    _configure_pool(svc)
    svc.providers_set_function_model({"function": "select", "provider": "groq-llama-3.3-70b"}, _ctx())
    svc.settings.set({"routingPolicy": "corrupt-not-a-dict"})
    pool = svc._provider_for_function("select")
    assert all(e.local for e in pool.entries), "corrupt policy must fail closed to local"


def test_provider_for_function_override_local_forces_local_even_when_global_cloud(tmp_path: Any) -> None:
    # A per-function override of 'local' beats a global 'cloud' at the seam: the
    # select function is forced local while other functions could still egress.
    svc = _svc(tmp_path)
    _configure_pool(svc)
    svc.providers_set_function_model({"function": "select", "provider": "groq-llama-3.3-70b"}, _ctx())
    svc.settings.set({"routingPolicy": {"global": "cloud", "overrides": {"select": "local"}}})
    pool = svc._provider_for_function("select")
    assert all(e.local for e in pool.entries), "override 'local' must force the local pool"


def test_translation_seam_translator_prefers_routed_provider(tmp_path: Any) -> None:
    svc = _svc(tmp_path)
    _configure_pool(svc)
    svc.providers_set_function_model({"function": "translation", "provider": "groq-llama-3.3-70b"}, _ctx())
    translator = svc._translator_for_function("translation")
    hosted = translator._hosted_provider()
    assert [e.provider for e in hosted.entries][0] == "GroqL"


# --------------------------------------------------------------------------- #
# First-run local-vs-cloud chooser
# --------------------------------------------------------------------------- #


def test_first_run_default_is_local_safe_before_choice(tmp_path: Any) -> None:
    svc = _svc(tmp_path)
    out = svc.providers_first_run({}, _ctx())
    assert out["firstRunChoiceMade"] is False
    assert out["default"] == "privacy"


def test_first_run_choose_cloud_flips_routing_and_sets_flag(tmp_path: Any) -> None:
    svc = _svc(tmp_path)
    _configure_pool(svc)
    out = svc.providers_first_run({"choice": "bestFreeCloud"}, _ctx())
    assert out["firstRunChoiceMade"] is True
    assert out["activePreset"] == "bestFreeCloud"
    # Routing flipped to cloud picks (not local).
    assert out["routing"]["perFunction"]["select"]["provider"] != presets_mod.LOCAL
    saved = svc.settings.get()
    assert saved["firstRunChoiceMade"] is True
    assert saved["activePreset"] == "bestFreeCloud"


def test_first_run_choose_local_sets_flag_keeps_privacy(tmp_path: Any) -> None:
    svc = _svc(tmp_path)
    _configure_pool(svc)
    out = svc.providers_first_run({"choice": "privacy"}, _ctx())
    assert out["firstRunChoiceMade"] is True
    assert out["activePreset"] == "privacy"
    for fn in presets_mod.FUNCTIONS:
        assert out["routing"]["perFunction"][fn]["provider"] == presets_mod.LOCAL


def test_first_run_invalid_choice_is_invalid(tmp_path: Any) -> None:
    svc = _svc(tmp_path)
    with pytest.raises(protocol.RpcError):
        svc.providers_first_run({"choice": "weird"}, _ctx())
