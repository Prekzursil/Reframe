"""Tests for media_studio.features.recipes — saved multi-step pipelines.

Pure logic + filesystem + the real JobRegistry (stdlib). No media work: recipe
steps invoke fake methods on an injected registry. Covers CRUD, ref resolution,
sequential execution with per-step progress, sub-job awaiting, and errors.
"""

from __future__ import annotations

from typing import Any

import pytest
from media_studio.features import recipes
from media_studio.jobs import JobCancelled, JobRegistry
from media_studio.protocol import RpcContext, RpcError


# --------------------------------------------------------------------------- #
# pure: normalize_recipe
# --------------------------------------------------------------------------- #
class TestNormalizeRecipe:
    def test_full_recipe_normalized(self):
        r = recipes.normalize_recipe(
            {"name": "  Pipe  ", "steps": [{"method": "a.b", "params": {"x": 1}, "label": "Step A"}]}
        )
        assert r["name"] == "Pipe"
        assert r["id"]  # generated
        assert r["steps"][0] == {"method": "a.b", "params": {"x": 1}, "label": "Step A"}

    def test_label_defaults_to_method(self):
        r = recipes.normalize_recipe({"name": "x", "steps": [{"method": "transcribe.start"}]})
        assert r["steps"][0]["label"] == "transcribe.start"
        assert r["steps"][0]["params"] == {}

    def test_id_preserved_when_given(self):
        r = recipes.normalize_recipe({"id": "fixed", "name": "x", "steps": [{"method": "m"}]})
        assert r["id"] == "fixed"

    @pytest.mark.parametrize(
        "bad",
        [
            {"steps": [{"method": "m"}]},  # no name
            {"name": "", "steps": [{"method": "m"}]},  # blank name
            {"name": "x"},  # no steps
            {"name": "x", "steps": []},  # empty steps
            {"name": "x", "steps": [{}]},  # step without method
            {"name": "x", "steps": [{"method": "m", "params": "no"}]},  # bad params
            {"name": "x", "steps": ["nope"]},  # step not an object
        ],
    )
    def test_rejects_malformed(self, bad):
        with pytest.raises(RpcError):
            recipes.normalize_recipe(bad)


# --------------------------------------------------------------------------- #
# pure: resolve_refs
# --------------------------------------------------------------------------- #
class TestResolveRefs:
    def test_resolves_dotted_path(self):
        prior = [{"track": {"id": "T1"}}]
        out = recipes.resolve_refs({"trackId": "$0.track.id", "lang": "es"}, prior)
        assert out == {"trackId": "T1", "lang": "es"}

    def test_list_index_in_path(self):
        prior = [{"candidates": [{"rank": 1}, {"rank": 2}]}]
        out = recipes.resolve_refs({"r": "$0.candidates.1.rank"}, prior)
        assert out["r"] == 2

    def test_out_of_range_ref_is_none(self):
        assert recipes.resolve_refs({"x": "$5.k"}, [])["x"] is None

    def test_missing_path_is_none(self):
        assert recipes.resolve_refs({"x": "$0.nope.deep"}, [{"a": 1}])["x"] is None

    def test_non_ref_strings_passthrough(self):
        assert recipes.resolve_refs({"x": "literal", "y": 3}, [])["x"] == "literal"


