// dataRootMigrateIo.ts — the concrete FILESYSTEM seam for the WU-R1 legacy
// `<exeDir>/data` -> `%APPDATA%/media-studio` migration.
//
// WHY separate from dataRootPlan.ts: the DECISION (whether to migrate, and the
// abort/fallback branches) is pure and fully unit-tested in dataRootPlan.ts. The
// actual disk work — measuring the tree, probing free space, and the atomic move
// that must never leave a partial destination — is real node:fs IO and lives here
// (Electron-free: only node:fs + node:path + process.pid). main.ts wires these
// primitives into a MigrationSeam for runMigration().
import {
  cpSync,
  existsSync,
  mkdirSync,
  readdirSync,
  renameSync,
  rmSync,
  statfsSync,
  statSync,
} from 'node:fs';
import { dirname, join } from 'node:path';

/**
 * True when `dir` exists, is a directory, and is NON-EMPTY. Used both to detect a
 * legacy `<exeDir>/data` worth rescuing and to detect an already-occupied
 * `%APPDATA%/media-studio` we must not clobber. Any stat/read error -> false
 * (treat as absent/empty — the conservative, no-clobber default).
 */
export function dirHasContent(dir: string): boolean {
  try {
    if (!existsSync(dir) || !statSync(dir).isDirectory()) return false;
    return readdirSync(dir).length > 0;
  } catch {
    return false;
  }
}

/** Total size in bytes of every regular file under `dir` (recursive). */
export function dirSizeBytes(dir: string): number {
  let total = 0;
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const child = join(dir, entry.name);
    if (entry.isDirectory()) {
      total += dirSizeBytes(child);
    } else if (entry.isFile()) {
      try {
        total += statSync(child).size;
      } catch {
        /* a file that vanished mid-walk contributes nothing */
      }
    }
  }
  return total;
}

/**
 * Bytes available (to an unprivileged process) on the volume that holds `path`.
 * `path` must already exist — callers pass the destination's PARENT (%APPDATA%,
 * which always exists) so the probe works before the destination is created.
 */
export function freeSpaceBytes(path: string): number {
  const st = statfsSync(path);
  return st.bavail * st.bsize;
}

/**
 * Atomically move the directory `from` to `to`, all-or-nothing:
 *  - a pre-existing but EMPTY destination is removed first so the move can create
 *    it fresh (callers only migrate when the destination is not content-ful);
 *  - a same-volume move uses renameSync (atomic, instant, no copy);
 *  - a cross-volume move (EXDEV) copies to a temp sibling, renames it into place
 *    atomically, then best-effort removes the source. If the copy fails partway,
 *    the temp is removed and the error re-thrown so the SOURCE stays intact and NO
 *    partial destination is ever published.
 */
export function atomicMoveDir(from: string, to: string): void {
  mkdirSync(dirname(to), { recursive: true });
  if (existsSync(to) && !dirHasContent(to)) {
    rmSync(to, { recursive: true, force: true });
  }
  try {
    renameSync(from, to); // atomic same-volume move
    return;
  } catch (err) {
    if ((err as NodeJS.ErrnoException).code !== 'EXDEV') throw err;
  }
  // Cross-volume: stage a full copy, then publish it with an atomic rename.
  const staging = `${to}.migrating-${process.pid}`;
  try {
    cpSync(from, staging, { recursive: true, errorOnExist: true, force: false });
    renameSync(staging, to);
    rmSync(from, { recursive: true, force: true }); // best-effort source cleanup
  } catch (err) {
    rmSync(staging, { recursive: true, force: true }); // never leave a partial dest
    throw err;
  }
}
