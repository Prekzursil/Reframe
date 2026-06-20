// repurposeLogic.test.ts — pure-logic coverage for the Repurpose bundle (WU11).

import { describe, it, expect } from 'vitest';

import {
  CAPTION_STYLE_OPTIONS,
  REFRAME_ENGINE_OPTIONS,
  MIN_WINDOW_SEC,
  MAX_WINDOW_SEC,
  clampWindowSec,
  isValidCaptionStyle,
  statusToken,
  isTerminalItem,
  terminalAnnouncement,
  sourceToken,
  aggregateUpdate,
  isIncomplete,
  incompleteBatches,
  remainingCount,
  batchSettled,
  blankPreset,
} from './repurposeLogic';
import type { BatchItemStatus, BatchSummary, ProgressEvent } from '../lib/rpc';

describe('caption-style + engine constraints', () => {
  it('exposes a closed style set including the libass sentinels', () => {
    expect(CAPTION_STYLE_OPTIONS).toContain('tiktok');
    expect(CAPTION_STYLE_OPTIONS).toContain('libass');
    expect(CAPTION_STYLE_OPTIONS).toContain('none');
  });

  it('exposes the three reframe engines', () => {
    expect([...REFRAME_ENGINE_OPTIONS]).toEqual(['auto', 'verthor', 'claudeshorts']);
  });

  it('isValidCaptionStyle gates by the closed set', () => {
    expect(isValidCaptionStyle('hormozi')).toBe(true);
    expect(isValidCaptionStyle('__nope__')).toBe(false);
  });
});

describe('clampWindowSec', () => {
  it('floors below the min', () => {
    expect(clampWindowSec(5)).toBe(MIN_WINDOW_SEC);
  });
  it('caps above the max', () => {
    expect(clampWindowSec(600)).toBe(MAX_WINDOW_SEC);
  });
  it('keeps an in-range value', () => {
    expect(clampWindowSec(42)).toBe(42);
  });
  it('treats NaN as the min', () => {
    expect(clampWindowSec(Number.NaN)).toBe(MIN_WINDOW_SEC);
  });
});

describe('statusToken (text, not color-only)', () => {
  const cases: Array<[BatchItemStatus, string]> = [
    ['done', 'Done'],
    ['error', 'Failed'],
    ['cancelled', 'Cancelled'],
    ['skipped', 'Skipped'],
    ['running', 'Running'],
    ['queued', 'Queued'],
  ];
  it.each(cases)('%s -> %s', (status, token) => {
    expect(statusToken(status)).toBe(token);
  });
});

describe('isTerminalItem', () => {
  it('terminal states are terminal', () => {
    expect(isTerminalItem('done')).toBe(true);
    expect(isTerminalItem('error')).toBe(true);
    expect(isTerminalItem('cancelled')).toBe(true);
    expect(isTerminalItem('skipped')).toBe(true);
  });
  it('transient states are not', () => {
    expect(isTerminalItem('queued')).toBe(false);
    expect(isTerminalItem('running')).toBe(false);
  });
});

describe('terminalAnnouncement (announce on terminal only)', () => {
  it('done is polite', () => {
    expect(terminalAnnouncement('Clip A', { status: 'done' })).toEqual({
      text: 'Clip A — done',
      assertive: false,
    });
  });
  it('error is assertive and carries the reason', () => {
    expect(terminalAnnouncement('Clip A', { status: 'error', error: 'boom' })).toEqual({
      text: 'Clip A — failed: boom',
      assertive: true,
    });
  });
  it('error falls back to a default reason', () => {
    expect(terminalAnnouncement('Clip A', { status: 'error' })?.text).toBe(
      'Clip A — failed: unknown error',
    );
  });
  it('cancelled is polite', () => {
    expect(terminalAnnouncement('Clip A', { status: 'cancelled' })).toEqual({
      text: 'Clip A — cancelled',
      assertive: false,
    });
  });
  it('skipped carries the skipReason', () => {
    expect(
      terminalAnnouncement('Clip A', { status: 'skipped', skipReason: 'would egress' }),
    ).toEqual({ text: 'Clip A — skipped: would egress', assertive: false });
  });
  it('skipped falls back to a default reason', () => {
    expect(terminalAnnouncement('Clip A', { status: 'skipped' })?.text).toBe(
      'Clip A — skipped: unknown reason',
    );
  });
  it('non-terminal transitions are silent', () => {
    expect(terminalAnnouncement('Clip A', { status: 'queued' })).toBeNull();
    expect(terminalAnnouncement('Clip A', { status: 'running' })).toBeNull();
  });
});

