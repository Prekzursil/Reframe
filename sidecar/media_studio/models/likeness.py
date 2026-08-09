"""Likeness-attestation gate — the ETHICS gate for face/voice alteration (C15).

Gaze redirection MANIPULATES A REAL PERSON'S FACE. Before any such alteration
runs, the operator must have explicitly attested that they hold the right to
alter that subject's likeness. This module is the ENFORCEMENT half — the typed,
FAIL-CLOSED refusal every likeness-altering path MUST pass through first.

Deliberately mirrors :mod:`media_studio.models.consent` (the repo's existing
default-deny gate idiom): pure, stdlib-only, crossing no other ``models/``
module, and carrying booleans/labels only — never a secret.

  * :data:`SCOPE_GAZE` / :data:`SCOPE_VOICE` — the two alteration classes. A
    grant for one is NOT a grant for the other (a face-alteration attestation
    must never authorise a voice clone, or vice versa).
  * :func:`attestation_granted` — pure predicate over persisted settings
    (default-deny: absent, ``False``, truthy-but-not-``True``, or any malformed
    level all resolve to NOT granted).
  * :func:`require_attestation` — raises :class:`LikenessError` unless granted.
  * :func:`resolve_attestation` — the seam a job entry point calls: accepts an
    EXPLICIT per-job attestation in the request, else falls back to the
    persisted grant, else raises. Returns the :class:`Attestation` that
    authorised the run so the job can record it as an audit trail.

NOT the same thing as ``models/consent.py``. That gate answers "may this payload
LEAVE the machine" (per-provider egress). This one answers "may we alter this
person's likeness at all" — an orthogonal question that stays REQUIRED even for
a fully offline run, because the harm is the altered artifact, not the transport.

RECONCILIATION NOTE (WU-A2, the voice-clone lane): :data:`SCOPE_VOICE` exists so
the voice-clone consent gate adopts THIS module rather than growing a second,
divergent likeness gate. At the time of writing ``features/tts/voices.py`` has
no attestation of any kind and ``VoiceSample`` is ``{id, name, path,
durationSec}``; wiring that lane through :func:`resolve_attestation` is a
follow-up, not something this module can do for it. There is deliberately NO
entry added to ``settings_store.DEFAULT_SETTINGS`` here: the persisted-grant
SETTER (and its UI) belongs to that shared lane, and this gate reads defensively
so it is correct — and closed — before the setter exists.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

#: The distinct likeness-alteration classes. Independently attested.
SCOPE_GAZE: str = "gaze"
SCOPE_VOICE: str = "voice"

#: Where a resolved attestation came from (audit trail).
SOURCE_REQUEST: str = "request"
SOURCE_SETTINGS: str = "settings"

#: The settings path the gate reads. Named in the error so the message is actionable.
SETTINGS_PATH: str = "likeness.attestations"


class LikenessError(RuntimeError):
    """Raised when a likeness alteration is attempted without an attestation.

    The typed refusal a caller surfaces to the operator. Carries the offending
    subject label and alteration scope so the message is precise — and NEVER a
    secret (attestation state is a boolean plus an operator-chosen label).

    Subclasses :class:`RuntimeError` to match the repo's typed-refusal idiom
    (:class:`media_studio.models.consent.ConsentError`), so a caller already
    catching ``RuntimeError`` around a feature call keeps working.
    """

    def __init__(self, subject: str, scope: str) -> None:
        self.subject = subject
        self.scope = scope
        super().__init__(
            f"{scope} likeness alteration for subject {subject!r} refused: no "
            f"attestation. Altering a real person's likeness requires an explicit "
            f"attestation that you hold the right to do so — set "
            f"{SETTINGS_PATH}[{subject!r}].{scope} = true, or pass "
            f"likenessAttested=true with likenessSubject on the request."
        )


@dataclass(frozen=True)
class Attestation:
    """The attestation that authorised one likeness alteration (audit record)."""

    subject: str
    scope: str
    source: str


def _clean_subject(subject: Any) -> str:
    """The normalised subject key, or ``""`` when it is not a usable label."""
    if not isinstance(subject, str):
        return ""
    return subject.strip()


def attestation_granted(settings: Mapping[str, Any], subject: str, scope: str) -> bool:
    """Return ``True`` only if ``scope`` is EXPLICITLY attested for ``subject``.

    Reads ``settings.likeness.attestations[subject][scope]`` defensively. A
    missing likeness block, missing attestations map, missing subject entry,
    missing flag, an empty subject label, or any malformed (non-mapping) level
    all resolve to ``False``.

    The flag must be the literal ``True``: a truthy string or ``1`` is NOT an
    attestation. A checkbox that was never ticked, a config that half-parsed, or
    a stray non-empty value must never read as consent to alter a real person's
    face.
    """
    key = _clean_subject(subject)
    if not key:
        return False
    likeness = settings.get("likeness")
    if not isinstance(likeness, Mapping):
        return False
    attestations = likeness.get("attestations")
    if not isinstance(attestations, Mapping):
        return False
    entry = attestations.get(key)
    if not isinstance(entry, Mapping):
        return False
    return entry.get(scope) is True


def require_attestation(settings: Mapping[str, Any], subject: str, scope: str) -> None:
    """Raise :class:`LikenessError` unless ``scope`` is attested for ``subject``.

    The single enforcement point a likeness-altering path calls FIRST, BEFORE any
    frame is decoded or any model is loaded, so a non-attested run never even
    prepares the alteration.
    """
    if not attestation_granted(settings, subject, scope):
        raise LikenessError(_clean_subject(subject), scope)


def resolve_attestation(settings: Mapping[str, Any], params: Mapping[str, Any], *, scope: str) -> Attestation:
    """Resolve the attestation authorising this job, or raise :class:`LikenessError`.

    Order (FAIL CLOSED — the fallthrough is a refusal, never a grant):

      1. the request carries ``likenessAttested is True`` + a usable
         ``likenessSubject`` -> an explicit per-job attestation;
      2. else the persisted grant for that subject (:func:`attestation_granted`);
      3. else refuse.

    A usable ``likenessSubject`` is required in EVERY case, including the
    per-job form: an attestation that names no subject attests to nothing, and
    without it the audit record would be empty.
    """
    if not isinstance(params, Mapping):
        raise LikenessError("", scope)
    subject = _clean_subject(params.get("likenessSubject"))
    if not subject:
        raise LikenessError("", scope)
    if params.get("likenessAttested") is True:
        return Attestation(subject=subject, scope=scope, source=SOURCE_REQUEST)
    if attestation_granted(settings, subject, scope):
        return Attestation(subject=subject, scope=scope, source=SOURCE_SETTINGS)
    raise LikenessError(subject, scope)


__all__ = [
    "SCOPE_GAZE",
    "SCOPE_VOICE",
    "SETTINGS_PATH",
    "SOURCE_REQUEST",
    "SOURCE_SETTINGS",
    "Attestation",
    "LikenessError",
    "attestation_granted",
    "require_attestation",
    "resolve_attestation",
]
