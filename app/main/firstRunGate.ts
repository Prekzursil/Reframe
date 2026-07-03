// firstRunGate.ts — pure decision helpers for the packaged first-run gate.
//
// WIRING-T5 §2 hardening (first-run provisioning). The Electron supervisor must
// decide, per packaged launch, whether to run stage-2 bootstrap.py. The honest
// signal is the FIRST-RUN-COMPLETE marker bootstrap.py writes at the DATA ROOT
// only after a FULL provision (env + every model + the S3FD/LR-ASD weights)
// succeeds — NOT the per-env sentinel (`.media-studio-env.json`), which only
// means "the pip env installed". Gating on the env sentinel let a run that built
// the env but failed the model/weight downloads look "done", so the next launch
// skipped bootstrap and the app ran half-provisioned (silently centre-cropping).
//
// This name MUST stay in sync with bootstrap.py FIRST_RUN_COMPLETE_MARKER
// (firstRunGate.test.ts asserts they match by reading bootstrap.py).
export const FIRST_RUN_COMPLETE_MARKER = '.first-run-complete.json';

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
