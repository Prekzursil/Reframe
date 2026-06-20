// Tests for chooseDataRoot — the pure data-root priority resolver.
//
// The data root is the ONE relocatable folder that holds models/envs/exports/
// proxies/peaks/dubs/voices/feedback. These cover every branch of the priority
// order (env > marker > writable exe-data > appData) plus whitespace/empty
// rejection at each tier, so a blank marker or env can never beat a real path.
import { describe, it, expect, vi } from 'vitest';
import {
  chooseDataRoot,
  DATA_DIR_MARKER,
  resolveDataRootFrom,
  type ChooseDataRootInput,
  type DataRootIO,
} from './dataRoot';

const APPDATA = 'C:\\Users\\me\\AppData\\Roaming\\media-studio';
const EXE_DATA = 'C:\\Apps\\Reframe\\data';
const MARKER_PATH = 'D:\\MediaStudioData';
const ENV_PATH = 'E:\\override';

/** Base input: everything absent except the always-present appData fallback. */
function base(overrides: Partial<ChooseDataRootInput> = {}): ChooseDataRootInput {
  return { appDataRoot: APPDATA, ...overrides };
}

describe('DATA_DIR_MARKER', () => {
  it('is the marker filename next to the executable', () => {
    expect(DATA_DIR_MARKER).toBe('data-dir.txt');
  });
});

describe('chooseDataRoot — priority order', () => {
  it('env override wins over everything', () => {
    expect(
      chooseDataRoot(
        base({
          envOverride: ENV_PATH,
          markerContent: MARKER_PATH,
          exeDataDir: EXE_DATA,
          exeDataWritable: true,
        }),
      ),
    ).toBe(ENV_PATH);
  });

  it('marker wins over a writable exe-data dir and appData', () => {
    expect(
      chooseDataRoot(
        base({ markerContent: MARKER_PATH, exeDataDir: EXE_DATA, exeDataWritable: true }),
      ),
    ).toBe(MARKER_PATH);
  });

  it('uses the exe-data dir only when it is writable', () => {
    expect(chooseDataRoot(base({ exeDataDir: EXE_DATA, exeDataWritable: true }))).toBe(EXE_DATA);
  });

  it('falls back to appData when the exe-data dir is NOT writable', () => {
    expect(chooseDataRoot(base({ exeDataDir: EXE_DATA, exeDataWritable: false }))).toBe(APPDATA);
  });

  it('falls back to appData when no exe-data dir is provided', () => {
    expect(chooseDataRoot(base({ exeDataWritable: true }))).toBe(APPDATA);
  });

  it('falls back to appData when nothing else is set', () => {
    expect(chooseDataRoot(base())).toBe(APPDATA);
  });
});

describe('chooseDataRoot — whitespace / empty candidates are ignored', () => {
  it('ignores a whitespace-only env override and uses the marker', () => {
    expect(chooseDataRoot(base({ envOverride: '   ', markerContent: MARKER_PATH }))).toBe(
      MARKER_PATH,
    );
  });

  it('ignores an empty env override and falls through to appData', () => {
    expect(chooseDataRoot(base({ envOverride: '' }))).toBe(APPDATA);
  });

  it('ignores a whitespace-only marker and uses the writable exe-data dir', () => {
    expect(
      chooseDataRoot(base({ markerContent: '  \n ', exeDataDir: EXE_DATA, exeDataWritable: true })),
    ).toBe(EXE_DATA);
  });

  it('ignores an empty marker and falls through to appData', () => {
    expect(chooseDataRoot(base({ markerContent: '' }))).toBe(APPDATA);
  });

  it('ignores a whitespace-only exe-data dir even when marked writable', () => {
    expect(chooseDataRoot(base({ exeDataDir: '   ', exeDataWritable: true }))).toBe(APPDATA);
  });

  it('trims surrounding whitespace from the chosen value', () => {
    expect(chooseDataRoot(base({ envOverride: `  ${ENV_PATH}  ` }))).toBe(ENV_PATH);
    expect(chooseDataRoot(base({ markerContent: `\t${MARKER_PATH}\n` }))).toBe(MARKER_PATH);
  });
});

// --------------------------------------------------------------------------- #
// resolveDataRootFrom — the IO-seam resolver (G1 preview fix regression lock)
// --------------------------------------------------------------------------- #
function io(overrides: Partial<DataRootIO> = {}): DataRootIO {
  return {
    envOverride: undefined,
    exeDataDir: EXE_DATA,
    appDataRoot: APPDATA,
    readMarker: () => undefined,
    isExeDataWritable: () => false,
    ...overrides,
  };
}

