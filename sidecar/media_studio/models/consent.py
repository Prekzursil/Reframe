"""Per-data-type egress consent gate (WU-keys / SE1, PLAN §WU-keys acceptance (d)).

TEXT (transcripts) and FRAMES (vision) are SEPARATE, independently-revocable
opt-ins, stored at ``settings.consent.perProvider[<provider>] = {"text": bool,
"frames": bool}`` (see :data:`settings_store.DEFAULT_SETTINGS`). The *setter*
(``providers.setConsent``) lives in :mod:`handlers`; this module is the
ENFORCEMENT half — the typed gate any egress path MUST pass through before a
payload leaves the machine.

PLAN §WU-keys acceptance (d) requires that "a vision egress without frame
consent is **blocked**" and the test strategy requires a vision call without
``consent.perProvider[p].frames`` to be "refused (**typed**)". This module
supplies that typed refusal as a small, PURE, dependency-free primitive:

  * :func:`frame_consent_granted` / :func:`text_consent_granted` — pure
    predicates reading the consent block (default-deny: absent == not granted).
  * :func:`require_frame_consent` — raises :class:`ConsentError` (typed) unless
    frame consent is granted for the given provider; the *single* enforcement
    point a vision egress calls FIRST, before any frame is sampled or encoded.

The FULL control-flow wiring of this gate into ``handlers.phase8_select``'s
``job_body`` is assigned by PLAN to **WU-vision** (PLAN §WU-vision lines
208/210/214/217); WU-keys owns this consent primitive + its typed-refusal test
so the criterion is implemented and provable at the seam, not merely a hope.

Deliberately dependency-free (stdlib typing only) and crosses NO other
``models/`` module — consent carries booleans only, never a secret.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

#: The two distinct egress data types (SE1). FRAMES (vision) requires its OWN
#: confirmation, separate from TEXT (transcripts).
DATA_TYPE_TEXT: str = "text"
DATA_TYPE_FRAMES: str = "frames"


class ConsentError(RuntimeError):
    """Raised when an egress is attempted without the required per-data-type consent.

    This is the TYPED refusal PLAN §WU-keys acceptance (d) / test-strategy
    require: a vision (frame) egress without ``consent.perProvider[p].frames``
    raises this rather than silently proceeding. It carries the offending
    provider name and data type so a caller can surface a precise message — and
    NEVER a secret (consent state is booleans only).
    """

    def __init__(self, provider: str, data_type: str) -> None:
        self.provider = provider
        self.data_type = data_type
        super().__init__(
            f"{data_type} egress to provider {provider!r} refused: "
            f"consent.perProvider[{provider!r}].{data_type} is not granted"
        )


def _consent_flag(settings: Mapping[str, Any], provider: str, data_type: str) -> bool:
    """Return the stored consent flag for ``(provider, data_type)`` (default-deny).

    Reads ``settings.consent.perProvider[provider][data_type]`` defensively: a
    missing consent block, missing provider entry, missing flag, or any
    malformed (non-mapping) level all resolve to ``False`` — consent must be an
    EXPLICIT, present ``True`` to grant egress, never an absence.
    """
    consent = settings.get("consent")
    if not isinstance(consent, Mapping):
        return False
    per_provider = consent.get("perProvider")
    if not isinstance(per_provider, Mapping):
        return False
    entry = per_provider.get(provider)
    if not isinstance(entry, Mapping):
        return False
    return entry.get(data_type) is True


def frame_consent_granted(settings: Mapping[str, Any], provider: str) -> bool:
    """Return ``True`` only if FRAME (vision) egress is explicitly opted-in for ``provider``."""
    return _consent_flag(settings, provider, DATA_TYPE_FRAMES)


def text_consent_granted(settings: Mapping[str, Any], provider: str) -> bool:
    """Return ``True`` only if TEXT (transcript) egress is explicitly opted-in for ``provider``."""
    return _consent_flag(settings, provider, DATA_TYPE_TEXT)


def require_frame_consent(settings: Mapping[str, Any], provider: str) -> None:
    """Raise :class:`ConsentError` unless FRAME egress is granted for ``provider``.

    The single enforcement point a vision egress path calls FIRST, BEFORE any
    frame is sampled or base64-encoded, so a no-consent run never prepares a
    frame for egress (PLAN §WU-keys acceptance (d): "a vision egress without
    frame consent is **blocked**"; test strategy: "refused (typed)").
    """
    if not frame_consent_granted(settings, provider):
        raise ConsentError(provider, DATA_TYPE_FRAMES)
