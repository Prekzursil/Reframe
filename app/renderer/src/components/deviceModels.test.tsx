// deviceModels.test.tsx — render + helper tests for the WU-models/device building
// blocks: DeviceStatusStrip / DeviceModelReco / LocalRunners / OpenRouterUsage.

// @vitest-environment jsdom
import React from 'react';
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import { DeviceStatusStrip, deviceChips, formatEta } from './DeviceStatusStrip';
import { DeviceModelReco } from './DeviceModelReco';
import { LocalRunners } from './LocalRunners';
import { OpenRouterUsage, formatUsd } from './OpenRouterUsage';
import type { HardwareInfo, ModelReco, OpenRouterUsageRow, RunnerAdvice } from '../lib/rpc';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

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
});

async function render(node: React.ReactElement): Promise<void> {
  await act(async () => {
    root.render(node);
  });
}

const hw: HardwareInfo = {
  vramMb: 6000,
  ramMb: 32000,
  cpuCount: 16,
  gpuPresent: true,
  diskFreeMb: 250000,
};

// --------------------------------------------------------------------------- //
// DeviceStatusStrip
// --------------------------------------------------------------------------- //
describe('formatEta', () => {
  it('formats seconds as m:ss', () => {
    expect(formatEta(90)).toBe('1:30');
    expect(formatEta(0)).toBe('0:00');
    expect(formatEta(605)).toBe('10:05');
  });
  it('returns — for null / undefined / negative / non-finite', () => {
    expect(formatEta(null)).toBe('—');
    expect(formatEta(undefined)).toBe('—');
    expect(formatEta(-5)).toBe('—');
    expect(formatEta(Number.POSITIVE_INFINITY)).toBe('—');
  });
});

describe('deviceChips', () => {
  it('builds disk/ram/vram/gpu/eta chips from hardware + eta', () => {
    const chips = deviceChips(hw, 120);
    const byKey = Object.fromEntries(chips.map((c) => [c.key, c.value]));
    expect(byKey.gpu).toBe('yes');
    expect(byKey.eta).toBe('2:00');
    expect(byKey.disk).not.toBe('—'); // 250000 MB -> a GB string
  });
  it('degrades unknown fields to — and gpu none', () => {
    const blank: HardwareInfo = {
      vramMb: null,
      ramMb: null,
      cpuCount: null,
      gpuPresent: false,
    };
    const byKey = Object.fromEntries(deviceChips(blank, null).map((c) => [c.key, c.value]));
    expect(byKey.disk).toBe('—'); // diskFreeMb absent
    expect(byKey.vram).toBe('—');
    expect(byKey.gpu).toBe('none');
    expect(byKey.eta).toBe('—');
  });
  it('reads RAM as "unknown" (never "undefined MB") when the probe found nothing', () => {
    // F3: Windows RAM probe -> null on an undetectable host. The RAM chip must
    // degrade to a readable "unknown", distinct from the em dash used elsewhere.
    const noRam: HardwareInfo = {
      vramMb: 6000,
      ramMb: null,
      cpuCount: 8,
      gpuPresent: true,
      diskFreeMb: 250000,
    };
    const byKey = Object.fromEntries(deviceChips(noRam, 30).map((c) => [c.key, c.value]));
    expect(byKey.ram).toBe('unknown');
    expect(byKey.ram).not.toContain('undefined');
  });
});

describe('<DeviceStatusStrip />', () => {
  it('renders all five chips with values', async () => {
    await render(<DeviceStatusStrip hardware={hw} etaSeconds={45} />);
    const strip = container.querySelector('[data-section="device-strip"]') as HTMLElement;
    expect(strip).not.toBeNull();
    expect(strip.querySelector('[data-chip="disk"]')).not.toBeNull();
    expect(strip.querySelector('[data-chip="eta"]')?.textContent).toContain('0:45');
    expect(strip.querySelector('[data-chip="gpu"]')?.textContent).toContain('yes');
  });
});

// --------------------------------------------------------------------------- //
// DeviceModelReco
// --------------------------------------------------------------------------- //
describe('<DeviceModelReco />', () => {
  it('renders the whisper + LLM picks with their device reasons', async () => {
    const whisper: ModelReco = {
      model: 'large-v3-turbo',
      label: 'Whisper large-v3-turbo',
      reason: 'Whisper large-v3-turbo — fits your GPU (6000 MB VRAM)',
    };
    const llm: ModelReco = {
      model: 'qwen2.5:7b',
      label: 'Qwen2.5 7B',
      reason: 'Qwen2.5 7B — fits your GPU (6000 MB VRAM)',
    };
    await render(<DeviceModelReco whisper={whisper} llm={llm} />);
    const reco = container.querySelector('[data-section="device-reco"]') as HTMLElement;
    expect(reco.querySelector('[data-reco="whisper"] [data-field="model"]')?.textContent).toBe(
      'Whisper large-v3-turbo',
    );
    expect(reco.querySelector('[data-reco="llm"] [data-field="reason"]')?.textContent).toContain(
      '6000 MB VRAM',
    );
  });
});

