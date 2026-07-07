// Tests for dataRootMigrateIo — the concrete node:fs seam behind the WU-R1 legacy
// data-root migration. These run against a REAL temp directory (not mocks) so the
// predicates + the atomic same-volume move are exercised end-to-end honestly.
//
// node:fs is mocked as a PASSTHROUGH: every export delegates to the real
// implementation by default (so the real-disk tests above stay honest), and a few
// seams (renameSync/cpSync/readdirSync/statSync) are spyable so the SAFETY-CRITICAL
// error/cross-volume branches — the ones that can NEVER be provoked on a normal
// same-volume disk — are exercised deterministically. Fault injection is per-test
// and reset in afterEach, so the default behaviour everywhere else stays real.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// Holder for the real node:fs functions, populated by the mock factory. `vi.hoisted`
// makes it safe to reference from inside the (hoisted) vi.mock factory.
const real = vi.hoisted(
  () =>
    ({}) as Record<
      'renameSync' | 'cpSync' | 'readdirSync' | 'statSync',
      (...args: never[]) => unknown
    >,
);

vi.mock('node:fs', async (importOriginal) => {
  const actual = await importOriginal<typeof import('node:fs')>();
  real.renameSync = actual.renameSync as never;
  real.cpSync = actual.cpSync as never;
  real.readdirSync = actual.readdirSync as never;
  real.statSync = actual.statSync as never;
  return {
    ...actual,
    renameSync: vi.fn(actual.renameSync),
    cpSync: vi.fn(actual.cpSync),
    readdirSync: vi.fn(actual.readdirSync),
    statSync: vi.fn(actual.statSync),
  };
});

import {
  cpSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  renameSync,
  rmSync,
  statSync,
  writeFileSync,
} from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { atomicMoveDir, dirHasContent, dirSizeBytes, freeSpaceBytes } from './dataRootMigrateIo';

let root: string;

beforeEach(() => {
  root = mkdtempSync(join(tmpdir(), 'rf-datamove-'));
});

afterEach(() => {
  // Drop any fault injection and restore the passthrough default on every seam so
  // the next test starts against a fully real fs.
  vi.mocked(renameSync)
    .mockReset()
    .mockImplementation(real.renameSync as never);
  vi.mocked(cpSync)
    .mockReset()
    .mockImplementation(real.cpSync as never);
  vi.mocked(readdirSync)
    .mockReset()
    .mockImplementation(real.readdirSync as never);
  vi.mocked(statSync)
    .mockReset()
    .mockImplementation(real.statSync as never);
  rmSync(root, { recursive: true, force: true });
});

describe('dirHasContent', () => {
  it('is false for a path that does not exist', () => {
    expect(dirHasContent(join(root, 'missing'))).toBe(false);
  });

  it('is false for a regular file (not a directory)', () => {
    const file = join(root, 'file.txt');
    writeFileSync(file, 'x');
    expect(dirHasContent(file)).toBe(false);
  });

  it('is false for an empty directory', () => {
    const dir = join(root, 'empty');
    mkdirSync(dir);
    expect(dirHasContent(dir)).toBe(false);
  });

  it('is true for a directory with at least one entry', () => {
    const dir = join(root, 'full');
    mkdirSync(dir);
    writeFileSync(join(dir, 'library.db'), 'data');
    expect(dirHasContent(dir)).toBe(true);
  });

  it('is false when the directory listing throws (stat/read error is swallowed)', () => {
    // A real, populated directory whose listing blows up (e.g. EACCES/EIO) — the
    // conservative default is "no content", NEVER an unhandled throw that would
    // crash the migration decision.
    const dir = join(root, 'unreadable');
    mkdirSync(dir);
    writeFileSync(join(dir, 'library.db'), 'data');
    vi.mocked(readdirSync).mockImplementationOnce((() => {
      const err = new Error('EACCES: permission denied') as NodeJS.ErrnoException;
      err.code = 'EACCES';
      throw err;
    }) as never);
    expect(dirHasContent(dir)).toBe(false);
  });
});

describe('dirSizeBytes', () => {
  it('sums the sizes of every file across nested subdirectories', () => {
    const dir = join(root, 'tree');
    mkdirSync(join(dir, 'sub'), { recursive: true });
    writeFileSync(join(dir, 'a.bin'), Buffer.alloc(100));
    writeFileSync(join(dir, 'sub', 'b.bin'), Buffer.alloc(250));
    expect(dirSizeBytes(dir)).toBe(350);
  });

  it('is zero for an empty directory', () => {
    const dir = join(root, 'nada');
    mkdirSync(dir);
    expect(dirSizeBytes(dir)).toBe(0);
  });

  it('counts a file that vanishes mid-walk as zero and still sums the rest', () => {
    // Race window: readdir sees the file, but stat fails because it was deleted
    // between listing and sizing. That file must contribute 0, not throw — the walk
    // continues and still totals the surviving files.
    const dir = join(root, 'racy');
    mkdirSync(dir);
    writeFileSync(join(dir, 'kept.bin'), Buffer.alloc(120));
    writeFileSync(join(dir, 'gone.bin'), Buffer.alloc(9999));
    vi.mocked(statSync).mockImplementation(((path: Parameters<typeof statSync>[0]) => {
      if (String(path).endsWith('gone.bin')) {
        const err = new Error('ENOENT: file vanished mid-walk') as NodeJS.ErrnoException;
        err.code = 'ENOENT';
        throw err;
      }
      return (real.statSync as typeof statSync)(path);
    }) as never);
    expect(dirSizeBytes(dir)).toBe(120);
  });
});

