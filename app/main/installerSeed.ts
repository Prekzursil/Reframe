// installerSeed.ts — carry the NSIS installer's component choice into first run (WU-I1).
//
// THE PROBLEM. The installer now has a real component page (Default / Full / Custom
// with individually selectable feature packs — build/installer.nsh). The user makes a
// choice there, and then the app's FIRST-EVER launch used to ask the SAME question
// again in the in-app ProfilePicker (main.ts `awaitingProfile`). Asking twice is not
// just noise: the second answer is the one that provisions, so the installer page
// would be decorative and the install could never be unattended.
//
// WHY THE INSTALLER CANNOT JUST WRITE THE DATA ROOT. The persisted profile lives at
// `<dataRoot>/.first-run-profile.json`, and the data root is RESOLVED AT RUNTIME by
// dataRootPlan.planDataRoot (env override -> `data-dir.txt` marker -> a legacy
// `<exeDir>/data` migration -> `%APPDATA%/media-studio`). NSIS cannot evaluate that
// without re-implementing it, and a second implementation of a path policy is exactly
// how the two silently drift. So the installer writes a SEED at the one location it
// knows EXACTLY — `$INSTDIR` — and this module (the single policy owner, in TS) copies
// it into whatever data root the app actually resolved.
//
// WHY `$INSTDIR` AND NOT `<userData>`. `$INSTDIR` is byte-exact on both sides: NSIS
// has `$INSTDIR`, the app has `dirname(process.execPath)` (dataRootIo.exeDir). The
// `<userData>` alternative depends on electron-builder's `APP_FILENAME` define
// matching Electron's `app.getName()`, which is a guess this module refuses to make.
// `$INSTDIR` is wiped by an in-place NSIS update (app-builder-lib
// templates/nsis/uninstaller.nsh:187 `RMDir /r $INSTDIR`) — which is CORRECT here: the
// seed is re-written by every installer run and consumed on the next launch, so it is
// per-install state, not durable state. Nothing durable is stored there (that is the
// T13 rule dataRootIo.ts already enforces for `data-dir.txt`).
//
// BACKWARD COMPATIBILITY (load-bearing). The seed is adopted ONLY when the resolved
// data root holds NO profile yet. An existing install therefore keeps the profile it
// already chose, its models are never re-fetched, and no setting is touched — even
// though every upgrade re-runs the installer page and re-writes a seed. That guard is
// the whole backward-compatibility contract and it is unit-tested from both sides.
//
// PURE-BY-SEAM: all filesystem access is injected ({@link InstallerSeedIo}) so the
// decision is fully testable; main.ts owns the concrete seam.
import { join } from 'node:path';
import type { FirstRunKind } from './firstRunGate';
import {
  INSTALL_PROFILE_FILE,
  parsePersistedInstallProfile,
  type PersistedInstallProfile,
} from './installProfiles';

/**
 * The seed filename the installer writes into `$INSTDIR`. Deliberately the SAME name
 * (and byte-identical schema) as the app's own persisted profile — one contract, one
 * parser, no translation layer. installerSeed.test.ts pins the equality.
 */
export const INSTALLER_PROFILE_SEED_FILE = INSTALL_PROFILE_FILE;

/** Absolute path of the installer seed for an install directory. */
export function installerSeedPath(installDir: string): string {
  return join(installDir, INSTALLER_PROFILE_SEED_FILE);
}

/**
 * Why an adoption attempt ended the way it did. Every value is a NORMAL outcome that
 * must not crash startup — the worst case simply falls back to the in-app picker.
 *
 *  - `adopted`        the seed was valid and is now the data root's profile;
 *  - `already-chosen` the data root already has a profile (an UPGRADE — never clobber);
 *  - `same-path`      the seed IS the data-root profile (nothing to copy);
 *  - `no-seed`        no installer seed (a portable/zip build, or an unreadable dir);
 *  - `invalid-seed`   present but corrupt / from a drifted installer — ignored loudly;
 *  - `write-failed`   the data root refused the write (read-only / AV lock).
 */
export type InstallerSeedOutcome =
  | 'adopted'
  | 'already-chosen'
  | 'same-path'
  | 'no-seed'
  | 'invalid-seed'
  | 'write-failed';

/** The adoption result: the outcome plus the record actually adopted (or `null`). */
export interface InstallerSeedResult {
  readonly outcome: InstallerSeedOutcome;
  readonly profile: PersistedInstallProfile | null;
}

