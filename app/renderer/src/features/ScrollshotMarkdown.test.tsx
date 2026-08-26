// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import ScrollshotMarkdown, {
  describeScrollshotVerdict,
  parseScrollshotResult,
  resultNeedsReview,
  type ScrollshotExportResult,
} from './ScrollshotMarkdown';
import type { DoneEvent, MediaStudioApi, ProgressEvent } from './_api';

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

interface FakeApi {
  api: MediaStudioApi;
  calls: Array<{ method: string; params?: Record<string, unknown> }>;
  fireProgress: (event: ProgressEvent) => void;
  fireDone: (event: DoneEvent) => void;
  counts: () => { progress: number; done: number };
}

function makeFakeApi(opts: { observeDone?: boolean } = {}): FakeApi {
  const observeDone = opts.observeDone ?? true;
  const calls: FakeApi['calls'] = [];
  let progressCbs: Array<(event: ProgressEvent) => void> = [];
  let doneCbs: Array<(event: DoneEvent) => void> = [];
  const api: MediaStudioApi = {
    rpc: vi.fn(async <T,>(method: string, params?: Record<string, unknown>) => {
      calls.push({ method, params });
      if (method === 'scrollshot.exportMarkdown') {
        return { jobId: 'job-scroll', kind: 'scrollshot.exportMarkdown' } as T;
      }
      return {} as T;
    }) as MediaStudioApi['rpc'],
    onProgress: (cb) => {
      progressCbs.push(cb);
      return () => {
        progressCbs = progressCbs.filter((entry) => entry !== cb);
      };
    },
    ...(observeDone
      ? {
          onJobDone: (cb: (event: DoneEvent) => void) => {
            doneCbs.push(cb);
            return () => {
              doneCbs = doneCbs.filter((entry) => entry !== cb);
            };
          },
        }
      : {}),
  };
  return {
    api,
    calls,
    fireProgress: (event) => progressCbs.slice().forEach((cb) => cb(event)),
    fireDone: (event) => doneCbs.slice().forEach((cb) => cb(event)),
    counts: () => ({ progress: progressCbs.length, done: doneCbs.length }),
  };
}

const canonicalResult: ScrollshotExportResult = {
  schemaVersion: '2',
  runId: 'run-1',
  verdict: 'FULL_DOCUMENT_COMPLETE',
  markdownPath: '/out/scrollshot.md',
  panoramaPaths: ['/out/pano-a.png', '/out/pano-b.png'],
  manifestPath: '/out/manifest.json',
  reviewRequired: false,
  warnings: [],
};

describe('parseScrollshotResult', () => {
  it('accepts the canonical contract', () => {
    expect(parseScrollshotResult(canonicalResult)).toEqual(canonicalResult);
  });

  it('accepts the legacy contract only when it can be normalized safely', () => {
    expect(
      parseScrollshotResult({
        bundleId: 'bundle-1',
        manifestPath: '/out/manifest.json',
        markdownPath: '/out/scrollshot.md',
        imagePath: '/out/stitched.png',
        coverageVerdict: 'complete',
      }),
    ).toEqual({
      schemaVersion: 'legacy',
      runId: 'bundle-1',
      verdict: 'FULL_DOCUMENT_COMPLETE',
      markdownPath: '/out/scrollshot.md',
      panoramaPaths: ['/out/stitched.png'],
      manifestPath: '/out/manifest.json',
      reviewRequired: false,
        warnings: [],
      });
  });

  it('normalizes the legacy recorded-span verdict spelling too', () => {
    expect(
      parseScrollshotResult({
        bundleId: 'bundle-2',
        manifestPath: '/out/manifest.json',
        markdownPath: '/out/scrollshot.md',
        coverageVerdict: 'recorded_span_complete',
      }),
    )?.toMatchObject({
      runId: 'bundle-2',
      schemaVersion: 'legacy',
      verdict: 'RECORDED_SPAN_COMPLETE',
    });
  });

  it('normalizes the legacy incomplete verdict spelling too', () => {
    expect(
      parseScrollshotResult({
        bundleId: 'bundle-3',
        manifestPath: '/out/manifest.json',
        markdownPath: '/out/scrollshot.md',
        coverageVerdict: 'incomplete',
      }),
    )?.toMatchObject({
      runId: 'bundle-3',
      schemaVersion: 'legacy',
      verdict: 'INCOMPLETE',
    });
  });

  it('rejects malformed verdicts, paths, and warning arrays', () => {
    expect(parseScrollshotResult({ ...canonicalResult, verdict: 'BROKEN' })).toBeNull();
    expect(parseScrollshotResult({ ...canonicalResult, markdownPath: 4 })).toBeNull();
    expect(parseScrollshotResult({ ...canonicalResult, manifestPath: false })).toBeNull();
    expect(parseScrollshotResult({ ...canonicalResult, warnings: ['ok', 1] })).toBeNull();
    expect(parseScrollshotResult({ ...canonicalResult, panoramaPaths: 'bad' })).toBeNull();
    expect(parseScrollshotResult({ schemaVersion: '2', verdict: 'INCOMPLETE' })).toBeNull();
    expect(
      parseScrollshotResult({
        verdict: 'FULL_DOCUMENT_COMPLETE',
        markdownPath: '/out/scrollshot.md',
        manifestPath: '/out/manifest.json',
        panoramaPaths: [],
        reviewRequired: false,
        warnings: [],
      }),
    ).toBeNull();
    expect(parseScrollshotResult(null)).toBeNull();
  });
});

