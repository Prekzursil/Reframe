// installProfiles.test.ts — the profile->asset map decision logic (WU-1c) AND the
// cross-file CONFORMANCE gate. Mirrors firstRunGate.test.ts's bootstrap.py parity
// check: the TS profile map is the single source of truth, and these tests pin
//   (1) the CORE FLOOR is in EVERY profile (no silent centre-crop),
//   (2) the TS core floor === firstRunGate.CORE_FIRST_RUN_ASSETS === the sidecar
//       manifest constant VALUES bootstrap.py core_first_run_assets() references,
//   (3) the Full profile === bootstrap.py default_first_run_assets() (by value).
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';
import {
  ASSET_SIZES_MB,
  CORE_FLOOR_ASSETS,
  INSTALL_BUNDLES,
  INSTALL_PROFILE_FILE,
  INSTALL_PROFILE_IDS,
  INSTALL_PROFILES,
  InstallProfileError,
  assetsSizeMb,
  formatSize,
  isBundleId,
  isInstallProfileId,
  parsePersistedInstallProfile,
  profileSizeLabel,
  resolveInstallChoice,
} from './installProfiles';
import { CORE_FIRST_RUN_ASSETS } from './firstRunGate';

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(HERE, '..', '..');
const SIDECAR = resolve(REPO_ROOT, 'sidecar', 'media_studio');
const BOOTSTRAP_PY = resolve(REPO_ROOT, 'sidecar', 'runtime_setup', 'bootstrap.py');
const MANIFEST_PY = resolve(SIDECAR, 'assets', 'manifest.py');
const TOOLS_PY = resolve(SIDECAR, 'tools_resolver.py');

/** Extract a `NAME = "value"` string constant's value from a Python source. */
function pyConst(src: string, name: string): string {
  const m = src.match(new RegExp(`${name}\\s*=\\s*"([^"]+)"`));
  if (!m) throw new Error(`constant ${name} not found`);
  return m[1];
}

describe('CORE_FLOOR_ASSETS — the no-silent-centre-crop floor', () => {
  it('is the always-on YuNet + S3FD + LR-ASD weights', () => {
    expect([...CORE_FLOOR_ASSETS]).toEqual([
      'yunet-face-detection',
      'lightasd-s3fd',
      'lightasd-asd',
    ]);
  });

  it('is byte-identical to firstRunGate.CORE_FIRST_RUN_ASSETS (one core floor)', () => {
    expect([...CORE_FLOOR_ASSETS]).toEqual([...CORE_FIRST_RUN_ASSETS]);
  });

  it('matches the sidecar manifest constant VALUES bootstrap.py gates the marker on', () => {
    const manifest = readFileSync(MANIFEST_PY, 'utf8');
    expect([...CORE_FLOOR_ASSETS]).toEqual([
      pyConst(manifest, 'YUNET_ASSET_NAME'),
      pyConst(manifest, 'LIGHTASD_S3FD_ASSET_NAME'),
      pyConst(manifest, 'LIGHTASD_ASD_ASSET_NAME'),
    ]);
  });

  it('mirrors bootstrap.py core_first_run_assets() (references those constants)', () => {
    const src = readFileSync(BOOTSTRAP_PY, 'utf8');
    const coreFn = src.match(/def core_first_run_assets\(\)[\s\S]*?\n    return \[([\s\S]*?)\]/);
    const body = coreFn?.[1] ?? '';
    expect(body).toContain('YUNET_ASSET_NAME');
    expect(body).toContain('LIGHTASD_S3FD_ASSET_NAME');
    expect(body).toContain('LIGHTASD_ASD_ASSET_NAME');
  });
});

describe('every profile is a SUPERSET of the core floor (WU-1c invariant)', () => {
  it.each([...INSTALL_PROFILE_IDS])('profile %s pins all three core weights', (id) => {
    const { assets } = resolveInstallChoice(id, id === 'custom' ? [] : undefined);
    for (const core of CORE_FLOOR_ASSETS) {
      expect(assets).toContain(core);
    }
  });

  it('Minimum is core-floor ONLY (app + subject tracking, nothing else)', () => {
    expect(resolveInstallChoice('minimum').assets).toEqual([...CORE_FLOOR_ASSETS]);
  });

  it('Custom with every bundle also keeps the floor', () => {
    const { assets } = resolveInstallChoice('custom', ['transcription', 'ai-director']);
    for (const core of CORE_FLOOR_ASSETS) expect(assets).toContain(core);
  });
});

