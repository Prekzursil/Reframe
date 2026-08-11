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

import { createPackage } from '@electron/asar';
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { bundledFfmpegPath, findBuiltApp } from './fixtures';

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

/**
 * A synthetic macOS `.app` bundle (the other shape `parseElectronApp` accepts).
 *
 * `decoys` are extra, COMPLETE `.app` bundles dropped in the SAME parent
 * directory. That is the canonical macOS case, not a contrivance: the documented
 * install location is `/Applications`, which holds many bundles. It matters
 * because `parseElectronApp` strips a `.app` argument to its PARENT and then picks
 * `readdirSync(parent).find((f) => f.endsWith('.app'))` (node_modules/
 * electron-playwright-helpers/dist/find_parse_builds.js — `buildDir =
 * dirname(bundle)` then the `.app` find) — the SAME readdir-order hazard the
 * Windows twin has, and for darwin it poisons `main` as well as `executable`
 * because both are derived from the bundle that `find` chose.
 */
function makeMacInstall(
  name: string,
  decoys: string[] = [],
): { bundle: string; executable: string; main: string } {
  const dir = mkdtempSync(join(root, 'macinstall-'));
  for (const decoy of decoys) makeMacBundle(dir, decoy);
  return makeMacBundle(dir, name);
}

/** One complete `<parent>/<name>.app` bundle (executable + non-asar app dir). */
function makeMacBundle(
  dir: string,
  name: string,
): { bundle: string; executable: string; main: string } {
  const bundle = join(dir, `${name}.app`);
  const macos = join(bundle, 'Contents', 'MacOS');
  mkdirSync(macos, { recursive: true });
  // The inner executable is named after the bundle, as electron-builder writes
  // it — so a decoy bundle yields a DIFFERENT executable basename, which is what
  // makes a mis-resolution visible rather than coincidentally identical.
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

/**
 * A macOS bundle in the shape electron-builder ACTUALLY ships: the app entry
 * inside `Contents/Resources/app.asar` rather than a plain `app/` directory.
 *
 * Built with the real `@electron/asar` (already a transitive dep — it is what
 * `parseElectronApp` itself reads the archive with) so the archive is genuine and
 * the resolution is not being proven against a hand-faked file.
 */
async function makeMacAsarBundle(dir: string, name: string): Promise<string> {
  const bundle = join(dir, `${name}.app`);
  const macos = join(bundle, 'Contents', 'MacOS');
  mkdirSync(macos, { recursive: true });
  writeFileSync(join(macos, name), '#!/bin/sh\n', 'utf8');
  const resources = join(bundle, 'Contents', 'Resources');
  mkdirSync(resources, { recursive: true });
  // Stage the app tree, pack it, then drop the staging dir — leaving it behind
  // would make `resources/` contain BOTH `app.asar` and `app/`, which is not a
  // shape electron-builder produces and would blur which branch is under test.
  const staging = join(dir, `${name}-asar-staging`);
  mkdirSync(join(staging, 'out', 'main'), { recursive: true });
  writeFileSync(
    join(staging, 'package.json'),
    JSON.stringify({ name: 'media-studio', main: 'out/main/main.js' }),
    'utf8',
  );
  writeFileSync(join(staging, 'out', 'main', 'main.js'), '// entry', 'utf8');
  await createPackage(staging, join(resources, 'app.asar'));
  rmSync(staging, { recursive: true, force: true });
  return bundle;
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
    // WHICH GUARD FIRED, not merely "something threw". Asserting only the two
    // patterns above was a SURVIVING MUTANT: deleting the `existsSync` pre-check
    // lets control fall through to `parseElectronApp`, whose failure is re-wrapped
    // as "…is not a launchable Electron app tree", and that message ALSO contains
    // `RF_E2E_APP_EXE` and the path — so all seven cases stayed green with the
    // pre-check gone. This substring belongs to the missing-path branch alone.
    expect(() => findBuiltApp()).toThrowError(/refusing to fall back/);
  });

  it('FAILS LOUD on a path that EXISTS but is not an Electron app tree', () => {
    // The other half of the fail-loud contract, previously unpinned: a directory
    // that is really there but carries no resources/app[.asar]. `parseElectronApp`
    // throws and the wrapper must re-report it against the variable rather than
    // letting a raw library error surface (or, worse, falling back to dev).
    const bare = mkdtempSync(join(root, 'not-an-app-'));
    const exe = join(bare, 'Reframe.exe');
    writeFileSync(exe, 'MZ', 'utf8');
    process.env.RF_E2E_APP_EXE = exe;

    expect(() => findBuiltApp()).toThrowError(/is not a launchable Electron app tree/);
    expect(() => findBuiltApp()).toThrowError(/RF_E2E_APP_EXE/);
    // And it is a DIFFERENT branch from the missing-path one above — without this
    // the two cases could both be satisfied by a single generic message.
    expect(() => findBuiltApp()).not.toThrowError(/refusing to fall back/);
  });

  it('accepts a macOS .app bundle and derives its inner executable', () => {
    // The `.app` bundle directory is NOT itself an executable, so the inner
    // `Contents/MacOS/<name>` is the right answer and the raw variable is not.
    const { bundle, executable, main } = makeMacInstall('Reframe');
    process.env.RF_E2E_APP_EXE = bundle;

    const built = findBuiltApp();
    expect(built.packaged).toBe(true);
    expect(built.executablePath).toBe(executable);
    expect(built.main).toBe(main);
  });

  it('resolves the NAMED .app bundle, not a sibling one, when the parent holds several', () => {
    // The darwin twin of the `Aardvark.exe` decoy case above, and it was MISSING:
    // `makeMacInstall` built a fresh mkdtemp holding exactly ONE bundle, so the
    // macOS arm could not observe `parseElectronApp`'s `dirname` +
    // `readdirSync(parent).find(f => f.endsWith('.app'))` picking a sibling.
    //
    // This is the CANONICAL macOS input, not an edge case: the documented install
    // location is /Applications. It is also the WORSE half of the hazard — for
    // darwin the chosen bundle drives `main` as well as `executable`, so both come
    // back pointing into the wrong app, and it fails SILENTLY because
    // parseElectronApp returns a well-formed (wrong) result and nothing throws.
    //
    // MEASURED on this box: with the resolution delegated to
    // `parseElectronApp(bundle).executable`, `Aardvark.app` wins both fields and
    // this case is red while the six others stay green — the mutation-sensitive
    // arm for the darwin branch.
    const { bundle, executable, main } = makeMacInstall('Reframe', ['Aardvark', 'Zebra']);
    process.env.RF_E2E_APP_EXE = bundle;

    const built = findBuiltApp();
    expect(built.executablePath).toBe(executable);
    expect(built.main).toBe(main);
    // Stated as containment too, so the case still bites if the decoy naming
    // scheme changes: everything resolved must live under the bundle we named.
    expect(built.executablePath!.startsWith(bundle)).toBe(true);
    expect(built.main.startsWith(bundle)).toBe(true);
  });

  it('resolves an ASAR-packed .app bundle from inside the named bundle', async () => {
    // electron-builder ships `Contents/Resources/app.asar`, not a plain `app/`
    // dir, so the non-asar fixtures above do not cover the shape a REAL installed
    // macOS app has. Pinned with a decoy present, because the asar branch reads
    // package.json out of the bundle it picked — the field most likely to be
    // silently taken from the wrong app.
    const dir = mkdtempSync(join(root, 'macasar-'));
    makeMacBundle(dir, 'Aardvark');
    const bundle = await makeMacAsarBundle(dir, 'Reframe');
    process.env.RF_E2E_APP_EXE = bundle;

    const built = findBuiltApp();
    expect(built.executablePath).toBe(join(bundle, 'Contents', 'MacOS', 'Reframe'));
    expect(built.main).toBe(
      join(bundle, 'Contents', 'Resources', 'app.asar', 'out', 'main', 'main.js'),
    );
  });

  it('picks the binary NAMED after the bundle when Contents/MacOS holds several', () => {
    // `parseElectronApp` takes `readdirSync(appDir)[0]` unconditionally
    // (find_parse_builds.js:212). Our replacement prefers the productName match
    // first and only falls back to a lone entry — without this case that
    // preference is decorative: every other fixture puts exactly ONE file in
    // Contents/MacOS, so `[0]` and the stem match are the same answer and the
    // branch is never discriminated. `app/e2e/**` is outside the vitest coverage
    // gate, so nothing else would notice it was unmeasured.
    const { bundle, executable, main } = makeMacInstall('Reframe');
    // `Aardvark` sorts first, so an index-0 pick returns the WRONG binary on any
    // ordered readdir.
    writeFileSync(join(bundle, 'Contents', 'MacOS', 'Aardvark'), '#!/bin/sh\n', 'utf8');
    process.env.RF_E2E_APP_EXE = bundle;

    const built = findBuiltApp();
    expect(built.executablePath).toBe(executable);
    expect(built.main).toBe(main);
  });

  it('REFUSES TO GUESS when Contents/MacOS is ambiguous — no silent wrong binary', () => {
    // The other half of the same branch. Several candidates and none named after
    // the bundle: there is no defensible answer, and returning any of them is the
    // exact failure mode (a leg driving the wrong binary) this resolution exists
    // to prevent. It must throw, naming the candidates it saw.
    const { bundle, executable } = makeMacInstall('Reframe');
    rmSync(executable);
    for (const stray of ['Aardvark', 'Zebra']) {
      writeFileSync(join(bundle, 'Contents', 'MacOS', stray), '#!/bin/sh\n', 'utf8');
    }
    process.env.RF_E2E_APP_EXE = bundle;

    expect(() => findBuiltApp()).toThrowError(/refusing to guess/);
    expect(() => findBuiltApp()).toThrowError(/Aardvark/);
  });
});

