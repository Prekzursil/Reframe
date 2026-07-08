"""Device-aware auto-recommender (WU-B1, resolves gap G-B1).

A **pure**, side-effect-free function that turns the EXISTING advisor output into
an actionable plan. No probe, no GPU, no socket, no network — every input is a
plain dict / list (the wire shapes the WU-B2 handler forwards from the existing
probe / advisor / detect / asr seams):

* ``report``         — the advisor wire dict (``recommendedPreset`` + ``components``)
* ``present``        — the installed-state map (``{component: bool}``)
* ``detected_local`` — the detected local-server pool entries (``[PoolEntry]``)
* ``asr_engines``    — the ASR engine list (``{"engines": [{id,label,installed}]}``)

It composes (never invents): the advisor's recommended preset + installed-state +
detected local servers into a :data:`Recommendation`::

    {
        "preset": "<routing-preset>",
        "routing": {"perFunction": {fn: {"provider": <id|LOCAL>, ...}}},
        "asrEngine": "<engine-id>" | None,
        "downloads": [{"assetName", "label", "sizeMb", "reason"}],
        "rationale": [str, ...],
    }

The concrete per-function routing is resolved through the EXISTING pure
:mod:`media_studio.models.presets` seam (``apply_preset`` over an injected, equally
pure ``CatalogAdapter``) so this module hard-depends on nothing networked. Detected
local servers are then folded over that base routing (route what they can serve to
the user's running server, before ever proposing a download). Offline mode drops
every download-requiring + cloud proposal — the local floor always survives.
"""

from __future__ import annotations

from typing import Any, TypedDict

from ..models import presets as _presets

# --------------------------------------------------------------------------- #
# Typed result shape
# --------------------------------------------------------------------------- #


class DownloadItem(TypedDict):
    """One proposed (never auto-triggered) asset download."""

    assetName: str
    label: str
    sizeMb: float
    reason: str


class RoutingSlot(TypedDict, total=False):
    """One function's resolved routing slot (``provider`` + optional ``fallback``)."""

    provider: str
    fallback: list[str]


class Routing(TypedDict):
    """The per-function routing map (mirrors ``providers.applyPreset`` output)."""

    perFunction: dict[str, RoutingSlot]


class Recommendation(TypedDict):
    """The full actionable plan returned by :func:`recommend`."""

    preset: str
    routing: Routing
    asrEngine: str | None
    downloads: list[DownloadItem]
    rationale: list[str]


# --------------------------------------------------------------------------- #
# Static maps (pure data; mirror the handler's _COMPONENT_ASSETS registrations)
# --------------------------------------------------------------------------- #

#: Advisor component name -> its pinned asset name (the download the UI proposes).
#: Components absent here (numeric-floor: motion/diversity/ranker) never download.
#: Mirrors ``handlers._COMPONENT_ASSETS`` — kept local so this stays import-light.
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

#: Components whose model is a vision/multimodal one — a detected local server only
#: "covers" these when it advertises the ``"vision"`` capability.
_VISION_COMPONENTS: frozenset[str] = frozenset(
    {"saliency", "scene_transnet", "vlm_backbone", "aesthetic", "quality_gate", "emotion", "ocr", "smolvlm2"}
)

#: A component verdict is "runnable" (and so download-worthy when missing) unless
#: the advisor marked it ``unavailable``.
_NOT_RUNNABLE: str = "unavailable"

#: Advisor tier-preset id -> the function-routing preset the recommender emits.
_TIER_TO_ROUTING_PRESET: dict[str, str] = {
    "tier0-numeric": "privacy",
    "tier1-multimodal": "balanced",
    "tier2-vlm": "bestFreeCloud",
}

#: The local-safe fallback preset when the report names nothing recognisable.
_FALLBACK_PRESET: str = "privacy"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _normalise_preset(raw: str) -> str:
    """Map the report's ``recommendedPreset`` to a known function-routing preset.

    A direct routing-preset name (``privacy``/``balanced``/``bestFreeCloud``) is
    kept; an advisor tier id is translated; anything else falls back to the
    local-safe ``privacy`` floor.
    """
    if raw in _presets.PRESETS:
        return raw
    return _TIER_TO_ROUTING_PRESET.get(raw, _FALLBACK_PRESET)


