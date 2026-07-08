// SpendCap.test.tsx — the Monthly spend-cap control (WU-spend-cap). Covers load
// (seed from providers.spend), every zone render (no-cap / ok / near / blocked),
// the bounded-vs-unbounded meter, editing soft/hard/enforce, save → settings.set
// + refetch (success + error), the saved indicator, and the alive-guard paths.

// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import { SpendCap, type SpendCapClient } from './SpendCap';
import type { SpendInfo } from '../lib/rpc';

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
  vi.restoreAllMocks();
});

async function flush(): Promise<void> {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });
}

function setInputValue(el: HTMLInputElement, value: string): void {
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set;
  setter?.call(el, value);
  el.dispatchEvent(new Event('input', { bubbles: true }));
}

function toggleCheckbox(el: HTMLInputElement, value: boolean): void {
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'checked')?.set;
  setter?.call(el, value);
  el.dispatchEvent(new Event('click', { bubbles: true }));
}

function spendInfo(over: Partial<SpendInfo> = {}): SpendInfo {
  return {
    month: '2026-06',
    monthToDateCents: 0,
    softLimitCents: 0,
    hardLimitCents: 0,
    enforceHardLimit: false,
    isEstimate: false,
    ...over,
  };
}

interface Overrides {
  spend?: () => Promise<SpendInfo>;
  set?: ReturnType<typeof vi.fn>;
}

function makeApi(over: Overrides = {}): {
  api: SpendCapClient;
  set: ReturnType<typeof vi.fn>;
  spend: ReturnType<typeof vi.fn>;
} {
  const spend = vi.fn(over.spend ?? (() => Promise.resolve(spendInfo())));
  const set = over.set ?? vi.fn(() => Promise.resolve({}));
  return { api: { providers: { spend }, settings: { set } }, set, spend };
}

async function mount(api: SpendCapClient): Promise<void> {
  await act(async () => {
    root.render(<SpendCap rpcClient={api} />);
  });
  await flush();
}

const $ = (sel: string): Element | null => container.querySelector(sel);

describe('SpendCap — load + zero/empty state', () => {
  it('shows a loading state then the no-cap state when nothing is configured', async () => {
    let resolveSpend: (v: SpendInfo) => void = () => {};
    const { api } = makeApi({
      spend: () =>
        new Promise<SpendInfo>((res) => {
          resolveSpend = res;
        }),
    });
    await act(async () => {
      root.render(<SpendCap rpcClient={api} />);
    });
    expect($('.spend-cap__loading')).not.toBeNull();
    await act(async () => {
      resolveSpend(spendInfo());
    });
    await flush();
    expect($('.spend-cap__loading')).toBeNull();
    expect($('.spend-cap__meter')?.getAttribute('data-zone')).toBe('no-cap');
    expect(container.textContent).toContain('No spend cap set');
    // No bounded bar in the no-cap state.
    expect($('.spend-cap__track')).toBeNull();
    // The readout still shows month-to-date + the month key.
    expect($('.spend-cap__readout-value')?.textContent).toBe('$0.00');
    expect($('.spend-cap__readout-month')?.textContent).toBe('2026-06');
  });

  it('seeds the inputs + toggle from the configured caps', async () => {
    const { api } = makeApi({
      spend: () =>
        Promise.resolve(
          spendInfo({ softLimitCents: 1000, hardLimitCents: 5000, enforceHardLimit: true }),
        ),
    });
    await mount(api);
    expect(($('#spend-cap-soft') as HTMLInputElement).value).toBe('10.00');
    expect(($('#spend-cap-hard') as HTMLInputElement).value).toBe('50.00');
    expect(($('#spend-cap-enforce') as HTMLInputElement).checked).toBe(true);
  });

  it('surfaces a load error and shows no meter', async () => {
    const { api } = makeApi({ spend: () => Promise.reject(new Error('boom')) });
    await mount(api);
    expect($('[role="alert"]')?.textContent).toBe('boom');
    expect($('.spend-cap__meter')).toBeNull();
  });

  it('degrades to an inline error (no thrown-through blank) when window.api is missing', async () => {
    // WU2 resilience: no injected rpcClient -> the real `client`, whose bridge()
    // throws SYNCHRONOUSLY when window.api is undefined. The sync-safe guard must
    // surface it inline rather than let it unmount the tree.
    expect((globalThis as { window?: { api?: unknown } }).window?.api).toBeUndefined();
    await act(async () => {
      root.render(<SpendCap />);
    });
    await flush();
    const alert = $('[role="alert"]');
    expect(alert).not.toBeNull();
    expect(alert?.textContent).toContain('window.api');
  });

  it('stringifies a non-Error rejection', async () => {
    const { api } = makeApi({ spend: () => Promise.reject('nope') });
    await mount(api);
    expect($('[role="alert"]')?.textContent).toBe('nope');
  });
});

