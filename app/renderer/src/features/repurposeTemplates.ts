// repurposeTemplates.ts — the curated starter-template catalog (F-template-catalog).
//
// Curated-preset-first (DESIGN §7): a creator assembles a template by picking
// human-labeled starter presets, NEVER raw `protocol.METHODS` ids. The method
// ids live ONLY inside `build()` (the implementation detail the UI maps onto) —
// they are never surfaced to the DOM. The export step's `exportTargets` drive the
// per-preset fan-out; `defaultControls` is the shared "house style".
//
// Pure data + a pure builder so the catalog (and the no-raw-method-id contract)
// is unit-testable without React.

import type { Template, TemplateStep } from '../lib/rpc';

/** One curated starter template the picker offers (friendly label only). */
export interface StarterTemplate {
  id: string;
  /** Human label shown in the picker (never a method id). */
  name: string;
  /** One-line description for the picker. */
  describe: string;
  /** Build the underlying steps bound to one source — method ids live HERE only. */
  build: (videoId: string) => TemplateStep[];
}

/**
 * The v1 curated starter set (F-template-catalog). Each `build` binds steps to a
 * source id; the export step's `exportTargets` is filled from the chosen presets
 * at save time (see `buildTemplateFromStarter`).
 */
export const STARTER_TEMPLATES: StarterTemplate[] = [
  {
    id: 'shorts-house-style',
    name: 'Make shorts (house style)',
    describe: 'Transcribe, pick the best moments, and export shorts per platform.',
    build: (videoId) => [
      { method: 'transcribe.start', params: { videoId }, label: 'Transcribe' },
      { method: 'shortmaker.select', params: { videoId }, label: 'Pick best moments' },
      { method: 'shortmaker.export', params: { videoId }, label: 'Make shorts' },
    ],
  },
  {
    id: 'captioned-shorts',
    name: 'Captioned shorts',
    describe: 'Transcribe, generate subtitles, then export captioned shorts per platform.',
    build: (videoId) => [
      { method: 'transcribe.start', params: { videoId }, label: 'Transcribe' },
      { method: 'subtitles.generate', params: { videoId }, label: 'Generate subtitles' },
      { method: 'shortmaker.export', params: { videoId }, label: 'Make shorts' },
    ],
  },
  {
    id: 'translate-and-shorts',
    name: 'Translate + shorts',
    describe: 'Transcribe, subtitle, translate to Spanish, then export shorts per platform.',
    build: (videoId) => [
      { method: 'transcribe.start', params: { videoId }, label: 'Transcribe' },
      { method: 'subtitles.generate', params: { videoId }, label: 'Generate subtitles' },
      {
        method: 'subtitles.translate',
        params: { trackId: '$2.track.id', targetLang: 'es' },
        label: 'Translate to Spanish',
      },
      { method: 'shortmaker.export', params: { videoId }, label: 'Make shorts' },
    ],
  },
];

/** The export step's method id — `exportTargets` attaches to THIS step. */
export const EXPORT_METHOD = 'shortmaker.export';

/** Resolve a starter by id, falling back to the first when the id is unknown. */
export function starterById(id: string): StarterTemplate {
  return STARTER_TEMPLATES.find((s) => s.id === id) ?? STARTER_TEMPLATES[0];
}

/**
 * Build a save-ready template payload (no id) from a curated starter, the chosen
 * default controls, and the export-target preset ids. The `exportTargets` are
 * attached to BOTH the template field (the runner reads it) and the export step's
 * params (so the sidecar fan-out — `expand_export_steps` — sees them).
 */
export function buildTemplateFromStarter(
  starter: StarterTemplate,
  name: string,
  defaultControls: Record<string, unknown>,
  exportTargets: string[],
): Omit<Template, 'id'> {
  const steps = starter
    .build('$source')
    .map((step) =>
      step.method === EXPORT_METHOD ? { ...step, params: { ...step.params, exportTargets } } : step,
    );
  return { name, steps, defaultControls, exportTargets };
}