describe('bundledFfmpegPath — the extraResources layout of the tree under test', () => {
  // WHY THIS SUITE EXISTS: `bundledFfmpegPath` had NO unit test, and it was wrong
  // for the macOS input `RF_E2E_APP_EXE` documents as supported. It keyed the whole
  // layout off `process.platform` and a flat `dirname(exe)/resources`, so for a
  // `.app` (whose executable is `<bundle>/Contents/MacOS/<name>`) it produced
  // `<bundle>/Contents/MacOS/resources/bin/ffmpeg` — electron-builder puts
  // extraResources at `<bundle>/Contents/Resources/`. `installed-app.spec.ts`
  // asserts `existsSync` on that path with the message "NSIS is NOT laying
  // resources out identically", so a Mac maintainer following the spec's own
  // printed instructions would have got a false and actively misleading diagnosis
  // on a platform where NSIS is not involved.
  //
  // The layout is now derived from the TARGET PATH, not from `process.platform`,
  // which is also what makes these cases assert identically on every runner — the
  // same reasoning the win32 arm above relies on.
  it('derives <install dir>/resources/bin/ffmpeg.exe for a Windows install', () => {
    expect(bundledFfmpegPath(join('C:', 'Program Files', 'Reframe', 'Reframe.exe'))).toBe(
      join('C:', 'Program Files', 'Reframe', 'resources', 'bin', 'ffmpeg.exe'),
    );
  });

  it('derives Contents/Resources/bin/ffmpeg for a macOS bundle, NOT Contents/MacOS/resources', () => {
    const inner = join('/Applications', 'Reframe.app', 'Contents', 'MacOS', 'Reframe');
    expect(bundledFfmpegPath(inner)).toBe(
      join('/Applications', 'Reframe.app', 'Contents', 'Resources', 'bin', 'ffmpeg'),
    );
    // Stated as the negative too: the old flat derivation is what this replaces.
    expect(bundledFfmpegPath(inner)).not.toContain(join('MacOS', 'resources'));
  });

  it('derives <dir>/resources/bin/ffmpeg (no .exe) for a linux-unpacked tree', () => {
    expect(bundledFfmpegPath(join('/opt', 'Reframe', 'reframe'))).toBe(
      join('/opt', 'Reframe', 'resources', 'bin', 'ffmpeg'),
    );
  });
});
