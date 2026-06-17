// UsageBar.test.tsx — WU-usage-ui renderer tests at vitest 100%.
//
// Covers: REQ + TOKEN mixed pool -> >= 2 SEPARATE grouped bars (no cross-unit
// sum); each color band + its non-color glyph + numeric label; superpowered
// fires at exactly >= 3 same-unit healthy keys across DISTINCT providers and NOT
// at the borderline (2 keys, or 3 keys across 2 providers); reduced-motion
// disables animation; stale desaturation + "last checked Xm ago".

// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import {
  UsageBars,
  compactCount,
  groupByUnit,
  isSuperpowered,
  numericLabel,
  prefersReducedMotion,
  remainingFraction,
  staleAgeLabel,
  unitLabel,
  usageZone,
  zoneGlyph,
  SUPERPOWERED_MIN,
} from './UsageBar';
import type { UsageRow } from '../lib/rpc';

let container: HTMLDivElement;
let root: Root;

function setReducedMotion(reduced: boolean): void {
  // jsdom has no matchMedia by default; install a controllable stub.
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: reduced,
    media: query,
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }));
}

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  setReducedMotion(false);
});

afterEach(async () => {
  await act(async () => {
    root.unmount();
  });
  container.remove();
  vi.restoreAllMocks();
});

async function render(node: React.ReactElement): Promise<void> {
  await act(async () => {
    root.render(node);
  });
}

function row(p: Partial<UsageRow> & Pick<UsageRow, 'provider' | 'unit'>): UsageRow {
  return {
    key: '…WXYZ',
    used: 0,
    max: 1000,
    resetAt: null,
    stale: false,
    lastCheckedAt: null,
    ...p,
  };
}

// --------------------------------------------------------------------------- //
// pure helpers
// --------------------------------------------------------------------------- //
describe('usage helpers', () => {
  it('remainingFraction: known max', () => {
    expect(remainingFraction(row({ provider: 'A', unit: 'req', used: 250, max: 1000 }))).toBeCloseTo(
      0.75,
    );
  });

  it('remainingFraction: unknown/zero max reads as fully healthy', () => {
    expect(remainingFraction(row({ provider: 'A', unit: 'req', max: null }))).toBe(1);
    expect(remainingFraction(row({ provider: 'A', unit: 'req', max: 0 }))).toBe(1);
  });

  it('remainingFraction: clamps used over max to zero remaining', () => {
    expect(remainingFraction(row({ provider: 'A', unit: 'req', used: 1500, max: 1000 }))).toBe(0);
  });

  it('usageZone thresholds (green >= 60 / yellow 30-60 / red < 30)', () => {
    expect(usageZone(0.6)).toBe('healthy');
    expect(usageZone(0.45)).toBe('warn');
    expect(usageZone(0.3)).toBe('warn');
    expect(usageZone(0.29)).toBe('critical');
  });

  it('zoneGlyph: a distinct non-color glyph per band', () => {
    expect(zoneGlyph('healthy')).toBe('●');
    expect(zoneGlyph('warn')).toBe('◐');
    expect(zoneGlyph('critical')).toBe('○');
  });

  it('unitLabel maps token->tok, else req', () => {
    expect(unitLabel('token')).toBe('tok');
    expect(unitLabel('req')).toBe('req');
    expect(unitLabel('anything')).toBe('req');
  });

  it('compactCount: M / K / plain, with exact-multiple trimming', () => {
    expect(compactCount(1_200_000)).toBe('1.2M');
    expect(compactCount(4_000_000)).toBe('4M');
    expect(compactCount(4_000)).toBe('4K');
    expect(compactCount(1_500)).toBe('1.5K');
    expect(compactCount(820)).toBe('820');
  });

  it('numericLabel: known max vs unknown max', () => {
    expect(numericLabel(row({ provider: 'A', unit: 'req', used: 820, max: 1000 }))).toBe(
      '820 / 1000 req',
    );
    expect(
      numericLabel(row({ provider: 'A', unit: 'token', used: 1_200_000, max: 4_000_000 })),
    ).toBe('1.2M / 4M tok');
    expect(numericLabel(row({ provider: 'A', unit: 'token', used: 5, max: null }))).toBe('5 tok');
  });

  it('staleAgeLabel rounds minutes and floors at zero', () => {
    expect(staleAgeLabel(1000, 1000 + 600)).toBe('last checked 10m ago');
    expect(staleAgeLabel(2000, 1000)).toBe('last checked 0m ago');
  });

  it('groupByUnit keeps first-seen order and never merges units', () => {
    const groups = groupByUnit([
      row({ provider: 'A', unit: 'req' }),
      row({ provider: 'B', unit: 'token' }),
      row({ provider: 'C', unit: 'req' }),
    ]);
    expect(groups.map((g) => g.unit)).toEqual(['req', 'token']);
    expect(groups[0].rows).toHaveLength(2);
    expect(groups[1].rows).toHaveLength(1);
  });

  it('isSuperpowered: 3 healthy distinct providers true; borderline false', () => {
    const healthy = (p: string) => row({ provider: p, unit: 'req', used: 100, max: 1000 });
    expect(isSuperpowered([healthy('A'), healthy('B'), healthy('C')])).toBe(true);
    // Only 2 healthy keys.
    expect(isSuperpowered([healthy('A'), healthy('B')])).toBe(false);
    // 3 keys but only 2 DISTINCT providers.
    expect(isSuperpowered([healthy('A'), healthy('A'), healthy('B')])).toBe(false);
    // 3 distinct providers but one is unhealthy (low remaining).
    expect(
      isSuperpowered([
        healthy('A'),
        healthy('B'),
        row({ provider: 'C', unit: 'req', used: 950, max: 1000 }),
      ]),
    ).toBe(false);
  });

  it('prefersReducedMotion reads matchMedia', () => {
    setReducedMotion(true);
    expect(prefersReducedMotion()).toBe(true);
    setReducedMotion(false);
    expect(prefersReducedMotion()).toBe(false);
  });
});

