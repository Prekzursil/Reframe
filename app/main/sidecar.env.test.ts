// sidecar.env.test.ts — the cross-process exports-root invariant (P4 §6, C10 /
// code-review #5).
//
// main.ts resolves the `short:` exports root by RE-DERIVING the path literal in
// TypeScript:
//     resolve(app.getPath('appData'), 'media-studio', 'exports')
// The sidecar independently derives the SAME root via
//     settings_store.default_config_dir() / 'exports'
// and `default_config_dir()` resolves to `%APPDATA%/media-studio` — i.e. the two
// agree — ONLY while `MEDIA_STUDIO_CONFIG_DIR` is UNSET (that env var is the
// FIRST branch of `default_config_dir`, overriding %APPDATA%). The sidecar child
// inherits its env from `buildSidecarEnv`, which must therefore NOT introduce
// that override, or every `short:` playback/thumbnail URL would 404 silently.
//
// This test pins that invariant: `buildSidecarEnv` never SETS
// MEDIA_STUDIO_CONFIG_DIR (so the two independently-derived roots stay equal).
// child_process / fs are not exercised here — `buildSidecarEnv` is pure over
// `process.env`, so we drive it by temporarily mutating the env.
import { resolve } from 'node:path';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { buildSidecarEnv } from './sidecar';

/** Read/write `process.resourcesPath` (Electron-only) without Electron types. */
type ProcessWithResources = NodeJS.Process & { resourcesPath?: string };

/** Remove `resourcesPath` (delete through an index signature — the typed
 *  property is not declared `delete`-able on `NodeJS.Process`). */
function clearResourcesPath(): void {
  delete (process as unknown as Record<string, unknown>).resourcesPath;
}

describe('buildSidecarEnv — short: exports-root cross-process invariant (C10 / #5)', () => {
  const ENV_KEY = 'MEDIA_STUDIO_CONFIG_DIR';
  let savedConfigDir: string | undefined;

  beforeEach(() => {
    savedConfigDir = process.env[ENV_KEY];
    delete process.env[ENV_KEY];
  });

  afterEach(() => {
    if (savedConfigDir === undefined) delete process.env[ENV_KEY];
    else process.env[ENV_KEY] = savedConfigDir;
  });

  it('does NOT set MEDIA_STUDIO_CONFIG_DIR (keeps the sidecar exports root == %APPDATA%/media-studio)', () => {
    // Parent env has no override -> the child must not gain one, so the sidecar's
    // default_config_dir() stays %APPDATA%/media-studio, matching main.ts's
    // re-derived exports root.
    const dev = buildSidecarEnv(false);
    expect(ENV_KEY in dev).toBe(false);

    const packaged = buildSidecarEnv(true);
    expect(ENV_KEY in packaged).toBe(false);
  });

  it('never CLOBBERS a parent override (inherits it verbatim — divergence would be the caller’s explicit choice)', () => {
    // If the user themselves exported MEDIA_STUDIO_CONFIG_DIR, the child inherits
    // that exact value (the env is a copy of process.env). buildSidecarEnv must
    // not inject a DIFFERENT value — the documented invariant only holds while
    // the override is unset, and that is the caller's contract to honor.
    process.env[ENV_KEY] = '/tmp/custom-config';
    const env = buildSidecarEnv(false);
    expect(env[ENV_KEY]).toBe('/tmp/custom-config');
  });
});

// A3 — bundled ffmpeg/ffprobe env wiring (WIRING-T5 §2). The packaged supervisor
// points ffmpeg.py's env link at the ffmpeg/ffprobe shipped OUTSIDE app.asar by
// electron-builder `extraResources` (from: ../build/ffmpeg/win -> to: bin). The
// exes therefore resolve to `<process.resourcesPath>/bin/ffmpeg.exe` (and
// ffprobe.exe) only in a PACKAGED build; in dev buildSidecarEnv sets neither, so
// ffmpeg.py falls through to its own bundled/PATH resolution.
describe('buildSidecarEnv — bundled ffmpeg/ffprobe path resolution (A3, WIRING-T5 §2)', () => {
  const FFMPEG = 'MEDIA_STUDIO_FFMPEG';
  const FFPROBE = 'MEDIA_STUDIO_FFPROBE';
  const RES = '/fake/resources';
  const proc = process as ProcessWithResources;
  let savedResources: string | undefined;
  let savedFfmpeg: string | undefined;
  let savedFfprobe: string | undefined;

  beforeEach(() => {
    savedResources = proc.resourcesPath;
    savedFfmpeg = process.env[FFMPEG];
    savedFfprobe = process.env[FFPROBE];
    delete process.env[FFMPEG];
    delete process.env[FFPROBE];
  });

  afterEach(() => {
    if (savedResources === undefined) clearResourcesPath();
    else proc.resourcesPath = savedResources;
    if (savedFfmpeg === undefined) delete process.env[FFMPEG];
    else process.env[FFMPEG] = savedFfmpeg;
    if (savedFfprobe === undefined) delete process.env[FFPROBE];
    else process.env[FFPROBE] = savedFfprobe;
  });

  it('packaged build resolves ffmpeg/ffprobe to <resourcesPath>/bin/*.exe', () => {
    proc.resourcesPath = RES;
    const env = buildSidecarEnv(true);
    // Must equal the SAME `resources/bin` layout electron-builder ships to; a
    // drift between `to: bin` and this resolution would 404 the bundled binary.
    expect(env[FFMPEG]).toBe(resolve(RES, 'bin', 'ffmpeg.exe'));
    expect(env[FFPROBE]).toBe(resolve(RES, 'bin', 'ffprobe.exe'));
  });

  it('dev build (packaged=false) sets NEITHER ffmpeg nor ffprobe (ffmpeg.py owns dev resolution)', () => {
    // Real Electron always defines process.resourcesPath, even in dev — pin that
    // the dev branch still leaves the ffmpeg env link unset regardless.
    proc.resourcesPath = RES;
    const env = buildSidecarEnv(false);
    expect(FFMPEG in env).toBe(false);
    expect(FFPROBE in env).toBe(false);
  });

  it('packaged build never CLOBBERS a pre-set ffmpeg/ffprobe override', () => {
    proc.resourcesPath = RES;
    process.env[FFMPEG] = '/opt/custom/ffmpeg';
    process.env[FFPROBE] = '/opt/custom/ffprobe';
    const env = buildSidecarEnv(true);
    expect(env[FFMPEG]).toBe('/opt/custom/ffmpeg');
    expect(env[FFPROBE]).toBe('/opt/custom/ffprobe');
  });

  it('packaged build without a resourcesPath leaves ffmpeg/ffprobe unset (guarded)', () => {
    clearResourcesPath();
    const env = buildSidecarEnv(true);
    expect(FFMPEG in env).toBe(false);
    expect(FFPROBE in env).toBe(false);
  });
});
