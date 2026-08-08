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
  adoptInstallerProfileSeed,
  installerSeedPath,
  parseInstallerSeed,
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

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(HERE, '..', '..');
const INSTALLER_NSH = resolve(REPO_ROOT, 'build', 'installer.nsh');

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
