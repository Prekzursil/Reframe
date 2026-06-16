// CandidateList.test.tsx — behavioral tests for the candidate review list/row.
// Mounts CandidateList directly (react-dom/client + act under jsdom) and drives
// every row action callback (select, nudge ×4, reset, approve, discard,
// reinstate) plus the factor-breakdown disclosure and the virality/score chips.

// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import { CandidateList, CandidateRow, NUDGE_STEP } from './CandidateList';
import {
  type Candidate,
  type ReviewItem,
  type ReviewStatus,
  candidateId,
} from './shortMakerLogic';

function cand(over: Partial<Candidate> = {}): Candidate {
  return {
    rank: 1,
    start: 100,
    end: 140,
    durationSec: 40,
    hook: 'A hook',
    why: 'A reason',
    score: 95,
    sourceStart: 100,
    ...over,
  };
}

function item(over: Partial<Candidate> = {}, status: ReviewStatus = 'pending'): ReviewItem {
  const c = cand(over);
  return { id: candidateId(c), original: c, current: c, status };
}

describe('<CandidateList />', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  function spies() {
    return {
      onSelect: vi.fn(),
      onApprove: vi.fn(),
      onDiscard: vi.fn(),
      onReinstate: vi.fn(),
      onNudge: vi.fn(),
      onReset: vi.fn(),
    };
  }

  function mount(items: ReviewItem[], s: ReturnType<typeof spies>, selectedId: string | null = null) {
    act(() => {
      root.render(
        <CandidateList
          items={items}
          selectedId={selectedId}
          onSelect={s.onSelect}
          onApprove={s.onApprove}
          onDiscard={s.onDiscard}
          onReinstate={s.onReinstate}
          onNudge={s.onNudge}
          onReset={s.onReset}
        />,
      );
    });
  }

  it('renders one row per item and marks the selected one', () => {
    const items = [item({ rank: 1, sourceStart: 1 }), item({ rank: 2, sourceStart: 2 })];
    const s = spies();
    mount(items, s, items[1].id);
    const rows = container.querySelectorAll('.sm-candidate');
    expect(rows.length).toBe(2);
    expect(rows[1].classList.contains('sm-selected')).toBe(true);
    expect(rows[1].getAttribute('aria-current')).toBe('true');
    expect(rows[0].getAttribute('aria-current')).toBeNull();
  });

  it('clicking a row selects it', () => {
    const items = [item({ rank: 1, sourceStart: 1 })];
    const s = spies();
    mount(items, s);
    act(() => (container.querySelector('.sm-candidate') as HTMLElement).click());
    expect(s.onSelect).toHaveBeenCalledWith(items[0].id);
  });

  it('the four nudge buttons call onNudge with the right deltas (and stop row-select)', () => {
    const items = [item({ rank: 1, sourceStart: 1 })];
    const s = spies();
    mount(items, s);
    const row = container.querySelector('.sm-candidate')!;
    const click = (label: string) =>
      act(() => (row.querySelector(`[aria-label="${label}"]`) as HTMLButtonElement).click());

    click('Earlier start');
    expect(s.onNudge).toHaveBeenCalledWith(items[0].id, -NUDGE_STEP, 0);
    click('Later start');
    expect(s.onNudge).toHaveBeenCalledWith(items[0].id, NUDGE_STEP, 0);
    click('Earlier end');
    expect(s.onNudge).toHaveBeenCalledWith(items[0].id, 0, -NUDGE_STEP);
    click('Later end');
    expect(s.onNudge).toHaveBeenCalledWith(items[0].id, 0, NUDGE_STEP);
  });

  it('shows a nudged badge + Reset button only when boundaries differ; Reset calls onReset', () => {
    const original = cand({ rank: 1, sourceStart: 1, start: 100, end: 140 });
    const nudged: ReviewItem = {
      id: candidateId(original),
      original,
      current: { ...original, end: 141 },
      status: 'pending',
    };
    const s = spies();
    mount([nudged], s);
    const row = container.querySelector('.sm-candidate')!;
    expect(row.querySelector('.sm-nudged')).toBeTruthy();
    const reset = row.querySelector('[aria-label="Reset boundaries"]') as HTMLButtonElement;
    expect(reset).toBeTruthy();
    act(() => reset.click());
    expect(s.onReset).toHaveBeenCalledWith(nudged.id);
  });

  it('hides the Reset button when not nudged', () => {
    const s = spies();
    mount([item({ rank: 1, sourceStart: 1 })], s);
    expect(container.querySelector('[aria-label="Reset boundaries"]')).toBeNull();
  });

  it('approve/discard/reinstate buttons are shown per status and fire their callbacks', () => {
    const s = spies();
    // pending: approve + discard shown, reinstate hidden.
    mount([item({ rank: 1, sourceStart: 1 }, 'pending')], s);
    let row = container.querySelector('.sm-candidate')!;
    expect(row.querySelector('[aria-label="Approve"]')).toBeTruthy();
    expect(row.querySelector('[aria-label="Discard"]')).toBeTruthy();
    expect(row.querySelector('[aria-label="Reinstate"]')).toBeNull();
    act(() => (row.querySelector('[aria-label="Approve"]') as HTMLButtonElement).click());
    expect(s.onApprove).toHaveBeenCalled();
    act(() => (row.querySelector('[aria-label="Discard"]') as HTMLButtonElement).click());
    expect(s.onDiscard).toHaveBeenCalled();

    // approved: approve hidden, reinstate shown.
    mount([item({ rank: 1, sourceStart: 1 }, 'approved')], s);
    row = container.querySelector('.sm-candidate')!;
    expect(row.querySelector('[aria-label="Approve"]')).toBeNull();
    expect(row.querySelector('[aria-label="Reinstate"]')).toBeTruthy();
    act(() => (row.querySelector('[aria-label="Reinstate"]') as HTMLButtonElement).click());
    expect(s.onReinstate).toHaveBeenCalled();

    // discarded: discard hidden.
    mount([item({ rank: 1, sourceStart: 1 }, 'discarded')], s);
    row = container.querySelector('.sm-candidate')!;
    expect(row.querySelector('[aria-label="Discard"]')).toBeNull();
  });
});

