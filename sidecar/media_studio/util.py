"""Shared, dependency-free helpers for the sidecar.

Kept deliberately tiny and import-light so pure-logic modules (jobs, protocol)
and their tests never pull in heavy-ML deps. Logs always go to stderr — stdout
is reserved for the JSON-RPC framing (see CONTRACTS.md section 2).
"""

from __future__ import annotations

import logging
import sys
import time
from typing import Final

# CONTRACT-NOTE: §2 says logs go to stderr only (stdout is the JSON-RPC channel).
# A single module-level configurator enforces that for every logger in the package.
_LOG_FORMAT: Final[str] = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def get_logger(name: str = "media_studio") -> logging.Logger:
    """Return a package logger that writes to STDERR only.

    Idempotent: repeated calls do not stack handlers, so the sidecar can call
    this from any module without duplicating log lines on stdout.
    """
    logger = logging.getLogger(name)
    if not getattr(logger, "_media_studio_configured", False):
        handler = logging.StreamHandler(stream=sys.stderr)
        handler.setFormatter(logging.Formatter(_LOG_FORMAT))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
        # Mark so re-imports / repeated calls stay idempotent.
        logger._media_studio_configured = True  # type: ignore[attr-defined]
    return logger


def now_ms() -> int:
    """Monotonic-ish wall-clock millisecond timestamp (for ids / timing)."""
    return int(time.time() * 1000)


def clamp(value: float, low: float, high: float) -> float:
    """Clamp ``value`` into the inclusive ``[low, high]`` range."""
    if low > high:
        raise ValueError(f"clamp: low ({low}) must be <= high ({high})")
    return max(low, min(high, value))


def clamp_pct(pct: float) -> int:
    """Clamp a progress percentage into an integer 0..100.

    Job progress notifications carry an integer ``pct`` (§2). Handlers may emit
    floats or out-of-range values; this normalizes them so the UI never sees a
    negative or >100 percentage.
    """
    return int(round(clamp(float(pct), 0.0, 100.0)))
