"""Shared fakes for the offline Director golden-plan eval harness (WU-eval-harness).

The harness drives the SHIPPED Director path end-to-end —
``director.plan`` -> ``validate_and_reject`` -> ``director.apply`` (-> ``apply_plan``)
— with a FAKE at every seam, so it is fully offline (no network, no model, no
render, no image decode) and deterministic. This module holds those fakes so the
golden-plan test (``test_director_golden_plans.py``) stays declarative:

  * :class:`CannedPlanProvider` — a provider whose ``chat`` returns a fixed
    planner JSON string (the canned EditPlan for a fixture), counting calls so
    the harness can assert exactly-one planner call;
  * :func:`fake_engine` / :func:`build_engines` — fake op-engines that mutate the
    project COPY (appending an apply log) and return a known inverse op, so the
    apply walk is exercised without any real engine, OCR, stitch, or regen;
  * :func:`director_ctx` / :func:`done_result` — an in-memory ``RpcContext`` with
    a real :class:`JobRegistry` that records emitted events, plus a helper to join
    the job thread and read the terminal ``job.done`` payload;
  * :func:`make_services` / :func:`add_project` — a ``Services`` over a tmp dir
    with a registered, transcribed video, the canned provider wired in, and the
    fake engines injected.

NO heavy imports (no faster-whisper / cv2 / numpy / onnxruntime): the seams are
all injected, mirroring ``tests/test_handlers_director.py``.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from media_studio.features.apply_engine import EngineTable
from media_studio.features.project_copy import ProjectCopy
from media_studio.handlers import Services
from media_studio.jobs import JobRegistry
from media_studio.models.edit_plan import EditOp
from media_studio.protocol import RpcContext

#: A 12-second source clip (12000 ms) — the validator's clip bound for every
#: fixture, so a fixture span beyond 12000 ms is provably out-of-range (dropped).
CLIP_DURATION_S = 12.0
CLIP_DURATION_MS = 12000


class CannedPlanProvider:
    """A provider whose ``chat`` returns a fixed planner JSON, counting calls.

    The harness injects one per fixture; ``reply`` is the canned planner output
    (a JSON object with an ``ops`` array) parsed by ``parse_edit_plan`` into the
    typed EditPlan. ``calls`` records every ``chat`` invocation so the test can
    assert the planner ran exactly once on the editPlan-routed provider.
    """

    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.calls: list[list[dict[str, str]]] = []

    def chat(self, messages: list[dict[str, str]], **_k: Any) -> str:
        self.calls.append([dict(m) for m in messages])
        return self.reply


def fake_engine():
    """Return a fake op-engine that logs the op on the COPY + returns an inverse.

    The engine appends the op id to ``project_copy.data["applyLog"]`` (so the test
    can assert the apply order over the COPY) and returns a known ``inv-<id>``
    inverse op of the same kind/span (so the recorded inverse plan is checkable).
    The source manifest is never touched — only the COPY's deep-copied data.
    """

    def engine(op: EditOp, project_copy: ProjectCopy) -> EditOp:
        project_copy.data.setdefault("applyLog", []).append(op.id)
        return EditOp(id=f"inv-{op.id}", kind=op.kind, span=op.span)

    return engine


def build_engines(kinds: tuple[str, ...]) -> EngineTable:
    """Build a fake engines dispatch table covering exactly ``kinds``.

    Each kind maps to its own :func:`fake_engine`. Any op whose kind is absent
    here surfaces as a per-op ``failed`` with auto-rollback in ``apply_plan`` —
    which is itself a useful golden assertion (an unmapped kind never crashes).
    """
    return {kind: fake_engine() for kind in kinds}


def director_ctx() -> RpcContext:
    """An in-memory ``RpcContext`` with a real ``JobRegistry`` recording events.

    Mirrors ``tests/test_handlers_director._director_ctx``: ``job.progress`` and
    ``job.done`` are appended to ``ctx.events`` so :func:`done_result` can read
    the terminal payload after joining the job thread.
    """
    events: list[Any] = []
    jobs = JobRegistry(
        emit_progress=lambda jid, pct, msg: events.append(("progress", jid, pct, msg)),
        emit_done=lambda jid, result: events.append(("done", jid, result)),
    )
    ctx = RpcContext(emit_notification=lambda obj: None, jobs=jobs)
    ctx.events = events  # type: ignore[attr-defined]
    return ctx


def done_result(ctx: RpcContext) -> Any:
    """Join the job thread and return the last ``job.done`` payload.

    Raises ``AssertionError`` if no terminal ``job.done`` was emitted (a job that
    errored or never ran), so a regression surfaces as a clear test failure.
    """
    assert ctx.jobs is not None  # the harness always builds a job-bearing ctx
    ctx.jobs.join(timeout=5)
    done = [e for e in ctx.events if e[0] == "done"]  # type: ignore[attr-defined]
    assert done, "no job.done emitted"
    return done[-1][2]


def make_services(tmp_path: Path, *, provider: Any, engines: EngineTable) -> Services:
    """A ``Services`` over a tmp dir with the canned provider + fake engines wired.

    The library probe + ffprobe are stubbed to :data:`CLIP_DURATION_S` so the
    validator's clip bound is deterministic. ``engines`` is injected as the
    ``director.apply`` dispatch table (the seam), so apply runs without any real
    engine. Mirrors ``tests/test_handlers_director._services``.
    """
    from media_studio import library as _library

    svc = Services(data_dir=tmp_path / "data", provider=provider)
    video_file = tmp_path / "talk.mp4"
    video_file.write_bytes(b"\x00fake")
    svc.library = _library.Library(svc.data_dir / "library.json", probe_duration=lambda _p: CLIP_DURATION_S)
    svc._ffprobe_duration = lambda _p: CLIP_DURATION_S
    svc._director_engines = lambda: engines  # type: ignore[method-assign]
    return svc


def add_project(
    svc: Services,
    *,
    transcript: Any = "hello world",
    tracks: list[dict[str, Any]] | None = None,
) -> str:
    """Register a transcribed project on ``svc`` and return its video id.

    ``transcript`` becomes the project's persisted transcript (fenced as untrusted
    DATA by the planner prompt); ``tracks`` (if given) seeds the manifest tracks so
    track-targeting ops (``overlayText``/``caption``) validate against real tracks.
    Mirrors ``tests/test_handlers_director._add_project``.
    """
    video = svc.library.add(str(svc.data_dir.parent / "talk.mp4"))
    vid = video["id"]
    project = svc._load_or_create_project(vid)
    project.data["transcript"] = transcript
    if tracks is not None:
        project.data["tracks"] = tracks
    project.save()
    return vid


def op_statuses(apply_result: Mapping[str, Any]) -> dict[str, str]:
    """Map ``{opId: status}`` from a ``director.apply`` ``job.done`` payload."""
    return {op["id"]: op["status"] for op in apply_result["opsStatus"]}
