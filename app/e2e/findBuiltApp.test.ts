// findBuiltApp.test.ts — the deterministic half of the INSTALLED-BUILD escape hatch.
//
// ── WHY THIS FILE EXISTS ─────────────────────────────────────────────────────
// `fixtures.findBuiltApp()` resolved the app under test from exactly ONE place:
// `DIST_DIR = join(REPO_ROOT, 'dist')`, i.e. the electron-builder OUTPUT tree
// (`dist/win-unpacked`). There was no way to point it at an app installed by the
// NSIS installer, so `packaged.spec.ts` — the only spec that hard-requires a real
// package — drives `dist/win-unpacked` and NEVER an installed app. The installer
// path (build -> silent `/S /D=` install -> launch -> first-run provisioning ->
// clean uninstall) has been walked by hand, but no video and no GUI flow has ever
// been driven through an INSTALLED build.
//
// `RF_E2E_APP_EXE` is that escape hatch, and this file is its DETERMINISTIC proof:
// it builds a synthetic "installed" tree on disk (the exact layout
// `parseElectronApp` reads: `<dir>/<app>.exe` + `<dir>/resources/app/package.json`)
// and pins the resolution contract without needing Electron, a package, an
// installer, or a GUI. The LAUNCH arm — that an installed .exe actually boots and
// answers RPCs — belongs to `installed-app.spec.ts`, which self-skips unless the
// variable is set; see that file for what is and is not measured there.
//
// It rides `vitest.e2e.config.ts` (`include: ['e2e/**/*.test.{ts,tsx}']`, run by
// `npm run test:e2e:dom`), which EVERY OS leg of e2e.yml already runs — so this
// half is exercised on Windows, macOS and Linux, unlike the Windows-only installer.
//
// OS-INDEPENDENT BY CONSTRUCTION. `parseElectronApp` infers `platform` from the
// path SUFFIX (`.exe` -> win32, `.app` -> darwin) and not from `process.platform`,
// and everything it then touches is plain `fs`/`path`. So the win32 arm below runs
// and asserts identically on a Linux runner. Nothing here hardcodes a separator:
// every expectation is composed with `path.join`, and the one case-sensitivity-
// adjacent assertion (the error message) compares against the value this test
// itself wrote.