# --------------------------------------------------------------------------- #
# RecipeStore
# --------------------------------------------------------------------------- #
class TestRecipeStore:
    def test_save_then_list(self, tmp_path):
        store = recipes.RecipeStore(tmp_path / "r.json")
        store.save({"id": "1", "name": "A", "steps": []})
        assert [r["id"] for r in store.list()] == ["1"]

    def test_save_upserts_same_id(self, tmp_path):
        store = recipes.RecipeStore(tmp_path / "r.json")
        store.save({"id": "1", "name": "A", "steps": []})
        store.save({"id": "1", "name": "A2", "steps": []})
        listed = store.list()
        assert len(listed) == 1 and listed[0]["name"] == "A2"

    def test_delete(self, tmp_path):
        store = recipes.RecipeStore(tmp_path / "r.json")
        store.save({"id": "1", "name": "A", "steps": []})
        assert store.delete("1") is True
        assert store.delete("1") is False  # already gone
        assert store.list() == []

    def test_get(self, tmp_path):
        store = recipes.RecipeStore(tmp_path / "r.json")
        store.save({"id": "1", "name": "A", "steps": []})
        assert store.get("1")["name"] == "A"
        assert store.get("nope") is None

    def test_corrupt_file_treated_as_empty(self, tmp_path):
        p = tmp_path / "r.json"
        p.write_text("not json{", encoding="utf-8")
        assert recipes.RecipeStore(p).list() == []

    def test_non_list_file_treated_as_empty(self, tmp_path):
        p = tmp_path / "r.json"
        p.write_text('{"oops": 1}', encoding="utf-8")
        assert recipes.RecipeStore(p).list() == []


# --------------------------------------------------------------------------- #
# Recipes — CRUD handlers
# --------------------------------------------------------------------------- #
def _ctx(registry=None) -> RpcContext:
    return RpcContext(emit_notification=lambda *_: None, jobs=registry)


class TestCrudHandlers:
    def test_save_normalizes_and_persists(self, tmp_path):
        svc = recipes.Recipes(recipes.RecipeStore(tmp_path / "r.json"))
        out = svc.save({"recipe": {"name": "P", "steps": [{"method": "m"}]}}, _ctx())
        assert out["recipe"]["name"] == "P"
        assert svc.list({}, _ctx())["recipes"][0]["name"] == "P"

    def test_save_requires_object(self, tmp_path):
        svc = recipes.Recipes(recipes.RecipeStore(tmp_path / "r.json"))
        with pytest.raises(RpcError):
            svc.save({"recipe": "nope"}, _ctx())

    def test_delete_handler(self, tmp_path):
        svc = recipes.Recipes(recipes.RecipeStore(tmp_path / "r.json"))
        svc.save({"recipe": {"id": "1", "name": "P", "steps": [{"method": "m"}]}}, _ctx())
        assert svc.delete({"id": "1"}, _ctx())["ok"] is True

    def test_delete_requires_id(self, tmp_path):
        svc = recipes.Recipes(recipes.RecipeStore(tmp_path / "r.json"))
        with pytest.raises(RpcError):
            svc.delete({}, _ctx())


