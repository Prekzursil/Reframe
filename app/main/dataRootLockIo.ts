// dataRootLockIo.ts — the concrete FILESYSTEM/process seam for the DATA-ROOT lock.
//
// WHY this exists: the pure lock DECISION core lives in dataRootLock.ts (held to
// 100%). The IO it injects — exclusive-create/read/overwrite/remove of the
// lockfile, the `process.kill(pid,0)` liveness probe, the per-boot id, the host id —
// used to be private inside main.ts, which cannot be imported under vitest (main.ts
// runs Electron module-level side effects on import). So the EXACT process/fs seam
// behind the lock had ZERO direct coverage. These are Electron-free (`node:fs`,
// `node:os`, `process`), so they live here and are tested in dataRootLockIo.test.ts
// (mirroring dataRootIo.ts); main.ts just wires them into acquire/releaseDataRootLock.
import { linkSync, mkdirSync, readFileSync, renameSync, unlinkSync, writeFileSync } from 'node:fs';
import { hostname, uptime } from 'node:os';
import type { BootProbe, LockIo, LockOwner } from './dataRootLock';

/**
 * OS liveness probe: `process.kill(pid, 0)` sends no signal but throws when the pid
 * does not exist (`ESRCH` -> dead). `EPERM` means the process EXISTS but is owned by
 * another user — still ALIVE, so the lock is NOT reclaimable. Any non-throw means the
 * pid is alive.
 */
export function isPidAlive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch (err) {
    return (err as NodeJS.ErrnoException).code === 'EPERM';
  }
}

/**
 * Derive a per-BOOT id (epoch seconds of the last boot) from wall-clock `nowMs` and
 * process `uptimeSec`. Because both reference the SAME kernel boot instant, the
 * result is stable across processes on the same boot (independent of WHEN measured)
 * and CHANGES after a reboot — so a lock acquired before a reboot no longer matches,
 * and a pid reused after a reboot is not mistaken for the original holder. Pure so it
 * is directly unit-testable.
 */
export function computeBootId(nowMs: number, uptimeSec: number): number {
  return Math.round(nowMs / 1000 - uptimeSec);
}

// Computed ONCE at module load so it is constant for this process's lifetime (a
// live re-derivation must not drift and make us mistake our own lock for stale).
const BOOT_ID = computeBootId(Date.now(), uptime());

/**
 * The injected {@link BootProbe} (dataRootLock.ts): a holder pid's CURRENT boot id
 * when it is alive, else null. A boot id is machine-global for a given boot, so
 * returning THIS process's BOOT_ID for any live pid is correct — the decision core
 * only counts the holder as live when that id also equals the RECORD's boot id.
 */
export const bootProbe: BootProbe = (pid) => (isPidAlive(pid) ? BOOT_ID : null);

/** This process's full lock identity (pid + per-boot id + host). */
export function selfLockOwner(): LockOwner {
  return { pid: process.pid, boot: BOOT_ID, host: hostname() };
}

/** Path resolvers main.ts injects (keeps this module free of the DATA_ROOT logic). */
export interface LockPaths {
  /** Absolute path of the lockfile (already traversal-guarded by main.ts). */
  lockPath: () => string;
  /** The DATA_ROOT dir to ensure exists before creating/overwriting the lockfile. */
  dataRoot: () => string;
}

/**
 * Build the {@link LockIo} seam the pure acquire/release inject. `createLock` uses
 * the exclusive `'wx'` flag so acquisition is ATOMIC (create-or-EEXIST, no
 * read->decide->write window); a non-EEXIST error (e.g. a permission failure)
 * THROWS rather than being swallowed into a false "no lock" (fail loud).
 */
export function createLockIo(paths: LockPaths): LockIo {
  return {
    createLock: (body) => {
      mkdirSync(paths.dataRoot(), { recursive: true });
      try {
        writeFileSync(paths.lockPath(), body, { encoding: 'utf8', flag: 'wx' });
        return true;
      } catch (err) {
        if ((err as NodeJS.ErrnoException).code === 'EEXIST') return false;
        throw err; // permission/other IO error — fail loud, do NOT treat as free.
      }
    },
    readLock: () => {
      try {
        return readFileSync(paths.lockPath(), 'utf8');
      } catch {
        return undefined; // absent/unreadable -> parseLock treats as "no lock".
      }
    },
    writeLock: (body) => {
      mkdirSync(paths.dataRoot(), { recursive: true });
      writeFileSync(paths.lockPath(), body, 'utf8');
    },
    removeLock: () => {
      try {
        unlinkSync(paths.lockPath());
      } catch {
        /* already gone — best-effort */
      }
    },
    reclaimLock: (sidelineSuffix) => {
      const lock = paths.lockPath();
      const sideline = `${lock}${sidelineSuffix}`;
      try {
        // `linkSync` is the PORTABLE compare-and-swap: it fails with EEXIST when the
        // destination already exists on BOTH Windows and POSIX. Because the suffix is
        // keyed to the DEAD holder's identity (dataRootLock.staleSidelineSuffix), two
        // copies racing to reclaim the same record target the same name and exactly
        // ONE creates the link. The loser returns false and creates nothing — which is
        // what a bare `unlinkSync` could never guarantee (it would happily delete the
        // winner's brand-new record and hand out a second ownership).
        linkSync(lock, sideline);
      } catch (err) {
        const code = (err as NodeJS.ErrnoException).code;
        if (code === 'EEXIST') return false; // another racer already reclaimed it
        if (code === 'ENOENT') return false; // the record is gone — nothing to reclaim
        // Filesystems without hard links (FAT/exFAT, some network shares) report
        // EPERM/ENOSYS/EOPNOTSUPP. Degrade to a plain rename: still a single-winner
        // move on Windows (rename onto an existing path fails) and never worse than
        // the pre-fix unconditional unlink.
        try {
          renameSync(lock, sideline);
        } catch {
          return false; // could not move it aside at all — do NOT claim a reclaim
        }
        return true; // the rename already freed the lock path
      }
      try {
        unlinkSync(lock); // publish the reclaim: the lock path is free for 'wx'
      } catch {
        /* already gone — our sideline link still proves we won the reclaim */
      }
      // NOTE: the sidelined dead record is deliberately LEFT on disk. It is the
      // compare-and-swap token that keeps a later racer out, and its name can never
      // legitimately recur (that pid is dead for this boot, and a reboot changes the
      // boot id), so it is inert — one tiny file, not a growing leak.
      return true;
    },
  };
}
