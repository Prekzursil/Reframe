// App-icon wiring guard for WU A2 (Reframe v1.3 — Concept A "Crop Pull").
//
// v1.3 ships the user-picked production icon. The multi-size .ico (16/24/32/48/
// 64/128/256, PNG-embedded) is the installer/exe icon; a 512px PNG is the
// runtime BrowserWindow icon. This test reads the REAL source + assets (not
// copies) so that:
//   1. the icon assets actually exist at the referenced paths,
//   2. the .ico is a genuine multi-size ICO (not a placeholder / renamed png),
//   3. electron-builder.yml wires the .ico to win.icon + nsis installer/
//      uninstaller icons AND ships the runtime icons via extraResources, and
//   4. main.ts's createWindow sets the BrowserWindow `icon` to the resolved
//      packaged/dev icon path.
// Runs in the default node environment (filesystem access, no jsdom). Tests run
// with cwd = app/, so repo paths are resolved via import.meta.url. This file
// lives under main/ which is OUTSIDE the renderer 100% coverage gate
// (vitest.config.ts coverage.include is renderer-only) — it is a pure
// config/asset-assertion guard, mirroring brand.test.ts.
import { describe, it, expect } from 'vitest';
import { readFileSync, statSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

// app/main -> repo root is two levels up.
const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(HERE, '..', '..');

const ICON_DIR = resolve(REPO_ROOT, 'build', 'icons');
const ICO = resolve(ICON_DIR, 'reframe.ico');
const PNG_512 = resolve(ICON_DIR, 'reframe-512.png');
const MAIN_TS = resolve(REPO_ROOT, 'app', 'main', 'main.ts');
const ELECTRON_BUILDER = resolve(REPO_ROOT, 'electron-builder.yml');

const read = (p: string): string => readFileSync(p, 'utf8');

describe('app icon assets exist and are valid (WU A2)', () => {
  it('the multi-size .ico exists and is non-trivial', () => {
    const bytes = readFileSync(ICO);
    // ICONDIR header: reserved(2)=0, type(2)=1 (icon), count(2)=N>=1.
    expect(bytes.readUInt16LE(0)).toBe(0); // reserved
    expect(bytes.readUInt16LE(2)).toBe(1); // type 1 = icon
    // Concept A is authored at 16/24/32/48/64/128/256 -> 7 embedded images.
    expect(bytes.readUInt16LE(4)).toBe(7); // image count
    expect(bytes.byteLength).toBeGreaterThan(2048);
  });

  it('the 512px runtime PNG exists and is a real PNG', () => {
    const bytes = readFileSync(PNG_512);
    // PNG 8-byte magic signature.
    const sig = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
    expect(bytes.subarray(0, 8).equals(sig)).toBe(true);
    expect(statSync(PNG_512).size).toBeGreaterThan(2048);
  });
});

describe('electron-builder.yml wires the production icon (WU A2)', () => {
  const src = read(ELECTRON_BUILDER);

  it('win.icon points at the multi-size .ico (relative to buildResources)', () => {
    expect(src).toMatch(/^\s*icon: icons\/reframe\.ico$/m);
  });

  it('nsis installerIcon + uninstallerIcon point at the .ico', () => {
    expect(src).toMatch(/^\s*installerIcon: icons\/reframe\.ico$/m);
    expect(src).toMatch(/^\s*uninstallerIcon: icons\/reframe\.ico$/m);
  });

  it('extraResources ships the runtime icon set under resources/icons', () => {
    expect(src).toContain('../build/icons');
    expect(src).toMatch(/to: icons$/m);
  });
});

describe('main.ts wires the BrowserWindow runtime icon (WU A2)', () => {
  const src = read(MAIN_TS);

  it('createWindow sets a BrowserWindow icon', () => {
    expect(src).toMatch(/icon: resolveWindowIcon\(\)/);
  });

  it('the runtime icon resolves the packaged 512px PNG under resources/icons', () => {
    expect(src).toContain("'icons', 'reframe-512.png'");
    // dev fallback resolves the same asset out of the repo build/icons tree.
    expect(src).toContain("'build', 'icons', 'reframe-512.png'");
  });
});
