// Tests for dataRootIo — the FILESYSTEM seam feeding data-root resolution.
//
// These functions used to be private inside main.ts (un-importable under vitest),
// so the EXACT seam behind the dev "empty writable <exeDir>/data" preview trap had
// no direct coverage. They are Electron-free (process.execPath + node:fs +
// node:path), so we cover every branch here: exe-dir derivation, marker read
// (present / absent-or-unreadable), and the writability probe (writable /
// read-only / probe-cleanup-failure).
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// node:fs is mocked so the writability probe + marker read never touch a real
// disk (deterministic + no side effects on the test runner's filesystem).
vi.mock('node:fs', () => ({
  existsSync: vi.fn(),
  mkdirSync: vi.fn(),
  readFileSync: vi.fn(),
  unlinkSync: vi.fn(),
  writeFileSync: vi.fn(),
}));

import { existsSync, mkdirSync, readFileSync, unlinkSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { DATA_DIR_MARKER } from './dataRoot';
import { FIRST_RUN_COMPLETE_MARKER } from './firstRunGate';
import {
  dataDirMarkerPath,
  exeDataDir,
  exeDir,
  isExeDataWritable,
  isProvisionedRoot,
  PROVISIONING_MARKERS,
  readDataDirMarker,
} from './dataRootIo';

// process.execPath is read-only typed but writable at runtime; stub it per-test
// so exeDir() is deterministic regardless of the machine running the suite.
const REAL_EXEC_PATH = process.execPath;
const FAKE_EXE = '/opt/Reframe/Reframe.exe';
const FAKE_DIR = '/opt/Reframe';

function setExecPath(path: string): void {
  Object.defineProperty(process, 'execPath', { value: path, configurable: true });
}

beforeEach(() => {
  vi.clearAllMocks();
  setExecPath(FAKE_EXE);
});

afterEach(() => {
  setExecPath(REAL_EXEC_PATH);
});

describe('exeDir / exeDataDir / dataDirMarkerPath', () => {
  it('exeDir returns the directory of process.execPath', () => {
    expect(exeDir()).toBe(FAKE_DIR);
  });

  it('exeDataDir is <exeDir>/data', () => {
    expect(exeDataDir()).toBe(join(FAKE_DIR, 'data'));
  });

  it('dataDirMarkerPath is <exeDir>/<DATA_DIR_MARKER>', () => {
    expect(dataDirMarkerPath()).toBe(join(FAKE_DIR, DATA_DIR_MARKER));
  });
});

describe('readDataDirMarker', () => {
  it('returns the marker file contents when it reads successfully', () => {
    // readFileSync(path, 'utf8') returns a string; cast through unknown because
    // the mocked signature unions the no-encoding Buffer overload.
    vi.mocked(readFileSync).mockReturnValue(
      'D:\\MediaStudioData' as unknown as ReturnType<typeof readFileSync>,
    );
    expect(readDataDirMarker()).toBe('D:\\MediaStudioData');
    expect(readFileSync).toHaveBeenCalledWith(join(FAKE_DIR, DATA_DIR_MARKER), 'utf8');
  });

  it('returns undefined when the marker is absent/unreadable (read throws)', () => {
    vi.mocked(readFileSync).mockImplementation(() => {
      throw new Error('ENOENT');
    });
    expect(readDataDirMarker()).toBeUndefined();
  });
});

describe('isExeDataWritable', () => {
  const DIR = '/opt/Reframe/data';

  it('returns true when mkdir + write-probe + cleanup all succeed', () => {
    expect(isExeDataWritable(DIR)).toBe(true);
    expect(mkdirSync).toHaveBeenCalledWith(DIR, { recursive: true });
    expect(writeFileSync).toHaveBeenCalledWith(expect.stringContaining('.write-probe-'), '');
    expect(unlinkSync).toHaveBeenCalledTimes(1);
  });

  it('returns true even when probe cleanup (unlink) fails — cleanup is best-effort', () => {
    vi.mocked(unlinkSync).mockImplementation(() => {
      throw new Error('EBUSY');
    });
    expect(isExeDataWritable(DIR)).toBe(true);
  });

  it('returns false when the dir is read-only (mkdir/write throws)', () => {
    vi.mocked(writeFileSync).mockImplementation(() => {
      throw new Error('EACCES');
    });
    expect(isExeDataWritable(DIR)).toBe(false);
  });
});

describe('isProvisionedRoot (A4 content-aware probe)', () => {
  const ROOT = '/data/root';

  it('includes the first-run + library markers in PROVISIONING_MARKERS', () => {
    expect(PROVISIONING_MARKERS).toContain(FIRST_RUN_COMPLETE_MARKER);
    expect(PROVISIONING_MARKERS).toContain('library.json');
    expect(PROVISIONING_MARKERS).toContain('library.db');
  });

  it('returns false when NO provisioning marker exists at the root', () => {
    vi.mocked(existsSync).mockReturnValue(false);
    expect(isProvisionedRoot(ROOT)).toBe(false);
    // Every candidate marker was probed under the root.
    for (const name of PROVISIONING_MARKERS) {
      expect(existsSync).toHaveBeenCalledWith(join(ROOT, name));
    }
  });

  it('returns true when the first-run-complete marker exists', () => {
    vi.mocked(existsSync).mockImplementation((p) => p === join(ROOT, FIRST_RUN_COMPLETE_MARKER));
    expect(isProvisionedRoot(ROOT)).toBe(true);
  });

  it('returns true when a migrated library.db exists', () => {
    vi.mocked(existsSync).mockImplementation((p) => p === join(ROOT, 'library.db'));
    expect(isProvisionedRoot(ROOT)).toBe(true);
  });

  it('returns true when a legacy library.json exists', () => {
    vi.mocked(existsSync).mockImplementation((p) => p === join(ROOT, 'library.json'));
    expect(isProvisionedRoot(ROOT)).toBe(true);
  });
});