# --------------------------------------------------------------------------- #
# Recipes.run — the orchestrated pipeline
# --------------------------------------------------------------------------- #
class TestRun:
    def _registry(self):
        events: list[tuple] = []

        def on_prog(jid, pct, msg):
            events.append(("progress", jid, pct, msg))

        def on_done(jid, result):
            events.append(("done", jid, result))

        return JobRegistry(emit_progress=on_prog, emit_done=on_done), events

    def test_run_unknown_recipe_raises(self, tmp_path):
        reg, _ = self._registry()
        svc = recipes.Recipes(recipes.RecipeStore(tmp_path / "r.json"))
        with pytest.raises(RpcError):
            svc.run({"id": "nope"}, _ctx(reg))

    def test_run_requires_registry(self, tmp_path):
        svc = recipes.Recipes(recipes.RecipeStore(tmp_path / "r.json"))
        svc.save({"recipe": {"id": "1", "name": "P", "steps": [{"method": "m"}]}}, _ctx())
        with pytest.raises(RpcError):
            svc.run({"id": "1"}, _ctx(None))

    def test_direct_steps_run_in_order_with_ref_resolution(self, tmp_path):
        reg, _ = self._registry()
        calls: list[tuple[str, dict]] = []

        def gen(params, ctx):
            calls.append(("gen", params))
            return {"track": {"id": "T9"}}

        def translate(params, ctx):
            calls.append(("translate", params))
            return {"ok": True}

        methods = {"subtitles.generate": gen, "subtitles.translate": translate}
        svc = recipes.Recipes(recipes.RecipeStore(tmp_path / "r.json"), methods_provider=lambda: methods)
        svc.save(
            {
                "recipe": {
                    "id": "1",
                    "name": "G->T",
                    "steps": [
                        {"method": "subtitles.generate", "params": {"videoId": "v1"}},
                        {"method": "subtitles.translate", "params": {"trackId": "$0.track.id", "targetLang": "es"}},
                    ],
                }
            },
            _ctx(),
        )
        out = svc.run({"id": "1"}, _ctx(reg))
        reg.get(out["jobId"]).wait(5)
        # generate ran, then translate consumed generate's track id.
        assert calls[0][0] == "gen"
        assert calls[1] == ("translate", {"trackId": "T9", "targetLang": "es"})
        job = reg.get(out["jobId"])
        assert job.result["results"][0] == {"track": {"id": "T9"}}
        assert job.result["results"][1] == {"ok": True}

    def test_unknown_method_step_errors_the_job(self, tmp_path):
        reg, events = self._registry()
        svc = recipes.Recipes(recipes.RecipeStore(tmp_path / "r.json"), methods_provider=lambda: {})
        svc.save({"recipe": {"id": "1", "name": "X", "steps": [{"method": "no.such"}]}}, _ctx())
        out = svc.run({"id": "1"}, _ctx(reg))
        reg.get(out["jobId"]).wait(5)
        assert reg.get(out["jobId"]).status.value == "error"
        # the failure surfaced via job.done error payload
        assert any(e[0] == "done" and isinstance(e[2], dict) and "error" in e[2] for e in events)

    def test_subjob_step_is_awaited_and_unwrapped(self, tmp_path):
        reg, _ = self._registry()

        # transcribe.start: a real handler that starts a SUB-job on the registry
        # and returns {jobId}. The recipe runner must wait for it + unwrap.
        def transcribe_start(params, ctx):
            def body(job_ctx):
                job_ctx.progress(50.0, "half")
                return {"transcript": {"language": "en", "segments": []}}

            sub = ctx.jobs.start(body)
            return {"jobId": sub.id}

        methods = {"transcribe.start": transcribe_start}
        svc = recipes.Recipes(recipes.RecipeStore(tmp_path / "r.json"), methods_provider=lambda: methods)
        svc.save(
            {"recipe": {"id": "1", "name": "T", "steps": [{"method": "transcribe.start", "params": {"videoId": "v"}}]}},
            _ctx(),
        )
        out = svc.run({"id": "1"}, _ctx(reg))
        reg.get(out["jobId"]).wait(10)
        job = reg.get(out["jobId"])
        assert job.status.value == "done"
        # the inner {transcript} was unwrapped as the step result.
        assert job.result["results"][0] == {"transcript": {"language": "en", "segments": []}}

    def test_subjob_error_fails_the_recipe(self, tmp_path):
        reg, _ = self._registry()

        def failing(params, ctx):
            def body(job_ctx):
                raise RuntimeError("boom inside step")

            sub = ctx.jobs.start(body)
            return {"jobId": sub.id}

        methods = {"step.fail": failing}
        svc = recipes.Recipes(recipes.RecipeStore(tmp_path / "r.json"), methods_provider=lambda: methods)
        svc.save({"recipe": {"id": "1", "name": "F", "steps": [{"method": "step.fail"}]}}, _ctx())
        out = svc.run({"id": "1"}, _ctx(reg))
        reg.get(out["jobId"]).wait(10)
        job = reg.get(out["jobId"])
        assert job.status.value == "error"
        assert "boom inside step" in (job.error or "")

    def test_progress_is_step_scoped(self, tmp_path):
        reg, events = self._registry()

        def quick(params, ctx):
            return {"ok": 1}

        methods = {"a": quick, "b": quick}
        svc = recipes.Recipes(recipes.RecipeStore(tmp_path / "r.json"), methods_provider=lambda: methods)
        svc.save(
            {"recipe": {"id": "1", "name": "P", "steps": [{"method": "a", "label": "First"}, {"method": "b"}]}},
            _ctx(),
        )
        out = svc.run({"id": "1"}, _ctx(reg))
        reg.get(out["jobId"]).wait(5)
        msgs = [e[3] for e in events if e[0] == "progress"]
        assert any("step 1/2 · First" in m for m in msgs)
        assert any("step 2/2 · b" in m for m in msgs)


