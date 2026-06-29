# The only inter-module cycle is the TYPE_CHECKING-only Services ref below
# (no runtime cycle); silence the type-only back-edge warning.
# pyright: reportImportCycles=false
"""Composition-root handlers (F4b split): Director plan/apply/undo/evaluate handlers.

Each function is a Services method body extracted verbatim from the former
monolithic handlers.py; `self` is typed against the composed `Services` (bound
in services.py). Behaviour + the RPC surface are byte-identical to pre-split.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from ..features import director as _director
from ..features import offline as _offline
from ..protocol import ErrorCode, RpcContext, RpcError
from ._shared import (
    _DirectorPlanEntry,
    _invalid,
    _require_str,
    log,
)
from ._wire import (
    _coerce_tier,
    _self_ffprobe,
)

if TYPE_CHECKING:  # pragma: no cover - typing-only import, never executed at runtime
    from ._services import Services


def _director_video_duration_ms(self: Services, video_id: str) -> int:
    """Probe the source video's duration in ms (validator clip bound)."""
    path = self._resolve_video_path(video_id)
    if not path:
        raise _invalid(f"unknown video: {video_id}")
    probe = self._ffprobe_duration or _self_ffprobe()
    return int(round(probe(path) * 1000))


def _director_get_plan(self: Services, plan_id: str) -> _DirectorPlanEntry:
    """Resolve a stored plan entry by id (raises INVALID_PARAMS if absent)."""
    entry = self._director_plans.get(plan_id)
    if entry is None:
        raise _invalid(f"unknown plan: {plan_id}")
    return entry


def _editplan_provider_or_refuse(self: Services) -> Any:
    """Resolve the ``editPlan`` chat provider, gated by per-provider TEXT consent.

    CRITICAL PRIVACY INVARIANT (PLAN §WU-A1/G-A5 — the chat analog of the
    index-embedder :meth:`_resolve_index_embedder` and the vision
    :meth:`_resolve_frame_scorer` consent gates): ``build_understanding`` folds
    the transcript into the planner prompt, so the ``director.plan`` chat egress
    carries transcript TEXT. The egress provider is therefore BUILT FROM the
    per-entry TEXT-consent-filtered settings — exactly like the embedder builds
    its :class:`CloudEmbedder` from :meth:`_resolve_index_embedder`'s filtered
    pool — so EVERY slot the routed pool may rotate to (primary AND every 429
    failover) is one whose TEXT consent is granted. Filtering the actual pool
    (not just an all-or-nothing precheck) is what closes the mixed-consent
    rotation hole: a non-consented cloud entry is DROPPED before the pool is
    built, so it can never become the ``prefer`` primary nor a failover target.

    Resolution (mirrors :meth:`_resolve_index_embedder`):

    1. An injected ``_provider`` seam wins outright (tests / a wholesale
       override) — same as the embedder's injected-``_embedder`` short-circuit.
    2. Else build the routed ``editPlan`` pool over the TEXT-CONSENT-FILTERED
       RAW settings (``get_raw()`` keeps the RAW key on the wire for the
       consented entries; the filter drops every non-consented cloud entry).
       When the RAW (unfiltered) routed pool HAD a cloud egress target but the
       filtered pool has NONE, every configured cloud target is non-consented:
       REFUSE before any chat (a clear refusal, the chat analog of the
       embedder's local fallback — chat has no in-process local backstop to
       complete with). Zero bytes leave the machine.
    3. Else -> the consent-filtered routed pool: a consented cloud entry
       egresses (RAW key), and a genuinely local/no-cloud config routes local
       untouched.
    """
    if self._provider is not None:
        return self._provider

    from ..models import provider as _provider_mod  # local: heavy seam

    prefer = self._function_prefer("editPlan")
    raw = self.settings.get_raw()
    consented_provider = _provider_mod.get_provider(self._text_consented_settings(raw), prefer=prefer)

    builder = getattr(_provider_mod, "build_pool_provider", None)
    if builder is not None:  # pragma: no branch -- always present off the stub
        raw_cloud = any(not e.local for e in builder(raw, detect_local=False, prefer=prefer).entries)
        # OFFLINE GATE: offline forbids ALL cloud text egress, even for a fully
        # TEXT-consented + routed provider. Chat has no in-process local
        # backstop to complete with, so REFUSE before any chat when a cloud
        # egress target is configured (offline is authoritative over consent).
        # A genuinely local/no-cloud route (raw_cloud False) proceeds untouched.
        if raw_cloud and _offline.is_offline(self.settings.get()):
            raise _offline.OfflineError(
                "Offline mode is on — director.plan would egress transcript text to a "
                "cloud provider, which has no local backstop. Turn off Offline mode in "
                "System Health, or route editPlan to a local provider."
            )
        consented_cloud = any(
            not e.local for e in builder(self._text_consented_settings(raw), detect_local=False, prefer=prefer).entries
        )
        if raw_cloud and not consented_cloud:
            raise _invalid(
                "director.plan would egress transcript text but TEXT consent is "
                "revoked for every configured cloud provider; grant per-provider "
                "text consent (consent.perProvider[<provider>].text) or route local"
            )
    return consented_provider


