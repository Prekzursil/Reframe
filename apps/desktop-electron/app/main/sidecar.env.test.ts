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
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { buildSidecarEnv } from './sidecar';

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
