"""Routing-policy READ — fail-CLOSED to local (M1a; M3 extends with the WRITE).

The ``models.overview`` thin compose (M1a) surfaces the persisted
``RoutingPolicy`` so the UI can render the global Local/Cloud/Auto toggle and any
per-function overrides. A :class:`RoutingPolicy` is the single source of routing
truth (DESIGN §2.1/§2.3):

    ``{global: 'local'|'cloud'|'auto', overrides: {<fn>: <mode>}}``

GATE-2 (Risk #3 — silent cloud egress) makes the READ **fail CLOSED**: a corrupt,
missing, or half-written policy MUST resolve to ``global:'local'`` (zero egress),
never fail open or crash, and an out-of-enum mode is **clamped to local**. This
module owns only that defensive read (PURE, import-light, no I/O); M3 layers the
atomic ``models.setRoutingPolicy`` write + ``resolve_route`` on the same shape.
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


def read_routing_policy(settings: dict[str, Any]) -> dict[str, Any]:
    """Read the persisted ``RoutingPolicy`` from ``settings``, failing CLOSED.

    Returns a JSON-safe ``{global, overrides}`` dict where ``global`` is a valid
    mode (corrupt / missing / out-of-enum -> ``local``) and ``overrides`` maps
    string function names to valid modes (an out-of-enum override mode is clamped
    to ``local``; a non-string key is dropped). A wholly non-dict (corrupt /
    half-written) policy degrades to :func:`default_routing_policy`. PURE: never
    raises, never mutates the input, opens no I/O.
    """
    raw = settings.get("routingPolicy")
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


__all__ = [
    "DEFAULT_GLOBAL",
    "VALID_MODES",
    "default_routing_policy",
    "read_routing_policy",
]
