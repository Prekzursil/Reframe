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
import { createHash } from 'node:crypto';
//
// This name MUST stay in sync with bootstrap.py FIRST_RUN_COMPLETE_MARKER
// (firstRunGate.test.ts asserts they match by reading bootstrap.py).
export const FIRST_RUN_COMPLETE_MARKER = '.first-run-complete.json';

// WU-S2 (version-aware re-bootstrap): the persisted requirements FINGERPRINT the
// supervisor writes at the DATA ROOT, next to FIRST_RUN_COMPLETE_MARKER, after a
// successful bootstrap. Comparing it against the CURRENT shipped fingerprint lets
// an auto-update that CHANGED the sidecar env silently re-provision instead of
// starting a stale env against the old pip target. The fingerprint hashes the
// ACTIVE install source — bootstrap.py installs the env from the sibling hashed
// lock (`requirements-sidecar.lock.txt`, `pip --require-hashes`) when it is
// staged, else the loose pins — so a lock-only / transitive bump is caught too
// (WU-S2-FIX; see `hashedLockFilename`). SCOPE: drift detection is the SIDECAR
// env ONLY — the default bootstrap the supervisor spawns builds just that env.
// The isolated chatterbox (torch) env is provisioned on demand at its own
// point-of-use (`bootstrap.py --chatterbox` / a U4 env asset), so its own
// requirements are NOT part of this signal and re-provision there, not here.
// Single-owner by design: the Electron supervisor both computes AND reads this
// fingerprint (TS `crypto`), so there is NO cross-language hash-parity contract
// with bootstrap.py — the marker stays the only cross-file name the test pins.
// blake3 already ships in the lock, so v1.4 changes no dep and this is INSURANCE
// that arms drift-detection for FUTURE bumps.
export const FIRST_RUN_REQUIREMENTS_FINGERPRINT_FILE = '.first-run-requirements.json';

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
  return requiredCoreAssets.filter(isCoreFirstRunAsset).every((asset) => present.has(asset));
}

/**
 * Normalise a sidecar requirements file body to the lines that actually
 * determine the installed env — mirroring bootstrap.py `parse_requirements`:
 * drop blank lines and `#` comments (inline ` #…` too), then SORT so
 * comment / whitespace / reorder churn never triggers a spurious re-bootstrap,
 * while any real pin change (a bumped `pkg==version`, an added / removed dep)
 * always does. Pure — the input is the shipped file's text.
 */
export function normalizeRequirements(requirementsText: string): string[] {
  const lines: string[] = [];
  for (const raw of requirementsText.split('\n')) {
    let line = raw.trim();
    if (line === '' || line.startsWith('#')) {
      continue;
    }
    const inline = line.indexOf(' #');
    if (inline !== -1) {
      line = line.slice(0, inline).trim();
    }
    if (line !== '') {
      lines.push(line);
    }
  }
  return lines.sort();
}

/**
 * Stable fingerprint (sha256 hex) of the sidecar requirements body — the version
 * signal for the re-bootstrap decision. The caller hashes the ACTIVE install
 * source (the sibling hashed lock when staged, else the loose pins — see
 * {@link hashedLockFilename}), so a lock-only / transitive-dependency bump is
 * caught too. Computed over {@link normalizeRequirements} so it is sensitive to
 * any dependency change (a bumped pin, a changed `--hash=`, an added / removed
 * line) but insensitive to comment / whitespace / reorder churn — for the loose
 * pins AND the lock's hashed lines alike.
 */
export function requirementsFingerprint(requirementsText: string): string {
  return createHash('sha256')
    .update(normalizeRequirements(requirementsText).join('\n'))
    .digest('hex');
}

/**
 * WU-S2-FIX: the sibling fully-hashed lock filename for a loose sidecar
 * requirements filename — the TS mirror of bootstrap.py `hashed_lock_path`
 * (`requirements-sidecar.txt` -> `requirements-sidecar.lock.txt`): drop the final
 * extension (Python `Path.stem`) and append `.lock.txt`.
 *
 * The packaged env is installed from THIS lock with `pip --require-hashes` when
 * it is staged (bootstrap.py `install_env` -> `resolve_active_lock`), so the
 * drift fingerprint MUST hash the lock — not the loose `.txt` — whenever it is
 * present; otherwise a lock-only / transitive bump (which never edits the loose
 * pins) would slip past and start a stale env against the new pip target. Pure:
 * the caller owns the existence check + read (it prefers the lock when present,
 * else falls back to the loose file). Filename-only (no directory separators),
 * mirroring `Path.stem` on a basename.
 */
export function hashedLockFilename(requirementsFilename: string): string {
  const lastDot = requirementsFilename.lastIndexOf('.');
  const stem = lastDot === -1 ? requirementsFilename : requirementsFilename.slice(0, lastDot);
  return `${stem}.lock.txt`;
}

