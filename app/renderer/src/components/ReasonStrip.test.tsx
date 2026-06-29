// ReasonStrip.test.tsx — render tests for the M2 "using X because Y" reason strip
// + device card. The copy derivation is unit-tested in reasonStrip.test.ts; this
// pins the rendered structure (summary line, data-source flag, device-card facts).

// @vitest-environment jsdom
import React from 'react';
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import { ReasonStrip } from './ReasonStrip';
import type { Eligibility, HardwareInfo, ModelsOverview } from '../lib/rpc';

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

function overview(eligibility: Eligibility, hardware?: HardwareInfo): ModelsOverview {
  return {
    hardware: hardware ?? { vramMb: 8000, ramMb: 16000, cpuCount: 8, gpuPresent: true },
    tiers: [],
    recommendedPreset: 'tier1-multimodal',
    runners: [],
    localPlan: {
      whisper: { model: 'large-v3-turbo', label: 'Whisper large-v3-turbo', reason: 'w' },
      llm: { model: 'qwen2.5:7b', label: 'Qwen2.5 7B', reason: 'Qwen2.5 7B — fits your GPU' },
      runners: [],
    },
    providers: [],
    keyPool: [],
    routingPolicy: { global: 'local', overrides: {} },
    eligibility,
  };
}

const metadata: Eligibility = {
  source: 'metadata',
  models: [
    {
      model: 'qwen2.5:7b-instruct-q4_K_M',
      digest: 'D',
      sizeBytes: 4700,
      paramsB: 7.6,
      quantBits: 4,
      vramEstimateGb: 4.0,
      capabilities: ['completion'],
      aliases: [],
      fits: true,
    },
  ],
  fallback: { model: 'qwen2.5:1.5b', label: 'Qwen2.5 1.5B', reason: 'floor' },
};

const ladder: Eligibility = {
  source: 'ladder',
  models: [],
  fallback: { model: 'qwen2.5:1.5b', label: 'Qwen2.5 1.5B', reason: 'floor' },
};

describe('<ReasonStrip />', () => {
  it('renders the metadata summary + device-card facts with data-source="metadata"', async () => {
    await render(<ReasonStrip overview={overview(metadata)} />);
    const strip = container.querySelector('[data-section="reason-strip"]') as HTMLElement;
    expect(strip.getAttribute('data-source')).toBe('metadata');
    expect(strip.querySelector('[data-field="summary"]')?.textContent).toContain('7.6B-Q4');
    expect(strip.querySelector('[data-fact="vram-est"]')?.textContent).toContain('≈ 4.0 GB');
    expect(strip.querySelectorAll('.reason-strip__fact').length).toBe(6);
  });

  it('renders the ladder fallback with data-source="ladder" + null-RAM "unknown"', async () => {
    const ov = overview(ladder, { vramMb: null, ramMb: null, cpuCount: null, gpuPresent: false });
    await render(<ReasonStrip overview={ov} />);
    const strip = container.querySelector('[data-section="reason-strip"]') as HTMLElement;
    expect(strip.getAttribute('data-source')).toBe('ladder');
    expect(strip.querySelector('[data-fact="ram"]')?.textContent).toContain('unknown');
    expect(strip.querySelector('[data-fact="quant"]')?.textContent).toContain('—');
  });
});
