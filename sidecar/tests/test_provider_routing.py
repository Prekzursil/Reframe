"""Per-function routing preference for the rotation pool (WU-presets).

PLAN §WU-presets acceptance (b): "per-function override actually changes the
provider the corresponding seam uses (assert ``get_provider`` / ``get_translator``
/ vision pick)". The mechanism: the factory accepts a ``prefer`` provider id; the
matching configured provider is moved to the FRONT of the pool (tried first),
with the rest kept as failover and the local backstop always last. A ``prefer``
of the LOCAL sentinel yields a local-only pool (no cloud egress at all).
"""

from __future__ import annotations

from typing import Any

from media_studio.models import provider as P


def _settings(*providers: dict[str, Any]) -> dict[str, Any]:
    return {"providers": list(providers)}


_GROQ = {
    "id": "groq-gpt-oss-120b",
    "provider": "Groq",
    "baseUrl": "https://groq.example/v1",
    "model": "gpt-oss-120b",
    "apiKeys": ["gk-aaaa1111"],
    "capabilities": ["text"],
    "unit": "token",
}
_CEREBRAS = {
    "id": "cerebras-qwen3-235b",
    "provider": "Cerebras",
    "baseUrl": "https://cerebras.example/v1",
    "model": "qwen3-235b",
    "apiKeys": ["ck-bbbb2222"],
    "capabilities": ["text"],
    "unit": "token",
}


def test_no_prefer_keeps_configured_order() -> None:
    pool = P.build_pool_provider(_settings(_GROQ, _CEREBRAS), detect_local=False)
    # Cloud entries keep settings order; local backstop is last.
    providers = [e.provider for e in pool.entries]
    assert providers == ["Groq", "Cerebras", "local"]


def test_prefer_moves_matching_provider_to_front() -> None:
    # Configured order is Groq, Cerebras; preferring Cerebras must try it FIRST.
    pool = P.build_pool_provider(_settings(_GROQ, _CEREBRAS), detect_local=False, prefer="cerebras-qwen3-235b")
    providers = [e.provider for e in pool.entries]
    assert providers[0] == "Cerebras"
    # Groq is kept as failover; local is still last.
    assert "Groq" in providers
    assert providers[-1] == "local"


def test_prefer_unknown_id_is_a_no_op_not_an_error() -> None:
    pool = P.build_pool_provider(_settings(_GROQ, _CEREBRAS), detect_local=False, prefer="does-not-exist")
    providers = [e.provider for e in pool.entries]
    assert providers == ["Groq", "Cerebras", "local"]


def test_prefer_local_yields_local_only_pool_no_cloud_egress() -> None:
    pool = P.build_pool_provider(_settings(_GROQ, _CEREBRAS), detect_local=False, prefer=P.LOCAL_PROVIDER_ID)
    providers = [e.provider for e in pool.entries]
    # No cloud entry at all -> a privacy/local-only route sends nothing off-box.
    assert providers == ["local"]
    assert pool.provider_groups() == ()


def test_get_provider_threads_prefer_into_the_pool() -> None:
    pool = P.get_provider(_settings(_GROQ, _CEREBRAS), prefer="cerebras-qwen3-235b")
    assert isinstance(pool, P.RotatingProvider)
    assert [e.provider for e in pool.entries][0] == "Cerebras"


def test_get_provider_prefer_local_is_local_only() -> None:
    pool = P.get_provider(_settings(_GROQ, _CEREBRAS), prefer=P.LOCAL_PROVIDER_ID)
    assert isinstance(pool, P.RotatingProvider)
    assert [e.provider for e in pool.entries] == ["local"]


def test_prefer_with_non_list_providers_is_a_no_op() -> None:
    # A malformed providers value + a prefer must not raise (defensive guard):
    # the pool degrades to the local backstop only.
    pool = P.build_pool_provider({"providers": "garbage"}, detect_local=False, prefer="x")
    assert [e.provider for e in pool.entries] == ["local"]


def test_prefer_routes_first_call_to_the_preferred_provider() -> None:
    # End-to-end: a fake transport records which base_url the FIRST chat hits.
    hits: list[str] = []

    def transport(url: str, body: dict[str, Any], headers: dict[str, str], timeout: float) -> dict[str, Any]:
        hits.append(url)
        return {"choices": [{"message": {"content": "ok"}}]}

    pool = P.build_pool_provider(
        _settings(_GROQ, _CEREBRAS),
        detect_local=False,
        prefer="cerebras-qwen3-235b",
        transport=transport,
    )
    pool.chat([{"role": "user", "content": "hi"}])
    # The preferred provider (Cerebras) was the first (and only) one hit.
    assert hits[0].startswith("https://cerebras.example/v1")