// --------------------------------------------------------------------------- //
// <UsageBars /> render
// --------------------------------------------------------------------------- //
describe('<UsageBars />', () => {
  it('renders the empty state with no rows', async () => {
    await render(<UsageBars rows={[]} />);
    expect(container.querySelector('[data-usage="empty"]')).not.toBeNull();
    expect(container.querySelector('[data-usage="groups"]')).toBeNull();
  });

  it('mixed REQ + TOKEN pool yields >= 2 SEPARATE grouped bars (no cross-unit sum)', async () => {
    await render(
      <UsageBars
        rows={[
          row({ provider: 'Groq', unit: 'req', used: 100, max: 1000 }),
          row({ provider: 'OpenRouter', unit: 'token', used: 500_000, max: 4_000_000 }),
        ]}
      />,
    );
    const groups = container.querySelectorAll('.usage-group');
    expect(groups.length).toBe(2);
    const units = Array.from(groups).map((g) => g.getAttribute('data-unit'));
    expect(units).toContain('req');
    expect(units).toContain('token');
    // Each group keeps its OWN bar(s) — nothing is summed across units.
    expect(container.querySelectorAll('[data-unit="req"] .usage-bar').length).toBe(1);
    expect(container.querySelectorAll('[data-unit="token"] .usage-bar').length).toBe(1);
    expect(container.querySelector('[data-usage="groups"]')?.getAttribute('data-group-count')).toBe(
      '2',
    );
  });

  it('renders each color band with its glyph and numeric label', async () => {
    await render(
      <UsageBars
        rows={[
          row({ provider: 'Healthy', unit: 'req', used: 100, max: 1000 }),
          row({ provider: 'Warn', unit: 'req', used: 600, max: 1000 }),
          row({ provider: 'Critical', unit: 'req', used: 900, max: 1000 }),
        ]}
      />,
    );
    const bars = container.querySelectorAll('.usage-bar');
    expect(bars.length).toBe(3);
    const byProvider = (name: string) =>
      container.querySelector(`.usage-bar[data-provider="${name}"]`) as HTMLElement;

    const h = byProvider('Healthy');
    expect(h.getAttribute('data-zone')).toBe('healthy');
    expect(h.querySelector('.usage-bar__glyph')?.textContent).toBe('●');
    expect(h.querySelector('.usage-bar__value')?.textContent).toBe('100 / 1000 req');

    const w = byProvider('Warn');
    expect(w.getAttribute('data-zone')).toBe('warn');
    expect(w.querySelector('.usage-bar__glyph')?.textContent).toBe('◐');

    const c = byProvider('Critical');
    expect(c.getAttribute('data-zone')).toBe('critical');
    expect(c.querySelector('.usage-bar__glyph')?.textContent).toBe('○');
    // The fill width reflects REMAINING (100 used of 1000 -> 90% remaining).
    const fill = h.querySelector('.usage-bar__fill') as HTMLElement;
    expect(fill.style.width).toBe('90%');
  });

  it('superpowered: fires at >= 3 healthy distinct providers with an always-present label', async () => {
    const healthy = (p: string) => row({ provider: p, unit: 'req', used: 50, max: 1000 });
    await render(<UsageBars rows={[healthy('A'), healthy('B'), healthy('C')]} />);
    const group = container.querySelector('.usage-group') as HTMLElement;
    expect(group.getAttribute('data-superpowered')).toBe('true');
    const label = group.querySelector('[data-label="superpowered"]') as HTMLElement;
    expect(label).not.toBeNull();
    expect(label.textContent).toContain('Superpowered');
    expect(label.title).toContain(`${SUPERPOWERED_MIN}+`);
  });

  it('NOT superpowered at the borderline (3 keys across only 2 providers)', async () => {
    const healthy = (p: string) => row({ provider: p, unit: 'req', used: 50, max: 1000 });
    await render(<UsageBars rows={[healthy('A'), healthy('A'), healthy('B')]} />);
    const group = container.querySelector('.usage-group') as HTMLElement;
    expect(group.getAttribute('data-superpowered')).toBe('false');
    expect(group.querySelector('[data-label="superpowered"]')).toBeNull();
  });

  it('reduced-motion disables the fill transition', async () => {
    setReducedMotion(true);
    await render(<UsageBars rows={[row({ provider: 'Groq', unit: 'req', used: 100, max: 1000 })]} />);
    expect(container.querySelector('.usage-bar.is-reduced-motion')).not.toBeNull();
  });

  it('does NOT add the reduced-motion class when motion is allowed', async () => {
    setReducedMotion(false);
    await render(<UsageBars rows={[row({ provider: 'Groq', unit: 'req', used: 100, max: 1000 })]} />);
    expect(container.querySelector('.usage-bar.is-reduced-motion')).toBeNull();
  });

  it('stale rows desaturate and show "last checked Xm ago" (fake clock)', async () => {
    await render(
      <UsageBars
        rows={[
          row({
            provider: 'Groq',
            unit: 'req',
            used: 100,
            max: 1000,
            stale: true,
            lastCheckedAt: 1000,
          }),
        ]}
        nowSec={1000 + 15 * 60}
      />,
    );
    const bar = container.querySelector('.usage-bar') as HTMLElement;
    expect(bar.classList.contains('is-stale')).toBe(true);
    const note = bar.querySelector('[data-stale-note="true"]') as HTMLElement;
    expect(note).not.toBeNull();
    expect(note.textContent).toBe('last checked 15m ago');
  });

  it('a stale row with no lastCheckedAt falls back to now (0m ago)', async () => {
    await render(
      <UsageBars
        rows={[row({ provider: 'Groq', unit: 'req', used: 100, max: 1000, stale: true })]}
        nowSec={5000}
      />,
    );
    const note = container.querySelector('[data-stale-note="true"]') as HTMLElement;
    expect(note.textContent).toBe('last checked 0m ago');
  });

  it('non-stale rows render no stale note', async () => {
    await render(
      <UsageBars rows={[row({ provider: 'Groq', unit: 'req', used: 100, max: 1000 })]} />,
    );
    expect(container.querySelector('[data-stale-note="true"]')).toBeNull();
  });

  it('defaults nowSec to Date.now when not injected', async () => {
    const spy = vi.spyOn(Date, 'now').mockReturnValue(9_000_000);
    await render(
      <UsageBars
        rows={[
          row({ provider: 'Groq', unit: 'req', used: 100, max: 1000, stale: true, lastCheckedAt: 9000 - 120 }),
        ]}
      />,
    );
    const note = container.querySelector('[data-stale-note="true"]') as HTMLElement;
    expect(note.textContent).toBe('last checked 2m ago');
    spy.mockRestore();
  });
});
