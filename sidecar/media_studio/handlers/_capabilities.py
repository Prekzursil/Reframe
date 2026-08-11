"""WU C2 — capability-per-profile matrix + reframe INVARIANT (thin mapping layer).

Reconciles over the EXISTING readiness infra (the ``_wire`` readiness-item builder
+ the manifest installer PROFILES): maps each user-facing FEATURE to the assets it
needs, then derives a per-feature readiness state — the point-of-use "Needs
download -> [button]" surface — from either the live installed-asset set (appended
to ``readiness.summary``) or a hypothetical install PROFILE
(:func:`profile_capability_matrix`). It introduces NO new wire type, RPC, or UI
framework: the items are ordinary :class:`ReadinessItem` dicts the existing
``ReadinessRollup``/``ReadinessBadge`` already render.

REFRAME INVARIANT (R3): the tiny always-on YuNet subject tracker
(``yunet-face-detection`` — a CORE weight) satisfies "no silent centre-crop" on its
OWN. The on-demand ViNet-S saliency model (``vinet-s-saliency``) is a crop-QUALITY
enhancement, NEVER a reframe prerequisite. So the ``reframe`` capability is READY
the moment the tracker is present — INDEPENDENT of saliency — and a missing
saliency model surfaces as a SEPARATE, LOUD "download saliency to improve" item,
never a silent quality degrade and never marking reframe itself unavailable. A
Minimum install is therefore one tiny tracker download away from honest
subject-tracked reframing (the "honestly usable, never silently degraded" contract).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from ._wire import _readiness_item

#: The reframe subject tracker (YuNet ONNX, CORE tier) — the crop-driver that makes
#: "no silent centre-crop" true on its own (see reframe_claudeshorts.py).
TRACKER_ASSET = "yunet-face-detection"
#: The on-demand ViNet-S saliency weight (a crop-QUALITY enhancement, never a
#: reframe prerequisite). De-registered until B4 re-hosts + pins it.
SALIENCY_ASSET = "vinet-s-saliency"
#: The on-demand TransNetV2 scene-cut weight (de-registered until B4).
SCENE_ASSET = "transnetv2-pytorch"
#: The isolated LatentSync/MuseTalk re-lip environment ``tts.lipsync.start`` runs in.
#: A plain literal (like the three above) rather than an import, so this data-only
#: module stays import-light — ``test_handlers_capabilities`` asserts it equals
#: ``features.tts.lipsync.LIPSYNC_ENV_ASSET``, so the two cannot drift apart.
LIPSYNC_ENV_ASSET = "latentsync-env"


@dataclass(frozen=True)
class FeatureSpec:
    """One user-facing feature -> the assets it needs + its point-of-use copy.

    ``blocked_phrase`` is the LOUD plain-language reason shown when the feature is
    not ready (the reframe invariant lives in this copy). ``core`` marks a feature
    whose readiness must NEVER depend on an on-demand enhancement (reframe's
    no-silent-centre-crop floor); it is documentation of intent, not a code branch.
    """

    capability: str
    label: str
    assets: tuple[str, ...]
    blocked_phrase: str
    core: bool


#: The thin feature -> asset mapping. ``reframe`` (core) needs ONLY the tracker;
#: ``reframe.saliency`` is the SEPARATE enhancement that carries the loud
#: "download saliency to improve" notice — the two are deliberately split so a
#: missing saliency model can never silently degrade (or block) reframe.
_FEATURE_CAPABILITIES: tuple[FeatureSpec, ...] = (
    FeatureSpec(
        capability="reframe",
        label="Reframe - vertical subject tracking",
        assets=(TRACKER_ASSET,),
        blocked_phrase="download the subject tracker to reframe with real speaker tracking (no centre-crop)",
        core=True,
    ),
    FeatureSpec(
        capability="reframe.saliency",
        label="Reframe - saliency (better crop)",
        assets=(SALIENCY_ASSET,),
        blocked_phrase="download saliency to improve the reframe crop - subject tracking already works without it",
        core=False,
    ),
    FeatureSpec(
        capability="scene.detect",
        label="Scene-cut detection",
        assets=(SCENE_ASSET,),
        blocked_phrase="download the scene-cut model to enable automatic scene detection",
        core=False,
    ),
    # ``tts.lipsync.start`` is registered UNCONDITIONALLY (see features/tts/__init__.py:23-28)
    # and cannot succeed in any stock build, so without a row here the app offered a
    # Re-lip button with no up-front warning at all. The capability name matches the
    # job registry's ``feature="lipsync"`` tag (lipsync.py:717) so the readiness row
    # and the job that fails are the same feature.
    #
    # The blocker named here is the one that is UNFIXABLE from the app: the re-lip
    # env has no manifest entry, so ``assets.ensure`` cannot install it and no
    # install PROFILE can supply it. (The face-box probe is a second, independent
    # gate — wiring it would move the refusal here rather than remove it, which is
    # why this row, not a probe, is the honest surface today.) Provisioning the env
    # needs pinned torch/diffusers versions from a live resolve plus a hashed lock
    # and an accepted OpenRAIL licence — lipsync.py:283-294 records why inventing
    # those pins would put a lie in the manifest.
    FeatureSpec(
        capability="lipsync",
        label="Lip-sync - re-lip a dub to the on-screen mouth",
        assets=(LIPSYNC_ENV_ASSET,),
        blocked_phrase=(
            "lip-sync is not available in this build: the re-lip engine environment is not "
            "provisioned, so every re-lip request refuses"
        ),
        core=False,
    ),
)


def capability_asset_names() -> list[str]:
    """The de-duplicated capability asset names, in first-seen order.

    The single probe set ``readiness.summary`` resolves installed-state for (the
    :meth:`Services._installed_asset_names` seam).
    """
    seen: dict[str, None] = {}
    for spec in _FEATURE_CAPABILITIES:
        for name in spec.assets:
            seen.setdefault(name, None)
    return list(seen)


def _ensurable_missing(spec: FeatureSpec, installed: set[str]) -> list[str]:
    """The de-duplicated, ENSURABLE (manifest-known) assets ``spec`` still needs.

    A de-registered asset (``manifest.get_asset`` is None) is dropped — emitting it
    in an ``assets.ensure`` action would trip the manager's "unknown asset(s)" gate
    (B1). Only manifest-known targets are ever offered as a download button.
    """
    from ..assets import manifest as _manifest  # local: import-light, data only

    # A not-installed asset is ensurable only when the manifest still knows it; a
    # de-registered name is dropped so it never reaches an ``assets.ensure`` action.
    return [name for name in spec.assets if name not in installed and _manifest.get_asset(name) is not None]


def _feature_item(spec: FeatureSpec, installed: set[str], *, offline: bool) -> dict[str, object]:
    """Roll one feature up to a :class:`ReadinessItem` from the installed set.

    ``ready`` when every required weight is installed; ``needsDownload`` (with a
    one-button ``assets.ensure`` action over the missing manifest-KNOWN assets) when
    a weight is missing online AND at least one is ensurable; ``unavailable`` when
    none of the missing weights map to a registered asset yet OR Offline mode blocks
    an otherwise-downloadable one (loud, never a silent drop and never an
    unknown-asset name). Mirrors ``_tier_readiness_items``.

    REASON PRECEDENCE — "not registered" OUTRANKS "offline". Both produce
    ``unavailable``, so only the note differs, but the note is the part the user
    acts on: telling someone Offline mode blocks a weight that is not registered at
    all sends them to a setting that cannot help, and it silently becomes a lie the
    moment they go online. The unregistered case is checked FIRST so the reason
    given is the one that is actually true; the Offline note is narrowed to the case
    where a real, ensurable asset exists and only connectivity is in the way.
    """
    if all(name in installed for name in spec.assets):
        return _readiness_item(spec.capability, spec.label, "ready", "", None)
    ensurable = _ensurable_missing(spec, installed)
    if not ensurable:
        blocked = f"{spec.blocked_phrase} (not yet available for download)"
        return _readiness_item(spec.capability, spec.label, "unavailable", blocked, None)
    if offline:
        blocked = f"{spec.blocked_phrase} (Offline mode blocks downloads)"
        return _readiness_item(spec.capability, spec.label, "unavailable", blocked, None)
    action = {"kind": "assets.ensure", "assets": ensurable}
    return _readiness_item(spec.capability, spec.label, "needsDownload", spec.blocked_phrase, action)


def feature_readiness_items(installed: Iterable[str], *, offline: bool) -> list[dict[str, object]]:
    """The per-feature :class:`ReadinessItem` list for the live installed-asset set.

    Appended to ``readiness.summary`` so each feature's point-of-use
    "Needs download -> [button]" state rides the SAME roll-up the existing
    ``ReadinessRollup`` renders (no parallel readiness system).
    """
    inst = set(installed)
    return [_feature_item(spec, inst, offline=offline) for spec in _FEATURE_CAPABILITIES]


def profile_capability_matrix(profile: str, custom: Iterable[str] | None = None) -> dict[str, str]:
    """Map each feature -> its readiness STATUS for a hypothetical install PROFILE.

    The per-PROFILE view (WU C2's namesake): resolves the assets a profile installs
    (:func:`manifest.resolve_profile`) and derives each feature's status as if that
    profile were freshly installed online. Encodes the reframe invariant at the
    profile level — Default (core tier) makes ``reframe`` ``ready`` via the tracker
    alone, while saliency/scene stay downloads (never bundled into core). An unknown
    profile raises ``ValueError`` (fail loud — no silent empty fallback).
    """
    from ..assets import manifest as _manifest  # local: import-light, data only

    installed = set(_manifest.resolve_profile(profile, list(custom) if custom is not None else None))
    return {
        spec.capability: str(_feature_item(spec, installed, offline=False)["status"]) for spec in _FEATURE_CAPABILITIES
    }