describe('verdict helpers', () => {
  it('describes all four explicit verdicts', () => {
    expect(describeScrollshotVerdict('FULL_DOCUMENT_COMPLETE').title).toBe(
      'Full document captured',
    );
    expect(describeScrollshotVerdict('RECORDED_SPAN_COMPLETE').title).toBe(
      'Recorded span captured',
    );
    expect(describeScrollshotVerdict('REVIEW_REQUIRED').title).toBe('Review required');
    expect(describeScrollshotVerdict('INCOMPLETE').title).toBe('Incomplete capture');
  });

  it('flags only the review-bearing results', () => {
    expect(resultNeedsReview(canonicalResult)).toBe(false);
    expect(
      resultNeedsReview({ ...canonicalResult, verdict: 'REVIEW_REQUIRED', reviewRequired: false }),
    ).toBe(true);
    expect(
      resultNeedsReview({ ...canonicalResult, verdict: 'INCOMPLETE', reviewRequired: false }),
    ).toBe(true);
    expect(
      resultNeedsReview({ ...canonicalResult, verdict: 'FULL_DOCUMENT_COMPLETE', reviewRequired: true }),
    ).toBe(true);
  });
});

describe('<ScrollshotMarkdown />', () => {
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
    delete (globalThis as { api?: unknown }).api;
  });

  async function mount(
    api: MediaStudioApi,
    props: { videoId?: string; title?: string } = {},
  ): Promise<void> {
    await act(async () => {
      root.render(
        <ScrollshotMarkdown videoId={props.videoId ?? 'v1'} title={props.title ?? 'Talk'} api={api} />,
      );
    });
  }

  function setValue(selector: string, value: string): void {
    const input = container.querySelector(selector) as HTMLInputElement | HTMLSelectElement;
    const proto =
      input instanceof HTMLSelectElement ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, 'value')!.set!;
    act(() => {
      setter.call(input, value);
      input.dispatchEvent(new Event('input', { bubbles: true }));
      input.dispatchEvent(new Event('change', { bubbles: true }));
    });
  }

  async function click(selector: string): Promise<void> {
    const button = container.querySelector(selector) as HTMLButtonElement;
    expect(button).not.toBeNull();
    await act(async () => {
      button.click();
      await Promise.resolve();
    });
  }

  it('renders the local evidence-preserving contract and seeded defaults', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    expect(container.querySelector('.scrollshot-panel')?.textContent).toContain('fully local');
    expect(container.querySelector('.scrollshot-panel')?.textContent).toContain(
      'evidence-preserving',
    );
    expect(container.querySelector('.scrollshot-panel')?.textContent).toContain(
      'original video stays untouched',
    );
    expect((container.querySelector('[data-input="title"]') as HTMLInputElement).value).toBe(
      'Talk',
    );
    expect((container.querySelector('[data-input="language"]') as HTMLInputElement).value).toBe('');
    expect((container.querySelector('[data-input="assurance"]') as HTMLSelectElement).value).toBe(
      'standard',
    );
  });

  it('sends trimmed optional params, filters progress, and renders a canonical full-document result', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    setValue('[data-input="title"]', '  Recovered scroll  ');
    setValue('[data-input="language"]', '  ro  ');
    setValue('[data-input="assurance"]', 'high');

    await click('button[data-action="export-markdown"]');
    expect(fake.calls.find((call) => call.method === 'scrollshot.exportMarkdown')?.params).toEqual({
      videoId: 'v1',
      title: 'Recovered scroll',
      language: 'ro',
      assurance: 'high',
    });

    await act(async () => {
      fake.fireProgress({ jobId: 'other', pct: 99, message: 'ignore me' });
      fake.fireProgress({ jobId: 'job-scroll', pct: 45, message: 'Aligning frames' });
    });
    expect(container.querySelector('.progress')?.textContent).toContain('45%');
    expect(container.querySelector('.progress')?.textContent).toContain('Aligning frames');
    expect(container.querySelector('.progress')?.textContent).not.toContain('99%');

    await act(async () => {
      fake.fireDone({ jobId: 'job-scroll', result: canonicalResult });
      await Promise.resolve();
    });

    expect(container.querySelector('[data-section="verdict"]')?.textContent).toContain(
      'Full document captured',
    );
    expect(container.querySelector('[data-field="markdownPath"] code')?.textContent).toBe(
      '/out/scrollshot.md',
    );
    expect(container.querySelector('[data-field="manifestPath"] code')?.textContent).toBe(
      '/out/manifest.json',
    );
    expect(container.querySelectorAll('[data-section="panoramaPaths"] li')).toHaveLength(2);
    expect(container.querySelector('[data-section="review-required"]')).toBeNull();
    expect(container.querySelector('[role="alert"]')).toBeNull();
  });

  it('omits blank optional params and hides an empty progress message', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    setValue('[data-input="title"]', '   ');
    setValue('[data-input="language"]', '   ');

    await click('button[data-action="export-markdown"]');
    expect(fake.calls.find((call) => call.method === 'scrollshot.exportMarkdown')?.params).toEqual({
      videoId: 'v1',
      assurance: 'standard',
    });

    await act(async () => {
      fake.fireProgress({ jobId: 'job-scroll', pct: 12, message: '' });
    });

    expect(container.querySelector('.progress-pct')?.textContent).toContain('12%');
    expect(container.querySelector('.progress-message')).toBeNull();
  });

  it('distinguishes recorded-span output and shows warnings without forcing review by itself', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);

    await click('button[data-action="export-markdown"]');
    await act(async () => {
      fake.fireDone({
        jobId: 'job-scroll',
        result: {
          ...canonicalResult,
          verdict: 'RECORDED_SPAN_COMPLETE',
          panoramaPaths: [],
          warnings: ['Scrollbar drifted once', 'One seam was low confidence'],
        } satisfies ScrollshotExportResult,
      });
      await Promise.resolve();
    });

    expect(container.querySelector('[data-section="verdict"]')?.textContent).toContain(
      'Recorded span captured',
    );
    expect(container.querySelectorAll('[data-section="warnings"] li')).toHaveLength(2);
    expect(container.querySelector('[data-section="review-required"]')).toBeNull();
    expect(container.querySelector('[data-section="panoramaPaths"]')).toBeNull();
  });

  it('shows explicit review-required verdicts and incomplete verdicts as manual-review states', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);

    await click('button[data-action="export-markdown"]');
    await act(async () => {
      fake.fireDone({
        jobId: 'job-scroll',
        result: {
          ...canonicalResult,
          verdict: 'REVIEW_REQUIRED',
          panoramaPaths: [],
          warnings: ['Check the handoff before publishing'],
        } satisfies ScrollshotExportResult,
      });
      await Promise.resolve();
    });

    expect(container.querySelector('[data-section="verdict"]')?.textContent).toContain(
      'Review required',
    );
    expect(container.querySelector('[data-section="review-required"]')).not.toBeNull();

    await click('button[data-action="export-markdown"]');
    await act(async () => {
      fake.fireDone({
        jobId: 'job-scroll',
        result: {
          ...canonicalResult,
          verdict: 'INCOMPLETE',
          reviewRequired: false,
          warnings: ['OCR confidence fell below threshold'],
        } satisfies ScrollshotExportResult,
      });
      await Promise.resolve();
    });

    expect(container.querySelector('[data-section="verdict"]')?.textContent).toContain(
      'Incomplete capture',
    );
    expect(container.querySelector('[data-section="review-required"]')).not.toBeNull();
  });

  it('accepts legacy payloads only when they normalize cleanly', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);

    await click('button[data-action="export-markdown"]');
    await act(async () => {
      fake.fireDone({
        jobId: 'job-scroll',
        result: {
          bundleId: 'legacy-bundle',
          manifestPath: '/out/manifest.json',
          markdownPath: '/out/scrollshot.md',
          imagePath: '/out/stitched.png',
          coverageVerdict: 'review_required',
        },
      });
      await Promise.resolve();
    });

    expect(container.querySelector('[data-field="runId"] code')?.textContent).toContain(
      'legacy-bundle · schema legacy',
    );
    expect(container.querySelector('[data-section="verdict"]')?.textContent).toContain(
      'Review required',
    );
    expect(container.querySelectorAll('[data-section="panoramaPaths"] li')).toHaveLength(1);
  });

  it('fails loudly on malformed or nullish job.done payloads', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);

    await click('button[data-action="export-markdown"]');
    await act(async () => {
      fake.fireDone({ jobId: 'job-scroll', result: undefined });
      await Promise.resolve();
    });
    expect(container.querySelector('[role="alert"]')?.textContent).toContain(
      'unexpected result shape',
    );

    await click('button[data-action="export-markdown"]');
    await act(async () => {
      fake.fireDone({
        jobId: 'job-scroll',
        result: {
          schemaVersion: '2',
          runId: 'bad',
          verdict: 'BROKEN',
          markdownPath: '/out/scrollshot.md',
          panoramaPaths: [],
          manifestPath: '/out/manifest.json',
          reviewRequired: false,
          warnings: [],
        },
      });
      await Promise.resolve();
    });
    expect(container.querySelector('[role="alert"]')?.textContent).toContain(
      'unexpected result shape',
    );
  });

  it('fails loudly when the bridge cannot observe job.done or omits a job id', async () => {
    const missingDone = makeFakeApi({ observeDone: false });
    await mount(missingDone.api);
    await click('button[data-action="export-markdown"]');
    expect(container.querySelector('[role="alert"]')?.textContent).toContain(
      'cannot observe scrollshot completion results',
    );

    const missingJobId = makeFakeApi();
    (missingJobId.api.rpc as ReturnType<typeof vi.fn>).mockResolvedValueOnce({});
    await mount(missingJobId.api);
    await click('button[data-action="export-markdown"]');
    expect(container.querySelector('[role="alert"]')?.textContent).toContain(
      'did not return a job id',
    );
  });

  it('surfaces both Error.message and String(err) for rpc failures', async () => {
    const fake = makeFakeApi();
    (fake.api.rpc as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error('bridge crashed'));
    await mount(fake.api);
    await click('button[data-action="export-markdown"]');
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('bridge crashed');

    const second = makeFakeApi();
    (second.api.rpc as ReturnType<typeof vi.fn>).mockRejectedValueOnce('engine offline');
    await mount(second.api);
    await click('button[data-action="export-markdown"]');
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('engine offline');
  });

  it('cancels the active job cleanly on JobCancelled and swallows cancel-rpc failures', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);

    await click('button[data-action="export-markdown"]');
    await click('button[data-action="cancel"]');
    expect(fake.calls.find((call) => call.method === 'job.cancel')?.params).toEqual({
      jobId: 'job-scroll',
    });

    await act(async () => {
      fake.fireDone({
        jobId: 'job-scroll',
        result: { error: { message: 'cancelled', type: 'JobCancelled' } },
      });
      await Promise.resolve();
    });

    expect(container.querySelector('[role="alert"]')).toBeNull();
    expect(container.querySelector('[data-section="result"]')).toBeNull();
    expect(
      (container.querySelector('button[data-action="export-markdown"]') as HTMLButtonElement)
        .disabled,
    ).toBe(false);

    const second = makeFakeApi();
    await mount(second.api);
    await click('button[data-action="export-markdown"]');
    (second.api.rpc as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error('already gone'));
    await click('button[data-action="cancel"]');
    expect(container.querySelector('[role="alert"]')).toBeNull();
  });

  it('falls back to globalThis.api and tears down progress/job.done subscriptions on unmount', async () => {
    const fake = makeFakeApi();
    (globalThis as { api?: unknown }).api = fake.api;

    await act(async () => {
      root.render(<ScrollshotMarkdown videoId="v1" title="Talk" />);
    });

    await click('button[data-action="export-markdown"]');
    expect(fake.calls.find((call) => call.method === 'scrollshot.exportMarkdown')?.params).toEqual({
      videoId: 'v1',
      title: 'Talk',
      assurance: 'standard',
    });
    expect(fake.counts()).toEqual({ progress: 1, done: 1 });

    await act(async () => {
      root.unmount();
    });

    expect(fake.counts()).toEqual({ progress: 0, done: 0 });
    await act(async () => {
      fake.fireProgress({ jobId: 'job-scroll', pct: 80, message: 'late' });
      fake.fireDone({ jobId: 'job-scroll', result: canonicalResult });
      await Promise.resolve();
    });
  });

  it('aborts an in-flight wait when the video identity changes', async () => {
    const fake = makeFakeApi();
    const abortSpy = vi.spyOn(AbortController.prototype, 'abort');
    await mount(fake.api, { videoId: 'v1', title: 'Talk' });

    await click('button[data-action="export-markdown"]');
    expect(fake.counts()).toEqual({ progress: 1, done: 1 });

    await act(async () => {
      root.render(<ScrollshotMarkdown videoId="v2" title="Replacement" api={fake.api} />);
    });

    expect(abortSpy).toHaveBeenCalled();
    expect(container.querySelector('button[data-action="cancel"]')).toBeNull();
    expect((container.querySelector('[data-input="title"]') as HTMLInputElement).value).toBe(
      'Replacement',
    );
    abortSpy.mockRestore();
  });
});
