"""Unit tests for media_studio.models.spend_ledger (WU-spend-cap, persisted half).

The spend ledger is a month-keyed cumulative cost store persisted as a single
JSON document under the data root (alongside other persisted state). It records
each cloud-AI job's actual-or-estimated cost (in integer cents) at completion and
answers "how much have I spent this month?" so the submission gate can enforce a
monthly hard cap and warn at a soft cap.

It is small + pure-with-IO (no heavy imports): the clock is injected so the
month-key derivation is deterministic, and the file round-trips atomically with a
corrupt/missing fallback to an empty ledger (mirrors SettingsStore).
"""

from __future__ import annotations

import json
import time

import pytest
from media_studio.models.spend_ledger import SpendLedger, month_key


class _FakeClock:
    """A settable monotonic-ish clock: returns the unix seconds it is told to."""

    def __init__(self, value: float) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


# UTC reference points (seconds since epoch).
# 2026-06-21 00:00:00 UTC -> month "2026-06".
_JUN_2026 = 1781913600.0
# 2026-07-01 00:00:00 UTC -> month "2026-07".
_JUL_2026 = 1782950400.0
# 2027-01-15 12:00:00 UTC -> month "2027-01".
_JAN_2027 = 1800100800.0


class TestMonthKey:
    def test_month_key_formats_year_dash_month(self):
        assert month_key(_JUN_2026) == "2026-06"

    def test_month_key_rolls_into_next_month(self):
        assert month_key(_JUL_2026) == "2026-07"

    def test_month_key_rolls_into_next_year(self):
        assert month_key(_JAN_2027) == "2027-01"

    @pytest.mark.skipif(
        not hasattr(time, "tzset"),
        reason="time.tzset() (and TZ-env honouring) is Unix-only; on Windows the "
        "host timezone cannot be forced per-process to prove UTC-invariance.",
    )
    def test_month_key_is_utc_not_host_local_time(self, monkeypatch):
        # The module's stated invariant is that the month boundary is UTC, stable
        # across hosts. Pick a timestamp that is one month earlier in a far-west
        # local zone than in UTC, force that zone, and assert month_key still
        # reports the UTC month — proving it uses tz=UTC, not the host clock.
        # 2026-07-01 03:00:00 UTC -> "2026-07" in UTC, but 2026-06-30 20:00
        # "2026-06" in US/Pacific (UTC-7). This kills any tz=None / dropped-tz
        # mutant, which would read the local (June) month instead.
        boundary = 1782874800.0
        monkeypatch.setenv("TZ", "America/Los_Angeles")
        time.tzset()
        try:
            assert month_key(boundary) == "2026-07"
        finally:
            monkeypatch.delenv("TZ", raising=False)
            time.tzset()


class TestRecordAndMonthToDate:
    def test_empty_ledger_month_to_date_is_zero(self, tmp_path):
        ledger = SpendLedger(tmp_path / "spend.json", clock=_FakeClock(_JUN_2026))
        assert ledger.month_to_date() == 0

    def test_record_accumulates_within_a_month(self, tmp_path):
        ledger = SpendLedger(tmp_path / "spend.json", clock=_FakeClock(_JUN_2026))
        ledger.record(150)
        ledger.record(75)
        assert ledger.month_to_date() == 225

    def test_record_uses_clock_month_by_default(self, tmp_path):
        ledger = SpendLedger(tmp_path / "spend.json", clock=_FakeClock(_JUN_2026))
        ledger.record(40)
        assert ledger.month_to_date("2026-06") == 40
        assert ledger.month_to_date("2026-07") == 0

    def test_record_into_an_explicit_month(self, tmp_path):
        ledger = SpendLedger(tmp_path / "spend.json", clock=_FakeClock(_JUN_2026))
        ledger.record(500, month="2026-07")
        assert ledger.month_to_date("2026-06") == 0
        assert ledger.month_to_date("2026-07") == 500

    def test_month_to_date_defaults_to_clock_month(self, tmp_path):
        clock = _FakeClock(_JUN_2026)
        ledger = SpendLedger(tmp_path / "spend.json", clock=clock)
        ledger.record(99)
        # Advance the clock into July: the June spend no longer counts toward MTD.
        clock.value = _JUL_2026
        assert ledger.month_to_date() == 0
        assert ledger.month_to_date("2026-06") == 99


class TestRollover:
    def test_separate_months_are_isolated(self, tmp_path):
        ledger = SpendLedger(tmp_path / "spend.json", clock=_FakeClock(_JUN_2026))
        ledger.record(100, month="2026-06")
        ledger.record(250, month="2026-07")
        assert ledger.month_to_date("2026-06") == 100
        assert ledger.month_to_date("2026-07") == 250

    def test_record_persists_across_instances(self, tmp_path):
        path = tmp_path / "spend.json"
        first = SpendLedger(path, clock=_FakeClock(_JUN_2026))
        first.record(321)
        reopened = SpendLedger(path, clock=_FakeClock(_JUN_2026))
        assert reopened.month_to_date() == 321


