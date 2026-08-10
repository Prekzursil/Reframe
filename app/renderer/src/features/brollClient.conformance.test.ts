// Conformance test for the auto-b-roll wire surface + the MIRRORED engine constants.
//
// TWO things drift silently and this file makes both fail the build.
//
// 1. THE METHOD SET. A wrapper naming a method the sidecar does not register is a
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
//    REFUTED, AND FIXED — this file's first draft said "`client.broll.*` is the
//    renderer's only typed door to the flagship". That was FALSE. `features/
//    BrollPanel.tsx` is the door, and it reached the bridge with its own
//    hand-written copies of the same seven strings; `client.broll` appeared in
//    ZERO files under `app/` outside this one. A reviewer proved the gap
//    executably: renaming the PANEL's `'broll.removeAsset'` to `'broll.remove'`
//    left this suite 16/16 GREEN and `tsc --noEmit` at exit 0, i.e. the
//    sidecar-anchored check was guarding a surface no user path executes. The fix
//    is `lib/rpc/client.ts`'s exported `BROLL_METHODS` map: BOTH the wrappers and
//    the panel now read every method string from it, and the test below pins THAT
//    MAP against the sidecar, so the strings that actually go on the wire are the
//    pinned ones. `BrollPanel.test.tsx` closes the other half — it drives the
//    mounted panel and asserts the `broll.*` set it emits IS `BROLL_METHODS`.
//
//    RESIDUAL, disclosed rather than papered over: the seven `client.broll.*`
//    wrappers still have no PRODUCTION caller. That is this repo's existing
//    convention rather than a lane invention — measured on this branch,
//    `client.stabilize`, `client.gaze`, `client.audiomix` and `client.speed`
//    likewise appear only in `lib/rpc/*.test.ts`, while their panels call
//    `bridge.rpc` through the injectable `api` prop (`features/_api.ts`, which
//    exists precisely so a panel can be mounted against a fake bridge). Routing
//    the panel through the module-singleton `client` would break that injection
//    seam for one panel out of many. The settling experiment for whether the
//    wrappers should exist at all is a repo-wide decision on the `_api.ts` seam,
//    not a b-roll question; until then the value they add is the typed param
//    shapes pinned below.
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
//
// CROSS-LANE COUPLING, stated because "renderer-only, zero changes under
// `sidecar/`" is true of the DIFF and still understates this: two of the four
// paths read below — `handlers/composition.py` and `tests/test_handlers_rpc_
// surface.py` — are sidecar files, so an edit there can redden the RENDERER
// suite. Reading `features/*.py` from a renderer conformance test is well
// precedented here (AudioMix, batchSurface, languages, reframeDegraded,
// captionTemplates all do it); reading the composition root and the frozen-surface
// test is NOT — this is the only one of the ten `*conformance*` files that does.
// The exposure is bounded: the two scanners key on `reg("broll.` and on per-line
// `"broll.x",` entries, so only an edit to the broll REGISTRATIONS can move them,
// which is exactly the drift this file exists to catch. Accepted deliberately —
// the three-way cross-check is what makes a single hand-written list impossible.
import { describe, it, expect, vi, afterEach } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

import { BROLL_METHODS, client } from '../lib/rpc/client';
import {
  BROLL_LAYOUTS,
  BROLL_REASON_MATCHED,
  BROLL_REASON_NO_MATCH,
  DEFAULT_BROLL_COOLDOWN_SEC,
  DEFAULT_BROLL_MAX_COVERAGE_PCT,
  DEFAULT_BROLL_MIN_DURATION_SEC,
  DEFAULT_BROLL_THRESHOLD,
  THRESHOLD_IS_UNCALIBRATED,
} from './BrollPanel';

// app/renderer/src/features -> repo root is four levels up.
const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(HERE, '..', '..', '..', '..');
const SIDECAR = resolve(REPO_ROOT, 'sidecar');
const BROLL_PLAN = resolve(SIDECAR, 'media_studio', 'features', 'broll_plan.py');
const BROLL_OPS = resolve(SIDECAR, 'media_studio', 'features', 'broll_ops.py');
const COMPOSITION = resolve(SIDECAR, 'media_studio', 'handlers', 'composition.py');
const FROZEN_SURFACE = resolve(SIDECAR, 'tests', 'test_handlers_rpc_surface.py');

