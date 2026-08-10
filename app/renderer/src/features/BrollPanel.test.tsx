// BrollPanel.test.tsx — tests for the "Auto B-roll" panel (W16-UI).
//
// MEASURED GAP, detector controlled BOTH ways before a line was written.
// The sidecar ships ~58 KB of b-roll engine across four modules
// (`sidecar/media_studio/features/broll_ops.py`, `broll_plan.py`, `broll_index.py`,
// `broll_compose.py`) and SEVEN registered RPCs, frozen into the authoritative
// method list (`sidecar/tests/test_handlers_rpc_surface.py:52-58`). Probe, run at
// 2e1f5fbf:
//   target : rg -i broll app/   -> 0 files
//   control: rg -i broll sidecar/ -> 15 files (so the matcher fires)
// i.e. the whole flagship was unreachable by any user. This panel is the surface.
//
// THE SEVEN RPCs AND THEIR TRANSPORT (read off the landed code, not the design doc):
//   broll.assets()                        -> {assets, missing}   direct
//   broll.addAsset({path, title?})        -> {asset}             direct
//   broll.removeAsset({id})               -> {ok}                direct
//   broll.status()                        -> {indexed, assetCount, libraryCount,
//                                             model, dim, stale, staleCount,
//                                             willEgress}         direct
//   broll.index({force?})                 -> {jobId} -> {assetCount, embedded, ...}
//   broll.suggest({videoId, threshold?, maxCoveragePct?, layout?})
//                                         -> {jobId} -> {insertions, reason, ...}
//   broll.apply({videoId, insertions})    -> {jobId} -> {path, inserted}
//
// FIVE LANDED-CODE FACTS THAT EACH GET THEIR OWN CASE HERE, because working from
// the design doc instead would have got each one wrong:
//   1. `durationSec` is `number | null` (a SCANNED row reports None; a REGISTERED
//      row reports 0.0) — `library.py:615` / `broll_ops.py:131`.
//   2. A registered asset has NO poster: `add_broll` writes `""` and the only
//      writer, `Library.set_thumbnail`, is `role='source'`-scoped
//      (`library.py:477-490,569`). A grid that assumes an image renders holes.
//   3. `missing` is a FEATURE, not an error (`handlers/library_ops.py:400-406`).
//   4. TWO sources, ONE list: `broll_asset_rows` merges the `brollDir` scan with
//      the BR1 registry (`handlers/library_ops.py:373-449`), so the panel must
//      read that one seam and never build a second lister.
//   5. A non-canonical `brollDir` spelling diverges `assetId`
//      (`handlers/library_ops.py:416-427`), so no UI state may be keyed on it
//      across a library change — the review list is keyed by POSITION.

// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import BrollPanel, {
  APPLY_IS_ONE_WAY,
  BROLL_LAYOUTS,
  BROLL_NEEDS_TRANSCRIPT,
  BROLL_REASON_NO_MATCH,
  DEFAULT_BROLL_COOLDOWN_SEC,
  DEFAULT_BROLL_MAX_COVERAGE_PCT,
  DEFAULT_BROLL_MIN_DURATION_SEC,
  DEFAULT_BROLL_THRESHOLD,
  NO_POSTER_LABEL,
  THRESHOLD_IS_UNCALIBRATED,
  assetDurationLabel,
  assetLabel,
  emptyPlanExplanation,
  insertionWindowLabel,
  isCoverageUsable,
  posterSrc,
  readBrollAssets,
  readBrollPlan,
  readBrollStatus,
} from './BrollPanel';
import { BROLL_METHODS, type BrollAsset } from '../lib/rpc';
import type { DoneEvent, MediaStudioApi, ProgressEvent } from './_api';

// --- fixtures --------------------------------------------------------------

/** A row as the `brollDir` SCAN emits it (`broll_ops.scan_assets`). */
const SCANNED: BrollAsset = {
  assetId: 'aaaa1111bbbb2222',
  path: 'C:/broll/city.mp4',
  kind: 'video',
  sizeBytes: 1024,
  mtime: 1000,
  durationSec: null,
  registered: false,
};

/** A row as the BR1 REGISTRY emits it (`Library._row_to_broll_asset`). */
const REGISTERED: BrollAsset = {
  assetId: 'cccc3333dddd4444',
  path: 'D:/pictures/hero dog.png',
  kind: 'image',
  entityKind: 'brollImage',
  title: 'Hero dog',
  addedAt: '2026-08-10T00:00:00Z',
  durationSec: 0,
  contentHash: null,
  thumbnailPath: '',
  sizeBytes: 2048,
  mtime: 2000,
  exists: true,
  registered: true,
};

/** A registered row whose file has since vanished (the `missing` half). */
const VANISHED: BrollAsset = {
  ...REGISTERED,
  assetId: 'eeee5555ffff6666',
  path: 'D:/pictures/gone.png',
  title: 'Gone',
  sizeBytes: 0,
  mtime: 0,
  exists: false,
};

const STATUS = {
  indexed: true,
  assetCount: 2,
  libraryCount: 3,
  model: 'google/siglip2-so400m-patch16-384',
  dim: 1152,
  stale: true,
  staleCount: 1,
  willEgress: false,
};

const INSERTION_A = {
  segmentIndex: 0,
  start: 4,
  end: 8,
  duration: 4,
  sourceStart: 0,
  assetId: REGISTERED.assetId,
  path: REGISTERED.path,
  kind: 'image',
  score: 0.61,
  reason: '"the dog ran off" (0.61)',
  layout: 'cutaway',
};
const INSERTION_B = {
  ...INSERTION_A,
  segmentIndex: 4,
  start: 30,
  end: 33,
  duration: 3,
  assetId: SCANNED.assetId,
  path: SCANNED.path,
  kind: 'video',
  score: 0.34,
  reason: '"downtown at night" (0.34)',
};

// --- fake bridge -----------------------------------------------------------

