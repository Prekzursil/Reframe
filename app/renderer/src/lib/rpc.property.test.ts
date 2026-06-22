// rpc.property.test.ts — fast-check property tests over the typed `client`
// RPC builders (WU-B test-hardening). The bridge is mocked; we assert the EXACT
// wire call (method string + params object) for arbitrary inputs, so the frozen
// §2 contract holds for every value, not just the hand-picked examples in
// rpc.test.ts.
//
// Append-only: ADDS coverage; touches no source and no existing test. Fixed
// seed + bounded numRuns keep the gate deterministic.

import fc from 'fast-check';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { client, rpc } from './rpc';

fc.configureGlobal({ numRuns: 75, seed: 0x5eed, endOnFailure: true });

// The preload bridge is installed ONCE per test (beforeEach) and torn down in
// afterEach. Each fast-check iteration calls `freshSpy()` to clear the spy's
// recorded calls without re-mutating the shared `globalThis.window` mid-run
// (mutating a global inside an async fast-check loop is racy — keep the window
// stable and only reset the spy's call log).
let rpcSpy: ReturnType<typeof vi.fn>;

function freshSpy(): ReturnType<typeof vi.fn> {
  rpcSpy.mockClear();
  return rpcSpy;
}

beforeEach(() => {
  rpcSpy = vi.fn().mockResolvedValue({});
  (globalThis as { window?: { api?: unknown } }).window = {
    api: { rpc: rpcSpy, onProgress: vi.fn(() => () => {}) },
  };
});

afterEach(() => {
  vi.restoreAllMocks();
});

const idText = fc.string({ minLength: 1, maxLength: 20 });

// ---------------------------------------------------------------------------
// single-arg id-passing wrappers
// ---------------------------------------------------------------------------

describe('client id-passing wrappers (property)', () => {
  it('library.add / remove / thumbnail forward the id under the right key', async () => {
    await fc.assert(
      fc.asyncProperty(idText, async (id) => {
        const spy = freshSpy();
        await client.library.add(id);
        await client.library.remove(id);
        await client.library.thumbnail(id);
        expect(spy).toHaveBeenNthCalledWith(1, 'library.add', { path: id });
        expect(spy).toHaveBeenNthCalledWith(2, 'library.remove', { id });
        expect(spy).toHaveBeenNthCalledWith(3, 'library.thumbnail', { id });
      }),
    );
  });

  it('job.* wrappers forward jobId verbatim', async () => {
    await fc.assert(
      fc.asyncProperty(idText, async (jobId) => {
        const spy = freshSpy();
        await client.job.cancel(jobId);
        await client.job.status(jobId);
        await client.job.retry(jobId);
        await client.job.list();
        expect(spy).toHaveBeenNthCalledWith(1, 'job.cancel', { jobId });
        expect(spy).toHaveBeenNthCalledWith(2, 'job.status', { jobId });
        expect(spy).toHaveBeenNthCalledWith(3, 'job.retry', { jobId });
        expect(spy).toHaveBeenNthCalledWith(4, 'job.list', undefined);
      }),
    );
  });
});

// ---------------------------------------------------------------------------
// optional-arg shaping: omitted optionals must not leak undefined keys that
// change the wire shape the sidecar sees.
// ---------------------------------------------------------------------------

describe('client optional-arg shaping (property)', () => {
  it('transcribe.start only includes language when provided', async () => {
    await fc.assert(
      fc.asyncProperty(idText, fc.option(idText, { nil: undefined }), async (videoId, language) => {
        const spy = freshSpy();
        await client.transcribe.start(videoId, language);
        const [method, params] = spy.mock.calls[0];
        expect(method).toBe('transcribe.start');
        expect(params).toEqual(language ? { videoId, language } : { videoId });
      }),
    );
  });

  it('shorts.list omits videoId when absent', async () => {
    await fc.assert(
      fc.asyncProperty(fc.option(idText, { nil: undefined }), async (videoId) => {
        const spy = freshSpy();
        await client.shorts.list(videoId);
        const [method, params] = spy.mock.calls[0];
        expect(method).toBe('shorts.list');
        expect(params).toEqual(videoId ? { videoId } : {});
      }),
    );
  });

  it('director.apply only includes confirmBudget when provided', async () => {
    await fc.assert(
      fc.asyncProperty(
        idText,
        fc.option(idText, { nil: undefined }),
        async (planId, confirmBudget) => {
          const spy = freshSpy();
          await client.director.apply(planId, confirmBudget);
          const [method, params] = spy.mock.calls[0];
          expect(method).toBe('director.apply');
          expect(params).toEqual(
            confirmBudget === undefined ? { planId } : { planId, confirmBudget },
          );
        },
      ),
    );
  });

  it('index.search always forwards videoId/query/topK', async () => {
    await fc.assert(
      fc.asyncProperty(
        idText,
        idText,
        fc.integer({ min: 1, max: 100 }),
        async (videoId, query, topK) => {
          const spy = freshSpy();
          await client.index.search(videoId, query, topK);
          expect(spy).toHaveBeenCalledWith('index.search', { videoId, query, topK });
        },
      ),
    );
  });
});

// ---------------------------------------------------------------------------
// spread-merge wrappers must preserve the leading positional args + merge opts
// ---------------------------------------------------------------------------

describe('client spread-merge wrappers (property)', () => {
  it('shortmaker.export merges opts after the required ids', async () => {
    await fc.assert(
      fc.asyncProperty(
        idText,
        fc.array(idText, { maxLength: 4 }),
        fc.record(
          {
            audioTrackId: idText,
            captionStyle: idText,
            hookTitle: fc.boolean(),
            removeFillers: fc.boolean(),
          },
          { requiredKeys: [] },
        ),
        async (videoId, candidateIds, opts) => {
          const spy = freshSpy();
          await client.shortmaker.export(videoId, candidateIds, opts);
          expect(spy).toHaveBeenCalledWith('shortmaker.export', {
            videoId,
            candidateIds,
            ...opts,
          });
        },
      ),
    );
  });

  it('providers.setConsent spreads the patch onto the provider', async () => {
    await fc.assert(
      fc.asyncProperty(
        idText,
        fc.record({ text: fc.boolean(), frames: fc.boolean() }, { requiredKeys: [] }),
        async (provider, patch) => {
          const spy = freshSpy();
          await client.providers.setConsent(provider, patch);
          expect(spy).toHaveBeenCalledWith('providers.setConsent', { provider, ...patch });
        },
      ),
    );
  });
});

// ---------------------------------------------------------------------------
// the bare rpc() passthrough
// ---------------------------------------------------------------------------

describe('rpc passthrough (property)', () => {
  it('forwards method + params unchanged', async () => {
    await fc.assert(
      fc.asyncProperty(
        idText,
        fc.dictionary(fc.string({ maxLength: 4 }), fc.integer()),
        async (method, params) => {
          const spy = freshSpy();
          await rpc(method, params);
          expect(spy).toHaveBeenCalledWith(method, params);
        },
      ),
    );
  });
});
