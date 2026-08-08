// installerSeedIo.test.ts — the installer-seed seam against a REAL filesystem.
//
// The pure policy is covered by installerSeed.test.ts with fakes. This file drives the
// seam main.ts actually installs, on real temp dirs, because a fake `existsSync` cannot
// tell you that the write lands at the right path, in the right shape, or that an
// UPGRADE leaves the previous install untouched. The upgrade case is the load-bearing
// one: the whole feature re-runs the component page on every install, so the ONLY thing
// standing between an upgrade and a re-provision is the never-clobber guard proved here.
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { adoptInstallerProfileSeed } from './installerSeed';
import {
  createInstallerSeedIo,
  dataRootProfilePath,
  serializeInstallProfile,
} from './installerSeedIo';
import { INSTALL_PROFILE_FILE } from './installProfiles';

let root = '';
let installDir = '';
let dataRoot = '';

beforeEach(() => {
  root = mkdtempSync(join(tmpdir(), 'reframe-seed-'));
  installDir = join(root, 'install');
  dataRoot = join(root, 'data');
  mkdirSync(installDir, { recursive: true });
});

afterEach(() => {
  rmSync(root, { recursive: true, force: true });
});

/** Write the seed the NSIS `customInstall` macro produces (CRLF, 2-space, trailing NL). */
function writeInstallerSeed(profile: string, bundles: readonly string[]): void {
  const list = bundles.map((b) => `"${b}"`).join(', ');
  writeFileSync(
    join(installDir, INSTALL_PROFILE_FILE),
    `{\r\n  "profile": "${profile}",\r\n  "bundles": [${list}]\r\n}\r\n`,
    'utf8',
  );
}

function adopt(): ReturnType<typeof adoptInstallerProfileSeed> {
  return adoptInstallerProfileSeed(createInstallerSeedIo(installDir, dataRoot));
}

describe('fresh install — the component page choice reaches the data root', () => {
  it('adopts the seed and writes it in the app persistence shape', () => {
    writeInstallerSeed('custom', ['transcription', 'ai-director']);
    expect(adopt()).toEqual({
      outcome: 'adopted',
      profile: { profile: 'custom', bundles: ['transcription', 'ai-director'] },
    });
    const written = readFileSync(dataRootProfilePath(dataRoot), 'utf8');
    expect(written).toBe(
      serializeInstallProfile({ profile: 'custom', bundles: ['transcription', 'ai-director'] }),
    );
    // Round-trips through the app's own reader: this IS what a first-ever run installs.
    expect(JSON.parse(written)).toEqual({
      profile: 'custom',
      bundles: ['transcription', 'ai-director'],
    });
  });

  it('CREATES the data root when it does not exist yet (a first-ever launch)', () => {
    expect(existsSync(dataRoot)).toBe(false);
    writeInstallerSeed('full', []);
    expect(adopt().outcome).toBe('adopted');
    expect(existsSync(dataRootProfilePath(dataRoot))).toBe(true);
  });

  it('parses the installer CRLF body byte-for-byte (NSIS writes $\\r$\\n)', () => {
    writeInstallerSeed('minimum', []);
    const raw = readFileSync(join(installDir, INSTALL_PROFILE_FILE), 'utf8');
    expect(raw).toContain('\r\n');
    expect(adopt().profile).toEqual({ profile: 'minimum', bundles: [] });
  });

  it('does nothing when there is no installer (a portable / zip extraction)', () => {
    expect(adopt()).toEqual({ outcome: 'no-seed', profile: null });
    expect(existsSync(dataRootProfilePath(dataRoot))).toBe(false);
  });

  it('leaves the data root alone when the seed is corrupt', () => {
    writeFileSync(join(installDir, INSTALL_PROFILE_FILE), '{ this is not json', 'utf8');
    expect(adopt().outcome).toBe('invalid-seed');
    expect(existsSync(dataRootProfilePath(dataRoot))).toBe(false);
  });
});

describe('UPGRADE — install old, install new: the existing install survives untouched', () => {
  it('keeps the old profile, its models and its settings when the new installer differs', () => {
    // --- the OLD install: a user who chose Full, provisioned, and has state on disk.
    mkdirSync(join(dataRoot, 'models'), { recursive: true });
    const oldProfile = serializeInstallProfile({ profile: 'full', bundles: [] });
    writeFileSync(dataRootProfilePath(dataRoot), oldProfile, 'utf8');
    writeFileSync(join(dataRoot, '.first-run-complete.json'), '{"ok":true}', 'utf8');
    writeFileSync(join(dataRoot, 'settings.json'), '{"theme":"dark"}', 'utf8');
    writeFileSync(join(dataRoot, 'models', 'qwen3-4b.gguf'), 'PRETEND-2.5GB', 'utf8');

    // --- the NEW installer runs and writes its own (different, defaulted) seed.
    writeInstallerSeed('minimum', []);

    expect(adopt()).toEqual({ outcome: 'already-chosen', profile: null });

    // The profile is byte-identical — no downgrade from Full to Minimum.
    expect(readFileSync(dataRootProfilePath(dataRoot), 'utf8')).toBe(oldProfile);
    // Provisioning marker intact -> classifyFirstRun stays 'none' -> no re-download.
    expect(readFileSync(join(dataRoot, '.first-run-complete.json'), 'utf8')).toBe('{"ok":true}');
    // Settings intact.
    expect(readFileSync(join(dataRoot, 'settings.json'), 'utf8')).toBe('{"theme":"dark"}');
    // Models intact.
    expect(readFileSync(join(dataRoot, 'models', 'qwen3-4b.gguf'), 'utf8')).toBe('PRETEND-2.5GB');
  });

  it('is idempotent across repeated installer runs (re-running setup changes nothing)', () => {
    writeInstallerSeed('default', []);
    expect(adopt().outcome).toBe('adopted');
    const afterFirst = readFileSync(dataRootProfilePath(dataRoot), 'utf8');

    writeInstallerSeed('minimum', []);
    expect(adopt().outcome).toBe('already-chosen');
    expect(adopt().outcome).toBe('already-chosen');
    expect(readFileSync(dataRootProfilePath(dataRoot), 'utf8')).toBe(afterFirst);
  });
});

describe('createInstallerSeedIo — the paths main.ts wires', () => {
  it('points at $INSTDIR for the seed and the data root for the profile', () => {
    const io = createInstallerSeedIo(installDir, dataRoot);
    expect(io.seedPath).toBe(join(installDir, INSTALL_PROFILE_FILE));
    expect(io.dataRootProfilePath).toBe(join(dataRoot, INSTALL_PROFILE_FILE));
  });

  it('short-circuits to same-path when the install dir IS the data root', () => {
    // A portable layout where both resolve to one folder: adoption is meaningless
    // and must not rewrite the file it would be reading from.
    const io = createInstallerSeedIo(installDir, installDir);
    writeInstallerSeed('full', []);
    expect(adoptInstallerProfileSeed(io)).toEqual({ outcome: 'same-path', profile: null });
    expect(readFileSync(join(installDir, INSTALL_PROFILE_FILE), 'utf8')).toContain('\r\n');
  });

  it('reports write-failed instead of throwing when the data root path is a FILE', () => {
    // mkdirSync on a path whose parent is a regular file throws ENOTDIR/EEXIST.
    writeFileSync(dataRoot, 'not a directory', 'utf8');
    writeInstallerSeed('full', []);
    expect(adopt()).toEqual({ outcome: 'write-failed', profile: null });
  });
});
