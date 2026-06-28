"""Tests for the M1a routing-policy READ (fail-CLOSED to local).

The ``models.overview`` compose (M1a) surfaces the persisted ``RoutingPolicy``.
GATE-2 (M3 — fail-closed egress) requires that a corrupt / missing / half-written
policy NEVER fails open to cloud: it MUST resolve to ``global:'local'`` (zero
egress) and an out-of-enum mode MUST be clamped to ``local``. These tests pin
exactly that for the pure read used by the overview (M3 layers the WRITE +
``resolve_route`` on top of this same module).
"""

from __future__ import annotations

from typing import Any

import pytest
from media_studio.models import routing_policy as rp


def test_default_is_local_with_empty_overrides() -> None:
    """The default policy is local-only with no per-function overrides."""
    assert rp.DEFAULT_GLOBAL == "local"
    assert set(rp.VALID_MODES) == {"local", "cloud", "auto"}
    default = rp.default_routing_policy()
    assert default == {"global": "local", "overrides": {}}
    # a fresh object each call (no shared-mutable default leak)
    default["overrides"]["x"] = "cloud"
    assert rp.default_routing_policy() == {"global": "local", "overrides": {}}


def test_missing_policy_fails_closed_to_local() -> None:
    """No persisted policy at all -> the local default (zero egress)."""
    assert rp.read_routing_policy({}) == {"global": "local", "overrides": {}}


@pytest.mark.parametrize("corrupt", [None, "garbage", 42, [], 3.14])
def test_corrupt_non_dict_policy_fails_closed(corrupt: Any) -> None:
    """A non-dict (corrupt / half-written) policy fails CLOSED to local."""
    assert rp.read_routing_policy({"routingPolicy": corrupt}) == {"global": "local", "overrides": {}}


@pytest.mark.parametrize("bad_global", [None, "cloudy", "", 1, "AUTO"])
def test_out_of_enum_global_clamps_to_local(bad_global: Any) -> None:
    """An out-of-enum / non-string global mode clamps to local (fail-closed)."""
    out = rp.read_routing_policy({"routingPolicy": {"global": bad_global, "overrides": {}}})
    assert out == {"global": "local", "overrides": {}}


@pytest.mark.parametrize("good_global", ["local", "cloud", "auto"])
def test_valid_global_is_preserved(good_global: str) -> None:
    """A valid explicit global mode is preserved verbatim."""
    out = rp.read_routing_policy({"routingPolicy": {"global": good_global}})
    assert out["global"] == good_global
    assert out["overrides"] == {}


def test_valid_overrides_preserved() -> None:
    """Per-function overrides with valid modes survive the read verbatim."""
    out = rp.read_routing_policy(
        {"routingPolicy": {"global": "cloud", "overrides": {"select": "local", "vision": "auto"}}}
    )
    assert out == {"global": "cloud", "overrides": {"select": "local", "vision": "auto"}}


def test_out_of_enum_override_mode_clamps_to_local() -> None:
    """An override whose mode is out-of-enum or non-string clamps to local."""
    out = rp.read_routing_policy(
        {"routingPolicy": {"global": "cloud", "overrides": {"a": "nope", "b": 7, "c": "auto"}}}
    )
    assert out["overrides"] == {"a": "local", "b": "local", "c": "auto"}


def test_non_string_override_key_is_dropped() -> None:
    """A non-string override key is dropped (cannot name a function)."""
    out = rp.read_routing_policy({"routingPolicy": {"global": "local", "overrides": {5: "cloud", "ok": "cloud"}}})
    assert out["overrides"] == {"ok": "cloud"}


def test_non_dict_overrides_becomes_empty() -> None:
    """A non-dict ``overrides`` value degrades to an empty map (valid global kept)."""
    out = rp.read_routing_policy({"routingPolicy": {"global": "auto", "overrides": "oops"}})
    assert out == {"global": "auto", "overrides": {}}


def test_returned_overrides_is_independent_copy() -> None:
    """The read returns a fresh overrides dict (caller cannot poison the input)."""
    src = {"routingPolicy": {"global": "local", "overrides": {"a": "cloud"}}}
    out = rp.read_routing_policy(src)
    out["overrides"]["a"] = "auto"
    assert src["routingPolicy"]["overrides"]["a"] == "cloud"