describe('freeSpaceBytes', () => {
  it('reports a positive number of available bytes for an existing volume', () => {
    expect(freeSpaceBytes(root)).toBeGreaterThan(0);
  });
});

describe('atomicMoveDir', () => {
  it('moves a directory tree to a fresh destination (same volume)', () => {
    const from = join(root, 'src');
    const to = join(root, 'nested', 'dst');
    mkdirSync(join(from, 'envs'), { recursive: true });
    writeFileSync(join(from, 'library.db'), 'DB');
    writeFileSync(join(from, 'envs', 'marker'), 'M');

    atomicMoveDir(from, to);

    expect(existsSync(from)).toBe(false);
    expect(readFileSync(join(to, 'library.db'), 'utf8')).toBe('DB');
    expect(readFileSync(join(to, 'envs', 'marker'), 'utf8')).toBe('M');
  });

  it('replaces a pre-existing EMPTY destination before moving into it', () => {
    const from = join(root, 'src2');
    const to = join(root, 'dst2');
    mkdirSync(from);
    writeFileSync(join(from, 'f'), 'v');
    mkdirSync(to); // empty destination already present

    atomicMoveDir(from, to);

    expect(readFileSync(join(to, 'f'), 'utf8')).toBe('v');
    expect(existsSync(from)).toBe(false);
  });

  it('rethrows a non-EXDEV rename error WITHOUT staging any copy (source untouched)', () => {
    // A same-volume rename that fails for a reason OTHER than cross-device (e.g.
    // EPERM/EBUSY) is a real failure, not a fallback trigger: it must propagate
    // immediately, never enter the copy-staging path, and leave the source intact.
    const from = join(root, 'esrc');
    const to = join(root, 'nested', 'edst');
    mkdirSync(from);
    writeFileSync(join(from, 'library.db'), 'DB');

    vi.mocked(renameSync).mockImplementationOnce((() => {
      const err = new Error('EPERM: operation not permitted') as NodeJS.ErrnoException;
      err.code = 'EPERM';
      throw err;
    }) as never);

    expect(() => atomicMoveDir(from, to)).toThrow('EPERM: operation not permitted');
    expect(cpSync).not.toHaveBeenCalled();
    expect(existsSync(to)).toBe(false);
    expect(existsSync(`${to}.migrating-${process.pid}`)).toBe(false);
    expect(readFileSync(join(from, 'library.db'), 'utf8')).toBe('DB');
  });

  it('cross-volume: stages a copy, publishes it with an atomic rename, and removes the source', () => {
    // Force the same-volume rename to report EXDEV so control enters the staging
    // path — the ONLY branch where a partial move is even possible. Only the
    // from->to publish is simulated cross-volume (mockImplementationOnce); the
    // staging->to publish rename then delegates to the REAL fs.
    const from = join(root, 'xsrc');
    const to = join(root, 'nested', 'xdst');
    mkdirSync(join(from, 'envs'), { recursive: true });
    writeFileSync(join(from, 'library.db'), 'DB');
    writeFileSync(join(from, 'envs', 'marker'), 'M');

    vi.mocked(renameSync).mockImplementationOnce((() => {
      const err = new Error('EXDEV: cross-device link not permitted') as NodeJS.ErrnoException;
      err.code = 'EXDEV';
      throw err;
    }) as never);

    atomicMoveDir(from, to);

    // SUCCESS: copied to the destination, source removed, no staging left behind.
    expect(existsSync(from)).toBe(false);
    expect(readFileSync(join(to, 'library.db'), 'utf8')).toBe('DB');
    expect(readFileSync(join(to, 'envs', 'marker'), 'utf8')).toBe('M');
    expect(existsSync(`${to}.migrating-${process.pid}`)).toBe(false);
  });

  it('cross-volume: a copy failure removes the staging dir and rethrows with the source FULLY intact', () => {
    // The atomic / never-partial property: if the cross-volume copy dies partway,
    // the half-written staging dir is removed, NO destination is ever published, the
    // error is rethrown, and the legacy source is left completely untouched.
    const from = join(root, 'psrc');
    const to = join(root, 'nested', 'pdst');
    mkdirSync(join(from, 'envs'), { recursive: true });
    writeFileSync(join(from, 'library.db'), 'DB');
    writeFileSync(join(from, 'envs', 'marker'), 'M');
    const staging = `${to}.migrating-${process.pid}`;

    vi.mocked(renameSync).mockImplementationOnce((() => {
      const err = new Error('EXDEV: cross-device link not permitted') as NodeJS.ErrnoException;
      err.code = 'EXDEV';
      throw err;
    }) as never);
    vi.mocked(cpSync).mockImplementationOnce(((_src: string, dest: string) => {
      // Simulate a partial copy: the staging dir starts filling, then the copy dies.
      mkdirSync(dest, { recursive: true });
      writeFileSync(join(dest, 'partial'), 'x');
      const err = new Error('ENOSPC: no space left on device') as NodeJS.ErrnoException;
      err.code = 'ENOSPC';
      throw err;
    }) as never);

    expect(() => atomicMoveDir(from, to)).toThrow('ENOSPC: no space left on device');

    // Never a partial destination; staging cleaned up; source completely intact.
    expect(existsSync(staging)).toBe(false);
    expect(existsSync(to)).toBe(false);
    expect(readFileSync(join(from, 'library.db'), 'utf8')).toBe('DB');
    expect(readFileSync(join(from, 'envs', 'marker'), 'utf8')).toBe('M');
  });
});