# --------------------------------------------------------------------------- #
# resolve_refs: the list-index miss paths in _dotted_get
# --------------------------------------------------------------------------- #
class TestDottedGetListPaths:
    def test_non_int_list_index_is_none(self):
        # "$0.items.x" -> list indexed by a non-int part -> ValueError -> None.
        prior = [{"items": [1, 2, 3]}]
        assert recipes.resolve_refs({"v": "$0.items.x"}, prior)["v"] is None

    def test_out_of_range_list_index_is_none(self):
        # "$0.items.9" -> IndexError -> None.
        prior = [{"items": [1, 2]}]
        assert recipes.resolve_refs({"v": "$0.items.9"}, prior)["v"] is None

    def test_path_through_scalar_is_none(self):
        # Descending into a scalar (neither dict nor list) yields None.
        prior = [{"n": 5}]
        assert recipes.resolve_refs({"v": "$0.n.deeper"}, prior)["v"] is None


# --------------------------------------------------------------------------- #
# RecipeStore.save: the "keep an existing different-id recipe" branch
# --------------------------------------------------------------------------- #
def test_save_keeps_other_recipes_when_upserting(tmp_path):
    store = recipes.RecipeStore(tmp_path / "r.json")
    store.save({"id": "a", "name": "A", "steps": []})
    store.save({"id": "b", "name": "B", "steps": []})  # different id -> appended
    store.save({"id": "a", "name": "A2", "steps": []})  # upsert a; b untouched
    by_id = {r["id"]: r["name"] for r in store.list()}
    assert by_id == {"a": "A2", "b": "B"}


# --------------------------------------------------------------------------- #
# _await_subjob: the defensive / cancel / timeout branches (tested directly)
# --------------------------------------------------------------------------- #
class _FakeJobCtx:
    """A minimal job_ctx for _await_subjob: tracks cancel + raise semantics."""

    def __init__(self, cancelled: bool = False) -> None:
        self.cancelled = cancelled

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise JobCancelled()

    def progress(self, *_a, **_k) -> None:  # pragma: no cover - unused here
        pass


class _FakeSub:
    """A fake Job for the await loop: drives finished/pct/status/result."""

    def __init__(self, *, status="done", pct=0, result=None, error=None, finish_after=0) -> None:
        self._status = status
        self.pct = pct
        self.result = result
        self.error = error
        self._calls = 0
        self._finish_after = finish_after

    class _Status:
        def __init__(self, value: str) -> None:
            self.value = value

    @property
    def status(self):
        return self._Status(self._status)

    @property
    def finished(self) -> bool:
        # Finishes once wait() has been polled enough times.
        return self._calls >= self._finish_after

    def wait(self, _timeout=None) -> bool:
        self._calls += 1
        return self.finished


class _FakeRegistry:
    def __init__(self, sub) -> None:
        self._sub = sub
        self.cancelled: list[str] = []

    def get(self, _sub_id):
        return self._sub

    def cancel(self, sub_id) -> None:
        self.cancelled.append(sub_id)


def _svc(tmp_path):
    return recipes.Recipes(recipes.RecipeStore(tmp_path / "r.json"))


def test_await_subjob_vanished_raises(tmp_path):
    svc = _svc(tmp_path)
    reg = _FakeRegistry(sub=None)
    ctx = RpcContext(emit_notification=lambda *_: None, jobs=reg)
    with pytest.raises(RpcError, match="sub-job vanished"):
        svc._await_subjob("gone", _FakeJobCtx(), ctx, lambda *_: None)


