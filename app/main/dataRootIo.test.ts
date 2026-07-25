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
import { dirname, join } from 'node:path';
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
  readStableDataDirMarker,
  resolveDataDirMarker,
  stableDataDirMarkerPath,
  writeDataDirMarker,
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

// --------------------------------------------------------------------------- #
// T13 DATA LOSS ON UPDATE — the chosen data folder used to be persisted ONLY at
// `<exeDir>/data-dir.txt`, and `<exeDir>` IS the NSIS `$INSTDIR` that an in-place
// auto-update REPLACES. After an update the marker was gone, resolution fell back
// to the default, and the user's external library APPEARED LOST. The fix persists
// the choice in the STABLE per-user `userData` area (which no updater touches) and
// FORWARD-MIGRATES an existing legacy marker on first read, so nobody is orphaned.
// --------------------------------------------------------------------------- #
const USER_DATA = '/home/me/AppData/Roaming/Reframe';
const STABLE_MARKER = join(USER_DATA, DATA_DIR_MARKER);
const LEGACY_MARKER = join(FAKE_DIR, DATA_DIR_MARKER);
const CHOSEN = 'D:\\MediaStudioData';

/**
 * Back the mocked node:fs marker reads/writes with an in-memory path->content map
 * so a test can model BOTH marker locations (and an NSIS update deleting one).
 */
function fakeMarkerFiles(initial: Iterable<readonly [string, string]>): Map<string, string> {
  const files = new Map<string, string>(initial);
  vi.mocked(readFileSync).mockImplementation(((path: string) => {
    const value = files.get(String(path));
    if (value === undefined) {
      const err = new Error('ENOENT: no such file') as NodeJS.ErrnoException;
      err.code = 'ENOENT';
      throw err;
    }
    return value;
  }) as never);
  vi.mocked(writeFileSync).mockImplementation(((path: string, body: string) => {
    files.set(String(path), body);
  }) as never);
  return files;
}

describe('stableDataDirMarkerPath', () => {
  it('is <userDataDir>/<DATA_DIR_MARKER>', () => {
    expect(stableDataDirMarkerPath(USER_DATA)).toBe(STABLE_MARKER);
  });

  it('is NOT inside <exeDir> — the dir an NSIS in-place update REPLACES (T13)', () => {
    expect(stableDataDirMarkerPath(USER_DATA)).not.toBe(dataDirMarkerPath());
    expect(stableDataDirMarkerPath(USER_DATA).startsWith(exeDir())).toBe(false);
  });
});

describe('readStableDataDirMarker', () => {
  it('reads the per-user marker file', () => {
    fakeMarkerFiles([[STABLE_MARKER, CHOSEN]]);
    expect(readStableDataDirMarker(USER_DATA)).toBe(CHOSEN);
    expect(readFileSync).toHaveBeenCalledWith(STABLE_MARKER, 'utf8');
  });

  it('returns undefined when the per-user marker is absent/unreadable', () => {
    fakeMarkerFiles([]);
    expect(readStableDataDirMarker(USER_DATA)).toBeUndefined();
  });
});

describe('writeDataDirMarker', () => {
  it('creates the parent dir and writes the value as utf8, returning true', () => {
    expect(writeDataDirMarker(STABLE_MARKER, CHOSEN)).toBe(true);
    expect(mkdirSync).toHaveBeenCalledWith(dirname(STABLE_MARKER), { recursive: true });
    expect(writeFileSync).toHaveBeenCalledWith(STABLE_MARKER, CHOSEN, 'utf8');
  });

  it('returns false (never throws) when the write fails', () => {
    vi.mocked(writeFileSync).mockImplementationOnce(() => {
      throw new Error('EROFS: read-only file system');
    });
    expect(writeDataDirMarker(STABLE_MARKER, CHOSEN)).toBe(false);
  });

  it('returns false (never throws) when the parent dir cannot be created', () => {
    vi.mocked(mkdirSync).mockImplementationOnce(() => {
      throw new Error('EACCES: permission denied');
    });
    expect(writeDataDirMarker(STABLE_MARKER, CHOSEN)).toBe(false);
    expect(writeFileSync).not.toHaveBeenCalled();
  });
});

describe('resolveDataDirMarker — T13 update-survival + legacy forward-migration', () => {
  it('prefers the STABLE per-user marker and never touches the legacy one', () => {
    fakeMarkerFiles([
      [STABLE_MARKER, CHOSEN],
      [LEGACY_MARKER, 'E:\\Stale'],
    ]);
    expect(resolveDataDirMarker(USER_DATA)).toBe(CHOSEN);
    expect(readFileSync).toHaveBeenCalledTimes(1);
    expect(writeFileSync).not.toHaveBeenCalled();
  });

  it('THE FIX: forward-migrates a legacy <exeDir> marker so it survives the next update', () => {
    const files = fakeMarkerFiles([[LEGACY_MARKER, CHOSEN]]);

    // First launch after the fix ships: the legacy value is honored VERBATIM …
    expect(resolveDataDirMarker(USER_DATA)).toBe(CHOSEN);
    // … and written FORWARD into the stable per-user location.
    expect(files.get(STABLE_MARKER)).toBe(CHOSEN);

    // Now simulate the NSIS in-place update: $INSTDIR (and its marker) is REPLACED.
    files.delete(LEGACY_MARKER);

    // T13 REGRESSION LOCK: the user's folder is still resolved (pre-fix this
    // returned undefined and the external library appeared LOST).
    expect(resolveDataDirMarker(USER_DATA)).toBe(CHOSEN);
  });

  it('returns undefined and writes nothing when NEITHER marker exists', () => {
    fakeMarkerFiles([]);
    expect(resolveDataDirMarker(USER_DATA)).toBeUndefined();
    expect(writeFileSync).not.toHaveBeenCalled();
  });

  it('treats a BLANK stable marker as absent and falls through to the legacy one', () => {
    const files = fakeMarkerFiles([
      [STABLE_MARKER, '   \n'],
      [LEGACY_MARKER, CHOSEN],
    ]);
    expect(resolveDataDirMarker(USER_DATA)).toBe(CHOSEN);
    expect(files.get(STABLE_MARKER)).toBe(CHOSEN);
  });

  it('never forward-migrates a BLANK legacy marker (not a real choice)', () => {
    fakeMarkerFiles([[LEGACY_MARKER, '  ']]);
    expect(resolveDataDirMarker(USER_DATA)).toBe('  ');
    expect(writeFileSync).not.toHaveBeenCalled();
  });

  it('returns an UNSAFE legacy value (so chooseDataRoot still REFUSES it) but never copies it forward', () => {
    // A poisoned data-dir.txt must keep raising DataRootSecurityError downstream —
    // and must NOT be propagated into the stable per-user location.
    fakeMarkerFiles([[LEGACY_MARKER, '\\\\evil-host\\share\\data']]);
    expect(resolveDataDirMarker(USER_DATA)).toBe('\\\\evil-host\\share\\data');
    expect(writeFileSync).not.toHaveBeenCalled();
  });

  it('still honors the legacy value when the forward write fails (read-only userData)', () => {
    fakeMarkerFiles([[LEGACY_MARKER, CHOSEN]]);
    vi.mocked(writeFileSync).mockImplementationOnce(() => {
      throw new Error('EACCES: permission denied');
    });
    expect(resolveDataDirMarker(USER_DATA)).toBe(CHOSEN);
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
