// installerSeed.test.ts — the NSIS installer -> first-run PROFILE handoff (WU-I1).
//
// Two jobs, both mechanical:
//   (1) the ADOPTION policy (installerSeed.ts) — when a seed the installer wrote is
//       copied into the resolved data root, and (critically) when it is NOT, because
//       an EXISTING install must upgrade without re-provisioning or losing its choice;
//   (2) a cross-file CONFORMANCE gate over build/installer.nsh — the component page's
//       profile ids, feature-pack ids, labels and the seed filename are pinned against
//       installProfiles.ts, the single source of truth. Same pattern as
//       installProfiles.test.ts pinning bootstrap.py. Without this the NSIS page and
//       the app's profile map are two hand-maintained lists that silently drift, and
//       a drifted id resolves to `null` at runtime = the picker reappears after an
//       unattended install (the exact bug this feature exists to remove).
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join, resolve } from 'node:path';
import {
  INSTALLER_PROFILE_SEED_FILE,
  UNINSTALL_DATA_DIR_MARKER,
  UNINSTALL_DATA_ROOT_DIRNAME,
  UNINSTALL_REMOVABLE_MODEL_DIRS,
  UNINSTALL_USER_DATA_DIRNAME,
  adoptInstallerProfileSeed,
  installerSeedPath,
  parseInstallerSeed,
  shouldAwaitProfileChoice,
  type InstallerSeedIo,
} from './installerSeed';
import {
  BUNDLE_IDS,
  INSTALL_BUNDLES,
  INSTALL_PROFILES,
  INSTALL_PROFILE_FILE,
  INSTALL_PROFILE_IDS,
  type PersistedInstallProfile,
} from './installProfiles';
import { DATA_DIR_MARKER } from './dataRoot';

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(HERE, '..', '..');
const INSTALLER_NSH = resolve(REPO_ROOT, 'build', 'installer.nsh');
const ELECTRON_BUILDER_YML = resolve(REPO_ROOT, 'electron-builder.yml');

/** Extract a `!define NAME "value"` from an NSIS source. */
function nshDefine(src: string, name: string): string {
  const m = src.match(new RegExp(`^\\s*!define\\s+${name}\\s+"([^"]*)"`, 'm'));
  if (!m) throw new Error(`!define ${name} not found in installer.nsh`);
  return m[1];
}

/** A `!define NAME "a|b|c"` id list, split on `|`. */
function nshIdList(src: string, name: string): string[] {
  const raw = nshDefine(src, name);
  return raw === '' ? [] : raw.split('|');
}

// ---------------------------------------------------------------------------
// (1) the adoption policy
// ---------------------------------------------------------------------------

interface SeedFixture {
  readonly io: InstallerSeedIo;
  readonly written: PersistedInstallProfile[];
}

function fixture(over: Partial<InstallerSeedIo> = {}, writeOk = true): SeedFixture {
  const written: PersistedInstallProfile[] = [];
  const io: InstallerSeedIo = {
    seedPath: 'C:\\Program Files\\Reframe\\.first-run-profile.json',
    dataRootProfilePath: 'C:\\Users\\u\\AppData\\Roaming\\media-studio\\.first-run-profile.json',
    readSeed: () => JSON.stringify({ profile: 'full', bundles: [] }),
    dataRootProfileExists: () => false,
    writeDataRootProfile: (record) => {
      written.push(record);
      return writeOk;
    },
    ...over,
  };
  return { io, written };
}

