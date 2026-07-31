"""Tests for the M3 ``models.setRoutingPolicy`` WRITE handler.

The WRITE half of the single ``RoutingPolicy`` store the M1a read surfaces. It
persists a sanitised ``{global, overrides}`` through the atomic settings store
(temp-file + ``os.replace``). GATE-2 (Risk #3 — silent cloud egress): a corrupt /
out-of-enum mode is clamped to ``local`` BEFORE persistence, a non-string
override key is dropped, and the handler NEVER raises on a malformed body. The
DECISION §4 default (``global:'local'``, no auto-promote) means the toggle only
ever moves on an explicit user write.

The write is a PER-HALF PATCH, not a whole-key replace (F33/F35): the header
toggle owns ``global`` and the Advanced table owns ``overrides``, so an ABSENT
key inherits the persisted value instead of blanking it. Writing
``global:'local'`` still scrubs inherited cloud/auto pins so GATE-2 holds.

These tests pin: registration, the round-trip persist+read-back, the fail-closed
clamp on write, the partial-merge (other settings preserved), the per-half patch
in both directions + its egress consequence, and that the returned policy is the
sanitised one.
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


def test_set_routing_policy_header_local_scrubs_egress_pins(tmp_path: Path) -> None:
    """GATE-2: a header flip to Local drops INHERITED cloud/auto pins.

    F33 changed the write from a whole-key REPLACE to a per-half PATCH, so a
    second write no longer blanks the half it omits. The one case that still
    ends with ``overrides == {}`` is this GATE-2 scrub: writing
    ``global:'local'`` cannot leave an inherited cloud pin behind, or a user who
    clicked Local would still egress (``providers_ops._translator_for_function``).
    """
    svc = _services(tmp_path)
    svc.models_set_routing_policy({"global": "cloud", "overrides": {"select": "cloud"}}, _direct())
    out = svc.models_set_routing_policy({"global": "local"}, _direct())
    assert out["routingPolicy"] == {"global": "local", "overrides": {}}


# --------------------------------------------------------------------------- #
# (e) F33/F35 — the write is a PER-HALF PATCH, not a whole-key replace
# --------------------------------------------------------------------------- #
def test_header_toggle_preserves_existing_overrides(tmp_path: Path) -> None:
    """F33: a header-toggle {global} write must NOT erase the Advanced table's pins."""
    svc = _services(tmp_path)
    # The Advanced-table write (proven to land by ..._persists_and_returns above).
    first = svc.models_set_routing_policy({"global": "auto", "overrides": {"translation": "local"}}, _direct())
    assert first["routingPolicy"]["overrides"] == {"translation": "local"}
    # The header-toggle body, byte-identical to what App.tsx sends.
    out = svc.models_set_routing_policy({"global": "cloud"}, _direct())
    assert out["routingPolicy"] == {"global": "cloud", "overrides": {"translation": "local"}}


def test_header_toggle_preserves_the_local_egress_gate(tmp_path: Path) -> None:
    """F33 EGRESS proof at the resolver ``providers_ops`` actually consults.

    ``translation`` is used deliberately: it is one of the three functions with a
    live ``resolve_route`` consumer, so a wiped pin is real cloud egress rather
    than inert state loss.
    """
    svc = _services(tmp_path)
    svc.models_set_routing_policy({"global": "auto", "overrides": {"translation": "local"}}, _direct())
    svc.models_set_routing_policy({"global": "cloud"}, _direct())

    from media_studio.models import routing_policy as rp

    assert rp.resolve_route("translation", svc.settings.get()) == {"mode": "local"}


def test_overrides_only_write_preserves_persisted_global(tmp_path: Path) -> None:
    """F35: the table sends {overrides} only; the persisted global must SURVIVE."""
    svc = _services(tmp_path)
    svc.models_set_routing_policy({"global": "cloud"}, _direct())
    out = svc.models_set_routing_policy({"overrides": {"select": "local"}}, _direct())
    assert out["routingPolicy"] == {"global": "cloud", "overrides": {"select": "local"}}


def test_empty_body_against_an_existing_policy_is_a_no_op(tmp_path: Path) -> None:
    """An empty body patches nothing — it can neither promote NOR blank a policy."""
    svc = _services(tmp_path)
    svc.models_set_routing_policy({"global": "auto", "overrides": {"director": "cloud"}}, _direct())
    out = svc.models_set_routing_policy({}, _direct())
    assert out["routingPolicy"] == {"global": "auto", "overrides": {"director": "cloud"}}
