// ModelsSystemPanel.test.tsx — the "Models & System" panel: opt-in analysis,
// hardware bars, recommended preset, tier selection, model download gating,
// notes, ASR/diarize selectors, and the first-run onboarding overlay.

// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import {
  ModelsSystemPanel,
  applyOutcomeText,
  errText,
  indexAssets,
  isInstalled,
  qualityFraction,
  recommendationAlreadyOptimal,
  recommendationUnavailable,
  sizeForComponent,
} from './ModelsSystemPanel';
import type {
  AdvisorReport,
  AssetInfo,
  CatalogResponse,
  ComponentStatus,
  HardwareInfo,
  ReadinessItem,
  Recommendation,
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

// WU-B3 — a full actionable recommendation (preset + folded local-server delta +
// ASR pick + one proposed download + rationale). The `select` slot diverges from
// the applyPreset base ('groq-x' below) so Apply must persist that one delta.
function recommendation(): Recommendation {
  return {
    preset: 'balanced',
    routing: {
      perFunction: {
        select: { provider: 'local-ollama', fallback: ['local'] },
        caption: { provider: 'groq-x', fallback: ['local'] },
      },
    },
    asrEngine: 'parakeet',
    downloads: [
      { assetName: 'smolvlm2-2.2b', label: 'SmolVLM2 2.2B', sizeMb: 4500, reason: 'runnable' },
    ],
    rationale: [
      "Recommended preset 'balanced' based on this device's advisor report.",
      "Detected local server 'local-ollama' — routing select to it (no cloud egress).",
    ],
  };
}

/** The G-B1 typed fallback: empty routing -> the card's "unavailable" state. */
function unavailableRecommendation(): Recommendation {
  return {
    preset: 'privacy',
    routing: { perFunction: {} },
    asrEngine: null,
    downloads: [],
    rationale: ['Could not detect this device’s capabilities — no recommendation available yet.'],
  };
}

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
    recommendation?: Recommendation;
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
      recommend: vi.fn(async (opts?: { commercial?: boolean }) => {
        calls.push({ method: 'system.recommend', args: [opts] });
        return { recommendation: over.recommendation ?? recommendation() };
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
        // Base routing for the preset BEFORE the recommender's local-server fold:
        // `select` resolves to a cloud provider (so the rec's `local-ollama` is a
        // delta Apply must persist) while `caption` already matches the rec.
        const routing = {
          perFunction: {
            select: { provider: 'groq-x', fallback: ['local'] },
            caption: { provider: 'groq-x', fallback: ['local'] },
          },
        };
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

async function mount(c: FakeClient, onOpenProviders?: () => void): Promise<void> {
  await act(async () => {
    root.render(<ModelsSystemPanel rpcClient={c.client} onOpenProviders={onOpenProviders} />);
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

  // ---- progressive disclosure: key controls work BEFORE analysis ----------
  it('the empty-state prompt offers an Analyze call-to-action button', async () => {
    const c = makeClient();
    await mount(c);
    const prompt = container.querySelector('[data-section="prompt"]') as HTMLElement;
    expect(prompt).not.toBeNull();
    const cta = prompt.querySelector('button[data-action="analyze-cta"]') as HTMLButtonElement;
    expect(cta).not.toBeNull();
    // The CTA drives the same opt-in analysis as the header button.
    await act(async () => cta.click());
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(container.querySelector('[data-section="hardware"]')).not.toBeNull();
  });

  it('renders the AI presets + speech controls BEFORE analysis (cheap data on mount)', async () => {
    const c = makeClient({
      initialSettings: { modelsOnboardingSeen: true, firstRunChoiceMade: true },
      catalog: presetCatalog(),
    });
    await mount(c);
    // No analysis yet, but the probe-independent controls are present + usable.
    expect(container.querySelector('[data-section="hardware"]')).toBeNull();
    expect(container.querySelector('[data-section="presets"]')).not.toBeNull();
    expect(container.querySelector('[data-preset="balanced"]')).not.toBeNull();
    expect(container.querySelector('select[data-action="asr-engine"]')).not.toBeNull();
    expect(container.querySelector('[data-section="usage"]')).not.toBeNull();
    // The cheap reads ran on mount without the user opting into the probe.
    expect(c.calls.some((x) => x.method === 'providers.catalog')).toBe(true);
    expect(c.calls.some((x) => x.method === 'asr.engines')).toBe(true);
    expect(c.calls.some((x) => x.method === 'providers.usage')).toBe(true);
    expect(c.calls.some((x) => x.method === 'system.probe')).toBe(false);
  });

  it('applies a preset BEFORE analysis (key control is not gated)', async () => {
    const c = makeClient({
      initialSettings: { modelsOnboardingSeen: true, firstRunChoiceMade: true },
      catalog: presetCatalog(),
    });
    await mount(c);
    const btn = container.querySelector('[data-preset="privacy"]') as HTMLButtonElement;
    await act(async () => btn.click());
    await act(async () => {
      await Promise.resolve();
    });
    expect(c.client.providers.applyPreset as ReturnType<typeof vi.fn>).toHaveBeenCalledWith(
      'privacy',
    );
  });

  it('tolerates a rejected cheap mount load without blocking the panel', async () => {
    const c = makeClient({ initialSettings: { modelsOnboardingSeen: true } });
    (c.client.providers.catalog as ReturnType<typeof vi.fn>).mockRejectedValueOnce(
      new Error('catalog offline'),
    );
    (c.client.asr.engines as ReturnType<typeof vi.fn>).mockRejectedValueOnce(
      new Error('engines offline'),
    );
    (c.client.providers.usage as ReturnType<typeof vi.fn>).mockRejectedValueOnce(
      new Error('usage offline'),
    );
    await mount(c);
    // A failed cheap read degrades quietly: the opt-in prompt still renders and
    // nothing is thrown into the alert region.
    expect(container.querySelector('[data-section="prompt"]')).not.toBeNull();
    expect(container.querySelector('[role="alert"]')).toBeNull();
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

  it('model rows read exactly one unambiguous state (Installed / Download (size) / Downloading)', async () => {
    const c = makeClient({ initialSettings: { modelsOnboardingSeen: true } });
    await mount(c);
    await analyze();

    // smolvlm2: not installed, asset 4500 MB -> "Download (4.4 GB)" + the size.
    const smolCard = container.querySelector('.model-card[data-model="smolvlm2"]') as HTMLElement;
    const smolBtn = smolCard.querySelector('button[data-action="download"]') as HTMLButtonElement;
    expect(smolBtn.textContent).toContain('Download');
    expect(smolBtn.textContent).toContain('4.4 GB');
    expect(smolBtn.disabled).toBe(false);
    // No installed-check icon on a not-installed row.
    expect(smolCard.querySelector('svg[data-icon="installed"]')).toBeNull();

    // vlm_backbone: installed (siglip) -> "Installed", disabled, with an SVG check
    // (no emoji glyph used as an icon).
    const vlmCard = container.querySelector('.model-card[data-model="vlm_backbone"]') as HTMLElement;
    const vlmBtn = vlmCard.querySelector('button[data-action="download"]') as HTMLButtonElement;
    expect(vlmBtn.textContent).toContain('Installed');
    expect(vlmBtn.disabled).toBe(true);
    expect(vlmCard.querySelector('svg[data-icon="installed"]')).not.toBeNull();

    // motion: a CPU floor (no asset) -> "Installed" (nothing to download).
    const motionCard = container.querySelector('.model-card[data-model="motion"]') as HTMLElement;
    const motionBtn = motionCard.querySelector(
      'button[data-action="download"]',
    ) as HTMLButtonElement;
    expect(motionBtn.textContent).toContain('Installed');
    expect(motionBtn.disabled).toBe(true);
  });

  it('a model row shows the Downloading… state while its download is in flight', async () => {
    const c = makeClient({ initialSettings: { modelsOnboardingSeen: true } });
    // Hold assets.ensure open so the row stays in the downloading state.
    let release: (() => void) | undefined;
    (c.client.assets.ensure as ReturnType<typeof vi.fn>).mockImplementationOnce(
      () =>
        new Promise<{ jobId: string }>((resolve) => {
          release = () => resolve({ jobId: 'job-x' });
        }),
    );
    await mount(c);
    await analyze();
    const smolCard = container.querySelector('.model-card[data-model="smolvlm2"]') as HTMLElement;
    const btn = smolCard.querySelector('button[data-action="download"]') as HTMLButtonElement;
    await act(async () => btn.click());
    expect(btn.textContent).toContain('Downloading…');
    expect(btn.disabled).toBe(true);
    // Let the download settle so the test tears down cleanly.
    await act(async () => {
      release?.();
      await Promise.resolve();
      await Promise.resolve();
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

  it('the selected tier carries an unmistakable Selected badge + aria-current', async () => {
    const c = makeClient({ initialSettings: { modelsOnboardingSeen: true, phase8Tier: 2 } });
    await mount(c);
    await analyze();
    const selected = container.querySelector('.tier-card[data-tier="2"]') as HTMLElement;
    const unselected = container.querySelector('.tier-card[data-tier="0"]') as HTMLElement;
    // Selection is conveyed by a visible badge AND aria-current (not color alone).
    expect(selected.getAttribute('aria-current')).toBe('true');
    expect(selected.querySelector('.tier-card__selected')).not.toBeNull();
    expect(unselected.getAttribute('aria-current')).toBeNull();
    expect(unselected.querySelector('.tier-card__selected')).toBeNull();
  });

  it('the active AI preset shows an Active badge + aria-pressed (selection clarity)', async () => {
    const c = makeClient({
      initialSettings: {
        modelsOnboardingSeen: true,
        firstRunChoiceMade: true,
        activePreset: 'balanced',
      },
      catalog: presetCatalog(),
    });
    await mount(c);
    const active = container.querySelector('[data-preset="balanced"]') as HTMLButtonElement;
    const inactive = container.querySelector('[data-preset="privacy"]') as HTMLButtonElement;
    expect(active.getAttribute('aria-pressed')).toBe('true');
    expect(active.querySelector('.preset-picker__active')).not.toBeNull();
    expect(inactive.getAttribute('aria-pressed')).toBe('false');
    expect(inactive.querySelector('.preset-picker__active')).toBeNull();
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
    // asr.engines is read TWICE (cheap mount load + analyze); use a persistent
    // mock so the analyze path's `Array.isArray(engineRes?.engines)` false-arm is
    // exercised (a single Once would be consumed by the mount load first).
    (c.client.asr.engines as ReturnType<typeof vi.fn>).mockResolvedValue({
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

  it('WU-PROVIDERS: a key/consent roll-up action navigates via onOpenProviders', async () => {
    const onOpenProviders = vi.fn();
    const c = makeClient({
      initialSettings: { firstRunChoiceMade: true },
      readiness: [
        {
          capability: 'tr',
          label: 'Translation',
          status: 'needsKey',
          blockedBy: 'no key',
          action: { kind: 'openProviders', provider: 'Groq' },
        },
      ],
    });
    await mount(c, onOpenProviders);
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
    expect(onOpenProviders).toHaveBeenCalledTimes(1);
    // Navigation only — no install attempted.
    expect(c.calls.some((x) => x.method === 'assets.ensure')).toBe(false);
  });

  it('WU-PROVIDERS: a setConsent roll-up action also navigates via onOpenProviders', async () => {
    const onOpenProviders = vi.fn();
    const c = makeClient({
      initialSettings: { firstRunChoiceMade: true },
      readiness: [
        {
          capability: 'tr',
          label: 'Translation',
          status: 'needsConsent',
          blockedBy: 'consent needed',
          action: { kind: 'setConsent', provider: 'Groq' },
        },
      ],
    });
    await mount(c, onOpenProviders);
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
    expect(onOpenProviders).toHaveBeenCalledTimes(1);
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

// ---- WU-B3: device-aware recommendation card + Apply flow ------------------

describe('WU-B3 recommendation pure helpers', () => {
  it('recommendationUnavailable is true iff routing.perFunction is empty', () => {
    expect(recommendationUnavailable(unavailableRecommendation())).toBe(true);
    expect(recommendationUnavailable(recommendation())).toBe(false);
  });

  it('recommendationAlreadyOptimal covers every gating arm', () => {
    const rec = recommendation();
    // the current routing that ALREADY matches the recommendation's per-function plan
    const matchRouting = {
      perFunction: {
        select: { provider: 'local-ollama', fallback: ['local'] },
        caption: { provider: 'groq-x', fallback: ['local'] },
      },
    };
    // different preset -> not optimal
    expect(recommendationAlreadyOptimal(rec, 'privacy', 'parakeet', matchRouting)).toBe(false);
    // same preset but pending downloads -> not optimal
    expect(recommendationAlreadyOptimal(rec, 'balanced', 'parakeet', matchRouting)).toBe(false);
    // same preset, no downloads, but ASR engine differs -> not optimal
    const noDl = { ...rec, downloads: [] };
    expect(recommendationAlreadyOptimal(noDl, 'balanced', 'whisper', matchRouting)).toBe(false);
    // same preset, no downloads, ASR matches, routing matches -> optimal
    expect(recommendationAlreadyOptimal(noDl, 'balanced', 'parakeet', matchRouting)).toBe(true);
    // same preset, no downloads, recommendation proposes NO ASR -> optimal regardless of ASR
    const noAsr = { ...rec, downloads: [], asrEngine: null };
    expect(recommendationAlreadyOptimal(noAsr, 'balanced', undefined, matchRouting)).toBe(true);
    // preset+ASR match and no downloads, but a per-function ROUTING delta remains
    // (the folded detected-local-server route like select -> local-ollama) -> NOT
    // optimal, so Apply stays enabled and the local-routing recommendation can be applied.
    const routingDiverges = {
      perFunction: {
        select: { provider: 'groq-x', fallback: ['local'] }, // recommends local-ollama, current is cloud
        caption: { provider: 'groq-x', fallback: ['local'] },
      },
    };
    expect(recommendationAlreadyOptimal(noDl, 'balanced', 'parakeet', routingDiverges)).toBe(false);
    // a slot the recommendation routes but current routing lacks entirely -> NOT optimal
    expect(recommendationAlreadyOptimal(noDl, 'balanced', 'parakeet', { perFunction: {} })).toBe(
      false,
    );
    // missing current routing block entirely (undefined) -> NOT optimal when rec routes slots
    expect(recommendationAlreadyOptimal(noDl, 'balanced', 'parakeet', undefined)).toBe(false);
  });

  it('applyOutcomeText summarises preset, ASR, and download counts', () => {
    expect(applyOutcomeText(recommendation())).toBe(
      'Applied: preset balanced, ASR → parakeet, 1 download started.',
    );
    // plural downloads + no ASR
    const many: Recommendation = {
      ...recommendation(),
      asrEngine: null,
      downloads: [
        { assetName: 'a', label: 'A', sizeMb: 1, reason: 'r' },
        { assetName: 'b', label: 'B', sizeMb: 2, reason: 'r' },
      ],
    };
    expect(applyOutcomeText(many)).toBe('Applied: preset balanced, 2 downloads started.');
    // no ASR, no downloads -> just the preset
    const bare: Recommendation = { ...recommendation(), asrEngine: null, downloads: [] };
    expect(applyOutcomeText(bare)).toBe('Applied: preset balanced.');
  });
});

describe('<ModelsSystemPanel /> WU-B3 card', () => {
  const optedIn = { modelsOnboardingSeen: true, firstRunChoiceMade: true };

  it('renders the card by its accessible heading + rationale list + plan rows', async () => {
    const c = makeClient({ initialSettings: optedIn });
    await mount(c);
    await analyze();
    const card = container.querySelector('[data-section="recommend"]') as HTMLElement;
    expect(card).not.toBeNull();
    // queryable by its accessible heading
    const heading = container.querySelector('#recommend-card-heading') as HTMLElement;
    expect(card.getAttribute('aria-labelledby')).toBe('recommend-card-heading');
    expect(heading.textContent).toContain('Recommended setup for your machine');
    // rationale renders as list items, count == rationale length
    const items = card.querySelectorAll('[data-section="recommend-rationale"] li');
    expect(items.length).toBe(recommendation().rationale.length);
    // plan rows surface preset + ASR + downloads as labelled fields
    expect(card.querySelector('[data-field="preset"]')).not.toBeNull();
    expect(card.querySelector('[data-field="asr"]')?.textContent).toBe('parakeet');
    expect(card.querySelector('[data-field="downloads"]')?.textContent).toContain('SmolVLM2');
    // recommend RPC was called with the commercial flag
    expect(c.calls.find((x) => x.method === 'system.recommend')?.args[0]).toEqual({
      commercial: false,
    });
  });

  it('the loading live region announces while analysis is in flight', async () => {
    const c = makeClient({ initialSettings: optedIn });
    let release: () => void = () => {};
    (c.client.system.probe as ReturnType<typeof vi.fn>).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          release = () => resolve({ vramMb: 6000, ramMb: 32000, cpuCount: 16, gpuPresent: true });
        }),
    );
    await mount(c);
    const btn = container.querySelector('button[data-action="analyze"]') as HTMLButtonElement;
    await act(async () => btn.click());
    const loading = container.querySelector('[data-section="recommend-loading"]') as HTMLElement;
    expect(loading).not.toBeNull();
    expect(loading.getAttribute('aria-live')).toBe('polite');
    expect(loading.textContent).toContain('Analysing your machine');
    await act(async () => {
      release();
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(container.querySelector('[data-section="recommend-loading"]')).toBeNull();
  });

  it('Apply issues applyPreset + exactly the diverging setFunctionModel + ASR + one ensure', async () => {
    const c = makeClient({ initialSettings: optedIn });
    await mount(c);
    await analyze();
    const apply = container.querySelector(
      'button[data-action="apply-recommendation"]',
    ) as HTMLButtonElement;
    expect(apply.getAttribute('aria-label')).toBe('Apply recommended settings');
    await act(async () => apply.click());
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });
    // base preset applied
    expect(
      c.calls.filter((x) => x.method === 'providers.applyPreset').map((x) => x.args[0]),
    ).toEqual(['balanced']);
    // ONLY the diverging `select` slot persisted (caption already matched the base)
    const fnCalls = c.calls.filter((x) => x.method === 'providers.setFunctionModel');
    expect(fnCalls.length).toBe(1);
    expect(fnCalls[0].args).toEqual(['select', 'local-ollama']);
    // ASR engine persisted
    expect(
      c.calls.find(
        (x) => x.method === 'settings.set' && (x.args[0] as { asrEngine?: string }).asrEngine,
      ),
    ).toBeTruthy();
    // exactly one ensure with the proposed asset
    const ensures = c.calls.filter((x) => x.method === 'assets.ensure');
    expect(ensures.length).toBe(1);
    expect(ensures[0].args[0]).toEqual(['smolvlm2-2.2b']);
    // outcome announced in the polite live region
    const outcome = container.querySelector('[data-section="recommend-outcome"]') as HTMLElement;
    expect(outcome.getAttribute('aria-live')).toBe('polite');
    expect(outcome.textContent).toContain('Applied: preset balanced');
  });

  it('Apply with no ASR and no downloads only touches preset + deltas', async () => {
    const rec: Recommendation = {
      preset: 'balanced',
      routing: { perFunction: { select: { provider: 'groq-x', fallback: ['local'] } } },
      asrEngine: null,
      downloads: [],
      rationale: ['preset balanced'],
    };
    const c = makeClient({ initialSettings: optedIn, recommendation: rec });
    await mount(c);
    await analyze();
    const apply = container.querySelector(
      'button[data-action="apply-recommendation"]',
    ) as HTMLButtonElement;
    await act(async () => apply.click());
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    // select matches the base -> no setFunctionModel, no ensure, no asr settings.set
    expect(c.calls.filter((x) => x.method === 'providers.setFunctionModel').length).toBe(0);
    expect(c.calls.filter((x) => x.method === 'assets.ensure').length).toBe(0);
    expect(
      c.calls.filter(
        (x) => x.method === 'settings.set' && 'asrEngine' in (x.args[0] as Record<string, unknown>),
      ).length,
    ).toBe(0);
    expect(container.querySelector('[data-section="recommend-outcome"]')?.textContent).toContain(
      'Applied: preset balanced',
    );
  });

  it('shows aria-busy + disabled while Apply runs, then clears', async () => {
    const c = makeClient({ initialSettings: optedIn });
    let release: () => void = () => {};
    (c.client.providers.applyPreset as ReturnType<typeof vi.fn>).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          release = () =>
            resolve({
              activePreset: 'balanced',
              routing: { perFunction: { select: { provider: 'groq-x', fallback: ['local'] } } },
            });
        }),
    );
    await mount(c);
    await analyze();
    const apply = container.querySelector(
      'button[data-action="apply-recommendation"]',
    ) as HTMLButtonElement;
    await act(async () => apply.click());
    expect(apply.getAttribute('aria-busy')).toBe('true');
    expect(apply.disabled).toBe(true);
    expect(apply.textContent).toContain('Applying');
    await act(async () => {
      release();
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(apply.getAttribute('aria-busy')).toBe('false');
    expect(apply.disabled).toBe(false);
  });

  it('an Apply error surfaces in the alert and clears the busy state', async () => {
    const c = makeClient({ initialSettings: optedIn });
    (c.client.providers.applyPreset as ReturnType<typeof vi.fn>).mockRejectedValueOnce(
      new Error('apply boom'),
    );
    await mount(c);
    await analyze();
    const apply = container.querySelector(
      'button[data-action="apply-recommendation"]',
    ) as HTMLButtonElement;
    await act(async () => apply.click());
    await act(async () => {
      await Promise.resolve();
    });
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('apply boom');
    expect(apply.getAttribute('aria-busy')).toBe('false');
  });

  it('the unavailable recommendation renders the announced message, not a blank card', async () => {
    const c = makeClient({ initialSettings: optedIn, recommendation: unavailableRecommendation() });
    await mount(c);
    await analyze();
    const card = container.querySelector('[data-section="recommend"]') as HTMLElement;
    expect(card).not.toBeNull();
    const msg = container.querySelector('[data-section="recommend-unavailable"]') as HTMLElement;
    expect(msg).not.toBeNull();
    expect(msg.getAttribute('aria-live')).toBe('polite');
    expect(msg.textContent).toContain('Could not detect your hardware');
    // no plan / no Apply button in the unavailable state
    expect(container.querySelector('[data-section="recommend-plan"]')).toBeNull();
    expect(container.querySelector('button[data-action="apply-recommendation"]')).toBeNull();
  });

  it('already-optimal renders Apply disabled with the reason as its accessible name', async () => {
    const rec: Recommendation = {
      preset: 'balanced',
      routing: { perFunction: { select: { provider: 'local', fallback: [] } } },
      asrEngine: 'whisper',
      downloads: [],
      rationale: ['already optimal'],
    };
    const c = makeClient({
      initialSettings: {
        ...optedIn,
        activePreset: 'balanced',
        asrEngine: 'whisper',
        // current routing ALREADY matches the recommendation's per-function plan
        routing: { perFunction: { select: { provider: 'local', fallback: [] } } },
      },
      recommendation: rec,
    });
    await mount(c);
    await analyze();
    const apply = container.querySelector(
      'button[data-action="apply-recommendation"]',
    ) as HTMLButtonElement;
    expect(apply.disabled).toBe(true);
    expect(apply.getAttribute('aria-label')).toBe('Your settings already match the recommendation');
    // DISABLED clarity: a hover tooltip gives the WHY (not just the SR-only label).
    expect(apply.getAttribute('title')).toBe('Your settings already match the recommendation');
    expect(container.querySelector('[data-section="recommend-optimal"]')?.textContent).toContain(
      'already match',
    );
  });

  it('a routing-delta-only recommendation is NOT optimal: Apply stays enabled and applies the delta', async () => {
    // preset + ASR already match and no downloads, but the recommendation folds a
    // detected-local-server route (select -> local-ollama) the current routing lacks.
    // This is the headline Capability-B "no cloud egress" case: the card MUST let the
    // user apply it, not declare "already optimal".
    const rec: Recommendation = {
      preset: 'balanced',
      routing: { perFunction: { select: { provider: 'local-ollama', fallback: ['local'] } } },
      asrEngine: 'whisper',
      downloads: [],
      rationale: ["Detected local server 'local-ollama' — routing select to it (no cloud egress)."],
    };
    const c = makeClient({
      initialSettings: {
        ...optedIn,
        activePreset: 'balanced',
        asrEngine: 'whisper',
        // current routing sends select to a CLOUD provider -> a real routing delta
        routing: { perFunction: { select: { provider: 'groq-x', fallback: ['local'] } } },
      },
      recommendation: rec,
    });
    await mount(c);
    await analyze();
    const apply = container.querySelector(
      'button[data-action="apply-recommendation"]',
    ) as HTMLButtonElement;
    // NOT optimal: Apply enabled with the actionable accessible name
    expect(apply.disabled).toBe(false);
    expect(apply.getAttribute('aria-label')).toBe('Apply recommended settings');
    expect(container.querySelector('[data-section="recommend-optimal"]')).toBeNull();
    // clicking it persists exactly the local-ollama routing delta
    await act(async () => apply.click());
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });
    const fnCalls = c.calls.filter((x) => x.method === 'providers.setFunctionModel');
    expect(fnCalls.length).toBe(1);
    expect(fnCalls[0].args).toEqual(['select', 'local-ollama']);
  });

  it('no card renders when system.recommend yields a nullish recommendation', async () => {
    const c = makeClient({ initialSettings: optedIn });
    (c.client.system.recommend as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      {} as unknown as { recommendation: Recommendation },
    );
    await mount(c);
    await analyze();
    expect(container.querySelector('[data-section="recommend"]')).toBeNull();
    // the rest of the analyzed panel still renders (report present).
    expect(container.querySelector('[data-section="preset"]')).not.toBeNull();
  });
});
