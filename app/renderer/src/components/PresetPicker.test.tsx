// PresetPicker.test.tsx — presets + per-function override (WU-presets PH3).
// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

import { PresetPicker, FUNCTION_LABELS } from './PresetPicker';
import type { CatalogResponse, RoutingBlock } from '../lib/rpc';

function catalog(): CatalogResponse {
  return {
    asOfDate: '2026-06-16',
    unit: ['req', 'token'],
    tasks: ['moment_find', 'caption', 'translation', 'vision', 'edit_plan'],
    topPicks: {
      moment_find: 'groq-gpt-oss-120b',
      vision: 'gemini-2.5-flash-lite',
    },
    providers: [
      {
        id: 'groq-gpt-oss-120b',
        provider: 'Groq',
        model: 'GPT-OSS-120B',
        capabilities: ['text'],
        contextTokens: 128000,
        perTaskTier: {
          moment_find: 'S',
          caption: 'A',
          translation: 'A',
          vision: 'na',
          edit_plan: 'S',
        },
        costClass: 'free',
        freeLimits: '30 RPM',
        freeLimitScore: 80,
        unit: 'token',
        trainsOnInput: false,
        privacyTier: 'SAFE',
        recommendedFor: ['moment_find'],
        notes: 'safe',
        asOfDate: '2026-06-16',
      },
      {
        id: 'gemini-2.5-flash-lite',
        provider: 'Google',
        model: 'Gemini 2.5 Flash-Lite',
        capabilities: ['text', 'vision'],
        contextTokens: 1000000,
        perTaskTier: {
          moment_find: 'A',
          caption: 'S',
          translation: 'A',
          vision: 'S',
          edit_plan: 'A',
        },
        costClass: 'free',
        freeLimits: '30 RPM',
        freeLimitScore: 65,
        unit: 'req',
        trainsOnInput: true,
        privacyTier: 'AVOID',
        recommendedFor: ['vision'],
        notes: 'trains',
        asOfDate: '2026-06-16',
      },
    ],
  };
}

function routing(): RoutingBlock {
  return {
    perFunction: {
      select: { provider: 'groq-gpt-oss-120b', fallback: ['local'] },
      subtitles: { provider: 'local', fallback: [] },
      translation: { provider: 'groq-gpt-oss-120b', fallback: ['local'] },
      vision: { provider: 'local', fallback: [] },
      editPlan: { provider: 'groq-gpt-oss-120b', fallback: ['local'] },
    },
  };
}

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
  vi.restoreAllMocks();
});

function mount(props: Parameters<typeof PresetPicker>[0]): void {
  act(() => {
    root.render(<PresetPicker {...props} />);
  });
}