describe('SpendCap — estimate honesty (WU-D4)', () => {
  it('labels a non-zero month-to-date "estimated" when the figure is placeholder-derived', async () => {
    const { api } = makeApi({
      spend: () => Promise.resolve(spendInfo({ monthToDateCents: 2500, isEstimate: true })),
    });
    await mount(api);
    const badge = $('.spend-cap__readout-estimate');
    expect(badge).not.toBeNull();
    expect(badge?.getAttribute('data-estimate')).toBe('true');
    expect(badge?.textContent).toBe('estimated');
  });

  it('does not label a zero month-to-date as estimated (nothing to qualify)', async () => {
    const { api } = makeApi({
      spend: () => Promise.resolve(spendInfo({ monthToDateCents: 0, isEstimate: true })),
    });
    await mount(api);
    expect($('.spend-cap__readout-estimate')).toBeNull();
  });

  it('does not label a figure estimated when real pricing backs it', async () => {
    const { api } = makeApi({
      spend: () => Promise.resolve(spendInfo({ monthToDateCents: 2500, isEstimate: false })),
    });
    await mount(api);
    expect($('.spend-cap__readout-estimate')).toBeNull();
  });
});

describe('SpendCap — zone rendering', () => {
  it('ok zone: bounded meter under the soft cap', async () => {
    const { api } = makeApi({
      spend: () =>
        Promise.resolve(
          spendInfo({ monthToDateCents: 2500, softLimitCents: 4000, hardLimitCents: 5000 }),
        ),
    });
    await mount(api);
    const meter = $('.spend-cap__meter');
    expect(meter?.getAttribute('data-zone')).toBe('ok');
    const track = $('.spend-cap__track');
    expect(track).not.toBeNull();
    expect(track?.getAttribute('aria-valuenow')).toBe('50');
    expect(track?.getAttribute('aria-valuetext')).toContain('$25.00 of $50.00');
    expect(($('.spend-cap__fill') as HTMLElement).style.width).toBe('50%');
    expect(container.textContent).toContain('Within budget');
  });

  it('near zone: at/over the soft cap, under the hard cap', async () => {
    const { api } = makeApi({
      spend: () =>
        Promise.resolve(
          spendInfo({ monthToDateCents: 4500, softLimitCents: 4000, hardLimitCents: 8000 }),
        ),
    });
    await mount(api);
    expect($('.spend-cap__meter')?.getAttribute('data-zone')).toBe('near');
    expect(container.textContent).toContain('Near the soft cap');
    // The non-color glyph is present (color is never the only signal).
    expect($('.spend-cap__status-glyph')?.textContent).toBe('⚠');
  });

  it('blocked zone (enforced): at the hard cap, full bar, blocked copy', async () => {
    const { api } = makeApi({
      spend: () =>
        Promise.resolve(
          spendInfo({
            monthToDateCents: 8000,
            softLimitCents: 4000,
            hardLimitCents: 8000,
            enforceHardLimit: true,
          }),
        ),
    });
    await mount(api);
    expect($('.spend-cap__meter')?.getAttribute('data-zone')).toBe('blocked');
    expect(($('.spend-cap__fill') as HTMLElement).style.width).toBe('100%');
    expect(container.textContent).toContain('new cloud runs are blocked');
    expect($('.spend-cap__status-glyph')?.textContent).toBe('⛔');
  });

  it('blocked zone (not enforced): over the hard cap but runs proceed', async () => {
    const { api } = makeApi({
      spend: () =>
        Promise.resolve(
          spendInfo({
            monthToDateCents: 9000,
            hardLimitCents: 8000,
            enforceHardLimit: false,
          }),
        ),
    });
    await mount(api);
    expect($('.spend-cap__meter')?.getAttribute('data-zone')).toBe('blocked');
    expect(container.textContent).toContain('not enforced');
  });

  it('soft-only cap renders a bounded bar against the soft ceiling', async () => {
    const { api } = makeApi({
      spend: () => Promise.resolve(spendInfo({ monthToDateCents: 500, softLimitCents: 1000 })),
    });
    await mount(api);
    expect($('.spend-cap__track')?.getAttribute('aria-valuenow')).toBe('50');
    expect($('.spend-cap__track')?.getAttribute('aria-valuetext')).toContain('$5.00 of $10.00');
  });
});

