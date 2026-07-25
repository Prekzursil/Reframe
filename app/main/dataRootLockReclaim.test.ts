// dataRootLockReclaim.test.ts — the stale-lock reclaim against a REAL filesystem.
//
// WHY a separate file: dataRootLockIo.test.ts mocks `node:fs` wholesale (so the
// per-branch seam behaviour is deterministic). This file deliberately does NOT, so
// the SINGLE-WINNER property of the reclaim is measured against real `linkSync`
// EEXIST semantics in a real temp directory — an independent signal from the mocked
// branch tests, not a re-run of them.
//
// T8 (the defect this locks): the reclaim used to be read -> unlink -> create. The
// unlink was UNCONDITIONAL, so a second copy that had also decided "stale" deleted
// the FIRST copy's freshly-created record, created its own, and passed its own
// read-back — leaving TWO copies each believing they owned the same data root (two
// sidecars racing library.db and the pip env). A reclaim that must first CLAIM a
// victim-keyed sideline name cannot be won twice.
import { describe, expect, it } from 'vitest';
import { existsSync, mkdtempSync, readFileSync, rmSync, unlinkSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import {
  acquireDataRootLock,
  type BootProbe,
  DATA_ROOT_LOCK_FILE,
  type LockIo,
  type LockOwner,
  parseLock,
} from './dataRootLock';
import { createLockIo } from './dataRootLockIo';

const DEAD_HOLDER = '{"pid":200,"time":1,"boot":5000,"host":"hostA"}';
const COPY_A: LockOwner = { pid: 100, boot: 5000, host: 'hostA' };
const COPY_B: LockOwner = { pid: 101, boot: 5000, host: 'hostA' };
/** Every pid reads as DEAD, so a found record is always classified STALE. */
const dead: BootProbe = () => null;

/** A real temp data root seeded with a DEAD holder's lock record. */
function withDataRoot(run: (io: LockIo, lock: string, root: string) => void): void {
  const root = mkdtempSync(join(tmpdir(), 'rf-lockreclaim-'));
  try {
    const lock = join(root, DATA_ROOT_LOCK_FILE);
    writeFileSync(lock, DEAD_HOLDER, 'utf8');
    run(createLockIo({ lockPath: () => lock, dataRoot: () => root }), lock, root);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
}

describe('reclaimLock (real fs) — the sideline name can be claimed only ONCE', () => {
  it('moves the dead record aside and frees the lock path for an exclusive create', () => {
    withDataRoot((io, lock) => {
      expect(io.reclaimLock('.stale-200-5000')).toBe(true);
      expect(existsSync(lock)).toBe(false);
      expect(readFileSync(`${lock}.stale-200-5000`, 'utf8')).toBe(DEAD_HOLDER);
      expect(io.createLock('MINE')).toBe(true);
    });
  });

  it('refuses a SECOND reclaim of the same victim and leaves the live record intact', () => {
    withDataRoot((io, lock) => {
      expect(io.reclaimLock('.stale-200-5000')).toBe(true);
      // Racer 1 has now published its own record at the lock path.
      writeFileSync(lock, '{"pid":100,"time":9,"boot":5000,"host":"hostA"}', 'utf8');

      // Racer 2 (same stale victim, so the same sideline name) tries to reclaim.
      expect(io.reclaimLock('.stale-200-5000')).toBe(false);

      // A bare unlink would have DESTROYED racer 1's live lock here.
      expect(readFileSync(lock, 'utf8')).toBe('{"pid":100,"time":9,"boot":5000,"host":"hostA"}');
    });
  });

  it('refuses when the lockfile is already gone (nothing to move aside)', () => {
    withDataRoot((io, lock) => {
      unlinkSync(lock);
      expect(io.reclaimLock('.stale-200-5000')).toBe(false);
    });
  });
});

describe('acquireDataRootLock over the REAL seam — two copies, one owner', () => {
  it('TOCTOU: copy A reclaims the stale lock and copy B is REFUSED (no double spawn)', () => {
    withDataRoot((io, lock) => {
      // Copy B captured the STALE record before A ran (the racy read) and only now
      // performs its reclaim/create — the exact interleaving that used to double-own.
      const bIo: LockIo = {
        ...io,
        readLock: (() => {
          let first = true;
          return () => {
            if (first) {
              first = false;
              return DEAD_HOLDER;
            }
            return io.readLock();
          };
        })(),
      };

      const a = acquireDataRootLock(io, COPY_A, 10, dead);
      const b = acquireDataRootLock(bIo, COPY_B, 11, dead);

      expect(a).toEqual({ ok: true, heldBy: 200, stale: true });
      expect(b.ok).toBe(false);
      expect([a.ok, b.ok].filter(Boolean)).toHaveLength(1);
      // The on-disk owner is A, and B's pid never reached the lockfile.
      expect(parseLock(readFileSync(lock, 'utf8'))).toEqual({
        pid: 100,
        time: 10,
        boot: 5000,
        host: 'hostA',
      });
    });
  });
});
