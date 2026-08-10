// Cross-boundary conformance test for the reframe `reframeDegraded` signal.
//
// WHY THIS EXISTS: the sidecar side of this signal was 100% covered and the
// renderer side was 100% covered, and the signal STILL never reached a user —
// because nothing tested the SEAM between them. Both halves can be perfectly
// green while the renderer reads a key the sidecar does not send (or reads
// nothing at all). This test reads the REAL source files on both sides, so a
// rename on either side fails the build.
//
// DIRECTION: renderer ⊆ sidecar. The sidecar may legitimately send a field the UI
// does not render yet (unfinished UI, not a lie); the reverse — the renderer
// promising to read something that is never sent — is the defect class guarded
// here. Mirrors ./rpc/batchSurface.conformance.test.ts. Node env (filesystem).
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';
import { REFRAME_DEGRADED_KEY } from './reframeDegraded';

// app/renderer/src/lib -> repo root is four levels up.
const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(HERE, '..', '..', '..', '..');
const SIDECAR = resolve(REPO_ROOT, 'sidecar', 'media_studio', 'features');

const RENDERER_TS = resolve(HERE, 'reframeDegraded.ts');
const SHORTMAKER_PY = resolve(SIDECAR, 'shortmaker.py');
const CLAUDESHORTS_PY = resolve(SIDECAR, 'reframe_claudeshorts.py');
const MULTISPEAKER_PY = resolve(SIDECAR, 'reframe_multispeaker.py');

/** The literal keys of the dict a python factory returns. */
function pyReturnDictKeys(file: string, fnName: string): string[] {
  const src = readFileSync(file, 'utf8');
  const start = src.indexOf(`def ${fnName}(`);
  if (start < 0) return [];
  const after = src.slice(start);
  const nextDef = after.indexOf('\ndef ');
  const body = nextDef < 0 ? after : after.slice(0, nextDef);
  const open = body.indexOf('return {');
  if (open < 0) return [];
  // Close on a `}` that OPENS ITS OWN LINE. A plain indexOf('}') truncates the
  // dict at the `{reason}` placeholder inside the f-string message — measured:
  // it silently dropped the "reason" key and produced a false conformance
  // failure. The closing brace of a black-formatted dict is always line-leading.
  const region = body.slice(open);
  const close = /\n\s*\}/.exec(region);
  const dict = close === null ? region : region.slice(0, close.index);
  return [...dict.matchAll(/^\s*"([A-Za-z_][A-Za-z0-9_]*)":/gm)].map((m) => m[1]).sort();
}

/** The declared field names of a TS interface. */
function tsInterfaceFields(file: string, name: string): string[] {
  const src = readFileSync(file, 'utf8');
  const start = src.indexOf(`export interface ${name} {`);
  if (start < 0) return [];
  const body = src.slice(start, src.indexOf('\n}', start));
  return [...body.matchAll(/^ {2}([A-Za-z][A-Za-z0-9]*)\??:/gm)].map((m) => m[1]).sort();
}

describe('reframeDegraded sidecar/renderer conformance', () => {
  // Detector control (fail-closed): a parser that silently matched nothing would
  // make every assertion below vacuously true. These guards make a broken parser
  // fail LOUDLY instead of certifying an empty set as conformant.
  it('parses a non-empty sidecar notice shape (guards a vacuous pass)', () => {
    expect(pyReturnDictKeys(CLAUDESHORTS_PY, 'make_degraded_notice').length).toBeGreaterThan(0);
  });

  it('parses a non-empty renderer notice shape (guards a vacuous pass)', () => {
    expect(tsInterfaceFields(RENDERER_TS, 'ReframeDegradedNotice').length).toBeGreaterThan(0);
  });

  it('reads the key the sidecar actually stamps on the clip payload', () => {
    const src = readFileSync(SHORTMAKER_PY, 'utf8');
    expect(src).toContain(`clip["${REFRAME_DEGRADED_KEY}"]`);
  });

  it('declares no notice field the center-crop producer does not send', () => {
    const sidecar = pyReturnDictKeys(CLAUDESHORTS_PY, 'make_degraded_notice');
    const renderer = tsInterfaceFields(RENDERER_TS, 'ReframeDegradedNotice');
    expect(renderer.filter((f) => !sidecar.includes(f))).toEqual([]);
  });

  it('declares no notice field the engine-degrade producer does not send', () => {
    const sidecar = pyReturnDictKeys(MULTISPEAKER_PY, 'make_engine_degrade_notice');
    const renderer = tsInterfaceFields(RENDERER_TS, 'ReframeDegradedNotice');
    expect(renderer.filter((f) => !sidecar.includes(f))).toEqual([]);
  });
});