describe('adoptInstallerProfileSeed — the installer choice reaches the data root', () => {
  it('ADOPTS a valid seed on a fresh install (no profile at the data root yet)', () => {
    const { io, written } = fixture();
    expect(adoptInstallerProfileSeed(io)).toEqual({
      outcome: 'adopted',
      profile: { profile: 'full', bundles: [] },
    });
    expect(written).toEqual([{ profile: 'full', bundles: [] }]);
  });

  it('adopts a Custom seed with its feature packs', () => {
    const { io, written } = fixture({
      readSeed: () => JSON.stringify({ profile: 'custom', bundles: ['ai-director'] }),
    });
    expect(adoptInstallerProfileSeed(io).outcome).toBe('adopted');
    expect(written).toEqual([{ profile: 'custom', bundles: ['ai-director'] }]);
  });

  it('BACKWARD COMPAT: never overwrites an existing choice (an upgrade keeps its profile)', () => {
    const { io, written } = fixture({ dataRootProfileExists: () => true });
    expect(adoptInstallerProfileSeed(io)).toEqual({ outcome: 'already-chosen', profile: null });
    expect(written).toEqual([]);
  });

  it('is a NO-OP when the seed IS the data-root profile (same resolved path)', () => {
    const same = 'C:\\Users\\u\\AppData\\Roaming\\media-studio\\.first-run-profile.json';
    const { io, written } = fixture({ seedPath: same, dataRootProfilePath: same });
    expect(adoptInstallerProfileSeed(io)).toEqual({ outcome: 'same-path', profile: null });
    expect(written).toEqual([]);
  });

  it('treats the same path case-insensitively (Windows paths differ only in case)', () => {
    const { io, written } = fixture({
      seedPath: 'C:\\Users\\u\\AppData\\Roaming\\media-studio\\.first-run-profile.json',
      dataRootProfilePath: 'c:\\users\\u\\appdata\\roaming\\media-studio\\.first-run-profile.json',
    });
    expect(adoptInstallerProfileSeed(io).outcome).toBe('same-path');
    expect(written).toEqual([]);
  });

  it('reports no-seed when the installer wrote nothing (a portable / zip build)', () => {
    const { io, written } = fixture({ readSeed: () => undefined });
    expect(adoptInstallerProfileSeed(io)).toEqual({ outcome: 'no-seed', profile: null });
    expect(written).toEqual([]);
  });

  it('reports invalid-seed on corrupt JSON — the picker still appears, never a wrong set', () => {
    const { io, written } = fixture({ readSeed: () => '{not json' });
    expect(adoptInstallerProfileSeed(io)).toEqual({ outcome: 'invalid-seed', profile: null });
    expect(written).toEqual([]);
  });

  it('reports invalid-seed on an unknown profile id (a drifted installer)', () => {
    const { io } = fixture({ readSeed: () => JSON.stringify({ profile: 'everything' }) });
    expect(adoptInstallerProfileSeed(io).outcome).toBe('invalid-seed');
  });

  it('reports write-failed (never throws) when the data root is not writable', () => {
    const { io } = fixture({}, false);
    expect(adoptInstallerProfileSeed(io)).toEqual({ outcome: 'write-failed', profile: null });
  });

  it('never throws when readSeed itself throws (an unreadable install dir)', () => {
    const { io } = fixture({
      readSeed: () => {
        throw new Error('EACCES');
      },
    });
    expect(adoptInstallerProfileSeed(io)).toEqual({ outcome: 'no-seed', profile: null });
  });

  it('never throws when the existence probe throws', () => {
    const { io } = fixture({
      dataRootProfileExists: () => {
        throw new Error('EACCES');
      },
    });
    expect(adoptInstallerProfileSeed(io).outcome).toBe('already-chosen');
  });

  it('never throws when the write itself throws', () => {
    const { io } = fixture({
      writeDataRootProfile: () => {
        throw new Error('EACCES');
      },
    });
    expect(adoptInstallerProfileSeed(io).outcome).toBe('write-failed');
  });
});

describe('parseInstallerSeed', () => {
  it('parses a valid body into the persisted record', () => {
    expect(parseInstallerSeed('{"profile":"minimum","bundles":[]}')).toEqual({
      profile: 'minimum',
      bundles: [],
    });
  });

  it('drops unknown bundles rather than failing the whole seed', () => {
    expect(parseInstallerSeed('{"profile":"custom","bundles":["transcription","nope"]}')).toEqual({
      profile: 'custom',
      bundles: ['transcription'],
    });
  });

  it('returns null for undefined / corrupt / legacy bodies', () => {
    expect(parseInstallerSeed(undefined)).toBeNull();
    expect(parseInstallerSeed('')).toBeNull();
    expect(parseInstallerSeed('[]')).toBeNull();
    expect(parseInstallerSeed('{"profile":1}')).toBeNull();
  });
});