describe('resolveDataRootFrom — marker/exe-dir are consulted UNCONDITIONALLY', () => {
  // G1 REGRESSION (was: the old main.ts gated marker/exe-dir on app.isPackaged,
  // so a DEV run ignored the marker and always resolved %APPDATA% — the empty
  // data folder with no library.json that broke preview + subtitles). There is
  // now NO isPackaged switch: dev resolves the marker root exactly like packaged.
  it('resolves the MARKER root (like packaged) — the dev-now-works fix', () => {
    expect(resolveDataRootFrom(io({ readMarker: () => MARKER_PATH }))).toBe(MARKER_PATH);
  });

  it('resolves a writable exe-data dir when there is no marker', () => {
    expect(resolveDataRootFrom(io({ isExeDataWritable: () => true }))).toBe(EXE_DATA);
  });

  it('falls back to appData only when neither marker nor writable exe-dir exists', () => {
    expect(resolveDataRootFrom(io())).toBe(APPDATA);
  });

  it('lets an explicit env override win over the marker (power-user escape hatch)', () => {
    expect(resolveDataRootFrom(io({ envOverride: ENV_PATH, readMarker: () => MARKER_PATH }))).toBe(
      ENV_PATH,
    );
  });

  it('probes writability against the exe-data dir it was given', () => {
    const isExeDataWritable = vi.fn(() => true);
    expect(resolveDataRootFrom(io({ isExeDataWritable }))).toBe(EXE_DATA);
    expect(isExeDataWritable).toHaveBeenCalledWith(EXE_DATA);
  });
});

// --------------------------------------------------------------------------- #
// DEV exe-dir TRAP (preview blocker root cause) — the writable <exeDir>/data
// auto-pick is PORTABLE-INSTALL-ONLY. In `npm run dev`, process.execPath lives in
// node_modules/electron/dist, so <exeDir>/data is a writable but EMPTY folder with
// no library.json — picking it silently broke preview (empty library -> 404 ->
// blank <video> -> no subtitles). The auto-pick is now gated on preferExeDataDir
// (= app.isPackaged); env + marker stay UNCONDITIONAL so a dev power-user can
// still point at their real data folder.
// --------------------------------------------------------------------------- #
describe('chooseDataRoot — exe-data auto-pick is gated on preferExeDataDir', () => {
  it('uses a writable exe-data dir when preferExeDataDir is true (packaged portable)', () => {
    expect(
      chooseDataRoot(base({ exeDataDir: EXE_DATA, exeDataWritable: true, preferExeDataDir: true })),
    ).toBe(EXE_DATA);
  });

  it('IGNORES a writable exe-data dir when preferExeDataDir is false (the dev trap)', () => {
    // The regression: dev (preferExeDataDir=false) must NOT silently land on the
    // empty node_modules/electron/dist/data — it falls through to appData.
    expect(
      chooseDataRoot(
        base({ exeDataDir: EXE_DATA, exeDataWritable: true, preferExeDataDir: false }),
      ),
    ).toBe(APPDATA);
  });

  it('still honors an explicit env override in dev (preferExeDataDir false)', () => {
    expect(
      chooseDataRoot(
        base({ envOverride: ENV_PATH, exeDataWritable: true, preferExeDataDir: false }),
      ),
    ).toBe(ENV_PATH);
  });

  it('still honors a marker in dev (preferExeDataDir false)', () => {
    expect(
      chooseDataRoot(
        base({ markerContent: MARKER_PATH, exeDataWritable: true, preferExeDataDir: false }),
      ),
    ).toBe(MARKER_PATH);
  });

  it('defaults preferExeDataDir to true when omitted (backward compatible)', () => {
    // Existing callers/tests that never pass the flag keep the portable behavior.
    expect(chooseDataRoot(base({ exeDataDir: EXE_DATA, exeDataWritable: true }))).toBe(EXE_DATA);
  });
});

describe('resolveDataRootFrom — threads preferExeDataDir through to chooseDataRoot', () => {
  it('falls back to appData in dev even when the exe-dir is writable', () => {
    // The end-to-end dev-trap lock at the IO seam: a writable exe-dir is NOT
    // chosen when packaged=false (preferExeDataDir=false).
    expect(
      resolveDataRootFrom(io({ isExeDataWritable: () => true, preferExeDataDir: false })),
    ).toBe(APPDATA);
  });

  it('chooses the writable exe-dir when packaged (preferExeDataDir true)', () => {
    expect(resolveDataRootFrom(io({ isExeDataWritable: () => true, preferExeDataDir: true }))).toBe(
      EXE_DATA,
    );
  });

  it('defaults to portable (preferExeDataDir true) when the seam omits the flag', () => {
    expect(resolveDataRootFrom(io({ isExeDataWritable: () => true }))).toBe(EXE_DATA);
  });
});
