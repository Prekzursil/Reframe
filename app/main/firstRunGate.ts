// firstRunGate.ts — pure decision helpers for the packaged first-run gate.
//
// WIRING-T5 §2 hardening (first-run provisioning) + WU C3 (CORE-ONLY marker).
// The Electron supervisor must decide, per packaged launch, whether to run
// stage-2 bootstrap.py. The honest signal is the FIRST-RUN-COMPLETE marker
// bootstrap.py writes at the DATA ROOT only after the CORE-ONLY provision — env
// + bundled ffmpeg + the always-on face/ASD weights (the YuNet subject tracker
// and the S3FD / LR-ASD active-speaker weights) — succeeds. It is NOT "env +
// every model + weights": the on-demand assets (the Whisper/Qwen GGUFs, TTS
// voices, ViNet-S saliency, TransNetV2 scene-cut) live OUTSIDE the marker and are
// fetched at point-of-use, so a Minimum/Custom install that skips them opens
// PROVISIONED (no re-bootstrap loop, never perpetually "un-provisioned") — while
// a missing CORE face/ASD weight still (correctly) leaves no marker so the next
// launch retries instead of silently centre-cropping. The marker is still the
// honest signal — distinct from the per-env sentinel (`.media-studio-env.json`),
// which only means "the pip env installed".
//
// This name MUST stay in sync with bootstrap.py FIRST_RUN_COMPLETE_MARKER
// (firstRunGate.test.ts asserts they match by reading bootstrap.py).
export const FIRST_RUN_COMPLETE_MARKER = '.first-run-complete.json';

// The CORE-ONLY asset set the marker attests: the always-on face/ASD weights
// that make the reframe engine track a real subject instead of silently
// centre-cropping. MUST stay in sync with bootstrap.py `core_first_run_assets()`
// (manifest YUNET/LIGHTASD_S3FD/LIGHTASD_ASD asset names; the test asserts the
// bootstrap CORE set references those and excludes the GGUFs). Everything else a
// first run may pull is ON-DEMAND and lives OUTSIDE this set.
export const CORE_FIRST_RUN_ASSETS: readonly string[] = [
  'yunet-face-detection',
  'lightasd-s3fd',
  'lightasd-asd',
];

/** Point-of-use readiness for one first-run asset. */
export interface FirstRunAssetReadiness {
  readonly asset: string;
  /** true when the asset's bytes are present on disk. */
  readonly present: boolean;
  /**
   * `core` assets gate the FIRST_RUN_COMPLETE marker (the no-silent-centre-crop
   * floor); `on-demand` assets NEVER do — they are fetched at point-of-use.
   */
  readonly kind: 'core' | 'on-demand';
  /** `ready` when present; `needs-download` when missing (never "setup incomplete"). */
  readonly status: 'ready' | 'needs-download';
}

/** Whether `asset` is one of the CORE always-on face/ASD weights. */
export function isCoreFirstRunAsset(asset: string): boolean {
  return CORE_FIRST_RUN_ASSETS.includes(asset);
}

/**
 * Point-of-use readiness rollup: classify each first-run asset as core vs
 * on-demand and ready vs needs-download, given the set present on disk. A
 * MISSING on-demand asset is a `needs-download` item (a one-button fetch at its
 * feature) — never a "setup incomplete" that would re-run bootstrap.
 */
export function firstRunReadinessRollup(
  assets: readonly string[],
  presentAssets: readonly string[],
): FirstRunAssetReadiness[] {
  const present = new Set(presentAssets);
  return assets.map((asset) => {
    const isPresent = present.has(asset);
    return {
      asset,
      present: isPresent,
      kind: isCoreFirstRunAsset(asset) ? 'core' : 'on-demand',
      status: isPresent ? 'ready' : 'needs-download',
    };
  });
}

/**
 * Per-profile completion signal (WU C3): a profile's first run is COMPLETE once
 * the pip env is built AND every CORE face/ASD weight that profile pledged to
 * install is present — regardless of on-demand extras. This mirrors bootstrap.py
 * gating the marker on `verify_provisioned(core_subset)`:
 *
 *   - Minimum/Custom that pledges NO core weight (`requiredCoreAssets` empty) is
 *     complete the moment the env exists — it never loops bootstrap, and its
 *     absent weights surface as `needs-download`, not "setup incomplete".
 *   - Default/Full pledges all three face/ASD weights, so all must be present.
 *
 * `requiredCoreAssets` is the profile's resolved asset set intersected with
 * CORE_FIRST_RUN_ASSETS (non-core names are ignored — they never gate).
 */
export function isProfileFirstRunComplete(
  envReady: boolean,
  presentAssets: readonly string[],
  requiredCoreAssets: readonly string[],
): boolean {
  if (!envReady) {
    return false;
  }
  const present = new Set(presentAssets);
  return requiredCoreAssets
    .filter(isCoreFirstRunAsset)
    .every((asset) => present.has(asset));
}

/**
 * True when packaged AND the full first run has NOT completed yet — the only
 * time stage-2 bootstrap.py must run. An existing (pre-marker) install missing
 * the marker re-runs bootstrap, which is idempotent (pip re-checks satisfied,
 * ensure_assets skips downloaded assets) and back-fills anything newly added.
 */
export function needsFirstRunSetup(isPackaged: boolean, completeMarkerExists: boolean): boolean {
  return isPackaged && !completeMarkerExists;
}

/**
 * After a FAILED first-run bootstrap, whether to still start the sidecar.
 *
 * If a prior env sentinel exists this was a RE-PROVISION (e.g. an upgrade
 * back-filling new deps) of an already-working install — start it DEGRADED
 * rather than brick a previously-working app over a transient download failure;
 * the loud bootstrap-error banner already told the user what to fix. A truly
 * empty first run (no env) has nothing to start, so it stays down + loud.
 */
export function shouldStartSidecarAfterFailedFirstRun(envSentinelExists: boolean): boolean {
  return envSentinelExists;
}
