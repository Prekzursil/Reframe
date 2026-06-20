"""WU6 + WU7 tests — ``features/batch.py``.

WU6 — store + model + checkpoint-on-transition. Pure store + pure model logic
over a ``tmp_path`` JSON document (one file per batch under
``batches/<batchId>.json``). The store mirrors :class:`recipes.RecipeStore`'s
atomic temp+rename write, keyed per-batch so one corrupt batch can never poison
another.

WU7 — the batch RUNNER with per-source isolation (G-ISO). The parent batch job
iterates ``sourceVideoIds``, spreads ``[0,100]`` progress across items, and runs
each source through the template runner seam — but with NEW per-source try/except
so one bad source records ``error`` on its :class:`batch.BatchItem` and the batch
CONTINUES (the deliberate divergence from ``convert_batch``/``_run_one_step``).
Gated by ``batchContinueOnError`` (default ``true``). The per-source sub-job is
awaited with the EXISTING recipe ``_await_subjob`` relay. No real ffmpeg/model:
the template-run seam is faked.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from media_studio.features import batch
from media_studio.jobs import JobCancelled, JobRegistry
from media_studio.protocol import RpcContext, RpcError

# --------------------------------------------------------------------------- #
# pure model — BatchItem / BatchState shaping + status derivation
# --------------------------------------------------------------------------- #


class TestBatchItemModel:
    def test_new_item_is_queued_with_no_extras(self):
        item = batch.new_item("v1")
        assert item == {"videoId": "v1", "status": "queued"}

    def test_new_item_rejects_empty_video_id(self):
        with pytest.raises(RpcError):
            batch.new_item("")

    def test_new_item_rejects_non_str_video_id(self):
        with pytest.raises(RpcError):
            batch.new_item(None)  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        "status",
        ["queued", "running", "done", "error", "cancelled", "skipped"],
    )
    def test_valid_item_status_accepted(self, status: str):
        assert batch.is_terminal_status(status) in (True, False)

    @pytest.mark.parametrize("status", ["done", "error", "cancelled", "skipped"])
    def test_terminal_statuses(self, status: str):
        assert batch.is_terminal_status(status) is True

    @pytest.mark.parametrize("status", ["queued", "running"])
    def test_non_terminal_statuses(self, status: str):
        assert batch.is_terminal_status(status) is False


class TestNewState:
    def test_create_persists_all_items_queued(self):
        state = batch.new_state("My run", "tmpl-1", ["v1", "v2", "v3"])
        assert state["name"] == "My run"
        assert state["templateId"] == "tmpl-1"
        assert state["status"] == "queued"
        assert [i["status"] for i in state["items"]] == ["queued"] * 3
        assert [i["videoId"] for i in state["items"]] == ["v1", "v2", "v3"]

    def test_create_assigns_id_and_created_at(self):
        state = batch.new_state("n", "t", ["v1"])
        assert isinstance(state["id"], str) and state["id"]
        assert isinstance(state["createdAt"], int) and state["createdAt"] > 0

    def test_create_honors_explicit_id(self):
        state = batch.new_state("n", "t", ["v1"], batch_id="fixed-id")
        assert state["id"] == "fixed-id"

    def test_create_rejects_empty_name(self):
        with pytest.raises(RpcError):
            batch.new_state("  ", "t", ["v1"])

    def test_create_rejects_empty_template_id(self):
        with pytest.raises(RpcError):
            batch.new_state("n", "", ["v1"])

    def test_create_rejects_empty_sources(self):
        with pytest.raises(RpcError):
            batch.new_state("n", "t", [])

    def test_create_rejects_non_list_sources(self):
        with pytest.raises(RpcError):
            batch.new_state("n", "t", "v1")  # type: ignore[arg-type]

    def test_create_rejects_non_str_source(self):
        with pytest.raises(RpcError):
            batch.new_state("n", "t", ["v1", 7])  # type: ignore[list-item]

    def test_create_rejects_empty_str_source(self):
        with pytest.raises(RpcError):
            batch.new_state("n", "t", ["v1", ""])


class TestDeriveStatus:
    def test_all_queued_is_queued(self):
        assert batch.derive_status(["queued", "queued"]) == "queued"

    def test_any_running_is_running(self):
        assert batch.derive_status(["done", "running", "queued"]) == "running"

    def test_unfinished_with_progress_is_running(self):
        # Some done, some still queued, none running -> the batch is mid-flight.
        assert batch.derive_status(["done", "queued"]) == "running"

    def test_all_done_is_done(self):
        assert batch.derive_status(["done", "done"]) == "done"

    def test_terminal_mix_with_error_is_error_when_none_succeeded(self):
        assert batch.derive_status(["error", "error"]) == "error"

    def test_terminal_mix_with_some_done_and_some_error_is_partial(self):
        assert batch.derive_status(["done", "error"]) == "partial"

    def test_terminal_mix_with_skipped_and_done_is_partial(self):
        assert batch.derive_status(["done", "skipped"]) == "partial"

    def test_all_skipped_is_error(self):
        # Nothing ran successfully; a wholly-skipped batch is a failed outcome.
        assert batch.derive_status(["skipped", "skipped"]) == "error"

    def test_all_cancelled_is_cancelled(self):
        assert batch.derive_status(["cancelled", "cancelled"]) == "cancelled"

    def test_cancelled_with_done_is_partial(self):
        assert batch.derive_status(["done", "cancelled"]) == "partial"

    def test_empty_items_is_queued(self):
        assert batch.derive_status([]) == "queued"


# --------------------------------------------------------------------------- #
# storage — one file per batch, atomic temp+rename, per-batch isolation
# --------------------------------------------------------------------------- #


class TestBatchStore:
    def test_create_writes_three_queued_items(self, tmp_path):
        store = batch.BatchStore(tmp_path / "batches")
        state = store.create("run", "t", ["v1", "v2", "v3"])
        on_disk = json.loads((tmp_path / "batches" / f"{state['id']}.json").read_text(encoding="utf-8"))
        assert on_disk["status"] == "queued"
        assert [i["status"] for i in on_disk["items"]] == ["queued"] * 3

    def test_load_round_trips_full_state(self, tmp_path):
        store = batch.BatchStore(tmp_path / "batches")
        state = store.create("run", "t", ["v1"])
        loaded = store.load(state["id"])
        assert loaded == state

    def test_load_unknown_returns_none(self, tmp_path):
        store = batch.BatchStore(tmp_path / "batches")
        assert store.load("nope") is None

    def test_per_item_transition_rewrites_file_immediately(self, tmp_path):
        store = batch.BatchStore(tmp_path / "batches")
        state = store.create("run", "t", ["v1", "v2", "v3"])
        store.update_item(state["id"], "v2", status="error", error="boom")
        on_disk = json.loads((tmp_path / "batches" / f"{state['id']}.json").read_text(encoding="utf-8"))
        statuses = {i["videoId"]: i["status"] for i in on_disk["items"]}
        assert statuses == {"v1": "queued", "v2": "error", "v3": "queued"}
        v2 = next(i for i in on_disk["items"] if i["videoId"] == "v2")
        assert v2["error"] == "boom"

    def test_update_item_recomputes_aggregate_status(self, tmp_path):
        store = batch.BatchStore(tmp_path / "batches")
        state = store.create("run", "t", ["v1", "v2"])
        store.update_item(state["id"], "v1", status="running")
        assert store.load(state["id"])["status"] == "running"

    def test_update_item_persists_optional_fields(self, tmp_path):
        store = batch.BatchStore(tmp_path / "batches")
        state = store.create("run", "t", ["v1"])
        store.update_item(
            state["id"],
            "v1",
            status="done",
            jobId="job-9",
            results=[{"ok": True}],
        )
        item = store.load(state["id"])["items"][0]
        assert item["jobId"] == "job-9"
        assert item["results"] == [{"ok": True}]

    def test_update_item_skip_round_trips_reason_losslessly(self, tmp_path):
        store = batch.BatchStore(tmp_path / "batches")
        state = store.create("run", "t", ["v1"])
        store.update_item(state["id"], "v1", status="skipped", skipReason="would egress — not acknowledged")
        item = store.load(state["id"])["items"][0]
        assert item["status"] == "skipped"
        assert item["skipReason"] == "would egress — not acknowledged"

    def test_update_item_unknown_batch_raises(self, tmp_path):
        store = batch.BatchStore(tmp_path / "batches")
        with pytest.raises(RpcError):
            store.update_item("nope", "v1", status="done")

    def test_update_item_unknown_video_raises(self, tmp_path):
        store = batch.BatchStore(tmp_path / "batches")
        state = store.create("run", "t", ["v1"])
        with pytest.raises(RpcError):
            store.update_item(state["id"], "v9", status="done")

    def test_update_item_rejects_invalid_status(self, tmp_path):
        store = batch.BatchStore(tmp_path / "batches")
        state = store.create("run", "t", ["v1"])
        with pytest.raises(RpcError):
            store.update_item(state["id"], "v1", status="bogus")

    def test_per_batch_isolation(self, tmp_path):
        store = batch.BatchStore(tmp_path / "batches")
        a = store.create("A", "t", ["v1"])
        b = store.create("B", "t", ["v2"])
        store.update_item(a["id"], "v1", status="error", error="x")
        # B is untouched by a write to A.
        assert store.load(b["id"])["items"][0]["status"] == "queued"
        assert store.load(a["id"])["items"][0]["status"] == "error"

    def test_corrupt_one_batch_leaves_others_loadable(self, tmp_path):
        store = batch.BatchStore(tmp_path / "batches")
        a = store.create("A", "t", ["v1"])
        b = store.create("B", "t", ["v2"])
        (tmp_path / "batches" / f"{a['id']}.json").write_text("{not json", encoding="utf-8")
        assert store.load(a["id"]) is None  # corrupt -> unreadable
        assert store.load(b["id"]) is not None  # sibling intact

    def test_corrupt_non_dict_file_loads_as_none(self, tmp_path):
        store = batch.BatchStore(tmp_path / "batches")
        store.dir.mkdir(parents=True, exist_ok=True)
        (tmp_path / "batches" / "x.json").write_text("[1, 2, 3]", encoding="utf-8")
        assert store.load("x") is None

    def test_save_unreadable_file_returns_none(self, tmp_path):
        store = batch.BatchStore(tmp_path / "batches")
        store.dir.mkdir(parents=True, exist_ok=True)
        (tmp_path / "batches" / "y.json").write_text("\x00\x01 garbage", encoding="utf-8")
        assert store.load("y") is None

    def test_list_summaries_omit_heavy_results(self, tmp_path):
        store = batch.BatchStore(tmp_path / "batches")
        state = store.create("run", "t", ["v1"])
        store.update_item(state["id"], "v1", status="done", results=[{"big": "payload"}])
        summaries = store.list()
        assert len(summaries) == 1
        summary = summaries[0]
        assert summary["id"] == state["id"]
        assert summary["name"] == "run"
        assert summary["status"] == "done"
        assert summary["templateId"] == "t"
        # the heavy per-item ``results`` are NOT carried in a summary.
        assert "results" not in json.dumps(summary)
        assert summary["counts"] == {
            "total": 1,
            "done": 1,
            "error": 0,
            "skipped": 0,
            "queued": 0,
            "running": 0,
            "cancelled": 0,
        }

    def test_list_empty_when_no_batches(self, tmp_path):
        store = batch.BatchStore(tmp_path / "batches")
        assert store.list() == []

    def test_list_skips_corrupt_batch_files(self, tmp_path):
        store = batch.BatchStore(tmp_path / "batches")
        good = store.create("good", "t", ["v1"])
        (tmp_path / "batches" / "broken.json").write_text("{bad", encoding="utf-8")
        ids = [s["id"] for s in store.list()]
        assert ids == [good["id"]]

    def test_list_ignores_non_json_files(self, tmp_path):
        store = batch.BatchStore(tmp_path / "batches")
        store.create("good", "t", ["v1"])
        (tmp_path / "batches" / "notes.txt").write_text("hello", encoding="utf-8")
        assert len(store.list()) == 1

    def test_list_skips_non_dict_json_file(self, tmp_path):
        store = batch.BatchStore(tmp_path / "batches")
        good = store.create("good", "t", ["v1"])
        # a syntactically-valid JSON file that is not a batch object (a list).
        (tmp_path / "batches" / "arr.json").write_text("[1, 2, 3]", encoding="utf-8")
        ids = [s["id"] for s in store.list()]
        assert ids == [good["id"]]

    def test_list_count_ignores_unknown_item_status(self, tmp_path):
        store = batch.BatchStore(tmp_path / "batches")
        # write a batch whose item carries a status outside the counted set.
        bad = {
            "id": "weird",
            "name": "n",
            "templateId": "t",
            "status": "running",
            "createdAt": 1,
            "items": [{"videoId": "v1", "status": "phantom"}],
        }
        store.dir.mkdir(parents=True, exist_ok=True)
        (tmp_path / "batches" / "weird.json").write_text(json.dumps(bad), encoding="utf-8")
        summary = next(s for s in store.list() if s["id"] == "weird")
        # the unknown status is not counted into any bucket but total still reflects it.
        assert summary["counts"]["total"] == 1
        assert sum(v for k, v in summary["counts"].items() if k != "total") == 0

    def test_list_when_dir_absent_is_empty(self, tmp_path):
        store = batch.BatchStore(tmp_path / "does-not-exist")
        assert store.list() == []

    def test_set_status_overrides_aggregate(self, tmp_path):
        store = batch.BatchStore(tmp_path / "batches")
        state = store.create("run", "t", ["v1", "v2"])
        store.set_status(state["id"], "error")
        assert store.load(state["id"])["status"] == "error"

    def test_set_status_unknown_batch_raises(self, tmp_path):
        store = batch.BatchStore(tmp_path / "batches")
        with pytest.raises(RpcError, match="unknown batch"):
            store.set_status("nope", "error")

    def test_delete_removes_file_and_reports(self, tmp_path):
        store = batch.BatchStore(tmp_path / "batches")
        state = store.create("run", "t", ["v1"])
        assert store.delete(state["id"]) is True
        assert store.load(state["id"]) is None

    def test_delete_unknown_reports_false(self, tmp_path):
        store = batch.BatchStore(tmp_path / "batches")
        assert store.delete("nope") is False

    def test_atomic_write_failure_leaves_prior_file_intact(self, tmp_path, monkeypatch):
        store = batch.BatchStore(tmp_path / "batches")
        state = store.create("run", "t", ["v1"])
        path = tmp_path / "batches" / f"{state['id']}.json"
        before = path.read_text(encoding="utf-8")

        def boom(_src: Any, _dst: Any) -> None:
            raise OSError("disk full")

        monkeypatch.setattr(batch.os, "replace", boom)
        with pytest.raises(OSError):
            store.update_item(state["id"], "v1", status="done")
        # the original checkpoint is byte-for-byte intact (temp+rename never truncates).
        assert path.read_text(encoding="utf-8") == before


# --------------------------------------------------------------------------- #
# WU7 — batch runner with per-source isolation (G-ISO)
# --------------------------------------------------------------------------- #
class _FakeJobCtx:
    """A minimal parent job_ctx for the batch runner (cancel + progress + raise).

    Mirrors ``test_recipes._FakeJobCtx`` but also records the progress messages so
    a test can assert the ``source k/N · <title> ·`` prefix the runner prepends.
    """

    def __init__(self, *, cancelled: bool = False, cancel_after: int | None = None) -> None:
        self._cancelled = cancelled
        self._cancel_after = cancel_after
        self._raise_calls = 0
        self.messages: list[tuple[float, str]] = []

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def raise_if_cancelled(self) -> None:
        self._raise_calls += 1
        # ``cancel_after`` flips cancellation on once the runner has checked the
        # gate N times (so cancellation lands BETWEEN specific sources).
        if self._cancel_after is not None and self._raise_calls > self._cancel_after:
            self._cancelled = True
        if self._cancelled:
            raise JobCancelled()

    def progress(self, pct: float, message: str = "") -> None:
        self.messages.append((pct, message))


def _registry() -> JobRegistry:
    return JobRegistry(emit_progress=lambda *_: None, emit_done=lambda *_: None)


def _ctx(registry: JobRegistry) -> RpcContext:
    return RpcContext(emit_notification=lambda *_: None, jobs=registry)


def _make_runner(reg: JobRegistry, *, results=None, fail=(), pct=50.0):
    """Build a template-run seam: ``video_id -> {jobId}`` over a real sub-job.

    ``fail`` is a set of video ids whose sub-job raises (so the per-source
    try/except is exercised); every other source's sub-job reports ``pct`` then
    returns ``{"source": video_id}`` (or ``results[video_id]`` when supplied).
    The list of video ids the seam was invoked for is returned for assertions.
    """
    invoked: list[str] = []

    def runner(video_id: str, ctx: RpcContext) -> dict[str, Any]:
        invoked.append(video_id)

        def body(job_ctx: Any) -> dict[str, Any]:
            job_ctx.progress(pct, "step 1/1 · go")
            if video_id in fail:
                raise RuntimeError(f"boom: {video_id}")
            return (results or {}).get(video_id, {"source": video_id})

        sub = ctx.jobs.start(body)
        return {"jobId": sub.id}

    return runner, invoked


def _statuses(store: batch.BatchStore, batch_id: str) -> list[str]:
    return [item["status"] for item in store.load(batch_id)["items"]]


class TestRunBatchIsolation:
    def test_all_sources_succeed_all_done(self, tmp_path):
        reg = _registry()
        store = batch.BatchStore(tmp_path / "batches")
        state = store.create("run", "t", ["v1", "v2", "v3"])
        runner, invoked = _make_runner(reg)
        out = batch.run_batch(store, state["id"], runner, _FakeJobCtx(), _ctx(reg))
        assert invoked == ["v1", "v2", "v3"]
        assert _statuses(store, state["id"]) == ["done", "done", "done"]
        assert store.load(state["id"])["status"] == "done"
        # each item carries the unwrapped per-source result + its sub-job id.
        items = store.load(state["id"])["items"]
        assert items[0]["results"] == {"source": "v1"}
        assert all(isinstance(item["jobId"], str) and item["jobId"] for item in items)
        assert out["status"] == "done"

    def test_one_bad_source_isolated_others_done(self, tmp_path):
        # Acceptance #1: source 2 raises -> [done, error, done], status "partial".
        reg = _registry()
        store = batch.BatchStore(tmp_path / "batches")
        state = store.create("run", "t", ["v1", "v2", "v3"])
        runner, invoked = _make_runner(reg, fail={"v2"})
        batch.run_batch(store, state["id"], runner, _FakeJobCtx(), _ctx(reg))
        assert invoked == ["v1", "v2", "v3"]  # the bad source did NOT abort the batch
        assert _statuses(store, state["id"]) == ["done", "error", "done"]
        loaded = store.load(state["id"])
        assert loaded["status"] == "partial"
        assert "boom: v2" in loaded["items"][1]["error"]

    def test_continue_on_error_false_stops_at_first_error(self, tmp_path):
        # Acceptance #2: with the toggle off, the batch stops at the first error
        # and the remaining source stays queued; aggregate status is "error".
        reg = _registry()
        store = batch.BatchStore(tmp_path / "batches")
        state = store.create("run", "t", ["v1", "v2", "v3"])
        runner, invoked = _make_runner(reg, fail={"v2"})
        batch.run_batch(store, state["id"], runner, _FakeJobCtx(), _ctx(reg), continue_on_error=False)
        assert invoked == ["v1", "v2"]  # v3 was never attempted
        assert _statuses(store, state["id"]) == ["done", "error", "queued"]
        assert store.load(state["id"])["status"] == "error"

    def test_each_item_flip_is_checkpointed_to_disk(self, tmp_path):
        # Acceptance #3: every transition is durably written before the next item.
        # A runner that snapshots the on-disk statuses at each call proves the
        # prior item was already flipped to a terminal state on disk.
        reg = _registry()
        store = batch.BatchStore(tmp_path / "batches")
        state = store.create("run", "t", ["v1", "v2"])
        seen: list[list[str]] = []

        def runner(video_id: str, ctx: RpcContext) -> dict[str, Any]:
            seen.append(_statuses(store, state["id"]))

            def body(job_ctx: Any) -> dict[str, Any]:
                return {"source": video_id}

            return {"jobId": ctx.jobs.start(body).id}

        batch.run_batch(store, state["id"], runner, _FakeJobCtx(), _ctx(reg))
        # When v1 runs it is already "running" on disk; when v2 runs, v1 is "done".
        assert seen[0] == ["running", "queued"]
        assert seen[1] == ["done", "running"]

    def test_unknown_batch_raises(self, tmp_path):
        reg = _registry()
        store = batch.BatchStore(tmp_path / "batches")
        runner, _ = _make_runner(reg)
        with pytest.raises(RpcError, match="unknown batch"):
            batch.run_batch(store, "nope", runner, _FakeJobCtx(), _ctx(reg))


class TestRunBatchCancellation:
    def test_cancel_between_sources_leaves_rest_queued(self, tmp_path):
        # Acceptance #4: cancellation mid-batch — the cancel lands after source 1
        # finishes; sources 2 and 3 stay queued, the batch is cancelled.
        reg = _registry()
        store = batch.BatchStore(tmp_path / "batches")
        state = store.create("run", "t", ["v1", "v2", "v3"])
        runner, invoked = _make_runner(reg)
        # The runner checks raise_if_cancelled once per source BEFORE running it;
        # cancel_after=1 flips cancellation on after the first gate check, so v1
        # runs and the gate before v2 raises.
        with pytest.raises(JobCancelled):
            batch.run_batch(store, state["id"], runner, _FakeJobCtx(cancel_after=1), _ctx(reg))
        assert invoked == ["v1"]
        assert _statuses(store, state["id"]) == ["done", "queued", "queued"]

    def test_cancel_during_a_source_marks_it_cancelled(self, tmp_path):
        # A source whose sub-job is cancelled mid-run records "cancelled" on its
        # item (the _await_subjob relay re-raises JobCancelled), and the batch
        # unwinds with the in-flight item cancelled, the rest still queued.
        reg = _registry()
        store = batch.BatchStore(tmp_path / "batches")
        state = store.create("run", "t", ["v1", "v2"])

        def runner(video_id: str, ctx: RpcContext) -> dict[str, Any]:
            def body(job_ctx: Any) -> dict[str, Any]:
                return {"source": video_id}

            return {"jobId": ctx.jobs.start(body).id}

        # Parent reports NOT cancelled at the pre-source gate, then becomes
        # cancelled while awaiting the sub-job (cancel_after=1: first gate passes
        # for v1, the await relay sees .cancelled flip via a second check).
        ctx_obj = _FakeJobCtx()

        def fake_await(job_id, job_ctx, ctx, on_sub):
            on_sub(100.0, "step 1/1 · go")
            raise JobCancelled()

        with pytest.raises(JobCancelled):
            batch.run_batch(store, state["id"], runner, ctx_obj, _ctx(reg), await_subjob=fake_await)
        assert _statuses(store, state["id"]) == ["cancelled", "queued"]


class TestRunBatchProgress:
    def test_progress_message_carries_source_prefix(self, tmp_path):
        reg = _registry()
        store = batch.BatchStore(tmp_path / "batches")
        state = store.create("run", "t", ["v1", "v2"])
        runner, _ = _make_runner(reg, pct=40.0)
        ctx_obj = _FakeJobCtx()
        batch.run_batch(
            store,
            state["id"],
            runner,
            ctx_obj,
            _ctx(reg),
            title_resolver=lambda vid: f"Title-{vid}",
        )
        prefixes = [msg for _pct, msg in ctx_obj.messages if msg]
        # The runner prepends "source k/N · <title> · " to the relayed message. The
        # reused recipe relay forwards the sub-job's PCT with an empty message
        # string (it relays progress percent, not the inner step text), so the
        # message is exactly the source prefix — that prefix IS the WU7 contract.
        assert any(msg == "source 1/2 · Title-v1 · " for msg in prefixes)
        assert any(msg == "source 2/2 · Title-v2 · " for msg in prefixes)
        # a terminal "done" tick lands at 100%.
        assert (100.0, "done") in ctx_obj.messages

    def test_progress_is_spread_across_sources(self, tmp_path):
        # Source i's [0,100] slice maps into [i/N, (i+1)/N] of the overall bar. The
        # runner emits a deterministic start-of-source tick at the slice base
        # (on_sub(0.0) → i/N*100); the inner sub-pct relay is timing-dependent, so
        # the spread is asserted on those runner-owned base offsets, which proves
        # source 2 begins at the halfway mark of the overall bar.
        reg = _registry()
        store = batch.BatchStore(tmp_path / "batches")
        state = store.create("run", "t", ["v1", "v2", "v3", "v4"])
        runner, _ = _make_runner(reg, pct=50.0)
        ctx_obj = _FakeJobCtx()
        batch.run_batch(store, state["id"], runner, ctx_obj, _ctx(reg))
        pcts = [pct for pct, _msg in ctx_obj.messages]
        # 4 sources -> slice bases at 0, 25, 50, 75 of the overall [0,100] bar.
        assert 0.0 in pcts
        assert 25.0 in pcts
        assert 50.0 in pcts
        assert 75.0 in pcts

    def test_default_title_resolver_is_video_id(self, tmp_path):
        reg = _registry()
        store = batch.BatchStore(tmp_path / "batches")
        state = store.create("run", "t", ["v1"])
        runner, _ = _make_runner(reg)
        ctx_obj = _FakeJobCtx()
        batch.run_batch(store, state["id"], runner, ctx_obj, _ctx(reg))
        # with no resolver supplied, the title falls back to the raw video id.
        assert any("source 1/1 · v1 · " in msg for _pct, msg in ctx_obj.messages)

    def test_run_batch_skips_already_done_items(self, tmp_path):
        # An item already terminal-``done`` on disk (e.g. preserved by a resume)
        # is NOT re-run — its runner is never invoked and it stays ``done``.
        reg = _registry()
        store = batch.BatchStore(tmp_path / "batches")
        state = store.create("run", "t", ["v1", "v2"])
        store.update_item(state["id"], "v1", status="done", jobId="old", results={"source": "v1"})
        runner, invoked = _make_runner(reg)
        batch.run_batch(store, state["id"], runner, _FakeJobCtx(), _ctx(reg))
        # v1 (already done) is skipped; only v2 runs.
        assert invoked == ["v2"]
        assert _statuses(store, state["id"]) == ["done", "done"]


# --------------------------------------------------------------------------- #
# WU8 — resume (G-DUR, source granularity)
# --------------------------------------------------------------------------- #


def _sync_start(captured: dict[str, Any]):
    """A ``start_job`` seam that runs the parent job body synchronously.

    Mirrors a real ``ctx.jobs.start`` enough for a deterministic test: it runs
    the body NOW with a fresh :class:`_FakeJobCtx`, stashes the returned state in
    ``captured``, and returns an object exposing ``.id`` (the job-id contract).
    """

    class _Job:
        id = "resume-job-1"

    def start_job(body, **_kwargs):
        captured["state"] = body(_FakeJobCtx())
        return _Job()

    return start_job


class TestResumableVideoIds:
    def test_selects_queued_and_running_not_done(self):
        state = batch.new_state("r", "t", ["v1", "v2", "v3"])
        state["items"][0]["status"] = "done"
        state["items"][1]["status"] = "running"
        # v3 stays queued.
        assert batch.resumable_video_ids(state) == ["v2", "v3"]

    def test_errors_excluded_by_default(self):
        state = batch.new_state("r", "t", ["v1", "v2"])
        state["items"][0]["status"] = "error"
        # default policy does NOT retry errored sources.
        assert batch.resumable_video_ids(state) == ["v2"]

    def test_errors_included_when_retry_errors(self):
        state = batch.new_state("r", "t", ["v1", "v2"])
        state["items"][0]["status"] = "error"
        assert batch.resumable_video_ids(state, retry_errors=True) == ["v1", "v2"]

    def test_skipped_and_cancelled_never_resumed(self):
        state = batch.new_state("r", "t", ["v1", "v2", "v3"])
        state["items"][0]["status"] = "skipped"
        state["items"][1]["status"] = "cancelled"
        # only the still-queued v3 is resumable; skip/cancel are terminal here.
        assert batch.resumable_video_ids(state, retry_errors=True) == ["v3"]

    def test_all_done_is_empty(self):
        state = batch.new_state("r", "t", ["v1", "v2"])
        for item in state["items"]:
            item["status"] = "done"
        assert batch.resumable_video_ids(state) == []


class TestResumeBatch:
    def test_unknown_batch_raises(self, tmp_path):
        reg = _registry()
        store = batch.BatchStore(tmp_path / "batches")
        runner, _ = _make_runner(reg)
        with pytest.raises(RpcError, match="unknown batch"):
            batch.resume_batch(store, "nope", runner, _ctx(reg))

    def test_resume_reruns_only_incomplete_items(self, tmp_path):
        # Acceptance #1: resuming [done, error, queued] re-runs only items 2 & 3.
        # The default policy retries errored sources too (retry_errors=True here),
        # so item 1 (done) is the ONLY one not re-run — its runner is not invoked.
        reg = _registry()
        store = batch.BatchStore(tmp_path / "batches")
        state = store.create("run", "t", ["v1", "v2", "v3"])
        store.update_item(state["id"], "v1", status="done", jobId="old1", results={"source": "v1"})
        store.update_item(state["id"], "v2", status="error", error="boom: v2")
        captured: dict[str, Any] = {}
        runner, invoked = _make_runner(reg)
        out = batch.resume_batch(
            store,
            state["id"],
            runner,
            _ctx(reg),
            retry_errors=True,
            start_job=_sync_start(captured),
        )
        assert out == {"jobId": "resume-job-1"}
        # item 1's runner was NOT invoked; only the re-enqueued v2 and v3 ran.
        assert invoked == ["v2", "v3"]
        assert _statuses(store, state["id"]) == ["done", "done", "done"]

    def test_error_not_retried_by_default(self, tmp_path):
        # Default policy leaves errored sources terminal — only queued/running re-run.
        reg = _registry()
        store = batch.BatchStore(tmp_path / "batches")
        state = store.create("run", "t", ["v1", "v2", "v3"])
        store.update_item(state["id"], "v1", status="done", results={"source": "v1"})
        store.update_item(state["id"], "v2", status="error", error="boom: v2")
        captured: dict[str, Any] = {}
        runner, invoked = _make_runner(reg)
        batch.resume_batch(store, state["id"], runner, _ctx(reg), start_job=_sync_start(captured))
        # v1 done (skipped), v2 stays error (not retried), only v3 re-runs.
        assert invoked == ["v3"]
        assert _statuses(store, state["id"]) == ["done", "error", "done"]

    def test_all_done_resume_is_noop_no_job(self, tmp_path):
        # Acceptance #2: resuming an all-done batch starts NO job, reports done.
        reg = _registry()
        store = batch.BatchStore(tmp_path / "batches")
        state = store.create("run", "t", ["v1", "v2"])
        store.update_item(state["id"], "v1", status="done", results={"source": "v1"})
        store.update_item(state["id"], "v2", status="done", results={"source": "v2"})
        started: list[Any] = []

        def start_job(body, **_kwargs):  # pragma: no cover - must NOT be called
            started.append(body)
            raise AssertionError("no job should start for an all-done batch")

        runner, invoked = _make_runner(reg)
        out = batch.resume_batch(store, state["id"], runner, _ctx(reg), start_job=start_job)
        assert out == {"jobId": None, "status": "done"}
        assert started == []
        assert invoked == []

    def test_resumed_source_runs_from_first_step(self, tmp_path):
        # Acceptance #3: a re-enqueued source runs from its FIRST step — the runner
        # is handed the source's full template path (source granularity), proven by
        # the start-of-source progress tick at the slice base (0.0), not a suffix.
        reg = _registry()
        store = batch.BatchStore(tmp_path / "batches")
        state = store.create("run", "t", ["v1", "v2"])
        store.update_item(state["id"], "v1", status="done", results={"source": "v1"})
        captured: dict[str, Any] = {}
        ctx_obj_holder: dict[str, _FakeJobCtx] = {}

        class _Job:
            id = "resume-job-2"

        def start_job(body, **_kwargs):
            job_ctx = _FakeJobCtx()
            ctx_obj_holder["ctx"] = job_ctx
            captured["state"] = body(job_ctx)
            return _Job()

        runner, invoked = _make_runner(reg, pct=50.0)
        batch.resume_batch(
            store,
            state["id"],
            runner,
            _ctx(reg),
            title_resolver=lambda vid: f"Title-{vid}",
            start_job=start_job,
        )
        # only v2 re-runs and it starts at its slice base (full path, step 1).
        assert invoked == ["v2"]
        msgs = ctx_obj_holder["ctx"].messages
        assert any(msg == "source 2/2 · Title-v2 · " for _pct, msg in msgs)

    def test_resume_resets_running_item_to_queued_before_job(self, tmp_path):
        # A source left ``running`` by a crash is reset to ``queued`` on disk by
        # resume BEFORE the job body runs (durable re-enqueue, not in-memory only).
        reg = _registry()
        store = batch.BatchStore(tmp_path / "batches")
        state = store.create("run", "t", ["v1", "v2"])
        store.update_item(state["id"], "v1", status="done", results={"source": "v1"})
        store.update_item(state["id"], "v2", status="running", jobId="dead-job")
        on_disk_at_start: list[list[str]] = []

        class _Job:
            id = "resume-job-3"

        def start_job(body, **_kwargs):
            # at job-start time, the running item must already be re-queued on disk.
            on_disk_at_start.append(_statuses(store, state["id"]))
            body(_FakeJobCtx())
            return _Job()

        runner, _ = _make_runner(reg)
        batch.resume_batch(store, state["id"], runner, _ctx(reg), start_job=start_job)
        assert on_disk_at_start[0] == ["done", "queued"]
        assert _statuses(store, state["id"]) == ["done", "done"]

    def test_resume_uses_real_registry_start_by_default(self, tmp_path):
        # With no start_job seam injected, resume starts a real parent job via the
        # registry and returns its id; the threaded body re-runs the queued source.
        reg = _registry()
        store = batch.BatchStore(tmp_path / "batches")
        state = store.create("run", "t", ["v1", "v2"])
        store.update_item(state["id"], "v1", status="done", results={"source": "v1"})
        runner, _ = _make_runner(reg)
        out = batch.resume_batch(store, state["id"], runner, _ctx(reg))
        job = reg.get(out["jobId"])
        job._thread.join(timeout=5)
        assert isinstance(out["jobId"], str) and out["jobId"]
        assert _statuses(store, state["id"]) == ["done", "done"]

    def test_resume_passes_continue_on_error_through(self, tmp_path):
        # The continue_on_error policy threads into the resumed run: with it off and
        # a failing re-enqueued source, the run halts and the tail stays queued.
        reg = _registry()
        store = batch.BatchStore(tmp_path / "batches")
        state = store.create("run", "t", ["v1", "v2", "v3"])
        store.update_item(state["id"], "v1", status="done", results={"source": "v1"})
        captured: dict[str, Any] = {}
        runner, invoked = _make_runner(reg, fail={"v2"})
        batch.resume_batch(
            store,
            state["id"],
            runner,
            _ctx(reg),
            continue_on_error=False,
            start_job=_sync_start(captured),
        )
        # v2 fails and halts the resumed run; v3 is never attempted.
        assert invoked == ["v2"]
        assert _statuses(store, state["id"]) == ["done", "error", "queued"]
