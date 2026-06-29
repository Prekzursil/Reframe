"""Tests for the M5 CONCRETE routing resolver (DESIGN §2.3 step 4).

The pure policy resolver (:func:`routing_policy.resolve_route`) answers only the
abstract ``{mode}``. THIS layer (:mod:`routing_resolve`) resolves the concrete
``{mode, model, runner|provider}`` per AI function by reading the ``models.overview``
compose (local plan + detected runners + redacted providers) plus the persisted
``routing.perFunction`` model map. On a cloud failure (or no usable cloud target)
in ``cloud`` / ``auto`` it degrades LOUDLY to local with the
:data:`routing_resolve.ROUTE_DEGRADED_NOTICE` notice — never a silent center-of-
the-road cloud route.
"""

from __future__ import annotations

from typing import Any

from media_studio.models import routing_resolve as rr


def _overview(
    *,
    llm: str | None = "qwen2.5:7b",
    whisper: str | None = "large-v3-turbo",
    runners: list[dict[str, Any]] | None = None,
    providers: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """A minimal models.overview-shaped dict for the resolver to read."""
    return {
        "localPlan": {
            "llm": {"model": llm, "label": "LLM", "reason": "fits"},
            "whisper": {"model": whisper, "label": "ASR", "reason": "fits"},
        },
        "runners": runners if runners is not None else [{"kind": "ollama", "model": "qwen2.5:7b"}],
        "providers": providers
        if providers is not None
        else [{"id": "openrouter", "provider": "OpenRouter", "apiKeys": ["…abcd"]}],
    }


# --------------------------------------------------------------------------- #
# canonical function set
# --------------------------------------------------------------------------- #
class TestAiFunctions:
    def test_canonical_set(self) -> None:
        assert rr.AI_FUNCTIONS == ("asr", "select", "caption", "translation", "director")

    def test_every_function_has_a_label(self) -> None:
        assert set(rr.AI_FUNCTION_LABELS) == set(rr.AI_FUNCTIONS)
        assert all(rr.AI_FUNCTION_LABELS[fn] for fn in rr.AI_FUNCTIONS)

    def test_notice_is_loud(self) -> None:
        assert "degraded" in rr.ROUTE_DEGRADED_NOTICE
        assert "local" in rr.ROUTE_DEGRADED_NOTICE


# --------------------------------------------------------------------------- #
# local mode -> concrete local model + runner
# --------------------------------------------------------------------------- #
class TestLocalMode:
    def test_local_llm_function_picks_llm_model_and_runner(self) -> None:
        route = rr.resolve_concrete_route("select", {"routingPolicy": {"global": "local"}}, _overview())
        assert route == {
            "fn": "select",
            "mode": "local",
            "requestedMode": "local",
            "model": "qwen2.5:7b",
            "runner": "ollama",
            "provider": None,
            "degraded": False,
            "notice": None,
        }

    def test_local_asr_function_picks_whisper_model(self) -> None:
        route = rr.resolve_concrete_route("asr", {"routingPolicy": {"global": "local"}}, _overview())
        assert route["model"] == "large-v3-turbo"
        assert route["runner"] == "ollama"

    def test_default_policy_is_local(self) -> None:
        # No routingPolicy at all -> fail-closed to local (GATE-2).
        route = rr.resolve_concrete_route("select", {}, _overview())
        assert route["mode"] == "local"
        assert route["degraded"] is False

    def test_no_runner_falls_back_to_bundled(self) -> None:
        route = rr.resolve_concrete_route("select", {}, _overview(runners=[]))
        assert route["runner"] == rr.BUNDLED_RUNNER

    def test_runner_without_kind_is_skipped(self) -> None:
        route = rr.resolve_concrete_route("select", {}, _overview(runners=[{"model": "x"}, {"kind": "lmstudio"}]))
        assert route["runner"] == "lmstudio"

    def test_non_dict_runner_is_skipped(self) -> None:
        route = rr.resolve_concrete_route("select", {}, _overview(runners=["nope", {"kind": "ollama"}]))
        assert route["runner"] == "ollama"

    def test_missing_local_plan_model_is_empty_string(self) -> None:
        route = rr.resolve_concrete_route("select", {}, _overview(llm=None))
        assert route["model"] == ""

    def test_missing_local_plan_entirely(self) -> None:
        route = rr.resolve_concrete_route("select", {}, {"runners": [], "providers": []})
        assert route["model"] == ""
        assert route["runner"] == rr.BUNDLED_RUNNER


# --------------------------------------------------------------------------- #
# cloud / auto mode -> concrete provider target
# --------------------------------------------------------------------------- #
class TestCloudMode:
    def test_cloud_uses_first_usable_provider(self) -> None:
        settings = {"routingPolicy": {"global": "cloud"}}
        route = rr.resolve_concrete_route("select", settings, _overview())
        assert route["mode"] == "cloud"
        assert route["provider"] == "openrouter"
        assert route["runner"] is None
        assert route["degraded"] is False

    def test_cloud_model_from_per_function_routing(self) -> None:
        settings = {
            "routingPolicy": {"global": "cloud"},
            "routing": {"perFunction": {"select": {"provider": "anthropic/claude-3.5"}}},
        }
        route = rr.resolve_concrete_route("select", settings, _overview())
        assert route["model"] == "anthropic/claude-3.5"

    def test_cloud_model_falls_back_to_cloud_model_setting(self) -> None:
        settings = {"routingPolicy": {"global": "cloud"}, "cloudModel": "openai/gpt-4o"}
        route = rr.resolve_concrete_route("select", settings, _overview())
        assert route["model"] == "openai/gpt-4o"

    def test_local_sentinel_in_routing_is_ignored_for_cloud_model(self) -> None:
        settings = {
            "routingPolicy": {"global": "cloud"},
            "routing": {"perFunction": {"select": {"provider": "local"}}},
            "cloudModel": "openai/gpt-4o",
        }
        route = rr.resolve_concrete_route("select", settings, _overview())
        assert route["model"] == "openai/gpt-4o"

    def test_cloud_model_unknown_is_empty_string(self) -> None:
        route = rr.resolve_concrete_route("select", {"routingPolicy": {"global": "cloud"}}, _overview())
        assert route["model"] == ""

    def test_cloud_model_routing_per_function_not_dict(self) -> None:
        settings = {
            "routingPolicy": {"global": "cloud"},
            "routing": {"perFunction": "nope"},
            "cloudModel": "openai/gpt-4o",
        }
        route = rr.resolve_concrete_route("select", settings, _overview())
        assert route["model"] == "openai/gpt-4o"

    def test_cloud_model_slot_missing_for_function(self) -> None:
        settings = {
            "routingPolicy": {"global": "cloud"},
            "routing": {"perFunction": {"director": {"provider": "x/y"}}},
            "cloudModel": "openai/gpt-4o",
        }
        route = rr.resolve_concrete_route("select", settings, _overview())
        assert route["model"] == "openai/gpt-4o"

    def test_auto_with_provider_stays_auto(self) -> None:
        route = rr.resolve_concrete_route("select", {"routingPolicy": {"global": "auto"}}, _overview())
        assert route["mode"] == "auto"
        assert route["provider"] == "openrouter"


# --------------------------------------------------------------------------- #
# degrade-to-local (no usable cloud provider) — the LOUD notice
# --------------------------------------------------------------------------- #
class TestDegradeToLocal:
    def test_cloud_without_provider_degrades_loud(self) -> None:
        route = rr.resolve_concrete_route("select", {"routingPolicy": {"global": "cloud"}}, _overview(providers=[]))
        assert route["mode"] == "local"
        assert route["requestedMode"] == "cloud"
        assert route["degraded"] is True
        assert route["notice"] == rr.ROUTE_DEGRADED_NOTICE
        assert route["model"] == "qwen2.5:7b"
        assert route["runner"] == "ollama"
        assert route["provider"] is None

    def test_auto_without_provider_degrades_loud(self) -> None:
        route = rr.resolve_concrete_route("select", {"routingPolicy": {"global": "auto"}}, _overview(providers=[]))
        assert route["requestedMode"] == "auto"
        assert route["degraded"] is True

    def test_provider_without_key_is_not_usable(self) -> None:
        route = rr.resolve_concrete_route(
            "select",
            {"routingPolicy": {"global": "cloud"}},
            _overview(providers=[{"id": "openrouter", "apiKeys": []}]),
        )
        assert route["degraded"] is True

    def test_provider_with_blank_key_is_not_usable(self) -> None:
        route = rr.resolve_concrete_route(
            "select",
            {"routingPolicy": {"global": "cloud"}},
            _overview(providers=[{"id": "openrouter", "apiKeys": ["", "  "]}]),
        )
        assert route["degraded"] is True

    def test_non_dict_provider_skipped(self) -> None:
        route = rr.resolve_concrete_route(
            "select",
            {"routingPolicy": {"global": "cloud"}},
            _overview(providers=["nope", {"id": "or", "apiKeys": ["…wxyz"]}]),
        )
        assert route["provider"] == "or"

    def test_provider_without_id_skipped(self) -> None:
        route = rr.resolve_concrete_route(
            "select",
            {"routingPolicy": {"global": "cloud"}},
            _overview(providers=[{"apiKeys": ["…wxyz"]}, {"provider": "OR2", "apiKeys": ["…wxyz"]}]),
        )
        assert route["provider"] == "OR2"

    def test_provider_with_non_list_keys_skipped(self) -> None:
        route = rr.resolve_concrete_route(
            "select",
            {"routingPolicy": {"global": "cloud"}},
            _overview(providers=[{"id": "or", "apiKeys": "nope"}]),
        )
        assert route["degraded"] is True

    def test_degraded_asr_uses_whisper(self) -> None:
        route = rr.resolve_concrete_route("asr", {"routingPolicy": {"global": "cloud"}}, _overview(providers=[]))
        assert route["model"] == "large-v3-turbo"


# --------------------------------------------------------------------------- #
# per-function overrides win over the global mode
# --------------------------------------------------------------------------- #
class TestOverrides:
    def test_override_forces_local_even_when_global_cloud(self) -> None:
        settings = {"routingPolicy": {"global": "cloud", "overrides": {"select": "local"}}}
        route = rr.resolve_concrete_route("select", settings, _overview())
        assert route["mode"] == "local"
        assert route["provider"] is None

    def test_override_forces_cloud_even_when_global_local(self) -> None:
        settings = {"routingPolicy": {"global": "local", "overrides": {"select": "cloud"}}}
        route = rr.resolve_concrete_route("select", settings, _overview())
        assert route["mode"] == "cloud"
        assert route["provider"] == "openrouter"


# --------------------------------------------------------------------------- #
# resolve_all — one route per canonical function
# --------------------------------------------------------------------------- #
class TestResolveAll:
    def test_resolve_all_returns_one_route_per_function(self) -> None:
        routes = rr.resolve_all_routes({}, _overview())
        assert [r["fn"] for r in routes] == list(rr.AI_FUNCTIONS)

    def test_resolve_all_honors_mixed_policy(self) -> None:
        settings = {"routingPolicy": {"global": "local", "overrides": {"select": "cloud"}}}
        routes = {r["fn"]: r for r in rr.resolve_all_routes(settings, _overview())}
        assert routes["select"]["mode"] == "cloud"
        assert routes["asr"]["mode"] == "local"
