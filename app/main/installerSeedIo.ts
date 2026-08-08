// installerSeedIo.ts — the concrete FILESYSTEM seam for installer-seed adoption.
//
// WHY THIS IS ITS OWN MODULE. dataRootIo.ts exists for exactly this reason and says so
// (dataRootIo.ts:1-12): when the IO half lives as private functions inside main.ts it
// cannot be imported under vitest (main.ts runs Electron side effects on import), so
// the seam that actually touches disk ends up with ZERO direct coverage and slips past
// every gate. The pure decision is installerSeed.ts; this is the half that reads and
// writes real files, and installerSeedIo.test.ts drives it against real temp dirs —
// including a simulated old-install -> new-install upgrade.
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { INSTALL_PROFILE_FILE, type PersistedInstallProfile } from './installProfiles';
import { installerSeedPath, type InstallerSeedIo } from './installerSeed';

/** `<dataRoot>/.first-run-profile.json` — the app's persisted install profile. */
export function dataRootProfilePath(dataRoot: string): string {
  return join(dataRoot, INSTALL_PROFILE_FILE);
}

/**
 * Serialise a profile record exactly as main.ts `persistInstallProfile` does — 2-space
 * JSON with a trailing newline — so a seed adopted here and a choice made in the in-app
 * picker produce byte-identical files. One writer shape, no "which one wrote this?".
 */
export function serializeInstallProfile(record: PersistedInstallProfile): string {
  return `${JSON.stringify({ profile: record.profile, bundles: record.bundles }, null, 2)}\n`;
}

/**
 * Build the filesystem seam for {@link installerSeed.adoptInstallerProfileSeed}.
 *
 * `installDir` is the running executable's directory (`dataRootIo.exeDir()` — the NSIS
 * `$INSTDIR`), `dataRoot` is the root main.ts resolved this session. Every callback may
 * throw; the pure policy catches and degrades, so nothing here needs its own try/catch
 * and no failure mode is silently swallowed twice.
 */
export function createInstallerSeedIo(installDir: string, dataRoot: string): InstallerSeedIo {
  const seedPath = installerSeedPath(installDir);
  const profilePath = dataRootProfilePath(dataRoot);
  return {
    seedPath,
    dataRootProfilePath: profilePath,
    readSeed: () => (existsSync(seedPath) ? readFileSync(seedPath, 'utf8') : undefined),
    dataRootProfileExists: () => existsSync(profilePath),
    writeDataRootProfile: (record) => {
      // The data root may not exist yet on a first-ever launch (bootstrap.py creates
      // it), so create it rather than losing the installer's choice to ENOENT.
      mkdirSync(dirname(profilePath), { recursive: true });
      writeFileSync(profilePath, serializeInstallProfile(record), 'utf8');
      return true;
    },
  };
}
