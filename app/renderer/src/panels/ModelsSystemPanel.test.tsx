// ModelsSystemPanel.test.tsx — the "Models & System" panel: opt-in analysis,
// hardware bars, recommended preset, tier selection, model download gating,
// notes, ASR/diarize selectors, and the first-run onboarding overlay.

// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import {
  ModelsSystemPanel,
  errText,
  indexAssets,
  isInstalled,
  qualityFraction,
  sizeForComponent,
} from './ModelsSystemPanel';
import type {
  AdvisorReport,
  AssetInfo,
  ComponentStatus,
  HardwareInfo,
  client as RealClient,
} from '../lib/rpc';

// ---- pure-helper coverage --------------------------------------------------

function report(): AdvisorReport {
  return {
    components: [
      {
        name: 'motion',
        present: true,
        verdict: 'ok',
        vramMb: null,
        licenseCommercialOk: true,
        reason: 'CPU floor',
      },
      {
        name: 'vlm_backbone',
        present: true,
        verdict: 'ok',
        vramMb: 2300,
        licenseCommercialOk: true,
        reason: 'SigLIP-2',
      },
      {
        name: 'smolvlm2',
        present: false,
        verdict: 'degraded',
        vramMb: 5200,
        licenseCommercialOk: true,
        reason: 'tight',
      },
    ],
    tiers: [
      { tier: 0, label: 'Numeric floor', verdict: 'ok', components: ['motion'] },
      { tier: 1, label: 'Multimodal', verdict: 'ok', components: ['vlm_backbone'] },
      { tier: 2, label: 'Video-LLM', verdict: 'degraded', components: ['smolvlm2'] },
    ],
    recommendedPreset: 'tier1-multimodal',
    vramBudgetMb: 6000,
    notes: ['Parakeet ASR fits only with audio CHUNKING'],
  };
}

const assetList: AssetInfo[] = [
  { name: 'siglip2-so400m', kind: 'model', sizeMB: 4540, installed: true, dest: '/m/siglip' },
  { name: 'smolvlm2-2.2b', kind: 'model', sizeMB: 4500, installed: false, dest: '/m/smol' },
];

describe('pure helpers', () => {
  it('errText handles Error and non-Error', () => {
    expect(errText(new Error('boom'))).toBe('boom');
    expect(errText('plain')).toBe('plain');
  });
  it('qualityFraction normalizes over max tier; mid value when unowned', () => {
    const r = report();
    expect(qualityFraction('motion', r)).toBe(0);
    expect(qualityFraction('vlm_backbone', r)).toBeCloseTo(0.5);
    expect(qualityFraction('smolvlm2', r)).toBe(1);
    expect(qualityFraction('ctc_aligner', r)).toBe(0.5);
  });
  it('qualityFraction guards a no-tier report (maxTier -> 1)', () => {
    const r = { ...report(), tiers: [] };
    expect(qualityFraction('anything', r)).toBe(0.5);
  });
  it('indexAssets / isInstalled / sizeForComponent', () => {
    const byAsset = indexAssets(assetList);
    expect(byAsset['siglip2-so400m'].sizeMB).toBe(4540);
    const motion: ComponentStatus = report().components[0];
    const vlm: ComponentStatus = report().components[1];
    const smol: ComponentStatus = report().components[2];
    expect(isInstalled(motion, byAsset)).toBe(true); // floor — always "installed"
    expect(isInstalled(vlm, byAsset)).toBe(true); // siglip installed
    expect(isInstalled(smol, byAsset)).toBe(false); // smol not installed
    expect(sizeForComponent(motion, byAsset)).toBeNull();
    expect(sizeForComponent(vlm, byAsset)).toBe(4540);
    // unknown asset -> null
    expect(sizeForComponent({ ...smol, name: 'mystery' }, byAsset)).toBeNull();
  });
});

// ---- component tests -------------------------------------------------------

interface FakeClient {
  client: typeof RealClient;
  calls: Array<{ method: string; args: unknown[] }>;
  settings: Record<string, unknown>;
}

