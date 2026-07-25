// Tests for dataRootLockIo — the FILESYSTEM/process seam behind the DATA-ROOT lock.
//
// These used to be private inside main.ts (un-importable under vitest), so the
// process/fs seam behind the lock had no direct coverage (WU-S1-FIX finding LOW).
// They are Electron-free (process.kill + node:fs + node:os), so we cover every
// branch here: the pid-liveness probe (ESRCH -> dead / EPERM -> alive / no-throw ->
// alive), the pure boot-id derivation, the boot/liveness probe (alive -> boot id /
// dead -> null), the self identity, and the LockIo round-trip (exclusive create -
// created / EEXIST / other-error-throws - read - overwrite - remove).
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// node:fs + node:os are mocked so the seam never touches a real disk and the boot
// id / host are deterministic regardless of the machine running the suite.
vi.mock('node:fs', () => ({
  linkSync: vi.fn(),
  mkdirSync: vi.fn(),
  readFileSync: vi.fn(),
  renameSync: vi.fn(),
  unlinkSync: vi.fn(),
  writeFileSync: vi.fn(),
}));
vi.mock('node:os', () => ({
  hostname: vi.fn(() => 'test-host'),
  uptime: vi.fn(() => 1000),
}));

import { linkSync, mkdirSync, readFileSync, renameSync, unlinkSync, writeFileSync } from 'node:fs';
import {
  bootProbe,
  computeBootId,
  createLockIo,
  isPidAlive,
  selfLockOwner,
} from './dataRootLockIo';

const LOCK_PATH = '/data/root/.reframe-instance.lock';
const DATA_ROOT = '/data/root';
const paths = { lockPath: () => LOCK_PATH, dataRoot: () => DATA_ROOT };

/** Make process.kill(pid, 0) throw an ErrnoException with the given code. */
function killThrows(code: string): void {
  vi.spyOn(process, 'kill').mockImplementation(() => {
    const err = new Error(code) as NodeJS.ErrnoException;
    err.code = code;
    throw err;
  });
}

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('isPidAlive', () => {
  it('ESRCH (no such process) -> dead (false)', () => {
    killThrows('ESRCH');
    expect(isPidAlive(4242)).toBe(false);
  });

  it('EPERM (exists but not ours) -> alive (true)', () => {
    killThrows('EPERM');
    expect(isPidAlive(4242)).toBe(true);
  });

  it('no throw (signal delivered) -> alive (true)', () => {
    vi.spyOn(process, 'kill').mockImplementation(() => true);
    expect(isPidAlive(4242)).toBe(true);
    expect(process.kill).toHaveBeenCalledWith(4242, 0);
  });
});

describe('computeBootId', () => {
  it('derives boot epoch seconds = round(now/1000 - uptime)', () => {
    // now = 2_000_000 ms (2000 s), uptime = 500 s -> boot at 1500 s.
    expect(computeBootId(2_000_000, 500)).toBe(1500);
  });

  it('rounds to the nearest second (sub-second now)', () => {
    expect(computeBootId(1_500_400, 100)).toBe(1400);
  });
});

describe('bootProbe / selfLockOwner', () => {
  it('bootProbe returns the process boot id for a LIVE pid', () => {
    vi.spyOn(process, 'kill').mockImplementation(() => true);
    const boot = bootProbe(123);
    expect(typeof boot).toBe('number');
    expect(boot).toBe(selfLockOwner().boot);
  });

  it('bootProbe returns null for a DEAD pid', () => {
    killThrows('ESRCH');
    expect(bootProbe(123)).toBeNull();
  });

  it('selfLockOwner reports pid + boot id + host', () => {
    const owner = selfLockOwner();
    expect(owner.pid).toBe(process.pid);
    expect(typeof owner.boot).toBe('number');
    expect(owner.host).toBe('test-host');
  });
});

describe('createLockIo.createLock (exclusive)', () => {
  it('returns true + writes with the exclusive wx flag when the file did not exist', () => {
    const io = createLockIo(paths);
    expect(io.createLock('BODY')).toBe(true);
    expect(mkdirSync).toHaveBeenCalledWith(DATA_ROOT, { recursive: true });
    expect(writeFileSync).toHaveBeenCalledWith(LOCK_PATH, 'BODY', {
      encoding: 'utf8',
      flag: 'wx',
    });
  });

  it('returns false when the lockfile already exists (EEXIST)', () => {
    vi.mocked(writeFileSync).mockImplementation(() => {
      const err = new Error('exists') as NodeJS.ErrnoException;
      err.code = 'EEXIST';
      throw err;
    });
    expect(createLockIo(paths).createLock('BODY')).toBe(false);
  });

  it('re-throws a non-EEXIST error (fail loud, never a false "no lock")', () => {
    vi.mocked(writeFileSync).mockImplementation(() => {
      const err = new Error('denied') as NodeJS.ErrnoException;
      err.code = 'EACCES';
      throw err;
    });
    expect(() => createLockIo(paths).createLock('BODY')).toThrow('denied');
  });
});

