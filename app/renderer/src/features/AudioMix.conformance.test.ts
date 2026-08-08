// Conformance test for the audio-mixer's MIRRORED engine constants.
//
// The mixer panel shows numbers the SIDECAR owns
// (`sidecar/media_studio/features/audiomix.py`):
//   * `PLATFORM_LOUDNESS`      — the per-platform integrated-loudness (LUFS) map,
//   * `DEFAULT_BG_GAIN_DB` / `DEFAULT_DUCK_THRESHOLD` / `DEFAULT_DUCK_RATIO`
//     — the bed-gain + sidechain-duck defaults the pickers start on.
//
// The panel SENDS `platform` (never a hard-coded LUFS) so the sidecar stays the
// single authority for the value that is actually APPLIED — but it DISPLAYS the
// number next to the choice, so a silent drift between the two tables would show
// a figure the export does not hit. This test reads the REAL `.py` source (not a
// copy), the same idiom as `lib/captionTemplates.conformance.test.ts`, so adding
// or moving a target without updating the mirror fails the build.
//
// Runs in the default node environment (filesystem access, no jsdom).
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

import {
  DEFAULT_BG_GAIN_DB,
  DEFAULT_DUCK_RATIO,
  DEFAULT_DUCK_THRESHOLD,
  LOUDNESS_TARGETS,
} from './AudioMix';

// app/renderer/src/features -> repo root is four levels up.
const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(HERE, '..', '..', '..', '..');
const SIDECAR_AUDIOMIX = resolve(REPO_ROOT, 'sidecar', 'media_studio', 'features', 'audiomix.py');

function sidecarSource(): string {
  return readFileSync(SIDECAR_AUDIOMIX, 'utf8');
}

/** Parse `PLATFORM_LOUDNESS: dict[str, float] = { "id": -14.0, ... }` from the engine. */
function sidecarPlatformLoudness(): Record<string, number> {
  const src = sidecarSource();
  const block = src.match(/PLATFORM_LOUDNESS: dict\[str, float\] = \{([\s\S]*?)\n\}/);
  if (!block) throw new Error('could not find PLATFORM_LOUDNESS in audiomix.py');
  const out: Record<string, number> = {};
  for (const m of block[1].matchAll(/"([^"]+)":\s*(-?\d+(?:\.\d+)?)/g)) {
    out[m[1]] = Number(m[2]);
  }
  return out;
}

/** Parse a top-level `NAME = <number>` module constant from the engine. */
function sidecarConstant(name: string): number {
  const m = sidecarSource().match(new RegExp(`^${name} = (-?\\d+(?:\\.\\d+)?)$`, 'm'));
  if (!m) throw new Error(`could not find ${name} in audiomix.py`);
  return Number(m[1]);
}

describe('audiomix.py parse helpers (detector control)', () => {
  // rules/common/single-signal-verification.md §3: prove the parser can FIND a
  // known-present item before trusting any assertion built on its output. An
  // empty map here would make every conformance check below vacuously pass.
  it('extracts a non-empty PLATFORM_LOUDNESS map containing the documented anchors', () => {
    const table = sidecarPlatformLoudness();
    expect(Object.keys(table).length).toBeGreaterThanOrEqual(10);
    expect(table.tiktok).toBe(-14);
    expect(table.ebu).toBe(-23);
    expect(table.atsc).toBe(-24);
  });

  it('throws (never silently returns a default) when a constant is absent', () => {
    expect(() => sidecarConstant('DEFINITELY_NOT_A_REAL_CONSTANT')).toThrow(/could not find/);
  });
});

describe('LOUDNESS_TARGETS mirrors sidecar PLATFORM_LOUDNESS', () => {
  it('offers only platform ids the sidecar recognises', () => {
    const table = sidecarPlatformLoudness();
    const unknown = LOUDNESS_TARGETS.filter((t) => !(t.id in table)).map((t) => t.id);
    // resolve_loudness_target() raises INVALID_PARAMS on an unknown platform, so
    // an id the sidecar does not know is a guaranteed runtime failure.
    expect(unknown).toEqual([]);
  });

  it('shows the same LUFS number the sidecar will apply', () => {
    const table = sidecarPlatformLoudness();
    const mismatched = LOUDNESS_TARGETS.filter((t) => table[t.id] !== t.lufs).map(
      (t) => `${t.id}: ui=${t.lufs} sidecar=${table[t.id]}`,
    );
    expect(mismatched).toEqual([]);
  });

  it('leaves no sidecar loudness target unreachable from the UI', () => {
    // Every DISTINCT value in the engine's table must be pickable. Aliases
    // (x/twitter, broadcast/ebu) collapse to one UI row on purpose; a NEW value
    // (say a -16 platform) would have no row and must fail here.
    const engineValues = [...new Set(Object.values(sidecarPlatformLoudness()))].sort(
      (a, b) => a - b,
    );
    const uiValues = [...new Set(LOUDNESS_TARGETS.map((t) => t.lufs))].sort((a, b) => a - b);
    expect(uiValues).toEqual(engineValues);
  });

  it('has unique ids and a non-empty label per row', () => {
    const ids = LOUDNESS_TARGETS.map((t) => t.id);
    expect(new Set(ids).size).toBe(ids.length);
    expect(LOUDNESS_TARGETS.every((t) => t.label.length > 0)).toBe(true);
  });
});

describe('mix defaults mirror the sidecar module constants', () => {
  it('bed gain / duck threshold / duck ratio match audiomix.py', () => {
    expect(DEFAULT_BG_GAIN_DB).toBe(sidecarConstant('DEFAULT_BG_GAIN_DB'));
    expect(DEFAULT_DUCK_THRESHOLD).toBe(sidecarConstant('DEFAULT_DUCK_THRESHOLD'));
    expect(DEFAULT_DUCK_RATIO).toBe(sidecarConstant('DEFAULT_DUCK_RATIO'));
  });
});
