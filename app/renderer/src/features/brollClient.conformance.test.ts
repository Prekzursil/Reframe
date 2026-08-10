// Conformance test for the auto-b-roll wire surface + the MIRRORED engine constants.
//
// TWO things drift silently and this file makes both fail the build.
//
// 1. THE METHOD SET. `client.broll.*` is the renderer's only typed door to the
//    flagship. A wrapper naming a method the sidecar does not register is a
//    guaranteed runtime "method not found", and a REGISTERED method with no wrapper
//    is exactly the defect this lane exists to fix (the whole family had zero
//    callers under `app/`). So the method strings the wrappers actually PUT ON THE
//    WIRE are collected from a spy and compared against THREE independent readings
//    of the sidecar source, not against a hand-written list:
//      * the frozen surface  `sidecar/tests/test_handlers_rpc_surface.py`
//      * the engine's own    `broll_ops.METHODS` tuple
//      * the composition root `handlers/composition.py` `reg("broll.…")` calls
//    The engine tuple and the composition root each cover only PART of the family
//    (four engine methods vs the three BR1 registry methods), so their UNION is the
//    real registration and the frozen list is the independent check on it.
//
// 2. THE MIRRORED CONSTANTS. The panel seeds its threshold slider from
//    `broll_plan.DEFAULT_MIN_SIMILARITY`, its coverage field from
//    `DEFAULT_MAX_COVERAGE_PCT`, its style picker from `LAYOUTS`, and its
//    empty-plan copy from `broll_ops.NO_CONFIDENT_MATCH`. Every one of those is a
//    value the SIDECAR owns. The threshold in particular is documented in-module as
//    an UNCALIBRATED placeholder, so a later calibration WILL change it — and if
//    this mirror is not pinned, the slider would keep seeding the old guess while
//    the sidecar used the measured value, and the panel would be lying about which
//    number is in force.
//
// Reads the REAL `.py` sources (never a copy), the same idiom as
// `AudioMix.conformance.test.ts`. Runs in the default node environment.
import { describe, it, expect, vi, afterEach } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

import { client } from '../lib/rpc/client';
import {
  BROLL_LAYOUTS,
  BROLL_REASON_MATCHED,
  BROLL_REASON_NO_MATCH,
  DEFAULT_BROLL_MAX_COVERAGE_PCT,
  DEFAULT_BROLL_THRESHOLD,
} from './BrollPanel';

// app/renderer/src/features -> repo root is four levels up.
const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(HERE, '..', '..', '..', '..');
const SIDECAR = resolve(REPO_ROOT, 'sidecar');
const BROLL_PLAN = resolve(SIDECAR, 'media_studio', 'features', 'broll_plan.py');
const BROLL_OPS = resolve(SIDECAR, 'media_studio', 'features', 'broll_ops.py');
const COMPOSITION = resolve(SIDECAR, 'media_studio', 'handlers', 'composition.py');
const FROZEN_SURFACE = resolve(SIDECAR, 'tests', 'test_handlers_rpc_surface.py');

function source(path: string): string {
  return readFileSync(path, 'utf8');
}

/** Parse a top-level `NAME = <number>` module constant. */
function pyNumber(path: string, name: string): number {
  const m = source(path).match(new RegExp(`^${name} = (-?\\d+(?:\\.\\d+)?)$`, 'm'));
  if (!m) throw new Error(`could not find ${name} in ${path}`);
  return Number(m[1]);
}

/** Parse a top-level `NAME = "<text>"` module constant. */
function pyString(path: string, name: string): string {
  const m = source(path).match(new RegExp(`^${name} = "([^"]*)"$`, 'm'));
  if (!m) throw new Error(`could not find ${name} in ${path}`);
  return m[1];
}

/** Parse a top-level `NAME: <ann> = ("a", "b")` / `NAME = ("a", "b")` tuple. */
function pyStringTuple(path: string, name: string): string[] {
  const m = source(path).match(new RegExp(`^${name}(?::[^=]+)? = \\(([^)]*)\\)`, 'm'));
  if (!m) throw new Error(`could not find ${name} in ${path}`);
  return [...m[1].matchAll(/"([^"]+)"/g)].map((hit) => hit[1]);
}

/** Every `"<prefix>.<name>",` entry of the frozen-surface set literal. */
function frozenMethods(prefix: string): string[] {
  const pattern = new RegExp(`^\\s*"(${prefix}\\.[A-Za-z.]+)",\\s*$`, 'gm');
  return [...source(FROZEN_SURFACE).matchAll(pattern)].map((hit) => hit[1]);
}

