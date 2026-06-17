"""Per-data-type egress consent gate (WU-keys / SE1, PLAN §WU-keys acceptance (d)).

The setter (``providers.setConsent``) is covered in ``test_handlers_keys.py``;
THIS module covers the ENFORCEMENT half — the typed refusal that PLAN §WU-keys
acceptance (d) ("a vision egress without frame consent is **blocked**") and the
test strategy ("refused (typed)") require. Default-deny: absent/malformed
consent never grants egress; only an explicit ``True`` does.
"""

from __future__ import annotations

import pytest
from media_studio.models.consent import (
    DATA_TYPE_FRAMES,
    DATA_TYPE_TEXT,
    ConsentError,
    frame_consent_granted,
    require_frame_consent,
    text_consent_granted,
)


def _settings(per_provider: object) -> dict:
    return {"consent": {"perProvider": per_provider}}


# --------------------------------------------------------------------------- #
# frame_consent_granted / text_consent_granted — positive grants
# --------------------------------------------------------------------------- #
def test_frame_consent_granted_when_explicit_true() -> None:
    settings = _settings({"Gemini": {"frames": True}})
    assert frame_consent_granted(settings, "Gemini") is True


def test_text_consent_granted_when_explicit_true() -> None:
    settings = _settings({"Groq": {"text": True}})
    assert text_consent_granted(settings, "Groq") is True


def test_text_and_frames_are_independent() -> None:
    # frames opted-in, text NOT — the two gates are separate (SE1).
    settings = _settings({"Gemini": {"frames": True}})
    assert frame_consent_granted(settings, "Gemini") is True
    assert text_consent_granted(settings, "Gemini") is False


# --------------------------------------------------------------------------- #
# default-deny: every absent / malformed shape resolves to NOT granted
# --------------------------------------------------------------------------- #
def test_frame_consent_denied_when_flag_false() -> None:
    assert frame_consent_granted(_settings({"Gemini": {"frames": False}}), "Gemini") is False


def test_frame_consent_denied_when_flag_absent() -> None:
    # provider entry exists but has only text consent — frames absent == denied.
    assert frame_consent_granted(_settings({"Gemini": {"text": True}}), "Gemini") is False


def test_frame_consent_denied_when_provider_absent() -> None:
    assert frame_consent_granted(_settings({"Other": {"frames": True}}), "Gemini") is False


def test_frame_consent_denied_when_provider_entry_not_mapping() -> None:
    assert frame_consent_granted(_settings({"Gemini": "yes"}), "Gemini") is False


def test_frame_consent_denied_when_per_provider_not_mapping() -> None:
    assert frame_consent_granted(_settings(["Gemini"]), "Gemini") is False


def test_frame_consent_denied_when_consent_block_missing() -> None:
    assert frame_consent_granted({}, "Gemini") is False


def test_frame_consent_denied_when_consent_block_not_mapping() -> None:
    assert frame_consent_granted({"consent": "nope"}, "Gemini") is False


def test_frame_consent_denied_when_flag_truthy_but_not_true() -> None:
    # default-deny is strict: a truthy non-True value (e.g. 1) is NOT consent.
    assert frame_consent_granted(_settings({"Gemini": {"frames": 1}}), "Gemini") is False


# --------------------------------------------------------------------------- #
# require_frame_consent — typed refusal (the acceptance-(d) enforcement point)
# --------------------------------------------------------------------------- #
def test_require_frame_consent_passes_when_granted() -> None:
    # No exception when consent is explicitly granted.
    require_frame_consent(_settings({"Gemini": {"frames": True}}), "Gemini")


def test_require_frame_consent_raises_typed_when_denied() -> None:
    with pytest.raises(ConsentError) as exc_info:
        require_frame_consent(_settings({"Gemini": {"frames": False}}), "Gemini")
    err = exc_info.value
    assert err.provider == "Gemini"
    assert err.data_type == DATA_TYPE_FRAMES
    # Message names the provider + the precise consent path, no secret.
    assert "Gemini" in str(err)
    assert DATA_TYPE_FRAMES in str(err)


def test_require_frame_consent_raises_when_consent_absent() -> None:
    with pytest.raises(ConsentError):
        require_frame_consent({}, "Gemini")


def test_data_type_constants() -> None:
    assert DATA_TYPE_TEXT == "text"
    assert DATA_TYPE_FRAMES == "frames"