def test_await_subjob_cancel_cancels_sub_and_raises(tmp_path):
    svc = _svc(tmp_path)
    sub = _FakeSub(status="cancelled", finish_after=99)  # never finishes on its own
    reg = _FakeRegistry(sub)
    ctx = RpcContext(emit_notification=lambda *_: None, jobs=reg)
    with pytest.raises(JobCancelled):
        svc._await_subjob("s1", _FakeJobCtx(cancelled=True), ctx, lambda *_: None)
    assert reg.cancelled == ["s1"]  # the running sub-job was cancelled too


def test_await_subjob_relays_progress_and_returns_result(tmp_path):
    svc = _svc(tmp_path)
    sub = _FakeSub(status="done", pct=42, result={"ok": 1}, finish_after=1)
    reg = _FakeRegistry(sub)
    ctx = RpcContext(emit_notification=lambda *_: None, jobs=reg)
    relayed: list[float] = []
    out = svc._await_subjob("s1", _FakeJobCtx(), ctx, lambda pct, _m: relayed.append(pct))
    assert out == {"ok": 1}
    assert 42.0 in relayed  # the sub's pct was relayed (348-350)


def test_await_subjob_skips_relay_when_pct_unchanged(tmp_path):
    # pct starts at -1 internally; a sub at pct 0 across two polls relays once then
    # takes the `pct == last_pct` no-relay edge (the 348->351 branch).
    svc = _svc(tmp_path)
    sub = _FakeSub(status="done", pct=0, result={"ok": 2}, finish_after=2)
    reg = _FakeRegistry(sub)
    ctx = RpcContext(emit_notification=lambda *_: None, jobs=reg)
    relayed: list[float] = []
    out = svc._await_subjob("s1", _FakeJobCtx(), ctx, lambda pct, _m: relayed.append(pct))
    assert out == {"ok": 2}
    assert relayed == [0.0]  # relayed once (pct changed -1->0), then skipped


def test_await_subjob_timeout_raises(tmp_path, monkeypatch):
    svc = _svc(tmp_path)
    sub = _FakeSub(status="done", finish_after=99)  # would never finish in time
    reg = _FakeRegistry(sub)
    ctx = RpcContext(emit_notification=lambda *_: None, jobs=reg)
    # Force an already-expired deadline so the timeout branch (351-352) fires.
    monkeypatch.setattr(recipes, "SUBJOB_TIMEOUT", -1.0)
    with pytest.raises(RpcError, match="timed out"):
        svc._await_subjob("s1", _FakeJobCtx(), ctx, lambda *_: None)


def test_await_subjob_cancelled_status_raises_if_parent_cancelled(tmp_path):
    # A sub-job that FINISHED as cancelled, with the parent now cancelled too:
    # exercises the `status == "cancelled"` -> raise_if_cancelled branch (358).
    svc = _svc(tmp_path)
    sub = _FakeSub(status="cancelled", finish_after=0)  # already finished
    reg = _FakeRegistry(sub)
    ctx = RpcContext(emit_notification=lambda *_: None, jobs=reg)
    with pytest.raises(JobCancelled):
        svc._await_subjob("s1", _FakeJobCtx(cancelled=True), ctx, lambda *_: None)


def test_await_subjob_cancelled_status_returns_when_parent_not_cancelled(tmp_path):
    # Same finished-cancelled sub, but the parent is NOT cancelled: the branch is
    # entered, raise_if_cancelled is a no-op, and the (None) result is returned.
    svc = _svc(tmp_path)
    sub = _FakeSub(status="cancelled", finish_after=0, result=None)
    reg = _FakeRegistry(sub)
    ctx = RpcContext(emit_notification=lambda *_: None, jobs=reg)
    assert svc._await_subjob("s1", _FakeJobCtx(cancelled=False), ctx, lambda *_: None) is None


# --------------------------------------------------------------------------- #
# register
# --------------------------------------------------------------------------- #
def test_register_installs_four_methods(tmp_path):
    registered: dict[str, Any] = {}
    recipes.register(path=tmp_path / "r.json", register_fn=lambda n, f: registered.__setitem__(n, f))
    assert set(registered) == {"recipes.list", "recipes.save", "recipes.delete", "recipes.run"}
