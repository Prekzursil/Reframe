// repairSetupIpc.ts — main-process IPC for the on-demand "Retry setup / Repair"
// control (WU A5).
//
// A user whose FIRST run partially failed (a transient download error, a locked
// file) is left with a loud bootstrap-error banner but no way to recover short of
// relaunching. This handler lets the renderer re-run the SAME idempotent
// `runtime_setup/bootstrap.py` on demand: pip re-checks already-satisfied deps
// and only missing assets re-download, then — on success — the sidecar is
// (re)started so the app becomes usable in place.
//
// It is SINGLE-FLIGHT: if a first-run (or a prior repair) bootstrap is already
// running, a second request is a no-op that reports back rather than spawning a
// second concurrent bootstrap. The heavy wiring (the bootstrap runner, the
// in-flight signal, the sidecar (re)start) is INJECTED by main.ts so this module
// stays thin and testable — mirroring `dataFolderIpc.ts`.
import { ipcMain } from 'electron';

/** ipc channel: re-run the first-run bootstrap on demand. */
export const SETUP_REPAIR_CHANNEL = 'setup.repair';

/** Outcome of a repair attempt, forwarded to `window.api.repairSetup()`. */
export interface RepairSetupResult {
  /** true once the core runtime is provisioned AND the sidecar (re)started. */
  ok: boolean;
  /** Actionable reason when `ok` is false (already-running / spawn failure). */
  reason?: string;
}

/** Wiring main.ts injects (keeps this module free of Electron app/sidecar IO). */
export interface RepairSetupDeps {
  /**
   * True while a first-run OR repair bootstrap is already running. Guards
   * against spawning a second concurrent bootstrap (single-flight).
   */
  isBootstrapInFlight: () => boolean;
  /**
   * Re-run the idempotent first-run bootstrap. Resolves true on a clean
   * provision (exit 0), false otherwise. MUST NOT throw for a normal failed
   * run — but a rejection is still handled defensively below.
   */
  runBootstrap: () => Promise<boolean>;
  /**
   * Called exactly once, AFTER a successful bootstrap, to (re)start the sidecar
   * so the freshly-provisioned runtime is picked up.
   */
  onBootstrapSucceeded: () => void;
}

/**
 * Core repair decision (pure of ipcMain, directly unit-testable):
 *   - already running → no-op, `{ ok:false }` + a "please wait" reason.
 *   - run + succeed   → (re)start the sidecar, `{ ok:true }`.
 *   - run + fail      → `{ ok:false }` (the loud, actionable message arrives on
 *                       the separate bootstrap-error channel).
 *   - run + throw     → `{ ok:false }` with the thrown message (never crashes
 *                       the handler).
 */
export async function performRepairSetup(deps: RepairSetupDeps): Promise<RepairSetupResult> {
  if (deps.isBootstrapInFlight()) {
    return {
      ok: false,
      reason: 'Setup is already running — please wait for it to finish.',
    };
  }
  let ok: boolean;
  try {
    ok = await deps.runBootstrap();
  } catch (err) {
    return { ok: false, reason: `Setup could not run: ${(err as Error).message}` };
  }
  if (ok) {
    deps.onBootstrapSucceeded();
    return { ok: true };
  }
  // A normal failed run: the actionable "what failed + how to fix" line was
  // already broadcast on the bootstrap-error channel, so no reason is duplicated
  // here — the renderer keeps that message and re-offers Retry.
  return { ok: false };
}

/**
 * Register the `setup.repair` handler. Returns a disposer that removes it
 * (mirrors `registerDataFolderIpc`). bootstrap() in main.ts wires this and tears
 * the disposer down in will-quit.
 */
export function registerRepairSetupIpc(deps: RepairSetupDeps): () => void {
  ipcMain.handle(SETUP_REPAIR_CHANNEL, () => performRepairSetup(deps));
  return (): void => {
    ipcMain.removeHandler(SETUP_REPAIR_CHANNEL);
  };
}