describe('SpendCap — edit + save', () => {
  it('edits soft/hard/enforce and saves the converted cents through settings.set, then refetches', async () => {
    const fresh = spendInfo({
      softLimitCents: 1500,
      hardLimitCents: 6000,
      enforceHardLimit: true,
    });
    const spend = vi
      .fn(() => Promise.resolve(spendInfo()))
      .mockResolvedValueOnce(spendInfo())
      .mockResolvedValueOnce(fresh);
    const set = vi.fn(() => Promise.resolve({}));
    const api: SpendCapClient = { providers: { spend }, settings: { set } };
    await act(async () => {
      root.render(<SpendCap rpcClient={api} />);
    });
    await flush();

    setInputValue($('#spend-cap-soft') as HTMLInputElement, '15');
    setInputValue($('#spend-cap-hard') as HTMLInputElement, '60');
    toggleCheckbox($('#spend-cap-enforce') as HTMLInputElement, true);
    await flush();

    await act(async () => {
      ($('.spend-cap__save') as HTMLButtonElement).click();
    });
    await flush();

    expect(set).toHaveBeenCalledWith({
      monthlySoftLimitCents: 1500,
      monthlyHardLimitCents: 6000,
      enforceMonthlyHardLimit: true,
    });
    // Refetched: the inputs now reflect the persisted values, "Saved" is shown.
    expect(spend).toHaveBeenCalledTimes(2);
    expect(($('#spend-cap-soft') as HTMLInputElement).value).toBe('15.00');
    expect($('.spend-cap__saved')).not.toBeNull();
  });

  it('surfaces a save error and shows no saved indicator', async () => {
    const { api } = makeApi({ set: vi.fn(() => Promise.reject(new Error('write failed'))) });
    await mount(api);
    await act(async () => {
      ($('.spend-cap__save') as HTMLButtonElement).click();
    });
    await flush();
    expect($('[role="alert"]')?.textContent).toBe('write failed');
    expect($('.spend-cap__saved')).toBeNull();
  });

  it('disables the inputs + save button while saving', async () => {
    let resolveSet: (v: unknown) => void = () => {};
    const set = vi.fn(
      () =>
        new Promise((res) => {
          resolveSet = res;
        }),
    );
    const { api } = makeApi({ set });
    await mount(api);
    await act(async () => {
      ($('.spend-cap__save') as HTMLButtonElement).click();
    });
    await flush();
    const btn = $('.spend-cap__save') as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
    expect(btn.textContent).toBe('Saving…');
    expect(($('#spend-cap-soft') as HTMLInputElement).disabled).toBe(true);
    // Let it settle so the unmount in afterEach is clean.
    await act(async () => {
      resolveSet({});
    });
    await flush();
  });
});

describe('SpendCap — alive guards', () => {
  it('ignores a late spend resolve after unmount', async () => {
    let resolveSpend: (v: SpendInfo) => void = () => {};
    const { api } = makeApi({
      spend: () =>
        new Promise<SpendInfo>((res) => {
          resolveSpend = res;
        }),
    });
    await act(async () => {
      root.render(<SpendCap rpcClient={api} />);
    });
    await act(async () => root.unmount());
    await act(async () => {
      resolveSpend(spendInfo({ softLimitCents: 1000 }));
    });
    await flush();
    expect($('.spend-cap__meter')).toBeNull();
    root = createRoot(container);
  });

  it('ignores a late spend reject after unmount', async () => {
    let rejectSpend: (e: Error) => void = () => {};
    const { api } = makeApi({
      spend: () =>
        new Promise<SpendInfo>((_res, rej) => {
          rejectSpend = rej;
        }),
    });
    await act(async () => {
      root.render(<SpendCap rpcClient={api} />);
    });
    await act(async () => root.unmount());
    await act(async () => {
      rejectSpend(new Error('late'));
    });
    await flush();
    expect($('[role="alert"]')).toBeNull();
    root = createRoot(container);
  });
});
