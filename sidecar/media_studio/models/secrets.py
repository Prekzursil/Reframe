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
from collections.abc import Sequence

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