// --------------------------------------------------------------------------- //
// LocalRunners
// --------------------------------------------------------------------------- //
function runner(over: Partial<RunnerAdvice> = {}): RunnerAdvice {
  return {
    kind: 'ollama',
    label: 'Ollama',
    present: true,
    baseUrl: 'http://127.0.0.1:11434/v1',
    installUrl: 'https://ollama.com/download',
    installHint: 'Ollama is running — no install needed.',
    installedModels: ['llama3.2'],
    recommendedModel: {
      model: 'qwen2.5:7b',
      label: 'Qwen2.5 7B',
      reason: 'Qwen2.5 7B — fits your GPU (6000 MB VRAM)',
      pull: 'ollama pull qwen2.5:7b',
    },
    ...over,
  };
}

describe('<LocalRunners />', () => {
  it('renders a running runner with installed models + a copy-able pull hint', async () => {
    const writes: string[] = [];
    const writeClipboard = (t: string): Promise<void> => {
      writes.push(t);
      return Promise.resolve();
    };
    await render(<LocalRunners runners={[runner()]} writeClipboard={writeClipboard} />);
    const card = container.querySelector('[data-runner="ollama"]') as HTMLElement;
    expect(card.getAttribute('data-present')).toBe('true');
    expect(card.querySelector('[data-field="installed"]')?.textContent).toContain('llama3.2');
    expect(card.querySelector('[data-field="pull"]')?.textContent).toBe('ollama pull qwen2.5:7b');
    const copy = card.querySelector('[data-action="copy-pull"]') as HTMLButtonElement;
    await act(async () => copy.click());
    await act(async () => {
      await Promise.resolve();
    });
    expect(writes).toEqual(['ollama pull qwen2.5:7b']);
    expect(copy.textContent).toBe('Copied');
  });

  it('omits the installed line when no models are installed', async () => {
    await render(
      <LocalRunners
        runners={[runner({ installedModels: [] })]}
        writeClipboard={() => Promise.resolve()}
      />,
    );
    expect(container.querySelector('[data-field="installed"]')).toBeNull();
  });

  it('keeps the button un-copied when the clipboard write rejects', async () => {
    const writeClipboard = (): Promise<void> => Promise.reject(new Error('denied'));
    await render(<LocalRunners runners={[runner()]} writeClipboard={writeClipboard} />);
    const copy = container.querySelector('[data-action="copy-pull"]') as HTMLButtonElement;
    await act(async () => copy.click());
    await act(async () => {
      await Promise.resolve();
    });
    expect(copy.textContent).toBe('Copy'); // copy failed -> never flips to "Copied"
  });

  it('renders an absent runner with an install hint + official link (no auto-install)', async () => {
    const absent = runner({
      kind: 'lmstudio',
      label: 'LM Studio',
      present: false,
      installUrl: 'https://lmstudio.ai',
      installHint:
        'LM Studio is not running. Install it from https://lmstudio.ai (we never auto-install).',
      installedModels: [],
    });
    await render(<LocalRunners runners={[absent]} writeClipboard={() => Promise.resolve()} />);
    const card = container.querySelector('[data-runner="lmstudio"]') as HTMLElement;
    expect(card.getAttribute('data-present')).toBe('false');
    const link = card.querySelector('[data-action="install-link"]') as HTMLAnchorElement;
    expect(link.getAttribute('href')).toBe('https://lmstudio.ai');
    expect(card.querySelector('[data-field="install-hint"]')?.textContent).toContain(
      'never auto-install',
    );
  });
});

// --------------------------------------------------------------------------- //
// OpenRouterUsage
// --------------------------------------------------------------------------- //
describe('formatUsd', () => {
  it('formats / degrades USD amounts', () => {
    expect(formatUsd(1.5)).toBe('$1.50');
    expect(formatUsd(0)).toBe('$0.00');
    expect(formatUsd(null)).toBe('—');
    expect(formatUsd(undefined)).toBe('—');
    expect(formatUsd(Number.NaN)).toBe('—');
  });
});

describe('<OpenRouterUsage />', () => {
  it('shows an empty hint when there are no rows', async () => {
    await render(<OpenRouterUsage rows={[]} />);
    expect(container.querySelector('[data-openrouter="empty"]')).not.toBeNull();
  });

  it('renders a paid-tier row with cost + remaining/limit', async () => {
    const rows: OpenRouterUsageRow[] = [
      {
        provider: 'OpenRouter',
        key: '…WXYZ',
        costUsd: 1.5,
        limitUsd: 10,
        remainingUsd: 8.5,
        isFreeTier: false,
      },
    ];
    await render(<OpenRouterUsage rows={rows} />);
    const row = container.querySelector('.openrouter-usage__row') as HTMLElement;
    expect(row.querySelector('[data-field="cost"]')?.textContent).toContain('$1.50');
    expect(row.querySelector('[data-field="remaining"]')?.textContent).toContain(
      '$8.50 of $10.00 left',
    );
    expect(row.querySelector('[data-field="free-tier"]')).toBeNull();
  });

  it('renders a free-tier row with no credit limit', async () => {
    const rows: OpenRouterUsageRow[] = [
      {
        provider: 'OpenRouter',
        key: '…AAAA',
        costUsd: 0,
        limitUsd: null,
        remainingUsd: null,
        isFreeTier: true,
      },
    ];
    await render(<OpenRouterUsage rows={rows} />);
    const row = container.querySelector('.openrouter-usage__row') as HTMLElement;
    expect(row.querySelector('[data-field="remaining"]')?.textContent).toBe('no credit limit');
    expect(row.querySelector('[data-field="free-tier"]')).not.toBeNull();
  });
});
