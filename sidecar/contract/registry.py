"""Stable loader for the generated contract — the runtime consumption surface.

This module is hand-written (NOT generated): it loads the generated
``contract.schema.json`` and exposes the frozensets + schema lookups + the
``validate_request`` dispatch seam the sidecar will call. In the migration,
``media_studio`` imports THESE functions instead of hand-maintaining the
``needsKeyInjection`` allowlist and the scattered ``_require_*`` param checks.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any

from .validate import validate_params, validate_settings

_JSON_PATH = Path(__file__).resolve().parent / "generated" / "contract.schema.json"


@cache
def _contract() -> dict[str, Any]:
    return json.loads(_JSON_PATH.read_text(encoding="utf-8"))


def method_names() -> frozenset[str]:
    """Every method name declared in the contract."""
    return frozenset(_contract()["methodNames"])


def needs_key_injection() -> frozenset[str]:
    """The set of methods whose handler needs live provider keys injected."""
    return frozenset(_contract()["needsKeyInjection"])


def needs_key(method: str) -> bool:
    """The Python twin of ``keyBridge.ts``'s ``needsKeyInjection``."""
    return method in needs_key_injection()


def params_schema(method: str) -> dict[str, Any] | None:
    """The JSON Schema for a method's params, or ``None`` (no params / unmodeled)."""
    for m in _contract()["methods"]:
        if m["name"] == method:
            return m["paramsSchema"]
    return None


def settings_schema() -> dict[str, Any]:
    """The generated JSON Schema for the typed ``Settings`` object."""
    return _contract()["settingsSchema"]


def settings_defaults() -> dict[str, Any]:
    """The statically-known default value per modeled settings key."""
    return _contract()["settingsDefaults"]


def validate_request(method: str, params: Any) -> None:
    """Validate a request's params against the generated schema (the dispatch seam).

    A no-param or not-yet-modeled method validates as a no-op, so wiring this into
    dispatch is safe BEFORE every method is migrated (additive rollout).
    """
    validate_params(method, params, params_schema(method))


def validate_settings_object(obj: Any) -> None:
    """Validate a settings object against the generated ``SETTINGS_SCHEMA``."""
    validate_settings(obj, settings_schema())