describe('<PresetPicker />', () => {
  it('renders the three smart preset buttons', () => {
    mount({
      catalog: catalog(),
      routing: routing(),
      activePreset: 'bestFreeCloud',
      onApplyPreset: vi.fn(),
      onSetFunction: vi.fn(),
    });
    expect(container.querySelector('[data-preset="privacy"]')).not.toBeNull();
    expect(container.querySelector('[data-preset="bestFreeCloud"]')).not.toBeNull();
    expect(container.querySelector('[data-preset="balanced"]')).not.toBeNull();
  });

  it('marks the active preset', () => {
    mount({
      catalog: catalog(),
      routing: routing(),
      activePreset: 'bestFreeCloud',
      onApplyPreset: vi.fn(),
      onSetFunction: vi.fn(),
    });
    const active = container.querySelector('[data-preset="bestFreeCloud"]') as HTMLElement;
    expect(active.getAttribute('aria-pressed')).toBe('true');
    const other = container.querySelector('[data-preset="privacy"]') as HTMLElement;
    expect(other.getAttribute('aria-pressed')).toBe('false');
  });

  it('calls onApplyPreset when a preset is clicked', () => {
    const onApplyPreset = vi.fn();
    mount({
      catalog: catalog(),
      routing: routing(),
      activePreset: '',
      onApplyPreset,
      onSetFunction: vi.fn(),
    });
    const btn = container.querySelector('[data-preset="balanced"]') as HTMLButtonElement;
    act(() => btn.click());
    expect(onApplyPreset).toHaveBeenCalledWith('balanced');
  });

  it('renders a per-function dropdown for each of the five functions', () => {
    mount({
      catalog: catalog(),
      routing: routing(),
      activePreset: 'custom',
      onApplyPreset: vi.fn(),
      onSetFunction: vi.fn(),
    });
    for (const fn of Object.keys(FUNCTION_LABELS)) {
      expect(container.querySelector(`select[data-function="${fn}"]`)).not.toBeNull();
    }
  });

  it('selects the routed provider in each dropdown', () => {
    mount({
      catalog: catalog(),
      routing: routing(),
      activePreset: 'custom',
      onApplyPreset: vi.fn(),
      onSetFunction: vi.fn(),
    });
    const sel = container.querySelector('select[data-function="select"]') as HTMLSelectElement;
    expect(sel.value).toBe('groq-gpt-oss-120b');
    const visionSel = container.querySelector(
      'select[data-function="vision"]',
    ) as HTMLSelectElement;
    expect(visionSel.value).toBe('local');
  });

  it('only offers vision-capable models for the vision function', () => {
    mount({
      catalog: catalog(),
      routing: routing(),
      activePreset: 'custom',
      onApplyPreset: vi.fn(),
      onSetFunction: vi.fn(),
    });
    const visionSel = container.querySelector(
      'select[data-function="vision"]',
    ) as HTMLSelectElement;
    const optionValues = Array.from(visionSel.options).map((o) => o.value);
    // local always offered; the text-only Groq model is NOT a vision option.
    expect(optionValues).toContain('local');
    expect(optionValues).toContain('gemini-2.5-flash-lite');
    expect(optionValues).not.toContain('groq-gpt-oss-120b');
  });

  it('offers text models (not vision-only) for the select function', () => {
    mount({
      catalog: catalog(),
      routing: routing(),
      activePreset: 'custom',
      onApplyPreset: vi.fn(),
      onSetFunction: vi.fn(),
    });
    const sel = container.querySelector('select[data-function="select"]') as HTMLSelectElement;
    const optionValues = Array.from(sel.options).map((o) => o.value);
    // Groq has a real (non-na) select grade -> offered; gemini has a select grade too.
    expect(optionValues).toContain('groq-gpt-oss-120b');
    expect(optionValues).toContain('local');
  });

  it('calls onSetFunction when a dropdown changes', () => {
    const onSetFunction = vi.fn();
    mount({
      catalog: catalog(),
      routing: routing(),
      activePreset: 'custom',
      onApplyPreset: vi.fn(),
      onSetFunction,
    });
    const sel = container.querySelector('select[data-function="subtitles"]') as HTMLSelectElement;
    sel.value = 'gemini-2.5-flash-lite';
    act(() => sel.dispatchEvent(new Event('change', { bubbles: true })));
    expect(onSetFunction).toHaveBeenCalledWith('subtitles', 'gemini-2.5-flash-lite');
  });

  it('shows a privacy-AVOID warning glyph on a training model option', () => {
    mount({
      catalog: catalog(),
      routing: routing(),
      activePreset: 'custom',
      onApplyPreset: vi.fn(),
      onSetFunction: vi.fn(),
    });
    const visionSel = container.querySelector(
      'select[data-function="vision"]',
    ) as HTMLSelectElement;
    const gemOpt = Array.from(visionSel.options).find((o) => o.value === 'gemini-2.5-flash-lite');
    // The AVOID privacy tier is surfaced in the option text (not color-only).
    expect(gemOpt?.textContent).toContain('trains on input');
  });

  it('disables controls while busy', () => {
    mount({
      catalog: catalog(),
      routing: routing(),
      activePreset: 'custom',
      onApplyPreset: vi.fn(),
      onSetFunction: vi.fn(),
      busy: true,
    });
    expect((container.querySelector('[data-preset="privacy"]') as HTMLButtonElement).disabled).toBe(
      true,
    );
    expect(
      (container.querySelector('select[data-function="select"]') as HTMLSelectElement).disabled,
    ).toBe(true);
  });

  it('falls back to local-only options when the catalog is empty', () => {
    const empty: CatalogResponse = { ...catalog(), providers: [] };
    mount({
      catalog: empty,
      routing: routing(),
      activePreset: 'privacy',
      onApplyPreset: vi.fn(),
      onSetFunction: vi.fn(),
    });
    const sel = container.querySelector('select[data-function="select"]') as HTMLSelectElement;
    const optionValues = Array.from(sel.options).map((o) => o.value);
    expect(optionValues).toEqual(['local']);
  });

  it('handles a routing block missing a function slot (defaults to local)', () => {
    const partial: RoutingBlock = { perFunction: {} };
    mount({
      catalog: catalog(),
      routing: partial,
      activePreset: 'custom',
      onApplyPreset: vi.fn(),
      onSetFunction: vi.fn(),
    });
    const sel = container.querySelector('select[data-function="select"]') as HTMLSelectElement;
    expect(sel.value).toBe('local');
  });
});
