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
import { mkdirSync, readFileSync, unlinkSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { DATA_DIR_MARKER } from './dataRoot';

/** Directory holding the running executable (where the marker file lives). */
export function exeDir(): string {
  return dirname(process.execPath);
}

/** Absolute path of the data-folder marker file (`<exeDir>/data-dir.txt`). */
export function dataDirMarkerPath(): string {
  return join(exeDir(), DATA_DIR_MARKER);
}

/** Absolute path of the portable `<exeDir>/data` data root. */
export function exeDataDir(): string {
  return join(exeDir(), 'data');
}

/** Read the marker file's trimmed contents, or undefined if absent/unreadable. */
export function readDataDirMarker(): string | undefined {
  try {
    return readFileSync(dataDirMarkerPath(), 'utf8');
  } catch {
    return undefined; // no marker (or unreadable) -> ignored by chooseDataRoot
  }
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
