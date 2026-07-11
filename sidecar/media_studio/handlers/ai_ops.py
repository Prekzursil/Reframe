# The only inter-module cycle is the TYPE_CHECKING-only Services ref below
# (no runtime cycle); silence the type-only back-edge warning.
# pyright: reportImportCycles=false
"""Composition-root handlers (F4b split): AI-job envelope / budget / spend-cap + translator-runner handlers.

Each function is a Services method body extracted verbatim from the former
monolithic handlers.py; `self` is typed against the composed `Services` (bound
in services.py). Behaviour + the RPC surface are byte-identical to pre-split.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..protocol import RpcContext
from ._shared import (
    _BudgetRequest,
    _invalid,
    _LocalOnlyPool,
    log,
)

if TYPE_CHECKING:  # pragma: no cover - typing-only import, never executed at runtime
    from collections.abc import Callable

    from ._services import Services


def _sleep(seconds: float) -> None:
    """The real wall-clock pacing seam for the WU-B2 readiness probe.

    A thin ``time.sleep`` wrapper (``time`` imported lazily to keep this handler
    import-light). Isolated so the probe's poll interval is a single injectable
    seam the ``_llama_ensure`` closure passes down.
    """
    import time as _time  # noqa: PLC0415 - lazy so the module has no top-level time import

    _time.sleep(seconds)


def _get_provider(self: Services) -> Any:
    """Return the LLM provider for translation (cached test seam or real).

    FACTORY PATH (PLAN §WU-keys): builds from RAW keys via ``get_raw()`` — the
    provider must carry the live key; only RPC reads return redacted.
    """
    if self._provider is not None:
        return self._provider
    from ..models import provider as _provider_mod  # local import: heavy seam

    return _provider_mod.get_provider(self.settings.get_raw())


def _ai_cache(self: Services) -> Any:
    """The shared AI-call content cache (WU-cache), under the data dir.

    Honors ``settings.aiCacheDir`` (absolute path) when set, else
    ``data_dir/ai-cache``. The cache is local-only; nothing leaves the box.
    """
    from ..models.ai_cache import DEFAULT_CACHE_DIRNAME, AiCache  # local: import-light

    configured = self.settings.get().get("aiCacheDir")
    store_dir = Path(configured) if configured else self.data_dir / DEFAULT_CACHE_DIRNAME
    return AiCache(store_dir=store_dir)


def _ai_pool(self: Services) -> Any:
    """Build the rotation pool (WU-pool) from settings for budget/route reads.

    Returns an object whose ``.entries`` (each carrying ``.provider`` /
    ``.local``) satisfy :func:`budget.estimate`'s pool shape. The real path
    builds a :class:`RotatingProvider` with detection OFF (planning only reads
    the catalog-shaped entries; skipping the live ``GET /models`` probe keeps
    ai.planJob / the plan step socket-free — PLAN: ZERO provider calls). When
    the provider module is a test stub WITHOUT ``build_pool_provider`` we fall
    back to a local-only pool (the budget then reports local-only, no egress).
    """
    from ..models import provider as _provider_mod  # local: heavy seam

    builder = getattr(_provider_mod, "build_pool_provider", None)
    if builder is None:
        return _LocalOnlyPool()
    # FACTORY PATH (PLAN §WU-keys): the pool is built from RAW keys.
    return builder(self.settings.get_raw(), detect_local=False)


def _spend_ledger(self: Services) -> Any:
    """The persisted monthly spend ledger (WU-spend-cap), under the data root.

    A single JSON document at ``data_dir/spend-ledger.json`` (alongside the
    other persisted state), keyed by calendar month. The handler's injectable
    ``_now`` clock is threaded in so the month-key derivation is deterministic
    under test and matches the rest of the Hub's wall-clock seam.
    """
    from ..models.spend_ledger import SpendLedger  # local: import-light pure

    return SpendLedger(self.data_dir / "spend-ledger.json", clock=self._now)


def _estimate_job_cents(self: Services, envelope: Any) -> int:
    """The estimated cost (cents) of running ``envelope``, or 0 if non-egressing.

    A run that will not egress (cache hit / local-only pool) costs nothing. For
    an egressing cloud run the estimate is the planned request count times the
    per-request price for the run's model — a REAL price where the pricing table
    has one, else the documented placeholder (see ``provider_pricing``; the catalog
    has no structured numeric price yet, so today every estimate is placeholder-
    derived and ``providers.spend`` flags the aggregate ``isEstimate``). The SAME
    helper feeds both the pre-egress hard-cap check and the completion record, so
    the predicted and recorded costs always agree.
    """
    from ..models import provider_pricing  # local: import-light pure

    if not envelope.route.willEgress:
        return 0
    return int(envelope.costEst.requests) * provider_pricing.request_cents(envelope.inputs.model)


def _enforce_monthly_hard_cap(self: Services, envelope: Any) -> None:
    """Refuse an egressing run that would push month-to-date over the hard cap.

    Fires ONLY when ``enforceMonthlyHardLimit`` is on AND the planned run would
    egress AND ``month_to_date + this-job-estimate`` exceeds
    ``monthlyHardLimitCents``. This is INDEPENDENT of the ``confirmCloudBudget``
    ack gate (the two are orthogonal: a per-run ack does not waive the monthly
    ceiling). A non-egressing run costs nothing and is never refused.
    """
    settings = self.settings.get()
    if not settings.get("enforceMonthlyHardLimit"):
        return
    job_cents = self._estimate_job_cents(envelope)
    if job_cents <= 0:
        return
    hard_cap = settings.get("monthlyHardLimitCents")
    if not isinstance(hard_cap, (int, float)) or isinstance(hard_cap, bool) or hard_cap <= 0:
        return
    ledger = self._spend_ledger()
    projected = ledger.month_to_date() + job_cents
    if projected > hard_cap:
        raise _invalid(f"monthly spend cap ${hard_cap / 100:.2f} reached")


def _enforce_egress_gates(self: Services, envelope: Any, ack: str | None) -> None:
    """Run BOTH pre-egress gates for ``envelope`` (the single egress chokepoint).

    Every cloud-egress path (``_run_ai_job`` and the ``index.*`` embedding
    routes) calls this so the gates can never be applied unevenly: the per-run
    ``confirmCloudBudget`` ack gate AND the independent monthly hard cap. Both
    are no-ops for a non-egressing (local-only / cache-hit) envelope.
    """
    self._enforce_cloud_budget_ack(envelope, ack)
    self._enforce_monthly_hard_cap(envelope)


def _record_egress_cost(self: Services, envelope: Any) -> None:
    """Record ``envelope``'s estimated cost in the spend ledger (WU-spend-cap).

    The single recording site shared by the job-bus path (via ``run_ai_job``'s
    ``on_egress`` callback) and the synchronous ``index.search`` query embed.
    ``_estimate_job_cents`` returns 0 for a non-egressing envelope, so calling
    this for a local-only run is a harmless zero-record; callers gate on
    ``willEgress`` first so a local run records nothing at all.
    """
    self._spend_ledger().record(self._estimate_job_cents(envelope))


def plan_ai_job_envelope(self: Services, inputs: Any) -> Any:
    """Assemble an :class:`ai_job.AiJob` envelope for ``inputs`` (PURE, no calls).

    Shared by ``ai.planJob`` (pre-flight) and the AI-bearing job handlers so
    cost/route/cacheKey are derived from ONE place. Performs ZERO provider
    calls — the pool is built only to read its catalog-shaped ``.entries``.
    """
    from ..models import ai_job as _ai_job  # local: import-light

    return _ai_job.plan_ai_job(
        inputs,
        pool=self._ai_pool(),
        catalog=_ai_job.CatalogFreeCapAdapter(),
        cache=self._ai_cache(),
    )


def _run_ai_job(
    self: Services,
    ctx: RpcContext,
    *,
    messages: list[dict[str, str]],
    model: str,
    provider: Any,
    work: Any,
    feature: str,
    label: str,
    videoId: str | None = None,  # noqa: N803 - wire-name kwarg (matches JobRegistry)
    ack: str | None = None,
    enforce_budget: bool = True,
) -> Any:
    """Plan + run an :class:`ai_job.AiJob` on ``ctx.jobs`` with a custom ``work``.

    ``provider`` is the resolved provider the work consumes; when ``None`` the
    pool-aware ``get_provider`` is built lazily (so rotation + degrade tracking
    apply). The envelope's cost/route/cacheKey come from
    :meth:`plan_ai_job_envelope`. Returns the created job (the ``{jobId}``
    source). The work's own result dict is the ``job.done`` payload.

    WU-budget pre-flight gate: when ``settings['confirmCloudBudget']`` is on
    AND the planned run WOULD egress, ``ack`` MUST equal the envelope's
    ``cacheKey`` (the token ``ai.planJob`` returns), else the run is refused
    with a typed error telling the client to pre-flight + acknowledge first.
    A local-only / cache-hit run never egresses, so it is never gated.

    ``enforce_budget=False`` skips the cloud-budget gate entirely — for a job
    whose ``work`` provably makes NO provider call and therefore never egresses
    (e.g. ``director.undo``: a pure LOCAL manifest reversal). Such a job rides
    the same envelope/job path for uniformity but has no budget surface to
    acknowledge, so gating it would refuse a non-egressing run with a token the
    caller cannot supply.
    """
    from ..models import ai_job as _ai_job  # local: import-light

    inputs = _ai_job.AiInputs(
        messages=tuple({str(k): str(v) for k, v in m.items()} for m in messages),
        model=model,
    )
    envelope = self.plan_ai_job_envelope(inputs)
    if enforce_budget:
        # WU-spend-cap: the per-run ack gate AND the independent monthly hard
        # cap both run here before any egress (the shared egress chokepoint).
        self._enforce_egress_gates(envelope, ack)

    def _factory() -> Any:
        if provider is not None:
            return provider
        from ..models import provider as _provider_mod  # local: heavy seam

        # FACTORY PATH (PLAN §WU-keys): the run provider carries RAW keys.
        return _provider_mod.get_provider(self.settings.get_raw())

    return _ai_job.run_ai_job(
        envelope,
        jobs=ctx.jobs,
        provider_factory=_factory,
        cache=self._ai_cache(),
        work=work,
        feature=feature,
        label=label,
        videoId=videoId,
        # WU-spend-cap record-at-completion: fired ONLY after a run that
        # actually egressed (a real cloud call, including degrade-to-local) —
        # never on a cache hit, local-only run, cancel, or error.
        on_egress=self._record_egress_cost if enforce_budget else None,
    )


def _enforce_cloud_budget_ack(self: Services, envelope: Any, ack: str | None) -> None:
    """Refuse a non-acknowledged cloud run when ``confirmCloudBudget`` is on.

    The gate fires ONLY when both hold: the setting ``confirmCloudBudget`` is
    truthy AND the planned envelope ``route.willEgress`` is True (a run that
    sends bytes off the machine). In that case ``ack`` must equal the
    envelope's ``cacheKey`` — the token ``ai.planJob`` returns — proving the
    client previewed THIS exact request's cost/egress budget. A local-only or
    cache-hit run never egresses, so it bypasses the gate entirely.
    """
    if not envelope.route.willEgress:
        return
    if not self.settings.get().get("confirmCloudBudget"):
        return
    if ack == envelope.cacheKey:
        return
    raise _invalid(
        "cloud run requires budget acknowledgement: call ai.planJob and pass "
        "its cacheKey as confirmBudget (or disable confirmCloudBudget)"
    )


def ai_plan_job(self: Services, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
    """``ai.planJob({messages?, model?, params?, request?, capability?})`` -> pre-flight.

    Returns ``{route, costEst, cacheHit, willEgress, budget, preview, cacheKey}``
    WITHOUT executing any AI call (PLAN acceptance: ZERO provider calls). The
    request shape is the budget request (``target_size`` / ``text_bytes`` /
    ``frame_bytes``); ``messages`` feed the cache key so the pre-flight knows
    whether a real run would be a cache hit.
    """
    from ..models import ai_job as _ai_job  # local: import-light

    raw_messages = params.get("messages")
    messages = (
        tuple({str(k): str(v) for k, v in m.items()} for m in raw_messages if isinstance(m, dict))
        if isinstance(raw_messages, list)
        else ()
    )
    request = self._budget_request(params.get("request"))
    inputs = _ai_job.AiInputs(
        messages=messages,
        model=str(params.get("model") or ""),
        params=dict(params.get("params") or {}),
        request=request,
        capability=str(params.get("capability") or "text"),
    )
    envelope = self.plan_ai_job_envelope(inputs)
    planned = envelope.planned()
    warning = self._soft_spend_warning(envelope)
    if warning is not None:
        planned["spendWarning"] = warning
    return planned


def _soft_spend_warning(self: Services, envelope: Any) -> dict[str, Any] | None:
    """A non-blocking soft-cap warning for ``ai.planJob``, or ``None``.

    Returns a warning payload when ``monthlySoftLimitCents`` is set (> 0) AND
    the projected month-to-date (current MTD + this job's estimate) exceeds it.
    This NEVER blocks — it is surfaced in the plan/envelope so the renderer can
    nudge the user; the hard cap (``_enforce_monthly_hard_cap``) is the only
    thing that refuses a run.
    """
    settings = self.settings.get()
    soft_cap = settings.get("monthlySoftLimitCents")
    if not isinstance(soft_cap, (int, float)) or isinstance(soft_cap, bool) or soft_cap <= 0:
        return None
    ledger = self._spend_ledger()
    month_to_date = ledger.month_to_date()
    projected = month_to_date + self._estimate_job_cents(envelope)
    if projected <= soft_cap:
        return None
    return {
        "softLimitCents": int(soft_cap),
        "monthToDateCents": month_to_date,
        "projectedCents": projected,
        "message": f"monthly soft spend limit ${soft_cap / 100:.2f} exceeded",
    }


def _budget_request(self: Services, raw: Any) -> Any:
    """Coerce a wire ``request`` dict into a budget request (or ``None``).

    The returned :class:`_BudgetRequest` satisfies the duck-typed
    ``budget.BudgetRequest`` protocol (``target_size`` / ``text_bytes`` /
    ``frame_bytes``). A non-dict ``raw`` yields ``None`` (an unsized request).

    WU-budget (P1 #6): when the wire request pins NO ``targetSize`` we resolve
    the size to the user's ``defaultTargetJobSize`` setting, so the pre-flight
    budget reflects the configured default job size (one source -> N shorts)
    rather than only the module constant. A request that DOES pin a size keeps
    it verbatim. A non-positive / non-int setting falls back to the budget
    module's ``DEFAULT_TARGET_JOB_SIZE`` (the same fallback ``estimate`` uses).
    """
    if not isinstance(raw, dict):
        return None
    size = raw.get("targetSize")
    return _BudgetRequest(
        target_size=int(size) if isinstance(size, int) else self._default_target_job_size(),
        text_bytes=int(raw.get("textBytes") or 0),
        frame_bytes=int(raw.get("frameBytes") or 0),
    )


def _default_target_job_size(self: Services) -> int:
    """The configured default job size, or the budget module's constant.

    Reads ``settings['defaultTargetJobSize']`` (PLAN P1 #6); a missing /
    non-int / non-positive value falls back to
    :data:`budget.DEFAULT_TARGET_JOB_SIZE` so the estimate stays falsifiable.
    """
    from ..models import budget as _budget_mod  # local: import-light pure

    configured = self.settings.get().get("defaultTargetJobSize")
    if isinstance(configured, int) and configured > 0:
        return configured
    return _budget_mod.DEFAULT_TARGET_JOB_SIZE


def _get_model_runner(self: Services) -> Any:
    """The shared ModelRunner (lazily built from settings; T3)."""
    if self._model_runner is None:
        from ..models import runner as _runner_mod  # local import: heavy seam

        self._model_runner = _runner_mod.ModelRunner(self.settings.get())
    return self._model_runner


def _llama_ensure(self: Services) -> Callable[[], None]:
    """Build the injected llama-backstop ``ensure()`` callback (WU-B2: fixes LLM 10061).

    Returns an opaque zero-arg callback the provider / translator seams invoke
    lazily ONLY when a ``local`` backstop slot is actually reached (after cloud
    keys; never for a detected Ollama / LM-Studio server). It ensures the
    llama.cpp server (:8088) is up via the shared :class:`ModelRunner` — reuse-
    aware (a running server is left as-is) and LaneLock-cooperative (the spawn is
    routed through ``start_server``, so it evicts / yields to whisper/ASR) — then
    runs the bounded ``GET /health`` readiness probe.

    NO silent fallback: a ``start_server`` failure is surfaced as a
    :class:`ProviderError` (so :class:`RotatingProvider` treats the slot as
    exhausted and the exhausted-pool message shows the real cause), and the probe
    RAISES a :class:`ProviderError` on timeout / child-exit rather than hanging.
    The shared runner is captured so repeated calls single-flight onto one server.
    """
    from ..models import provider as _provider_mod  # local: heavy seam

    runner = self._get_model_runner()
    settings = self.settings.get()
    base_url = str(settings.get("localBaseUrl") or _provider_mod.DEFAULT_LOCAL_BASE_URL)
    health_url = _provider_mod.health_url_from_base(base_url)

    def _ensure() -> None:
        try:
            runner.start_server()
        except _provider_mod.ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001 - surface ANY start failure loudly as ProviderError
            raise _provider_mod.ProviderError(f"local model server failed to start: {exc}") from exc
        _provider_mod.readiness_probe(
            health_url,
            transport=_provider_mod.urllib_get_json,
            now=self._now,
            sleep=_sleep,
            child_exited=lambda: not runner.server_running,
        )

    return _ensure


def _get_translator(self: Services) -> Any | None:
    """TieredTranslator for subtitles.translate (T3).

    Returns ``None`` when a legacy ``provider`` seam was injected (tests):
    the caller then keeps the original single-provider path, so every
    existing handler test stays green.
    """
    if self._provider is not None:
        return None
    from ..models import translation as _translation_mod  # local import

    # FACTORY PATH (PLAN §WU-keys): the tier3 hosted provider is built from RAW keys.
    # TEXT-CONSENT GATE (bug-sweep fix): filter the RAW settings through
    # _text_consented_settings so cue text can never rotate onto a non-text-consented
    # cloud provider (mirrors _translator_for_function / _provider_for_function).
    return _translation_mod.get_translator(
        self._text_consented_settings(self.settings.get_raw()), runner=self._get_model_runner()
    )


def _dub_translator(self: Services) -> Any:
    """Adapt T3's TieredTranslator to dub's text-based Translator seam.

    CONTRACT-NOTE (WIRING-T2 §2): ``tts.dub.Translator`` is
    ``translate(texts, target_lang, source_lang) -> texts`` + ``free()``;
    T3's TieredTranslator is cue-based and exposes no ``free``. This
    adapter wraps texts into cue dicts (timings unused by MT) and frees the
    MT model by stopping the shared llama server — the batched 'free MT'
    stage between translate-ALL and synth-ALL (A4).

    OFFLINE GATE (bug-sweep fix): the tiered translator is built via
    ``_translator_for_function('translation')``, which forces a LOCAL-ONLY
    hosted pool when Offline mode is on — so dub translation can NEVER egress
    transcript text while offline, mirroring the subtitles.translate path.
    (The old direct ``get_translator`` build had no offline gate.)
    """
    runner = self._get_model_runner()
    # FACTORY PATH (PLAN §WU-keys): tier3 carries RAW keys; the offline gate lives
    # in _translator_for_function (prefer=LOCAL_PROVIDER_ID when offline).
    tiered = self._translator_for_function("translation")

    class _DubTranslator:
        def translate(
            self,
            texts: list[str],
            target_lang: str,
            source_lang: str | None = None,
        ) -> list[str]:
            cues = [{"index": i + 1, "start": 0.0, "end": 0.0, "text": str(t)} for i, t in enumerate(texts)]
            out = tiered.translate(cues, target_lang, source_lang=source_lang)
            return [str(c.get("text", "")) for c in out]

        def free(self) -> None:
            try:
                runner.stop_server()
            except Exception:  # noqa: BLE001 - freeing is best-effort
                log.warning("MT free: stop_server failed")

    return _DubTranslator()
