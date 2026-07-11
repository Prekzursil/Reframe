"""Cross-edit tests for media_studio.models.catalog.provider_label_for_id.

Covers the new public helper (added for the _wire.py readiness/consent lookups):
a known catalog model id resolves to its provider LABEL, an unknown id returns
None, and the ``catalog`` override kwarg is honoured. Both branches of the loop
(match found / never found) are exercised to keep 100% branch coverage.
"""

from __future__ import annotations

from media_studio.models.catalog import (
    CATALOG,
    provider_label_for_id,
)


def test_provider_label_for_id_known_id_returns_provider_label() -> None:
    # Loop match branch: entry.id == model_id -> return entry.provider.
    assert provider_label_for_id("groq-gpt-oss-120b") == "Groq"
    assert provider_label_for_id("gemini-2.5-flash-lite") == "Google AI Studio"


def test_provider_label_for_id_unknown_id_returns_none() -> None:
    # Loop-falls-through branch: no entry matches -> return None.
    assert provider_label_for_id("does-not-exist") is None


def test_provider_label_for_id_honours_catalog_override() -> None:
    # The override kwarg scans the supplied catalog, not the default CATALOG.
    only_openai = tuple(e for e in CATALOG if e.id == "openai-api")
    assert provider_label_for_id("openai-api", catalog=only_openai) == "OpenAI"
    # An id present in the default CATALOG but absent from the override -> None.
    assert provider_label_for_id("groq-gpt-oss-120b", catalog=only_openai) is None