describe('<CandidateRow /> chips + factor disclosure', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  function noop() {
    return {
      onSelect: vi.fn(),
      onApprove: vi.fn(),
      onDiscard: vi.fn(),
      onReinstate: vi.fn(),
      onNudge: vi.fn(),
      onReset: vi.fn(),
    };
  }

  function renderRow(it: ReviewItem) {
    const s = noop();
    act(() => {
      root.render(<CandidateRow item={it} selected={false} {...s} />);
    });
  }

  it('shows the legacy score chip (no virality, no factor toggle) for pre-P3 candidates', () => {
    renderRow(item({ rank: 1, sourceStart: 1, score: 81 }));
    expect(container.querySelector('.sm-score')?.textContent).toBe('81');
    expect(container.querySelector('.sm-virality')).toBeNull();
    expect(container.querySelector('[aria-label="Factor breakdown"]')).toBeNull();
  });

  it('headlines virality, demotes score to a tooltip, and toggles the factor bars', () => {
    const c = cand({
      rank: 1,
      sourceStart: 1,
      score: 95,
      viralityPct: 87,
      factors: { hookStrength: 88, emotionalFlow: 64, perceivedValue: 71, shareability: 90 },
      factorNotes: { hookStrength: 'Opens mid-claim' },
    });
    renderRow({ id: candidateId(c), original: c, current: c, status: 'pending' });

    const virality = container.querySelector('.sm-virality') as HTMLElement;
    expect(virality.textContent).toBe('87%');
    expect(virality.getAttribute('title')).toContain('95');

    const toggle = container.querySelector('[aria-label="Factor breakdown"]') as HTMLButtonElement;
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    expect(container.querySelector('.sm-factors')).toBeNull();

    act(() => toggle.click());
    expect(toggle.getAttribute('aria-expanded')).toBe('true');
    const bars = [...container.querySelectorAll('.sm-factor')];
    expect(bars.map((b) => b.getAttribute('data-value'))).toEqual(['88', '64', '71', '90']);
    expect(bars[0].querySelector('.sm-factor-note')?.textContent).toBe('Opens mid-claim');

    act(() => toggle.click());
    expect(container.querySelector('.sm-factors')).toBeNull();
  });
});
