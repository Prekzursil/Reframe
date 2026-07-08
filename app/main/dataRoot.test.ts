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
  DataRootSecurityError,
  isSafeLocalDataRoot,
  resolveDataRootFrom,
  type ChooseDataRootInput,
  type DataRootIO,
} from './dataRoot';

const APPDATA = 'C:\\Users\\me\\AppData\\Roaming\\media-studio';
const EXE_DATA = 'C:\\Apps\\Reframe\\data';
const MARKER_PATH = 'D:\\MediaStudioData';
const ENV_PATH = 'E:\\override';
// Attacker-influenceable inputs the content-aware selector must REFUSE (A4/R7):
// a UNC share, a Windows device namespace, and a `..` traversal are code-exec
// vectors into the tree the sidecar pip-installs into — never a valid data root.
const UNC_PATH = '\\\\evil-host\\share\\data';
const DEVICE_PATH = '\\\\.\\PhysicalDrive0';
const TRAVERSAL_PATH = 'C:\\Apps\\Reframe\\data\\..\\..\\Windows\\System32';

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

// --------------------------------------------------------------------------- #
// A4 — CONTENT-aware selection (permanent anti-brick). Before auto-picking an
// EMPTY writable <exeDir>/data (tier 3), a provisioned lower tier (appData that
// already holds .first-run-complete.json / library.db) is preferred so a clean
// portable install opens onto the real library instead of a blank one. Multiple
// provisioned roots resolve by the deterministic tier order (never a merge).
// --------------------------------------------------------------------------- #
describe('chooseDataRoot — content-aware provisioning (anti-brick)', () => {
  it('prefers a provisioned appData over an EMPTY writable exe-data dir', () => {
    expect(
      chooseDataRoot(
        base({
          exeDataDir: EXE_DATA,
          exeDataWritable: true,
          exeDataProvisioned: false,
          appDataProvisioned: true,
        }),
      ),
    ).toBe(APPDATA);
  });

  it('keeps the exe-data dir when BOTH roots are provisioned (deterministic tie-break)', () => {
    // Two provisioned roots must NOT merge; the higher-priority portable tier wins.
    expect(
      chooseDataRoot(
        base({
          exeDataDir: EXE_DATA,
          exeDataWritable: true,
          exeDataProvisioned: true,
          appDataProvisioned: true,
        }),
      ),
    ).toBe(EXE_DATA);
  });

  it('keeps the exe-data dir when NEITHER root is provisioned (portable default)', () => {
    expect(
      chooseDataRoot(
        base({
          exeDataDir: EXE_DATA,
          exeDataWritable: true,
          exeDataProvisioned: false,
          appDataProvisioned: false,
        }),
      ),
    ).toBe(EXE_DATA);
  });

  it('keeps the exe-data dir when it is provisioned and appData is not', () => {
    expect(
      chooseDataRoot(
        base({
          exeDataDir: EXE_DATA,
          exeDataWritable: true,
          exeDataProvisioned: true,
          appDataProvisioned: false,
        }),
      ),
    ).toBe(EXE_DATA);
  });

  it('does NOT divert to a provisioned appData when the exe-data tier is not eligible', () => {
    // When exe-data is not auto-picked (not writable), appData is the fallback
    // regardless of provisioning — no diversion branch is reached.
    expect(
      chooseDataRoot(
        base({ exeDataDir: EXE_DATA, exeDataWritable: false, appDataProvisioned: true }),
      ),
    ).toBe(APPDATA);
  });

  it('env override still wins UNCONDITIONALLY over provisioning', () => {
    expect(
      chooseDataRoot(
        base({ envOverride: ENV_PATH, exeDataWritable: true, appDataProvisioned: true }),
      ),
    ).toBe(ENV_PATH);
  });

  it('a data-dir.txt marker still wins UNCONDITIONALLY over provisioning', () => {
    expect(
      chooseDataRoot(
        base({ markerContent: MARKER_PATH, exeDataWritable: true, appDataProvisioned: true }),
      ),
    ).toBe(MARKER_PATH);
  });

  it('treats omitted provisioning flags as un-provisioned (backward compatible)', () => {
    // No flags -> old behavior: a writable exe-data dir is chosen.
    expect(chooseDataRoot(base({ exeDataDir: EXE_DATA, exeDataWritable: true }))).toBe(EXE_DATA);
  });
});

