"""WU6 tests — ``features/batch.py`` store + model + checkpoint-on-transition.

Pure store + pure model logic over a ``tmp_path`` JSON document (one file per
batch under ``batches/<batchId>.json``). No runner, no RPC, no media work — those
are later WUs. The store mirrors :class:`recipes.RecipeStore`'s atomic temp+rename
write (a simulated ``os.replace`` failure must leave the prior file intact), but
keyed per-batch so one corrupt batch can never poison another.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from media_studio.features import batch
from media_studio.protocol import RpcError

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
