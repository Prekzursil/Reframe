"""Key-pool composition from the REDACTED provider list (M1a; M4 enriches usage).

The ``models.overview`` thin compose (M1a) surfaces a ``keyPool`` so the UI can
list each configured key as its own row. This module derives that list PURELY
from the ALREADY-REDACTED ``providers.list`` view (every ``apiKeys`` entry is the
display-safe last-4 — see :func:`media_studio.models.secrets.redact_keys`), so NO
full key is ever fabricated here. M4 layers live per-key usage / cooldown
(``GET /api/v1/key``) onto these rows; M1a only expands the redacted keys into
stable per-key entries.

A :class:`KeyPoolEntry` mirrors DESIGN §2.2 (``{id, providerId, redactedKey,
unit, status}``); ``status`` starts ``active`` (M4 flips it to ``cooldown`` on a
402/429). Malformed provider rows are skipped defensively — a corrupt settings
file must never crash the overview read.
"""

from __future__ import annotations

from typing import Any, TypedDict

#: The rate-limit unit assumed when a provider entry omits ``unit`` (local /
#: request-bounded servers are request-counted).
DEFAULT_UNIT: str = "req"

#: The starting per-key status; M4 flips it to ``cooldown`` on a 402/429.
DEFAULT_STATUS: str = "active"


class KeyPoolEntry(TypedDict):
    """One redacted key row the ``models.overview`` ``keyPool`` carries.

    ``id`` is a stable ``"<providerId>#<index>"`` slug; ``redactedKey`` is the
    last-4 redaction verbatim (never a full key); ``status`` starts ``active``.
    """

    id: str
    providerId: str
    redactedKey: str
    unit: str
    status: str


def build_key_pool(providers: list[Any]) -> list[KeyPoolEntry]:
    """Expand each REDACTED provider's keys into stable per-key pool entries.

    For every dict provider with a usable string id (``id`` or, as a fallback,
    the display ``provider`` name) and a list of redacted ``apiKeys``, emit one
    :class:`KeyPoolEntry` per non-blank key. Non-dict providers, providers
    without a usable id, and providers without a ``apiKeys`` LIST are skipped.
    The per-key index reflects the key's ORIGINAL position (a blank entry is
    dropped but does not renumber its siblings). PURE + key-safe: the
    ``redactedKey`` is exactly the (already-redacted) value supplied in.
    """
    out: list[KeyPoolEntry] = []
    for provider in providers:
        if not isinstance(provider, dict):
            continue
        provider_id = provider.get("id") or provider.get("provider")
        if not isinstance(provider_id, str) or not provider_id:
            continue
        keys = provider.get("apiKeys")
        if not isinstance(keys, list):
            continue
        raw_unit = provider.get("unit")
        unit = raw_unit if isinstance(raw_unit, str) and raw_unit else DEFAULT_UNIT
        for index, key in enumerate(keys):
            redacted = str(key)
            if not redacted:
                continue
            out.append(
                KeyPoolEntry(
                    id=f"{provider_id}#{index}",
                    providerId=provider_id,
                    redactedKey=redacted,
                    unit=unit,
                    status=DEFAULT_STATUS,
                )
            )
    return out


__all__ = ["DEFAULT_STATUS", "DEFAULT_UNIT", "KeyPoolEntry", "build_key_pool"]