function makeClient(
  over: {
    hardware?: HardwareInfo;
    advisor?: AdvisorReport;
    assets?: AssetInfo[];
    engines?: { id: string; label: string; installed: boolean }[];
    initialSettings?: Record<string, unknown>;
    rejectAnalyze?: boolean;
  } = {},
): FakeClient {
  const calls: FakeClient['calls'] = [];
  const settings: Record<string, unknown> = { ...(over.initialSettings ?? {}) };
  const fake = {
    system: {
      probe: vi.fn(async () => {
        calls.push({ method: 'system.probe', args: [] });
        if (over.rejectAnalyze) throw new Error('probe failed');
        return over.hardware ?? { vramMb: 6000, ramMb: 32000, cpuCount: 16, gpuPresent: true };
      }),
      advisor: vi.fn(async (opts?: { commercial?: boolean }) => {
        calls.push({ method: 'system.advisor', args: [opts] });
        return over.advisor ?? report();
      }),
    },
    assets: {
      list: vi.fn(async () => {
        calls.push({ method: 'assets.list', args: [] });
        return { assets: over.assets ?? assetList };
      }),
      ensure: vi.fn(async (names: string[]) => {
        calls.push({ method: 'assets.ensure', args: [names] });
        return { jobId: 'job-1' };
      }),
    },
    asr: {
      engines: vi.fn(async () => {
        calls.push({ method: 'asr.engines', args: [] });
        return {
          engines: over.engines ?? [
            { id: 'whisper', label: 'Whisper', installed: true },
            { id: 'parakeet', label: 'Parakeet', installed: false },
          ],
        };
      }),
    },
    settings: {
      get: vi.fn(async () => ({ ...settings })),
      set: vi.fn(async (patch: Record<string, unknown>) => {
        calls.push({ method: 'settings.set', args: [patch] });
        Object.assign(settings, patch);
        return { ...settings };
      }),
    },
  };
  return { client: fake as unknown as typeof RealClient, calls, settings };
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

async function mount(c: FakeClient): Promise<void> {
  await act(async () => {
    root.render(<ModelsSystemPanel rpcClient={c.client} />);
  });
  await act(async () => {
    await Promise.resolve();
  });
}

async function analyze(): Promise<void> {
  const btn = container.querySelector('button[data-action="analyze"]') as HTMLButtonElement;
  await act(async () => {
    btn.click();
  });
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

describe('<ModelsSystemPanel />', () => {
  it('shows the opt-in prompt before analysis runs', async () => {
    const c = makeClient();
    await mount(c);
    expect(container.querySelector('[data-section="prompt"]')).not.toBeNull();
    expect(container.querySelector('[data-section="hardware"]')).toBeNull();
  });

  it('analyzes: renders bars, preset, tiers, models, notes, and the onboarding tour', async () => {
    const c = makeClient();
    await mount(c);
    await analyze();

    // hardware bars + chips
    expect(container.querySelector('[data-section="hardware"]')).not.toBeNull();
    expect(container.querySelectorAll('.resource-bar').length).toBe(2);
    expect(container.querySelector('[data-chip="gpu"]')?.textContent).toContain('GPU detected');

    // recommended preset banner
    const banner = container.querySelector('[data-section="preset"]') as HTMLElement;
    expect(banner.getAttribute('data-preset')).toBe('tier1-multimodal');

    // tiers + models + notes
    expect(container.querySelectorAll('.tier-card').length).toBe(3);
    expect(container.querySelectorAll('.model-card').length).toBe(3);
    expect(container.querySelector('[data-section="notes"]')?.textContent).toContain('CHUNKING');

    // first-run onboarding overlay shows (modelsOnboardingSeen unset)
    expect(container.querySelector('.models-onboarding')).not.toBeNull();

    // advisor called with commercial:false (no setting)
    expect(c.calls.find((x) => x.method === 'system.advisor')?.args[0]).toEqual({
      commercial: false,
    });
  });

  it('does not show the tour when modelsOnboardingSeen is already set', async () => {
    const c = makeClient({ initialSettings: { modelsOnboardingSeen: true } });
    await mount(c);
    await analyze();
    expect(container.querySelector('.models-onboarding')).toBeNull();
  });

  it('finishing the tour persists modelsOnboardingSeen and re-opening works via Show tour again', async () => {
    const c = makeClient();
    await mount(c);
    await analyze();
    const skip = container.querySelector('button[data-action="skip"]') as HTMLButtonElement;
    await act(async () => skip.click());
    expect(c.settings.modelsOnboardingSeen).toBe(true);
    expect(container.querySelector('.models-onboarding')).toBeNull();

    const tour = container.querySelector('button[data-action="tour"]') as HTMLButtonElement;
    await act(async () => tour.click());
    expect(container.querySelector('.models-onboarding')).not.toBeNull();
  });

  it('selecting a tier writes settings.phase8Tier', async () => {
    const c = makeClient({ initialSettings: { modelsOnboardingSeen: true } });
    await mount(c);
    await analyze();
    const radios = container.querySelectorAll('.tier-card__radio');
    await act(async () => {
      (radios[2] as HTMLInputElement).click();
    });
    expect(c.calls.find((x) => x.method === 'settings.set')?.args[0]).toEqual({ phase8Tier: 2 });
  });

  it('Apply preset writes the recommended tier', async () => {
    const c = makeClient({ initialSettings: { modelsOnboardingSeen: true } });
    await mount(c);
    await analyze();
    const apply = container.querySelector(
      'button[data-action="apply-preset"]',
    ) as HTMLButtonElement;
    await act(async () => apply.click());
    expect(c.calls.find((x) => x.method === 'settings.set')?.args[0]).toEqual({ phase8Tier: 1 });
  });

  it('downloads a model then refreshes assets + advisor', async () => {
    const c = makeClient({ initialSettings: { modelsOnboardingSeen: true } });
    await mount(c);
    await analyze();
    const smolCard = container.querySelector('.model-card[data-model="smolvlm2"]') as HTMLElement;
    const btn = smolCard.querySelector('button[data-action="download"]') as HTMLButtonElement;
    await act(async () => {
      btn.click();
    });
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(c.calls.find((x) => x.method === 'assets.ensure')?.args[0]).toEqual(['smolvlm2-2.2b']);
    // a refresh advisor call happened after the ensure
    expect(c.calls.filter((x) => x.method === 'system.advisor').length).toBeGreaterThanOrEqual(2);
  });

  it('Re-probe re-runs only system.probe', async () => {
    const c = makeClient({ initialSettings: { modelsOnboardingSeen: true } });
    await mount(c);
    await analyze();
    const before = c.calls.filter((x) => x.method === 'system.probe').length;
    const reprobe = container.querySelector('button[data-action="reprobe"]') as HTMLButtonElement;
    await act(async () => {
      reprobe.click();
    });
    await act(async () => {
      await Promise.resolve();
    });
    expect(c.calls.filter((x) => x.method === 'system.probe').length).toBe(before + 1);
  });

  it('Commercial toggle persists and re-analysis passes commercial:true', async () => {
    const c = makeClient({ initialSettings: { modelsOnboardingSeen: true } });
    await mount(c);
    const toggle = container.querySelector('input[data-action="commercial"]') as HTMLInputElement;
    await act(async () => {
      toggle.click();
    });
    expect(c.settings.commercial).toBe(true);
    await analyze();
    const advisorCall = c.calls.filter((x) => x.method === 'system.advisor').pop();
    expect(advisorCall?.args[0]).toEqual({ commercial: true });
  });

  it('ASR + diarize selectors persist; pyannote shows the HF-token hint', async () => {
    const c = makeClient({ initialSettings: { modelsOnboardingSeen: true } });
    await mount(c);
    await analyze();

    const asr = container.querySelector('select[data-action="asr-engine"]') as HTMLSelectElement;
    await act(async () => {
      asr.value = 'parakeet';
      asr.dispatchEvent(new Event('change', { bubbles: true }));
    });
    expect(c.settings.asrEngine).toBe('parakeet');

    const diarize = container.querySelector(
      'select[data-action="diarize-backend"]',
    ) as HTMLSelectElement;
    await act(async () => {
      diarize.value = 'pyannote';
      diarize.dispatchEvent(new Event('change', { bubbles: true }));
    });
    expect(c.settings.diarizeBackend).toBe('pyannote');
    expect(container.querySelector('[data-hint="pyannote"]')).not.toBeNull();
  });

  it('surfaces an analysis error', async () => {
    const c = makeClient({ rejectAnalyze: true });
    await mount(c);
    await analyze();
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('probe failed');
    expect(container.querySelector('[data-section="hardware"]')).toBeNull();
  });
});