/** The filesystem seam {@link adoptInstallerProfileSeed} needs (main.ts supplies it). */
export interface InstallerSeedIo {
  /** `<installDir>/.first-run-profile.json` — where the installer wrote its choice. */
  readonly seedPath: string;
  /** `<dataRoot>/.first-run-profile.json` — where the app reads the choice from. */
  readonly dataRootProfilePath: string;
  /** Raw seed body, or `undefined` when absent/unreadable. May throw; treated as absent. */
  readSeed: () => string | undefined;
  /** True when the data root already holds a profile. May throw; treated as `true`. */
  dataRootProfileExists: () => boolean;
  /** Persist the adopted record at the data root; `false` (or throw) when it failed. */
  writeDataRootProfile: (record: PersistedInstallProfile) => boolean;
}

/**
 * Parse a raw installer-seed body into the validated persisted record, or `null` when
 * it is absent, empty, not JSON, or not a recognised profile. Reuses
 * {@link parsePersistedInstallProfile} so the installer seed and the app's own file can
 * never be validated by two different rules.
 */
export function parseInstallerSeed(raw: string | undefined): PersistedInstallProfile | null {
  if (raw === undefined || raw.trim() === '') {
    return null;
  }
  try {
    return parsePersistedInstallProfile(JSON.parse(raw));
  } catch {
    return null; // corrupt JSON -> fall back to the in-app picker, never a guessed set
  }
}

/**
 * WU-I1: whether the in-app ProfilePicker must still ask (main.ts `awaitingProfile`).
 *
 * The picker is suppressed for exactly one case: a FIRST-EVER run whose profile was
 * adopted from the installer ON THIS LAUNCH. That is what makes an install unattended.
 *
 * `installerAdoptedThisLaunch` — NOT "a profile exists at the data root" — is the
 * deliberate condition, and the difference is a real trap. A first run that dies
 * mid-download leaves its chosen profile persisted but writes no completion marker, so
 * the NEXT launch is `first-ever` again. Keying off mere existence would silently retry
 * the SAME set (possibly the one that just filled the disk) with no route back to the
 * chooser. Keying off this-launch adoption keeps that path exactly as it was before
 * WU-I1: the picker reappears and the user can pick something smaller.
 *
 * Every other case is unchanged: a silent WU-S2 `re-bootstrap` replays the persisted
 * profile without prompting, and `none` has no first-run work to gate.
 */
export function shouldAwaitProfileChoice(
  firstRun: boolean,
  firstRunKind: FirstRunKind,
  installerAdoptedThisLaunch: boolean,
): boolean {
  return firstRun && firstRunKind === 'first-ever' && !installerAdoptedThisLaunch;
}

/** Windows paths are case-insensitive; compare the two profile paths accordingly. */
function samePath(a: string, b: string): boolean {
  return a.toLowerCase() === b.toLowerCase();
}

/**
 * Copy the installer's component choice into the resolved data root, so a first-ever
 * launch provisions THAT set unattended instead of re-asking.
 *
 * NEVER THROWS — every failure mode is a returned {@link InstallerSeedOutcome}, because
 * a seed problem must degrade to "show the picker", never to a failed startup.
 *
 * ORDER MATTERS. `same-path` is checked before the existence probe (when the seed IS
 * the target, "it already exists" is a tautology, not a user choice), and
 * `already-chosen` is checked before the seed is even read, so an upgrade does no IO
 * and cannot be influenced by a corrupt seed.
 */
export function adoptInstallerProfileSeed(io: InstallerSeedIo): InstallerSeedResult {
  if (samePath(io.seedPath, io.dataRootProfilePath)) {
    return { outcome: 'same-path', profile: null };
  }
  // FAIL CLOSED: an unprobeable data root counts as "already chosen". Treating a
  // transient stat error as "empty" would let a stale seed overwrite a real choice.
  let exists: boolean;
  try {
    exists = io.dataRootProfileExists();
  } catch {
    exists = true;
  }
  if (exists) {
    return { outcome: 'already-chosen', profile: null };
  }

  let raw: string | undefined;
  try {
    raw = io.readSeed();
  } catch {
    raw = undefined;
  }
  if (raw === undefined || raw.trim() === '') {
    return { outcome: 'no-seed', profile: null };
  }

  const record = parseInstallerSeed(raw);
  if (record === null) {
    return { outcome: 'invalid-seed', profile: null };
  }

  let ok: boolean;
  try {
    ok = io.writeDataRootProfile(record);
  } catch {
    ok = false;
  }
  return ok ? { outcome: 'adopted', profile: record } : { outcome: 'write-failed', profile: null };
}
