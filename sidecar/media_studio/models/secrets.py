"""Secret redaction + provider-error-body scrubbing (WU-keys, PLAN §WU-keys).

Two PURE, import-light helpers that keep API keys out of anything a user (or a
log file, or an RPC error payload) can see:

  * :func:`redact` — display-safe redaction that reveals at most the last 4
    characters of a key (and reveals NOTHING for short/empty keys, where the
    "last 4" would be the whole key).
  * :func:`scrub_error_body` — strips every known key AND any
    ``Authorization: Bearer <...>`` header value out of a raw provider error
    body BEFORE it can reach a log line or a JSON-RPC error message.

These are deliberately dependency-free (only :mod:`re` from the stdlib) so the
ENFORCEABLE-SCRUB invariant in PLAN §WU-keys — "no live key in any error body" —
is provable at the construction site that calls :func:`scrub_error_body`, not a
hope. They do NOT cross-import any other ``models/`` module.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from typing import Any

#: Marker substituted in place of any stripped secret. Visible so a scrubbed
#: body is recognizably scrubbed rather than silently truncated.
REDACTION_PLACEHOLDER: str = "[REDACTED]"

#: Number of trailing characters :func:`redact` is allowed to reveal.
_VISIBLE_TAIL: int = 4

#: Ellipsis prefix that marks a value as redacted in UI displays.
_ELLIPSIS: str = "…"

#: Matches an ``Authorization: Bearer <token>`` header (case-insensitive) and
#: captures the token so only the token is replaced, the header name preserved.
#: The token run is "non-space, non-newline" so a trailing message on its own
#: line is not swallowed.
_BEARER_RE = re.compile(
    r"(authorization\s*:\s*bearer\s+)(\S+)",
    re.IGNORECASE,
)


def redact(key: str) -> str:
    """Return a display-safe redaction of ``key`` revealing at most the last 4 chars.

    Long keys render as ``"…WXYZ"`` (ellipsis + last 4). Keys with 4 or fewer
    characters — where the "last 4" would expose the entire key — render as a
    bare ``"…"`` so nothing leaks. An empty key likewise renders as ``"…"``.
    """
    if len(key) > _VISIBLE_TAIL:
        return f"{_ELLIPSIS}{key[-_VISIBLE_TAIL:]}"
    return _ELLIPSIS


def scrub_error_body(text: str, keys: Sequence[str]) -> str:
    """Strip every key in ``keys`` and any ``Authorization: Bearer`` token from ``text``.

    Each non-empty key (and every occurrence of it) is replaced with
    :data:`REDACTION_PLACEHOLDER`; empty keys are ignored so they cannot match
    everywhere and erase the whole body. Any ``Authorization: Bearer <token>``
    header has its token replaced too — even a leaked bearer we never registered
    in ``keys`` — so the body is safe to log or surface over RPC. Surrounding,
    non-secret text is preserved verbatim.
    """
    scrubbed = text
    for key in keys:
        if key:
            scrubbed = scrubbed.replace(key, REDACTION_PLACEHOLDER)
    scrubbed = _BEARER_RE.sub(rf"\1{REDACTION_PLACEHOLDER}", scrubbed)
    return scrubbed


#: RPC param fields that carry live key material and must never reach a log line.
#: ``apiKey`` (providers.testKey), ``apiKeys`` (providers.upsert pool), and the
#: legacy single ``cloudApiKey`` are the key-bearing param names in §2;
#: ``_injectedKeys`` (WU-D2b-2) is the DPAPI-decrypted key bundle main injects on
#: provider-calling methods — the composition root pops it BEFORE dispatch logs
#: or records params, and listing it here is the belt-and-suspenders guarantee
#: that ANY diagnostic that ever sees it strips it wholesale.
_SECRET_PARAM_FIELDS: tuple[str, ...] = ("apiKey", "apiKeys", "cloudApiKey", "_injectedKeys")


def _redact_secret_fields(entry: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of ``entry`` with every known secret field value hidden.

    ``apiKeys`` (a list) is replaced element-for-element with
    :data:`REDACTION_PLACEHOLDER` so the field's SHAPE (how many keys) still
    reads in a log while NO character of any key survives; a non-list ``apiKeys``
    and the scalar ``apiKey`` / ``cloudApiKey`` fields are replaced wholesale.
    Non-secret fields are copied through verbatim.
    """
    out = dict(entry)
    for field in _SECRET_PARAM_FIELDS:
        if field not in out:
            continue
        value = out[field]
        if field == "apiKeys" and isinstance(value, list):
            out[field] = [REDACTION_PLACEHOLDER for _ in value]
        else:
            out[field] = REDACTION_PLACEHOLDER
    return out


def redact_params(params: Any) -> Any:
    """Return a log-safe copy of an RPC ``params`` object with NO key material.

    R7 (PLAN §WU D2 "DPAPI no-log"): a diagnostic that wants to record the
    originating RPC frame (``rpc.py`` crash/notification-failure paths) must not
    leak a live key. This strips every key-bearing field
    (:data:`_SECRET_PARAM_FIELDS`) — at the top level, inside a nested
    ``provider`` dict (``providers.upsert``'s single-entry shape), and inside a
    ``providers`` list (each dict entry) — replacing each with
    :data:`REDACTION_PLACEHOLDER`.

    PURE + defensive: the input is never mutated (the sidecar still needs the raw
    key), and a non-dict ``params`` (or a non-dict nested ``provider`` / list
    entry) is passed through unchanged rather than crashing the log path.
    """
    if not isinstance(params, dict):
        return params
    out = _redact_secret_fields(params)
    nested = out.get("provider")
    if isinstance(nested, dict):
        out["provider"] = _redact_secret_fields(nested)
    providers = out.get("providers")
    if isinstance(providers, list):
        out["providers"] = [_redact_secret_fields(p) if isinstance(p, dict) else p for p in providers]
    return out


def redact_keys(providers: Iterable[Any]) -> list[dict[str, Any]]:
    """Return a copy of ``providers`` with every ``apiKeys`` entry redacted to last-4.

    This is the RPC-facing transform (PLAN §WU-keys): the persisted
    ``settings.providers`` carries RAW keys, but anything that crosses RPC —
    ``settings.get`` and ``providers.list`` — must replace each key with its
    display-safe :func:`redact` form so NO full key ever leaves the sidecar.

    Each provider dict is shallow-copied (never mutated in place — the caller's
    RAW store stays intact) and its ``apiKeys`` list is rebuilt from
    :func:`redact`. Non-dict entries and missing/non-list ``apiKeys`` are passed
    through unchanged (defensive: a malformed settings file must not crash a read).
    """
    out: list[dict[str, Any]] = []
    for raw in providers:
        if not isinstance(raw, dict):
            continue
        entry = dict(raw)
        keys = entry.get("apiKeys")
        if isinstance(keys, list):
            entry["apiKeys"] = [redact(str(k)) for k in keys]
        out.append(entry)
    return out
