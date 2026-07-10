# The only inter-module cycle is the TYPE_CHECKING-only Services ref below
# (no runtime cycle); silence the type-only back-edge warning.
# pyright: reportImportCycles=false
"""Composition-root handlers (F4b split): Provider-hub key/consent/usage/preset + routing-preference handlers.

Each function is a Services method body extracted verbatim from the former
monolithic handlers.py; `self` is typed against the composed `Services` (bound
in services.py). Behaviour + the RPC surface are byte-identical to pre-split.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..features import offline as _offline
from ..protocol import RpcContext
from ._shared import (
    _invalid,
    _require_str,
    _routing_block,
)

if TYPE_CHECKING:  # pragma: no cover - typing-only import, never executed at runtime
    from ._services import Services


def providers_catalog(self: Services, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
    """``providers.catalog()`` -> the static curated model catalog (WU-catalog).

    Returns :data:`catalog.CATALOG` as JSON: every provider/model with its
    per-task tiers, privacy / train-on-input flags, unit, free limits, the
    editorial top-pick per task, and the dated ``asOfDate`` stamp. PURE data —
    NO API keys, URLs, or secrets ever appear in this payload (the catalog is
    curated metadata; the user's keys live only in the redacted providers.list
    view). The renderer reads the camelCase wire shape verbatim.
    """
    from ..models import catalog as _catalog  # local: import-light pure data

    return _catalog.catalog_to_json()


def providers_list(self: Services, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
    """``providers.list()`` -> ``{providers:[...redacted...]}`` (WU-keys).

    Returns the configured pool with every ``apiKeys`` entry REDACTED to
    last-4 — the RPC layer NEVER returns a full key. Sourced from the
    already-redacting :meth:`SettingsStore.get`.
    """
    providers = self.settings.get().get("providers")
    return {"providers": providers if isinstance(providers, list) else []}


def providers_upsert(self: Services, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
    """``providers.upsert({id, provider?, kind?, baseUrl?, model?, apiKeys?, enabled?,
    capabilities?, unit?})`` -> ``{providers:[...redacted...]}`` (WU-keys).

    Inserts a new provider entry or merges into the existing one with the same
    ``id`` (RAW keys are stored). The returned providers list is REDACTED.
    Adding more keys to the SAME provider is failover-only (never N x quota,
    SE2) — that semantics lives in the rotation pool; here we just store them.
    """
    nested = params.get("provider")
    entry: dict[str, Any] = nested if isinstance(nested, dict) else params
    provider_id = entry.get("id")
    if not isinstance(provider_id, str) or not provider_id:
        raise _invalid("providers.upsert requires a provider id")
    existing = list(self.settings.get_raw().get("providers") or [])
    merged: list[dict[str, Any]] = []
    found = False
    for raw in existing:
        if isinstance(raw, dict) and raw.get("id") == provider_id:
            patch = {k: v for k, v in entry.items() if k != "id"}
            merged.append({**raw, **patch, "id": provider_id})
            found = True
        elif isinstance(raw, dict):
            merged.append(raw)
    if not found:
        merged.append(dict(entry))
    self.settings.set({"providers": merged})
    return self.providers_list(params, ctx)


def providers_remove(self: Services, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
    """``providers.remove({id})`` -> ``{providers:[...redacted...]}`` (WU-keys).

    Drops the provider entry with the given ``id``; returns the REDACTED
    remaining list. Removing an absent id is a no-op (idempotent).
    """
    provider_id = _require_str(params, "id")
    existing = list(self.settings.get_raw().get("providers") or [])
    remaining = [raw for raw in existing if not (isinstance(raw, dict) and raw.get("id") == provider_id)]
    self.settings.set({"providers": remaining})
    return self.providers_list(params, ctx)


def providers_test_key(self: Services, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
    """``providers.testKey({baseUrl, model?, apiKey})`` -> ``{ok, capabilities?, error?}``.

    Validates a key by issuing ONE minimal completion through the provider
    seam (a fake transport in tests). NEVER echoes the key back: the response
    carries only ``ok`` + the declared ``capabilities`` + a SCRUBBED ``error``
    string on failure (the live key is stripped at the provider construction
    site, so a 4xx error body never leaks the key over RPC).
    """
    base_url = _require_str(params, "baseUrl")
    api_key = params.get("apiKey")
    if not isinstance(api_key, str) or not api_key:
        raise _invalid("providers.testKey requires an apiKey")
    # Offline mode forbids ALL network egress: refuse (typed) before any HTTP so
    # the raw key never leaves the machine (bug-sweep fix).
    _offline.guard_network(self.settings.get(), "testing a provider key")
    capabilities = [str(c) for c in (params.get("capabilities") or ["text"])]
    from ..models import provider as _provider_mod  # local: heavy seam

    prov = _provider_mod.CloudProvider(
        api_key=api_key,
        base_url=base_url,
        model=str(params.get("model") or _provider_mod.DEFAULT_CLOUD_MODEL),
        transport=self._test_key_transport,
    )
    try:
        prov.chat([{"role": "user", "content": "ping"}], max_tokens=1)
    except _provider_mod.ProviderError as exc:
        # The message is already scrubbed at the construction site; do NOT add
        # the key back. Defensively scrub again in case a caller-side detail
        # carried it.
        from ..models.secrets import scrub_error_body

        return {"ok": False, "error": scrub_error_body(str(exc), [api_key])}
    return {"ok": True, "capabilities": capabilities}


def providers_reveal_key(self: Services, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
    """``providers.revealKey({id, index?})`` -> ``{key}`` — the ONE sanctioned plaintext exception.

    Returns exactly ONE raw plaintext API key, for TRANSIENT display in direct
    response to an EXPLICIT user click (a "reveal" affordance). This is the SOLE
    ``providers.*`` RPC that returns a FULL key: every other provider read
    (``providers.list`` / ``providers.usage`` / ``providers.openrouterUsage`` ...)
    redacts to last-4. It is the deliberate, DOCUMENTED exception to the
    redact-over-RPC invariant (PLAN §WU-D3, R7) — justified only because the user
    is explicitly asking to see their OWN stored key to read/copy it.

    SECURITY CONTRACT (enforced end-to-end, R7): the renderer holds the returned
    value ONLY in a transient ref, shows it masked-by-default, re-masks it on
    blur/timeout, and NEVER writes it into React state/store, logs, telemetry, or
    crash reports. Server-side the key is read RAW via :meth:`SettingsStore.get_raw`
    (the same FACTORY accessor the rotation pool uses), returned once, and never
    logged: ``rpc.py``'s param redaction keeps the ``{id, index}`` REQUEST out of
    diagnostics, and the RESPONSE is never written to a log line.

    ``index`` (default 0) selects among a provider's rotation-pool keys. An unknown
    id, an out-of-range / negative / non-``int`` (incl. ``bool``) index, or an empty
    stored slot is a typed ``INVALID_PARAMS`` error — never a crash, and never a
    silent empty reveal that the UI could mistake for a real key.
    """
    provider_id = _require_str(params, "id")
    index = params.get("index", 0)
    # bool is an int subclass but never a valid slot index; reject it explicitly.
    if isinstance(index, bool) or not isinstance(index, int) or index < 0:
        raise _invalid("providers.revealKey index must be a non-negative integer")
    raw_providers = self.settings.get_raw().get("providers")
    providers = raw_providers if isinstance(raw_providers, list) else []
    entry = next((p for p in providers if isinstance(p, dict) and p.get("id") == provider_id), None)
    if entry is None:
        raise _invalid(f"providers.revealKey: unknown provider {provider_id!r}")
    keys = entry.get("apiKeys")
    if not isinstance(keys, list) or index >= len(keys):
        raise _invalid(f"providers.revealKey: no key at index {index} for {provider_id!r}")
    key = keys[index]
    if not isinstance(key, str) or not key:
        raise _invalid(f"providers.revealKey: no key at index {index} for {provider_id!r}")
    return {"key": key}


def providers_set_consent(self: Services, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
    """``providers.setConsent({provider, text?, frames?})`` -> ``{consent}`` (WU-keys / SE1).

    TEXT (transcripts) and FRAMES (vision) consent are SEPARATE and
    independently revocable: only the keys present in the request are changed,
    so revoking ``frames`` leaves ``text`` intact and vice-versa. Returns the
    full consent block (no secrets — consent carries booleans only).
    """
    provider_name = _require_str(params, "provider")
    raw = self.settings.get_raw()
    consent = dict(raw.get("consent") or {})
    per_provider = dict(consent.get("perProvider") or {})
    current = dict(per_provider.get(provider_name) or {})
    if "text" in params:
        current["text"] = bool(params.get("text"))
    if "frames" in params:
        current["frames"] = bool(params.get("frames"))
    per_provider[provider_name] = current
    consent["perProvider"] = per_provider
    self.settings.set({"consent": consent})
    return {"consent": consent}


def providers_usage(self: Services, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
    """``providers.usage()`` -> ``{usage:[...]}`` per-key live usage (WU-usage-ui).

    Surfaces the rotation pool's per-key accounting
    ``{provider, key(redacted), used, max, unit, resetAt}`` — already produced
    from optimistic decrement + parsed 429/``X-RateLimit-*`` headers, so this
    is NOT a poller (no background loop, no per-call burst: the pool is built
    with ``detect_local=False`` so no ``GET /models`` socket is opened).

    The pool's in-memory counters reset each process, so the last-known numbers
    are PERSISTED (timestamped) in ``settings.usageCache`` and folded back in
    on read (DESIGN §15-Q1): the UI shows immediately on launch without
    re-polling, and rows older than the >10-min threshold are flagged ``stale``
    (the renderer desaturates them + shows "last checked Xm ago"). The ``key``
    field is ALWAYS the redacted last-4 (the pool never carries a live key into
    this row), so no full key crosses RPC.
    """
    from ..models.usage import flag_stale, merge_usage_cache

    live_rows: list[dict[str, Any]] = list(self._ai_pool().usage())
    raw_cache = self.settings.get_raw().get("usageCache")
    cache: dict[str, Any] = raw_cache if isinstance(raw_cache, dict) else {}
    raw_rows = cache.get("rows")
    cached_rows: list[dict[str, Any]] = raw_rows if isinstance(raw_rows, list) else []
    raw_checked = cache.get("checkedAt")
    checked_at: dict[str, Any] = raw_checked if isinstance(raw_checked, dict) else {}

    merged = merge_usage_cache(live_rows, cached_rows)
    now = self._now()
    # A row that carries real data this call is freshly checked NOW; one that
    # only survived from the persisted cache keeps its previous timestamp so
    # its age (and stale flag) keep counting up across reads.
    next_checked: dict[str, float] = {}
    for live in live_rows:
        ident = "\x00".join((str(live.get("provider", "")), str(live.get("key", ""))))
        used = live.get("used")
        fresh = (isinstance(used, (int, float)) and used > 0) or live.get("max") is not None
        next_checked[ident] = now if fresh else float(checked_at.get(ident, now))

    stamped = flag_stale(merged, now=now, checked_at=next_checked)
    # Persist the merged snapshot so the next launch shows it without polling.
    self.settings.set({"usageCache": {"rows": merged, "checkedAt": next_checked, "savedAt": now}})
    return {"usage": stamped}


def providers_openrouter_usage(self: Services, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
    """``providers.openrouterUsage()`` -> ``{usage:[...]}`` per-key COST (WU-models/device).

    The "calls/tokens" axes already live in :meth:`providers_usage` (parsed
    ``X-RateLimit-*`` headers). This adds the COST axis for OpenRouter: a
    best-effort ``GET /api/v1/key`` per RAW OpenRouter key (through the injectable
    ``_openrouter_usage_transport`` GET seam) reporting cumulative credit usage
    (USD), limit, and remaining. Best-effort + key-safe: a dead key is skipped
    (never raised), the live key rides ONLY the ``Authorization`` header, and the
    returned rows carry the REDACTED last-4 only — no full key crosses RPC.
    """
    # Offline mode forbids ALL network egress: refuse before the GET so the raw
    # OpenRouter key never leaves the machine (bug-sweep fix).
    _offline.guard_network(self.settings.get(), "checking OpenRouter usage")
    from ..models import openrouter_usage as _oru  # local: import-light
    from ..models import provider as _provider_mod  # local: heavy seam (GET transport)

    transport = self._openrouter_usage_transport or _provider_mod.urllib_get_json
    providers = self.settings.get_raw().get("providers")
    rows = _oru.fetch_usage(
        providers if isinstance(providers, list) else [],
        transport=transport,
    )
    return {"usage": rows}


def providers_spend(self: Services, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
    """``providers.spend()`` -> month-to-date spend + configured caps (WU-spend-cap).

    Surfaces the persisted monthly cumulative spend ledger for the renderer:
    the current month, the month-to-date total (cents), and the three
    configured caps (``monthlySoftLimitCents`` / ``monthlyHardLimitCents`` /
    ``enforceMonthlyHardLimit``). Read-only: it never records or mutates state.
    With the default off/0 settings every cap reads zero/false so an
    unconfigured install shows a benign "no cap" view.
    """
    from ..models import provider_pricing as _pricing  # local: import-light pure

    ledger = self._spend_ledger()
    settings = self.settings.get()
    return {
        "month": ledger.current_month(),
        "monthToDateCents": ledger.month_to_date(),
        "softLimitCents": int(settings.get("monthlySoftLimitCents") or 0),
        "hardLimitCents": int(settings.get("monthlyHardLimitCents") or 0),
        "enforceHardLimit": bool(settings.get("enforceMonthlyHardLimit")),
        # HONESTY (WU-D4): the month-to-date total is derived from STAND-IN
        # pricing (no curated model publishes a real per-request price), so it is
        # flagged an ESTIMATE — the UI must NOT present it as a real invoiced charge.
        "isEstimate": _pricing.spend_is_estimated(),
    }


def providers_usage_availability(self: Services, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
    """``providers.usageAvailability()`` -> ``{availability:[...]}`` honest per-provider notes (WU-D4).

    The LOCAL request/token counters (``providers.usage``) are always surfaced and
    OpenRouter's per-key COST is fetched live (``providers.openrouterUsage``). This
    read states, for every OTHER configured cloud provider, whether a provider-side
    usage API exists — OpenAI/Anthropic gate usage behind an organization ADMIN key
    a stored project key cannot use, and other providers publish nothing per-key.
    Rather than fabricate a 0, each such provider gets an honest "Usage API not
    available for <provider>" message. Rows carry the provider name only — NEVER a
    key (the classifier reads no key material).
    """
    from ..models import provider_usage_availability as _availability  # local: import-light pure

    raw_providers = self.settings.get_raw().get("providers")
    providers = raw_providers if isinstance(raw_providers, list) else []
    return {"availability": _availability.usage_availability(providers)}


def providers_apply_preset(self: Services, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
    """``providers.applyPreset({name})`` -> ``{activePreset, routing}`` (WU-presets).

    Resolves one of the smart presets (``privacy`` / ``bestFreeCloud`` /
    ``balanced``) into a concrete ``routing.perFunction`` map over the REAL
    curated catalog (via :class:`presets.CatalogAdapter`) and PERSISTS it. The
    ``privacy`` preset routes every function to local (zero cloud egress);
    ``bestFreeCloud`` picks the catalog's per-task top model with a local
    backstop; ``balanced`` mixes cloud text with local vision.
    """
    name = _require_str(params, "name")
    from ..models import presets as _presets  # local: import-light pure seam

    try:
        routing = _presets.apply_preset(name, self.settings.get(), _presets.CatalogAdapter())
    except ValueError as exc:
        raise _invalid(str(exc)) from exc
    self.settings.set({"activePreset": routing["activePreset"], "routing": _routing_block(routing)})
    return {"activePreset": routing["activePreset"], "routing": _routing_block(routing)}


def providers_set_function_model(self: Services, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
    """``providers.setFunctionModel({function, provider})`` -> ``{activePreset, routing}``.

    Overrides ONE function's routed provider (a catalog model-id or the
    :data:`presets.LOCAL` sentinel), leaving the other slots untouched, and
    flips ``activePreset`` to ``"custom"`` so the UI reflects the hand-edit.
    An unknown function or a missing provider is a typed invalid-params error.
    """
    from ..models import presets as _presets  # local: import-light pure seam

    function = _require_str(params, "function")
    if function not in _presets.FUNCTIONS:
        raise _invalid(f"unknown function: {function!r}")
    provider_id = _require_str(params, "provider")
    routing = dict(self.settings.get().get("routing") or {})
    per_function = dict(routing.get("perFunction") or {})
    per_function[function] = {"provider": provider_id, "fallback": []}
    new_routing = {"perFunction": per_function}
    self.settings.set({"activePreset": "custom", "routing": new_routing})
    return {"activePreset": "custom", "routing": new_routing}


def providers_first_run(self: Services, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
    """``providers.firstRun({choice?})`` -> the first-run local-vs-cloud chooser (P1 #6).

    With NO ``choice`` it is a READ: returns ``{firstRunChoiceMade, default}``
    where ``default`` is the local-safe :func:`presets.first_run_default`
    (``"privacy"`` until the user picks). With a ``choice`` (``"privacy"`` or
    any preset name) it APPLIES that preset, sets ``firstRunChoiceMade=True``,
    and returns ``{firstRunChoiceMade, activePreset, routing}`` — so a cloud
    choice flips the routing while a local choice keeps the all-local default.
    """
    from ..models import presets as _presets  # local: import-light pure seam

    choice = params.get("choice")
    if choice is None:
        return {
            "firstRunChoiceMade": bool(self.settings.get().get("firstRunChoiceMade")),
            "default": _presets.first_run_default(self.settings.get()),
        }
    if not isinstance(choice, str) or choice not in _presets.PRESETS:
        raise _invalid(f"unknown first-run choice: {choice!r}")
    try:
        routing = _presets.apply_preset(choice, self.settings.get(), _presets.CatalogAdapter())
    except ValueError as exc:  # pragma: no cover -- choice is guarded against PRESETS above
        raise _invalid(str(exc)) from exc
    block = _routing_block(routing)
    self.settings.set({"firstRunChoiceMade": True, "activePreset": routing["activePreset"], "routing": block})
    return {"firstRunChoiceMade": True, "activePreset": routing["activePreset"], "routing": block}


def _save_presets_block(self: Services) -> dict[str, Any]:
    """Return the current ``savePresets`` block as ``{presets, active}``.

    ``settings.set`` is a SHALLOW top-level merge (``settings_store``: writing
    ``savePresets`` REPLACES the whole block), so every mutating handler MUST
    read this full block, modify it, and write it back whole — otherwise a
    partial write would drop ``presets`` or ``active``. A corrupt (non-dict)
    block, or non-dict ``presets``, is defensively treated as empty.
    """
    raw = self.settings.get().get("savePresets")
    block = raw if isinstance(raw, dict) else {}
    presets = block.get("presets")
    active = block.get("active")
    return {
        "presets": dict(presets) if isinstance(presets, dict) else {},
        "active": active if isinstance(active, str) else "",
    }


def save_presets_list(self: Services, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
    """``savePresets.list()`` -> ``{presets, active}`` (WU-10).

    READ-ONLY roll-up of the named ``{autosave, exportDefaults}`` bundles the
    user has saved (``presets``) plus the last-applied bundle name (``active``).
    Writes nothing.
    """
    return self._save_presets_block()


def save_presets_upsert(self: Services, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
    """``savePresets.upsert({name, autosave?, exportDefaults?})`` -> ``{presets}``.

    Creates or replaces the named bundle. Omitted ``autosave`` / ``exportDefaults``
    default to ``{}`` (the renderer fills them from live settings). The whole
    ``savePresets`` block is read-modify-written so siblings (other presets +
    ``active``) survive the shallow-merge replace.
    """
    name = _require_str(params, "name")
    block = self._save_presets_block()
    block["presets"][name] = {
        "autosave": dict(params["autosave"]) if isinstance(params.get("autosave"), dict) else {},
        "exportDefaults": dict(params["exportDefaults"]) if isinstance(params.get("exportDefaults"), dict) else {},
    }
    self.settings.set({"savePresets": block})
    return {"presets": block["presets"]}


def save_presets_apply(self: Services, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
    """``savePresets.apply({name})`` -> ``{active, savePreset}`` (WU-10).

    Marks ``name`` the active bundle (persisted) and echoes it back. An unknown
    name is a typed invalid-params error (mirrors ``providers.applyPreset``'s
    ``ValueError -> _invalid``) rather than a crash.
    """
    name = _require_str(params, "name")
    block = self._save_presets_block()
    if name not in block["presets"]:
        raise _invalid(f"unknown save preset: {name!r}")
    block["active"] = name
    self.settings.set({"savePresets": block})
    return {"active": name, "savePreset": block["presets"][name]}


def save_presets_remove(self: Services, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
    """``savePresets.remove({name})`` -> ``{presets, active}`` (WU-10).

    Drops the named bundle. If it was the ``active`` one, ``active`` is reset to
    ``""`` (no stale pointer). An unknown name is a typed invalid-params error.
    """
    name = _require_str(params, "name")
    block = self._save_presets_block()
    if name not in block["presets"]:
        raise _invalid(f"unknown save preset: {name!r}")
    del block["presets"][name]
    if block["active"] == name:
        block["active"] = ""
    self.settings.set({"savePresets": block})
    return {"presets": block["presets"], "active": block["active"]}


def _function_prefer(self: Services, function: str) -> str | None:
    """Return the configured provider id the ``function`` seam should prefer.

    Reads ``routing.perFunction[function].provider`` (a catalog model-id, the
    :data:`presets.LOCAL` sentinel, or unset). The sentinel maps to
    :data:`provider.LOCAL_PROVIDER_ID` (a local-only route); an unset slot
    returns ``None`` (the pool keeps its configured order). The provider id is
    threaded into ``get_provider``/``get_translator`` as ``prefer=`` so the
    seam tries that provider first (PLAN §WU-presets acceptance (b)).
    """
    routing = self.settings.get().get("routing")
    if not isinstance(routing, dict):
        return None
    per_function = routing.get("perFunction")
    if not isinstance(per_function, dict):
        return None
    slot = per_function.get(function)
    if not isinstance(slot, dict):
        return None
    provider_id = slot.get("provider")
    return provider_id if isinstance(provider_id, str) and provider_id else None


def _provider_for_function(self: Services, function: str) -> Any:
    """Build the LLM provider the ``function`` seam uses, honoring routing.

    FACTORY PATH (PLAN §WU-keys): RAW keys via ``get_raw()``. The routed
    provider (``_function_prefer``) is tried first; the rest of the pool is
    failover with the local backstop last (or local-only when routed to LOCAL).

    M3 EGRESS GATE (GATE-2, Risk #3 — silent cloud egress): the cross-cutting
    ``RoutingPolicy`` resolves WHERE this function runs. ``resolve_route`` is
    fail-closed (a missing / corrupt / out-of-enum policy resolves ``local``), so
    ``mode == 'local'`` — which includes the DECISION §4 local-by-default — short-
    circuits to a LOCAL-ONLY pool with ``prefer=LOCAL_PROVIDER_ID``, exactly like
    offline: NO cloud entry is built, so neither the primary call nor a 429
    failover can ever reach a cloud target. ``cloud`` / ``auto`` fall through to
    the normal per-function route, where the per-entry text/frame consent gates
    still apply downstream.
    """
    from ..models import provider as _provider_mod  # local: heavy seam
    from ..models import routing_policy as _routing_policy  # local: import-light pure

    if _routing_policy.resolve_route(function, self.settings.get())["mode"] == "local":
        return _provider_mod.get_provider(
            self.settings.get_raw(), prefer=_provider_mod.LOCAL_PROVIDER_ID, ensure=self._llama_ensure()
        )
    # PRIVACY (bug-sweep fix, G-A5): text functions egress transcript-bearing
    # prompts, so filter the cloud pool through the per-provider TEXT-consent gate
    # BEFORE it is built — exactly as the index embedder + vision frame paths do.
    # A cloud entry without consent.perProvider[p].text is dropped, so neither the
    # primary call nor a 429 failover can reach a non-consented target (select then
    # degrades to the local LLM backstop rather than egressing without consent).
    return _provider_mod.get_provider(
        self._text_consented_settings(self.settings.get_raw()),
        prefer=self._function_prefer(function),
        ensure=self._llama_ensure(),
    )


def _select_provider_or_local(self: Services) -> Any:
    """Resolve the ``phase8.select`` chat provider, forcing LOCAL when offline.

    OFFLINE GATE: the unified selector's primary AI is a text chat over the
    ``select`` route, which is a cloud egress when routed cloud. Offline forbids
    that egress, so the provider is built with ``prefer=LOCAL_PROVIDER_ID`` —
    :func:`provider.build_pool_provider` then yields a LOCAL-ONLY pool with NO
    cloud entry, so neither the primary call NOR a 429 failover can ever reach a
    cloud target. Online, the normal per-function ``select`` route is honored.
    An injected ``_provider`` (tests) still wins outright.
    """
    if self._provider is not None:
        return self._provider
    from ..models import provider as _provider_mod  # local: heavy seam

    if _offline.is_offline(self.settings.get()):
        return _provider_mod.get_provider(
            self.settings.get_raw(), prefer=_provider_mod.LOCAL_PROVIDER_ID, ensure=self._llama_ensure()
        )
    return self._provider_for_function("select")


def _translator_for_function(self: Services, function: str) -> Any:
    """Build the TieredTranslator whose tier3 hosted pool honors routing.

    OFFLINE GATE (bug-sweep fix): when Offline mode is on, force the hosted tier
    to a LOCAL-ONLY pool (``prefer=LOCAL_PROVIDER_ID`` -> local-only per
    ``translation._default_hosted_factory``) so a cloud-routed translation can
    NEVER egress transcript text — mirroring ``_select_provider_or_local``. The
    prior ``subtitles.translate`` guard only fired on the legacy ``useCloud``
    flag, so a ``routing.perFunction['translation']`` cloud route slipped past it.
    The local MT tiers still translate offline.
    """
    from ..models import provider as _provider_mod  # local: heavy seam
    from ..models import translation as _translation_mod  # local: heavy seam

    prefer = (
        _provider_mod.LOCAL_PROVIDER_ID
        if _offline.is_offline(self.settings.get())
        else self._function_prefer(function)
    )
    return _translation_mod.get_translator(
        self.settings.get_raw(),
        runner=self._get_model_runner(),
        prefer=prefer,
        ensure=self._llama_ensure(),
    )


def _frame_consented_vision_settings(self: Services, settings: dict[str, Any]) -> dict[str, Any]:
    """Return ``settings`` with ``providers`` filtered to FRAME-consented entries.

    CRITICAL PRIVACY INVARIANT (PLAN §WU-vision acceptance (a): "NO frame
    egressed without that provider's frame consent"): the rotation pool that
    backs :class:`CloudVlmBackend` rotates across EVERY vision-capable cloud
    entry on a 429, so consent must be enforced PER-ENTRY at pool-construction
    time — not once against the first provider. Any cloud provider whose FRAME
    consent (``consent.perProvider[<provider>].frames``) is not explicitly
    granted is DROPPED from ``providers`` before the pool is built, so a 429
    failover can NEVER reach a non-consented target. Local-backstop entries
    (added inside ``build_pool_provider``, no key) are unaffected — they never
    egress. PURE: returns a new settings dict; the original is never mutated.
    """
    from ..models import consent as _consent  # local: import-light pure gate

    providers = settings.get("providers")
    if not isinstance(providers, list):
        return settings
    kept = [
        p
        for p in providers
        if isinstance(p, dict)
        and _consent.frame_consent_granted(settings, str(p.get("provider") or p.get("id") or "cloud"))
    ]
    return {**settings, "providers": kept}


def _text_consented_settings(self: Services, settings: dict[str, Any]) -> dict[str, Any]:
    """Return ``settings`` with ``providers`` filtered to TEXT-consented entries.

    CRITICAL PRIVACY INVARIANT (PLAN §WU-A1, G-A5 — the text analog of
    :meth:`_frame_consented_vision_settings`): the embedder rotation pool any
    cloud ``index`` route builds rotates across EVERY cloud entry on a 429, so
    TEXT consent must be enforced PER-ENTRY at pool-construction time — not once
    against the first provider — or a failover could rotate transcript text onto
    a non-consented target. Any provider whose TEXT consent
    (``consent.perProvider[<provider>].text``) is not explicitly granted is
    DROPPED from ``providers`` before the pool is built. Local-backstop entries
    (no key) are unaffected — they never egress. PURE: returns a new settings
    dict; the original is never mutated.

    Scope (PLAN §WU-A1): this seam is introduced HERE and consumed ONLY by the
    ``index`` routes; wiring it into the existing text functions
    (translation/select/subtitles) is an explicit follow-up (DESIGN §4 G-A5).
    """
    from ..models import consent as _consent  # local: import-light pure gate

    providers = settings.get("providers")
    if not isinstance(providers, list):
        return settings
    kept = [
        p
        for p in providers
        if isinstance(p, dict)
        and _consent.text_consent_granted(settings, str(p.get("provider") or p.get("id") or "cloud"))
    ]
    return {**settings, "providers": kept}


def _vision_pool(self: Services, settings: dict[str, Any]) -> Any:
    """Build the vision rotation pool honoring routing.perFunction["vision"].

    FACTORY PATH (PLAN §WU-keys): RAW keys via the caller's ``get_raw()``
    ``settings``. The routed vision provider is tried first; detection of local
    Ollama/LM-Studio is OFF here (no socket — only the configured cloud vision
    entries + the local backstop are needed). ``None`` when the provider module
    is a test stand-in without ``build_pool_provider``.

    SECURITY: callers building the cloud egress pool MUST pass settings already
    filtered through :meth:`_frame_consented_vision_settings`, so every
    cloud slot the pool may rotate to is frame-consented (no rotation bypass).
    """
    from ..models import provider as _provider_mod  # local: heavy seam

    builder = getattr(_provider_mod, "build_pool_provider", None)
    if builder is None:  # pragma: no cover -- only when provider is a stand-in w/o the pool builder
        return None
    return builder(
        settings,
        transport=self._vlm_chat_transport,
        detect_local=False,
        prefer=self._function_prefer("vision"),
    )


def _vision_provider_for_consent(self: Services, settings: dict[str, Any]) -> str | None:
    """The provider NAME a frame-consented vision pool would egress frames to.

    Builds the routed vision pool over the FRAME-CONSENT-FILTERED providers and
    returns the first vision-capable CLOUD entry's provider name — exactly the
    egress target. Because the input is already consent-filtered, ANY cloud
    entry it returns is one whose FRAME consent is granted; ``None`` when no
    consented cloud entry can serve vision (then the cloud path is never taken,
    so no frame is ever prepared for egress).
    """
    pool = self._vision_pool(self._frame_consented_vision_settings(settings))
    if pool is None:  # pragma: no cover -- stand-in-provider guard (see _vision_pool)
        return None
    from ..models.provider import DEFAULT_CAPABILITY  # local: import-light

    _vision = "vision"
    for entry in pool.entries:
        if not entry.local and _vision in entry.capabilities and _vision != DEFAULT_CAPABILITY:
            return entry.provider
    return None