/**
 * WU-S2: whether the persisted requirements fingerprint is IN SYNC with the
 * current shipped one. A `null` persisted value — a legacy marker written before
 * this feature existed, or a fingerprint write that failed — is treated as IN
 * SYNC so an update that changes NO dependency never forces a surprise
 * re-bootstrap; the supervisor BACKFILLS the current fingerprint instead
 * ({@link shouldBackfillFingerprint}).
 */
export function fingerprintInSync(persisted: string | null, currentShipped: string): boolean {
  return persisted === null || persisted === currentShipped;
}

/**
 * WU-S2: backfill the fingerprint (WITHOUT re-bootstrapping) exactly when a
 * completed install has a marker but NO persisted fingerprint — a legacy install
 * upgraded to a build that added this feature. Its env is assumed to match the
 * currently-shipped requirements (it was provisioned + working), so recording the
 * current fingerprint arms drift-detection for FUTURE bumps without a needless
 * re-provision now. No marker -> nothing is provisioned to describe, so no
 * backfill (the first-ever bootstrap will write it on success).
 */
export function shouldBackfillFingerprint(
  completeMarkerExists: boolean,
  persisted: string | null,
): boolean {
  return completeMarkerExists && persisted === null;
}

/** WU-S2: the kind of first-run work a launch must do. */
export type FirstRunKind = 'none' | 'first-ever' | 're-bootstrap';

/**
 * WU-S2: classify a launch's first-run work — the single decision point.
 *   - unpackaged (dev) -> `none` (dev behaviour is byte-identical).
 *   - packaged, NO marker -> `first-ever`: the INTERACTIVE first run (nothing is
 *     provisioned yet; the renderer's local-vs-cloud chooser may prompt, gated on
 *     its own `firstRunChoiceMade` settings flag).
 *   - packaged, marker present but fingerprint DRIFTED -> `re-bootstrap`: a
 *     SILENT / headless re-provision that reuses the persisted install profile
 *     and never re-prompts the chooser (the chooser flag is untouched, so it
 *     stays satisfied).
 *   - packaged, marker present and IN SYNC -> `none`.
 */
export function classifyFirstRun(
  isPackaged: boolean,
  completeMarkerExists: boolean,
  fingerprintIsInSync: boolean,
): FirstRunKind {
  if (!isPackaged) {
    return 'none';
  }
  if (!completeMarkerExists) {
    return 'first-ever';
  }
  return fingerprintIsInSync ? 'none' : 're-bootstrap';
}

/**
 * True when packaged AND a stage-2 bootstrap.py run is needed — either the full
 * first run has NOT completed yet (no marker) OR the marker exists but the shipped
 * sidecar requirements fingerprint DRIFTED from the persisted one (an auto-update
 * changed the env — WU-S2). Both cases re-run bootstrap, which is idempotent (pip
 * re-checks satisfied deps, ensure_assets skips downloaded assets) and back-fills
 * anything newly added. `fingerprintIsInSync` defaults to `true` so an existing
 * install with a marker is unaffected until a real drift is observed.
 */
export function needsFirstRunSetup(
  isPackaged: boolean,
  completeMarkerExists: boolean,
  fingerprintIsInSync = true,
): boolean {
  return classifyFirstRun(isPackaged, completeMarkerExists, fingerprintIsInSync) !== 'none';
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

/**
 * WU-1a: whether runFirstRunBootstrap should SPAWN bootstrap.py — and therefore
 * RAISE the explicit provisioning signal — given the data-root lock result. A busy
 * folder (`lockOk` false: another LIVE copy holds the tree) REFUSES: no spawn, so
 * the `provisioning.state` fan-out never fires and this copy surfaces only the loud
 * busy banner instead of a spurious "setting up" gate it could never finish.
 * Provisioning is broadcast ONLY past this busy-lock guard.
 */
export function shouldSpawnBootstrap(lockOk: boolean): boolean {
  return lockOk;
}

/**
 * WU-1a-FIX: whether a sidecar lifecycle status transition should CLEAR the
 * first-run provisioning signal. The supervisor only STARTS the sidecar (so it
 * only ever emits a status) AFTER a bootstrap succeeded — a first-ever / re-bootstrap
 * run that resolved ok, or a launch that needed no first run at all — so the FIRST
 * status transition of ANY kind is the terminal for provisioning:
 *   - 'running'    — the runtime came up (the success terminal).
 *   - 'restarting' — the sidecar crashed right after bootstrap and is auto-recovering.
 *   - 'down'       — it crashed after bootstrap and auto-restart gave up.
 * Clearing on all three closes the stuck-gate bug: previously only 'running'
 * cleared the signal, so a post-bootstrap crash that reached 'down' WITHOUT ever
 * reaching 'running' (e.g. the interpreter path became a directory / an invalid
 * cwd) left provisioning latched TRUE and the FirstRunSetup gate up FOREVER —
 * masking a crash as "still setting up". A post-bootstrap crash now correctly
 * surfaces via the in-shell SidecarBanner instead. Any other/unknown string is not
 * a recognised lifecycle state and does not clear.
 */
export function shouldClearProvisioningOnSidecarStatus(state: string): boolean {
  return state === 'running' || state === 'restarting' || state === 'down';
}
