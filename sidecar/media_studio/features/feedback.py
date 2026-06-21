"""Feedback flywheel — implicit labels, taste exemplars, score calibration (P3-D).

An **append-only** JSONL store at ``%APPDATA%/media-studio/feedback/
feedback.jsonl`` captures every approve / discard / nudge / export action the
user takes on a candidate (the candidate payload + factors + action + ts).
Three consumers:

1. **RPC** (frozen names): ``feedback.record({videoId, candidate, action})``
   -> ``{ok:true}`` and ``feedback.stats()`` -> ``{labels:int, calibrated:bool}``.
2. **Taste exemplars** (>= 20 labels): :meth:`FeedbackStore.exemplar_block`
   renders a compact block (top-5 approved hooks + top-5 discarded hooks,
   <= ~400 tokens, language-matched when possible) that ``features.select``
   embeds into its system prompt.
3. **Calibration** (>= 50 labels): :meth:`FeedbackStore.calibrated_pct` maps a
   candidate's raw factor-average through a 5-bin empirical approval table;
   select uses the result as ``calibratedPct`` (it REPLACES ``viralityPct`` in
   the candidate payload). ``feedback.stats`` flags ``calibrated:true``.

Implicit-label semantics: ``approved`` and ``exported`` count as POSITIVE,
``discarded`` as NEGATIVE; ``nudged`` counts toward the label totals (it is a
taste signal) but joins neither side of the approval table. LoRA tier is
explicitly deferred (PLAN-P2 P3-D).

Pure stdlib (json + pathlib): no heavy imports, nothing to pre-import in
``__main__``. Corrupt JSONL lines are skipped, never fatal.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..settings_store import default_config_dir
from ..util import get_logger

log = get_logger("media_studio.feedback")

# Frozen wire values (CONTRACTS.md P3 mini-contract / app rpc.ts).
ACTIONS = ("approved", "discarded", "nudged", "exported")
POSITIVE_ACTIONS = frozenset({"approved", "exported"})
NEGATIVE_ACTIONS = frozenset({"discarded"})

# Thresholds (P3-D): exemplars at >= 20 labels, calibration at >= 50.
EXEMPLAR_MIN_LABELS = 20
CALIBRATION_MIN_LABELS = 50
EXEMPLAR_TOP_N = 5
# Compact block budget: <= ~400 tokens ~= 1600 chars at ~4 chars/token.
EXEMPLAR_MAX_CHARS = 1600
_HOOK_MAX_CHARS = 120

# Calibration: 5 equal bins over the 0-100 raw factor-average.
CALIBRATION_BINS = 5
_BIN_WIDTH = 100.0 / CALIBRATION_BINS

# The four P3-C factors (kept in sync with features.select.FACTOR_NAMES).
_FACTOR_NAMES = ("hookStrength", "emotionalFlow", "perceivedValue", "shareability")

_STORE_DIR_NAME = "feedback"
_STORE_FILE_NAME = "feedback.jsonl"


def default_feedback_path() -> Path:
    """%APPDATA%/media-studio/feedback/feedback.jsonl (config-dir resolved)."""
    return default_config_dir() / _STORE_DIR_NAME / _STORE_FILE_NAME


def _factor_average(candidate: dict[str, Any]) -> float | None:
    """Mean of the four factor scores, or None when factors are absent."""
    factors = candidate.get("factors")
    if not isinstance(factors, dict):
        return None
    values: list[float] = []
    for name in _FACTOR_NAMES:
        try:
            values.append(float(factors[name]))
        except (KeyError, TypeError, ValueError):
            return None
    return sum(values) / len(values)


def bin_index(raw: float) -> int:
    """The 5-bin index (0..4) for a raw 0-100 factor-average."""
    raw = max(0.0, min(100.0, float(raw)))
    return min(CALIBRATION_BINS - 1, int(raw // _BIN_WIDTH))


class FeedbackStore:
    """The append-only JSONL feedback store + its derived views.

    ``path`` is injectable for tests (defaults to the %APPDATA% location).
    Every public method re-reads the file — the store is small (one JSON line
    per user action) and freshness beats caching here.
    """

    def __init__(self, path: str | os.PathLike | None = None) -> None:
        self.path = Path(path) if path is not None else default_feedback_path()

    # ------------------------------------------------------------------ I/O
    def record(self, video_id: str, candidate: Any, action: str) -> dict[str, Any]:
        """Append one labeled action; returns the stored entry.

        ``candidate`` is untyped on purpose: this is the validation boundary for
        the raw RPC ``params.get("candidate")`` (``Any | None``); a non-dict
        raises ``ValueError`` below so the RPC layer can surface INVALID_PARAMS.
        """
        if action not in ACTIONS:
            raise ValueError(f"action must be one of {list(ACTIONS)}, got {action!r}")
        if not isinstance(candidate, dict):
            raise ValueError("candidate (object) is required")
        entry = {
            "videoId": str(video_id or ""),
            "candidate": dict(candidate),
            "action": action,
            "ts": time.time(),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    def entries(self) -> list[dict[str, Any]]:
        """All stored entries in append order (corrupt lines skipped)."""
        if not self.path.exists():
            return []
        out: list[dict[str, Any]] = []
        try:
            raw = self.path.read_text(encoding="utf-8")
        except OSError:
            return []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue  # append-only file: a torn line must never be fatal
            if isinstance(obj, dict) and obj.get("action") in ACTIONS:
                out.append(obj)
        return out

    # ----------------------------------------------------------------- stats
    def labels(self) -> int:
        return len(self.entries())

    def stats(self) -> dict[str, Any]:
        """The frozen ``feedback.stats`` payload: {labels, calibrated}."""
        n = self.labels()
        return {"labels": n, "calibrated": n >= CALIBRATION_MIN_LABELS}

    # ------------------------------------------------------------- exemplars
    def exemplar_block(self, language: str | None = None) -> str | None:
        """The taste-exemplar prompt block, or None below the label threshold.

        Picks the most recent :data:`EXEMPLAR_TOP_N` approved and discarded
        hooks (deduped, truncated). When ``language`` is given and at least
        one approved AND one discarded entry carry a matching
        ``candidate.language``, only matching entries are used ("language-
        matched when possible"); otherwise all entries count.
        """
        entries = self.entries()
        if len(entries) < EXEMPLAR_MIN_LABELS:
            return None

        if language:
            lang = str(language).strip().lower()
            matched = [e for e in entries if str(e.get("candidate", {}).get("language", "")).strip().lower() == lang]
            if _has_both_sides(matched):
                entries = matched

        approved = _recent_hooks(entries, POSITIVE_ACTIONS)
        discarded = _recent_hooks(entries, NEGATIVE_ACTIONS)
        if not approved and not discarded:
            return None

        lines: list[str] = ["TASTE CALIBRATION — this user's past labels on clips like these:"]
        if approved:
            lines.append("Hooks they APPROVED:")
            lines.extend(f"+ {h}" for h in approved)
        if discarded:
            lines.append("Hooks they DISCARDED:")
            lines.extend(f"- {h}" for h in discarded)
        lines.append("Prefer clips in the spirit of the approved hooks; avoid the discarded kind.")
        block = "\n".join(lines)
        if (
            len(block) > EXEMPLAR_MAX_CHARS
        ):  # pragma: no cover - unreachable: worst-case block ~1408 chars (<=5+5 hooks x 122 + labels) < 1600 budget
            block = block[: EXEMPLAR_MAX_CHARS - 1].rstrip() + "…"
        return block

    # ------------------------------------------------------------ calibration
    def calibration_table(self) -> list[float | None] | None:
        """Per-bin empirical approval rate (None below threshold / no signal).

        Bin value = positives / (positives + negatives) among labeled entries
        whose candidate carries the four factors; an empty bin is filled with
        the overall approval rate.
        """
        entries = self.entries()
        if len(entries) < CALIBRATION_MIN_LABELS:
            return None
        pos = [0] * CALIBRATION_BINS
        neg = [0] * CALIBRATION_BINS
        for entry in entries:
            action = entry.get("action")
            if action in POSITIVE_ACTIONS:
                side = pos
            elif action in NEGATIVE_ACTIONS:
                side = neg
            else:
                continue  # 'nudged' counts as a label but not in the table
            raw = _factor_average(entry.get("candidate") or {})
            if raw is None:
                continue
            side[bin_index(raw)] += 1
        total_pos = sum(pos)
        total_neg = sum(neg)
        if total_pos + total_neg == 0:
            return None
        overall = total_pos / (total_pos + total_neg)
        table: list[float | None] = []
        for p, n in zip(pos, neg, strict=False):
            table.append(p / (p + n) if (p + n) > 0 else overall)
        return table

    def calibrated_pct(self, raw: float) -> int | None:
        """Map a raw factor-average through the approval table -> 0-100 int.

        None when calibration is not yet active (label count below threshold
        or no factor-bearing labels) — the caller keeps ``viralityPct``.
        """
        table = self.calibration_table()
        if table is None:
            return None
        rate = table[bin_index(raw)]
        if rate is None:  # pragma: no cover - table fills empty bins
            return None
        return int(round(100 * float(rate)))


def _has_both_sides(entries: list[dict[str, Any]]) -> bool:
    actions = {e.get("action") for e in entries}
    return bool(actions & POSITIVE_ACTIONS) and bool(actions & NEGATIVE_ACTIONS)


def _recent_hooks(entries: list[dict[str, Any]], actions: frozenset) -> list[str]:
    """Most-recent-first, deduped, truncated hooks for the given action side."""
    hooks: list[str] = []
    seen = set()
    for entry in reversed(entries):  # append order -> newest last
        if entry.get("action") not in actions:
            continue
        hook = str((entry.get("candidate") or {}).get("hook", "") or "").strip()
        if not hook:
            continue
        key = hook.lower()
        if key in seen:
            continue
        seen.add(key)
        hooks.append(hook[:_HOOK_MAX_CHARS])
        if len(hooks) >= EXEMPLAR_TOP_N:
            break
    return hooks


# --------------------------------------------------------------------------- #
# RPC registration (feedback.record / feedback.stats — frozen names)
# --------------------------------------------------------------------------- #
def register(
    *,
    register_fn: Callable[[str, Callable[..., Any]], None],
    store: FeedbackStore | None = None,
) -> FeedbackStore:
    """Register the two feedback methods; returns the bound store.

    ``register_fn`` is ``protocol.register`` in production (handlers.py wires
    it); tests pass a fake registrar + a tmp-path store.
    """
    st = store or FeedbackStore()

    def feedback_record(params: dict[str, Any], ctx: Any) -> dict[str, Any]:
        """``feedback.record({videoId, candidate, action})`` -> ``{ok:true}``."""
        video_id = params.get("videoId")
        if not isinstance(video_id, str) or not video_id:
            raise _invalid_params("videoId (str) is required")
        candidate = params.get("candidate")
        action = params.get("action")
        try:
            st.record(video_id, candidate, str(action))
        except ValueError as exc:
            raise _invalid_params(str(exc)) from exc
        return {"ok": True}

    def feedback_stats(params: dict[str, Any], ctx: Any) -> dict[str, Any]:
        """``feedback.stats()`` -> ``{labels:int, calibrated:bool}``."""
        return st.stats()

    register_fn("feedback.record", feedback_record)
    register_fn("feedback.stats", feedback_stats)
    return st


def _invalid_params(message: str) -> Exception:
    """INVALID_PARAMS RpcError (lazy import — mirrors shortmaker's helper)."""
    from ..protocol import ErrorCode, RpcError

    return RpcError(message, ErrorCode.INVALID_PARAMS)


__all__ = [
    "ACTIONS",
    "CALIBRATION_BINS",
    "CALIBRATION_MIN_LABELS",
    "EXEMPLAR_MAX_CHARS",
    "EXEMPLAR_MIN_LABELS",
    "EXEMPLAR_TOP_N",
    "FeedbackStore",
    "bin_index",
    "default_feedback_path",
    "register",
]
