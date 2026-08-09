"""Likeness-attestation gate (C15 gaze correction — the ETHICS gate).

Gaze redirection MANIPULATES A REAL PERSON'S FACE. This module covers the
ENFORCEMENT half of the attestation that authorises it: unless the operator has
explicitly attested they hold the right to alter this subject's likeness, the
pipeline REFUSES with a typed error. FAIL CLOSED — absent, false, or malformed
attestation state never grants; only an explicit ``True`` does.

Deliberately mirrors ``models/consent.py`` (the repo's existing default-deny
gate idiom) so the voice-clone lane (WU-A2) can adopt the SAME module for
``SCOPE_VOICE`` rather than growing a second, divergent likeness gate. See
``docs/wiring/WIRING-gaze.md`` for the reconciliation note.

NOTE ON SCOPE SEPARATION: this is NOT the per-provider EGRESS consent in
``models/consent.py``. That answers "may this payload leave the machine";
this answers "may we alter this person's face at all" — an orthogonal question
that stays required even for a fully offline run.
"""

from __future__ import annotations

import pytest
from media_studio.models.likeness import (
    SCOPE_GAZE,
    SCOPE_VOICE,
    Attestation,
    LikenessError,
    attestation_granted,
    require_attestation,
    resolve_attestation,
)


def _settings(attestations: object) -> dict:
    return {"likeness": {"attestations": attestations}}


# --------------------------------------------------------------------------- #
# attestation_granted — positive grants
# --------------------------------------------------------------------------- #
def test_granted_when_explicit_true_for_that_scope() -> None:
    settings = _settings({"subject-1": {"gaze": True}})
    assert attestation_granted(settings, "subject-1", SCOPE_GAZE) is True


def test_scopes_are_independent() -> None:
    # gaze attested, voice NOT — a face-alteration grant is not a voice-clone grant.
    settings = _settings({"subject-1": {"gaze": True}})
    assert attestation_granted(settings, "subject-1", SCOPE_GAZE) is True
    assert attestation_granted(settings, "subject-1", SCOPE_VOICE) is False


def test_subjects_are_independent() -> None:
    settings = _settings({"subject-1": {"gaze": True}})
    assert attestation_granted(settings, "subject-2", SCOPE_GAZE) is False


# --------------------------------------------------------------------------- #
# FAIL CLOSED: every absent / malformed shape resolves to NOT granted
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "attestations",
    [
        {"subject-1": {"gaze": False}},  # explicit false
        {"subject-1": {"voice": True}},  # different scope only
        {"subject-1": {}},  # entry present, scope absent
        {"subject-1": None},  # entry not a mapping
        {"subject-1": "yes"},  # truthy string is NOT an attestation
        {"subject-1": {"gaze": "true"}},  # truthy string flag is NOT True
        {"subject-1": {"gaze": 1}},  # truthy int is NOT True
        {},  # no subjects
        None,  # attestations not a mapping
        "nope",  # attestations wholly malformed
    ],
)
def test_denied_for_every_non_true_shape(attestations: object) -> None:
    assert attestation_granted(_settings(attestations), "subject-1", SCOPE_GAZE) is False


def test_denied_when_likeness_block_absent() -> None:
    assert attestation_granted({}, "subject-1", SCOPE_GAZE) is False


def test_denied_when_likeness_block_not_a_mapping() -> None:
    assert attestation_granted({"likeness": "nope"}, "subject-1", SCOPE_GAZE) is False


def test_denied_when_subject_key_is_empty() -> None:
    # An empty subject key must never resolve to a grant, even if stored.
    assert attestation_granted(_settings({"": {"gaze": True}}), "", SCOPE_GAZE) is False


# --------------------------------------------------------------------------- #
# require_attestation — the typed refusal
# --------------------------------------------------------------------------- #
def test_require_passes_when_granted() -> None:
    require_attestation(_settings({"s": {"gaze": True}}), "s", SCOPE_GAZE)


def test_require_raises_typed_error_when_denied() -> None:
    with pytest.raises(LikenessError) as excinfo:
        require_attestation({}, "s", SCOPE_GAZE)
    err = excinfo.value
    assert err.subject == "s"
    assert err.scope == SCOPE_GAZE
    # The message must name the subject, the scope, and the settings path to fix.
    assert "s" in str(err)
    assert SCOPE_GAZE in str(err)
    assert "likeness.attestations" in str(err)


def test_likeness_error_is_a_runtime_error() -> None:
    # Callers already catching RuntimeError (the repo's typed-refusal idiom) work.
    assert issubclass(LikenessError, RuntimeError)


# --------------------------------------------------------------------------- #
# resolve_attestation — persisted grant OR an explicit per-job attestation
# --------------------------------------------------------------------------- #
def test_resolve_accepts_explicit_per_job_attestation() -> None:
    params = {"likenessAttested": True, "likenessSubject": "ada"}
    att = resolve_attestation({}, params, scope=SCOPE_GAZE)
    assert att == Attestation(subject="ada", scope=SCOPE_GAZE, source="request")


def test_resolve_falls_back_to_persisted_settings() -> None:
    settings = _settings({"ada": {"gaze": True}})
    att = resolve_attestation(settings, {"likenessSubject": "ada"}, scope=SCOPE_GAZE)
    assert att == Attestation(subject="ada", scope=SCOPE_GAZE, source="settings")


def test_resolve_prefers_the_explicit_request_over_settings() -> None:
    settings = _settings({"ada": {"gaze": True}})
    params = {"likenessAttested": True, "likenessSubject": "ada"}
    assert resolve_attestation(settings, params, scope=SCOPE_GAZE).source == "request"


@pytest.mark.parametrize(
    "params",
    [
        {},  # nothing at all
        {"likenessSubject": "ada"},  # subject but no attestation, none persisted
        {"likenessAttested": True},  # attested but NO subject named
        {"likenessAttested": True, "likenessSubject": ""},  # empty subject
        {"likenessAttested": True, "likenessSubject": "   "},  # whitespace subject
        {"likenessAttested": True, "likenessSubject": 7},  # non-str subject
        {"likenessAttested": "yes", "likenessSubject": "ada"},  # truthy str, not True
        {"likenessAttested": 1, "likenessSubject": "ada"},  # truthy int, not True
        {"likenessAttested": False, "likenessSubject": "ada"},  # explicit refusal
    ],
)
def test_resolve_raises_when_no_valid_attestation(params: dict) -> None:
    with pytest.raises(LikenessError):
        resolve_attestation({}, params, scope=SCOPE_GAZE)


def test_resolve_rejects_a_non_mapping_params() -> None:
    with pytest.raises(LikenessError):
        resolve_attestation({}, None, scope=SCOPE_GAZE)  # type: ignore[arg-type]


def test_resolve_trims_the_subject_key() -> None:
    params = {"likenessAttested": True, "likenessSubject": "  ada  "}
    assert resolve_attestation({}, params, scope=SCOPE_GAZE).subject == "ada"


def test_attestation_is_frozen() -> None:
    att = Attestation(subject="ada", scope=SCOPE_GAZE, source="request")
    with pytest.raises(AttributeError):
        att.subject = "eve"  # type: ignore[misc]


def test_scope_constants_are_distinct_strings() -> None:
    assert SCOPE_GAZE == "gaze"
    assert SCOPE_VOICE == "voice"
