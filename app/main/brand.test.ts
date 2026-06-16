// Brand-rename guard for WU-FND-RENAME (P4 §0 / C13).
//
// The rename touches EXACTLY four brand surfaces and ZERO path literals. This
// test reads the REAL source files (not copies) so that:
//   1. all four brand surfaces read "Reframe - Media Studio", and
//   2. the appData/path literals still read "media-studio" — renaming a path
//      literal would break first-run state, proxy/peak/dub caches, and the
//      sidecar-env sentinel (a known regression class — P4 C13).
// Runs in the default node environment (filesystem access, no jsdom). Tests run
// with cwd = app/, so repo paths are resolved via import.meta.url.
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

// app/main -> repo root is two levels up.
const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(HERE, '..', '..');

const MAIN_TS = resolve(REPO_ROOT, 'app', 'main', 'main.ts');
const APP_TSX = resolve(REPO_ROOT, 'app', 'renderer', 'src', 'App.tsx');
const ELECTRON_BUILDER = resolve(REPO_ROOT, 'electron-builder.yml');
const SETTINGS_STORE = resolve(REPO_ROOT, 'sidecar', 'media_studio', 'settings_store.py');
const ASSETS_MANAGER = resolve(REPO_ROOT, 'sidecar', 'media_studio', 'assets', 'manager.py');

const read = (p: string): string => readFileSync(p, 'utf8');

const BRAND = 'Reframe - Media Studio';

describe('brand rename — four brand surfaces (P4 §0 / C13)', () => {
  it('window title reads the new brand (main.ts)', () => {
    expect(read(MAIN_TS)).toContain(`title: '${BRAND}'`);
  });

  it('renderer brand string reads the new brand (App.tsx)', () => {
    expect(read(APP_TSX)).toContain(`<span className="app__brand">${BRAND}</span>`);
  });

  it('electron-builder productName reads the new brand', () => {
    expect(read(ELECTRON_BUILDER)).toContain(`productName: ${BRAND}`);
  });

  it('nsis shortcutName reads the new brand', () => {
    expect(read(ELECTRON_BUILDER)).toContain(`shortcutName: ${BRAND}`);
  });
});

describe('brand rename — path literals stay "media-studio" (P4 C13 guard)', () => {
  it('main.ts appData first-run sentinel root stays media-studio', () => {
    const src = read(MAIN_TS);
    // resolveDataRoot()'s appData fallback: join(app.getPath('appData'),
    // 'media-studio') — the historical default + read-only-install fallback. The
    // data root is now relocatable, but the appData fallback literal MUST remain
    // so a dev/no-marker launch resolves the same tree as before.
    expect(src).toContain("'media-studio'");
    expect(src).toContain("join(app.getPath('appData'), 'media-studio')");
    expect(src).toContain("'.media-studio-env.json'");
    // The dub-serving root in registerMediaProtocol now derives from DATA_ROOT
    // (the relocatable data folder), not a hard-coded appData/media-studio join.
    expect(src).toContain("resolvePath(DATA_ROOT, 'dubs')");
  });

  it('sidecar settings_store config-dir name stays media-studio', () => {
    // _APP_DIR_NAME is the root for proxies/peaks/dubs/voices/feedback caches.
    expect(read(SETTINGS_STORE)).toContain('_APP_DIR_NAME = "media-studio"');
  });

  it('sidecar assets manager env sentinel name stays media-studio', () => {
    expect(read(ASSETS_MANAGER)).toContain('ENV_SENTINEL = ".media-studio-env.json"');
  });

  it('electron-builder artifactName keeps the package name (${name}), not the brand', () => {
    const src = read(ELECTRON_BUILDER);
    expect(src).toContain('artifactName: ${name}-');
    // appId stays the reverse-DNS local id (not the human brand).
    expect(src).toContain('appId: local.media-studio');
  });
});
