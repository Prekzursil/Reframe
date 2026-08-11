"""WU C2 — capability-per-profile matrix + reframe INVARIANT (thin mapping layer).

Reconciles over the EXISTING readiness infra (the ``_wire`` readiness-item builder
+ the manifest installer PROFILES): maps each user-facing FEATURE to the assets it
needs, then derives a per-feature readiness state — the point-of-use "Needs
download -> [button]" surface — from either the live installed-asset set (appended
to ``readiness.summary``) or a hypothetical install PROFILE
(:func:`profile_capability_matrix`). It introduces NO new wire type, RPC, or UI
framework: the items are ordinary :class:`ReadinessItem` dicts the existing
``ReadinessRollup``/``ReadinessBadge`` already render.

TWO RENDERER CONSUMERS, NOT ONE — correcting a scope claim that said adding a row
here needs "no renderer edit" full stop. No EDIT is required, but ``readiness
.summary`` is read at ``ReadinessRollup.tsx:77`` (per-row; unaffected by row count)
AND at ``CapabilitiesChip.tsx:49``, which derives a RATIO — ``items.filter(status
=== 'ready').length`` over ``items.length``, rendered as "Capabilities: N of M
installed" (``:64-71``). So every row added here is +1 to that denominator, and a
row that can never be ``ready`` (a de-registered asset, or a ``hard_blocked`` spec)
lowers the displayed ratio permanently, with no install action that can close it.
Measured, so the cost is stated at its real size rather than guessed: the chip
already cannot reach parity — ``reframe.saliency`` and ``scene.detect`` are both
de-registered pre-B4, and ``tier1-multimodal``/``tier2-vlm`` are unavailable on a
cold start — so ``lipsync`` makes an already-unreachable ratio one worse. That is a
disclosed cost of the roll-up, not a reason to hide a dead feature; the alternative
(a feature the rollup stays silent about) is the failure this module exists to fix.

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

    ``hard_blocked`` marks a feature that NO install can make work, because at
    least one of its gates is unfinished WIRING rather than a missing download.
    Such a feature can never be ``ready`` and never offers a download button, so
    ``blocked_phrase`` must be a complete, self-contained sentence (it is emitted
    verbatim, with no "(not yet available…)" / "(Offline…)" suffix — neither is
    the true reason). It exists because modelling a feature as "its assets" alone
    silently assumes the asset is its ONLY gate; where that is false the row would
    flip to ``ready`` the moment someone provisioned the asset, while the feature
    stayed dead. Clearing this flag forces whoever does that to re-read the other
    gates in the same commit.
    """

    capability: str
    label: str
    assets: tuple[str, ...]
    blocked_phrase: str
    core: bool
    hard_blocked: bool = False


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
    # ``tts.lipsync.start`` is registered UNCONDITIONALLY (features/tts/__init__.py:23-28)
    # and cannot succeed in any stock build, yet no row in ``readiness.summary`` — the
    # app's single "what is ready" surface — said so. The capability name matches the
    # job registry's ``feature="lipsync"`` tag (lipsync.py:717) so the readiness row
    # and the job that fails are the same feature.
    #
    # REFUTED, recorded rather than deleted: the wording this row shipped with said
    # the app "offered a Re-lip button, accepted the request, returned a jobId, and
    # only then failed the job", and the phrase below asserted the unprovisioned env
    # is why "every re-lip request refuses". Both are false for a STOCK build, and an
    # executable probe (with a sentinel ``jobs.start`` as the both-states control)
    # settled it: ``lipsync_enabled({})`` is False, so ``require_enabled``
    # (lipsync.py:208-215, called FIRST at :652) refuses SYNCHRONOUSLY with an
    # RpcError naming the flag — ``ctx.jobs.start`` (:717) is never reached and no
    # jobId exists. The control proves the sentinel fires: with ``lipSyncEnabled``
    # forced true the same call DOES reach ``jobs.start``. On the renderer side the
    # control is disabled too (LipSync.tsx:509 ``canStart`` requires
    # ``enabled === true``; ``lipSyncEnabled`` defaults False at settings_store.py:178
    # and LipSync.test.tsx:219 pins that nothing in ``app/`` writes it).
    #
    # So the accept-then-fail path needs a hand-edited settings.json, and THREE gates
    # are live, in this order: the build flag, the unprovisioned env
    # (SubprocessLipSyncBackend.relip, lipsync.py:456-465 — no manifest entry, so
    # ``assets.ensure`` cannot install it and no install PROFILE can supply it), and
    # the unwired face-box probe (require_face_boxes, lipsync.py:239-254, raising
    # inside the job because composition.py passes no ``lipsync_face_boxes_probe``).
    # The phrase names all three, flag first, because naming a blocker other than the
    # one that actually fires is the exact defect the precedence fix below removes.
    # Provisioning the env needs pinned torch/diffusers versions from a live resolve
    # plus a hashed lock and an accepted OpenRAIL licence — lipsync.py:283-294 records
    # why inventing those pins would put a lie in the manifest.
    #
    # ``hard_blocked`` because the probe gate is unfinished WIRING, not a download:
    # without it, provisioning the env alone (the prescribed WU-B1 next step) would
    # flip this row to ``ready`` while every re-lip still raised. Measured before the
    # flag existed: with the env registered AND installed the row returned
    # status='ready', blockedBy='', action=None while ``require_face_boxes(None, …)``
    # still raised.
    FeatureSpec(
        capability="lipsync",
        label="Lip-sync - re-lip a dub to the on-screen mouth",
        assets=(LIPSYNC_ENV_ASSET,),
        blocked_phrase=(
            "lip-sync is off in this build and cannot be switched on from the app; it is also "
            "unfinished - the re-lip engine environment is not provisioned and no face-box "
            "provider is wired, so a re-lip cannot succeed even with the setting forced on"
        ),
        core=False,
        hard_blocked=True,
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

    A ``hard_blocked`` spec short-circuits to ``unavailable`` with its phrase
    verbatim — no install can clear it, so neither the installed set nor Offline
    mode is consulted. Otherwise: ``ready`` when every required weight is
    installed; ``needsDownload`` (with a one-button ``assets.ensure`` action over
    the missing manifest-KNOWN assets) when a weight is missing online AND at least
    one is ensurable; ``unavailable`` when none of the missing weights map to a
    registered asset yet OR Offline mode blocks an otherwise-downloadable one
    (loud, never a silent drop and never an unknown-asset name).

    REASON PRECEDENCE — "not registered" OUTRANKS "offline". Both produce
    ``unavailable``, so only the note differs, but the note is the part the user
    acts on: telling someone Offline mode blocks a weight that is not registered at
    all sends them to a setting that cannot help, and it silently becomes a lie the
    moment they go online. The unregistered case is checked FIRST so the reason
    given is the one that is actually true; the Offline note is narrowed to the case
    where a real, ensurable asset exists and only connectivity is in the way.

    Mirrors ``_tier_readiness_items`` on that precedence — a claim that was FALSE
    for one commit and is restored here, not asserted: the swap landed in this
    function first while ``_wire._tier_readiness_items`` still checked ``offline``
    first, so the two families disagreed inside ONE ``readiness.summary`` payload
    (``library_ops.py:656`` tiers, ``:664`` features). Both now share the order.
    The ``hard_blocked`` short-circuit has no tier counterpart — tiers are pure
    weight sets with no wiring gate — so it is a deliberate, documented divergence.
    """
    if spec.hard_blocked:
        return _readiness_item(spec.capability, spec.label, "unavailable", spec.blocked_phrase, None)
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
