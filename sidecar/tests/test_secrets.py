"""Unit tests for secret redaction + error-body scrubbing (models/secrets.py).

WU-keys (PLAN §WU-keys "ENFORCEABLE SCRUB"). These are PURE functions — no I/O,
no network, no clock — so every branch is hit directly with fixtures.

Two public functions under test:
  * ``redact(key) -> "…last4"`` — a display-safe redaction that never leaks more
    than the last 4 characters of a key (and degrades gracefully for short keys).
  * ``scrub_error_body(text, keys) -> text`` — strips every key in ``keys`` AND
    any ``Authorization: Bearer <...>`` header value from a provider error body
    before it can reach a log line or an RPC error message.
"""

from __future__ import annotations

from media_studio.models import secrets


# --------------------------------------------------------------------------- #
# redact
# --------------------------------------------------------------------------- #
def test_redact_long_key_shows_only_last_four() -> None:
    out = secrets.redact("sk-1234567890ABCDEF")
    # Only the final 4 chars survive; nothing earlier leaks.
    assert out.endswith("CDEF")
    assert "1234567890" not in out
    assert "sk-" not in out


def test_redact_marks_redaction_with_ellipsis_prefix() -> None:
    # The redaction is visibly a redaction (ellipsis), not a bare suffix.
    assert secrets.redact("abcdefgh") == "…efgh"


def test_redact_short_key_does_not_leak_whole_key() -> None:
    # A key of <=4 chars must NOT be echoed verbatim (that would leak it all).
    out = secrets.redact("ab")
    assert "ab" not in out
    assert out == "…"


def test_redact_exactly_four_chars_is_fully_masked() -> None:
    # last4 of a 4-char key == the whole key, so masking must kick in at the
    # boundary and reveal nothing.
    out = secrets.redact("WXYZ")
    assert "WXYZ" not in out
    assert out == "…"


def test_redact_empty_key_returns_bare_ellipsis() -> None:
    assert secrets.redact("") == "…"


# --------------------------------------------------------------------------- #
# scrub_error_body — key stripping
# --------------------------------------------------------------------------- #
def test_scrub_removes_embedded_key_from_error_body() -> None:
    key = "sk-supersecret-abc123"
    body = f'{{"error":"invalid api key {key} for model"}}'
    out = secrets.scrub_error_body(body, [key])
    assert key not in out
    assert "invalid api key" in out  # surrounding text preserved


def test_scrub_removes_every_key_when_multiple_given() -> None:
    k1 = "key-AAAAAAAA"
    k2 = "key-BBBBBBBB"
    body = f"first {k1} then {k2} done"
    out = secrets.scrub_error_body(body, [k1, k2])
    assert k1 not in out
    assert k2 not in out


def test_scrub_strips_multiple_occurrences_of_same_key() -> None:
    key = "tok-DEADBEEF"
    body = f"{key} ... and again {key}"
    out = secrets.scrub_error_body(body, [key])
    assert key not in out


def test_scrub_ignores_empty_strings_in_keys() -> None:
    # An empty key must NOT scrub the whole body away (empty substring matches
    # everywhere). The text must survive intact.
    body = "a normal error message with no secrets"
    out = secrets.scrub_error_body(body, ["", ""])
    assert out == body


# --------------------------------------------------------------------------- #
# scrub_error_body — Authorization: Bearer header stripping
# --------------------------------------------------------------------------- #
def test_scrub_strips_bearer_header_value() -> None:
    body = "401 Unauthorized\nAuthorization: Bearer sk-live-zzz999\nretry later"
    out = secrets.scrub_error_body(body, [])
    assert "sk-live-zzz999" not in out
    # The header name may remain, but the token must be gone.
    assert "sk-live-zzz999" not in out
    assert "retry later" in out


def test_scrub_strips_bearer_header_case_insensitively() -> None:
    body = "authorization: bearer SECRETTOKEN42"
    out = secrets.scrub_error_body(body, [])
    assert "SECRETTOKEN42" not in out


def test_scrub_strips_bearer_token_even_when_not_in_keys_list() -> None:
    # A leaked bearer that we did not know about (not in keys) is still stripped.
    body = 'HTTP 403: {"detail":"bad"}\nAuthorization: Bearer unknown-leaked-key'
    out = secrets.scrub_error_body(body, ["some-other-key"])
    assert "unknown-leaked-key" not in out


def test_scrub_strips_both_known_keys_and_bearer_header() -> None:
    key = "kkk-known-1234"
    body = f"err {key}\nAuthorization: Bearer bbb-bearer-5678"
    out = secrets.scrub_error_body(body, [key])
    assert key not in out
    assert "bbb-bearer-5678" not in out


# --------------------------------------------------------------------------- #
# scrub_error_body — no-op / unchanged paths
# --------------------------------------------------------------------------- #
def test_scrub_leaves_clean_text_unchanged() -> None:
    body = '{"error":"model overloaded, please retry"}'
    assert secrets.scrub_error_body(body, ["sk-not-present"]) == body


def test_scrub_empty_text_returns_empty() -> None:
    assert secrets.scrub_error_body("", ["sk-anything"]) == ""


def test_scrub_no_keys_and_no_bearer_is_identity() -> None:
    body = "plain HTTP 500 internal error"
    assert secrets.scrub_error_body(body, []) == body


def test_scrub_returns_redaction_placeholder_not_raw_gap() -> None:
    # When a key is removed it leaves a visible placeholder, not silent deletion,
    # so a scrubbed body is recognizably scrubbed.
    key = "sk-visible-marker-1"
    out = secrets.scrub_error_body(f"before {key} after", [key])
    assert secrets.REDACTION_PLACEHOLDER in out