def _server_capability(entry: dict[str, Any]) -> str:
    """Return what a detected local server can serve: ``"vision"`` or ``"text"``.

    A server advertising the ``"vision"`` capability covers both vision and text
    functions; otherwise it covers text only.
    """
    caps = entry.get("capabilities") or []
    return "vision" if "vision" in caps else "text"


def _capture_local_servers(
    per_function: dict[str, RoutingSlot],
    detected_local: list[dict[str, Any]],
    rationale: list[str],
) -> None:
    """Route functions to a detected local server in-place (best server wins).

    A text-only server captures every NON-vision function; a vision-capable server
    additionally captures the vision function. Mutates ``per_function`` and appends
    one rationale line per captured server.
    """
    for entry in detected_local:
        server_id = str(entry.get("id") or entry.get("kind") or _presets.LOCAL)
        serves_vision = _server_capability(entry) == "vision"
        captured: list[str] = []
        for function, slot in per_function.items():
            is_vision = function in _presets._VISION_FUNCTIONS
            if is_vision and not serves_vision:
                continue
            slot["provider"] = server_id
            slot["fallback"] = [_presets.LOCAL]
            captured.append(function)
        if captured:
            rationale.append(
                f"Detected local server '{server_id}' — routing {', '.join(captured)} to it (no cloud egress)."
            )


def _force_local_routes(per_function: dict[str, RoutingSlot], rationale: list[str]) -> None:
    """Rewrite every non-local routing slot to the LOCAL backstop (offline mode).

    Offline mode cannot reach a cloud provider, so any cloud route the preset
    resolved is downgraded to the always-available local backstop in-place. Adds a
    single rationale line only when something was actually rewritten.
    """
    rewritten = False
    for slot in per_function.values():
        if slot.get("provider") != _presets.LOCAL:
            slot["provider"] = _presets.LOCAL
            slot["fallback"] = []
            rewritten = True
    if rewritten:
        rationale.append("Offline mode is on — cloud routes are downgraded to the local backstop.")


def _download_for(component: str, entry: Any, reason: str) -> DownloadItem:
    """Build one :class:`DownloadItem` for ``component`` from its manifest ``entry``.

    The caller (:func:`_derive_downloads`) has already resolved + validated a
    manifest-KNOWN ``entry`` (B1: a de-registered asset is never proposed), so the
    label/size come straight off the registered entry. A blank manifest label
    falls back to the asset name so the proposal always renders.
    """
    asset_name = _COMPONENT_ASSETS[component]
    return DownloadItem(
        assetName=asset_name,
        label=entry.label or asset_name,
        sizeMb=entry.size_mb,
        reason=reason,
    )


def _is_missing(component: str, present: dict[str, Any]) -> bool:
    """True iff ``component`` is not recorded as installed (absent == missing)."""
    return not present.get(component, False)


def _component_covered_by_servers(component: str, detected_local: list[dict[str, Any]]) -> bool:
    """True iff some detected local server can serve ``component``'s model.

    A vision component needs a vision-capable server; a non-vision component is
    covered by any detected server.
    """
    needs_vision = component in _VISION_COMPONENTS
    return any(not needs_vision or _server_capability(entry) == "vision" for entry in detected_local)


