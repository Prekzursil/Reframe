"""Unit tests for the feedback flywheel (features/feedback.py, P3-D).

Store round-trip, RPC registration, exemplar block formatting + threshold
gating, and calibration binning — all against a tmp-path store (the real
%APPDATA% location is never touched).
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from media_studio.features import feedback as fb
from media_studio.protocol import RpcError


@pytest.fixture()
def store(tmp_path) -> fb.FeedbackStore:
    return fb.FeedbackStore(tmp_path / "feedback" / "feedback.jsonl")


def cand(hook: str = "hook", *, factors=None, language=None) -> dict[str, Any]:
    c: dict[str, Any] = {
        "rank": 1,
        "start": 0.0,
        "end": 30.0,
        "durationSec": 30.0,
        "hook": hook,
        "why": "w",
        "score": 80,
        "sourceStart": 0.0,
    }
    if factors is not None:
        c["factors"] = factors
    if language is not None:
        c["language"] = language
    return c


def factors(avg: float) -> dict[str, int]:
    v = int(avg)
    return {"hookStrength": v, "emotionalFlow": v, "perceivedValue": v, "shareability": v}


def fill(store: fb.FeedbackStore, n: int, action: str = "approved", **kw) -> None:
    for i in range(n):
        store.record("v1", cand(f"{action} hook {i}", **kw), action)


# ---------------------------------------------------------------------------
# store round-trip
# ---------------------------------------------------------------------------
def test_record_appends_jsonl_and_entries_round_trip(store):
    e1 = store.record("vid-1", cand("first"), "approved")
    e2 = store.record("vid-2", cand("second"), "discarded")
    assert e1["videoId"] == "vid-1" and e1["ts"] > 0

    raw = store.path.read_text(encoding="utf-8").splitlines()
    assert len(raw) == 2  # append-only, one JSON line per action
    assert json.loads(raw[0])["candidate"]["hook"] == "first"

    entries = store.entries()
    assert [e["action"] for e in entries] == ["approved", "discarded"]
    assert entries[1]["candidate"]["hook"] == "second"
    assert e2["action"] == "discarded"


def test_record_rejects_bad_action_and_candidate(store):
    with pytest.raises(ValueError, match="action"):
        store.record("v", cand(), "loved")
    with pytest.raises(ValueError, match="candidate"):
        store.record("v", "not-a-dict", "approved")  # type: ignore[arg-type]
    assert store.labels() == 0  # nothing was written


def test_entries_skip_corrupt_lines(store):
    store.record("v", cand("good"), "approved")
    with open(store.path, "a", encoding="utf-8") as fh:
        fh.write("{torn json\n")
        fh.write('{"action": "unknown-action"}\n')
    store.record("v", cand("also good"), "exported")
    assert [e["candidate"]["hook"] for e in store.entries()] == [
        "good",
        "also good",
    ]


def test_missing_file_yields_empty(store):
    assert store.entries() == []
    assert store.labels() == 0


def test_entries_skip_blank_lines(store):
    store.record("v", cand("good"), "approved")
    with open(store.path, "a", encoding="utf-8") as fh:
        fh.write("\n")  # a blank line must be skipped, not parsed
        fh.write("   \n")
    store.record("v", cand("also good"), "exported")
    assert [e["candidate"]["hook"] for e in store.entries()] == ["good", "also good"]


def test_entries_unreadable_file_yields_empty(store, monkeypatch):
    store.record("v", cand("good"), "approved")

    def boom(*a, **k):
        raise OSError("permission denied")

    monkeypatch.setattr(fb.Path, "read_text", boom)
    # An OSError reading the store must degrade to [] (never fatal).
    assert store.entries() == []


def test_stats_payload_and_calibrated_flag(store):
    fill(store, 10)
    assert store.stats() == {"labels": 10, "calibrated": False}
    fill(store, 40, action="discarded")
    assert store.stats() == {"labels": 50, "calibrated": True}


def test_default_path_is_under_config_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("MEDIA_STUDIO_CONFIG_DIR", str(tmp_path))
    path = fb.default_feedback_path()
    assert path == tmp_path / "feedback" / "feedback.jsonl"


# ---------------------------------------------------------------------------
# RPC registration (frozen names + shapes)
# ---------------------------------------------------------------------------
def test_register_wires_record_and_stats(store):
    registered: dict[str, Any] = {}
    fb.register(register_fn=lambda name, h: registered.__setitem__(name, h), store=store)
    assert set(registered) == {"feedback.record", "feedback.stats"}

    out = registered["feedback.record"](
        {"videoId": "v1", "candidate": cand("rpc hook"), "action": "approved"},
        None,
    )
    assert out == {"ok": True}
    stats = registered["feedback.stats"]({}, None)
    assert stats == {"labels": 1, "calibrated": False}


def test_record_rpc_validates_params(store):
    registered: dict[str, Any] = {}
    fb.register(register_fn=lambda name, h: registered.__setitem__(name, h), store=store)
    record = registered["feedback.record"]
    with pytest.raises(RpcError):
        record({"candidate": cand(), "action": "approved"}, None)  # no videoId
    with pytest.raises(RpcError):
        record({"videoId": "v", "candidate": cand(), "action": "meh"}, None)
    with pytest.raises(RpcError):
        record({"videoId": "v", "candidate": None, "action": "approved"}, None)


# ---------------------------------------------------------------------------
# exemplar block — threshold gating + formatting
# ---------------------------------------------------------------------------
def test_exemplar_block_none_below_threshold(store):
    fill(store, fb.EXEMPLAR_MIN_LABELS - 1)
    assert store.exemplar_block() is None


def test_exemplar_block_formats_top5_each_side(store):
    fill(store, 12, action="approved")
    fill(store, 12, action="discarded")
    block = store.exemplar_block()
    assert block is not None
    assert "TASTE CALIBRATION" in block
    # Top-5 per side, most recent first.
    approved_lines = [line for line in block.splitlines() if line.startswith("+ ")]
    discarded_lines = [line for line in block.splitlines() if line.startswith("- ")]
    assert len(approved_lines) == fb.EXEMPLAR_TOP_N
    assert len(discarded_lines) == fb.EXEMPLAR_TOP_N
    assert approved_lines[0] == "+ approved hook 11"  # newest first
    assert discarded_lines[0] == "- discarded hook 11"
    assert "APPROVED" in block and "DISCARDED" in block


def test_exemplar_block_counts_exported_as_approved(store):
    fill(store, 20, action="exported")
    block = store.exemplar_block()
    assert block is not None
    assert "+ exported hook 19" in block


def test_exemplar_block_dedupes_hooks(store):
    for _ in range(25):
        store.record("v", cand("same hook"), "approved")
    block = store.exemplar_block()
    assert block.count("+ same hook") == 1


def test_exemplar_block_is_token_capped(store):
    long_hook = "x" * 300  # each hook line truncated to 120 chars
    for i in range(25):
        store.record("v", cand(f"{i} {long_hook}"), "approved")
    block = store.exemplar_block()
    assert len(block) <= fb.EXEMPLAR_MAX_CHARS


def test_exemplar_block_language_matched_when_possible(store):
    fill(store, 10, action="approved", language="en")
    fill(store, 10, action="discarded", language="en")
    store.record("v", cand("hook romanesc", language="ro"), "approved")
    store.record("v", cand("hook prost", language="ro"), "discarded")
    block = store.exemplar_block(language="ro")
    assert "hook romanesc" in block
    assert "+ approved hook" not in block  # the en entries were filtered out


def test_exemplar_block_falls_back_when_language_one_sided(store):
    fill(store, 15, action="approved", language="en")
    fill(store, 15, action="discarded", language="en")
    store.record("v", cand("only ro approved", language="ro"), "approved")
    # ro has no discarded side -> fall back to ALL entries.
    block = store.exemplar_block(language="ro")
    assert "approved hook" in block and "discarded hook" in block


# ---------------------------------------------------------------------------
# calibration — binning + thresholds
# ---------------------------------------------------------------------------
def test_bin_index_edges():
    assert fb.bin_index(0) == 0
    assert fb.bin_index(19.9) == 0
    assert fb.bin_index(20) == 1
    assert fb.bin_index(99.9) == 4
    assert fb.bin_index(100) == 4
    assert fb.bin_index(-5) == 0
    assert fb.bin_index(250) == 4


def test_calibration_none_below_threshold(store):
    fill(store, fb.CALIBRATION_MIN_LABELS - 1, factors=factors(90))
    assert store.calibration_table() is None
    assert store.calibrated_pct(90.0) is None


def test_calibration_maps_bins_to_empirical_approval(store):
    # High-factor candidates: 8 approved, 2 discarded -> 80% approval (bin 4).
    for i in range(8):
        store.record("v", cand(f"hi {i}", factors=factors(90)), "approved")
    for i in range(2):
        store.record("v", cand(f"hi-d {i}", factors=factors(95)), "discarded")
    # Low-factor candidates: 5 approved, 45 discarded -> 10% approval (bin 0).
    for i in range(5):
        store.record("v", cand(f"lo {i}", factors=factors(10)), "approved")
    for i in range(45):
        store.record("v", cand(f"lo-d {i}", factors=factors(15)), "discarded")

    assert store.labels() == 60  # threshold reached
    assert store.calibrated_pct(92.0) == 80
    assert store.calibrated_pct(12.0) == 10


def test_calibration_empty_bin_uses_overall_rate(store):
    for i in range(30):
        store.record("v", cand(f"a{i}", factors=factors(90)), "approved")
    for i in range(30):
        store.record("v", cand(f"d{i}", factors=factors(10)), "discarded")
    # Bin 2 (40-60) has no labels -> overall rate 30/60 = 50%.
    assert store.calibrated_pct(50.0) == 50


def test_calibration_ignores_nudged_and_factorless(store):
    for i in range(30):
        store.record("v", cand(f"a{i}", factors=factors(90)), "approved")
    for i in range(20):
        store.record("v", cand(f"n{i}", factors=factors(90)), "nudged")
    for i in range(10):
        store.record("v", cand(f"x{i}"), "discarded")  # no factors -> skipped
    # 60 labels total; the table only sees the 30 approved -> 100% in bin 4.
    assert store.calibrated_pct(95.0) == 100


def test_calibration_none_when_no_factor_bearing_labels(store):
    fill(store, 60)  # no factors anywhere
    assert store.calibration_table() is None
    assert store.calibrated_pct(50.0) is None


def test_calibration_skips_candidates_with_malformed_factors(store):
    # factors present-as-dict but a value is non-numeric / a key is missing ->
    # _factor_average returns None and the entry is skipped from the table.
    for i in range(30):
        store.record("v", cand(f"good {i}", factors=factors(90)), "approved")
    for i in range(20):
        store.record(
            "v",
            cand(f"bad {i}", factors={"hookStrength": "nope", "emotionalFlow": 1}),
            "discarded",
        )
    for i in range(10):
        store.record("v", cand(f"partial {i}", factors={"hookStrength": 50}), "discarded")
    # Only the 30 well-formed approved entries reach the table -> 100% in bin 4.
    assert store.labels() == 60
    assert store.calibrated_pct(95.0) == 100


# ---------------------------------------------------------------------------
# exemplar block — empty-side / one-sided / blank-hook edges
# ---------------------------------------------------------------------------
def test_exemplar_block_none_when_no_usable_hooks(store):
    # Enough labels to pass the threshold, but every hook is blank -> both sides
    # come back empty and the block is None.
    for _ in range(fb.EXEMPLAR_MIN_LABELS):
        store.record("v", cand(""), "approved")
    assert store.exemplar_block() is None


def test_exemplar_block_skips_blank_hooks_keeps_real_ones(store):
    # Interleave blank-hook entries with real ones; the blank ones are skipped by
    # _recent_hooks (the "not hook -> continue" branch) but the real ones remain.
    for _ in range(fb.EXEMPLAR_MIN_LABELS):
        store.record("v", cand(""), "approved")
    store.record("v", cand("real approved hook"), "approved")
    store.record("v", cand("real discarded hook"), "discarded")
    block = store.exemplar_block()
    assert block is not None
    assert "+ real approved hook" in block
    assert "- real discarded hook" in block


def test_exemplar_block_discarded_only_omits_approved_section(store):
    # Only discarded hooks exist -> the approved section is skipped entirely.
    for i in range(fb.EXEMPLAR_MIN_LABELS + 1):
        store.record("v", cand(f"discarded hook {i}"), "discarded")
    block = store.exemplar_block()
    assert block is not None
    assert "Hooks they APPROVED:" not in block
    assert "Hooks they DISCARDED:" in block


def test_exemplar_block_stays_within_char_budget(store):
    # With TOP_N=5 hooks/side capped at _HOOK_MAX_CHARS=120, the assembled block
    # cannot exceed EXEMPLAR_MAX_CHARS (~1450 worst case < 1600) — the hard
    # truncation at line 190 is defensive and unreachable under these constants.
    for i in range(fb.EXEMPLAR_MIN_LABELS + 10):
        store.record("v", cand(f"hook number {i:03d} " + "y" * 100), "approved")
    block = store.exemplar_block()
    assert len(block) <= fb.EXEMPLAR_MAX_CHARS
