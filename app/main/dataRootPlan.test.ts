// Tests for dataRootPlan — the PURE data-loss-safe data-root decision (WU-R1).
//
// These lock the fix for the DATA-LOSS vector: a packaged build must NOT resolve
// its default data root to <exeDir>/data (inside $INSTDIR, wiped by the in-place
// NSIS auto-update). Every named branch is covered: override-wins (env + marker),
// no-legacy -> fresh appData, legacy-migrates, appData-occupied (no-clobber), dev
// never migrates, an unsafe override still throws — plus every runMigration branch
// (success / space-abort-loud / move-fails-loud) and the migratedRoot selector.
import { describe, expect, it, vi } from 'vitest';
import { DataRootSecurityError } from './dataRoot';
import {
  type MigrationSeam,
  type PlanDataRootInput,
  migratedRoot,
  planDataRoot,
  runMigration,
} from './dataRootPlan';

const APPDATA = 'C:\\Users\\me\\AppData\\Roaming\\media-studio';
const EXE_DATA = 'C:\\Program Files\\Reframe\\data';
const MARKER = 'D:\\Reframe\\data';
const ENV = 'E:\\override';
const UNC = '\\\\evil-host\\share\\data';

/** Base input: a FRESH packaged install (no override, no legacy, empty appData). */
function base(overrides: Partial<PlanDataRootInput> = {}): PlanDataRootInput {
  return {
    packaged: true,
    legacyExeDataDir: EXE_DATA,
    legacyExeDataExists: false,
    appDataRoot: APPDATA,
    appDataOccupied: false,
    ...overrides,
  };
}

describe('planDataRoot — override wins (unchanged precedence)', () => {
  it('env override wins over everything, verbatim', () => {
    expect(
      planDataRoot(base({ envOverride: ENV, markerContent: MARKER, legacyExeDataExists: true })),
    ).toEqual({ kind: 'use', root: ENV });
  });

  it('data-dir.txt marker wins over the migration (existing user keeps their folder)', () => {
    expect(planDataRoot(base({ markerContent: MARKER, legacyExeDataExists: true }))).toEqual({
      kind: 'use',
      root: MARKER,
    });
  });

  it('trims surrounding whitespace on the chosen override', () => {
    expect(planDataRoot(base({ envOverride: `  ${ENV}  ` }))).toEqual({ kind: 'use', root: ENV });
  });

  it('ignores a whitespace-only override and still resolves the safe home', () => {
    expect(planDataRoot(base({ envOverride: '   ', markerContent: '\t\n' }))).toEqual({
      kind: 'use',
      root: APPDATA,
    });
  });

  it('throws DataRootSecurityError on an unsafe (UNC) override — no silent fallback', () => {
    expect(() => planDataRoot(base({ envOverride: UNC }))).toThrow(DataRootSecurityError);
  });

  it('throws on an unsafe marker even when a legacy tree exists', () => {
    expect(() => planDataRoot(base({ markerContent: UNC, legacyExeDataExists: true }))).toThrow(
      DataRootSecurityError,
    );
  });
});

describe('planDataRoot — packaged default is the SAFE appData home (not <exeDir>/data)', () => {
  it('a FRESH packaged install (no legacy) uses %APPDATA%/media-studio', () => {
    expect(planDataRoot(base())).toEqual({ kind: 'use', root: APPDATA });
  });

  it('NEVER returns the legacy exe-data dir as a fresh default (the data-loss vector)', () => {
    const plan = planDataRoot(base({ legacyExeDataExists: false }));
    expect(plan).toEqual({ kind: 'use', root: APPDATA });
    expect(plan).not.toEqual({ kind: 'use', root: EXE_DATA });
  });
});

describe('planDataRoot — packaged legacy migration (rescue out of $INSTDIR)', () => {
  it('plans a migration when a legacy <exeDir>/data exists and appData is free', () => {
    expect(planDataRoot(base({ legacyExeDataExists: true }))).toEqual({
      kind: 'migrate',
      from: EXE_DATA,
      to: APPDATA,
    });
  });

  it('does NOT clobber an already-occupied appData — uses it directly, legacy left intact', () => {
    expect(planDataRoot(base({ legacyExeDataExists: true, appDataOccupied: true }))).toEqual({
      kind: 'use',
      root: APPDATA,
    });
  });
});

describe('planDataRoot — DEV never migrates (unchanged behavior)', () => {
  it('a dev build with a legacy dir still resolves to appData, no migration', () => {
    expect(planDataRoot(base({ packaged: false, legacyExeDataExists: true }))).toEqual({
      kind: 'use',
      root: APPDATA,
    });
  });

  it('a dev override still wins', () => {
    expect(planDataRoot(base({ packaged: false, markerContent: MARKER }))).toEqual({
      kind: 'use',
      root: MARKER,
    });
  });
});

// --------------------------------------------------------------------------- #
// runMigration — the injected-seam branches (space-abort / move-fail -> loud
// fallback / success). No real filesystem is touched.
// --------------------------------------------------------------------------- #
function seam(overrides: Partial<MigrationSeam> = {}): MigrationSeam {
  return {
    sourceSize: () => 1000,
    destFree: () => 10_000,
    move: vi.fn(),
    warn: vi.fn(),
    ...overrides,
  };
}

describe('runMigration', () => {
  it('moves and returns true when there is enough free space', () => {
    const move = vi.fn();
    const warn = vi.fn();
    expect(runMigration(EXE_DATA, APPDATA, seam({ move, warn }))).toBe(true);
    expect(move).toHaveBeenCalledTimes(1);
    expect(warn).not.toHaveBeenCalled();
  });

  it('ABORTS with a loud warning (no move) when free space is insufficient', () => {
    const move = vi.fn();
    const warn = vi.fn();
    const s = seam({ sourceSize: () => 10_000, destFree: () => 500, move, warn });
    expect(runMigration(EXE_DATA, APPDATA, s)).toBe(false);
    expect(move).not.toHaveBeenCalled();
    expect(warn).toHaveBeenCalledTimes(1);
    expect(warn).toHaveBeenCalledWith(expect.stringContaining('ABORTED'));
    expect(warn).toHaveBeenCalledWith(expect.stringContaining(EXE_DATA));
  });

  it('FAILS loudly (returns false) when the atomic move throws', () => {
    const warn = vi.fn();
    const s = seam({
      move: () => {
        throw new Error('EXDEV boom');
      },
      warn,
    });
    expect(runMigration(EXE_DATA, APPDATA, s)).toBe(false);
    expect(warn).toHaveBeenCalledWith(expect.stringContaining('FAILED'));
    expect(warn).toHaveBeenCalledWith(expect.stringContaining('EXDEV boom'));
  });

  it('FAILS loudly when measuring the source throws (non-Error value)', () => {
    const warn = vi.fn();
    const s = seam({
      sourceSize: () => {
        // biome-ignore lint/complexity/noUselessThrow: exercising the String(err) branch
        throw 'disk gone';
      },
      warn,
    });
    expect(runMigration(EXE_DATA, APPDATA, s)).toBe(false);
    expect(warn).toHaveBeenCalledWith(expect.stringContaining('disk gone'));
  });
});

describe('migratedRoot — final root after the seam ran', () => {
  it('returns the destination when the move succeeded', () => {
    expect(migratedRoot(EXE_DATA, APPDATA, true)).toBe(APPDATA);
  });

  it('returns the legacy source UNCHANGED when the move failed (loud fallback)', () => {
    expect(migratedRoot(EXE_DATA, APPDATA, false)).toBe(EXE_DATA);
  });
});