/**
 * The `.py` source, read verbatim.
 *
 * LINE ENDINGS ARE NOT A HAZARD HERE, and that is MEASURED, not assumed — the
 * usual worry is that the `pyNumber` / `pyString` patterns below anchor with `$`
 * straight after the value, which would fail on a CRLF checkout. It does not:
 * ECMAScript counts `\r` itself as a LineTerminator, so in multiline mode `$`
 * matches before `\r\n` exactly as it does before `\n`.
 *
 * PROBED BOTH WAYS rather than reasoned about: the four parsed `.py` files were
 * rewritten to CRLF and this suite stayed 16/16 green. A first draft of this
 * helper added a `.replace(/\r\n/g, '\n')` on the stated premise that the parse
 * "would fail to match" on CRLF — that premise was REFUTED by the probe above, so
 * the line was removed rather than kept with a false rationale attached to it.
 * (For the record the tree is LF anyway: `.gitattributes` carries
 * `* text=auto eol=lf` and all four files measure 0 CRLF, on this box and on CI.)
 */
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

// DETECTOR CONTROL, the single-signal-verification discipline: prove each parser
// can FIND a known-present item, and FAIL on an absent one, before any assertion
// is built on its output. A silently-empty parse would make every check below
// vacuously pass — `expect([]).toEqual([])` is green and measures nothing.
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

  // THE FIX FOR THE SURVIVING MUTANT (see the header). Pinning the WRAPPERS was
  // never enough, because the shipped door is `BrollPanel.tsx`. Both now read
  // every method string from `BROLL_METHODS`, so pinning the MAP pins the wire.
  // The panel-side half of the chain — that the mounted panel emits exactly this
  // set — is asserted in `BrollPanel.test.tsx`.
  it('BROLL_METHODS (the ONE source both the wrappers and the panel read) IS the sidecar surface', () => {
    const engine = pyStringTuple(BROLL_OPS, 'METHODS');
    const wired = registeredMethods('broll');
    const registered = [...new Set([...engine, ...wired])].sort();
    expect(Object.values(BROLL_METHODS).sort()).toEqual(registered);
    // and the same set, read a third way (the frozen surface).
    expect(Object.values(BROLL_METHODS).sort()).toEqual([...frozenMethods('broll')].sort());
  });

  it('every wrapper puts its OWN mapped string on the wire (no key/value crossover)', async () => {
    // A map whose values are all correct can still be wired to the wrong wrapper —
    // `status: () => rpc(BROLL_METHODS.assets)` type-checks and passes the SET
    // comparison above. Pin the pairing, not just the membership.
    const rpc = installApi();
    await client.broll.status();
    await client.broll.assets();
    await client.broll.addAsset('D:/broll/dog.png');
    await client.broll.removeAsset('cccc3333dddd4444');
    await client.broll.index();
    await client.broll.suggest('v1');
    await client.broll.apply('v1', []);
    expect(rpc.mock.calls.map((call) => String(call[0]))).toEqual([
      BROLL_METHODS.status,
      BROLL_METHODS.assets,
      BROLL_METHODS.addAsset,
      BROLL_METHODS.removeAsset,
      BROLL_METHODS.index,
      BROLL_METHODS.suggest,
      BROLL_METHODS.apply,
    ]);
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

  // THE DISCLOSURE, not just the seed. REFUTED first draft: the seed was pinned
  // here while `THRESHOLD_IS_UNCALIBRATED` carried a HARD-CODED '0.22' and its only
  // test was `toContain('0.22')` — another literal, satisfied by stale copy. So the
  // §11.2 calibration would have reddened the seed pin, a dev would bump the one
  // constant, and the panel would then seed 0.31 while TELLING the user the
  // starting value is 0.22. The copy is now interpolated from the constant and
  // pinned against the sidecar here, so the number on screen cannot outlive it.
  it('the threshold DISCLOSURE quotes the sidecar number, not a frozen literal', () => {
    expect(THRESHOLD_IS_UNCALIBRATED).toContain(
      String(pyNumber(BROLL_PLAN, 'DEFAULT_MIN_SIMILARITY')),
    );
  });

  it('the coverage field seed IS broll_plan.DEFAULT_MAX_COVERAGE_PCT', () => {
    expect(DEFAULT_BROLL_MAX_COVERAGE_PCT).toBe(pyNumber(BROLL_PLAN, 'DEFAULT_MAX_COVERAGE_PCT'));
  });

  // The empty-plan copy NAMES these two as causes an empty result can have, so
  // they are mirrors like the rest and drift the same way.
  it('the placement limits quoted in the empty-plan copy ARE the planner defaults', () => {
    expect(DEFAULT_BROLL_MIN_DURATION_SEC).toBe(pyNumber(BROLL_PLAN, 'DEFAULT_MIN_DURATION_SEC'));
    expect(DEFAULT_BROLL_COOLDOWN_SEC).toBe(pyNumber(BROLL_PLAN, 'DEFAULT_COOLDOWN_SEC'));
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