describe('Full === bootstrap.py default_first_run_assets() (by value)', () => {
  it('resolves to exactly the sidecar default first-run set', () => {
    const manifest = readFileSync(MANIFEST_PY, 'utf8');
    const tools = readFileSync(TOOLS_PY, 'utf8');
    const expected = new Set([
      pyConst(manifest, 'WHISPER_ASSET_NAME'),
      pyConst(manifest, 'QWEN_ASSET_NAME'),
      pyConst(tools, 'LLAMA_CUDA_ASSET'),
      pyConst(tools, 'LLAMA_CUDART_ASSET'),
      pyConst(tools, 'LLAMA_CPU_ASSET'),
      pyConst(manifest, 'LIGHTASD_S3FD_ASSET_NAME'),
      pyConst(manifest, 'LIGHTASD_ASD_ASSET_NAME'),
      pyConst(manifest, 'YUNET_ASSET_NAME'),
    ]);
    expect(new Set(resolveInstallChoice('full').assets)).toEqual(expected);
  });

  it('the bootstrap.py default set references the same 8 constants', () => {
    const src = readFileSync(BOOTSTRAP_PY, 'utf8');
    const fn = src.match(/def default_first_run_assets\(\)[\s\S]*?\n    return \[([\s\S]*?)\]/);
    const body = fn?.[1] ?? '';
    for (const c of [
      'WHISPER_ASSET_NAME',
      'QWEN_ASSET_NAME',
      'LLAMA_CUDA_ASSET',
      'LLAMA_CUDART_ASSET',
      'LLAMA_CPU_ASSET',
      'LIGHTASD_S3FD_ASSET_NAME',
      'LIGHTASD_ASD_ASSET_NAME',
      'YUNET_ASSET_NAME',
    ]) {
      expect(body).toContain(c);
    }
  });
});

describe('resolveInstallChoice — profile -> asset resolution', () => {
  it('Default adds transcription (Whisper) on top of the floor', () => {
    expect(new Set(resolveInstallChoice('default').assets)).toEqual(
      new Set([...CORE_FLOOR_ASSETS, 'whisper-large-v3-turbo']),
    );
  });

  it('a Custom pick unions the floor with the selected bundles (order-preserving, deduped)', () => {
    const res = resolveInstallChoice('custom', ['ai-director', 'ai-director', 'transcription']);
    expect(res.bundles).toEqual(['ai-director', 'transcription']);
    expect(res.assets[0]).toBe('yunet-face-detection');
    expect(res.assets).toContain('qwen3-4b-gguf');
    expect(res.assets).toContain('whisper-large-v3-turbo');
    // no duplicate core assets even though bundles never repeat them
    expect(res.assets.length).toBe(new Set(res.assets).size);
  });

  it('Custom with no bundles is just the floor', () => {
    expect(resolveInstallChoice('custom', []).assets).toEqual([...CORE_FLOOR_ASSETS]);
  });

  it('ignores bundles passed to a NON-custom profile (fully determined by the id)', () => {
    // A malformed renderer that sends bundles for a fixed profile is not honored.
    expect(resolveInstallChoice('minimum', ['ai-director']).assets).toEqual([...CORE_FLOOR_ASSETS]);
  });

  it('FAILS LOUD on an unknown profile (no silent default)', () => {
    expect(() => resolveInstallChoice('everything')).toThrow(InstallProfileError);
    expect(() => resolveInstallChoice(undefined)).toThrow(InstallProfileError);
  });

  it('FAILS LOUD on an unknown Custom bundle', () => {
    expect(() => resolveInstallChoice('custom', ['transcription', 'mystery'])).toThrow(
      InstallProfileError,
    );
  });
});