def _derive_downloads(
    components: list[Any],
    present: dict[str, Any],
    detected_local: list[dict[str, Any]],
    *,
    offline: bool,
    rationale: list[str],
) -> list[DownloadItem]:
    """Propose downloads for runnable-but-missing components not already covered.

    Offline mode proposes nothing (a download is impossible). A component is a
    candidate only when it has an asset mapping, the advisor deems it runnable,
    it is not installed, no detected local server already serves it, AND its mapped
    asset is still MANIFEST-KNOWN (B1: a de-registered asset is never proposed —
    emitting its name would trip the manager's "unknown asset(s)" gate).
    """
    from ..assets import manifest as _manifest  # local: import-light, data only

    if offline:
        rationale.append("Offline mode is on — no downloads are proposed (the local floor still runs).")
        return []
    downloads: list[DownloadItem] = []
    for comp in components:
        if not isinstance(comp, dict):
            continue
        name = comp.get("name")
        if not isinstance(name, str) or name not in _COMPONENT_ASSETS:
            continue
        if comp.get("verdict") == _NOT_RUNNABLE:
            continue
        if not _is_missing(name, present):
            continue
        if _component_covered_by_servers(name, detected_local):
            continue
        entry = _manifest.get_asset(_COMPONENT_ASSETS[name])
        if entry is None:
            continue  # de-registered asset: never propose an un-ensurable download
        downloads.append(
            _download_for(name, entry, f"{name} is runnable on this device but its weights are not installed.")
        )
    return downloads


def _pick_asr_engine(asr_engines: dict[str, Any], rationale: list[str]) -> str | None:
    """Pick the best installed ASR engine (last installed wins; else None).

    The engine list is ordered by the ``asr.engines`` seam as the always-on
    whisper default first, then opt-in alternatives (e.g. multilingual parakeet).
    Those alternatives are preferred when installed, so the LAST installed entry is
    the recommended pick. Returns ``None`` when nothing is installed.
    """
    picked: str | None = None
    for engine in asr_engines.get("engines", []):
        if engine.get("installed"):
            picked = str(engine.get("id"))
    if picked is None:
        rationale.append("No ASR engine weights are installed — transcription needs a download first.")
        return None
    rationale.append(f"ASR engine '{picked}' is installed — using it for transcription.")
    return picked


def _unavailable(asr_engines: dict[str, Any]) -> Recommendation:
    """The G-B1 fallback: a typed 'could not detect' recommendation (no crash)."""
    rationale = ["Could not detect this device's capabilities — no recommendation available yet."]
    asr_engine = _pick_asr_engine(asr_engines, rationale)
    return Recommendation(
        preset=_FALLBACK_PRESET,
        routing=Routing(perFunction={}),
        asrEngine=asr_engine,
        downloads=[],
        rationale=rationale,
    )


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #


def recommend(
    report: dict[str, Any],
    present: dict[str, Any],
    detected_local: list[dict[str, Any]],
    asr_engines: dict[str, Any],
    *,
    offline: bool,
    commercial: bool = False,
    catalog: _presets.CatalogLike | None = None,
) -> Recommendation:
    """Compose the advisor output into an actionable :class:`Recommendation` (pure).

    See the module docstring for input shapes. ``offline=True`` drops all
    download-requiring + cloud proposals; ``commercial`` is surfaced in the
    rationale (the advisor already filtered commercial-blocked components upstream,
    reflected in ``report``/``present``). A malformed / empty ``report`` (missing
    ``recommendedPreset``) yields the G-B1 'unavailable' recommendation — never an
    exception.
    """
    if not isinstance(report, dict) or "recommendedPreset" not in report:
        return _unavailable(asr_engines)

    preset = _normalise_preset(str(report["recommendedPreset"]))
    rationale: list[str] = [f"Recommended preset '{preset}' based on this device's advisor report."]
    if commercial:
        rationale.append("Commercial build — license-restricted components are excluded by the advisor.")

    resolved = _presets.apply_preset(preset, {}, catalog or _presets.CatalogAdapter())
    per_function: dict[str, RoutingSlot] = resolved["perFunction"]
    if offline:
        _force_local_routes(per_function, rationale)
    _capture_local_servers(per_function, detected_local, rationale)

    components = report.get("components") or []
    downloads = _derive_downloads(
        components,
        present,
        detected_local,
        offline=offline,
        rationale=rationale,
    )
    asr_engine = _pick_asr_engine(asr_engines, rationale)

    return Recommendation(
        preset=preset,
        routing=Routing(perFunction=per_function),
        asrEngine=asr_engine,
        downloads=downloads,
        rationale=rationale,
    )