interface FakeApi {
  api: MediaStudioApi;
  calls: Array<{ method: string; params?: Record<string, unknown> }>;
  fireProgress: (ev: ProgressEvent) => void;
  fireDone: (ev: DoneEvent) => void;
}

interface Overrides {
  assets?: unknown;
  assetsError?: Error;
  status?: unknown;
  addError?: Error;
  indexError?: Error;
  suggestError?: Error;
  jobless?: boolean;
  cancelError?: Error;
}

function makeFakeApi(overrides: Overrides = {}): FakeApi {
  const calls: FakeApi['calls'] = [];
  let progressCbs: Array<(ev: ProgressEvent) => void> = [];
  let doneCbs: Array<(ev: DoneEvent) => void> = [];
  const handle = overrides.jobless ? {} : { jobId: 'job-b' };
  const api: MediaStudioApi = {
    rpc: vi.fn(async <T,>(method: string, params?: Record<string, unknown>) => {
      calls.push({ method, params });
      if (method === 'broll.assets') {
        if (overrides.assetsError) throw overrides.assetsError;
        return (overrides.assets ?? { assets: [SCANNED, REGISTERED], missing: [VANISHED] }) as T;
      }
      if (method === 'broll.status') return (overrides.status ?? STATUS) as T;
      if (method === 'broll.addAsset') {
        if (overrides.addError) throw overrides.addError;
        return { asset: REGISTERED } as T;
      }
      if (method === 'broll.removeAsset') return { ok: true } as T;
      if (method === 'broll.index') {
        if (overrides.indexError) throw overrides.indexError;
        return handle as T;
      }
      if (method === 'broll.suggest') {
        if (overrides.suggestError) throw overrides.suggestError;
        return handle as T;
      }
      if (method === 'broll.apply') return handle as T;
      if (method === 'job.cancel') {
        if (overrides.cancelError) throw overrides.cancelError;
        return { ok: true } as T;
      }
      return {} as T;
    }) as MediaStudioApi['rpc'],
    onProgress: (cb) => {
      progressCbs.push(cb);
      return () => {
        progressCbs = progressCbs.filter((c) => c !== cb);
      };
    },
    onJobDone: (cb) => {
      doneCbs.push(cb);
      return () => {
        doneCbs = doneCbs.filter((c) => c !== cb);
      };
    },
  };
  return {
    api,
    calls,
    fireProgress: (ev) => progressCbs.slice().forEach((cb) => cb(ev)),
    fireDone: (ev) => doneCbs.slice().forEach((cb) => cb(ev)),
  };
}

// --- pure helpers ----------------------------------------------------------

describe('readBrollAssets (the ONE list — fact 4)', () => {
  it('partitions {assets, missing} and preserves every landed field', () => {
    expect(readBrollAssets({ assets: [SCANNED, REGISTERED], missing: [VANISHED] })).toEqual({
      assets: [SCANNED, REGISTERED],
      missing: [VANISHED],
    });
  });

  it('degrades a shapeless payload to two EMPTY lists rather than throwing', () => {
    expect(readBrollAssets(null)).toEqual({ assets: [], missing: [] });
    expect(readBrollAssets({ assets: 'nope', missing: 7 })).toEqual({ assets: [], missing: [] });
  });

  it('drops a row with no usable assetId/path — a phantom must never reach the grid', () => {
    expect(
      readBrollAssets({
        assets: [SCANNED, { assetId: '', path: 'C:/x.png' }, { path: 'C:/y.png' }, 42],
        missing: [],
      }).assets,
    ).toEqual([SCANNED]);
  });
});

describe('readBrollStatus', () => {
  it('reads the freshness snapshot the sidecar actually returns', () => {
    expect(readBrollStatus(STATUS)).toEqual(STATUS);
  });

  it('returns null for a shapeless payload (renders nothing, never junk)', () => {
    expect(readBrollStatus(null)).toBeNull();
    expect(readBrollStatus('nope')).toBeNull();
  });

  // REFUTED, and this is the red-proof. The first draft only rejected NON-objects,
  // so `{}` — the canonical shapeless payload, and exactly what the lane's own
  // real-mount seam test feeds every rpc — fell through and returned a full
  // snapshot of zeros. Rendered, that reads "In library 0", a hard number the
  // panel never measured, from a docstring promising the opposite.
  it('returns null for an OBJECT carrying none of the snapshot fields ({} is not a snapshot)', () => {
    expect(readBrollStatus({})).toBeNull();
    expect(readBrollStatus({ somethingElse: 1 })).toBeNull();
  });

  // The coercion half was always right and is UNCHANGED: once a payload proves it
  // is a snapshot by carrying at least one known field, its absent siblings become
  // explicit zeros rather than `undefined` leaking into the DOM.
  it('coerces the ABSENT siblings of a partial payload to explicit zeros/falses', () => {
    expect(readBrollStatus({ indexed: false })).toEqual({
      indexed: false,
      assetCount: 0,
      libraryCount: 0,
      model: '',
      dim: 0,
      stale: false,
      staleCount: 0,
      willEgress: false,
    });
    // …and the detector fires on EVERY one of the eight, not just the first.
    expect(readBrollStatus({ willEgress: true })?.willEgress).toBe(true);
    expect(readBrollStatus({ libraryCount: 3 })?.libraryCount).toBe(3);
  });
});

describe('isCoverageUsable (the emptied-number-input trap)', () => {
  // `Number('')` is 0, not NaN, and the sidecar's `_opt_float` passes 0 straight
  // through — `float(0)` is valid, so the DEFAULT never kicks in — leaving
  // `budget_sec = total_sec * 0 / 100 = 0`, which rejects every candidate.
  it('rejects the value an emptied number input actually produces', () => {
    expect(isCoverageUsable(Number(''))).toBe(false);
    expect(isCoverageUsable(0)).toBe(false);
  });

  it('rejects a non-finite or out-of-range cap', () => {
    expect(isCoverageUsable(Number.NaN)).toBe(false);
    expect(isCoverageUsable(-5)).toBe(false);
    expect(isCoverageUsable(101)).toBe(false);
  });

  it('accepts the inclusive 1..100 range the input advertises', () => {
    expect(isCoverageUsable(1)).toBe(true);
    expect(isCoverageUsable(DEFAULT_BROLL_MAX_COVERAGE_PCT)).toBe(true);
    expect(isCoverageUsable(100)).toBe(true);
  });
});