describe('createLockIo.readLock', () => {
  it('returns the lockfile contents on a successful read', () => {
    vi.mocked(readFileSync).mockReturnValue('BODY' as unknown as ReturnType<typeof readFileSync>);
    expect(createLockIo(paths).readLock()).toBe('BODY');
    expect(readFileSync).toHaveBeenCalledWith(LOCK_PATH, 'utf8');
  });

  it('returns undefined when the lockfile is absent/unreadable (read throws)', () => {
    vi.mocked(readFileSync).mockImplementation(() => {
      throw new Error('ENOENT');
    });
    expect(createLockIo(paths).readLock()).toBeUndefined();
  });
});

describe('createLockIo.writeLock', () => {
  it('ensures the data root then overwrites the lockfile', () => {
    createLockIo(paths).writeLock('BODY');
    expect(mkdirSync).toHaveBeenCalledWith(DATA_ROOT, { recursive: true });
    expect(writeFileSync).toHaveBeenCalledWith(LOCK_PATH, 'BODY', 'utf8');
  });
});

describe('createLockIo.removeLock', () => {
  it('unlinks the lockfile', () => {
    createLockIo(paths).removeLock();
    expect(unlinkSync).toHaveBeenCalledWith(LOCK_PATH);
  });

  it('swallows an unlink failure (best-effort — already gone)', () => {
    vi.mocked(unlinkSync).mockImplementation(() => {
      throw new Error('EBUSY');
    });
    expect(() => createLockIo(paths).removeLock()).not.toThrow();
  });
});

// --------------------------------------------------------------------------- #
// T8: the stale-lock reclaim seam. `removeLock` (a bare unlink) cannot elect a
// winner — two copies could each delete the other's fresh record and each pass its
// own read-back. `reclaimLock` moves the dead record aside under a VICTIM-keyed
// name using `linkSync`, whose EEXIST is a portable compare-and-swap: exactly one
// racer creates that link, so exactly one reclaims.
// --------------------------------------------------------------------------- #
const SIDELINE = `${LOCK_PATH}.stale-200-5000`;

/** Make one node:fs export throw an ErrnoException with the given code. */
function fsThrows(fn: { mockImplementation: (impl: () => never) => unknown }, code: string): void {
  fn.mockImplementation((() => {
    const err = new Error(code) as NodeJS.ErrnoException;
    err.code = code;
    throw err;
  }) as () => never);
}

describe('createLockIo.reclaimLock', () => {
  it('hard-links the lockfile to the victim-keyed sideline, then frees the lock path', () => {
    expect(createLockIo(paths).reclaimLock('.stale-200-5000')).toBe(true);
    expect(linkSync).toHaveBeenCalledWith(LOCK_PATH, SIDELINE);
    expect(unlinkSync).toHaveBeenCalledWith(LOCK_PATH);
    expect(renameSync).not.toHaveBeenCalled();
  });

  it('returns FALSE when the sideline already exists (EEXIST) — we LOST the race', () => {
    fsThrows(vi.mocked(linkSync), 'EEXIST');
    expect(createLockIo(paths).reclaimLock('.stale-200-5000')).toBe(false);
    // Critically: it must NOT touch the lockfile a winning racer may already own.
    expect(unlinkSync).not.toHaveBeenCalled();
    expect(renameSync).not.toHaveBeenCalled();
  });

  it('returns FALSE when the lockfile is already gone (ENOENT) — nothing to reclaim', () => {
    fsThrows(vi.mocked(linkSync), 'ENOENT');
    expect(createLockIo(paths).reclaimLock('.stale-200-5000')).toBe(false);
    expect(unlinkSync).not.toHaveBeenCalled();
  });

  it('falls back to rename on a filesystem without hard links (EPERM)', () => {
    // FAT/exFAT/some network shares reject linkSync. Rename still moves the record
    // aside (and on Windows rename-onto-existing fails, so it stays single-winner).
    fsThrows(vi.mocked(linkSync), 'EPERM');
    expect(createLockIo(paths).reclaimLock('.stale-200-5000')).toBe(true);
    expect(renameSync).toHaveBeenCalledWith(LOCK_PATH, SIDELINE);
    expect(unlinkSync).not.toHaveBeenCalled(); // the rename already freed the path
  });

  it('returns FALSE when the rename fallback also fails (never a false reclaim)', () => {
    fsThrows(vi.mocked(linkSync), 'EPERM');
    fsThrows(vi.mocked(renameSync), 'EACCES');
    expect(createLockIo(paths).reclaimLock('.stale-200-5000')).toBe(false);
  });

  it('still reports the reclaim when freeing the lock path fails (the link proves the win)', () => {
    fsThrows(vi.mocked(unlinkSync), 'EBUSY');
    expect(createLockIo(paths).reclaimLock('.stale-200-5000')).toBe(true);
  });
});