class TestPersistenceRobustness:
    def test_atomic_write_leaves_valid_json(self, tmp_path):
        path = tmp_path / "spend.json"
        ledger = SpendLedger(path, clock=_FakeClock(_JUN_2026))
        ledger.record(12)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["months"]["2026-06"] == 12

    def test_persisted_document_carries_the_schema_version(self, tmp_path):
        # The on-disk shape is the FROZEN {"version": 1, "months": {...}} schema;
        # assert the version field name AND value so a regression that drops, renames
        # (e.g. "VERSION"), or nulls it is caught — not just the months sub-map.
        path = tmp_path / "spend.json"
        ledger = SpendLedger(path, clock=_FakeClock(_JUN_2026))
        ledger.record(12)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["version"] == 1
        assert "VERSION" not in data and "Version" not in data

    def test_write_creates_missing_parent_directories(self, tmp_path):
        # The data root may not exist on first run; _write must mkdir(parents=True)
        # so a nested, not-yet-created path is created rather than raising.
        path = tmp_path / "nested" / "deeper" / "spend.json"
        assert not path.parent.exists()
        ledger = SpendLedger(path, clock=_FakeClock(_JUN_2026))
        ledger.record(42)
        assert path.exists()
        assert ledger.month_to_date() == 42

    def test_no_temp_file_left_behind(self, tmp_path):
        path = tmp_path / "spend.json"
        ledger = SpendLedger(path, clock=_FakeClock(_JUN_2026))
        ledger.record(7)
        assert not path.with_name(path.name + ".tmp").exists()

    def test_corrupt_file_falls_back_to_empty(self, tmp_path):
        path = tmp_path / "spend.json"
        path.write_text("{ this is not json", encoding="utf-8")
        ledger = SpendLedger(path, clock=_FakeClock(_JUN_2026))
        assert ledger.month_to_date() == 0
        # And a subsequent record overwrites the corrupt file cleanly.
        ledger.record(33)
        assert ledger.month_to_date() == 33

    def test_non_dict_json_falls_back_to_empty(self, tmp_path):
        path = tmp_path / "spend.json"
        path.write_text("[1, 2, 3]", encoding="utf-8")
        ledger = SpendLedger(path, clock=_FakeClock(_JUN_2026))
        assert ledger.month_to_date() == 0

    def test_missing_months_block_is_tolerated(self, tmp_path):
        path = tmp_path / "spend.json"
        path.write_text(json.dumps({"version": 1}), encoding="utf-8")
        ledger = SpendLedger(path, clock=_FakeClock(_JUN_2026))
        assert ledger.month_to_date() == 0

    def test_non_numeric_stored_month_value_is_treated_as_zero(self, tmp_path):
        path = tmp_path / "spend.json"
        path.write_text(json.dumps({"months": {"2026-06": "oops"}}), encoding="utf-8")
        ledger = SpendLedger(path, clock=_FakeClock(_JUN_2026))
        assert ledger.month_to_date() == 0
        ledger.record(5)
        assert ledger.month_to_date() == 5


class TestRecordValidation:
    def test_negative_cost_is_rejected(self, tmp_path):
        ledger = SpendLedger(tmp_path / "spend.json", clock=_FakeClock(_JUN_2026))
        # Anchored match: assert the EXACT message so a regression that nulls,
        # re-cases, or pads the error text (not just the ValueError type) is caught.
        with pytest.raises(ValueError, match=r"^spend cost must be non-negative$"):
            ledger.record(-1)

    def test_record_coerces_float_cents_to_int(self, tmp_path):
        ledger = SpendLedger(tmp_path / "spend.json", clock=_FakeClock(_JUN_2026))
        ledger.record(10.9)
        # Truncates toward zero (int()): cents are whole-number money.
        assert ledger.month_to_date() == 10

    def test_zero_cost_record_is_a_noop_total(self, tmp_path):
        ledger = SpendLedger(tmp_path / "spend.json", clock=_FakeClock(_JUN_2026))
        ledger.record(0)
        assert ledger.month_to_date() == 0


class TestDefaultClock:
    def test_default_clock_is_wall_time(self, tmp_path, monkeypatch):
        # No injected clock -> the module uses time.time; patch it so the test is
        # deterministic and the default-arg branch is exercised.
        import media_studio.models.spend_ledger as mod

        monkeypatch.setattr(mod.time, "time", lambda: _JUN_2026)
        ledger = SpendLedger(tmp_path / "spend.json")
        ledger.record(60)
        assert ledger.month_to_date() == 60
