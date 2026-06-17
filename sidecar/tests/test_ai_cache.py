"""Unit tests for media_studio.models.ai_cache (WU-cache).

The cache is a small on-disk JSON store keyed by the sha256 of a *canonicalized*
AI request ``(messages, model, params)``. These tests pin the two contracts the
WU-cache spec calls falsifiable:

  * ``key()`` is a PURE, deterministic content hash: the same logical request
    always hashes the same; ANY change to content, model, or params yields a
    different key (dict-ordering / param-ordering must NOT matter).
  * ``get`` / ``put`` round-trip through an INJECTED store dir (a tmp path) with
    no network and no shared global state.

No real network, no model, no wall-clock — the store dir is the only side effect
and it lives entirely in the pytest ``tmp_path`` fixture.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from media_studio.models import ai_cache as cache_mod
from media_studio.models.ai_cache import AiCache


# --------------------------------------------------------------------------- #
# fixtures / helpers
# --------------------------------------------------------------------------- #
def _messages() -> list[dict[str, str]]:
    return [
        {"role": "system", "content": "You are concise."},
        {"role": "user", "content": "Pick the best moment."},
    ]


@pytest.fixture
def store(tmp_path: Path) -> AiCache:
    return AiCache(store_dir=tmp_path / "ai-cache")


# --------------------------------------------------------------------------- #
# key() — pure, deterministic content hash
# --------------------------------------------------------------------------- #
def test_key_is_sha256_hex(store: AiCache) -> None:
    key = store.key(_messages(), "qwen3-4b", {"temperature": 0.2})
    # sha256 hex digest is 64 lowercase hex chars.
    assert isinstance(key, str)
    assert len(key) == 64
    assert all(c in "0123456789abcdef" for c in key)


def test_key_deterministic_for_identical_request(store: AiCache) -> None:
    k1 = store.key(_messages(), "qwen3-4b", {"temperature": 0.2, "max_tokens": 64})
    k2 = store.key(_messages(), "qwen3-4b", {"temperature": 0.2, "max_tokens": 64})
    assert k1 == k2


def test_key_independent_of_param_dict_ordering(store: AiCache) -> None:
    # Canonicalization must sort keys: param insertion order is irrelevant.
    k1 = store.key(_messages(), "m", {"a": 1, "b": 2})
    k2 = store.key(_messages(), "m", {"b": 2, "a": 1})
    assert k1 == k2


def test_key_changes_when_content_changes(store: AiCache) -> None:
    base = store.key(_messages(), "m", {"t": 0})
    other_msgs = [
        {"role": "system", "content": "You are concise."},
        {"role": "user", "content": "Pick the WORST moment."},
    ]
    assert store.key(other_msgs, "m", {"t": 0}) != base


def test_key_changes_when_model_changes(store: AiCache) -> None:
    base = store.key(_messages(), "qwen3-4b", {"t": 0})
    assert store.key(_messages(), "gpt-4o-mini", {"t": 0}) != base


def test_key_changes_when_params_change(store: AiCache) -> None:
    base = store.key(_messages(), "m", {"temperature": 0.2})
    assert store.key(_messages(), "m", {"temperature": 0.9}) != base


def test_key_changes_when_param_added(store: AiCache) -> None:
    base = store.key(_messages(), "m", {"temperature": 0.2})
    assert store.key(_messages(), "m", {"temperature": 0.2, "max_tokens": 8}) != base


def test_key_empty_params_is_stable(store: AiCache) -> None:
    assert store.key(_messages(), "m", {}) == store.key(_messages(), "m", {})


# --------------------------------------------------------------------------- #
# get / put — round-trip in an injected tmp store dir
# --------------------------------------------------------------------------- #
def test_get_miss_returns_none(store: AiCache) -> None:
    key = store.key(_messages(), "m", {"t": 0})
    assert store.get(key) is None


def test_put_then_get_round_trip(store: AiCache) -> None:
    key = store.key(_messages(), "m", {"t": 0})
    result: dict[str, Any] = {"content": "clip 3", "scores": [0.9, 0.1]}
    store.put(key, result)
    assert store.get(key) == result


def test_put_round_trips_through_disk(tmp_path: Path) -> None:
    # A FRESH AiCache over the SAME dir must read what a prior instance wrote
    # (proves persistence, not in-memory caching).
    store_dir = tmp_path / "ai-cache"
    writer = AiCache(store_dir=store_dir)
    key = writer.key(_messages(), "m", {"t": 0})
    writer.put(key, {"content": "persisted"})

    reader = AiCache(store_dir=store_dir)
    assert reader.get(key) == {"content": "persisted"}


def test_put_creates_store_dir_lazily(tmp_path: Path) -> None:
    store_dir = tmp_path / "does-not-exist-yet"
    assert not store_dir.exists()
    store = AiCache(store_dir=store_dir)
    key = store.key(_messages(), "m", {"t": 0})
    store.put(key, {"ok": True})
    assert store_dir.is_dir()


def test_put_overwrites_existing_entry(store: AiCache) -> None:
    key = store.key(_messages(), "m", {"t": 0})
    store.put(key, {"v": 1})
    store.put(key, {"v": 2})
    assert store.get(key) == {"v": 2}


def test_distinct_requests_do_not_collide(store: AiCache) -> None:
    k1 = store.key(_messages(), "m1", {"t": 0})
    k2 = store.key(_messages(), "m2", {"t": 0})
    store.put(k1, {"which": "one"})
    store.put(k2, {"which": "two"})
    assert store.get(k1) == {"which": "one"}
    assert store.get(k2) == {"which": "two"}


def test_get_returns_none_on_corrupt_entry(store: AiCache, tmp_path: Path) -> None:
    # A truncated / non-JSON file on disk must be treated as a miss, never crash
    # the AI hot path.
    key = store.key(_messages(), "m", {"t": 0})
    store.put(key, {"ok": True})
    # Corrupt the backing file in place.
    entry_path = store.path_for(key)
    entry_path.write_text("{not valid json", encoding="utf-8")
    assert store.get(key) is None


def test_stored_file_is_json_on_disk(store: AiCache) -> None:
    key = store.key(_messages(), "m", {"t": 0})
    store.put(key, {"content": "hello"})
    raw = store.path_for(key).read_text(encoding="utf-8")
    assert json.loads(raw) == {"content": "hello"}


def test_default_store_dir_constant_exposed() -> None:
    # The module advertises a default sub-dir name for the data dir wiring WU.
    assert isinstance(cache_mod.DEFAULT_CACHE_DIRNAME, str)
    assert cache_mod.DEFAULT_CACHE_DIRNAME
