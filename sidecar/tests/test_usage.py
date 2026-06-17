"""WU-usage-ui PURE model tests: UsageUnit + cache merge + stale flagging.

The rotation pool already produces the per-key usage rows (tested in
test_rotating_provider). This pins the small pure half WU-usage-ui adds: the
REQ/TOKEN unit enum (never-summed dimensions), the persisted-cache merge that
shows last-known numbers on launch, and the >10-min stale flag.
"""

from __future__ import annotations

from media_studio.models.usage import (
    STALE_AFTER_SECONDS,
    UsageUnit,
    flag_stale,
    merge_usage_cache,
)


# --------------------------------------------------------------------------- #
# UsageUnit
# --------------------------------------------------------------------------- #
def test_usage_unit_values_are_plain_lowercase_strings() -> None:
    assert UsageUnit.REQ.value == "req"
    assert UsageUnit.TOKEN.value == "token"
    # str-subclass: the JSON value is the bare string the pool/catalog emit.
    assert UsageUnit.TOKEN == "token"


def test_usage_unit_coerce_maps_token_and_falls_back_to_req() -> None:
    assert UsageUnit.coerce("token") is UsageUnit.TOKEN
    assert UsageUnit.coerce("TOKEN") is UsageUnit.TOKEN
    assert UsageUnit.coerce("req") is UsageUnit.REQ
    # Unknown / garbage units fall back to the safe per-request default.
    assert UsageUnit.coerce("widgets") is UsageUnit.REQ
    assert UsageUnit.coerce(None) is UsageUnit.REQ


# --------------------------------------------------------------------------- #
# merge_usage_cache
# --------------------------------------------------------------------------- #
def _row(
    provider: str, key: str, *, used: int = 0, max_: int | None = None, unit: str = "req", reset_at: float | None = None
) -> dict[str, object]:
    return {"provider": provider, "key": key, "used": used, "max": max_, "unit": unit, "resetAt": reset_at}


def test_merge_keeps_cached_numbers_when_live_pool_is_freshly_zeroed() -> None:
    # A freshly-built pool reports used=0 / max=None; the cache holds real numbers.
    live = [_row("Groq", "…aaaa", used=0, max_=None)]
    cached = [_row("Groq", "…aaaa", used=983, max_=1000, reset_at=2030.0)]
    [merged] = merge_usage_cache(live, cached)
    assert merged["used"] == 983
    assert merged["max"] == 1000
    assert merged["resetAt"] == 2030.0
    # identity/unit always comes from the live row.
    assert merged["provider"] == "Groq"


def test_merge_live_real_data_supersedes_cache() -> None:
    live = [_row("Groq", "…aaaa", used=5, max_=1000)]
    cached = [_row("Groq", "…aaaa", used=983, max_=1000)]
    [merged] = merge_usage_cache(live, cached)
    assert merged["used"] == 5


def test_merge_drops_cached_only_keys_not_in_live_pool() -> None:
    live = [_row("Groq", "…aaaa")]
    cached = [_row("OpenRouter", "…zzzz", used=10, max_=100)]
    merged = merge_usage_cache(live, cached)
    assert [m["provider"] for m in merged] == ["Groq"]


def test_merge_with_empty_cache_returns_live_rows_unchanged() -> None:
    live = [_row("Groq", "…aaaa", used=2, max_=1000)]
    assert merge_usage_cache(live, []) == live


def test_merge_keeps_live_zero_when_cache_also_has_no_real_data() -> None:
    live = [_row("Groq", "…aaaa", used=0, max_=None)]
    cached = [_row("Groq", "…aaaa", used=0, max_=None)]
    [merged] = merge_usage_cache(live, cached)
    assert merged["used"] == 0
    assert merged["max"] is None


# --------------------------------------------------------------------------- #
# flag_stale (fake clock)
# --------------------------------------------------------------------------- #
def test_flag_stale_marks_fresh_rows_not_stale() -> None:
    rows = [_row("Groq", "…aaaa", used=2, max_=1000)]
    [out] = flag_stale(rows, now=1000.0, checked_at={"Groq\x00…aaaa": 999.0})
    assert out["stale"] is False
    assert out["lastCheckedAt"] == 999.0


def test_flag_stale_marks_old_rows_stale_past_threshold() -> None:
    rows = [_row("Groq", "…aaaa", used=2, max_=1000)]
    old = 1000.0 - STALE_AFTER_SECONDS - 1.0
    [out] = flag_stale(rows, now=1000.0, checked_at={"Groq\x00…aaaa": old})
    assert out["stale"] is True
    assert out["lastCheckedAt"] == old


def test_flag_stale_treats_unstamped_row_as_just_checked() -> None:
    rows = [_row("Groq", "…aaaa")]
    [out] = flag_stale(rows, now=1234.5)
    assert out["stale"] is False
    assert out["lastCheckedAt"] == 1234.5
