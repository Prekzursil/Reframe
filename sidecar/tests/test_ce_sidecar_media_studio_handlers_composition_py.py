"""Cross-edit (feature-completion reconcile) tests for ``handlers/composition.py``.

Covers the two wired-in changes without touching any consolidated test file:

  * ``index.plan`` is registered by :func:`register_all` (the PURE pre-flight
    consent surface mirroring ``ai.planJob``, bound to ``Services.index_plan``);
  * IDX 60 Part 2 — :func:`_key_overlay_wrapper` stashes the popped injected-key
    snapshot on the per-request :class:`RpcContext` (``ctx.injected_keys``) on the
    key-bearing path so a deferred job-worker step runner can re-attach it, and
    leaves ``ctx`` untouched on the ordinary (no-key) path. Both branches of the
    new behaviour are exercised, plus the full re-attach round-trip contract the
    ``RecipeRunner`` step runner relies on.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from media_studio.handlers import Services, register_all
from media_studio.handlers.composition import _key_overlay_wrapper
from media_studio.protocol import RpcContext
from media_studio.settings_store import INJECTED_KEYS_FIELD

# A stand-in for the DPAPI-decrypted raw-key bundle main injects (not a real key).
_TOKEN = "raw-token-ce-placeholder"
_SNAP = {"providers": {"groq": [_TOKEN]}}


def _ctx() -> RpcContext:
    return RpcContext(emit_notification=lambda _obj: None, jobs=None)


# --------------------------------------------------------------------------- #
# index.plan registration (renderer-features-2 cross-edit)
# --------------------------------------------------------------------------- #
def test_index_plan_is_registered(tmp_path: Path) -> None:
    """``register_all`` wires ``index.plan`` alongside build/search/status."""
    captured: dict[str, Any] = {}

    def fake_register(name: str, handler: Any) -> None:
        captured[name] = handler

    register_all(Services(data_dir=tmp_path), register=fake_register)

    assert "index.plan" in captured
    assert callable(captured["index.plan"])
    # Registered beside its siblings (proves the block, not a stray duplicate).
    for sibling in ("index.build", "index.search", "index.status"):
        assert sibling in captured


# --------------------------------------------------------------------------- #
# IDX 60 Part 2: ctx stash on the injected path, untouched on the ordinary path
# --------------------------------------------------------------------------- #
def test_wrapper_stashes_injected_snapshot_on_ctx(tmp_path: Path) -> None:
    svc = Services(data_dir=tmp_path)
    seen_inside: list[Any] = []

    def handler(params: dict[str, Any], ctx: RpcContext) -> str:
        # The wrapper popped the marker before us AND stashed it on ctx.
        seen_inside.append((INJECTED_KEYS_FIELD in params, getattr(ctx, "injected_keys", None)))
        return "ok"

    wrapped = _key_overlay_wrapper(svc, handler)
    ctx = _ctx()
    out = wrapped({"id": "x", INJECTED_KEYS_FIELD: _SNAP}, ctx)

    assert out == "ok"
    assert ctx.injected_keys == _SNAP
    assert seen_inside == [(False, _SNAP)]
    # RpcContext is a plain dataclass: its repr shows only declared fields, so the
    # stashed snapshot never leaks through a repr()/str() of the context.
    assert _TOKEN not in repr(ctx)


def test_wrapper_leaves_ctx_untouched_without_injected_keys(tmp_path: Path) -> None:
    svc = Services(data_dir=tmp_path)

    def handler(params: dict[str, Any], ctx: RpcContext) -> str:
        return "ok"

    wrapped = _key_overlay_wrapper(svc, handler)
    ctx = _ctx()
    assert wrapped({"id": "x"}, ctx) == "ok"
    # The ordinary (no-key) path never opens the overlay and never stashes.
    assert getattr(ctx, "injected_keys", None) is None


def test_stashed_injected_reattaches_through_the_wrapper(tmp_path: Path) -> None:
    """Simulate the RecipeRunner step re-attach contract end-to-end.

    Outer job-runner call stashes the snapshot on ``ctx``; the deferred step
    runner re-attaches it under :data:`INJECTED_KEYS_FIELD` onto the nested step's
    params, which flow through THIS wrapper again — so the marker is re-popped in
    place (no downstream leak) for each nested step.
    """
    svc = Services(data_dir=tmp_path)
    marker_visible: list[bool] = []

    def handler(params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        marker_visible.append(INJECTED_KEYS_FIELD in params)
        return {"jobId": "j1"}

    wrapped = _key_overlay_wrapper(svc, handler)
    ctx = _ctx()

    # Outer job-runner handler: enqueues the job, returns {jobId}, stash survives.
    wrapped({INJECTED_KEYS_FIELD: _SNAP}, ctx)
    assert ctx.injected_keys == _SNAP

    # Deferred worker: the step runner re-attaches the stashed snapshot per step.
    step_params: dict[str, Any] = {"trackId": "t0", INJECTED_KEYS_FIELD: ctx.injected_keys}
    wrapped(step_params, ctx)

    # Re-popped in place for the nested step; the handler never saw the marker.
    assert INJECTED_KEYS_FIELD not in step_params
    assert marker_visible == [False, False]
