"""Shared pytest fixtures for the sidecar-core tests.

Deliberately heavy-ML-free: only stdlib + the pure-logic modules under test are
imported. No faster-whisper / scenedetect / httpx import happens here.
"""

from __future__ import annotations

import io
import json
from typing import Any

import pytest
from hypothesis import HealthCheck, settings
from media_studio import protocol
from media_studio.jobs import JobRegistry

# --- Hypothesis: a deterministic, bounded CI profile -----------------------
# WU-B property/fuzz layer. The default Hypothesis profile is non-deterministic
# (random seed) and enforces a 200ms per-example deadline — both flake the
# 100%-coverage gate on the slow WSL-on-/mnt/c box. The "ci" profile pins a
# bounded example count, disables the deadline, and turns OFF the on-disk
# example database so a stale .hypothesis/ carryover can never change a run.
# ``derandomize`` makes the example stream a pure function of the test body, so
# the suite is byte-reproducible across machines/reruns (deterministic CI).
settings.register_profile(
    "ci",
    max_examples=75,
    deadline=None,
    derandomize=True,
    database=None,
    print_blob=False,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.load_profile("ci")


@pytest.fixture()
def collected() -> list[tuple[str, tuple]]:
    """A simple list that records (kind, payload) tuples from emit sinks."""
    return []


@pytest.fixture()
def emit_sinks(collected):
    """Return (emit_progress, emit_done) sinks that append to ``collected``."""

    def emit_progress(job_id: str, pct: int, message: str) -> None:
        collected.append(("progress", (job_id, pct, message)))

    def emit_done(job_id: str, result: Any) -> None:
        collected.append(("done", (job_id, result)))

    return emit_progress, emit_done


@pytest.fixture()
def registry(emit_sinks) -> JobRegistry:
    """A JobRegistry wired to the recording sinks."""
    emit_progress, emit_done = emit_sinks
    return JobRegistry(emit_progress=emit_progress, emit_done=emit_done)


@pytest.fixture(autouse=True)
def _restore_methods():
    """Snapshot/restore the global METHODS registry around each test.

    Tests that register/clear methods must not leak into other tests. The
    built-in ping/job.* handlers are restored by re-importing module state.
    """
    saved: dict[str, Any] = dict(protocol.METHODS)
    try:
        yield
    finally:
        protocol.METHODS.clear()
        protocol.METHODS.update(saved)


class FakeStreams:
    """Drives an RpcServer with in-memory text streams (no real stdio)."""

    def __init__(self, lines: list[str]):
        # Join request dicts/strings into newline-delimited input.
        rendered = []
        for line in lines:
            if isinstance(line, (dict, list)):
                rendered.append(json.dumps(line))
            else:
                rendered.append(str(line))
        self.instream = io.StringIO("\n".join(rendered) + ("\n" if rendered else ""))
        self.outstream = io.StringIO()

    def output_objects(self) -> list[dict[str, Any]]:
        """Parse every non-empty stdout line back into a dict."""
        out: list[dict[str, Any]] = []
        for raw in self.outstream.getvalue().splitlines():
            raw = raw.strip()
            if raw:
                out.append(json.loads(raw))
        return out


@pytest.fixture()
def make_streams():
    """Factory: build a FakeStreams from a list of requests/lines."""

    def _factory(lines: list[Any]) -> FakeStreams:
        return FakeStreams(lines)

    return _factory
