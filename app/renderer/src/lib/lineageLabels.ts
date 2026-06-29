// lib/lineageLabels.ts — FRIENDLY labels for L4's provenance card.
//
// The lineage RPC carries RAW ids (op = "shortmaker.select", model =
// "qwen2.5:7b", a route mode = "local"). A novice should never read those
// (DESIGN §3.5: "provenance"/"PROV" never shown in novice copy). Each mapper
// returns a {label, raw} pair so the card renders the friendly `label` inline
// and keeps the `raw` id in a `title` tooltip — surfaced, never hidden (no
// silent drop). An UNKNOWN id is shown verbatim as its own label rather than
// faked into something prettier we cannot vouch for.

import type { LineageProvenance } from './rpc';

export interface FriendlyLabel {
  /** Human-friendly text shown inline on the card. */
  label: string;
  /** The raw id/value — shown in the `title` tooltip (never hidden). */
  raw: string;
}

/** Friendly verb for each known op id. Unknown ops fall back to the raw id. */
const OP_LABELS: Record<string, string> = {
  'shortmaker.select': 'Found highlights',
  'shortmaker.export': 'Made short',
  'transcribe.start': 'Transcribed',
  'subtitles.generate': 'Made captions',
  'subtitles.translate': 'Translated captions',
  'thumbnail.select': 'Picked thumbnail',
  'convert.start': 'Converted',
  'convert.batch': 'Converted batch',
  'dub.start': 'Dubbed',
  'nle.export': 'Exported timeline',
  'package.export': 'Packaged for upload',
};

/** Where a model ran, from a route `mode`. Unknown modes fall back to the raw. */
const LOCALITY: Record<string, string> = {
  local: 'on this PC',
  cloud: 'cloud',
  auto: 'auto-routed',
};

/** Known model id -> display name. Unknown ids are shown verbatim (no guessing). */
const MODEL_NAMES: Record<string, string> = {
  'qwen2.5:7b': 'Qwen2.5 7B',
  'qwen2.5:14b': 'Qwen2.5 14B',
  'qwen2.5:32b': 'Qwen2.5 32B',
  'llama3.1:8b': 'Llama 3.1 8B',
  'whisper-large-v3': 'Whisper Large v3',
};

/** Known caption-template id -> display name. Unknown ids are shown verbatim. */
const CAPTION_NAMES: Record<string, string> = {
  bold: 'Bold',
  punchy: 'Punchy',
  karaoke: 'Karaoke',
  'opusclip-karaoke': 'OpusClip Karaoke',
  minimal: 'Minimal',
};

/** Read a string field of an untrusted record, or `''` when absent/non-string. */
function str(obj: Record<string, unknown>, key: string): string {
  const value = obj[key];
  return typeof value === 'string' ? value : '';
}

/** Friendly op verb (e.g. `shortmaker.select` -> "Found highlights"). `null` when blank. */
export function opLabel(op: string): FriendlyLabel | null {
  if (op === '') return null;
  return { label: OP_LABELS[op] ?? op, raw: op };
}

/**
 * Friendly model + locality (e.g. `{mode:'local', model:'qwen2.5:7b'}` ->
 * "Qwen2.5 7B (on this PC)", raw `qwen2.5:7b`). `null` when the route names
 * neither a model nor a mode.
 */
export function modelLabel(route: Record<string, unknown> | null): FriendlyLabel | null {
  if (route === null) return null;
  const model = str(route, 'model');
  const mode = str(route, 'mode');
  if (model === '' && mode === '') return null;
  const name = model === '' ? '' : (MODEL_NAMES[model] ?? model);
  const where = mode === '' ? '' : (LOCALITY[mode] ?? mode);
  let label: string;
  if (name !== '' && where !== '') {
    label = `${name} (${where})`;
  } else if (name !== '') {
    label = name;
  } else {
    label = where;
  }
  return { label, raw: model !== '' ? model : mode };
}

/** Friendly preset name (already human-readable, e.g. "Punchy"). `null` when blank. */
export function presetLabel(preset: string | null): FriendlyLabel | null {
  if (preset === null || preset === '') return null;
  return { label: preset, raw: preset };
}

/** Friendly caption-style name from the job params' `template`. `null` when absent. */
export function captionLabel(params: Record<string, unknown> | null): FriendlyLabel | null {
  if (params === null) return null;
  const template = str(params, 'template');
  if (template === '') return null;
  return { label: CAPTION_NAMES[template] ?? template, raw: template };
}

/** The "Reframe vX" maker line — `null` when the agent recorded no app version. */
export function makerLabel(provenance: LineageProvenance): string | null {
  const version = provenance.appVersion;
  if (version === null || version === '') return null;
  return `Reframe v${version}`;
}