// --------------------------------------------------------------------------- #
// A4/R7 — the marker + MEDIA_STUDIO_CONFIG_DIR are attacker-influenceable, so an
// UNC / device / `..`-traversal value is REFUSED with a clear error rather than
// honored (a code-exec vector into the pip-install tree). Safe absolute LOCAL
// paths pass through unchanged.
// --------------------------------------------------------------------------- #
describe('isSafeLocalDataRoot', () => {
  it('accepts a Windows drive-rooted absolute path', () => {
    expect(isSafeLocalDataRoot('C:\\Apps\\Reframe\\data')).toBe(true);
    expect(isSafeLocalDataRoot('D:/MediaStudioData')).toBe(true);
  });

  it('accepts a POSIX absolute path', () => {
    expect(isSafeLocalDataRoot('/home/me/.config/media-studio')).toBe(true);
  });

  it('rejects a UNC share path', () => {
    expect(isSafeLocalDataRoot(UNC_PATH)).toBe(false);
    expect(isSafeLocalDataRoot('//evil-host/share')).toBe(false);
  });

  it('rejects a Windows device namespace path', () => {
    expect(isSafeLocalDataRoot(DEVICE_PATH)).toBe(false);
    expect(isSafeLocalDataRoot('\\\\?\\C:\\data')).toBe(false);
  });

  it('rejects a path containing a `..` traversal segment', () => {
    expect(isSafeLocalDataRoot(TRAVERSAL_PATH)).toBe(false);
    expect(isSafeLocalDataRoot('/base/../etc')).toBe(false);
  });

  it('rejects a relative path (not absolute)', () => {
    expect(isSafeLocalDataRoot('relative\\data')).toBe(false);
    expect(isSafeLocalDataRoot('data')).toBe(false);
  });
});

describe('chooseDataRoot — refuses an unsafe env override / marker', () => {
  it('throws DataRootSecurityError on a UNC env override (not honored)', () => {
    expect(() => chooseDataRoot(base({ envOverride: UNC_PATH }))).toThrow(DataRootSecurityError);
  });

  it('throws on a device-namespace env override', () => {
    expect(() => chooseDataRoot(base({ envOverride: DEVICE_PATH }))).toThrow(DataRootSecurityError);
  });

  it('throws on a `..`-traversal env override', () => {
    expect(() => chooseDataRoot(base({ envOverride: TRAVERSAL_PATH }))).toThrow(
      DataRootSecurityError,
    );
  });

  it('throws on a UNC marker (a poisoned data-dir.txt)', () => {
    expect(() => chooseDataRoot(base({ markerContent: UNC_PATH }))).toThrow(DataRootSecurityError);
  });

  it('throws on a device-namespace marker', () => {
    expect(() => chooseDataRoot(base({ markerContent: DEVICE_PATH }))).toThrow(
      DataRootSecurityError,
    );
  });

  it('throws on a `..`-traversal marker', () => {
    expect(() => chooseDataRoot(base({ markerContent: TRAVERSAL_PATH }))).toThrow(
      DataRootSecurityError,
    );
  });

  it('the error message names the source and the rejected value', () => {
    let caught: unknown;
    try {
      chooseDataRoot(base({ envOverride: UNC_PATH }));
    } catch (err) {
      caught = err;
    }
    expect(caught).toBeInstanceOf(DataRootSecurityError);
    expect((caught as Error).message).toContain('MEDIA_STUDIO_CONFIG_DIR');
    // The rejected value is surfaced (JSON-escaped) so the error names what it refused.
    expect((caught as Error).message).toContain('evil-host');
  });

  it('still honors a SAFE absolute env override / marker', () => {
    expect(chooseDataRoot(base({ envOverride: ENV_PATH }))).toBe(ENV_PATH);
    expect(chooseDataRoot(base({ markerContent: MARKER_PATH }))).toBe(MARKER_PATH);
  });
});

// --------------------------------------------------------------------------- #
// resolveDataRootFrom threads the provisioning probe through to chooseDataRoot.
// --------------------------------------------------------------------------- #
describe('resolveDataRootFrom — threads the provisioning probe', () => {
  it('prefers a provisioned appData over an empty writable exe-dir (clean-install anti-brick)', () => {
    const isProvisioned = vi.fn((root: string) => root === APPDATA);
    expect(
      resolveDataRootFrom(
        io({ isExeDataWritable: () => true, preferExeDataDir: true, isProvisioned }),
      ),
    ).toBe(APPDATA);
    expect(isProvisioned).toHaveBeenCalledWith(EXE_DATA);
    expect(isProvisioned).toHaveBeenCalledWith(APPDATA);
  });

  it('keeps the writable exe-dir when it is itself provisioned', () => {
    const isProvisioned = vi.fn((root: string) => root === EXE_DATA);
    expect(
      resolveDataRootFrom(
        io({ isExeDataWritable: () => true, preferExeDataDir: true, isProvisioned }),
      ),
    ).toBe(EXE_DATA);
  });

  it('treats every root as un-provisioned when the seam omits isProvisioned', () => {
    // Default predicate (() => false): a writable exe-dir is still chosen.
    expect(resolveDataRootFrom(io({ isExeDataWritable: () => true }))).toBe(EXE_DATA);
  });
});