def director_plan(self: Services, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
    """``director.plan({videoId, goal})`` -> ``{jobId}``. Job-based.

    Understand -> editPlan LLM (via :meth:`_run_ai_job`, exactly the
    ``phase8_select`` pattern) -> ``validate_and_reject`` -> store the typed
    EditPlan under a fresh ``planId``. The ``job.done`` payload is
    ``{planId, editPlan, preview}``. The media-derived understanding is fenced
    as UNTRUSTED DATA by ``build_edit_plan_messages`` (injection mitigation #1);
    the planner provider is the ``editPlan``-routed pool, resolved through the
    per-provider TEXT-consent gate (:meth:`_editplan_provider_or_refuse`) so the
    transcript-bearing prompt is NEVER egressed to a non-consented cloud target
    (no new AI path).
    """
    if ctx.jobs is None:
        raise RpcError("no job registry available", ErrorCode.INTERNAL_ERROR)
    video_id = _require_str(params, "videoId")
    goal = _require_str(params, "goal")
    duration_ms = self._director_video_duration_ms(video_id)
    path = cast("str", self._resolve_video_path(video_id))
    project = self._load_or_create_project(video_id)
    understanding, media = _director.build_understanding(project.data, duration_ms=duration_ms)
    plan_id = _director.new_plan_id()
    source = _director.source_hash(path, duration_ms)

    from ..features import edit_plan_prompt as _prompt  # local: import-light pure
    from ..features import edit_validate as _validate  # local: import-light pure

    messages = _prompt.build_edit_plan_messages(goal, media)
    plan_provider = self._editplan_provider_or_refuse()

    def work(_job_ctx: Any, _envelope: Any, provider: Any) -> dict[str, Any]:
        content = provider.chat(list(messages))
        parsed = _prompt.parse_edit_plan(content, plan_id=plan_id, video_id=video_id, goal=goal, source_hash=source)
        validated = _validate.validate_and_reject(parsed, understanding=understanding)
        from ..models.edit_plan import plan_to_dict, to_json  # local: import-light pure

        self._director_plans[plan_id] = _DirectorPlanEntry(
            plan=validated,
            video_id=video_id,
            messages=tuple(dict(m) for m in messages),
        )
        return {"planId": plan_id, "editPlan": plan_to_dict(validated), "preview": to_json(validated)}

    job = self._run_ai_job(
        ctx,
        messages=messages,
        model=str(self.settings.get().get("cloudModel") or ""),
        provider=plan_provider,
        work=work,
        feature="director",
        label="director.plan",
        videoId=video_id,
        ack=params.get("confirmBudget") if isinstance(params.get("confirmBudget"), str) else None,
    )
    return {"jobId": job.id}


def director_preview_cost(self: Services, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:  # noqa: ARG002 - ctx parity
    """``director.previewCost({planId})`` -> per-function cost/route preview.

    A distinct ``director.*`` surface that is a PURE pass-through to
    ``ai.planJob`` per data type (DECISION, DESIGN §7.1/§9): the ``editPlan``
    text request + the frame ``vision`` request, each tied to its own consent
    gate. Performs ZERO provider calls (the planner is pure). Returns
    ``{perFunction:[{function, route, costEst, willEgress, cacheHit, cacheKey}]}``.
    """
    plan_id = _require_str(params, "planId")
    entry = self._director_get_plan(plan_id)
    messages = [dict(m) for m in entry.messages]
    per_function: list[dict[str, Any]] = []
    for function, capability in (("editPlan", "text"), ("vision", "vision")):
        planned = self.ai_plan_job({"messages": messages, "capability": capability}, ctx)
        per_function.append(
            {
                "function": function,
                "route": planned["route"],
                "costEst": planned["costEst"],
                "willEgress": planned["willEgress"],
                "cacheHit": planned["cacheHit"],
                "cacheKey": planned["cacheKey"],
            }
        )
    return {"perFunction": per_function}


def _director_engines(self: Services) -> Any:
    """The op-kind -> engine dispatch table for ``director.apply`` (the seam).

    Wires the REAL ffmpeg op-engine adapters (``features.director_op_engines``)
    so ``director.apply`` actually RENDERS edited media (FIX #7): the core
    renderers ``trim``/``cut``/``removeSilence``/``caption`` operate on the
    project COPY and produce real mp4s, each recording an inverse for
    ``director.undo``. Deferred kinds (logged ONCE on first build) have no
    engine yet, so an op of one surfaces as a per-op ``failed`` with
    auto-rollback — never a crash, never a silent no-op. Tests inject a fake
    table over this seam.
    """
    from ..features import director_op_engines as _engines  # local: import-light pure

    if not self._director_engines_logged:
        _engines.log_deferred(log)
        self._director_engines_logged = True
    return _engines.build_engines(settings=self.settings.get())


def _director_inverse_engines(
    self: Services,
) -> Any:  # pragma: no cover - defaults to the forward seam; tests inject a distinct table
    """The op-kind -> engine table used to run RECORDED INVERSE ops (WU-undo).

    ``director.undo`` walks the recorded inverse ops (from ``director.apply``);
    each routes through this table. Defaults to the forward
    :meth:`_director_engines` — a real engine's inverse is the same engine
    running the inverse op — so v1 needs no separate wiring. A test injects a
    distinct table to prove the undo path routes inverse ops independently.
    """
    return self._director_engines()


def _director_apply_ack(self: Services, plan_id: str) -> str:
    """The budget-ack token (``cacheKey``) ``director.apply`` would require.

    Mirrors :meth:`_run_ai_job`'s gate: the plan's editPlan envelope cacheKey.
    Exposed so a client (and the test) can echo it as ``confirmBudget``.
    """
    from ..models import ai_job as _ai_job  # local: import-light

    entry = self._director_get_plan(plan_id)
    inputs = _ai_job.AiInputs(
        messages=tuple({str(k): str(v) for k, v in m.items()} for m in entry.messages),
        model=str(self.settings.get().get("cloudModel") or ""),
    )
    return self.plan_ai_job_envelope(inputs).cacheKey


def director_apply(self: Services, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
    """``director.apply({planId, confirmBudget?})`` -> ``{jobId}``. Job-based.

    Copy the project -> walk the stored plan's ops over the COPY (recording an
    inverse) via ``apply_plan`` (WU-apply), on ``ctx.jobs``. Enforces
    ``_enforce_cloud_budget_ack`` (echo the planJob ``cacheKey`` as
    ``confirmBudget``) so an egressing run is gated identically to the plan
    step. The source manifest is NEVER mutated (apply writes to the COPY). The
    ``job.done`` payload carries the per-op statuses + the COPY path.
    """
    if ctx.jobs is None:
        raise RpcError("no job registry available", ErrorCode.INTERNAL_ERROR)
    plan_id = _require_str(params, "planId")
    entry = self._director_get_plan(plan_id)
    ack = params.get("confirmBudget") if isinstance(params.get("confirmBudget"), str) else None

    from dataclasses import replace as _dc_replace  # local: import-light pure

    from ..features import apply_engine as _apply_engine  # local: import-light pure
    from ..features import project_copy as _project_copy  # local: import-light pure
    from ..models import ai_job as _ai_job  # local: import-light
    from ..models.edit_plan import plan_to_dict  # local: import-light pure

    envelope = self.plan_ai_job_envelope(
        _ai_job.AiInputs(
            messages=tuple({str(k): str(v) for k, v in m.items()} for m in entry.messages),
            model=str(self.settings.get().get("cloudModel") or ""),
        )
    )
    self._enforce_cloud_budget_ack(envelope, ack)

    project = self._load_or_create_project(entry.video_id)
    engines = self._director_engines()
    plan = entry.plan

    def work(_job_ctx: Any, _envelope: Any, _provider: Any) -> dict[str, Any]:
        project_copy = _project_copy.copy_project(project)
        result = _apply_engine.apply_plan(plan, project_copy=project_copy, engines=engines)
        # WU-undo: stash the recorded inverse plan under the plan id so
        # ``director.undo`` can re-apply it for a one-shot reversal (DESIGN §5).
        self._director_inverses[plan_id] = result.inverse_plan
        # Reuse the canonical op serializer (plan_to_dict) for the per-op
        # statuses by framing them as a throwaway plan's ``ops``.
        ops_status = plan_to_dict(_dc_replace(plan, ops=result.ops_status))["ops"]
        return {
            "planId": plan_id,
            "opsStatus": ops_status,
            "inversePlan": plan_to_dict(result.inverse_plan),
            "projectCopyPath": result.project_copy_path,
        }

    job = self._run_ai_job(
        ctx,
        messages=list(entry.messages),
        model=str(self.settings.get().get("cloudModel") or ""),
        provider=self._provider,
        work=work,
        feature="director",
        label="director.apply",
        videoId=entry.video_id,
        ack=ack,
    )
    return {"jobId": job.id}


def director_undo(self: Services, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
    """``director.undo({planId})`` -> ``{jobId}``. Job-based (DESIGN §5/§7.1).

    One-shot undo: re-apply the inverse plan ``director.apply`` recorded under
    ``planId`` over a FRESH project COPY via ``apply_plan`` (WU-apply), on
    ``ctx.jobs``. The recorded inverse ops (newest-first) route through
    :meth:`_director_inverse_engines`; re-applying them restores the
    pre-apply COPY (round-trip undo, WU-apply acceptance (c)). Undo is a pure
    LOCAL manifest reversal — no LLM/vision call, no egress — so the budget
    ack is NOT re-enforced (apply already gated its egress). A plan that was
    never applied has no recorded inverse and is rejected. The ``job.done``
    payload carries the per-op statuses + the COPY path.
    """
    if ctx.jobs is None:
        raise RpcError("no job registry available", ErrorCode.INTERNAL_ERROR)
    plan_id = _require_str(params, "planId")
    entry = self._director_get_plan(plan_id)
    inverse_plan = self._director_inverses.get(plan_id)
    if inverse_plan is None:
        raise _invalid(f"plan not applied (nothing to undo): {plan_id}")

    from dataclasses import replace as _dc_replace  # local: import-light pure

    from ..features import apply_engine as _apply_engine  # local: import-light pure
    from ..features import project_copy as _project_copy  # local: import-light pure
    from ..models.edit_plan import plan_to_dict  # local: import-light pure

    project = self._load_or_create_project(entry.video_id)
    engines = self._director_inverse_engines()

    def work(_job_ctx: Any, _envelope: Any, _provider: Any) -> dict[str, Any]:
        project_copy = _project_copy.copy_project(project)
        result = _apply_engine.apply_plan(inverse_plan, project_copy=project_copy, engines=engines)
        ops_status = plan_to_dict(_dc_replace(inverse_plan, ops=result.ops_status))["ops"]
        return {
            "planId": plan_id,
            "opsStatus": ops_status,
            "projectCopyPath": result.project_copy_path,
        }

    job = self._run_ai_job(
        ctx,
        messages=list(entry.messages),
        model=str(self.settings.get().get("cloudModel") or ""),
        provider=self._provider,
        work=work,
        feature="director",
        label="director.undo",
        videoId=entry.video_id,
        # Undo's ``work`` makes ZERO provider calls (pure local manifest
        # reversal) — it never egresses, so the cloud-budget gate is skipped
        # (DESIGN §5/§7.1). Apply already gated its own egress.
        enforce_budget=False,
    )
    return {"jobId": job.id}


def _director_eval_signals(self: Services, source: str, *, is_copy: bool) -> dict[str, Any]:  # noqa: ARG002 - is_copy distinguishes before/after for an injected seam
    """The eval-signals seam: a source descriptor -> a JSON-safe metric bundle.

    Adapts the SHIPPED ``phase8.signals`` runner output (motion values, scene
    cuts) into the value sequences :func:`director_eval.signals_to_metrics`
    consumes — so ``director.evaluate`` rides the SAME signal compute as
    ``phase8.signals`` (no parallel path). ``is_copy`` lets a test inject
    distinct before/after bundles; the default ignores it (the v1 apply COPY is
    a manifest, not re-encoded media, so before+after share the source compute
    until the engine WUs render an after-clip). The heavy runner stays behind
    its existing ``# pragma: no cover`` seam; this adapter is pure shaping.
    """
    runner = self._phase8_runner or self._default_phase8_runner()
    probe = self._ffprobe_duration or _self_ffprobe()
    settings = self.settings.get()
    tier = _coerce_tier(None, settings)
    tracks = runner(source, tier=tier, settings=settings, duration_probe=probe)
    motion = tracks.get("motion")
    cuts = tracks.get("sceneCut")
    return {
        "motion": [float(s.value) for s in getattr(motion, "signals", ())],
        "cuts": [float(s.start) for s in getattr(cuts, "signals", ())],
    }


def director_evaluate(self: Services, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:  # noqa: ARG002 - ctx parity (synchronous objective compute)
    """``director.evaluate({planId})`` -> objective before/after metrics.

    Computes goal-vs-result with the OBJECTIVE deltas (jerk / cutRhythm /
    silenceRatio / ocrCoverage) via the PURE :func:`director_eval.evaluate` over
    before/after metric dicts (DESIGN §4, AGENTS.md §7 — preferred over a
    sycophancy-prone LLM judge). The signals ride the SHIPPED ``phase8.signals``
    runner (the ``_director_eval_signals`` seam — no new AI path). An OPTIONAL
    qualitative judge note (the ``_director_eval_judge`` seam, routed through
    ``_run_ai_job`` in production) is DESCRIPTIVE only — it NEVER overrides the
    objective score. A plan never applied has no after-state to score (rejected).
    """
    plan_id = _require_str(params, "planId")
    entry = self._director_get_plan(plan_id)
    if plan_id not in self._director_inverses:
        raise _invalid(f"plan not applied (nothing to evaluate): {plan_id}")

    from ..features import director_eval as _eval  # local: import-light pure

    path = cast("str", self._resolve_video_path(entry.video_id))
    before = _eval.signals_to_metrics(self._director_eval_signals(path, is_copy=False))
    after = _eval.signals_to_metrics(self._director_eval_signals(path, is_copy=True))
    return _eval.evaluate(before, after, goal=entry.plan.goal, judge=self._director_eval_judge)
