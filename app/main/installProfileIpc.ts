// installProfileIpc.ts — main-process IPC for the FIRST-EVER-run install PROFILE
// choice (WU-1c).
//
// On a first-ever run the supervisor does NOT auto-spawn bootstrap.py: it seeds
// the provisioning gate as "awaiting profile" and waits for the renderer's
// ProfilePicker. When the user picks (Minimum / Default / Full / Custom), the
// renderer invokes `installProfile.choose`; THIS handler validates the choice,
// PERSISTS it (so a later silent WU-S2 re-bootstrap replays the same profile), and
// kicks off bootstrap.py with the resolved `--assets`. Everything IO — resolution,
// persistence, the bootstrap kickoff — is INJECTED by main.ts so this module stays
// thin + testable, mirroring repairSetupIpc.ts.
import { ipcMain } from 'electron';

import { InstallProfileError, type ResolvedInstallChoice } from './installProfiles';

/** ipc channel: commit the first-run install profile choice. */
export const INSTALL_PROFILE_CHOOSE_CHANNEL = 'installProfile.choose';

/** Outcome forwarded to `window.api.chooseInstallProfile()`. */
export interface ChooseInstallProfileResult {
  /** true once the choice was accepted and bootstrap kicked off. */
  ok: boolean;
  /** Actionable reason when `ok` is false (invalid choice / already running). */
  reason?: string;
}

/** The raw choice payload the renderer sends. */
export interface InstallProfileChoicePayload {
  profile: unknown;
  bundles?: unknown;
}

/** Wiring main.ts injects (keeps this module free of the map + bootstrap IO). */
export interface InstallProfileDeps {
  /**
   * True while a first-run OR repair bootstrap is already running — guards a
   * double-submit from spawning a second concurrent bootstrap.
   */
  isBootstrapInFlight: () => boolean;
  /**
   * Validate + resolve the choice to its asset set (the single-source map).
   * MUST throw {@link InstallProfileError} on an unknown profile/bundle.
   */
  resolveChoice: (profile: unknown, bundles: readonly unknown[]) => ResolvedInstallChoice;
  /** Persist the accepted choice at the data root (for a silent re-bootstrap replay). */
  persist: (choice: ResolvedInstallChoice) => void;
  /**
   * Kick off bootstrap.py for the resolved assets: flip the gate from
   * "awaiting profile" to "provisioning" and spawn with `--assets`.
   */
  beginBootstrap: (assets: readonly string[]) => void;
}

/**
 * Core choose decision (pure of ipcMain, directly unit-testable):
 *   - already running → no-op, `{ ok:false }` + a "please wait" reason,
 *   - invalid choice  → `{ ok:false }` with the loud reason (NO silent default),
 *   - valid choice    → persist, begin bootstrap, `{ ok:true }`.
 */
export async function performChooseInstallProfile(
  deps: InstallProfileDeps,
  payload: InstallProfileChoicePayload,
): Promise<ChooseInstallProfileResult> {
  if (deps.isBootstrapInFlight()) {
    return {
      ok: false,
      reason: 'Setup is already running — please wait for it to finish.',
    };
  }
  const bundles = Array.isArray(payload?.bundles) ? payload.bundles : [];
  let choice: ResolvedInstallChoice;
  try {
    choice = deps.resolveChoice(payload?.profile, bundles);
  } catch (err) {
    const message = err instanceof InstallProfileError ? err.message : (err as Error).message;
    return { ok: false, reason: `Invalid install profile: ${message}` };
  }
  deps.persist(choice);
  deps.beginBootstrap(choice.assets);
  return { ok: true };
}

/**
 * Register the `installProfile.choose` handler. Returns a disposer that removes it
 * (mirrors registerRepairSetupIpc). bootstrap() wires this and disposes it in
 * will-quit.
 */
export function registerInstallProfileIpc(deps: InstallProfileDeps): () => void {
  ipcMain.handle(INSTALL_PROFILE_CHOOSE_CHANNEL, (_event, payload: InstallProfileChoicePayload) =>
    performChooseInstallProfile(deps, payload ?? { profile: undefined }),
  );
  return (): void => {
    ipcMain.removeHandler(INSTALL_PROFILE_CHOOSE_CHANNEL);
  };
}
