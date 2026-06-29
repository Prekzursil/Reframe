"""Concrete per-job routing resolver — DESIGN §2.3 step 4 (V1.1 WU M5).

:mod:`routing_policy` owns the PURE policy resolver: ``resolve_route(fn) =
overrides[fn] ?? {mode: global}``, which answers only the abstract ``{mode}``
(local / cloud / auto) and is the fail-closed egress gate. THIS module is the
*concrete* second half the design calls out as "deliberately distinct": given the
``models.overview`` compose (local plan + detected runners + redacted providers)
and the persisted ``routing.perFunction`` model map, it resolves the actual
``{mode, model, runner|provider}`` a function will run on.

Degrade contract (DESIGN §2.1/§2.3 step 4): when the resolved mode is ``cloud`` or
``auto`` but there is no usable cloud provider (no key on disk), the route
degrades LOUDLY to local — ``degraded=True`` with the
:data:`ROUTE_DEGRADED_NOTICE` notice — NEVER a silent cloud route. The same helper
(:func:`degrade_to_local`) backs a runtime cloud-call failure in ``auto`` (the
caller flips to local and surfaces the notice). PURE: no I/O, never mutates input,
never raises.
"""

from __future__ import annotations

from typing import Any

from . import presets as _presets
from . import routing_policy as _routing_policy

#: The canonical user-facing AI functions the override table + resolver cover
#: (DESIGN §2.1: asr, moment-select/LLM, caption-polish, translate, director).
AI_FUNCTIONS: tuple[str, ...] = ("asr", "select", "caption", "translation", "director")

#: Human labels for each function (the Advanced override-table rows).
AI_FUNCTION_LABELS: dict[str, str] = {
    "asr": "Transcription (ASR)",
    "select": "Moment selection (LLM)",
    "caption": "Caption polish",
    "translation": "Translation",
    "director": "Director plan",
}

#: The functions whose LOCAL model is the whisper ASR pick (vs. the LLM pick).
_ASR_FUNCTIONS: frozenset[str] = frozenset({"asr"})

#: The runner name when no external local runner (Ollama / LM Studio) is detected —
#: the app falls back to its BUNDLED local model (faster-whisper / bundled LLM).
BUNDLED_RUNNER: str = "bundled"

#: The LOUD per-job notice surfaced when a cloud/auto route degrades to local
#: (DESIGN §2.1 "degraded: fell back to local"; reuses the reliability badge copy).
ROUTE_DEGRADED_NOTICE: str = "degraded: fell back to local"


def _local_model(fn: str, overview: dict[str, Any]) -> str:
    """The concrete local model id for ``fn`` from the overview's local plan.

    ASR functions take the device-ranked whisper pick; everything else takes the
    LLM pick. A missing plan / pick yields ``""`` (unknown — the runtime resolves
    the bundled default), never raises.
    """
    plan = overview.get("localPlan")
    plan = plan if isinstance(plan, dict) else {}
    pick = plan.get("whisper") if fn in _ASR_FUNCTIONS else plan.get("llm")
    pick = pick if isinstance(pick, dict) else {}
    model = pick.get("model")
    return model if isinstance(model, str) and model else ""


def _first_runner(overview: dict[str, Any]) -> str:
    """The first detected local-runner kind, or :data:`BUNDLED_RUNNER` if none."""
    for runner in overview.get("runners") or []:
        if isinstance(runner, dict):
            kind = runner.get("kind")
            if isinstance(kind, str) and kind:
                return kind
    return BUNDLED_RUNNER


def _local_route(fn: str, overview: dict[str, Any]) -> dict[str, Any]:
    """Build a concrete LOCAL route (not degraded) for ``fn``."""
    return {
        "fn": fn,
        "mode": "local",
        "requestedMode": "local",
        "model": _local_model(fn, overview),
        "runner": _first_runner(overview),
        "provider": None,
        "degraded": False,
        "notice": None,
    }


