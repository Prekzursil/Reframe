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


# --------------------------------------------------------------------------- #
# redact_keys (the RPC-facing providers-list transform)
# --------------------------------------------------------------------------- #
def test_redact_keys_redacts_every_api_key_to_last_four() -> None:
    providers = [
        {"id": "groq", "apiKeys": ["sk-aaaaaaaaWXYZ", "gsk-bbbbbbbb7890"]},
        {"id": "openai", "apiKeys": ["sk-proj-cccccccc4242"]},
    ]
    out = secrets.redact_keys(providers)
    assert out[0]["apiKeys"] == ["…WXYZ", "…7890"]
    assert out[1]["apiKeys"] == ["…4242"]
    # No full key survives anywhere in the serialized result.
    blob = repr(out)
    for full in ("sk-aaaaaaaaWXYZ", "gsk-bbbbbbbb7890", "sk-proj-cccccccc4242"):
        assert full not in blob


def test_redact_keys_does_not_mutate_input() -> None:
    providers = [{"id": "groq", "apiKeys": ["sk-original-KEY9"]}]
    secrets.redact_keys(providers)
    # The caller's RAW store is untouched (immutability — the factory still needs it).
    assert providers[0]["apiKeys"] == ["sk-original-KEY9"]


def test_redact_keys_passes_through_other_fields_and_missing_keys() -> None:
    providers = [
        {"id": "no-keys", "enabled": True},  # no apiKeys field
        {"id": "bad-keys", "apiKeys": "not-a-list"},  # non-list -> untouched
    ]
    out = secrets.redact_keys(providers)
    assert out[0] == {"id": "no-keys", "enabled": True}
    assert out[1]["apiKeys"] == "not-a-list"


def test_redact_keys_skips_non_dict_entries() -> None:
    out = secrets.redact_keys(["garbage", 42, {"id": "ok", "apiKeys": ["abcdEFGH"]}])
    assert len(out) == 1
    assert out[0]["apiKeys"] == ["…EFGH"]


def test_redact_keys_empty_is_empty() -> None:
    assert secrets.redact_keys([]) == []


# --------------------------------------------------------------------------- #
# WU-D2 (R7): redact_params — the RPC no-log formatter. A key-bearing RPC frame's
# params must be safe to write to a diagnostic log line: NO key material survives.
# --------------------------------------------------------------------------- #
def test_redact_params_hides_top_level_api_key() -> None:
    out = secrets.redact_params({"baseUrl": "https://x/v1", "apiKey": "sk-live-SECRET-9999"})
    assert out["baseUrl"] == "https://x/v1"  # non-secret preserved
    assert "sk-live-SECRET-9999" not in repr(out)
    assert out["apiKey"] == secrets.REDACTION_PLACEHOLDER


def test_redact_params_hides_cloud_api_key() -> None:
    out = secrets.redact_params({"cloudApiKey": "sk-cloud-1234", "useCloud": True})
    assert out["useCloud"] is True
    assert out["cloudApiKey"] == secrets.REDACTION_PLACEHOLDER


def test_redact_params_hides_api_keys_list_preserving_length() -> None:
    out = secrets.redact_params({"apiKeys": ["gsk-aaaa1111", "gsk-bbbb2222"]})
    assert out["apiKeys"] == [secrets.REDACTION_PLACEHOLDER, secrets.REDACTION_PLACEHOLDER]
    for full in ("gsk-aaaa1111", "gsk-bbbb2222"):
        assert full not in repr(out)


def test_redact_params_hides_nested_provider_block() -> None:
    # providers.upsert nests the entry under a "provider" key (providers_ops.py).
    out = secrets.redact_params(
        {"provider": {"id": "groq", "provider": "Groq", "apiKeys": ["gsk-nested-KEY7"]}}
    )
    assert out["provider"]["id"] == "groq"
    assert out["provider"]["provider"] == "Groq"
    assert out["provider"]["apiKeys"] == [secrets.REDACTION_PLACEHOLDER]
    assert "gsk-nested-KEY7" not in repr(out)


def test_redact_params_hides_keys_in_providers_list() -> None:
    out = secrets.redact_params(
        {"providers": [{"id": "a", "apiKeys": ["k-aaaa"]}, {"id": "b", "cloudApiKey": "k-bbbb"}]}
    )
    assert out["providers"][0]["apiKeys"] == [secrets.REDACTION_PLACEHOLDER]
    assert out["providers"][1]["cloudApiKey"] == secrets.REDACTION_PLACEHOLDER
    for full in ("k-aaaa", "k-bbbb"):
        assert full not in repr(out)


def test_redact_params_does_not_mutate_input() -> None:
    params = {"apiKey": "sk-orig-KEY9", "apiKeys": ["gsk-orig-1"], "provider": {"apiKeys": ["p-1"]}}
    secrets.redact_params(params)
    # The caller's live params object is untouched (the sidecar still needs the key).
    assert params["apiKey"] == "sk-orig-KEY9"
    assert params["apiKeys"] == ["gsk-orig-1"]
    assert params["provider"]["apiKeys"] == ["p-1"]


def test_redact_params_passes_through_non_secret_only_params() -> None:
    out = secrets.redact_params({"jobId": "job-1", "pct": 50})
    assert out == {"jobId": "job-1", "pct": 50}


def test_redact_params_tolerates_non_dict_params() -> None:
    # Defensive: a malformed (non-dict) params value is returned unchanged, never crashes.
    assert secrets.redact_params("not-a-dict") == "not-a-dict"  # type: ignore[arg-type]


def test_redact_params_tolerates_non_list_api_keys_and_non_dict_entries() -> None:
    out = secrets.redact_params(
        {"apiKeys": "not-a-list", "providers": ["garbage", {"id": "ok", "apiKeys": ["k-ok"]}]}
    )
    # A non-list apiKeys is redacted wholesale (still a secret-bearing field).
    assert out["apiKeys"] == secrets.REDACTION_PLACEHOLDER
    # Non-dict list entries are passed through; dict entries are redacted.
    assert out["providers"][0] == "garbage"
    assert out["providers"][1]["apiKeys"] == [secrets.REDACTION_PLACEHOLDER]


def test_redact_params_tolerates_non_dict_nested_provider() -> None:
    out = secrets.redact_params({"provider": "not-a-dict"})
    assert out["provider"] == "not-a-dict"