describe('type guards', () => {
  it('isInstallProfileId', () => {
    expect(isInstallProfileId('full')).toBe(true);
    expect(isInstallProfileId('nope')).toBe(false);
    expect(isInstallProfileId(3)).toBe(false);
  });

  it('isBundleId', () => {
    expect(isBundleId('ai-director')).toBe(true);
    expect(isBundleId('dubbing')).toBe(false);
    expect(isBundleId(null)).toBe(false);
  });
});

describe('sizes', () => {
  it('every asset referenced by a bundle or the floor has a size entry', () => {
    const referenced = new Set<string>(CORE_FLOOR_ASSETS);
    for (const b of INSTALL_BUNDLES) for (const a of b.assets) referenced.add(a);
    for (const a of referenced) expect(ASSET_SIZES_MB[a]).toBeGreaterThan(0);
  });

  it('assetsSizeMb sums known sizes and treats unknown assets as 0', () => {
    expect(assetsSizeMb(['lightasd-asd', 'unknown-x'])).toBe(4);
  });

  it('formatSize renders MB under 1 GB and GB above', () => {
    expect(formatSize(90.3)).toBe('~90 MB');
    expect(formatSize(1690.3)).toBe('~1.7 GB');
    expect(formatSize(999)).toBe('~999 MB');
    expect(formatSize(1000)).toBe('~1.0 GB');
  });

  it('profileSizeLabel grows Minimum < Default < Full', () => {
    expect(profileSizeLabel('minimum')).toBe('~90 MB');
    expect(profileSizeLabel('default')).toBe('~1.7 GB');
    expect(profileSizeLabel('full')).toBe('~5.0 GB');
  });

  it('profileSizeLabel reflects Custom bundle picks', () => {
    expect(profileSizeLabel('custom', [])).toBe('~90 MB');
    expect(profileSizeLabel('custom', ['transcription'])).toBe(profileSizeLabel('default'));
  });
});

describe('profile display metadata', () => {
  it('exposes all four profiles with Default pre-selected as recommended', () => {
    expect(INSTALL_PROFILES.map((p) => p.id)).toEqual(['minimum', 'default', 'full', 'custom']);
    const recommended = INSTALL_PROFILES.filter((p) => p.recommended);
    expect(recommended).toHaveLength(1);
    expect(recommended[0].id).toBe('default');
  });

  it('every profile carries a what + why one-liner', () => {
    for (const p of INSTALL_PROFILES) {
      expect(p.what.length).toBeGreaterThan(0);
      expect(p.why.length).toBeGreaterThan(0);
    }
  });
});

describe('parsePersistedInstallProfile — replay the choice on a re-bootstrap', () => {
  it('parses a valid persisted record', () => {
    expect(parsePersistedInstallProfile({ profile: 'custom', bundles: ['ai-director'] })).toEqual({
      profile: 'custom',
      bundles: ['ai-director'],
    });
  });

  it('defaults bundles to [] when absent or not an array', () => {
    expect(parsePersistedInstallProfile({ profile: 'default' })).toEqual({
      profile: 'default',
      bundles: [],
    });
    expect(parsePersistedInstallProfile({ profile: 'full', bundles: 'x' })).toEqual({
      profile: 'full',
      bundles: [],
    });
  });

  it('drops unknown bundle ids and dedupes (defensive, not fatal)', () => {
    expect(
      parsePersistedInstallProfile({
        profile: 'custom',
        bundles: ['ai-director', 'x', 'ai-director'],
      }),
    ).toEqual({ profile: 'custom', bundles: ['ai-director'] });
  });

  it('returns null for a corrupt / legacy / non-object body (falls back to default set)', () => {
    expect(parsePersistedInstallProfile(null)).toBeNull();
    expect(parsePersistedInstallProfile('nope')).toBeNull();
    expect(parsePersistedInstallProfile({ profile: 'bogus' })).toBeNull();
    expect(parsePersistedInstallProfile({})).toBeNull();
  });

  it('exposes the persisted file name (sibling of the completion marker)', () => {
    expect(INSTALL_PROFILE_FILE).toBe('.first-run-profile.json');
  });
});