def degrade_to_local(fn: str, overview: dict[str, Any], *, requested_mode: str) -> dict[str, Any]:
    """A LOCAL route flagged ``degraded`` + the loud :data:`ROUTE_DEGRADED_NOTICE`.

    Used both when the concrete resolver finds no usable cloud target for a
    ``cloud`` / ``auto`` request AND by the runtime when a cloud call fails in
    ``auto`` (the caller flips to this and surfaces the notice). ``requested_mode``
    records what the user asked for so the UI can say "you asked for cloud, we ran
    local". NEVER a silent cloud route.
    """
    route = _local_route(fn, overview)
    route["requestedMode"] = requested_mode
    route["degraded"] = True
    route["notice"] = ROUTE_DEGRADED_NOTICE
    return route


def _configured_cloud_model(fn: str, settings: dict[str, Any]) -> str:
    """The cloud model id for ``fn``: per-function route > ``cloudModel`` > ``""``.

    Reads ``routing.perFunction[fn].provider`` (a catalog MODEL id per
    :mod:`presets`; the :data:`presets.LOCAL` sentinel is ignored — that means
    "local", not a cloud model). Falls back to the global ``cloudModel`` setting,
    else ``""`` (provider default).
    """
    routing = settings.get("routing")
    if isinstance(routing, dict):
        per = routing.get("perFunction")
        if isinstance(per, dict):
            slot = per.get(fn)
            if isinstance(slot, dict):
                model = slot.get("provider")
                if isinstance(model, str) and model and model != _presets.LOCAL:
                    return model
    cloud_model = settings.get("cloudModel")
    return cloud_model if isinstance(cloud_model, str) and cloud_model else ""


def _first_cloud_provider(overview: dict[str, Any]) -> str | None:
    """The first redacted provider that actually has a (last-4) key, or ``None``.

    A provider is usable only when it carries at least one non-blank key string —
    a keyless provider can never egress, so it does not count as a cloud target.
    """
    for provider in overview.get("providers") or []:
        if not isinstance(provider, dict):
            continue
        pid = provider.get("id") or provider.get("provider")
        keys = provider.get("apiKeys")
        if (
            isinstance(pid, str)
            and pid
            and isinstance(keys, list)
            and any(isinstance(k, str) and k.strip() for k in keys)
        ):
            return pid
    return None


def resolve_concrete_route(fn: str, settings: dict[str, Any], overview: dict[str, Any]) -> dict[str, Any]:
    """Resolve the concrete ``{mode, model, runner|provider}`` for ``fn`` (PURE).

    1. ``mode`` = the fail-closed policy mode (:func:`routing_policy.resolve_route`).
    2. ``local`` -> the device-ranked local model + detected runner.
    3. ``cloud`` / ``auto`` -> the configured cloud model on the first usable
       provider; when there is NO usable provider, :func:`degrade_to_local` (loud).

    Always returns a uniform shape: ``{fn, mode, requestedMode, model, runner,
    provider, degraded, notice}`` (``runner`` xor ``provider`` is set).
    """
    mode = _routing_policy.resolve_route(fn, settings)["mode"]
    if mode == "local":
        return _local_route(fn, overview)
    provider = _first_cloud_provider(overview)
    if provider is None:
        return degrade_to_local(fn, overview, requested_mode=mode)
    return {
        "fn": fn,
        "mode": mode,
        "requestedMode": mode,
        "model": _configured_cloud_model(fn, settings),
        "runner": None,
        "provider": provider,
        "degraded": False,
        "notice": None,
    }


def resolve_all_routes(settings: dict[str, Any], overview: dict[str, Any]) -> list[dict[str, Any]]:
    """Resolve a concrete route for every canonical :data:`AI_FUNCTIONS` (PURE)."""
    return [resolve_concrete_route(fn, settings, overview) for fn in AI_FUNCTIONS]


__all__ = [
    "AI_FUNCTIONS",
    "AI_FUNCTION_LABELS",
    "BUNDLED_RUNNER",
    "ROUTE_DEGRADED_NOTICE",
    "degrade_to_local",
    "resolve_all_routes",
    "resolve_concrete_route",
]
