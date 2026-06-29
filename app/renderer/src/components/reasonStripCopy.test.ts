// reasonStripCopy.test.ts — exhaustive branch coverage for the M2 reason-strip
// pure helpers (quant/params/VRAM formatting, device-fit clause, the chosen-LLM
// reason resolution, and the device-card facts). No DOM: these are pure functions.
import { describe, it, expect } from 'vitest';
import type { HardwareInfo, ModelMeta, ModelsOverview } from '../lib/rpc';
import {
  chosenLlm,
  deviceFacts,
  deviceFitText,
  paramsLabel,
  quantLabel,
  reasonSummary,
  sizeQuantLabel,
  vramEstimateText,
} from './reasonStripCopy';

function hw(over: Partial<HardwareInfo> = {}): HardwareInfo {
  return { vramMb: 8000, ramMb: 16000, cpuCount: 8, gpuPresent: true, ...over };
}

function meta(over: Partial<ModelMeta> = {}): ModelMeta {
  return {
    model: 'qwen2.5:7b-instruct-q4_K_M',
    digest: 'DIGEST_A',
    sizeBytes: 4700,
    paramsB: 7.6,
    quantBits: 4,
    vramEstimateGb: 4.0,
    capabilities: ['completion'],
    aliases: ['qwen2.5:7b'],
    fits: true,
    ...over,
  };
}

function overview(
  over: { hardware?: HardwareInfo; source?: string; models?: ModelMeta[] } = {},
): ModelsOverview {
  return {
    hardware: over.hardware ?? hw(),
    tiers: [],
    recommendedPreset: 'tier1-multimodal',
    runners: [],
    localPlan: {
      whisper: {
        model: 'large-v3-turbo',
        label: 'Whisper large-v3-turbo',
        reason: 'whisper reason',
      },
      llm: {
        model: 'qwen2.5:7b',
        label: 'Qwen2.5 7B',
        reason: 'Qwen2.5 7B — fits your GPU (8000 MB VRAM)',
      },
      runners: [],
    },
    providers: [],
    keyPool: [],
    routingPolicy: { global: 'local', overrides: {} },
    eligibility: {
      source: over.source ?? 'metadata',
      models: over.models ?? [meta()],
      fallback: { model: 'qwen2.5:1.5b', label: 'Qwen2.5 1.5B', reason: 'floor' },
    },
  };
}

describe('quantLabel', () => {
  it('maps known bit-widths', () => {
    expect(quantLabel(4)).toBe('Q4');
    expect(quantLabel(8)).toBe('Q8');
    expect(quantLabel(16)).toBe('FP16');
    expect(quantLabel(32)).toBe('FP32');
    expect(quantLabel(6)).toBe('Q6');
    expect(quantLabel(5)).toBe('Q5');
    expect(quantLabel(3)).toBe('Q3');
    expect(quantLabel(2)).toBe('Q2');
  });
  it('returns "" for unknown / absent widths', () => {
    expect(quantLabel(7)).toBe('');
    expect(quantLabel(null)).toBe('');
    expect(quantLabel(undefined)).toBe('');
  });
});

describe('paramsLabel', () => {
  it('formats billions (integer vs decimal) and millions', () => {
    expect(paramsLabel(7)).toBe('7B');
    expect(paramsLabel(7.6)).toBe('7.6B');
    expect(paramsLabel(0.27)).toBe('270M');
  });
  it('returns "" for absent / non-positive / non-finite', () => {
    expect(paramsLabel(null)).toBe('');
    expect(paramsLabel(undefined)).toBe('');
    expect(paramsLabel(0)).toBe('');
    expect(paramsLabel(-1)).toBe('');
    expect(paramsLabel(Number.POSITIVE_INFINITY)).toBe('');
  });
});

describe('vramEstimateText', () => {
  it('formats a positive GB estimate', () => {
    expect(vramEstimateText(4)).toBe('≈ 4.0 GB');
    expect(vramEstimateText(11.25)).toBe('≈ 11.3 GB');
  });
  it('returns "" for absent / non-positive / non-finite', () => {
    expect(vramEstimateText(null)).toBe('');
    expect(vramEstimateText(undefined)).toBe('');
    expect(vramEstimateText(0)).toBe('');
    expect(vramEstimateText(-2)).toBe('');
    expect(vramEstimateText(Number.NaN)).toBe('');
  });
});