import { mkdirSync, mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { findBuiltApp } from './fixtures';

/** The env keys this suite mutates; saved and restored around every case. */
const TOUCHED = ['RF_E2E_APP_EXE', 'RF_E2E_DEV', 'RF_E2E_REQUIRE_PACKAGED'] as const;

let saved: Record<string, string | undefined>;
let root: string;

/**
 * A synthetic WINDOWS installed tree, non-asar so no asar bundle is needed:
 *
 *   <root>/<name>.exe                              the executable
 *   <root>/resources/app/package.json              {"main": "out/main/main.js"}
 *   <root>/resources/app/out/main/main.js          the entry `main` must resolve to
 *
 * `decoys` are extra `.exe` files dropped in the SAME directory. That is not a
 * contrivance: an electron-builder NSIS install directory really does contain a
 * second executable (`Uninstall <ProductName>.exe`), and `parseElectronApp` picks
 * the executable with `list.find((f) => f.endsWith('.exe'))` over a raw
 * `readdirSync` — "assume the executable is the only .exe file in the directory"
 * in its own words (node_modules/electron-playwright-helpers/dist/
 * find_parse_builds.js). Which one that finds is filesystem-order-dependent, so
 * the override must return the path the CALLER named, not a re-derived guess.
 */
function makeWindowsInstall(name: string, decoys: string[] = []): { exe: string; main: string } {
  const dir = mkdtempSync(join(root, 'install-'));
  const exe = join(dir, `${name}.exe`);
  writeFileSync(exe, 'MZ', 'utf8');
  for (const decoy of decoys) writeFileSync(join(dir, decoy), 'MZ', 'utf8');
  const appDir = join(dir, 'resources', 'app');
  mkdirSync(join(appDir, 'out', 'main'), { recursive: true });
  writeFileSync(
    join(appDir, 'package.json'),
    JSON.stringify({ name: 'media-studio', main: 'out/main/main.js' }),
    'utf8',
  );
  const main = join(appDir, 'out', 'main', 'main.js');
  writeFileSync(main, '// entry', 'utf8');
  return { exe, main };
}

/** A synthetic macOS `.app` bundle (the other shape `parseElectronApp` accepts). */
function makeMacInstall(name: string): { bundle: string; executable: string; main: string } {
  const dir = mkdtempSync(join(root, 'macinstall-'));
  const bundle = join(dir, `${name}.app`);
  const macos = join(bundle, 'Contents', 'MacOS');
  mkdirSync(macos, { recursive: true });
  const executable = join(macos, name);
  writeFileSync(executable, '#!/bin/sh\n', 'utf8');
  const appDir = join(bundle, 'Contents', 'Resources', 'app');
  mkdirSync(join(appDir, 'out', 'main'), { recursive: true });
  writeFileSync(
    join(appDir, 'package.json'),
    JSON.stringify({ name: 'media-studio', main: 'out/main/main.js' }),
    'utf8',
  );
  const main = join(appDir, 'out', 'main', 'main.js');
  writeFileSync(main, '// entry', 'utf8');
  return { bundle, executable, main };
}

beforeEach(() => {
  saved = {};
  for (const key of TOUCHED) {
    saved[key] = process.env[key];
    delete process.env[key];
  }
  root = mkdtempSync(join(tmpdir(), 'reframe-e2e-appexe-'));
});

afterEach(() => {
  for (const key of TOUCHED) {
    if (saved[key] === undefined) delete process.env[key];
    else process.env[key] = saved[key];
  }
  // The synthetic trees are left in the OS temp dir on purpose: they are tiny
  // (a few hundred bytes) and keeping them makes a red run inspectable. The OS
  // reclaims them; nothing in the repo is touched.
});

describe('findBuiltApp — RF_E2E_APP_EXE (installed-build escape hatch)', () => {
  it('resolves a Windows installed tree from the variable alone', () => {
    const { exe, main } = makeWindowsInstall('Reframe');
    process.env.RF_E2E_APP_EXE = exe;

    const built = findBuiltApp();
    expect(built.packaged, 'an installed app IS a packaged artifact').toBe(true);
    expect(built.executablePath).toBe(exe);
    expect(built.main).toBe(main);
  });

  it('DETECTOR CONTROL — without the variable, that exe is never reachable', () => {
    // Without this arm the case above proves nothing: `findBuiltApp` could be
    // returning the fake exe for some ambient reason (a stale dist/, a cached
    // module) rather than because the override read it. Whatever the unset call
    // does here — resolve dist/, resolve the dev build, or throw because neither
    // exists — the ONE thing it must never do is name our synthetic tree.
    const { exe } = makeWindowsInstall('Reframe');
    let observed: string;
    try {
      observed = JSON.stringify(findBuiltApp());
    } catch (err) {
      observed = (err as Error).message;
    }
    expect(observed).not.toContain(exe);
  });

  it('returns the path the CALLER named, not a re-derived one, when the install dir holds another .exe', () => {
    // `Aardvark.exe` sorts before `Reframe.exe`, so on a filesystem whose
    // readdir is ordered (NTFS) `parseElectronApp`'s "only .exe in the
    // directory" assumption resolves the DECOY. MEASURED on this box: reverting
    // the override to `info.executable` turns this case red and leaves the two
    // cases above green — which is what makes this the mutation-sensitive one.
    // On a filesystem with hash-ordered readdir the decoy may not win, so the
    // assertion is written as the invariant that holds either way: the returned
    // path is EXACTLY the one the caller supplied.
    const { exe, main } = makeWindowsInstall('Reframe', ['Aardvark.exe', 'Uninstall Reframe.exe']);
    process.env.RF_E2E_APP_EXE = exe;

    const built = findBuiltApp();
    expect(built.executablePath).toBe(exe);
    expect(built.main).toBe(main);
  });

  it('OVERRIDES RF_E2E_DEV — the CI leg sets RF_E2E_DEV=1 for the whole job', () => {
    // e2e.yml exports RF_E2E_DEV=1 on the Windows leg so preview.spec's
    // data-pipeline assertions run against the dev build. An installed-build step
    // in that same job therefore CANNOT ask for the dev build to be turned off;
    // the variable must win outright, exactly as RF_E2E_REQUIRE_PACKAGED does.
    const { exe } = makeWindowsInstall('Reframe');
    process.env.RF_E2E_APP_EXE = exe;
    process.env.RF_E2E_DEV = '1';

    expect(findBuiltApp().executablePath).toBe(exe);
    expect(findBuiltApp().packaged).toBe(true);
  });

  it('SATISFIES RF_E2E_REQUIRE_PACKAGED — an installed app is a real package', () => {
    const { exe } = makeWindowsInstall('Reframe');
    process.env.RF_E2E_APP_EXE = exe;
    process.env.RF_E2E_REQUIRE_PACKAGED = '1';

    // Must NOT fall through to the "no electron-builder output dir found at
    // <dist>" throw: this worktree may legitimately have no dist/ at all.
    expect(findBuiltApp().packaged).toBe(true);
  });

  it('FAILS LOUD on a path that does not exist — never a silent dev fallback', () => {
    // The failure mode this guards against is the expensive one: a typo'd or
    // stale RF_E2E_APP_EXE quietly resolving the DEV build, so an
    // "installed-build" leg reports green having driven `out/main/main.js`.
    const missing = join(root, 'no-such-dir', 'Reframe.exe');
    process.env.RF_E2E_APP_EXE = missing;

    expect(() => findBuiltApp()).toThrowError(/RF_E2E_APP_EXE/);
    expect(() => findBuiltApp()).toThrowError(new RegExp(missing.replace(/[\\^$.*+?()[\]{}|]/g, '\\$&')));
  });

  it('accepts a macOS .app bundle and derives its inner executable', () => {
    // The `.app` bundle directory is NOT itself an executable, so here the
    // derived `info.executable` is the right answer and the raw variable is not.
    const { bundle, executable, main } = makeMacInstall('Reframe');
    process.env.RF_E2E_APP_EXE = bundle;

    const built = findBuiltApp();
    expect(built.packaged).toBe(true);
    expect(built.executablePath).toBe(executable);
    expect(built.main).toBe(main);
  });
});
