// advisorMeta.ts — pure, test-pinned helpers shared by the Models & System panel
// components (VerdictBadge / ResourceBar / TierCard / ModelCard). No React, no
// I/O: just the verdict->copy/color map, byte-size formatting, fit math, and
// human-friendly model labels grounded in the advisor payload. Keeping these
// here means each presentational component stays a thin render shell and the
// branchy logic is covered once.
import type { AdvisorVerdict } from '../lib/rpc';

/**
 * VRAM headroom fraction above which a model that nominally fits is shown as
 * "Tight". Mirrors the sidecar `system_advisor.TIGHT_FRACTION` so the bar's
 * amber zone and the verdict agree.
 */
export const TIGHT_FRACTION = 0.85;

/** Verdict -> the short badge label the UI shows. */
export const VERDICT_LABEL: Record<AdvisorVerdict, string> = {
  ok: 'Will run',
  degraded: 'Tight',
  unavailable: "Won't run",
};

/** Verdict -> the status modifier class (drives green/amber/red). */
export const VERDICT_CLASS: Record<AdvisorVerdict, string> = {
  ok: 'is-ok',
  degraded: 'is-degraded',
  unavailable: 'is-unavailable',
};

/** A one-line plain-language gloss of what each verdict means (badge tooltip). */
export const VERDICT_HINT: Record<AdvisorVerdict, string> = {
  ok: 'Fits your VRAM budget comfortably and will run.',
  degraded: 'Runs but is VRAM-tight — expect slower loads or close-to-the-edge memory.',
  unavailable: 'Will not run here (over budget, missing dependency, or license-blocked).',
};

/** Map a verdict to its label. */
export function verdictLabel(verdict: AdvisorVerdict): string {
  return VERDICT_LABEL[verdict] ?? verdict;
}

/** Map a verdict to its status class. */
export function verdictClass(verdict: AdvisorVerdict): string {
  return VERDICT_CLASS[verdict] ?? '';
}

/** Map a verdict to its plain-language hint. */
export function verdictHint(verdict: AdvisorVerdict): string {
  return VERDICT_HINT[verdict] ?? '';
}

/** Human-friendly MB/GB string from a megabyte count (null/0 -> em dash). */
export function fmtMb(mb: number | null | undefined): string {
  if (mb === null || mb === undefined || !Number.isFinite(mb) || mb <= 0) return '—';
  if (mb >= 1024) return `${(mb / 1024).toFixed(1)} GB`;
  return `${Math.round(mb)} MB`;
}

/**
 * Like {@link fmtMb} but reads "unknown" (not the em dash) when the probe found
 * nothing. F3: the RAM probe returns null on an undetectable host — the device
 * card must show a readable "unknown", never an "undefined MB" / "NaN" artifact.
 */
export function fmtMbOrUnknown(mb: number | null | undefined): string {
  const formatted = fmtMb(mb);
  return formatted === '—' ? 'unknown' : formatted;
}

/**
 * Clamp a 0..1 fraction (used = used/total) into a percentage for the bar fill.
 * Guards a zero/negative/absent total (-> 0) so an unprobed machine renders an
 * empty rail instead of NaN.
 */
export function fillPct(used: number | null | undefined, total: number | null | undefined): number {
  if (!total || total <= 0 || used === null || used === undefined || used < 0) return 0;
  return Math.min(100, Math.round((used / total) * 100));
}

/**
 * The bar's color zone from how full it is: a resource over TIGHT_FRACTION is
 * "tight" (amber), otherwise "ok" (calm). Used by ResourceBar for the fill tint.
 */
export function fillZone(
  used: number | null | undefined,
  total: number | null | undefined,
): 'ok' | 'tight' {
  if (!total || total <= 0 || !used || used <= 0) return 'ok';
  return used / total > TIGHT_FRACTION ? 'tight' : 'ok';
}

/**
 * Pretty display name for a raw component id — a plain-language capability label
 * that says what the model DOES for the user, never a model codename (§8 Voice).
 * The internal ids and asset names keep their real names; only this human-facing
 * label is de-jargoned. Falls back to a title-cased, de-snaked id (e.g.
 * "foo_bar" -> "Foo bar").
 */
export function prettyName(name: string): string {
  const special: Record<string, string> = {
    vlm_backbone: 'Understand the visuals',
    audio_saliency: 'Find audio highlights',
    scene_transnet: 'Find scene changes',
    quality_gate: 'Check video quality',
    smolvlm2: 'Re-rank clips by watching them',
    ctc_aligner: 'Karaoke word-timing',
    pyannote: 'Tell speakers apart',
    parakeet: 'Fast speech-to-text',
    saliency: 'Keep the subject in frame',
    aesthetic: 'Rate visual appeal',
    emotion: 'Spot emotional moments',
    ocr: 'Read on-screen text',
    motion: 'Detect on-screen motion',
    diversity: 'Skip near-duplicates',
    ranker: 'Smart clip ranking',
  };
  if (special[name]) return special[name];
  return name.charAt(0).toUpperCase() + name.slice(1).replace(/_/g, ' ');
}

/** The license chip text + class from the commercial-OK flag. */
export function licenseChip(commercialOk: boolean): { label: string; cls: string } {
  return commercialOk
    ? { label: 'Commercial OK', cls: 'is-commercial' }
    : { label: 'Local-only', cls: 'is-local-only' };
}

/** Map a preset id to a friendly label (the recommended-preset banner). */
export function presetLabel(preset: string): string {
  const labels: Record<string, string> = {
    'tier0-numeric': 'Tier 0 · Instant numeric (no downloads)',
    'tier1-multimodal': 'Tier 1 · Multimodal (visual + audio + transcript)',
    'tier2-vlm': 'Tier 2 · Video-LLM re-rank (heavy, opt-in)',
  };
  return labels[preset] ?? preset;
}

/**
 * Advisor component name -> its pinned asset name (mirrors the sidecar
 * `handlers._COMPONENT_ASSETS`). The panel uses this to resolve each model
 * card's real download size + installed state from `assets.list` and to target
 * `assets.ensure`. Components absent here are zero-download CPU floors.
 */
export const COMPONENT_ASSET: Record<string, string> = {
  saliency: 'vinet-s-saliency',
  audio_saliency: 'panns-cnn14',
  scene_transnet: 'transnetv2-pytorch',
  vlm_backbone: 'siglip2-so400m',
  aesthetic: 'siglip2-so400m',
  quality_gate: 'dover-mobile-quality',
  emotion: 'hsemotion-onnx',
  ocr: 'rapidocr-onnx',
  parakeet: 'parakeet-tdt-0.6b-v3',
  ctc_aligner: 'ctc-forced-aligner-mms',
  pyannote: 'pyannote-speaker-diarization-31',
  smolvlm2: 'smolvlm2-2.2b',
};

/** The asset name backing a component, or null when it is a zero-download floor. */
export function componentAsset(name: string): string | null {
  return COMPONENT_ASSET[name] ?? null;
}

/** The numeric tier a preset id maps to (for the "Apply preset" settings write). */
export function presetTier(preset: string): number {
  const tiers: Record<string, number> = {
    'tier0-numeric': 0,
    'tier1-multimodal': 1,
    'tier2-vlm': 2,
  };
  return tiers[preset] ?? 0;
}
