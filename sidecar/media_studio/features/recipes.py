"""Saved PIPELINE RECIPES (this group's feature 3).

A *recipe* is a lightweight, locally-saved, reusable multi-step pipeline — e.g.
``transcribe -> translate -> make N shorts -> package`` — that the user runs in
ONE shot, with per-step progress, generalizing the existing batch/job system.

Design (the recipe runner is a thin ORCHESTRATOR over the already-wired §2
methods — it adds NO new media logic):

  * **Storage** — recipes live in a single JSON document under the data root
    (``recipes.json``), exactly like :mod:`settings_store` (atomic temp+rename).
    A recipe is ``{id, name, steps:[Step]}``; a Step is
    ``{method, params, label?}`` naming an existing RPC method + its params.
  * ``recipes.list``   -> ``{recipes:[Recipe]}``        (direct-return)
  * ``recipes.save``   -> ``{recipe}``                  (direct-return; upsert)
  * ``recipes.delete`` -> ``{ok}``                      (direct-return)
  * ``recipes.run``    -> ``{jobId}``  (a LONG job: streams ``job.progress`` with
    a "step k/N · <label>" message; ``job.done.result`` = ``{results:[...]}`` —
    one entry per step). Per-step progress is the running step's own job
    progress scaled into its slice of ``[0,100]``.

How a step runs (the generalization of batch): each step's ``method`` is looked
up on the SAME ``protocol.METHODS`` registry the dispatcher uses, then invoked
with the step's params. Two shapes are handled, mirroring the existing handlers:

  * **direct-return** methods (transcribe is the only long one most recipes
    chain, but e.g. ``subtitles.generate`` / ``shortmaker.export`` vary): a
    method whose result carries a ``jobId`` is a sub-job; the runner WAITS for
    that sub-job to finish (relaying its progress) and unwraps the inner
    ``job.done.result`` as the step result. A direct result is used as-is.
  * a step may reference a prior step's output with ``"$N.key"`` param values
    (e.g. ``{"trackId": "$0.track.id"}``) — resolved against the collected step
    results before the call, so ``translate`` can consume ``generate``'s track.

Pure-logic + filesystem only at module level: no heavy-ML / network imports. The
sub-job wait uses the registry the context already owns; offline refusals from
the underlying handlers propagate verbatim into the step's error.
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .. import protocol
from ..protocol import ErrorCode, RpcContext, RpcError
from ..util import clamp, get_logger

log = get_logger("media_studio.features.recipes")

Recipe = dict[str, Any]
Step = dict[str, Any]

#: a ``$N.key.path`` reference to step N's result (dotted path into the dict).
_REF_RE = re.compile(r"^\$(\d+)\.(.+)$")
#: how long the runner waits on a single sub-job before giving up (seconds).
SUBJOB_TIMEOUT = 3600.0


def _invalid(message: str) -> RpcError:
    return RpcError(message, ErrorCode.INVALID_PARAMS)


def _require_str(params: dict[str, Any], key: str) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value:
        raise _invalid(f"{key} (str) is required")
    return value


# --------------------------------------------------------------------------- #
# pure: recipe shaping + step reference resolution
# --------------------------------------------------------------------------- #
def normalize_recipe(raw: dict[str, Any]) -> Recipe:
    """Validate + normalize a recipe payload into the frozen wire shape.

    ``{id?, name, steps:[{method, params?, label?}]}``. A missing ``id`` is
    generated. Raises INVALID_PARAMS on a malformed recipe so a bad save can
    never persist a half-typed record.
    """
    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        raise _invalid("recipe.name (non-empty str) is required")
    raw_steps = raw.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise _invalid("recipe.steps (non-empty array) is required")
    steps: list[Step] = []
    for index, raw_step in enumerate(raw_steps):
        if not isinstance(raw_step, dict):
            raise _invalid(f"recipe.steps[{index}] must be an object")
        method = raw_step.get("method")
        if not isinstance(method, str) or not method:
            raise _invalid(f"recipe.steps[{index}].method (str) is required")
        params = raw_step.get("params")
        if params is not None and not isinstance(params, dict):
            raise _invalid(f"recipe.steps[{index}].params must be an object")
        label = raw_step.get("label")
        steps.append(
            {
                "method": method,
                "params": dict(params or {}),
                "label": str(label) if isinstance(label, str) and label else method,
            }
        )
    recipe_id = raw.get("id")
    if not isinstance(recipe_id, str) or not recipe_id:
        recipe_id = uuid.uuid4().hex[:12]
    return {"id": recipe_id, "name": name.strip(), "steps": steps}


def _dotted_get(obj: Any, path: str) -> Any:
    """Read a dotted ``a.b.0.c`` path out of nested dicts/lists (None on miss)."""
    cur = obj
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return None
        else:
            return None
    return cur


def resolve_refs(params: dict[str, Any], results: list[Any]) -> dict[str, Any]:
    """Resolve ``"$N.key"`` references in a step's params against prior results.

    A string value matching ``$<stepIndex>.<dotted.path>`` is replaced with the
    value at that path in ``results[stepIndex]``. Non-matching strings and other
    types pass through unchanged. Out-of-range / missing references resolve to
    ``None`` (the step then validates its own params and errors clearly).
    """
    resolved: dict[str, Any] = {}
    for key, value in params.items():
        if isinstance(value, str):
            match = _REF_RE.match(value)
            if match:
                idx = int(match.group(1))
                if 0 <= idx < len(results):
                    resolved[key] = _dotted_get(results[idx], match.group(2))
                else:
                    resolved[key] = None
                continue
        resolved[key] = value
    return resolved


# --------------------------------------------------------------------------- #
# storage (JSON document under the data root; mirrors settings_store)
# --------------------------------------------------------------------------- #
class RecipeStore:
    """A JSON-backed list of recipes (atomic temp+rename writes)."""

    def __init__(self, path: str | os.PathLike) -> None:
        self.path = Path(path)

    def _read(self) -> list[Recipe]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            log.warning("recipes file unreadable (%s); treating as empty", exc)
            return []
        if not isinstance(data, list):
            return []
        return [r for r in data if isinstance(r, dict)]

    def _write(self, recipes: list[Recipe]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(recipes, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)

    def list(self) -> list[Recipe]:
        return self._read()

    def save(self, recipe: Recipe) -> Recipe:
        """Upsert ``recipe`` by id (replace same-id, else append). Returns it."""
        recipes = self._read()
        replaced = False
        out: list[Recipe] = []
        for existing in recipes:
            if existing.get("id") == recipe["id"]:
                out.append(recipe)
                replaced = True
            else:
                out.append(existing)
        if not replaced:
            out.append(recipe)
        self._write(out)
        return recipe

    def delete(self, recipe_id: str) -> bool:
        recipes = self._read()
        remaining = [r for r in recipes if r.get("id") != recipe_id]
        if len(remaining) == len(recipes):
            return False
        self._write(remaining)
        return True

    def get(self, recipe_id: str) -> Recipe | None:
        for recipe in self._read():
            if recipe.get("id") == recipe_id:
                return recipe
        return None


# --------------------------------------------------------------------------- #
# the runner service
# --------------------------------------------------------------------------- #
class Recipes:
    """Owns the ``recipes.*`` methods over a :class:`RecipeStore`.

    ``methods_provider`` returns the live method registry (defaults to
    ``protocol.METHODS``) so a step can invoke any wired §2 handler; injectable
    so tests run recipes over a fake registry with no real media work.
    """

    def __init__(
        self,
        store: RecipeStore,
        *,
        methods_provider: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        self.store = store
        self._methods_provider = methods_provider or (lambda: protocol.METHODS)

    # -- direct-return CRUD -------------------------------------------------
    def list(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``recipes.list()`` -> ``{recipes:[Recipe]}`` (direct-return)."""
        return {"recipes": self.store.list()}

    def save(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``recipes.save({recipe})`` -> ``{recipe}`` (direct-return; upsert)."""
        raw = params.get("recipe")
        if not isinstance(raw, dict):
            raise _invalid("recipe (object) is required")
        recipe = normalize_recipe(raw)
        return {"recipe": self.store.save(recipe)}

    def delete(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``recipes.delete({id})`` -> ``{ok}`` (direct-return)."""
        recipe_id = _require_str(params, "id")
        return {"ok": self.store.delete(recipe_id)}

    # -- recipes.run (the long job) ----------------------------------------
    def run(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``recipes.run({id})`` -> ``{jobId}`` (long job).

        Runs each step sequentially as ONE job. ``job.progress`` carries
        "step k/N · <label>" with the running step's own progress scaled into
        its even slice of ``[0,100]``. ``job.done.result`` is ``{results:[...]}``
        (one per step). A step that names a job-returning method is awaited as a
        sub-job (its progress relayed, its inner result unwrapped).
        """
        recipe_id = _require_str(params, "id")
        recipe = self.store.get(recipe_id)
        if recipe is None:
            raise _invalid(f"unknown recipe: {recipe_id}")
        if ctx.jobs is None:
            raise RpcError("no job registry available", ErrorCode.INTERNAL_ERROR)
        steps: list[Step] = list(recipe.get("steps") or [])

        def job_body(job_ctx: Any) -> dict[str, Any]:
            return self._run_steps(steps, job_ctx, ctx)

        job = ctx.jobs.start(job_body, feature="recipes", label=f"recipe: {recipe.get('name', '')}")
        return {"jobId": job.id}

    def _run_steps(self, steps: list[Step], job_ctx: Any, ctx: RpcContext) -> dict[str, Any]:
        """Execute the steps in order, relaying scaled per-step progress."""
        total = max(len(steps), 1)
        methods = self._methods_provider()
        results: list[Any] = []
        for index, step in enumerate(steps):
            job_ctx.raise_if_cancelled()
            label = step.get("label") or step.get("method", "")
            base = index / total * 100.0
            span = 100.0 / total

            def on_sub(
                pct: float, _msg: str = "", _b: float = base, _s: float = span, _i: int = index, _l: str = label
            ) -> None:
                job_ctx.progress(_b + clamp(pct, 0.0, 100.0) / 100.0 * _s, f"step {_i + 1}/{total} · {_l}")

            on_sub(0.0)
            result = self._run_one_step(step, methods, results, job_ctx, ctx, on_sub)
            results.append(result)
            on_sub(100.0)
        job_ctx.progress(100.0, "done")
        return {"results": results}

    def _run_one_step(
        self,
        step: Step,
        methods: dict[str, Any],
        prior: list[Any],
        job_ctx: Any,
        ctx: RpcContext,
        on_sub: Callable[[float, str], None],
    ) -> Any:
        """Invoke one step's method, awaiting it as a sub-job when needed."""
        method_name = str(step.get("method"))
        handler = methods.get(method_name)
        if handler is None:
            raise _invalid(f"recipe step names an unknown method: {method_name}")
        params = resolve_refs(dict(step.get("params") or {}), prior)
        result = handler(params, ctx)
        # A job-returning step: wait for the sub-job, relay its progress, unwrap.
        if isinstance(result, dict) and isinstance(result.get("jobId"), str):
            return self._await_subjob(result["jobId"], job_ctx, ctx, on_sub)
        return result

    def _await_subjob(
        self,
        sub_job_id: str,
        job_ctx: Any,
        ctx: RpcContext,
        on_sub: Callable[[float, str], None],
    ) -> Any:
        """Block until ``sub_job_id`` finishes; relay its progress to ``on_sub``.

        Cancelling the parent recipe job cancels the running sub-job too. The
        sub-job's terminal result is read off the registry's Job object (the
        runner does not depend on the notification bus for this). An errored
        sub-job's error is re-raised so the recipe job fails with the same cause
        (offline refusals propagate verbatim here).
        """
        registry = ctx.jobs
        sub = registry.get(sub_job_id)
        if sub is None:
            raise RpcError(f"recipe sub-job vanished: {sub_job_id}", ErrorCode.INTERNAL_ERROR)
        deadline = time.monotonic() + SUBJOB_TIMEOUT
        last_pct = -1
        while not sub.finished:
            if job_ctx.cancelled:
                registry.cancel(sub_job_id)
                job_ctx.raise_if_cancelled()
            if sub.pct != last_pct:
                last_pct = sub.pct
                on_sub(float(sub.pct), "")
            if time.monotonic() > deadline:
                raise RpcError(f"recipe sub-job timed out: {sub_job_id}", ErrorCode.INTERNAL_ERROR)
            sub.wait(0.05)
        status = getattr(sub.status, "value", str(sub.status))
        if status == "error":
            raise RpcError(f"recipe step failed: {sub.error or 'unknown error'}", ErrorCode.INTERNAL_ERROR)
        if status == "cancelled":
            job_ctx.raise_if_cancelled()
        return sub.result


# --------------------------------------------------------------------------- #
# registration (mirrors shorts.register)
# --------------------------------------------------------------------------- #
def register(
    *,
    path: str | os.PathLike,
    methods_provider: Callable[[], dict[str, Any]] | None = None,
    register_fn: Callable[[str, Any], None] | None = None,
) -> Recipes:
    """Create a :class:`Recipes` over ``path`` and register the four methods.

    ``register_fn`` defaults to :func:`protocol.register`; tests inject a fake
    registrar + a tmp ``path``. Returns the service so the caller can hold it.
    """
    service = Recipes(RecipeStore(path), methods_provider=methods_provider)
    reg = register_fn if register_fn is not None else protocol.register
    reg("recipes.list", service.list)
    reg("recipes.save", service.save)
    reg("recipes.delete", service.delete)
    reg("recipes.run", service.run)
    return service


__all__ = [
    "SUBJOB_TIMEOUT",
    "Recipe",
    "RecipeStore",
    "Recipes",
    "Step",
    "normalize_recipe",
    "register",
    "resolve_refs",
]
