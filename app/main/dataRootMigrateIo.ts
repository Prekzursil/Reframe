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
 * The TRI-STATE result of probing a directory for content:
 *  - `present` — it exists, is a directory, and holds at least one entry;
 *  - `absent`  — it does not exist, is not a directory, or is provably EMPTY;
 *  - `error`   — the probe itself FAILED (EACCES/EIO/...), so occupancy is UNKNOWN.
 *
 * The third state is the whole point (T8): the old boolean probe collapsed `error`
 * into "empty", and a caller asking "is it safe to overwrite?" then recursively
 * DELETED a populated tree because a transient stat/read failure looked like an
 * empty destination. Every caller must decide explicitly what `error` means for it.
 */
export type DirContentState = 'present' | 'absent' | 'error';

/** Probe `dir` for content, distinguishing a FAILED probe from an empty one. */
export function probeDirContent(dir: string): DirContentState {
  try {
    if (!existsSync(dir) || !statSync(dir).isDirectory()) return 'absent';
    return readdirSync(dir).length > 0 ? 'present' : 'absent';
  } catch {
    return 'error'; // occupancy UNKNOWN — never report this as "empty"
  }
}

/**
 * True when `dir` DEFINITELY holds content. Used to detect a legacy
 * `<exeDir>/data` tree worth rescuing: an unprobeable dir answers false, i.e. we
 * do NOT start a migration we cannot reason about (the safe direction here).
 *
 * NOT the right question for "may I overwrite this?" — use
 * {@link dirMayHaveContent} for that, which fails CLOSED.
 */
export function dirHasContent(dir: string): boolean {
  return probeDirContent(dir) === 'present';
}

/**
 * FAIL-CLOSED occupancy guard: true unless `dir` is PROVABLY absent/empty. An
 * `error` probe counts as OCCUPIED, so a transient stat/read failure can never be
 * mistaken for "empty and therefore safe to clobber". This is the predicate any
 * destination/no-clobber decision must use (see main.ts `appDataOccupied`).
 */
export function dirMayHaveContent(dir: string): boolean {
  return probeDirContent(dir) !== 'absent';
}

/**
 * Thrown by {@link atomicMoveDir} when the DESTINATION's occupancy cannot be
 * probed. Aborting is mandatory: the alternative is deleting a tree we cannot see.
 */
export const UNPROBEABLE_DEST_MESSAGE = 'migration destination contents could not be probed';

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
 *  - a PROVABLY empty pre-existing destination is removed first so the move can
 *    create it fresh (callers only migrate when the destination is not content-ful);
 *  - a destination whose occupancy CANNOT be probed ABORTS the move
 *    ({@link UNPROBEABLE_DEST_MESSAGE}) instead of deleting a tree we cannot see —
 *    the T8 fail-closed rule. runMigration turns the throw into its loud fallback,
 *    so the caller keeps using the legacy root with both trees byte-intact;
 *  - a same-volume move uses renameSync (atomic, instant, no copy);
 *  - a cross-volume move (EXDEV) copies to a temp sibling, renames it into place
 *    atomically, then best-effort removes the source. If the copy fails partway,
 *    the temp is removed and the error re-thrown so the SOURCE stays intact and NO
 *    partial destination is ever published.
 */
export function atomicMoveDir(from: string, to: string): void {
  mkdirSync(dirname(to), { recursive: true });
  const dest = probeDirContent(to);
  if (dest === 'error') throw new Error(`${UNPROBEABLE_DEST_MESSAGE}: ${to}`);
  if (dest === 'absent' && existsSync(to)) {
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
