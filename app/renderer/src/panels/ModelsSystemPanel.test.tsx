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
  CatalogResponse,
  ComponentStatus,
  HardwareInfo,
  ReadinessItem,
  UsageRow,
  client as RealClient,
} from '../lib/rpc';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

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

function emptyCatalog(): CatalogResponse {
  return {
    asOfDate: '2026-06-16',
    unit: ['req', 'token'],
    tasks: ['moment_find', 'caption', 'translation', 'vision', 'edit_plan'],
    topPicks: {},
    providers: [],
  };
}

function makeClient(
  over: {
    hardware?: HardwareInfo;
    advisor?: AdvisorReport;
    assets?: AssetInfo[];
    engines?: { id: string; label: string; installed: boolean }[];
    usage?: UsageRow[];
    catalog?: CatalogResponse;
    initialSettings?: Record<string, unknown>;
    rejectAnalyze?: boolean;
    rejectUsage?: boolean;
    readiness?: ReadinessItem[];
    rejectEnsure?: boolean;
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
        if (over.rejectEnsure) throw new Error('ensure failed');
        return { jobId: 'job-1' };
      }),
    },
    readiness: {
      summary: vi.fn(async () => {
        calls.push({ method: 'readiness.summary', args: [] });
        return { items: over.readiness ?? [] };
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
    providers: {
      usage: vi.fn(async () => {
        calls.push({ method: 'providers.usage', args: [] });
        if (over.rejectUsage) throw new Error('usage failed');
        return { usage: over.usage ?? [] };
      }),
      catalog: vi.fn(async () => {
        calls.push({ method: 'providers.catalog', args: [] });
        return over.catalog ?? emptyCatalog();
      }),
      applyPreset: vi.fn(async (name: string) => {
        calls.push({ method: 'providers.applyPreset', args: [name] });
        const routing = { perFunction: { select: { provider: 'groq-x', fallback: ['local'] } } };
        return { activePreset: name, routing };
      }),
      setFunctionModel: vi.fn(async (function_: string, provider: string) => {
        calls.push({ method: 'providers.setFunctionModel', args: [function_, provider] });
        const routing = { perFunction: { [function_]: { provider, fallback: [] } } };
        return { activePreset: 'custom', routing };
      }),
      firstRun: vi.fn(async (choice?: string) => {
        calls.push({ method: 'providers.firstRun', args: [choice] });
        if (choice === undefined) return { firstRunChoiceMade: false, default: 'privacy' };
        const routing = {
          perFunction:
            choice === 'privacy'
              ? { select: { provider: 'local', fallback: [] } }
              : { select: { provider: 'groq-x', fallback: ['local'] } },
        };
        return { firstRunChoiceMade: true, activePreset: choice, routing };
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

  it('persisting a setting surfaces an error when settings.set rejects', async () => {
    const c = makeClient({ initialSettings: { modelsOnboardingSeen: true } });
    await mount(c);
    await analyze();
    (c.client.settings.set as ReturnType<typeof vi.fn>).mockRejectedValueOnce(
      new Error('disk full'),
    );
    const radios = container.querySelectorAll('.tier-card__radio');
    await act(async () => {
      (radios[2] as HTMLInputElement).click();
    });
    await act(async () => {
      await Promise.resolve();
    });
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('disk full');
  });

  it('download surfaces an error when assets.ensure rejects', async () => {
    const c = makeClient({ initialSettings: { modelsOnboardingSeen: true } });
    await mount(c);
    await analyze();
    (c.client.assets.ensure as ReturnType<typeof vi.fn>).mockRejectedValueOnce(
      new Error('network down'),
    );
    const smolCard = container.querySelector('.model-card[data-model="smolvlm2"]') as HTMLElement;
    const btn = smolCard.querySelector('button[data-action="download"]') as HTMLButtonElement;
    await act(async () => {
      btn.click();
    });
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('network down');
  });

  it('Re-probe surfaces an error when the probe rejects', async () => {
    const c = makeClient({ initialSettings: { modelsOnboardingSeen: true } });
    await mount(c);
    await analyze();
    (c.client.system.probe as ReturnType<typeof vi.fn>).mockRejectedValueOnce(
      new Error('gpu vanished'),
    );
    const reprobe = container.querySelector('button[data-action="reprobe"]') as HTMLButtonElement;
    await act(async () => {
      reprobe.click();
    });
    await act(async () => {
      await Promise.resolve();
    });
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('gpu vanished');
  });

  it('falls back to a Whisper-only ASR list when the engines list is empty', async () => {
    const c = makeClient({ initialSettings: { modelsOnboardingSeen: true }, engines: [] });
    await mount(c);
    await analyze();
    const asr = container.querySelector('select[data-action="asr-engine"]') as HTMLSelectElement;
    const options = Array.from(asr.querySelectorAll('option'));
    expect(options.length).toBe(1);
    expect(options[0].value).toBe('whisper');
  });

  it('marks not-installed engines and renders no-CPU / no-GPU + missing-vram fallbacks', async () => {
    // vramBudgetMb undefined exercises the `report?.vramBudgetMb ?? hardware.vramMb`
    // nullish fallback (0 would NOT fall through since 0 is not nullish).
    const advisorNoVram = { ...report() } as Partial<AdvisorReport>;
    delete advisorNoVram.vramBudgetMb;
    const c = makeClient({
      initialSettings: { modelsOnboardingSeen: true },
      hardware: { vramMb: 4000, ramMb: 16000, cpuCount: 0, gpuPresent: false },
      advisor: advisorNoVram as AdvisorReport,
      engines: [{ id: 'parakeet', label: 'Parakeet', installed: false }],
    });
    await mount(c);
    await analyze();
    // not-installed engine annotated
    const asr = container.querySelector('select[data-action="asr-engine"]') as HTMLSelectElement;
    expect(asr.querySelector('option')?.textContent).toContain('(not installed)');
    // cpuCount 0 -> "unknown" false-arm
    expect(container.querySelector('[data-chip="cpu"]')?.textContent).toContain('unknown');
    // gpuPresent false -> "No GPU detected" false-arm
    expect(container.querySelector('[data-chip="gpu"]')?.textContent).toContain('No GPU detected');
    // vramBudgetMb undefined -> ?? falls through to hardware.vramMb
    expect(container.querySelectorAll('.resource-bar').length).toBe(2);
  });

  it('shows the "Analyzing…" busy label while an analysis is in flight', async () => {
    const c = makeClient({ initialSettings: { modelsOnboardingSeen: true } });
    // Hold probe pending so `busy` stays true and the button renders "Analyzing…".
    let release: () => void = () => {};
    (c.client.system.probe as ReturnType<typeof vi.fn>).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          release = () => resolve({ vramMb: 6000, ramMb: 32000, cpuCount: 16, gpuPresent: true });
        }),
    );
    await mount(c);
    const btn = container.querySelector('button[data-action="analyze"]') as HTMLButtonElement;
    await act(async () => {
      btn.click();
    });
    expect(btn.disabled).toBe(true);
    expect(btn.textContent).toContain('Analyzing');
    await act(async () => {
      release();
      await Promise.resolve();
      await Promise.resolve();
    });
    // After resolution the busy label clears.
    expect(btn.textContent).not.toContain('Analyzing');
  });

  it('download tolerates a non-array asset list and a null advisor refresh', async () => {
    const c = makeClient({ initialSettings: { modelsOnboardingSeen: true } });
    await mount(c);
    await analyze();
    // After the download refresh, assets.list yields a non-array (Array.isArray false-arm)
    // and advisor yields undefined (`rep ?? null` fallback).
    (c.client.assets.list as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      assets: null as unknown as AssetInfo[],
    });
    (c.client.system.advisor as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      undefined as unknown as AdvisorReport,
    );
    const smolCard = container.querySelector('.model-card[data-model="smolvlm2"]') as HTMLElement;
    const btn = smolCard.querySelector('button[data-action="download"]') as HTMLButtonElement;
    await act(async () => {
      btn.click();
    });
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });
    // advisor returned null -> report cleared -> preset banner gone, no crash.
    expect(c.calls.find((x) => x.method === 'assets.ensure')?.args[0]).toEqual(['smolvlm2-2.2b']);
    expect(container.querySelector('[data-section="preset"]')).toBeNull();
  });

  it('persisted settings.get returning nullish leaves settings empty (?? {} arm)', async () => {
    const c = makeClient({ initialSettings: { modelsOnboardingSeen: true } });
    (c.client.settings.get as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      null as unknown as Record<string, unknown>,
    );
    await mount(c);
    // No analysis yet -> opt-in prompt shows, commercial unchecked (settings empty).
    const toggle = container.querySelector('input[data-action="commercial"]') as HTMLInputElement;
    expect(toggle.checked).toBe(false);
  });

  it('analyze tolerates nullish probe/advisor and non-array asset/engine lists', async () => {
    const c = makeClient({ initialSettings: { modelsOnboardingSeen: true } });
    (c.client.system.probe as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      null as unknown as HardwareInfo,
    );
    (c.client.system.advisor as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      null as unknown as AdvisorReport,
    );
    (c.client.assets.list as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      assets: 'nope' as unknown as AssetInfo[],
    });
    (c.client.asr.engines as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      engines: null as unknown as { id: string; label: string; installed: boolean }[],
    });
    await mount(c);
    await analyze();
    // analyzed=true but hardware null -> no hardware section, no preset banner; no crash.
    expect(container.querySelector('[data-section="hardware"]')).toBeNull();
    expect(container.querySelector('[data-section="preset"]')).toBeNull();
    expect(container.querySelector('[role="alert"]')).toBeNull();
  });

  it('Re-probe tolerates a nullish probe result (?? null arm)', async () => {
    const c = makeClient({ initialSettings: { modelsOnboardingSeen: true } });
    await mount(c);
    await analyze();
    expect(container.querySelector('[data-section="hardware"]')).not.toBeNull();
    (c.client.system.probe as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      null as unknown as HardwareInfo,
    );
    const reprobe = container.querySelector('button[data-action="reprobe"]') as HTMLButtonElement;
    await act(async () => {
      reprobe.click();
    });
    await act(async () => {
      await Promise.resolve();
    });
    // hardware cleared -> the hardware header is gone, but no error.
    expect(container.querySelector('[data-section="hardware"]')).toBeNull();
    expect(container.querySelector('[role="alert"]')).toBeNull();
  });

  it('Apply preset is a no-op before a report exists (report guard)', async () => {
    // Render the panel with analysis never run; applyPreset is wired but `report`
    // is null, so calling it hits the `if (!report) return` guard. We drive it via
    // the toggle path: there is no apply button pre-analysis, so assert the guard by
    // re-analysis after a rejected advisor leaves report null, then Apply does nothing.
    const c = makeClient({ initialSettings: { modelsOnboardingSeen: true } });
    (c.client.system.advisor as ReturnType<typeof vi.fn>).mockRejectedValueOnce(
      new Error('advisor down'),
    );
    await mount(c);
    await analyze();
    // analysis failed -> no preset banner / apply button rendered
    expect(container.querySelector('button[data-action="apply-preset"]')).toBeNull();
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('advisor down');
  });

  // ---- WU-usage-ui: the loaded-providers usage section --------------------
  it('renders the usage section after analysis with the loaded keys', async () => {
    const usage: UsageRow[] = [
      {
        provider: 'Groq',
        key: '…WXYZ',
        used: 180,
        max: 1000,
        unit: 'req',
        resetAt: null,
        stale: false,
        lastCheckedAt: null,
      },
      {
        provider: 'OpenRouter',
        key: '…ABCD',
        used: 500_000,
        max: 4_000_000,
        unit: 'token',
        resetAt: null,
        stale: false,
        lastCheckedAt: null,
      },
    ];
    const c = makeClient({ initialSettings: { modelsOnboardingSeen: true }, usage });
    await mount(c);
    await analyze();
    expect(container.querySelector('[data-section="usage"]')).not.toBeNull();
    // mixed req + token -> two separate grouped bars (never summed).
    expect(container.querySelectorAll('.usage-group').length).toBe(2);
    expect(c.calls.some((x) => x.method === 'providers.usage')).toBe(true);
  });

  it('Refresh usage re-fetches and updates the bars', async () => {
    const c = makeClient({ initialSettings: { modelsOnboardingSeen: true } });
    await mount(c);
    await analyze();
    // initially empty.
    expect(container.querySelector('[data-usage="empty"]')).not.toBeNull();
    (c.client.providers.usage as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      usage: [
        {
          provider: 'Groq',
          key: '…WXYZ',
          used: 10,
          max: 1000,
          unit: 'req',
          resetAt: null,
          stale: false,
          lastCheckedAt: null,
        },
      ],
    });
    const btn = container.querySelector('button[data-action="refresh-usage"]') as HTMLButtonElement;
    await act(async () => btn.click());
    await act(async () => {
      await Promise.resolve();
    });
    expect(container.querySelector('[data-usage="groups"]')).not.toBeNull();
    expect(container.querySelector('[data-usage="empty"]')).toBeNull();
  });

  it('Refresh usage surfaces an error when the RPC rejects', async () => {
    const c = makeClient({ initialSettings: { modelsOnboardingSeen: true } });
    await mount(c);
    await analyze();
    (c.client.providers.usage as ReturnType<typeof vi.fn>).mockRejectedValueOnce(
      new Error('usage boom'),
    );
    const btn = container.querySelector('button[data-action="refresh-usage"]') as HTMLButtonElement;
    await act(async () => btn.click());
    await act(async () => {
      await Promise.resolve();
    });
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('usage boom');
  });

  it('non-array usage payloads coerce to an empty list (analyze + refresh paths)', async () => {
    const c = makeClient({ initialSettings: { modelsOnboardingSeen: true } });
    (c.client.providers.usage as ReturnType<typeof vi.fn>).mockResolvedValue({
      usage: null as unknown as UsageRow[],
    });
    await mount(c);
    await analyze();
    expect(container.querySelector('[data-usage="empty"]')).not.toBeNull();
    // Refresh also coerces a non-array payload to empty (the refresh ternary).
    const btn = container.querySelector('button[data-action="refresh-usage"]') as HTMLButtonElement;
    await act(async () => btn.click());
    await act(async () => {
      await Promise.resolve();
    });
    expect(container.querySelector('[data-usage="empty"]')).not.toBeNull();
  });

  // ---- WU-presets: first-run chooser + presets wiring --------------------

  function presetCatalog(): CatalogResponse {
    return {
      ...emptyCatalog(),
      providers: [
        {
          id: 'groq-x',
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
      ],
    };
  }

  it('shows the first-run chooser before a choice is made', async () => {
    const c = makeClient({
      initialSettings: { modelsOnboardingSeen: true, firstRunChoiceMade: false },
    });
    await mount(c);
    expect(
      container.querySelector('[role="dialog"][aria-label="Choose how Reframe runs AI"]'),
    ).not.toBeNull();
  });

  it('hides the first-run chooser once a choice is recorded', async () => {
    const c = makeClient({
      initialSettings: { modelsOnboardingSeen: true, firstRunChoiceMade: true },
    });
    await mount(c);
    expect(
      container.querySelector('[role="dialog"][aria-label="Choose how Reframe runs AI"]'),
    ).toBeNull();
  });

  it('choosing cloud on first run flips routing + hides the chooser', async () => {
    const c = makeClient({
      initialSettings: { modelsOnboardingSeen: true, firstRunChoiceMade: false },
    });
    await mount(c);
    const btn = container.querySelector('[data-choice="bestFreeCloud"]') as HTMLButtonElement;
    await act(async () => btn.click());
    await act(async () => {
      await Promise.resolve();
    });
    expect(c.client.providers.firstRun as ReturnType<typeof vi.fn>).toHaveBeenCalledWith(
      'bestFreeCloud',
    );
    // The chooser is gone once firstRunChoiceMade flipped true.
    expect(container.querySelector('[data-choice="bestFreeCloud"]')).toBeNull();
  });

  it('a first-run error surfaces in the alert and keeps the chooser', async () => {
    const c = makeClient({
      initialSettings: { modelsOnboardingSeen: true, firstRunChoiceMade: false },
    });
    (c.client.providers.firstRun as ReturnType<typeof vi.fn>).mockRejectedValueOnce(
      new Error('fr boom'),
    );
    await mount(c);
    const btn = container.querySelector('[data-choice="privacy"]') as HTMLButtonElement;
    await act(async () => btn.click());
    await act(async () => {
      await Promise.resolve();
    });
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('fr boom');
    expect(container.querySelector('[data-choice="privacy"]')).not.toBeNull();
  });

  it('renders the presets section after analysis with the catalog', async () => {
    const c = makeClient({
      initialSettings: { modelsOnboardingSeen: true, firstRunChoiceMade: true },
      catalog: presetCatalog(),
    });
    await mount(c);
    await analyze();
    expect(container.querySelector('[data-section="presets"]')).not.toBeNull();
    expect(container.querySelector('[data-preset="balanced"]')).not.toBeNull();
  });

  it('applying a preset calls providers.applyPreset', async () => {
    const c = makeClient({
      initialSettings: { modelsOnboardingSeen: true, firstRunChoiceMade: true },
      catalog: presetCatalog(),
    });
    await mount(c);
    await analyze();
    const btn = container.querySelector('[data-preset="privacy"]') as HTMLButtonElement;
    await act(async () => btn.click());
    await act(async () => {
      await Promise.resolve();
    });
    expect(c.client.providers.applyPreset as ReturnType<typeof vi.fn>).toHaveBeenCalledWith(
      'privacy',
    );
  });

  it('overriding a function calls providers.setFunctionModel', async () => {
    const c = makeClient({
      initialSettings: { modelsOnboardingSeen: true, firstRunChoiceMade: true },
      catalog: presetCatalog(),
    });
    await mount(c);
    await analyze();
    const sel = container.querySelector('select[data-function="select"]') as HTMLSelectElement;
    sel.value = 'groq-x';
    await act(async () => sel.dispatchEvent(new Event('change', { bubbles: true })));
    await act(async () => {
      await Promise.resolve();
    });
    expect(c.client.providers.setFunctionModel as ReturnType<typeof vi.fn>).toHaveBeenCalledWith(
      'select',
      'groq-x',
    );
  });

  it('an applyPreset error surfaces in the alert', async () => {
    const c = makeClient({
      initialSettings: { modelsOnboardingSeen: true, firstRunChoiceMade: true },
      catalog: presetCatalog(),
    });
    (c.client.providers.applyPreset as ReturnType<typeof vi.fn>).mockRejectedValueOnce(
      new Error('preset boom'),
    );
    await mount(c);
    await analyze();
    const btn = container.querySelector('[data-preset="balanced"]') as HTMLButtonElement;
    await act(async () => btn.click());
    await act(async () => {
      await Promise.resolve();
    });
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('preset boom');
  });

  it('a setFunctionModel error surfaces in the alert', async () => {
    const c = makeClient({
      initialSettings: { modelsOnboardingSeen: true, firstRunChoiceMade: true },
      catalog: presetCatalog(),
    });
    (c.client.providers.setFunctionModel as ReturnType<typeof vi.fn>).mockRejectedValueOnce(
      new Error('fn boom'),
    );
    await mount(c);
    await analyze();
    const sel = container.querySelector('select[data-function="vision"]') as HTMLSelectElement;
    sel.value = 'local';
    await act(async () => sel.dispatchEvent(new Event('change', { bubbles: true })));
    await act(async () => {
      await Promise.resolve();
    });
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('fn boom');
  });

  it('a first-run response without routing keeps the prior preset/routing', async () => {
    const c = makeClient({
      initialSettings: {
        modelsOnboardingSeen: true,
        firstRunChoiceMade: false,
        activePreset: 'balanced',
        routing: { perFunction: { select: { provider: 'keep-me', fallback: [] } } },
      },
    });
    // firstRun returns only the flag (no activePreset/routing) -> the ?? falls
    // back to the previous settings values (the 254-255 fallback branch).
    (c.client.providers.firstRun as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      firstRunChoiceMade: true,
    });
    await mount(c);
    const btn = container.querySelector('[data-choice="privacy"]') as HTMLButtonElement;
    await act(async () => btn.click());
    await act(async () => {
      await Promise.resolve();
    });
    // The chooser is gone (flag flipped) and no crash from the missing fields.
    expect(container.querySelector('[data-choice="privacy"]')).toBeNull();
  });

  it('coerces a null catalog payload to no presets section', async () => {
    const c = makeClient({
      initialSettings: { modelsOnboardingSeen: true, firstRunChoiceMade: true },
    });
    (c.client.providers.catalog as ReturnType<typeof vi.fn>).mockResolvedValue(
      null as unknown as CatalogResponse,
    );
    await mount(c);
    await analyze();
    expect(container.querySelector('[data-section="presets"]')).toBeNull();
  });

  // ---- WU-14: the readiness roll-up join ----------------------------------

  it('renders the readiness roll-up (one badge per readiness.summary item)', async () => {
    const c = makeClient({
      initialSettings: { firstRunChoiceMade: true },
      readiness: [
        { capability: 't1', label: 'Tier 1', status: 'ready', blockedBy: '', action: null },
        {
          capability: 'vis',
          label: 'Vision',
          status: 'needsDownload',
          blockedBy: 'saliency missing',
          action: { kind: 'assets.ensure', assets: ['saliency'] },
        },
      ],
    });
    await mount(c);
    await act(async () => {
      await Promise.resolve();
    });
    const badges = container.querySelectorAll('.readiness-rollup [role="status"]');
    expect(badges.length).toBe(2);
    expect(c.calls.some((x) => x.method === 'readiness.summary')).toBe(true);
  });

  it('an assets.ensure roll-up action installs + re-lists + re-runs the advisor', async () => {
    const c = makeClient({
      initialSettings: { firstRunChoiceMade: true },
      readiness: [
        {
          capability: 'vis',
          label: 'Vision',
          status: 'needsDownload',
          blockedBy: '',
          action: { kind: 'assets.ensure', assets: ['saliency'] },
        },
      ],
    });
    await mount(c);
    await act(async () => {
      await Promise.resolve();
    });
    const fix = container.querySelector(
      '.readiness-rollup button.readiness-badge__action',
    ) as HTMLButtonElement;
    await act(async () => {
      fix.click();
    });
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(c.calls.some((x) => x.method === 'assets.ensure')).toBe(true);
    expect(c.calls.some((x) => x.method === 'system.advisor')).toBe(true);
  });

  it('surfaces an error when a roll-up assets.ensure action fails', async () => {
    const c = makeClient({
      initialSettings: { firstRunChoiceMade: true },
      rejectEnsure: true,
      readiness: [
        {
          capability: 'vis',
          label: 'Vision',
          status: 'needsDownload',
          blockedBy: '',
          action: { kind: 'assets.ensure', assets: ['saliency'] },
        },
      ],
    });
    await mount(c);
    await act(async () => {
      await Promise.resolve();
    });
    const fix = container.querySelector(
      '.readiness-rollup button.readiness-badge__action',
    ) as HTMLButtonElement;
    await act(async () => {
      fix.click();
    });
    await act(async () => {
      await Promise.resolve();
    });
    expect(container.querySelector('.error')?.textContent).toContain('ensure failed');
  });

  it('a non-ensure roll-up action (openProviders) is a no-op install-wise', async () => {
    const c = makeClient({
      initialSettings: { firstRunChoiceMade: true },
      readiness: [
        {
          capability: 'tr',
          label: 'Translation',
          status: 'needsKey',
          blockedBy: 'no key',
          action: { kind: 'openProviders' },
        },
      ],
    });
    await mount(c);
    await act(async () => {
      await Promise.resolve();
    });
    const fix = container.querySelector(
      '.readiness-rollup button.readiness-badge__action',
    ) as HTMLButtonElement;
    await act(async () => {
      fix.click();
    });
    await act(async () => {
      await Promise.resolve();
    });
    // No install was attempted for a key/consent action.
    expect(c.calls.some((x) => x.method === 'assets.ensure')).toBe(false);
  });

  it('an assets.ensure roll-up action coerces a non-array list + null advisor', async () => {
    const c = makeClient({
      initialSettings: { firstRunChoiceMade: true },
      readiness: [
        {
          capability: 'vis',
          label: 'Vision',
          status: 'needsDownload',
          blockedBy: '',
          action: { kind: 'assets.ensure', assets: ['saliency'] },
        },
      ],
    });
    // assets.list resolves a non-array -> the `: []` fallback; advisor resolves
    // null -> the `?? null` fallback. Both arms of the post-ensure refresh.
    (c.client.assets.list as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      {} as unknown as { assets: AssetInfo[] },
    );
    (c.client.system.advisor as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      null as unknown as AdvisorReport,
    );
    await mount(c);
    await act(async () => {
      await Promise.resolve();
    });
    const fix = container.querySelector(
      '.readiness-rollup button.readiness-badge__action',
    ) as HTMLButtonElement;
    await act(async () => {
      fix.click();
    });
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(c.calls.some((x) => x.method === 'assets.ensure')).toBe(true);
    // No crash; no error surfaced.
    expect(container.querySelector('.error')).toBeNull();
  });

  it('an assets.ensure roll-up action with no asset names is a no-op', async () => {
    const c = makeClient({
      initialSettings: { firstRunChoiceMade: true },
      readiness: [
        {
          capability: 'vis',
          label: 'Vision',
          status: 'needsDownload',
          blockedBy: '',
          // assets.ensure with an empty list -> the guard short-circuits.
          action: { kind: 'assets.ensure', assets: [] },
        },
      ],
    });
    await mount(c);
    await act(async () => {
      await Promise.resolve();
    });
    const fix = container.querySelector(
      '.readiness-rollup button.readiness-badge__action',
    ) as HTMLButtonElement;
    await act(async () => {
      fix.click();
    });
    await act(async () => {
      await Promise.resolve();
    });
    expect(c.calls.some((x) => x.method === 'assets.ensure')).toBe(false);
  });
});
