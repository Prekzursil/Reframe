// Tests for dataRootMigrateIo — the concrete node:fs seam behind the WU-R1 legacy
// data-root migration. These run against a REAL temp directory (not mocks) so the
// predicates + the atomic same-volume move are exercised end-to-end honestly.
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { atomicMoveDir, dirHasContent, dirSizeBytes, freeSpaceBytes } from './dataRootMigrateIo';

let root: string;

beforeEach(() => {
  root = mkdtempSync(join(tmpdir(), 'rf-datamove-'));
});

afterEach(() => {
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
});
