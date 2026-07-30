// dataRootIo.ts — the concrete FILESYSTEM seam for data-root resolution.
//
// WHY this exists (preview-blocker gap closure): the pure priority policy lives
// in dataRoot.ts (chooseDataRoot / resolveDataRootFrom) and is fully unit-tested.
// But the IO that FEEDS that policy — where the running exe lives, reading the
// `data-dir.txt` marker, probing whether `<exeDir>/data` is writable — used to be
// private functions inside main.ts, which cannot be imported under vitest (main.ts
// runs Electron module-level side effects on import). So the EXACT seam that
// produced the dev "empty writable <exeDir>/data" trap had ZERO direct coverage —
// it slipped through every gate. These functions are Electron-free (only
// `process.execPath`, `node:fs`, `node:path`), so they live here and are tested in
// dataRootIo.test.ts; main.ts just wires them into resolveDataRootFrom.
import { existsSync, mkdirSync, readFileSync, unlinkSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { DATA_DIR_MARKER, isSafeLocalDataRoot } from './dataRoot';
import { FIRST_RUN_COMPLETE_MARKER } from './firstRunGate';

/**
 * Files whose presence at a data root PROVES it was already provisioned: the
 * first-run-complete marker bootstrap.py writes after a full provision, and the
 * library index in either its legacy (`library.json`) or migrated (`library.db`)
 * form. A4 content-aware selection prefers a root holding any of these over an
 * EMPTY writable `<exeDir>/data`, so a clean portable install never opens a blank
 * library when a provisioned tree already exists in a lower tier.
 */
export const PROVISIONING_MARKERS = [
  FIRST_RUN_COMPLETE_MARKER,
  'library.json',
  'library.db',
] as const;

/** True when `root` holds any {@link PROVISIONING_MARKERS} file (already set up). */
export function isProvisionedRoot(root: string): boolean {
  return PROVISIONING_MARKERS.some((name) => existsSync(join(root, name)));
}

/** Directory holding the running executable (where the marker file lives). */
export function exeDir(): string {
  return dirname(process.execPath);
}

/**
 * Absolute path of the LEGACY data-folder marker (`<exeDir>/data-dir.txt`).
 *
 * T13 (DATA LOSS ON UPDATE): `<exeDir>` is the NSIS `$INSTDIR`, and
 * electron-updater's in-place upgrade REPLACES that directory — so a marker stored
 * here is DELETED by every app update, resolution silently falls back to the
 * default root, and the user's external library APPEARS LOST. The authoritative
 * location is now {@link stableDataDirMarkerPath} (per-user `userData`, which no
 * updater touches); this path is still READ (and mirrored on write) FOREVER so an
 * existing install, or a rollback to an older build, is never orphaned.
 */
export function dataDirMarkerPath(): string {
  return join(exeDir(), DATA_DIR_MARKER);
}

/**
 * Absolute path of the STABLE per-user data-folder marker
 * (`<userDataDir>/data-dir.txt`), where `userDataDir` is `app.getPath('userData')`
 * (`%APPDATA%/<app>`). This is the T13 fix: it lives OUTSIDE `$INSTDIR`, so the
 * user's chosen data folder survives an in-place NSIS auto-update. Injected rather
 * than derived so this module stays Electron-free (main.ts owns `app.getPath`).
 */
export function stableDataDirMarkerPath(userDataDir: string): string {
  return join(userDataDir, DATA_DIR_MARKER);
}

/** Absolute path of the portable `<exeDir>/data` data root. */
export function exeDataDir(): string {
  return join(exeDir(), 'data');
}

/** Read `markerPath`'s raw contents, or undefined when absent/unreadable. */
function readMarkerAt(markerPath: string): string | undefined {
  try {
    return readFileSync(markerPath, 'utf8');
  } catch {
    return undefined; // no marker (or unreadable) -> ignored by chooseDataRoot
  }
}

/** Read the LEGACY `<exeDir>/data-dir.txt`, or undefined if absent/unreadable. */
export function readDataDirMarker(): string | undefined {
  return readMarkerAt(dataDirMarkerPath());
}

/** Read the STABLE `<userDataDir>/data-dir.txt`, or undefined if absent/unreadable. */
export function readStableDataDirMarker(userDataDir: string): string | undefined {
  return readMarkerAt(stableDataDirMarkerPath(userDataDir));
}

/** Trim a marker's contents and return it only when it has non-whitespace content. */
function nonEmptyMarker(value: string | undefined): string | undefined {
  if (typeof value !== 'string') return undefined;
  const trimmed = value.trim();
  return trimmed === '' ? undefined : trimmed;
}

/**
 * Persist `value` to `markerPath` (creating its parent dir), returning false —
 * never throwing — when the write fails. A read-only install dir, a missing
 * `userData`, or an AV lock must never crash startup or the data-folder IPC.
 */
export function writeDataDirMarker(markerPath: string, value: string): boolean {
  try {
    mkdirSync(dirname(markerPath), { recursive: true });
    writeFileSync(markerPath, value, 'utf8');
    return true;
  } catch {
    return false;
  }
}

/**
 * Resolve the user's chosen data folder from the marker — the T13 update-survival
 * read. Precedence:
 *
 *   1. the STABLE per-user marker (`<userDataDir>/data-dir.txt`) when it holds a
 *      non-blank value — this is the copy an app update cannot delete;
 *   2. otherwise the LEGACY `<exeDir>/data-dir.txt`, whose value is honored
 *      VERBATIM *and* written FORWARD into the stable location so the SAME choice
 *      survives the next update. Existing users keep their folder with no prompt.
 *
 * The forward write is best-effort (a failure just means we migrate again next
 * launch) and is SKIPPED for a value {@link isSafeLocalDataRoot} rejects: a
 * poisoned marker (UNC / device / `..`) must keep raising `DataRootSecurityError`
 * downstream in `chooseDataRoot` and must never be propagated into a second file.
 * The value is returned RAW (untrimmed) exactly like {@link readDataDirMarker},
 * because trimming + security validation belong to `chooseDataRoot`.
 */
export function resolveDataDirMarker(userDataDir: string): string | undefined {
  const stable = readStableDataDirMarker(userDataDir);
  if (nonEmptyMarker(stable) !== undefined) return stable;

  const legacy = readDataDirMarker();
  const value = nonEmptyMarker(legacy);
  if (value !== undefined && isSafeLocalDataRoot(value)) {
    writeDataDirMarker(stableDataDirMarkerPath(userDataDir), value);
  }
  return legacy;
}

/**
 * True when `dir` is creatable/writable (a writable install dir). Used to decide
 * whether a PACKAGED build may keep its data beside the executable (the portable
 * default) versus falling back to %APPDATA% on a read-only install (Program Files).
 * The result is only CONSULTED for the portable auto-pick when
 * `preferExeDataDir` is set (see dataRoot.ts) — in dev the auto-pick is gated off.
 */
export function isExeDataWritable(dir: string): boolean {
  try {
    mkdirSync(dir, { recursive: true });
    // Prove writability (mkdir on an existing dir succeeds even when read-only).
    const probe = join(dir, `.write-probe-${process.pid}`);
    writeFileSync(probe, '');
    try {
      unlinkSync(probe);
    } catch {
      /* probe cleanup is best-effort */
    }
    return true;
  } catch {
    return false; // read-only install (e.g. Program Files) -> fall back to appData
  }
}
