// Tests for chooseDataRoot — the pure data-root priority resolver.
//
// The data root is the ONE relocatable folder that holds models/envs/exports/
// proxies/peaks/dubs/voices/feedback. These cover every branch of the priority
// order (env > marker > writable exe-data > appData) plus whitespace/empty
// rejection at each tier, so a blank marker or env can never beat a real path.
import { describe, it, expect } from 'vitest';
import { chooseDataRoot, DATA_DIR_MARKER, type ChooseDataRootInput } from './dataRoot';

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
