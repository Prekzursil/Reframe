"""Routing-policy resolver — fail-CLOSED to local (M1a READ + M3 WRITE/resolve).

The ``models.overview`` thin compose (M1a) surfaces the persisted
``RoutingPolicy`` so the UI can render the global Local/Cloud/Auto toggle and any
per-function overrides. A :class:`RoutingPolicy` is the single source of routing
truth (DESIGN §2.1/§2.3):

    ``{global: 'local'|'cloud'|'auto', overrides: {<fn>: <mode>}}``

GATE-2 (Risk #3 — silent cloud egress) makes every read **fail CLOSED**: a
corrupt, missing, or half-written policy MUST resolve to ``global:'local'`` (zero
egress), never fail open or crash, and an out-of-enum mode is **clamped to
local**. This module is the SINGLE store + PURE policy resolver (import-light, no
I/O of its own — the bytes live in the §2 settings document under
``routingPolicy``):

  * :func:`sanitize_routing_policy` clamps any candidate ``{global, overrides}``
    shape to a valid, JSON-safe policy (the corrupt-load AND the write-validate
    path share it, so the fail-closed default is one constant).
  * :func:`read_routing_policy` reads the persisted policy from a settings dict.
  * :func:`resolve_route` is the PURE policy resolver M3 owns:
    ``resolve_route(fn) = overrides[fn] ?? {mode: global}`` with the SAME clamp
    applied to the final resolved mode (a corrupt ``global`` can never resolve to
    silent cloud). It returns only ``{mode}`` — deliberately distinct from the
    §2.3-step-4 concrete ``{mode, model, runner|provider}`` resolver (M5) so the
    two layers do not collide.

The atomic ``models.setRoutingPolicy`` write lives in the system_ops handler; it
persists the :func:`sanitize_routing_policy` output through the settings store,
whose ``_write`` is an atomic temp-file + ``os.replace`` (mirrors
``library._write_json``).
"""

from __future__ import annotations

from typing import Any

#: The egress-safe default when no (or a corrupt) policy is persisted.
DEFAULT_GLOBAL: str = "local"

#: The valid routing modes (wire-stable). ``local`` never egresses; ``cloud`` uses
#: a provider key (shows egress + cost); ``auto`` prefers cloud but degrades to
#: local loudly. Anything else is corruption and is clamped to ``local``.
VALID_MODES: tuple[str, ...] = ("local", "cloud", "auto")


def default_routing_policy() -> dict[str, Any]:
    """Return a FRESH egress-safe default policy (``local`` global, no overrides).

    A new dict each call so a caller mutating the result can never poison the
    next read's default (no shared-mutable default leak).
    """
    return {"global": DEFAULT_GLOBAL, "overrides": {}}


def _clamp_mode(mode: Any) -> str:
    """Return ``mode`` if it is a valid enum member, else ``local`` (fail-closed)."""
    return mode if isinstance(mode, str) and mode in VALID_MODES else DEFAULT_GLOBAL


def sanitize_routing_policy(raw: Any) -> dict[str, Any]:
    """Clamp an arbitrary candidate policy to a valid ``{global, overrides}``.

    Shared by the corrupt-load read AND the ``models.setRoutingPolicy`` write so
    BOTH fail closed through one path: ``global`` is a valid mode (corrupt /
    missing / out-of-enum -> ``local``) and ``overrides`` maps string function
    names to valid modes (an out-of-enum override mode is clamped to ``local``; a
    non-string key is dropped). A wholly non-dict (corrupt / half-written) value
    degrades to :func:`default_routing_policy`. PURE: never raises, never mutates
    the input, opens no I/O.
    """
    if not isinstance(raw, dict):
        return default_routing_policy()
    global_mode = _clamp_mode(raw.get("global"))
    overrides_raw = raw.get("overrides")
    overrides: dict[str, str] = {}
    if isinstance(overrides_raw, dict):
        for fn, mode in overrides_raw.items():
            if isinstance(fn, str):
                overrides[fn] = _clamp_mode(mode)
    return {"global": global_mode, "overrides": overrides}


def read_routing_policy(settings: dict[str, Any]) -> dict[str, Any]:
    """Read the persisted ``RoutingPolicy`` from ``settings``, failing CLOSED.

    Thin wrapper over :func:`sanitize_routing_policy` on the ``routingPolicy``
    key of the §2 settings document. PURE: never raises, never mutates the input,
    opens no I/O.
    """
    return sanitize_routing_policy(settings.get("routingPolicy"))


def resolve_route(fn: str, settings: dict[str, Any]) -> dict[str, str]:
    """Resolve the routing ``{mode}`` for AI function ``fn`` (PURE, fail-closed).

    The single resolution rule (DESIGN §2.3 / GATE-2):
    ``resolve_route(fn) = overrides[fn] ?? {mode: global}``. Because the policy is
    read through :func:`read_routing_policy` (which clamps BOTH a corrupt
    ``global`` and any out-of-enum per-function override to ``local``), the FINAL
    resolved mode is always a valid enum member and a corrupt policy can never
    resolve to silent cloud egress. Returns only ``{mode}`` — distinct from the
    §2.3-step-4 concrete ``{mode, model, runner|provider}`` resolver (M5).
    """
    policy = read_routing_policy(settings)
    overrides = policy["overrides"]
    mode = overrides[fn] if fn in overrides else policy["global"]
    return {"mode": mode}


__all__ = [
    "DEFAULT_GLOBAL",
    "VALID_MODES",
    "default_routing_policy",
    "read_routing_policy",
    "resolve_route",
    "sanitize_routing_policy",
]