// REFUTED COPY. The old sentence — "nothing in your library scored at or above
// {threshold} for any segment" — is a measurement the panel cannot make:
// `broll_ops.py:425` emits the same reason for ANY empty plan, and `place` drops
// candidates for min-duration, coverage budget, min-gap and per-asset cooldown,
// none of which are the score. Executed against the real planner with identical
// unit vectors (cosine 1.00 vs a 0.22 gate): default coverage -> 1 insertion,
// `maxCoveragePct=1` -> 0, a 1.0s segment -> 0.
describe('emptyPlanExplanation', () => {
  it('never asserts the threshold as the cause, and names the causes that are not', () => {
    const copy = emptyPlanExplanation(0.22, 40);
    expect(copy).not.toContain('scored at or above');
    expect(copy).toContain('SAME reason string');
    expect(copy).toContain(`shorter than ${DEFAULT_BROLL_MIN_DURATION_SEC}s`);
    expect(copy).toContain(`within ${DEFAULT_BROLL_COOLDOWN_SEC}s`);
    expect(copy).toContain('too close to another insert');
  });

  it('quotes the dials the user actually set, including the coverage cap', () => {
    const copy = emptyPlanExplanation(0.45, 25);
    expect(copy).toContain('0.45');
    expect(copy).toContain('coverage cap of 25%');
    // The old copy pointed only at the threshold — which for a coverage-caused
    // empty plan is the one control that provably cannot help.
    expect(copy).toContain('RAISE the coverage cap');
  });
});

describe('readBrollPlan', () => {
  it('reads the insertions plus the sidecar reason string verbatim', () => {
    expect(readBrollPlan({ insertions: [INSERTION_A], reason: 'matched' })).toEqual({
      insertions: [INSERTION_A],
      reason: 'matched',
    });
  });

  it('an absent/shapeless payload is the HONEST empty plan, not an error', () => {
    expect(readBrollPlan(null)).toEqual({ insertions: [], reason: BROLL_REASON_NO_MATCH });
    expect(readBrollPlan({ insertions: 'nope' })).toEqual({
      insertions: [],
      reason: BROLL_REASON_NO_MATCH,
    });
  });

  it('drops an insertion row that carries no usable path/assetId', () => {
    expect(
      readBrollPlan({ insertions: [INSERTION_A, { assetId: 'x' }, 3], reason: 'matched' })
        .insertions,
    ).toEqual([INSERTION_A]);
  });
});

// FACT 1 — `durationSec` is `number | null`. Typing it `number` is wrong at
// runtime, and `0.0` is what a registered STILL reports, so neither may render as
// a duration the file does not have.
describe('assetDurationLabel (fact 1: durationSec is number | null)', () => {
  it('a still has no timeline at all', () => {
    expect(assetDurationLabel(REGISTERED)).toBe('still');
  });

  it('formats a real clip duration', () => {
    expect(assetDurationLabel({ ...SCANNED, durationSec: 12.5 })).toBe('12.5s');
  });

  it('a SCANNED clip reports null — shown as unknown, never as 0s', () => {
    expect(assetDurationLabel(SCANNED)).toBe('—');
  });

  it('a probe-failed clip reports 0.0 — also unknown, never "0.0s"', () => {
    expect(assetDurationLabel({ ...SCANNED, durationSec: 0 })).toBe('—');
  });

  it('a non-finite duration is unknown too (NaN never reaches toFixed)', () => {
    expect(assetDurationLabel({ ...SCANNED, durationSec: Number.NaN })).toBe('—');
  });
});

// FACT 2 — registered assets have NO poster.
describe('posterSrc (fact 2: a registered asset has no poster)', () => {
  it('the empty string add_broll writes is NOT an image source', () => {
    expect(posterSrc(REGISTERED)).toBeNull();
  });

  it('an absent thumbnailPath (a scanned row) is not an image source either', () => {
    expect(posterSrc(SCANNED)).toBeNull();
  });

  // REFUTED PIN. This case used to assert the RAW path was the right answer,
  // endorsing a value the renderer cannot load at all: the CSP is
  // `img-src 'self' data: blob: mstream:` (app/main/security.ts:81, mirrored in
  // app/renderer/index.html:17), so a filesystem path never resolves. The whole
  // app routes posters through the traversal-guarded `thumb:` mstream resolver
  // (components/useVideoThumbnail.ts:33, views/LibraryCard.tsx); this now does too.
  it('a real poster is served as the thumb: mstream URL, never as a raw fs path', () => {
    const url = posterSrc({ ...REGISTERED, thumbnailPath: 'D:/th/dog.jpg' });
    expect(url).toBe(`mstream://media/${encodeURIComponent('thumb:D:/th/dog.jpg')}`);
    // one path segment, and a scheme the CSP actually permits
    expect(url?.startsWith('mstream://media/thumb%3A')).toBe(true);
    expect(url).not.toContain('D:/th/dog.jpg');
  });
});

describe('assetLabel', () => {
  it('prefers the registry title', () => {
    expect(assetLabel(REGISTERED)).toBe('Hero dog');
  });

  it('falls back to the basename of a Windows path', () => {
    expect(assetLabel({ ...REGISTERED, title: '   ' })).toBe('hero dog.png');
  });

  it('falls back to the basename of a POSIX path', () => {
    expect(assetLabel(SCANNED)).toBe('city.mp4');
  });

  it('falls back to the assetId when there is no basename at all', () => {
    expect(assetLabel({ ...SCANNED, path: '' })).toBe(SCANNED.assetId);
  });
});

