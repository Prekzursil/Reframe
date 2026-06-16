"""Unit tests for media_studio.util — the tiny dependency-free helpers.

Covers the logger configurator (idempotency + stderr-only handler), the
millisecond clock, and the two clamps. No heavy-ML imports.
"""

from __future__ import annotations

import logging
import sys

import pytest
from media_studio import util


# --------------------------------------------------------------------------- #
# get_logger
# --------------------------------------------------------------------------- #
def test_get_logger_configures_stderr_handler_once():
    name = "media_studio.test.util.first"
    logger = util.get_logger(name)
    # A single StreamHandler bound to stderr (stdout is the JSON-RPC channel).
    assert len(logger.handlers) == 1
    handler = logger.handlers[0]
    assert isinstance(handler, logging.StreamHandler)
    assert handler.stream is sys.stderr
    assert logger.level == logging.INFO
    assert logger.propagate is False
    assert logger._media_studio_configured is True


def test_get_logger_is_idempotent_across_repeated_calls():
    # The second call hits the already-configured branch (27 -> 35): no new
    # handler is stacked, so log lines never duplicate on stderr.
    name = "media_studio.test.util.idempotent"
    first = util.get_logger(name)
    handler_count = len(first.handlers)
    second = util.get_logger(name)
    assert second is first
    assert len(second.handlers) == handler_count == 1


def test_get_logger_default_name():
    logger = util.get_logger()
    assert logger.name == "media_studio"


# --------------------------------------------------------------------------- #
# now_ms
# --------------------------------------------------------------------------- #
def test_now_ms_returns_positive_int(monkeypatch):
    monkeypatch.setattr(util.time, "time", lambda: 1.5)
    assert util.now_ms() == 1500
    assert isinstance(util.now_ms(), int)


# --------------------------------------------------------------------------- #
# clamp
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "value,low,high,expected",
    [
        (5, 0, 10, 5),
        (-1, 0, 10, 0),
        (11, 0, 10, 10),
        (0.0, 0.0, 1.0, 0.0),
        (1.0, 0.0, 1.0, 1.0),
    ],
)
def test_clamp_clamps_into_range(value, low, high, expected):
    assert util.clamp(value, low, high) == expected


def test_clamp_raises_when_low_exceeds_high():
    with pytest.raises(ValueError):
        util.clamp(5, 10, 0)


# --------------------------------------------------------------------------- #
# clamp_pct
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "raw,expected",
    [(-5, 0), (0, 0), (33.4, 33), (33.6, 34), (100, 100), (250, 100)],
)
def test_clamp_pct_rounds_and_clamps(raw, expected):
    out = util.clamp_pct(raw)
    assert out == expected
    assert isinstance(out, int)