describe('shouldAwaitProfileChoice — when the in-app picker still has to ask', () => {
  it('skips the picker on the launch that adopted an installer choice (unattended)', () => {
    expect(shouldAwaitProfileChoice(true, 'first-ever', true)).toBe(false);
  });

  it('still asks on a first-ever run with no installer choice (the pre-WU-I1 path)', () => {
    expect(shouldAwaitProfileChoice(true, 'first-ever', false)).toBe(true);
  });

  it('RE-ASKS after a failed first run, even though a profile is already persisted', () => {
    // The regression this predicate exists to prevent: keying off "a profile exists at
    // the data root" would make a first run that died mid-download silently retry the
    // SAME set on the next launch, with no way back to the chooser to pick a smaller
    // one. Only an adoption performed on THIS launch suppresses the picker.
    expect(shouldAwaitProfileChoice(true, 'first-ever', false)).toBe(true);
  });

  it('never asks on a silent re-bootstrap (it replays the persisted profile)', () => {
    expect(shouldAwaitProfileChoice(true, 're-bootstrap', false)).toBe(false);
    expect(shouldAwaitProfileChoice(true, 're-bootstrap', true)).toBe(false);
  });

  it('never asks when there is no first-run work at all', () => {
    expect(shouldAwaitProfileChoice(false, 'none', false)).toBe(false);
    expect(shouldAwaitProfileChoice(false, 'first-ever', false)).toBe(false);
  });
});

describe('installerSeedPath', () => {
  it('is the seed file inside the install directory', () => {
    expect(installerSeedPath('C:\\Program Files\\Reframe')).toBe(
      join('C:\\Program Files\\Reframe', INSTALLER_PROFILE_SEED_FILE),
    );
  });

  it('reuses the app profile filename VERBATIM (one schema, one name)', () => {
    expect(INSTALLER_PROFILE_SEED_FILE).toBe(INSTALL_PROFILE_FILE);
  });
});

// ---------------------------------------------------------------------------
// (2) build/installer.nsh <-> installProfiles.ts conformance
// ---------------------------------------------------------------------------

describe('build/installer.nsh conforms to installProfiles.ts (no hand-maintained drift)', () => {
  const nsh = readFileSync(INSTALLER_NSH, 'utf8');

  it('offers exactly the app profile ids, in the same order', () => {
    expect(nshIdList(nsh, 'REFRAME_PROFILE_IDS')).toEqual([...INSTALL_PROFILE_IDS]);
  });

  it('offers exactly the app feature-pack ids, in the same order', () => {
    expect(nshIdList(nsh, 'REFRAME_BUNDLE_IDS')).toEqual([...BUNDLE_IDS]);
  });

  it('writes the SAME seed filename the app reads', () => {
    expect(nshDefine(nsh, 'REFRAME_PROFILE_SEED_FILE')).toBe(INSTALLER_PROFILE_SEED_FILE);
  });

  it('defaults to the profile the app marks recommended', () => {
    const recommended = INSTALL_PROFILES.find((p) => p.recommended);
    expect(nshDefine(nsh, 'REFRAME_PROFILE_DEFAULT')).toBe(recommended?.id);
  });

  it('shows each profile under the app label (same words in the installer and the app)', () => {
    for (const profile of INSTALL_PROFILES) {
      expect(nsh).toContain(profile.label);
    }
  });

  it('shows each feature pack under the app label', () => {
    for (const bundle of INSTALL_BUNDLES) {
      expect(nsh).toContain(bundle.label);
    }
  });

  it('emits the persisted schema keys (profile + bundles)', () => {
    // NSIS spells a literal double quote `$\"`, so the JSON the installer writes is
    // `"profile"` / `"bundles"` — the exact two keys parsePersistedInstallProfile reads.
    expect(nsh).toContain('$\\"profile$\\"');
    expect(nsh).toContain('$\\"bundles$\\"');
  });

  it('hooks the electron-builder macros it must (page + install-time write)', () => {
    expect(nsh).toMatch(/^!macro customPageAfterChangeDir$/m);
    expect(nsh).toMatch(/^!macro customInstall$/m);
  });

  it('does NOT bundle models into the installer (on-demand only — the NSIS 2 GB ceiling)', () => {
    // A component page that shipped model bytes would need `File` directives for
    // them; the packs are asset NAMES routed to bootstrap.py, never payload.
    expect(nsh).not.toMatch(/^\s*File\s/m);
  });
});

// ---------------------------------------------------------------------------
// (3) the UNINSTALL keep-vs-remove contract (WU-L7)
// ---------------------------------------------------------------------------
//
// Same job as block (2), other direction. The uninstaller has to name the data
// root, the Electron userData folder and the marker file in NSIS — three path
// literals the app also owns in TypeScript. installerSeed.ts holds the single
// declaration and these tests pin BOTH sides of it: the TS constants against the
// app's own sources, and build/installer.nsh against the TS constants. Without
// that chain the uninstaller becomes a second, silently-drifting implementation
// of the data-root path policy — exactly what installerSeed.ts's header refuses
// to allow for the install direction.