describe('insertionWindowLabel', () => {
  it('states the window the composite will occupy', () => {
    expect(insertionWindowLabel(INSERTION_A)).toBe('4.0s - 8.0s (4.0s)');
  });
});

// --- component -------------------------------------------------------------

describe('<BrollPanel />', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => {
      root.unmount();
    });
    container.remove();
  });

  const flush = async (): Promise<void> => {
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });
  };

  async function mount(api: MediaStudioApi, videoId = 'v1'): Promise<void> {
    await act(async () => {
      root.render(<BrollPanel videoId={videoId} api={api} />);
    });
    await flush();
  }

  async function rerender(api: MediaStudioApi, videoId: string): Promise<void> {
    await act(async () => {
      root.render(<BrollPanel videoId={videoId} api={api} />);
    });
    await flush();
  }

  const q = (selector: string): HTMLElement | null => container.querySelector(selector);
  const btn = (action: string): HTMLButtonElement =>
    container.querySelector(`[data-action="${action}"]`) as HTMLButtonElement;

  function pick(selector: string, value: string): void {
    const el = container.querySelector(selector) as HTMLInputElement;
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
    act(() => {
      setter.call(el, value);
      el.dispatchEvent(new Event('input', { bubbles: true }));
    });
  }

  function choose(selector: string, value: string): void {
    const el = container.querySelector(selector) as HTMLSelectElement;
    const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value')!.set!;
    act(() => {
      setter.call(el, value);
      el.dispatchEvent(new Event('change', { bubbles: true }));
    });
  }

  async function click(action: string): Promise<void> {
    await act(async () => {
      btn(action).click();
      await Promise.resolve();
    });
    await flush();
  }

  function toggle(selector: string): void {
    const el = container.querySelector(selector) as HTMLInputElement;
    act(() => {
      el.click();
    });
  }

  /** Drive a suggest to completion with the given job.done payload. */
  async function suggestWith(fake: FakeApi, result: unknown): Promise<void> {
    await act(async () => {
      btn('suggest').click();
    });
    await flush();
    await act(async () => {
      fake.fireDone({ jobId: 'job-b', result });
      await Promise.resolve();
    });
    await flush();
  }

  it('reads the ONE list on mount and adds no second lister (fact 4)', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    const methods = fake.calls.map((c) => c.method);
    expect(methods).toContain('broll.assets');
    expect(methods).toContain('broll.status');
    // `library.list` is the SOURCE-video lister; reading it here would show a
    // second, different library from the one broll.index actually embeds.
    expect(methods).not.toContain('library.list');
  });

  // THE SHIPPED WIRE STRINGS. A reviewer proved the gap executably: with the seven
  // method names hand-written in this panel, renaming one to a method the sidecar
  // does not register left `brollClient.conformance.test.ts` GREEN at 16/16 and
  // `tsc --noEmit` at exit 0, because that suite only ever saw `client.broll.*` —
  // a wrapper with no production caller. Both now read `BROLL_METHODS`; conformance
  // pins that map against three readings of the sidecar source, and THIS case pins
  // the other end of the chain: what the mounted panel actually emits.
  it('puts ONLY the pinned BROLL_METHODS strings on the wire — never a hand-written literal', async () => {
    const fake = makeFakeApi();
    await mount(fake.api); // assets + status
    pick('[data-input="add-path"]', 'D:/pictures/hero dog.png');
    await click('add'); // addAsset
    await act(async () => {
      (
        container.querySelector(
          `[data-asset-id="${REGISTERED.assetId}"] [data-action="unregister"]`,
        ) as HTMLButtonElement
      ).click();
      await Promise.resolve();
    });
    await flush(); // removeAsset
    await act(async () => {
      btn('index').click();
    });
    await flush();
    await act(async () => {
      fake.fireDone({ jobId: 'job-b', result: { assetCount: 1, embedded: 1 } });
      await Promise.resolve();
    });
    await flush(); // index
    await suggestWith(fake, { insertions: [INSERTION_A], reason: 'matched' }); // suggest
    await act(async () => {
      btn('apply').click();
    });
    await flush();
    await act(async () => {
      fake.fireDone({ jobId: 'job-b', result: { path: 'C:/out/talk.broll.mp4', inserted: 1 } });
      await Promise.resolve();
    });
    await flush(); // apply

    const sent = [
      ...new Set(fake.calls.map((c) => c.method).filter((m) => m.startsWith('broll.'))),
    ].sort();
    // EXACTLY the seven — equality, not containment, so an eighth invented string
    // fails here just as loudly as a renamed one.
    expect(sent).toEqual(Object.values(BROLL_METHODS).slice().sort());
  });

  it('renders the freshness snapshot including libraryCount and staleCount', async () => {
    await mount(makeFakeApi().api);
    const status = q('[data-section="status"]');
    expect(status?.textContent).toContain('3');
    expect(status?.textContent).toContain('siglip2');
    expect(q('[data-field="stale"]')?.textContent).toContain('1');
  });

  it('badges the run as fully local off the wire, not off a hardcoded promise', async () => {
    await mount(makeFakeApi().api);
    expect(q('[data-section="local-only"]')).not.toBeNull();
    expect(q('[data-section="egress-warning"]')).toBeNull();
  });

  it('flips that badge to a WARNING if the sidecar ever reports egress', async () => {
    await mount(makeFakeApi({ status: { ...STATUS, willEgress: true } }).api);
    expect(q('[data-section="egress-warning"]')).not.toBeNull();
    expect(q('[data-section="local-only"]')).toBeNull();
  });

  it('renders a placeholder tile — never a broken img — for a poster-less asset (fact 2)', async () => {
    await mount(makeFakeApi().api);
    const row = q(`[data-asset-id="${REGISTERED.assetId}"]`);
    expect(row).not.toBeNull();
    expect(row?.querySelector('img')).toBeNull();
    expect(row?.querySelector('[data-poster="none"]')?.textContent).toContain(NO_POSTER_LABEL);
  });

  it('shows an unknown duration for a scanned clip rather than inventing 0s (fact 1)', async () => {
    await mount(makeFakeApi().api);
    expect(
      q(`[data-asset-id="${SCANNED.assetId}"] [data-field="duration"]`)?.textContent,
    ).toContain('—');
  });

  it('surfaces the missing list LOUDLY in its own section (fact 3)', async () => {
    await mount(makeFakeApi().api);
    const missing = q('[data-section="missing"]');
    expect(missing).not.toBeNull();
    expect(missing?.textContent).toContain('gone.png');
    // and a vanished row is NOT in the indexable grid
    expect(q(`[data-asset-id="${VANISHED.assetId}"]`)).toBeNull();
  });

  it('unregisters a missing asset and re-reads the one list', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    await act(async () => {
      (
        container.querySelector(
          `[data-missing-id="${VANISHED.assetId}"] [data-action="unregister-missing"]`,
        ) as HTMLButtonElement
      ).click();
      await Promise.resolve();
    });
    await flush();
    expect(fake.calls.find((c) => c.method === 'broll.removeAsset')?.params).toEqual({
      id: VANISHED.assetId,
    });
    expect(fake.calls.filter((c) => c.method === 'broll.assets')).toHaveLength(2);
  });

  it('registers a new asset by path with an optional title, then refreshes', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    pick('[data-input="add-path"]', ' D:/pictures/hero dog.png ');
    pick('[data-input="add-title"]', ' Hero dog ');
    await click('add');
    expect(fake.calls.find((c) => c.method === 'broll.addAsset')?.params).toEqual({
      path: 'D:/pictures/hero dog.png',
      title: 'Hero dog',
    });
    expect(fake.calls.filter((c) => c.method === 'broll.assets')).toHaveLength(2);
  });

  it('OMITS title entirely when the field is blank (no empty-string title)', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    pick('[data-input="add-path"]', 'D:/pictures/hero dog.png');
    await click('add');
    expect(fake.calls.find((c) => c.method === 'broll.addAsset')?.params).toEqual({
      path: 'D:/pictures/hero dog.png',
    });
  });

  it('keeps the register control shut until a non-blank path exists', async () => {
    await mount(makeFakeApi().api);
    expect(btn('add').disabled).toBe(true);
    pick('[data-input="add-path"]', '   ');
    expect(btn('add').disabled).toBe(true);
    pick('[data-input="add-path"]', 'D:/x.png');
    expect(btn('add').disabled).toBe(false);
  });

  // The registry door refuses three real cases (missing path, a DIRECTORY with a
  // media extension, a non-b-roll extension) and each is INVALID_PARAMS, i.e. loud.
  // Two properties are pinned together because the second is what makes the first
  // usable: the message is shown, AND the typed path survives so the user can
  // correct it rather than retype it. `withBusy` swallows the rejection, so an
  // earlier draft that cleared the field in a `.then()` chained onto it wiped the
  // path on the refusal path too — this case is the red-proof for that fix.
  it('surfaces the registry-door refusal AND keeps the typed path for correction', async () => {
    const fake = makeFakeApi({
      addError: new Error('not a file (a directory cannot be a b-roll asset): D:/album.png'),
    });
    await mount(fake.api);
    pick('[data-input="add-path"]', 'D:/album.png');
    pick('[data-input="add-title"]', 'Album');
    await click('add');
    expect(q('.error')?.textContent).toContain('not a file');
    expect((q('[data-input="add-path"]') as HTMLInputElement).value).toBe('D:/album.png');
    expect((q('[data-input="add-title"]') as HTMLInputElement).value).toBe('Album');
  });

  it('clears the add fields ONLY after a successful registration', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    pick('[data-input="add-path"]', 'D:/pictures/hero dog.png');
    pick('[data-input="add-title"]', 'Hero dog');
    await click('add');
    expect((q('[data-input="add-path"]') as HTMLInputElement).value).toBe('');
    expect((q('[data-input="add-title"]') as HTMLInputElement).value).toBe('');
  });

  it('offers unregister on a REGISTERED row only — a scanned file is not ours to drop', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    expect(
      container.querySelector(`[data-asset-id="${SCANNED.assetId}"] [data-action="unregister"]`),
    ).toBeNull();
    await act(async () => {
      (
        container.querySelector(
          `[data-asset-id="${REGISTERED.assetId}"] [data-action="unregister"]`,
        ) as HTMLButtonElement
      ).click();
      await Promise.resolve();
    });
    await flush();
    expect(fake.calls.find((c) => c.method === 'broll.removeAsset')?.params).toEqual({
      id: REGISTERED.assetId,
    });
  });

  it('surfaces a failed first read rather than showing an empty library', async () => {
    await mount(makeFakeApi({ assetsError: new Error('library.json is corrupt') }).api);
    expect(q('.error')?.textContent).toContain('library.json is corrupt');
  });

  it('indexes the library, threading the force flag, then re-reads status', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    toggle('[data-input="force"]');
    await act(async () => {
      btn('index').click();
    });
    await flush();
    await act(async () => {
      fake.fireDone({ jobId: 'job-b', result: { assetCount: 2, embedded: 2 } });
      await Promise.resolve();
    });
    await flush();
    expect(fake.calls.find((c) => c.method === 'broll.index')?.params).toEqual({ force: true });
    expect(fake.calls.filter((c) => c.method === 'broll.status')).toHaveLength(2);
  });

  it('still refreshes when the index answer carries no jobId', async () => {
    const fake = makeFakeApi({ jobless: true });
    await mount(fake.api);
    await click('index');
    expect(fake.calls.filter((c) => c.method === 'broll.status')).toHaveLength(2);
  });

  it('surfaces an index failure', async () => {
    const fake = makeFakeApi({ indexError: new Error('no local image backbone is wired') });
    await mount(fake.api);
    await click('index');
    expect(q('.error')?.textContent).toContain('no local image backbone');
  });

  // THE THRESHOLD DECISION (option a). `broll_plan.DEFAULT_MIN_SIMILARITY = 0.22`
  // is documented in-module as an UNCALIBRATED placeholder. The panel therefore
  // SENDS an explicit threshold on every call, so what the slider says is what the
  // planner uses — the sidecar default is never the silent authority.
  it('sends an EXPLICIT threshold, coverage and layout — never relies on the guess', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    await act(async () => {
      btn('suggest').click();
    });
    await flush();
    expect(fake.calls.find((c) => c.method === 'broll.suggest')?.params).toEqual({
      videoId: 'v1',
      threshold: DEFAULT_BROLL_THRESHOLD,
      maxCoveragePct: DEFAULT_BROLL_MAX_COVERAGE_PCT,
      layout: BROLL_LAYOUTS[0],
    });
  });

  it('the slider moves the threshold that is actually sent', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    pick('[data-input="threshold"]', '0.45');
    pick('[data-input="coverage"]', '25');
    choose('[data-input="layout"]', 'pip');
    await act(async () => {
      btn('suggest').click();
    });
    await flush();
    expect(fake.calls.find((c) => c.method === 'broll.suggest')?.params).toEqual({
      videoId: 'v1',
      threshold: 0.45,
      maxCoveragePct: 25,
      layout: 'pip',
    });
    expect(q('.broll-threshold-value')?.textContent).toContain('0.45');
  });

  it('presents the threshold as adjustable and UNCALIBRATED, naming the experiment', async () => {
    await mount(makeFakeApi().api);
    const copy = q('[data-section="threshold-disclosure"]')?.textContent ?? '';
    expect(copy).toBe(THRESHOLD_IS_UNCALIBRATED);
    // REFUTED: this line used to read `toContain('0.22')` — a hardcoded literal
    // checking a hardcoded literal, which stale copy satisfies. It now checks the
    // copy against the CONSTANT, and `brollClient.conformance.test.ts` checks the
    // copy against the sidecar's own value, so the §11.2 calibration cannot leave
    // the panel telling the user a number it no longer seeds.
    expect(copy).toContain(String(DEFAULT_BROLL_THRESHOLD));
    // The FULL relative path, not a bare basename: the disclosure sends a user to
    // the calibration experiment, and a bare filename is not a place they can go.
    expect(copy).toContain('docs/plans/v1.5/flagship-auto-broll.md');
    // per-MODEL, the second warning in the sidecar docstring
    expect(copy).toContain('backbone');
  });

  it('renders every suggestion with its score, its reason and its window', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    await suggestWith(fake, { insertions: [INSERTION_A, INSERTION_B], reason: 'matched' });
    const rows = container.querySelectorAll('[data-insertion]');
    expect(rows).toHaveLength(2);
    expect(rows[0].querySelector('[data-field="score"]')?.textContent).toContain('0.61');
    expect(rows[0].querySelector('[data-field="reason"]')?.textContent).toContain(
      'the dog ran off',
    );
    expect(rows[0].querySelector('[data-field="window"]')?.textContent).toBe(
      insertionWindowLabel(INSERTION_A),
    );
  });

  it('treats "no confident match" as a RESULT, not an error', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    await suggestWith(fake, { insertions: [], reason: BROLL_REASON_NO_MATCH });
    expect(q('[data-section="no-match"]')).not.toBeNull();
    expect(q('.error')).toBeNull();
    expect(container.querySelectorAll('[data-insertion]')).toHaveLength(0);
  });

  // The rendered half of the refuted-copy fix. `emptyPlanExplanation` is unit-tested
  // above; this pins that the PANEL shows it, with the user's own dials in it, and
  // still quotes the engine's reason verbatim rather than paraphrasing it.
  it('the empty-plan copy blames no single cause and carries the coverage cap the user set', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    pick('[data-input="coverage"]', '25');
    await suggestWith(fake, { insertions: [], reason: BROLL_REASON_NO_MATCH });
    const copy = q('[data-section="no-match"]')?.textContent ?? '';
    expect(copy).not.toContain('scored at or above');
    expect(copy).toContain(emptyPlanExplanation(DEFAULT_BROLL_THRESHOLD, 25));
    expect(copy).toContain('coverage cap of 25%');
    expect(copy).toContain(BROLL_REASON_NO_MATCH);
  });

  // The explanation must quote the dials the RETURNED plan ran with, not whatever
  // the controls happen to say now. Reading live state here would reintroduce the
  // very defect the copy exists to avoid — stating a number that was not measured.
  it('quotes the dials the plan RAN with, not the ones the user moved to afterwards', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    pick('[data-input="coverage"]', '25');
    pick('[data-input="threshold"]', '0.35');
    await suggestWith(fake, { insertions: [], reason: BROLL_REASON_NO_MATCH });
    expect(q('[data-section="no-match"]')?.textContent).toContain('coverage cap of 25%');

    // the user now drags both dials WITHOUT re-running
    pick('[data-input="coverage"]', '60');
    pick('[data-input="threshold"]', '0.80');
    const copy = q('[data-section="no-match"]')?.textContent ?? '';
    expect(copy).toContain('coverage cap of 25%');
    expect(copy).toContain('0.35');
    expect(copy).not.toContain('coverage cap of 60%');
    expect(copy).not.toContain('0.80');
  });

  it('a suggest answer with no jobId leaves an honest empty plan', async () => {
    const fake = makeFakeApi({ jobless: true });
    await mount(fake.api);
    await click('suggest');
    expect(q('[data-section="no-match"]')).not.toBeNull();
    expect(q('.error')).toBeNull();
  });

  it('surfaces a suggest failure (e.g. no transcript yet)', async () => {
    const fake = makeFakeApi({
      suggestError: new Error('v1 has no transcript yet; run transcribe.start first'),
    });
    await mount(fake.api);
    await click('suggest');
    expect(q('.error')?.textContent).toContain('no transcript yet');
  });

  it('applies ONLY the accepted insertions (review-first, keyed by position — fact 5)', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    await suggestWith(fake, { insertions: [INSERTION_A, INSERTION_B], reason: 'matched' });
    toggle('[data-insertion="1"] [data-input="accept"]');
    await act(async () => {
      btn('apply').click();
    });
    await flush();
    expect(fake.calls.find((c) => c.method === 'broll.apply')?.params).toEqual({
      videoId: 'v1',
      insertions: [INSERTION_A],
    });
  });

  it('cannot apply an empty plan (the sidecar rejects it; the button never sends it)', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    await suggestWith(fake, { insertions: [INSERTION_A], reason: 'matched' });
    expect(btn('apply').disabled).toBe(false);
    toggle('[data-insertion="0"] [data-input="accept"]');
    expect(btn('apply').disabled).toBe(true);
  });

  it('reports the flat file apply produced, and says it is one-way BEFORE the click', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    // The disclosure is present as soon as an apply is possible, not after.
    await suggestWith(fake, { insertions: [INSERTION_A], reason: 'matched' });
    const notice = q('[data-section="one-way"]');
    expect(notice?.textContent).toBe(APPLY_IS_ONE_WAY);
    expect(notice?.compareDocumentPosition(btn('apply'))).toBe(Node.DOCUMENT_POSITION_FOLLOWING);

    await act(async () => {
      btn('apply').click();
    });
    await flush();
    await act(async () => {
      fake.fireDone({ jobId: 'job-b', result: { path: 'C:/out/talk.broll.mp4', inserted: 1 } });
      await Promise.resolve();
    });
    await flush();
    expect(q('[data-section="result"]')?.textContent).toContain('talk.broll.mp4');
  });

  it('streams progress for its own job and ignores another', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    await act(async () => {
      btn('suggest').click();
    });
    await flush();
    await act(async () => {
      fake.fireProgress({ jobId: 'job-b', pct: 42, message: 'matching 12 segments' });
      await Promise.resolve();
    });
    expect(q('.progress-pct')?.textContent).toContain('42');
    expect(q('.progress-message')?.textContent).toContain('matching 12 segments');
    await act(async () => {
      fake.fireProgress({ jobId: 'someone-else', pct: 99, message: 'other' });
      await Promise.resolve();
    });
    expect(q('.progress-pct')?.textContent).not.toContain('99');
  });

  it('cancels the running job, and a failed cancel is not a panel error', async () => {
    const fake = makeFakeApi({ cancelError: new Error('already finished') });
    await mount(fake.api);
    await act(async () => {
      btn('suggest').click();
    });
    await flush();
    await act(async () => {
      btn('cancel').click();
      await Promise.resolve();
    });
    await flush();
    expect(fake.calls.find((c) => c.method === 'job.cancel')?.params).toEqual({ jobId: 'job-b' });
    expect(q('.error')).toBeNull();
  });

  // A PLAN BELONGS TO ONE VIDEO. `broll.apply` sends the CURRENT videoId with
  // whatever insertions are on screen, so a plan left over from the previous video
  // would composite video A's windows and assets onto video B.
  it('clears a stale plan when a different video is opened in place', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    await suggestWith(fake, { insertions: [INSERTION_A], reason: 'matched' });
    expect(container.querySelectorAll('[data-insertion]')).toHaveLength(1);
    await rerender(fake.api, 'v2');
    expect(container.querySelectorAll('[data-insertion]')).toHaveLength(0);
    expect(q('[data-section="review"]')).toBeNull();
  });

  it('discards a DEFERRED suggest whose video was switched away mid-flight', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    await act(async () => {
      btn('suggest').click();
    });
    await flush();
    // the user moves on while the job is still running…
    await rerender(fake.api, 'v2');
    await act(async () => {
      fake.fireDone({ jobId: 'job-b', result: { insertions: [INSERTION_A], reason: 'matched' } });
      await Promise.resolve();
    });
    await flush();
    // …so video v1's plan must NOT appear under video v2.
    expect(container.querySelectorAll('[data-insertion]')).toHaveLength(0);
  });

  // THE PREREQUISITES. `broll_ops.suggest`'s job body runs `require_model` first
  // (broll_ops.py:403) and then raises "<id> has no transcript yet; run
  // transcribe.start first" (:408), so on a freshly imported video the advertised
  // click path ends in an ERROR, discovered one failed click at a time. The panel's
  // only previous mention of a transcript was inside the EGRESS badge, which is a
  // different statement. Diarize.tsx:138, caption/CaptionInspector.tsx:47 and
  // TranscriptEditor.tsx:221 all say it up front; so does this now.
  it('states BOTH prerequisites BEFORE the button that hits them', async () => {
    await mount(makeFakeApi().api);
    const prereq = q('[data-section="prerequisites"]');
    expect(prereq?.textContent).toBe(BROLL_NEEDS_TRANSCRIPT);
    expect(prereq?.textContent).toContain('transcribe');
    expect(prereq?.textContent).toContain('index your library');
    // BEFORE, not after: document order decides whether it is a warning or a
    // post-mortem. (`compareDocumentPosition` is the same check the one-way
    // disclosure uses against Apply.)
    expect(prereq?.compareDocumentPosition(btn('suggest'))).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
  });

  // `min`/`max` on a number input constrain VALIDITY, not the value React reads:
  // an emptied field reports '', `Number('')` is 0, and the sidecar's `_opt_float`
  // passes 0 through, so `budget_sec` becomes 0 and `place` rejects every candidate
  // — the feature dies silently while the panel blames the threshold.
  it('refuses to send an unusable coverage cap rather than silently sending 0', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    expect(btn('suggest').disabled).toBe(false);
    expect(q('[data-section="coverage-invalid"]')).toBeNull();

    pick('[data-input="coverage"]', '');
    expect(btn('suggest').disabled).toBe(true);
    expect(q('[data-section="coverage-invalid"]')?.textContent).toContain('between 1 and 100');
    // and the wire stayed clean — no `maxCoveragePct: 0` was ever sent
    expect(fake.calls.filter((c) => c.method === BROLL_METHODS.suggest)).toHaveLength(0);

    pick('[data-input="coverage"]', '25');
    expect(btn('suggest').disabled).toBe(false);
    expect(q('[data-section="coverage-invalid"]')).toBeNull();
  });

  it('names what is still missing so the copy cannot imply BR2 or posters shipped', async () => {
    await mount(makeFakeApi().api);
    const limits = q('[data-section="limits"]')?.textContent ?? '';
    expect(limits).toContain('size and modified time');
    expect(limits).toContain(NO_POSTER_LABEL.toLowerCase());
  });

  it('renders a real poster when one ever exists, instead of the placeholder', async () => {
    const withPoster: BrollAsset = { ...REGISTERED, thumbnailPath: 'D:/th/dog.jpg' };
    await mount(makeFakeApi({ assets: { assets: [withPoster], missing: [] } }).api);
    const row = q(`[data-asset-id="${REGISTERED.assetId}"]`);
    // The mstream URL, not the raw path — the CSP forbids the latter outright.
    expect(row?.querySelector('img')?.getAttribute('src')).toBe(
      `mstream://media/${encodeURIComponent('thumb:D:/th/dog.jpg')}`,
    );
    expect(row?.querySelector('[data-poster="none"]')).toBeNull();
  });

  // …and the day a poster path does NOT resolve (main.ts:1465 serves `thumb:` ids
  // ONLY from DATA_ROOT/thumbnails, and no b-roll poster writer exists yet to put
  // them there), the tile must degrade to the readable placeholder rather than a
  // permanently broken image icon. The `views/LibraryCard.tsx` pattern.
  it('falls back to the placeholder when a poster fails to load', async () => {
    const withPoster: BrollAsset = { ...REGISTERED, thumbnailPath: 'D:/th/dog.jpg' };
    await mount(makeFakeApi({ assets: { assets: [withPoster], missing: [] } }).api);
    const img = q(`[data-asset-id="${REGISTERED.assetId}"] img`) as HTMLImageElement;
    expect(img).not.toBeNull();
    await act(async () => {
      img.dispatchEvent(new Event('error'));
    });
    expect(q(`[data-asset-id="${REGISTERED.assetId}"] img`)).toBeNull();
    expect(
      q(`[data-asset-id="${REGISTERED.assetId}"] [data-poster="none"]`)?.textContent,
    ).toContain(NO_POSTER_LABEL);
  });

  // The un-indexed first-run state: every number the snapshot shows is ABSENT, and
  // the panel must say so rather than print zeros that look like measurements.
  it('reads a bare status payload as "not indexed yet", never as zeros', async () => {
    await mount(makeFakeApi({ status: { indexed: false } }).api);
    expect(q('[data-field="indexed"]')?.textContent).toBe('not yet');
    expect(q('[data-field="stale"]')?.textContent).toBe('none');
    expect(q('[data-field="model"]')?.textContent).toBe('none');
  });

  // …but a payload carrying NOTHING is not a snapshot at all, and printing
  // "In library 0" off it would be a measurement the panel never made. REFUTED
  // behaviour, now pinned at the rendered layer as well as the parser.
  it('renders NO status block at all for a `{}` payload — no invented zeros', async () => {
    await mount(makeFakeApi({ status: {} }).api);
    expect(q('[data-section="status"]')).toBeNull();
    expect(q('[data-field="libraryCount"]')).toBeNull();
    // control: the same mount DOES paint the rest of the panel, so the null above
    // is the status guard firing and not a failed render.
    expect(q('[data-section="threshold-disclosure"]')).not.toBeNull();
  });

  it('treats a job.done with NO result as the honest empty plan', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    await act(async () => {
      btn('suggest').click();
    });
    await flush();
    await act(async () => {
      fake.fireDone({ jobId: 'job-b' });
      await Promise.resolve();
    });
    await flush();
    expect(q('[data-section="no-match"]')).not.toBeNull();
    expect(q('.error')).toBeNull();
  });

  it('a successful cancel reports back without becoming an error', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    await act(async () => {
      btn('suggest').click();
    });
    await flush();
    await act(async () => {
      btn('cancel').click();
      await Promise.resolve();
    });
    expect(q('.progress-message')?.textContent).toContain('Cancelling');
    expect(q('.error')).toBeNull();
  });

  it('surfaces a NON-Error rejection as text rather than "[object Object]"', async () => {
    const api = {
      rpc: vi.fn(async (method: string) => {
        if (method === 'broll.assets') throw 'sidecar pipe closed';
        return {};
      }),
      onProgress: () => () => {},
      onJobDone: () => () => {},
    } as unknown as MediaStudioApi;
    await mount(api);
    expect(q('.error')?.textContent).toContain('sidecar pipe closed');
  });

  // The `api` prop exists only for these tests; the SHIPPED path reads the
  // preload-injected bridge through getApi(), so that default has to be exercised
  // or the packaged panel would be running an untested line.
  it('falls back to the preload bridge when no api prop is injected', async () => {
    const rpc = vi.fn(async () => ({}));
    (globalThis as { api?: unknown }).api = {
      rpc,
      onProgress: () => () => {},
      onJobDone: () => () => {},
    };
    try {
      await act(async () => {
        root.render(<BrollPanel videoId="v1" />);
      });
      await flush();
      expect(rpc).toHaveBeenCalledWith('broll.assets');
    } finally {
      delete (globalThis as { api?: unknown }).api;
    }
  });
});
