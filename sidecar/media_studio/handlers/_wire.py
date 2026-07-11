"""Pure wire/format helpers (F4b split): report->wire adapters, readiness-item
builders, tier coercion, and the default ffmpeg/ffprobe seam factories.
Extracted verbatim from the former handlers.py module-level helpers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def _self_ffmpeg_run() -> Callable[..., int]:
    """The default ffmpeg ``run`` (imported lazily to keep this module light)."""
    from .. import ffmpeg as _ffmpeg

    return _ffmpeg.run


def _self_ffprobe() -> Callable[..., float]:
    """The default ffprobe duration probe (lazy import)."""
    from .. import ffmpeg as _ffmpeg

    return _ffmpeg.ffprobe_duration


def _evenly_spaced(start: float, end: float, n: int) -> list[float]:
    """The ``n`` evenly-spaced sample times across ``[start, end)`` (WU-C3).

    Mirrors the frame-loader's even sampling so the picked frame's index maps back
    to its source-relative time. ``n <= 0`` yields ``[]``; a single frame samples
    the span start (the loader's first sample). A zero-length span collapses all
    samples onto ``start`` (a still clip), never raising.
    """
    if n <= 0:
        return []
    span = float(end) - float(start)
    step = span / float(n)
    return [float(start) + step * k for k in range(n)]


def _js_number(value: Any) -> str:
    """Render a number the way JavaScript ``String(n)`` would (for candidate ids).

    JS prints ``5`` for ``5.0`` and ``5.5`` for ``5.5``. Python's ``str(5.0)`` is
    ``"5.0"``, so an integer-valued float must drop the ``.0`` to match the UI's
    ``${c.sourceStart}`` template, otherwise the cached id never matches.
    """
    try:
        num = float(value)
    except (TypeError, ValueError):
        return str(value)
    if num.is_integer():
        return str(int(num))
    return repr(num)


# --------------------------------------------------------------------------- #
# Phase-8 wiring helpers (pure; the heavy runner stays pragma-excluded)
# --------------------------------------------------------------------------- #
#: advisor component name -> its registered manifest asset name (the installed
#: -state probe key). Components with no own asset (motion/diversity/ranker are
#: zero-download floors) are absent; ``aesthetic`` shares the SigLIP-2 backbone.
_COMPONENT_ASSETS: dict[str, str] = {
    "saliency": "vinet-s-saliency",
    "audio_saliency": "panns-cnn14",
    "scene_transnet": "transnetv2-pytorch",
    "vlm_backbone": "siglip2-so400m",
    "aesthetic": "siglip2-so400m",
    "quality_gate": "dover-mobile-quality",
    "emotion": "hsemotion-onnx",
    "ocr": "rapidocr-onnx",
    "parakeet": "parakeet-tdt-0.6b-v3",
    "ctc_aligner": "ctc-forced-aligner-mms",
    "pyannote": "pyannote-speaker-diarization-31",
    "smolvlm2": "smolvlm2-2.2b",
}

#: settings key picking the Phase-8 moment-finding tier (0/1/2).
PHASE8_TIER_KEY = "phase8Tier"


def _coerce_tier(value: Any, settings: dict[str, Any]) -> int:
    """Resolve the Phase-8 tier: explicit ``value`` wins, else settings, else 1.

    Clamped to 0..2 (the three runnable presets). Any non-integer / out-of-range
    input falls back to the Tier-1 default so a typo never breaks a select.
    """
    raw = value if value is not None else settings.get(PHASE8_TIER_KEY, 1)
    try:
        tier = int(raw)
    except (TypeError, ValueError):
        return 1
    return min(2, max(0, tier))


def _signals_summary(tracks: dict[str, Any]) -> dict[str, Any]:
    """Summarize computed signal tracks -> ``{tracks:{ch:count}, present:{ch:bool}}``.

    A JSON-safe digest of the per-channel :class:`SignalTrack` map (the heavy
    runner's output): per-channel signal count + present flag. Keeps the wire
    payload small (the raw signals stay server-side for the select path).
    """
    counts: dict[str, int] = {}
    present: dict[str, bool] = {}
    for channel, track in tracks.items():
        counts[channel] = len(getattr(track, "signals", ()) or ())
        present[channel] = bool(getattr(track, "present", False))
    return {"tracks": counts, "present": present}


#: WU-8 readiness: each runnable tier id -> (label, the advisor-component names it
#: needs). Mirrors ``system_advisor.TIERS`` but expressed against ``_COMPONENT_ASSETS``
#: so readiness is derived purely from installed-weight state (no hardware probe /
#: dependency import). Tier-0 is the zero-download CPU floor (no model-backed
#: components) and so is always ready.
_READINESS_TIERS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("tier0-numeric", "Instant numeric (no downloads)", ()),
    (
        "tier1-multimodal",
        "Multimodal (visual + audio + transcript)",
        ("saliency", "audio_saliency", "scene_transnet", "vlm_backbone", "quality_gate"),
    ),
    ("tier2-vlm", "Video-LLM re-rank (heavy, opt-in)", ("smolvlm2",)),
)

#: WU-8 readiness: the AI functions whose cloud-route key/consent state is rolled
#: up. Mirrors ``presets.FUNCTIONS``; ``vision`` checks FRAME consent, the rest
#: check TEXT consent (the §-consent data-type split).
_READINESS_FUNCTIONS: tuple[str, ...] = ("select", "subtitles", "translation", "vision", "editPlan")

#: The routing sentinel meaning "run this function locally" (mirrors
#: ``presets.LOCAL``); an unrouted function also defaults to the local-safe route.
_LOCAL_ROUTE = "local"


def _missing_tier_assets(component_names: tuple[str, ...], models_present: dict[str, bool]) -> list[str]:
    """The de-duplicated, ENSURABLE asset names a tier needs that are NOT installed.

    Maps each member component to its pinned asset (``_COMPONENT_ASSETS``) and
    keeps only the assets whose weight is not present AND that the manifest still
    knows (``manifest.get_asset`` is not None). Components sharing an asset
    (e.g. ``vlm_backbone``/``aesthetic`` both use SigLIP-2) collapse to one name.

    B1: a mapped-but-DE-REGISTERED asset is dropped here so it never reaches an
    ``assets.ensure`` action — emitting it would trip the manager's "unknown
    asset(s)" gate. Only manifest-known targets are ever emitted.
    """
    from ..assets import manifest as _manifest  # local: import-light, data only

    missing: list[str] = []
    for name in component_names:
        if models_present.get(name, False):
            continue
        asset = _COMPONENT_ASSETS.get(name)
        if asset is None or asset in missing:
            continue
        if _manifest.get_asset(asset) is None:
            continue  # de-registered: never emit an un-ensurable asset name
        missing.append(asset)
    return missing


def _tier_has_missing_weight(component_names: tuple[str, ...], models_present: dict[str, bool]) -> bool:
    """True when any model-backed member component's weight is not installed.

    Unlike :func:`_missing_tier_assets` (which reports only ENSURABLE assets), this
    counts a missing component even when its asset is de-registered — so a tier
    with an un-downloadable missing weight is never falsely reported ``ready``.
    """
    return any(name in _COMPONENT_ASSETS and not models_present.get(name, False) for name in component_names)


def _missing_weights_phrase(ensurable: list[str]) -> str:
    """The human ``blockedBy`` phrase for a tier with missing weights.

    Names the ensurable (manifest-known) assets when there are any; otherwise a
    generic phrase (the missing weights map only to de-registered assets, so no
    concrete download target can be named yet — B4 re-registers them).
    """
    if ensurable:
        return f"missing model weights: {', '.join(ensurable)}"
    return "missing model weights (not yet available for download)"


def _tier_readiness_items(models_present: dict[str, bool], *, offline: bool) -> list[dict[str, Any]]:
    """Roll each runnable tier up to a :class:`ReadinessItem` from installed state.

    ``ready`` when every member weight is installed; ``needsDownload`` (with an
    ``assets.ensure`` action over the missing, manifest-KNOWN asset names) when a
    weight is missing online AND at least one is ensurable; ``unavailable`` when a
    weight is missing but Offline mode is on (download blocked) OR none of the
    missing weights map to a registered asset yet (B1: emit no un-ensurable name,
    no false ``ready``).
    """
    items: list[dict[str, Any]] = []
    for tier_id, label, components in _READINESS_TIERS:
        if not _tier_has_missing_weight(components, models_present):
            items.append(_readiness_item(tier_id, label, "ready", "", None))
            continue
        ensurable = _missing_tier_assets(components, models_present)
        blocked = _missing_weights_phrase(ensurable)
        if offline:
            items.append(
                _readiness_item(tier_id, label, "unavailable", f"{blocked} (Offline mode blocks downloads)", None)
            )
        elif not ensurable:
            items.append(_readiness_item(tier_id, label, "unavailable", blocked, None))
        else:
            action = {"kind": "assets.ensure", "assets": ensurable}
            items.append(_readiness_item(tier_id, label, "needsDownload", blocked, action))
    return items


def _function_readiness_items(settings: dict[str, Any], providers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Roll each AI function's CLOUD route up to a key/consent readiness item.

    A function routed to LOCAL (or unrouted -> local-safe default) is ``ready``.
    A cloud-routed one is ``needsKey`` (no key for the provider), else
    ``needsConsent`` (key present but the data-type consent is not granted), else
    ``ready``. Vision checks FRAME consent; every other function checks TEXT.
    """
    from ..models import catalog  # local: import-light, data only
    from ..models import consent as _consent  # local: import-light pure gate

    routing = settings.get("routing")
    per_function = routing.get("perFunction") if isinstance(routing, dict) else None
    per_function = per_function if isinstance(per_function, dict) else {}

    items: list[dict[str, Any]] = []
    for function in _READINESS_FUNCTIONS:
        cap = f"ai.{function}"
        label = f"AI: {function}"
        provider_id = _routed_cloud_provider(per_function.get(function))
        if provider_id is None:
            items.append(_readiness_item(cap, label, "ready", "", None))
            continue
        if not _provider_has_key(provider_id, providers):
            action = {"kind": "openProviders", "provider": provider_id}
            items.append(_readiness_item(cap, label, "needsKey", f"no key for provider {provider_id!r}", action))
            continue
        consent_id = catalog.provider_label_for_id(provider_id) or provider_id
        granted = (
            _consent.frame_consent_granted(settings, consent_id)
            if function == "vision"
            else _consent.text_consent_granted(settings, consent_id)
        )
        if not granted:
            action = {"kind": "setConsent", "provider": provider_id}
            items.append(
                _readiness_item(cap, label, "needsConsent", f"consent not granted for {provider_id!r}", action)
            )
            continue
        items.append(_readiness_item(cap, label, "ready", "", None))
    return items


def _routed_cloud_provider(slot: Any) -> str | None:
    """The CLOUD provider id a routing slot points at, or None for local/unrouted.

    Returns ``None`` when the slot is absent, malformed, unset, or the LOCAL
    sentinel (those all run locally — no key/consent needed); otherwise the
    configured cloud provider id.
    """
    if not isinstance(slot, dict):
        return None
    provider_id = slot.get("provider")
    if not isinstance(provider_id, str) or not provider_id or provider_id == _LOCAL_ROUTE:
        return None
    return provider_id


def _provider_has_key(provider_id: str, providers: list[dict[str, Any]]) -> bool:
    """True when a configured provider matching ``provider_id`` carries a key.

    Matches on either the entry ``provider`` field or its ``id`` (the routing id
    may be a friendly id or the canonical provider name). Reads the REDACTED
    ``providers.list`` view, so it only ever sees key PRESENCE (last-4), never a
    full key.
    """
    from ..models import catalog  # local: import-light, data only

    wanted = {provider_id}
    label = catalog.provider_label_for_id(provider_id)
    if label:
        wanted.add(label)
    for entry in providers:
        if not isinstance(entry, dict):
            continue  # pragma: no cover - providers.list yields dicts only
        ident = {str(entry.get("provider") or ""), str(entry.get("id") or "")}
        if wanted & ident:
            keys = entry.get("apiKeys")
            if isinstance(keys, list) and any(keys):
                return True
    return False


def _readiness_item(
    capability: str, label: str, status: str, blocked_by: str, action: dict[str, Any] | None
) -> dict[str, Any]:
    """Build one wire :class:`ReadinessItem` dict (camelCase, JSON-safe)."""
    return {
        "capability": capability,
        "label": label,
        "status": status,
        "blockedBy": blocked_by,
        "action": action,
    }


def _advisor_report_to_wire(report: Any) -> dict[str, Any]:
    """Convert an :class:`AdvisorReport` frozen tree to the camelCase wire dict.

    Mirrors the renderer's ``AdvisorReport`` TS type (components/tiers/
    recommendedPreset/vramBudgetMb/notes), so the panel maps it 1:1 without a
    snake_case shim.
    """
    return {
        "components": [
            {
                "name": c.name,
                "present": c.present,
                "verdict": c.verdict,
                "vramMb": c.vram_mb,
                "licenseCommercialOk": c.license_commercial_ok,
                "reason": c.reason,
            }
            for c in report.components
        ],
        "tiers": [
            {"tier": t.tier, "label": t.label, "verdict": t.verdict, "components": list(t.components)}
            for t in report.tiers
        ],
        "recommendedPreset": report.recommended_preset,
        "vramBudgetMb": report.vram_budget_mb,
        "notes": list(report.notes),
    }


def _self_test_report_to_wire(report: Any) -> dict[str, Any]:
    """Convert a :class:`self_test.SelfTestReport` to the camelCase wire dict.

    Mirrors the renderer's ``SelfTestReport`` TS type (ok / checks[id,label,ok,
    required,detail,fixHint] / problems), so the setup-status panel maps it 1:1.
    """
    return {
        "ok": report.ok,
        "checks": [
            {
                "id": c.id,
                "label": c.label,
                "ok": c.ok,
                "required": c.required,
                "detail": c.detail,
                "fixHint": c.fix_hint,
            }
            for c in report.checks
        ],
        "problems": list(report.problems),
    }


def _run_phase8_signals(  # pragma: no cover - heavy Wave-1 signal compute (torch/cv2/transformers); tests inject a fake runner
    media_path: str,
    *,
    tier: int,
    settings: dict[str, Any],
    duration_probe: Callable[[str], float],
    on_progress: Callable[[float, str], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Run the enabled Wave-1 signal modules for ``media_path`` at ``tier``.

    The real (heavy) signal-compute path: motion always (Tier-0 floor), plus the
    Tier-1 visual/audio model tracks. Each module degrades to ``present=False``
    when its weights are missing offline (the §-signal rule), so this returns a
    partial map on any machine. Excluded from coverage — it imports the heavy ML
    backends; the pure shaping (:func:`_signals_summary`) and the select wiring are
    covered with an injected fake runner.
    """
    from ..features import (  # noqa: PLC0415 - lazy heavy seam
        audio_saliency as _audio_saliency,
    )
    from ..features import (
        motion as _motion,
    )

    duration = duration_probe(media_path)
    tracks: dict[str, Any] = {}
    # motion / saliency / scene_transnet each return a SINGLE SignalTrack (keyed by
    # its ``.channel``); audio_saliency / vlm_backbone return a dict[channel,track].
    motion_track = _motion.compute_motion_signals(media_path, duration, settings=settings)
    tracks[motion_track.channel] = motion_track
    if tier >= 1:
        from ..features import saliency as _saliency  # noqa: PLC0415
        from ..features import scene_transnet as _scene_transnet  # noqa: PLC0415
        from ..features import vlm_backbone as _vlm_backbone  # noqa: PLC0415

        tracks.update(_audio_saliency.compute_audio_signals(media_path, duration, settings=settings))
        sal = _saliency.compute_saliency_signals(media_path, duration, settings=settings)
        tracks[sal.channel] = sal
        scene = _scene_transnet.compute_scene_signals(media_path, duration, settings=settings)
        tracks[scene.channel] = scene
        tracks.update(_vlm_backbone.compute_backbone_signals(media_path, duration, settings=settings))
    if on_progress is not None:
        on_progress(100.0, "signals done")
    _ = should_cancel
    return tracks


# --------------------------------------------------------------------------- #
# registration
# --------------------------------------------------------------------------- #