describe('sourceToken / aggregateUpdate (debounce per-pct chatter)', () => {
  it('extracts the source k/N token', () => {
    expect(sourceToken('source 4/30 · Ep4 · step 2/5 · Reframe')).toBe('source 4/30');
  });
  it('returns empty when no token present', () => {
    expect(sourceToken('starting…')).toBe('');
  });
  function ev(message: string): ProgressEvent {
    return { jobId: 'j', pct: 10, message };
  }
  it('re-announces when the source token changes', () => {
    expect(aggregateUpdate('source 1/30 · A · step 1/2', ev('source 2/30 · B · step 1/2'))).toBe(
      'source 2/30 · B · step 1/2',
    );
  });
  it('suppresses when only pct/step changes within the same source', () => {
    expect(
      aggregateUpdate('source 1/30 · A · step 1/2', ev('source 1/30 · A · step 2/2')),
    ).toBeNull();
  });
});

describe('resume-surface predicates (§7.2)', () => {
  function summary(status: BatchSummary['status'], over: Partial<BatchSummary> = {}): BatchSummary {
    return {
      id: 'b',
      name: 'B',
      templateId: 't',
      status,
      createdAt: 1,
      counts: { total: 3, done: 1, error: 0, skipped: 0, queued: 2, running: 0, cancelled: 0 },
      ...over,
    };
  }
  it('classifies incomplete statuses', () => {
    expect(isIncomplete('queued')).toBe(true);
    expect(isIncomplete('running')).toBe(true);
    expect(isIncomplete('partial')).toBe(true);
    expect(isIncomplete('done')).toBe(false);
    expect(isIncomplete('cancelled')).toBe(false);
    expect(isIncomplete('error')).toBe(false);
  });
  it('filters + sorts incomplete batches newest-first', () => {
    const list = [
      summary('done', { id: 'd', createdAt: 10 }),
      summary('partial', { id: 'p', createdAt: 5 }),
      summary('running', { id: 'r', createdAt: 8 }),
    ];
    expect(incompleteBatches(list).map((b) => b.id)).toEqual(['r', 'p']);
  });
  it('computes remaining (not done, not skipped)', () => {
    expect(
      remainingCount({
        total: 30,
        done: 10,
        error: 1,
        skipped: 4,
        queued: 15,
        running: 0,
        cancelled: 0,
      }),
    ).toBe(16);
  });
});

describe('batchSettled', () => {
  it('true when all items terminal', () => {
    expect(
      batchSettled({
        items: [
          { videoId: 'a', status: 'done' },
          { videoId: 'b', status: 'skipped' },
        ],
      }),
    ).toBe(true);
  });
  it('false when any item pending', () => {
    expect(
      batchSettled({
        items: [
          { videoId: 'a', status: 'done' },
          { videoId: 'b', status: 'queued' },
        ],
      }),
    ).toBe(false);
  });
});

describe('blankPreset', () => {
  it('is valid-by-construction', () => {
    const p = blankPreset();
    expect(p.minSec).toBe(MIN_WINDOW_SEC);
    expect(p.maxSec).toBe(MAX_WINDOW_SEC);
    expect(isValidCaptionStyle(p.captionStyle)).toBe(true);
    expect(REFRAME_ENGINE_OPTIONS).toContain(p.reframeEngine);
  });
});