/** Every `reg("<prefix>.<name>"` call in the composition root. */
function registeredMethods(prefix: string): string[] {
  const pattern = new RegExp(`reg\\("(${prefix}\\.[A-Za-z.]+)"`, 'g');
  return [...source(COMPOSITION).matchAll(pattern)].map((hit) => hit[1]);
}

/** Install a fake preload bridge so `rpc()` resolves through a spy. */
function installApi(): ReturnType<typeof vi.fn> {
  const rpc = vi.fn().mockResolvedValue({ jobId: 'job-b' });
  (globalThis as { window?: { api?: unknown } }).window = {
    api: { rpc, onProgress: vi.fn(() => () => {}) },
  };
  return rpc;
}

afterEach(() => {
  delete (globalThis as { window?: unknown }).window;
  vi.restoreAllMocks();
});

// rules/common/single-signal-verification.md §3: prove each parser can FIND a
// known-present item, and FAIL on an absent one, before any assertion is built on
// its output. A silently-empty parse would make every check below vacuously pass —
// `expect([]).toEqual([])` is green and measures nothing.
describe('sidecar parse helpers (detector control)', () => {
  it('finds a known-present number, string and tuple', () => {
    expect(pyNumber(BROLL_PLAN, 'DEFAULT_TOP_K')).toBe(5);
    expect(pyString(BROLL_OPS, 'MATCHED')).toBe('matched');
    expect(pyStringTuple(BROLL_PLAN, 'LAYOUTS')).toContain('cutaway');
  });

  it('throws (never silently returns a default) when the symbol is absent', () => {
    expect(() => pyNumber(BROLL_PLAN, 'NOT_A_REAL_CONSTANT')).toThrow(/could not find/);
    expect(() => pyString(BROLL_OPS, 'NOT_A_REAL_CONSTANT')).toThrow(/could not find/);
    expect(() => pyStringTuple(BROLL_PLAN, 'NOT_A_REAL_TUPLE')).toThrow(/could not find/);
  });

  it('the method scanners find a known-present NON-broll method, and no bogus one', () => {
    // `captions.cues` sits in the same frozen set literal; `library.list` is
    // registered through the same `reg(...)` call shape. If either scanner returned
    // an empty list the broll assertions below would pass for the wrong reason.
    expect(frozenMethods('captions')).toContain('captions.cues');
    expect(registeredMethods('library')).toContain('library.list');
    expect(frozenMethods('definitelynotarealnamespace')).toEqual([]);
  });
});

describe('client.broll covers exactly the registered broll.* surface', () => {
  /** The method strings the seven wrappers actually put on the wire. */
  async function wireMethods(): Promise<string[]> {
    const rpc = installApi();
    await client.broll.status();
    await client.broll.assets();
    await client.broll.addAsset('D:/broll/dog.png');
    await client.broll.removeAsset('cccc3333dddd4444');
    await client.broll.index();
    await client.broll.suggest('v1');
    await client.broll.apply('v1', []);
    return rpc.mock.calls.map((call) => String(call[0]));
  }

  it('matches the FROZEN rpc surface exactly — no phantom, no orphan', async () => {
    const sent = [...new Set(await wireMethods())].sort();
    const frozen = [...frozenMethods('broll')].sort();
    expect(frozen).toHaveLength(7);
    expect(sent).toEqual(frozen);
  });

  it('matches the composition root + engine tuple (a second, independent reading)', async () => {
    const sent = [...new Set(await wireMethods())].sort();
    // The engine module owns four methods; BR1's three registry methods are wired
    // as closures in the composition root. Neither list is the whole family.
    const engine = pyStringTuple(BROLL_OPS, 'METHODS');
    const wired = registeredMethods('broll');
    expect(engine).toHaveLength(4);
    expect(wired).toHaveLength(3);
    expect([...new Set([...engine, ...wired])].sort()).toEqual(sent);
  });
});

