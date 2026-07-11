"""Cross-edit coverage for the _wire.py provider-label resolution fixes.

Uniquely-named so it never collides with the consolidated
``test_handlers_readiness.py`` suite. Covers every branch added by the
reconcile fixes to ``_provider_has_key`` and ``_function_readiness_items``:

* ``_provider_has_key`` now resolves a catalog MODEL id to its provider LABEL
  before matching, so a routing slot carrying an id like ``groq-gpt-oss-120b``
  matches a provider entry keyed by the label ``Groq``. Both sides of the new
  ``if label:`` guard and the widened ``wanted & ident`` match are exercised.
* ``_function_readiness_items`` now resolves ``consent_id`` via
  ``catalog.provider_label_for_id(provider_id) or provider_id`` — both sides of
  the ``or`` (label found vs. label absent) are exercised.
"""

from __future__ import annotations

from typing import Any

from media_studio.handlers import _function_readiness_items, _provider_has_key

# A real catalog model id whose provider LABEL differs from the id (id/label split).
_MODEL_ID = "groq-gpt-oss-120b"
_LABEL = "Groq"


def _select_item(settings: dict[str, Any], providers: list[dict[str, Any]]) -> dict[str, Any]:
    items = _function_readiness_items(settings, providers)
    return next(item for item in items if item["capability"] == "ai.select")


# --------------------------------------------------------------------------- #
# _provider_has_key: label resolution
# --------------------------------------------------------------------------- #
def test_provider_has_key_matches_label_when_routing_carries_model_id() -> None:
    # label branch TRUE + widened match: model id resolves to 'Groq', which is
    # how the provider entry is keyed -> key found.
    providers = [{"id": "groq", "provider": _LABEL, "apiKeys": ["sk-real"]}]
    assert _provider_has_key(_MODEL_ID, providers) is True


def test_provider_has_key_label_resolved_but_no_matching_entry() -> None:
    # label branch TRUE but no entry carries the id OR the label -> no key.
    providers = [{"id": "other", "provider": "Other", "apiKeys": ["sk-real"]}]
    assert _provider_has_key(_MODEL_ID, providers) is False


def test_provider_has_key_no_label_falls_back_to_raw_id() -> None:
    # label branch FALSE: a non-catalog id resolves to no label, so only the raw
    # id is matched (prior behaviour preserved).
    providers = [{"id": "gpt", "provider": "gpt", "apiKeys": ["sk-real"]}]
    assert _provider_has_key("gpt", providers) is True


# --------------------------------------------------------------------------- #
# _function_readiness_items: consent_id label resolution (both sides of `or`)
# --------------------------------------------------------------------------- #
def test_function_readiness_consent_keyed_by_label_is_ready() -> None:
    # `or` LEFT side: label 'Groq' is truthy -> consent looked up under 'Groq'.
    settings = {
        "routing": {"perFunction": {"select": {"provider": _MODEL_ID, "fallback": []}}},
        "consent": {"perProvider": {_LABEL: {"text": True}}},
    }
    providers = [{"id": "groq", "provider": _LABEL, "apiKeys": ["sk-real"]}]
    assert _select_item(settings, providers)["status"] == "ready"


def test_function_readiness_label_consent_missing_needs_consent() -> None:
    # `or` LEFT side, consent absent under the LABEL -> needsConsent. Proves the
    # lookup key is the resolved label 'Groq', not the raw model id.
    settings = {
        "routing": {"perFunction": {"select": {"provider": _MODEL_ID, "fallback": []}}},
        "consent": {"perProvider": {_LABEL: {"text": False}}},
    }
    providers = [{"id": "groq", "provider": _LABEL, "apiKeys": ["sk-real"]}]
    item = _select_item(settings, providers)
    assert item["status"] == "needsConsent"
    assert item["action"] == {"kind": "setConsent", "provider": _MODEL_ID}


def test_function_readiness_non_catalog_id_falls_back_to_raw_id() -> None:
    # `or` RIGHT side: a non-catalog id resolves to no label, so consent is
    # looked up under the raw id.
    settings = {
        "routing": {"perFunction": {"select": {"provider": "gpt", "fallback": []}}},
        "consent": {"perProvider": {"gpt": {"text": True}}},
    }
    providers = [{"id": "gpt", "provider": "gpt", "apiKeys": ["sk-real"]}]
    assert _select_item(settings, providers)["status"] == "ready"
