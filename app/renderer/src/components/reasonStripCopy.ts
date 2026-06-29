// reasonStrip.ts — pure, test-pinned helpers for the M2 "using X because Y"
// reason strip + device card (DESIGN §2.3 step 3, §2.4). No React, no I/O: just
// the copy derivation that turns a `models.overview` payload into the one-line
// novice reason ("Transcribing with whisper large-v3-turbo · moments by
// qwen2.5:7b (7B-Q4 ≈ 4.0 GB, fits your 8 GB GPU)") plus the per-pick device-card
// facts. When the detected Ollama runner exposes REAL metadata the reason names
// the actual quant + VRAM estimate; otherwise it reuses the advisor's verbatim
// device-ranked reason string (the static-ladder fallback). RAM that the probe
// could not read renders "unknown" (F3 tie-in), never "undefined MB".
import type { HardwareInfo, ModelMeta, ModelsOverview } from '../lib/rpc';
import { fmtMb, fmtMbOrUnknown } from './advisorMeta';

/** Quant width in bits -> its short label ("Q4" / "FP16"…); "" when unknown. */
export const QUANT_LABEL: Record<number, string> = {
  32: 'FP32',
  16: 'FP16',
  8: 'Q8',
  6: 'Q6',
  5: 'Q5',
  4: 'Q4',
  3: 'Q3',
  2: 'Q2',
};

/** Map a quant bit-width to its short label, or "" when unknown/absent. */
export function quantLabel(quantBits: number | null | undefined): string {
  if (quantBits === null || quantBits === undefined) return '';
  return QUANT_LABEL[quantBits] ?? '';
}

/**
 * Parameter count (in billions) -> a human size label: "7.6B" / "3B" / "270M".
 * "" for an absent/non-positive count. Sub-1B counts read in millions.
 */
export function paramsLabel(paramsB: number | null | undefined): string {
  if (paramsB === null || paramsB === undefined || !Number.isFinite(paramsB) || paramsB <= 0) {
    return '';
  }
  if (paramsB >= 1) {
    return Number.isInteger(paramsB) ? `${paramsB}B` : `${paramsB.toFixed(1)}B`;
  }
  return `${Math.round(paramsB * 1000)}M`;
}

/** Resident VRAM estimate (GB) -> "≈ 4.0 GB", or "" when unknown/non-positive. */
export function vramEstimateText(gb: number | null | undefined): string {
  if (gb === null || gb === undefined || !Number.isFinite(gb) || gb <= 0) return '';
  return `≈ ${gb.toFixed(1)} GB`;
}

/**
 * The "because <device>" clause: a GPU fit names the VRAM, a CPU fall-back names
 * the RAM (null-graceful → "unknown"), and a wholly-undetected device says so.
 */
export function deviceFitText(hardware: HardwareInfo): string {
  if (hardware.gpuPresent && hardware.vramMb !== null && hardware.vramMb > 0) {
    return `fits your ${fmtMb(hardware.vramMb)} GPU`;
  }
  if (hardware.ramMb !== null && hardware.ramMb !== undefined && hardware.ramMb > 0) {
    return `runs on CPU (RAM ${fmtMbOrUnknown(hardware.ramMb)})`;
  }
  return 'device not detected — using the safe baseline';
}

/** The size+quant headline for a metadata pick: "7.6B-Q4" / "7.6B" / "Q4" / "". */
export function sizeQuantLabel(meta: ModelMeta): string {
  const size = paramsLabel(meta.paramsB);
  const quant = quantLabel(meta.quantBits);
  if (size && quant) return `${size}-${quant}`;
  return size || quant;
}

/** The chosen LLM clause for the reason strip. */
export interface LlmReason {
  /** The model id (metadata) or its friendly label (ladder fallback). */
  name: string;
  /** The "7B-Q4 ≈ 4.0 GB, fits your 8 GB GPU" detail, or the advisor reason. */
  detail: string;
  /** True when real runner metadata (not the static ladder) drove the pick. */
  fromMetadata: boolean;
}

/**
 * The LLM reason: prefer the best-fitting REAL Ollama metadata model (naming its
 * actual quant + VRAM estimate); otherwise reuse the advisor's verbatim
 * device-ranked reason from the static-ladder plan (DESIGN: "reuse loud strings").
 */
export function chosenLlm(overview: ModelsOverview): LlmReason {
  const { eligibility, hardware, localPlan } = overview;
  const meta = eligibility.source === 'metadata' ? eligibility.models[0] : undefined;
  if (meta) {
    const headline = [sizeQuantLabel(meta), vramEstimateText(meta.vramEstimateGb)]
      .filter(Boolean)
      .join(' ');
    const fit = deviceFitText(hardware);
    const detail = [headline, fit].filter(Boolean).join(', ');
    return { name: meta.model, detail, fromMetadata: true };
  }
  return { name: localPlan.llm.label, detail: localPlan.llm.reason, fromMetadata: false };
}

/** The one-line "using X because Y" summary the reason strip + aria-label show. */
export function reasonSummary(overview: ModelsOverview): string {
  const whisper = overview.localPlan.whisper;
  const llm = chosenLlm(overview);
  const llmPart = llm.detail ? `${llm.name} (${llm.detail})` : llm.name;
  return `Transcribing with ${whisper.label} · moments by ${llmPart}`;
}

/** One labelled device-card fact (model / quant / VRAM est / RAM / VRAM / GPU). */
export interface DeviceFact {
  key: string;
  label: string;
  value: string;
}

/**
 * The device-card facts for the chosen pick: its size+quant + VRAM estimate
 * (real metadata only) plus the probed device headroom. RAM uses the F3
 * null-graceful formatter so an undetected host reads "unknown", never "NaN".
 */
export function deviceFacts(overview: ModelsOverview): DeviceFact[] {
  const { hardware } = overview;
  const llm = chosenLlm(overview);
  const meta =
    overview.eligibility.source === 'metadata' ? overview.eligibility.models[0] : undefined;
  const quantVal = meta ? sizeQuantLabel(meta) || '—' : '—';
  const vramEstVal = meta ? vramEstimateText(meta.vramEstimateGb) || '—' : '—';
  return [
    { key: 'model', label: 'Model', value: llm.name },
    { key: 'quant', label: 'Size · quant', value: quantVal },
    { key: 'vram-est', label: 'Est. VRAM', value: vramEstVal },
    { key: 'ram', label: 'RAM', value: fmtMbOrUnknown(hardware.ramMb) },
    { key: 'vram', label: 'VRAM', value: fmtMb(hardware.vramMb) },
    { key: 'gpu', label: 'GPU', value: hardware.gpuPresent ? 'yes' : 'none' },
  ];
}