describe('deviceFitText', () => {
  it('names the VRAM on a GPU device', () => {
    expect(deviceFitText(hw({ vramMb: 8192 }))).toBe('fits your 8.0 GB GPU');
  });
  it('names the RAM on a CPU device (null-graceful)', () => {
    expect(deviceFitText(hw({ gpuPresent: false, vramMb: null, ramMb: 16384 }))).toBe(
      'runs on CPU (RAM 16.0 GB)',
    );
  });
  it('falls to the RAM branch when a GPU reports no VRAM', () => {
    expect(deviceFitText(hw({ gpuPresent: true, vramMb: null, ramMb: 8192 }))).toBe(
      'runs on CPU (RAM 8.0 GB)',
    );
  });
  it('says "not detected" when neither VRAM nor RAM is known', () => {
    expect(deviceFitText(hw({ gpuPresent: false, vramMb: null, ramMb: null }))).toBe(
      'device not detected — using the safe baseline',
    );
  });
});

describe('sizeQuantLabel', () => {
  it('joins size + quant', () => {
    expect(sizeQuantLabel(meta())).toBe('7.6B-Q4');
  });
  it('size only when quant is unknown', () => {
    expect(sizeQuantLabel(meta({ quantBits: null }))).toBe('7.6B');
  });
  it('quant only when params are unknown', () => {
    expect(sizeQuantLabel(meta({ paramsB: null }))).toBe('Q4');
  });
  it('"" when neither is known', () => {
    expect(sizeQuantLabel(meta({ paramsB: null, quantBits: null }))).toBe('');
  });
});

describe('chosenLlm', () => {
  it('uses real metadata: model id + quant + VRAM estimate + device fit', () => {
    const r = chosenLlm(overview());
    expect(r.fromMetadata).toBe(true);
    expect(r.name).toBe('qwen2.5:7b-instruct-q4_K_M');
    expect(r.detail).toBe('7.6B-Q4 ≈ 4.0 GB, fits your 7.8 GB GPU');
  });
  it('drops an empty headline (no params/quant/VRAM) to just the fit clause', () => {
    const r = chosenLlm(
      overview({ models: [meta({ paramsB: null, quantBits: null, vramEstimateGb: null })] }),
    );
    expect(r.detail).toBe('fits your 7.8 GB GPU');
  });
  it('falls back to the advisor reason on the ladder source', () => {
    const r = chosenLlm(overview({ source: 'ladder', models: [] }));
    expect(r.fromMetadata).toBe(false);
    expect(r.name).toBe('Qwen2.5 7B');
    expect(r.detail).toBe('Qwen2.5 7B — fits your GPU (8000 MB VRAM)');
  });
});

describe('reasonSummary', () => {
  it('combines the ASR + LLM picks into one novice line', () => {
    expect(reasonSummary(overview())).toBe(
      'Transcribing with Whisper large-v3-turbo · moments by qwen2.5:7b-instruct-q4_K_M (7.6B-Q4 ≈ 4.0 GB, fits your 7.8 GB GPU)',
    );
  });
  it('omits the parenthetical when the LLM detail is empty', () => {
    // A ladder pick whose advisor reason is "" yields a bare model name.
    const ov = overview({ source: 'ladder', models: [] });
    ov.localPlan.llm = { model: 'm', label: 'Tiny', reason: '' };
    expect(reasonSummary(ov)).toBe('Transcribing with Whisper large-v3-turbo · moments by Tiny');
  });
});

describe('deviceFacts', () => {
  it('reports the real size/quant + est VRAM for a metadata pick', () => {
    const facts = deviceFacts(overview());
    const by = Object.fromEntries(facts.map((f) => [f.key, f.value]));
    expect(by.model).toBe('qwen2.5:7b-instruct-q4_K_M');
    expect(by.quant).toBe('7.6B-Q4');
    expect(by['vram-est']).toBe('≈ 4.0 GB');
    expect(by.ram).toBe('15.6 GB');
    expect(by.vram).toBe('7.8 GB');
    expect(by.gpu).toBe('yes');
  });
  it('uses em dashes for quant/est VRAM on the ladder fallback + null-RAM "unknown"', () => {
    const facts = deviceFacts(
      overview({
        source: 'ladder',
        models: [],
        hardware: hw({ gpuPresent: false, vramMb: null, ramMb: null }),
      }),
    );
    const by = Object.fromEntries(facts.map((f) => [f.key, f.value]));
    expect(by.quant).toBe('—');
    expect(by['vram-est']).toBe('—');
    expect(by.ram).toBe('unknown');
    expect(by.vram).toBe('—');
    expect(by.gpu).toBe('none');
  });
  it('uses em dashes when a metadata pick lacks params/quant/VRAM', () => {
    const facts = deviceFacts(
      overview({ models: [meta({ paramsB: null, quantBits: null, vramEstimateGb: null })] }),
    );
    const by = Object.fromEntries(facts.map((f) => [f.key, f.value]));
    expect(by.quant).toBe('—');
    expect(by['vram-est']).toBe('—');
  });
});
