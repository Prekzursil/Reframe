// routingFunctions.ts — the M5 per-function routing override vocabulary.
//
// Mirrors the sidecar `routing_resolve.AI_FUNCTIONS` / `AI_FUNCTION_LABELS`
// (DESIGN §2.1: asr, moment-select/LLM, caption-polish, translate, director) so
// the Advanced override table and the sidecar concrete resolver agree on the same
// canonical function set. The header toggle drives `RoutingPolicy.global`; this
// table drives `RoutingPolicy.overrides[fn]` — and an `inherit` choice REMOVES the
// override so the function falls back to the global mode.
import type { RoutingMode } from '../lib/rpc';

/** The canonical AI functions the override table exposes (DESIGN §2.1). */
export const AI_FUNCTIONS = ['asr', 'select', 'caption', 'translation', 'director'] as const;
export type AiFunction = (typeof AI_FUNCTIONS)[number];

/** Human labels for each override-table row. */
export const AI_FUNCTION_LABELS: Record<AiFunction, string> = {
  asr: 'Transcription (ASR)',
  select: 'Moment selection (LLM)',
  caption: 'Caption polish',
  translation: 'Translation',
  director: 'Director plan',
};

/** The per-row choices: `inherit` (use the global default) + the three modes. */
export const OVERRIDE_CHOICES = ['inherit', 'local', 'cloud', 'auto'] as const;
export type OverrideChoice = (typeof OVERRIDE_CHOICES)[number];

/** Labels for the per-row `<select>` options. */
export const OVERRIDE_LABELS: Record<OverrideChoice, string> = {
  inherit: 'Global default',
  local: 'Local',
  cloud: 'Cloud',
  auto: 'Auto',
};

/**
 * Apply one row's choice to the overrides map IMMUTABLY: `inherit` deletes the
 * key (fall back to global); a concrete mode sets it. Never mutates the input.
 */
export function applyOverrideChoice(
  overrides: Readonly<Record<string, RoutingMode>>,
  fn: AiFunction,
  choice: OverrideChoice,
): Record<string, RoutingMode> {
  const next: Record<string, RoutingMode> = { ...overrides };
  if (choice === 'inherit') {
    delete next[fn];
  } else {
    next[fn] = choice;
  }
  return next;
}

/** The current row choice for `fn`: its override mode, or `inherit` when unset. */
export function choiceFor(
  overrides: Readonly<Record<string, RoutingMode>>,
  fn: AiFunction,
): OverrideChoice {
  const mode = overrides[fn];
  return mode === 'local' || mode === 'cloud' || mode === 'auto' ? mode : 'inherit';
}
