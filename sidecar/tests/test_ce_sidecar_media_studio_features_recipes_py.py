"""Cross-edit tests for media_studio.features.recipes — IDX 60 Part 2.

Covers the per-step re-attach of the injected DPAPI key snapshot (WU-D2b-2):
``recipes.run`` captures the snapshot the composition root stashed on ``ctx``
under ``INJECTED_KEYS_FIELD`` and threads it into each step's params so a nested
cloud step's ``key_overlay`` re-opens on the job worker thread. Isolated file
(unique name) so it never collides with the 1:1 ``test_recipes.py`` under the
parallel cross-edit apply; coverage is by source file, so the new True branch of
``_run_one_step`` counts toward the 100% branch gate here (the False branch is
already exercised by every keyless run test in ``test_recipes.py``).
"""

from __future__ import annotations

from media_studio.features import recipes
from media_studio.jobs import JobRegistry
from media_studio.protocol import RpcContext


def _ctx(registry=None) -> RpcContext:
    return RpcContext(emit_notification=lambda *_: None, jobs=registry)


def _registry() -> JobRegistry:
    return JobRegistry(emit_progress=lambda *_: None, emit_done=lambda *_: None)


def _svc_with_capture(tmp_path):
    """A Recipes over a fake registry whose single step records its params."""
    captured: list[dict] = []

    def step_handler(params, _ctx):
        captured.append(dict(params))
        return {"ok": True}

    svc = recipes.Recipes(
        recipes.RecipeStore(tmp_path / "r.json"),
        methods_provider=lambda: {"m.one": step_handler},
    )
    svc.save(
        {"recipe": {"id": "1", "name": "K", "steps": [{"method": "m.one", "params": {"videoId": "v"}}]}},
        _ctx(),
    )
    return svc, captured


def test_run_reattaches_injected_keys_to_each_step(tmp_path):
    """injected is not None -> the snapshot rides each step's params (True branch)."""
    svc, captured = _svc_with_capture(tmp_path)
    reg = _registry()
    ctx = _ctx(reg)
    snapshot = {"providers": {"Groq": ["sk-live"]}, "cloudApiKey": "sk-live"}
    # The composition-root key_overlay wrapper stashes the popped snapshot here.
    setattr(ctx, recipes.INJECTED_KEYS_FIELD, snapshot)

    out = svc.run({"id": "1"}, ctx)
    job = reg.get(out["jobId"])
    job.wait(5)

    assert job.status.value == "done"
    assert captured[0][recipes.INJECTED_KEYS_FIELD] == snapshot
    # The step's own params are preserved alongside the re-attached snapshot.
    assert captured[0]["videoId"] == "v"


def test_run_without_snapshot_leaves_step_params_clean(tmp_path):
    """injected is None -> no key is attached (False branch; keyless request)."""
    svc, captured = _svc_with_capture(tmp_path)
    reg = _registry()

    out = svc.run({"id": "1"}, _ctx(reg))  # ctx carries no injected snapshot
    reg.get(out["jobId"]).wait(5)

    assert recipes.INJECTED_KEYS_FIELD not in captured[0]
    assert captured[0]["videoId"] == "v"