/** The body of a `!macro NAME … !macroend` block. */
function nshMacroBody(src: string, name: string): string {
  const m = src.match(new RegExp(`^!macro ${name}$([\\s\\S]*?)^!macroend$`, 'm'));
  if (!m) throw new Error(`!macro ${name} not found in installer.nsh`);
  return m[1];
}

describe('uninstall data contract — installerSeed.ts owns the path literals', () => {
  it('reuses the app data-folder marker filename VERBATIM (one name, one owner)', () => {
    expect(UNINSTALL_DATA_DIR_MARKER).toBe(DATA_DIR_MARKER);
  });

  it('names the SAME appData home main.ts resolves', () => {
    // main.ts resolveDataRoot(): join(app.getPath('appData'), 'media-studio').
    // brand.test.ts already pins that literal as un-renameable; this pins the
    // uninstaller to the same string rather than a copy of it.
    const main = readFileSync(resolve(REPO_ROOT, 'app', 'main', 'main.ts'), 'utf8');
    expect(main).toContain(`join(app.getPath('appData'), '${UNINSTALL_DATA_ROOT_DIRNAME}')`);
  });

  it('names the Electron userData folder (= package.json productName)', () => {
    // Electron prefers productName over name for app.getPath('userData'), so the
    // stable data-dir.txt marker lives at %APPDATA%/<productName>/data-dir.txt.
    const pkg = JSON.parse(readFileSync(resolve(REPO_ROOT, 'app', 'package.json'), 'utf8')) as {
      productName: string;
    };
    expect(UNINSTALL_USER_DATA_DIRNAME).toBe(pkg.productName);
  });

  it('lists only dirs the sidecar really provisions UNDER the data root', () => {
    const manifest = readFileSync(
      resolve(REPO_ROOT, 'sidecar', 'media_studio', 'assets', 'manifest.py'),
      'utf8',
    );
    const bootstrap = readFileSync(
      resolve(REPO_ROOT, 'sidecar', 'runtime_setup', 'bootstrap.py'),
      'utf8',
    );
    const manager = readFileSync(
      resolve(REPO_ROOT, 'sidecar', 'media_studio', 'assets', 'manager.py'),
      'utf8',
    );
    expect([...UNINSTALL_REMOVABLE_MODEL_DIRS]).toEqual(['models', 'envs', 'tools']);
    expect(manifest).toContain('dest="models/'); // weights
    expect(bootstrap).toContain('"envs"'); // first-run python envs
    expect(manager).toContain('"tools"'); // downloaded tooling
  });
});

