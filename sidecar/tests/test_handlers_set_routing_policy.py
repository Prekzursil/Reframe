"""Tests for the M3 ``models.setRoutingPolicy`` WRITE handler.

The WRITE half of the single ``RoutingPolicy`` store the M1a read surfaces. It
persists a sanitised ``{global, overrides}`` through the atomic settings store
(temp-file + ``os.replace``). GATE-2 (Risk #3 — silent cloud egress): a corrupt /
out-of-enum mode is clamped to ``local`` BEFORE persistence, a non-string
override key is dropped, and the handler NEVER raises on a malformed body. The
DECISION §4 default (``global:'local'``, no auto-promote) means the toggle only
ever moves on an explicit user write. These tests pin: registration, the
round-trip persist+read-back, the fail-closed clamp on write, the partial-merge
(other settings preserved), and that the returned policy is the sanitised one.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from media_studio import handlers
from media_studio.handlers import Services
from media_studio.protocol import RpcContext


def _services(tmp_path: Path) -> Services:
    return Services(data_dir=tmp_path / "data")


def _direct() -> RpcContext:
    return RpcContext(emit_notification=lambda obj: None, jobs=None)


# --------------------------------------------------------------------------- #
# (a) registration
# --------------------------------------------------------------------------- #
def test_register_all_wires_set_routing_policy(tmp_path: Path) -> None:
    registered: dict[str, Any] = {}
    handlers.register_all(
        services=Services(data_dir=tmp_path / "d"),
        register=lambda name, fn: registered.__setitem__(name, fn),
    )
    assert "models.setRoutingPolicy" in registered


# --------------------------------------------------------------------------- #
# (b) round-trip: write then read back through models.overview's policy read
# --------------------------------------------------------------------------- #
def test_set_routing_policy_persists_and_returns(tmp_path: Path) -> None:
    svc = _services(tmp_path)
    out = svc.models_set_routing_policy({"global": "auto", "overrides": {"select": "cloud"}}, _direct())
    assert out == {"routingPolicy": {"global": "auto", "overrides": {"select": "cloud"}}}
    # persisted: a fresh read sees exactly the sanitised policy
    from media_studio.models import routing_policy as rp

    assert rp.read_routing_policy(svc.settings.get()) == {
        "global": "auto",
        "overrides": {"select": "cloud"},
    }


def test_set_routing_policy_header_toggle_only_global(tmp_path: Path) -> None:
    """The header toggle sends only {global}; overrides default to empty."""
    svc = _services(tmp_path)
    out = svc.models_set_routing_policy({"global": "cloud"}, _direct())
    assert out == {"routingPolicy": {"global": "cloud", "overrides": {}}}


def test_set_routing_policy_empty_body_writes_local_default(tmp_path: Path) -> None:
    """An empty body sanitises to the egress-safe local default (no auto-promote)."""
    svc = _services(tmp_path)
    out = svc.models_set_routing_policy({}, _direct())
    assert out == {"routingPolicy": {"global": "local", "overrides": {}}}


# --------------------------------------------------------------------------- #
# (c) GATE-2 fail-closed clamp on WRITE
# --------------------------------------------------------------------------- #
def test_set_routing_policy_clamps_out_of_enum_global_to_local(tmp_path: Path) -> None:
    svc = _services(tmp_path)
    out = svc.models_set_routing_policy({"global": "sneaky-cloud"}, _direct())
    assert out["routingPolicy"]["global"] == "local"


def test_set_routing_policy_clamps_override_modes_and_drops_bad_keys(tmp_path: Path) -> None:
    svc = _services(tmp_path)
    out = svc.models_set_routing_policy(
        {"global": "cloud", "overrides": {"select": "nope", "vision": "auto", 7: "cloud"}},
        _direct(),
    )
    assert out["routingPolicy"] == {
        "global": "cloud",
        "overrides": {"select": "local", "vision": "auto"},
    }


def test_set_routing_policy_does_not_raise_on_non_dict_overrides(tmp_path: Path) -> None:
    svc = _services(tmp_path)
    out = svc.models_set_routing_policy({"global": "auto", "overrides": "oops"}, _direct())
    assert out["routingPolicy"] == {"global": "auto", "overrides": {}}


# --------------------------------------------------------------------------- #
# (d) partial merge: the write preserves unrelated settings
# --------------------------------------------------------------------------- #
def test_set_routing_policy_preserves_other_settings(tmp_path: Path) -> None:
    svc = _services(tmp_path)
    svc.settings.set({"asrEngine": "whisper", "phase8Tier": 2})
    svc.models_set_routing_policy({"global": "cloud"}, _direct())
    merged = svc.settings.get()
    assert merged["asrEngine"] == "whisper"
    assert merged["phase8Tier"] == 2
    assert merged["routingPolicy"] == {"global": "cloud", "overrides": {}}


def test_set_routing_policy_overwrites_previous_policy(tmp_path: Path) -> None:
    """A second write replaces the first (the store holds exactly one policy)."""
    svc = _services(tmp_path)
    svc.models_set_routing_policy({"global": "cloud", "overrides": {"select": "cloud"}}, _direct())
    out = svc.models_set_routing_policy({"global": "local"}, _direct())
    assert out["routingPolicy"] == {"global": "local", "overrides": {}}
