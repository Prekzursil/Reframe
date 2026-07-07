// Brand-rename + version guard for WU A1 (Reframe v1.3 naming lock).
//
// v1.3 unifies the user-facing display name to a single word "Reframe" across
// EVERY user-visible surface (window title, in-app header, the Electron About
// panel, and the installer/shortcut names) while KEEPING the internal id
// "media-studio" (package `name`, reverse-DNS `appId`, the `${name}` artifact
// filename, and every appData/path literal) unchanged — renaming a path literal
// would break first-run state, proxy/peak/dub caches, and the sidecar-env
// sentinel (a known regression class — P4 C13).
//
// This test reads the REAL source files (not copies) so that:
//   1. all user-facing brand surfaces read "Reframe",
//   2. NO user-facing surface leaks "media-studio"/"Media Studio", and
//   3. app/package.json declares version 1.4.0 + productName "Reframe" while the
//      internal `name` stays "media-studio".
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
const INDEX_HTML = resolve(REPO_ROOT, 'app', 'renderer', 'index.html');
const PACKAGE_JSON = resolve(REPO_ROOT, 'app', 'package.json');
const ELECTRON_BUILDER = resolve(REPO_ROOT, 'electron-builder.yml');
const SETTINGS_STORE = resolve(REPO_ROOT, 'sidecar', 'media_studio', 'settings_store.py');
const ASSETS_MANAGER = resolve(REPO_ROOT, 'sidecar', 'media_studio', 'assets', 'manager.py');

const read = (p: string): string => readFileSync(p, 'utf8');

const BRAND = 'Reframe';

// Extract the exact display strings from the real source. Each helper fails
// loudly (throws) if the anchor it depends on is gone, so a moved/renamed
// surface can never silently pass the audit below.
const capture = (src: string, re: RegExp, label: string): string => {
  const m = re.exec(src);
  if (!m) throw new Error(`brand surface not found: ${label}`);
  return m[1];
};

const windowTitle = (): string => capture(read(MAIN_TS), /title: '([^']*)'/, 'window title');
// index.html <title> becomes document.title once the renderer loads, which
// OVERRIDES the BrowserWindow `title` set in main.ts — so the running window's
// title bar shows THIS string, not main.ts's. It is the true user-facing title.
const indexHtmlTitle = (): string =>
  capture(read(INDEX_HTML), /<title>([^<]*)<\/title>/, 'renderer index.html title');
const aboutName = (): string =>
  capture(read(MAIN_TS), /applicationName: '([^']*)'/, 'About panel applicationName');
const headerBrand = (): string =>
  capture(read(APP_TSX), /<span className="app__brand">([^<]*)<\/span>/, 'in-app header');
const productName = (): string =>
  capture(read(ELECTRON_BUILDER), /^productName: (.+)$/m, 'electron-builder productName');
const shortcutName = (): string =>
  capture(read(ELECTRON_BUILDER), /shortcutName: (.+)$/m, 'nsis shortcutName');

describe('brand rename — user-facing surfaces read "Reframe" (WU A1)', () => {
  it('window title reads the new brand (main.ts)', () => {
    expect(windowTitle()).toBe(BRAND);
  });

  it('renderer index.html <title> (document.title override) reads the new brand', () => {
    expect(indexHtmlTitle()).toBe(BRAND);
  });

  it('Electron About panel applicationName reads the new brand (main.ts)', () => {
    expect(aboutName()).toBe(BRAND);
  });

  it('renderer in-app header reads the new brand (App.tsx)', () => {
    expect(headerBrand()).toBe(BRAND);
  });

  it('electron-builder productName reads the new brand', () => {
    expect(productName()).toBe(BRAND);
  });

  it('nsis shortcutName reads the new brand', () => {
    expect(shortcutName()).toBe(BRAND);
  });
});

describe('brand rename — NO user-facing "media-studio" leak (WU A1 / R8 audit)', () => {
  const surfaces: ReadonlyArray<readonly [string, () => string]> = [
    ['window title', windowTitle],
    ['index.html title', indexHtmlTitle],
    ['About panel', aboutName],
    ['in-app header', headerBrand],
    ['productName', productName],
    ['shortcutName', shortcutName],
  ];

  for (const [label, get] of surfaces) {
    it(`${label} shows no "media-studio"/"Media Studio" to the user`, () => {
      const shown = get().toLowerCase();
      expect(shown).not.toContain('media-studio');
      expect(shown).not.toContain('media studio');
    });
  }
});

describe('app/package.json — v1.4 version + productName (WU A1 / WU-R2)', () => {
  const pkg = JSON.parse(read(PACKAGE_JSON)) as {
    version: string;
    productName: string;
    name: string;
  };

  it('version is bumped to 1.4.0', () => {
    expect(pkg.version).toBe('1.4.0');
  });

  it('productName is the display brand "Reframe"', () => {
    expect(pkg.productName).toBe(BRAND);
  });

  it('internal package name stays "media-studio"', () => {
    expect(pkg.name).toBe('media-studio');
  });
});

describe('brand rename — internal id stays "media-studio" (P4 C13 guard)', () => {
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