describe('build/installer.nsh — the uninstall keep-vs-remove page (WU-L7)', () => {
  const nsh = readFileSync(INSTALLER_NSH, 'utf8');

  it('hooks the two electron-builder UNINSTALLER macros', () => {
    // customUnWelcomePage is the first uninstaller page (app-builder-lib
    // templates/nsis/assistedInstaller.nsh:66-71); customUnInstall runs inside
    // Section "un.Uninstall" BEFORE the files are removed (uninstaller.nsh:156-158).
    expect(nsh).toMatch(/^!macro customUnWelcomePage$/m);
    expect(nsh).toMatch(/^!macro customUnInstall$/m);
  });

  it('pins the data-root folder name against installerSeed.ts', () => {
    expect(nshDefine(nsh, 'REFRAME_DATA_ROOT_DIRNAME')).toBe(UNINSTALL_DATA_ROOT_DIRNAME);
  });

  it('pins the Electron userData folder name against installerSeed.ts', () => {
    expect(nshDefine(nsh, 'REFRAME_USER_DATA_DIRNAME')).toBe(UNINSTALL_USER_DATA_DIRNAME);
  });

  it('pins the data-folder marker filename against installerSeed.ts', () => {
    expect(nshDefine(nsh, 'REFRAME_DATA_DIR_MARKER')).toBe(UNINSTALL_DATA_DIR_MARKER);
  });

  it('pins the removable model/runtime dirs, in the same order', () => {
    expect(nshIdList(nsh, 'REFRAME_UNINSTALL_MODEL_DIRS')).toEqual([
      ...UNINSTALL_REMOVABLE_MODEL_DIRS,
    ]);
  });

  it('actually removes EVERY pinned dir (the id list is not decorative)', () => {
    const body = nshMacroBody(nsh, 'customUnInstall');
    for (const dir of UNINSTALL_REMOVABLE_MODEL_DIRS) {
      expect(body).toContain(`RMDir /r "$ReframeUnDataRoot\\${dir}"`);
    }
  });

  it('DEFAULTS TO KEEP — both removal flags are initialised to 0 before the page', () => {
    const body = nshMacroBody(nsh, 'customUnWelcomePage');
    expect(body).toContain('StrCpy $ReframeUnRemoveModels "0"');
    expect(body).toContain('StrCpy $ReframeUnRemoveUserData "0"');
  });

  it('states the reclaimable size on both choices (an informed choice, not a dare)', () => {
    const body = nshMacroBody(nsh, 'customUnWelcomePage');
    expect(body).toContain('${un.GetSize}');
    expect(body).toContain('$ReframeUnModelsSize');
    expect(body).toContain('$ReframeUnUserSize');
  });

  it('NEVER deletes on an in-place auto-update (silent + --updated, both checked)', () => {
    // electron-updater runs the OLD uninstaller with /S, and the installer always
    // appends --updated for an in-place upgrade (app-builder-lib
    // templates/nsis/include/installUtil.nsh:205-206). Deleting the data root on an
    // UPGRADE would be the worst possible bug this feature could ship.
    const body = nshMacroBody(nsh, 'customUnInstall');
    expect(body).toContain('"--updated"');
    expect(body).toMatch(/\$\{AndIfNot\} \$\{Silent\}/);
  });

  it('never Return/Aborts out of customUnInstall (it runs INSIDE the uninstall Section)', () => {
    // uninstaller.nsh:156-158 expands this macro inside Section "un.Uninstall",
    // ABOVE the RMDir of $INSTDIR — an early Return would skip the real uninstall.
    const body = nshMacroBody(nsh, 'customUnInstall');
    expect(body).not.toMatch(/^\s*(Return|Abort)\b/m);
  });

  it('declares every uninstaller-pass Var INSIDE a macro (the /WX warning-6001 trap)', () => {
    // electron-builder compiles this script TWICE and only the uninstaller pass
    // inserts the un-macros. A Var declared at FILE scope but referenced only from
    // an un-macro is "declared and never referenced" in the installer pass ->
    // warning 6001 -> /WX -> NO INSTALLER IS PRODUCED AT ALL. Declaring them inside
    // the macro means they exist exactly in the pass that uses them.
    const fileScopeVars = [...nsh.matchAll(/^Var\s+(\S+)/gm)].map((m) => m[1]);
    expect(fileScopeVars.filter((v) => v.startsWith('ReframeUn'))).toEqual([]);

    const vars = nshMacroBody(nsh, 'reframeUnVars');
    const used = new Set([...nsh.matchAll(/\$(ReframeUn\w+)/g)].map((m) => m[1]));
    expect(used.size).toBeGreaterThan(0);
    for (const name of used) {
      expect(vars).toContain(`Var /GLOBAL ${name}`);
    }
  });
});

describe('electron-builder.yml — the uninstall page must stay reachable', () => {
  const yml = readFileSync(ELECTRON_BUILDER_YML, 'utf8');

  it('keeps deleteAppDataOnUninstall FALSE (flipping it deletes appData on UPGRADE)', () => {
    // app-builder-lib templates/nsis/uninstaller.nsh:223-227 wipes %APPDATA%/<app>
    // whenever DELETE_APP_DATA_ON_UNINSTALL is defined and the run is not an update.
    // Our page replaces that blunt switch with an explicit opt-in; the switch stays off.
    expect(yml).toMatch(/^\s*deleteAppDataOnUninstall: false$/m);
  });

  it('does NOT set removeDefaultUninstallWelcomePage (it would DELETE our page)', () => {
    // assistedInstaller.nsh:66 wraps the customUnWelcomePage hook in
    // `!ifndef removeDefaultUninstallWelcomePage` — setting that option silently
    // drops the keep-vs-remove page instead of merely dropping MUI's welcome page.
    // Matched as a YAML KEY (line-anchored), not as a bare substring, so the comment
    // in electron-builder.yml that warns about this option does not trip its own guard.
    expect(yml).not.toMatch(/^\s*removeDefaultUninstallWelcomePage\s*:/m);
  });
});
