"""WU C2 — capability-per-profile matrix + reframe INVARIANT tests.

The thin ``feature -> asset`` mapping layer (``handlers._capabilities``) reconciles
over the EXISTING readiness infra (``_wire`` readiness-item builders + the manifest
installer PROFILES) — it invents NO new wire type, RPC, or UI framework. Two
surfaces are pinned here:

  * ``profile_capability_matrix(profile)`` — the per-PROFILE view: for a
    hypothetical install profile, which features are ``ready`` vs need a download.
  * ``feature_readiness_items(installed, offline)`` — the per-INSTALL-state
    point-of-use "Needs download -> [button]" items appended to ``readiness.summary``.

REFRAME INVARIANT (R3): the tiny always-on YuNet subject tracker
(``yunet-face-detection``, a CORE weight) satisfies "no silent centre-crop" on its
OWN. The on-demand ViNet-S saliency model is a crop-QUALITY enhancement, never a
reframe prerequisite. So ``reframe`` is READY the moment the tracker is present —
INDEPENDENT of saliency — and a missing saliency model surfaces as a SEPARATE,
LOUD "download saliency to improve" item, never a silent degrade and never marking
reframe itself unavailable. A Minimum install is one tiny tracker download away
from honest subject-tracked reframing.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from media_studio.handlers import Services
from media_studio.handlers import _capabilities as cap
from media_studio.protocol import RpcContext

_TRACKER = "yunet-face-detection"
_SALIENCY = "vinet-s-saliency"
_SCENE = "transnetv2-pytorch"
#: The isolated re-lip environment ``tts.lipsync.start`` needs. It is NOT a
#: registered manifest asset (measured: ``registry_snapshot()`` holds 11 entries and
#: this is not one of them), so lip-sync can never run in a stock build.
_LIPSYNC_ENV = "latentsync-env"


@pytest.fixture
def ctx() -> RpcContext:
    return RpcContext(emit_notification=lambda obj: None, jobs=None)


def _by_cap(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {item["capability"]: item for item in items}


def _register(monkeypatch: pytest.MonkeyPatch, *names: str) -> None:
    """Pin exactly ``names`` as manifest-KNOWN (ensurable) assets, rest unknown.

    Mirrors the readiness-test convention so a ``needsDownload`` (button) path can
    be exercised even before B4 registers the re-hosted saliency/scene weights.
    """
    from media_studio.assets import manifest as _manifest

    known = set(names)
    monkeypatch.setattr(
        _manifest,
        "get_asset",
        lambda n: SimpleNamespace(label="", size_mb=0) if n in known else None,
    )


# --------------------------------------------------------------------------- #
# reframe INVARIANT — reframe ready WITHOUT saliency; saliency a separate item
# --------------------------------------------------------------------------- #
def test_reframe_ready_without_saliency_and_saliency_is_a_separate_loud_item(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Tracker present, saliency REGISTERED but not installed: reframe is READY
    # (no silent centre-crop, no dependence on saliency); the saliency item is a
    # SEPARATE needsDownload with a LOUD "download saliency to improve" phrase and
    # a one-button assets.ensure action — never marking reframe unavailable.
    _register(monkeypatch, _TRACKER, _SALIENCY, _SCENE)
    items = _by_cap(cap.feature_readiness_items({_TRACKER}, offline=False))

    assert items["reframe"]["status"] == "ready"
    assert items["reframe"]["action"] is None
    assert items["reframe"]["blockedBy"] == ""

    sal = items["reframe.saliency"]
    assert sal["status"] == "needsDownload"
    assert "saliency" in sal["blockedBy"].lower()
    assert "improve" in sal["blockedBy"].lower()
    assert sal["action"] == {"kind": "assets.ensure", "assets": [_SALIENCY]}


def test_reframe_needs_only_the_tracker_download(monkeypatch: pytest.MonkeyPatch) -> None:
    # Nothing installed: reframe needs ONLY the tiny tracker (never saliency) to
    # become usable — the one-button state names just the tracker asset.
    _register(monkeypatch, _TRACKER, _SALIENCY, _SCENE)
    items = _by_cap(cap.feature_readiness_items(set(), offline=False))
    reframe = items["reframe"]
    assert reframe["status"] == "needsDownload"
    assert reframe["action"] == {"kind": "assets.ensure", "assets": [_TRACKER]}
    assert "centre-crop" in reframe["blockedBy"].lower() or "center-crop" in reframe["blockedBy"].lower()


def test_reframe_saliency_deregistered_is_loud_unavailable_not_silent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Saliency asset DE-REGISTERED (pre-B4): the item is LOUD `unavailable` with a
    # "not yet available for download" note (honest), NOT a silent drop and NOT an
    # ``assets.ensure`` emitting an unknown-asset name. Reframe still READY.
    _register(monkeypatch, _TRACKER)  # only the tracker is known
    items = _by_cap(cap.feature_readiness_items({_TRACKER}, offline=False))
    assert items["reframe"]["status"] == "ready"
    sal = items["reframe.saliency"]
    assert sal["status"] == "unavailable"
    assert sal["action"] is None
    assert "saliency" in sal["blockedBy"].lower()
    assert _SALIENCY not in repr(sal)  # never emit the unknown-asset name


# --------------------------------------------------------------------------- #
# per-feature status ladder
# --------------------------------------------------------------------------- #
def test_feature_all_assets_present_is_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    _register(monkeypatch, _TRACKER, _SALIENCY, _SCENE)
    items = _by_cap(cap.feature_readiness_items({_TRACKER, _SALIENCY, _SCENE}, offline=False))
    for feature in ("reframe", "reframe.saliency", "scene.detect"):
        assert items[feature]["status"] == "ready"
        assert items[feature]["action"] is None
        assert items[feature]["blockedBy"] == ""


def test_feature_missing_offline_is_unavailable_no_action(monkeypatch: pytest.MonkeyPatch) -> None:
    # Offline blocks the download: a missing (registered) weight -> unavailable with
    # NO action (the download button would not work offline).
    _register(monkeypatch, _TRACKER, _SALIENCY, _SCENE)
    items = _by_cap(cap.feature_readiness_items(set(), offline=True))
    reframe = items["reframe"]
    assert reframe["status"] == "unavailable"
    assert reframe["action"] is None
    assert "offline" in reframe["blockedBy"].lower()


def test_scene_detect_needs_download_when_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    _register(monkeypatch, _TRACKER, _SCENE)
    items = _by_cap(cap.feature_readiness_items({_TRACKER}, offline=False))
    scene = items["scene.detect"]
    assert scene["status"] == "needsDownload"
    assert scene["action"] == {"kind": "assets.ensure", "assets": [_SCENE]}


# --------------------------------------------------------------------------- #
# capability_asset_names — the de-duplicated probe set
# --------------------------------------------------------------------------- #
def test_capability_asset_names_are_deduped_and_cover_every_feature() -> None:
    names = cap.capability_asset_names()
    assert set(names) == {_TRACKER, _SALIENCY, _SCENE, _LIPSYNC_ENV}
    assert len(names) == len(set(names))  # no duplicates


# --------------------------------------------------------------------------- #
# profile_capability_matrix — the per-PROFILE view
# --------------------------------------------------------------------------- #
def test_matrix_minimum_reframe_is_one_tiny_download(monkeypatch: pytest.MonkeyPatch) -> None:
    # Minimum installs NOTHING: reframe needs only the tracker download; saliency &
    # scene surface as their own not-ready states — never silently missing.
    _register(monkeypatch, _TRACKER, _SALIENCY, _SCENE)
    matrix = cap.profile_capability_matrix("minimum")
    assert matrix["reframe"] == "needsDownload"
    assert matrix["reframe.saliency"] == "needsDownload"
    assert matrix["scene.detect"] == "needsDownload"


def test_matrix_default_reframes_without_saliency(monkeypatch: pytest.MonkeyPatch) -> None:
    # INVARIANT at the profile level: Default (core tier) installs the tracker, so
    # reframe is READY with real subject tracking WITHOUT the on-demand saliency
    # model. Saliency stays a download-to-improve (never bundled into core).
    _register(monkeypatch, _TRACKER, _SALIENCY, _SCENE)
    matrix = cap.profile_capability_matrix("default")
    assert matrix["reframe"] == "ready"
    assert matrix["reframe.saliency"] == "needsDownload"


def test_matrix_deregistered_saliency_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    # With saliency/scene DE-REGISTERED (pre-B4), Default reframes (tracker=core) but
    # saliency/scene are honestly `unavailable` (not yet downloadable), never `ready`.
    _register(monkeypatch, _TRACKER)
    matrix = cap.profile_capability_matrix("default")
    assert matrix["reframe"] == "ready"
    assert matrix["reframe.saliency"] == "unavailable"
    assert matrix["scene.detect"] == "unavailable"


def test_matrix_custom_profile_enables_picked_tracker(monkeypatch: pytest.MonkeyPatch) -> None:
    # A Custom profile that hand-picks the tracker makes reframe ready; unpicked
    # enhancements stay downloads.
    _register(monkeypatch, _TRACKER, _SALIENCY, _SCENE)
    matrix = cap.profile_capability_matrix("custom", custom=[_TRACKER])
    assert matrix["reframe"] == "ready"
    assert matrix["reframe.saliency"] == "needsDownload"


def test_matrix_unknown_profile_raises() -> None:
    with pytest.raises(ValueError, match="profile"):
        cap.profile_capability_matrix("bogus")


# --------------------------------------------------------------------------- #
# lip-sync — the SHIPPED-BUT-DEAD feature is surfaced, not silently offered
# --------------------------------------------------------------------------- #
# ``tts.lipsync.start`` is registered unconditionally and cannot succeed in any
# stock build. Measured at 81a04965, TWO independent gates, either one fatal:
#
#   1. ``require_face_boxes`` (``lipsync.py:239-254``) raises because no caller
#      supplies ``lipsync_face_boxes_probe`` — ``composition.py:344-353`` passes
#      none, and every hop defaults to ``None``.
#   2. EVEN WITH A PROBE WIRED, ``SubprocessLipSyncBackend.relip``
#      (``lipsync.py:456-465``) raises because the ``latentsync-env`` environment
#      has no manifest entry, so ``assets.ensure`` cannot install it.
#
# Gate 2 is why this capability entry exists rather than a probe: wiring YuNet
# would only move the raise from gate 1 to gate 2, leaving the button just as dead
# while looking fixed. Until the env is provisioned the honest surface is a LOUD
# ``unavailable`` the user sees BEFORE spending a click, which is exactly the state
# ``_feature_item`` already produces for an unregistered asset.
def test_lipsync_capability_is_surfaced_at_all(monkeypatch: pytest.MonkeyPatch) -> None:
    # Before this lane there was NO lip-sync entry in the readiness family at all,
    # so the app offered a Re-lip button with zero up-front warning.
    _register(monkeypatch, _TRACKER)
    items = _by_cap(cap.feature_readiness_items({_TRACKER}, offline=False))
    assert "lipsync" in items


def test_lipsync_is_unavailable_because_its_relip_env_is_unprovisioned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The env asset is unregistered -> LOUD `unavailable` with NO download button
    # (an assets.ensure naming an unknown asset would trip the manager's gate), and
    # the copy must say the feature is unavailable in this build.
    _register(monkeypatch, _TRACKER)  # latentsync-env deliberately NOT known
    items = _by_cap(cap.feature_readiness_items({_TRACKER}, offline=False))
    lipsync = items["lipsync"]
    assert lipsync["status"] == "unavailable"
    assert lipsync["action"] is None
    assert "lip-sync" in lipsync["blockedBy"].lower()
    assert "not available in this build" in lipsync["blockedBy"].lower()
    # Never emit the unknown-asset name into the wire payload.
    assert _LIPSYNC_ENV not in repr(lipsync)


def test_lipsync_unavailability_is_never_blamed_on_offline_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # HONESTY: an UNREGISTERED asset is not "blocked by Offline mode" — turning
    # Offline off would not make it downloadable. Blaming offline would send the
    # user to a setting that cannot help. The unregistered reason DOMINATES.
    _register(monkeypatch, _TRACKER)
    items = _by_cap(cap.feature_readiness_items({_TRACKER}, offline=True))
    lipsync = items["lipsync"]
    assert lipsync["status"] == "unavailable"
    assert "offline" not in lipsync["blockedBy"].lower()
    assert "not yet available for download" in lipsync["blockedBy"].lower()


def test_a_deregistered_asset_outranks_offline_for_every_feature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The same precedence bug hit the two pre-B4 de-registered weights: offline was
    # checked FIRST, so a permanently-unavailable feature reported the wrong reason.
    _register(monkeypatch, _TRACKER)  # saliency + scene de-registered
    items = _by_cap(cap.feature_readiness_items({_TRACKER}, offline=True))
    for feature in ("reframe.saliency", "scene.detect"):
        assert items[feature]["status"] == "unavailable"
        assert "offline" not in items[feature]["blockedBy"].lower()
    # ...but a REGISTERED weight that is merely undownloadable right now still
    # correctly blames Offline mode (the branch is narrowed, not deleted).
    _register(monkeypatch, _TRACKER, _SALIENCY)
    offline_items = _by_cap(cap.feature_readiness_items(set(), offline=True))
    assert "offline" in offline_items["reframe.saliency"]["blockedBy"].lower()


def test_lipsync_capability_name_matches_the_job_registry_feature_tag() -> None:
    # The readiness row and the job the user starts must be the SAME feature name,
    # or the rollup explains one thing while another fails.
    from media_studio.features.tts import lipsync as ls

    spec = next(s for s in cap._FEATURE_CAPABILITIES if s.capability == "lipsync")
    assert spec.assets == (ls.LIPSYNC_ENV_ASSET,)
    assert cap.LIPSYNC_ENV_ASSET == ls.LIPSYNC_ENV_ASSET
    assert spec.core is False  # never a core floor — it is an opt-in heavy extra


def test_lipsync_env_really_is_unregistered_so_the_copy_is_true() -> None:
    # The claim "not available in this build" rests on the env being absent from the
    # REAL manifest, so assert it against the real registry (no monkeypatch) with a
    # detector control: a known-present asset must be found by the same probe.
    from media_studio.assets import manifest as _manifest

    snapshot = _manifest.registry_snapshot()
    assert _TRACKER in snapshot  # CONTROL: the probe can find a present asset
    assert _LIPSYNC_ENV not in snapshot
    assert _manifest.get_asset(_LIPSYNC_ENV) is None


def test_matrix_lipsync_is_unavailable_in_every_install_profile() -> None:
    # No profile can install an unregistered env, so lip-sync is unavailable even on
    # the fullest profile — the matrix must never promise it.
    for profile in ("minimum", "default", "full"):
        assert cap.profile_capability_matrix(profile)["lipsync"] == "unavailable"


# --------------------------------------------------------------------------- #
# readiness.summary INTEGRATION — feature items flow through the EXISTING roll-up
# --------------------------------------------------------------------------- #
def _services(tmp_path: Path, *, installed: set[str] | None = None) -> Services:
    svc = Services(data_dir=tmp_path / "data")
    svc._models_present_map = lambda _s: {}  # type: ignore[method-assign]
    present = set(installed or ())
    svc._installed_asset_names = lambda _s: set(present)  # type: ignore[method-assign]
    return svc


def test_readiness_summary_includes_feature_capability_items(
    tmp_path: Path, ctx: RpcContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    _register(monkeypatch, _TRACKER, _SALIENCY, _SCENE)
    svc = _services(tmp_path, installed={_TRACKER})
    items = _by_cap(svc.readiness_summary({}, ctx)["items"])
    # The feature family rides the SAME payload as the tier/function families.
    assert items["reframe"]["status"] == "ready"
    assert items["reframe.saliency"]["status"] == "needsDownload"
    # And the existing tier/function families are still present (no rebuild).
    assert "tier0-numeric" in items
    assert "ai.select" in items


def test_readiness_summary_reframe_needs_tracker_when_nothing_installed(
    tmp_path: Path, ctx: RpcContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    _register(monkeypatch, _TRACKER, _SALIENCY, _SCENE)
    svc = _services(tmp_path, installed=set())
    items = _by_cap(svc.readiness_summary({}, ctx)["items"])
    assert items["reframe"]["status"] == "needsDownload"
    assert items["reframe"]["action"] == {"kind": "assets.ensure", "assets": [_TRACKER]}


def test_installed_asset_names_probes_only_registered_capability_assets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The real seam: a de-registered capability asset is skipped (never probed);
    # a registered-but-not-installed one is reported absent. Read-only: it must NOT
    # create the data dir's models directory.
    _register(monkeypatch, _TRACKER)  # only the tracker is a known asset
    svc = Services(data_dir=tmp_path / "data")
    installed = svc._installed_asset_names({})
    assert installed == set()  # nothing on disk in a fresh data dir
    assert not (svc.data_dir / "models").exists()


def test_installed_asset_names_is_fail_open_on_probe_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # A probe that raises for one asset must NOT sink the whole roll-up: the asset
    # is treated as absent (fail-open), never crashing readiness.summary.
    _register(monkeypatch, _TRACKER)
    from media_studio.assets.manager import AssetManager

    def _boom(self: AssetManager, entry: Any) -> Any:
        raise OSError("probe blew up")

    monkeypatch.setattr(AssetManager, "installed_path", _boom)
    svc = Services(data_dir=tmp_path / "data")
    assert svc._installed_asset_names({}) == set()


def test_installed_asset_names_reports_a_present_registered_asset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A registered asset whose probe returns a real path is reported installed.
    _register(monkeypatch, _TRACKER)  # only the tracker is a known asset
    from media_studio.assets.manager import AssetManager

    monkeypatch.setattr(AssetManager, "installed_path", lambda self, entry: "/some/models/yunet.onnx")
    svc = Services(data_dir=tmp_path / "data")
    assert svc._installed_asset_names({}) == {_TRACKER}
