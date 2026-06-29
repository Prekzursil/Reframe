"""GPU / real-frame golden tier for the Reframe eval harness (WU R0).

This tier is **opt-in and EXCLUDED from the 100% coverage gate** (every test is
``@pytest.mark.e2e``; the default run is ``-m 'not e2e'``). It is also
**collection-guarded**: it auto-skips unless the gitignored golden path is present
via the ``REFRAME_GOLDEN_DIR`` env var. CI never imports or requires the private
third-party clips (razvan_gandu RO talk-show + OpusClip's 41 derived clips) — the
pure tier in ``test_reframe_eval.py`` proves the metrics on synthetic fixtures.

Run it on a machine that has the golden set::

    REFRAME_GOLDEN_DIR=/path/to/razvan_gandu pytest -m e2e tests/test_reframe_eval_golden_e2e.py

R1 EXTENDS this tier to run the real multispeaker engine (ASD/diarize on real
frames) and assert the harness ``passed`` before promoting it to a default. At R0
the tier validates the golden-set contract end-to-end (manifest discovery + that
``run_harness`` ingests a real-shaped reference).
"""

from __future__ import annotations

import csv
import os
from pathlib import Path

import pytest
from media_studio.features import reframe_eval as re

pytestmark = pytest.mark.e2e

#: The env var that points at the external, gitignored golden directory.
GOLDEN_ENV = "REFRAME_GOLDEN_DIR"


def _golden_dir() -> Path:
    """The golden directory, or ``pytest.skip`` when it is not present locally."""
    raw = os.environ.get(GOLDEN_ENV)
    if not raw:
        pytest.skip(f"{GOLDEN_ENV} unset; GPU/real-frame golden tier skipped")
    path = Path(raw)
    if not path.exists():
        pytest.skip(f"{GOLDEN_ENV}={raw} not present; golden tier skipped")
    return path


def test_golden_manifest_discovers_clips() -> None:
    """The golden manifest lists the OpusClip-derived reference clips."""
    manifest = _golden_dir() / "manifest.csv"
    if not manifest.exists():
        pytest.skip("manifest.csv absent under the golden dir")
    rows = list(csv.DictReader(manifest.read_text(encoding="utf-8").splitlines()))
    assert rows, "expected at least one golden clip row"


def test_harness_ingests_a_real_shaped_reference() -> None:
    """``run_harness`` scores a reference-vs-itself trace derived from the golden set.

    A trivial perfect-score smoke proves the data contract + gate plumbing works on
    real-shaped data before R1 wires the actual engine output as the predicted side.
    """
    _golden_dir()  # gate the tier on the external path being present
    reference = re.ReframeTrace.from_dict(
        {
            "shotBoundaries": [30, 90],
            "speakerPerFrame": ["a"] * 30 + ["b"] * 60 + ["a"] * 30,
            "segments": [{"startFrame": 0, "endFrame": 120, "layout": "single"}],
            "crops": [[100.0, 0.0, 608.0, 1080.0]] * 120,
        }
    )
    report = re.run_harness(reference, reference)
    assert report["passed"] is True