describe('client.broll wire shapes', () => {
  it('status / assets take no params', async () => {
    const rpc = installApi();
    await client.broll.status();
    await client.broll.assets();
    expect(rpc).toHaveBeenNthCalledWith(1, 'broll.status', undefined);
    expect(rpc).toHaveBeenNthCalledWith(2, 'broll.assets', undefined);
  });

  it('addAsset OMITS title entirely when none is given (never an empty-string title)', async () => {
    const rpc = installApi();
    await client.broll.addAsset('D:/broll/dog.png');
    expect(rpc).toHaveBeenCalledWith('broll.addAsset', { path: 'D:/broll/dog.png' });
  });

  it('addAsset forwards a title when one is given', async () => {
    const rpc = installApi();
    await client.broll.addAsset('D:/broll/dog.png', 'Hero dog');
    expect(rpc).toHaveBeenCalledWith('broll.addAsset', {
      path: 'D:/broll/dog.png',
      title: 'Hero dog',
    });
  });

  it('removeAsset sends the id under the key the handler reads', async () => {
    const rpc = installApi();
    await client.broll.removeAsset('cccc3333dddd4444');
    expect(rpc).toHaveBeenCalledWith('broll.removeAsset', { id: 'cccc3333dddd4444' });
  });

  it('index defaults force to false and forwards an explicit true', async () => {
    const rpc = installApi();
    await client.broll.index();
    await client.broll.index(true);
    expect(rpc).toHaveBeenNthCalledWith(1, 'broll.index', { force: false });
    expect(rpc).toHaveBeenNthCalledWith(2, 'broll.index', { force: true });
  });

  it('suggest forwards videoId alone, and the full tunable set when given', async () => {
    const rpc = installApi();
    await client.broll.suggest('v1');
    await client.broll.suggest('v1', { threshold: 0.45, maxCoveragePct: 25, layout: 'pip' });
    expect(rpc).toHaveBeenNthCalledWith(1, 'broll.suggest', { videoId: 'v1' });
    expect(rpc).toHaveBeenNthCalledWith(2, 'broll.suggest', {
      videoId: 'v1',
      threshold: 0.45,
      maxCoveragePct: 25,
      layout: 'pip',
    });
  });

  it('apply sends the REVIEWED list verbatim under `insertions`', async () => {
    const rpc = installApi();
    const insertion = {
      segmentIndex: 0,
      start: 4,
      end: 8,
      duration: 4,
      sourceStart: 0,
      assetId: 'cccc3333dddd4444',
      path: 'D:/broll/dog.png',
      kind: 'image',
      score: 0.61,
      reason: '"the dog ran off" (0.61)',
      layout: 'cutaway',
    };
    await client.broll.apply('v1', [insertion]);
    // `insertions`, NOT the design doc's first-draft `suggestions`
    // (docs/plans/v1.5/flagship-auto-broll.md §5) — the landed handler reads
    // `params.get("insertions")` and raises INVALID_PARAMS on an empty list.
    expect(rpc).toHaveBeenCalledWith('broll.apply', { videoId: 'v1', insertions: [insertion] });
  });
});

describe('renderer mirrors of the sidecar planner constants', () => {
  // THE THRESHOLD PIN. The panel ships option (a) — a slider seeded from this
  // value and sent EXPLICITLY on every suggest. That is only honest while the seed
  // equals what the sidecar would have used, so a calibration landing in
  // `broll_plan.py` (the §11.2 experiment) must fail here and force the mirror,
  // rather than leaving the slider seeding a superseded guess.
  it('the slider seed IS broll_plan.DEFAULT_MIN_SIMILARITY', () => {
    expect(DEFAULT_BROLL_THRESHOLD).toBe(pyNumber(BROLL_PLAN, 'DEFAULT_MIN_SIMILARITY'));
  });

  it('the coverage field seed IS broll_plan.DEFAULT_MAX_COVERAGE_PCT', () => {
    expect(DEFAULT_BROLL_MAX_COVERAGE_PCT).toBe(pyNumber(BROLL_PLAN, 'DEFAULT_MAX_COVERAGE_PCT'));
  });

  it('offers exactly the layouts the planner accepts, default first', () => {
    // `broll_plan.suggest` raises ValueError on anything outside LAYOUTS, so a
    // renderer-only option would be a guaranteed job failure.
    expect([...BROLL_LAYOUTS]).toEqual(pyStringTuple(BROLL_PLAN, 'LAYOUTS'));
    expect(BROLL_LAYOUTS[0]).toBe(pyString(BROLL_PLAN, 'DEFAULT_LAYOUT'));
  });

  it('quotes the engine reason strings verbatim, not a paraphrase', () => {
    expect(BROLL_REASON_NO_MATCH).toBe(pyString(BROLL_OPS, 'NO_CONFIDENT_MATCH'));
    expect(BROLL_REASON_MATCHED).toBe(pyString(BROLL_OPS, 'MATCHED'));
  });
});
