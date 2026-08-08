// languages.ts — the renderer half of the ONE language inventory.
//
// The sidecar half is `sidecar/media_studio/features/languages.py`, and
// `languages.conformance.test.ts` fails the build if the two drift. Read that
// module's header for how each set was MEASURED (faster-whisper v1.2.1's
// `_LANGUAGE_CODES` cross-checked against openai-whisper's `LANGUAGES`; the
// parakeet-tdt-0.6b-v3 model card at the revision `parakeet_asr.py` pins), and
// run `python docs/validation/tools/probe_language_inventory.py` to re-derive
// them after a model or library bump.
//
// V1 IA decision (V1-GRILL-DECISIONS §h) is UNCHANGED: language is a DROPDOWN,
// never free-typed, so a user cannot pick a nonexistent code. What changed is the
// dropdown's contents. The old list was 19 hand-picked codes, which left 83 of the
// 102 languages the engines actually support unreachable — including Romanian,
// covered by BOTH ASR engines and by fast local translation. The 19 survive as
// COMMON_CODES, the ordered head of the list, so the common choices stay one
// glance away in a 102-item picker.
//
// Support is NOT uniform across the inventory, and the UI must say so per-language
// rather than silently offering a language that will fail — that is what
// `capabilityNote` is for. Three real asymmetries, all measured:
//   * Parakeet covers 25 European languages; Whisper covers all 100. Parakeet is a
//     strict SUBSET, so "switch to Whisper" is always a valid fix.
//   * `nb` and `zu` have NO ASR coverage at all — translation targets only.
//   * 50 languages have ASR but no LOCAL translation, so translating into them
//     needs the hosted provider (internet + an API key).

/** A selectable language: an ISO-639-1 code + a human label. */
export interface LanguageOption {
  code: string;
  label: string;
}

/** The wired ASR engines (mirrors `transcribe.ASR_ENGINES`). */
export type AsrEngine = 'whisper' | 'parakeet';

/** A translation tier id (mirrors `translation.TIERS`). */
export type MtTier = 'tier1' | 'tier2' | 'tier3';

/** The sentinel "let the engine detect the language" choice (not a real code). */
export const AUTO_DETECT = 'auto';

/** Display names for the engines, for use in user-facing advice. */
export const ASR_ENGINE_LABELS: Readonly<Record<AsrEngine, string>> = {
  whisper: 'Whisper',
  parakeet: 'Parakeet',
};

/** faster-whisper v1.2.1 `tokenizer._LANGUAGE_CODES` — 100 codes (measured). */
export const WHISPER_LANGS: ReadonlySet<string> = new Set([
  'af', 'am', 'ar', 'as', 'az', 'ba', 'be', 'bg', 'bn', 'bo',
  'br', 'bs', 'ca', 'cs', 'cy', 'da', 'de', 'el', 'en', 'es',
  'et', 'eu', 'fa', 'fi', 'fo', 'fr', 'gl', 'gu', 'ha', 'haw',
  'he', 'hi', 'hr', 'ht', 'hu', 'hy', 'id', 'is', 'it', 'ja',
  'jw', 'ka', 'kk', 'km', 'kn', 'ko', 'la', 'lb', 'ln', 'lo',
  'lt', 'lv', 'mg', 'mi', 'mk', 'ml', 'mn', 'mr', 'ms', 'mt',
  'my', 'ne', 'nl', 'nn', 'no', 'oc', 'pa', 'pl', 'ps', 'pt',
  'ro', 'ru', 'sa', 'sd', 'si', 'sk', 'sl', 'sn', 'so', 'sq',
  'sr', 'su', 'sv', 'sw', 'ta', 'te', 'tg', 'th', 'tk', 'tl',
  'tr', 'tt', 'uk', 'ur', 'uz', 'vi', 'yi', 'yo', 'yue', 'zh',
]);

/** `nvidia/parakeet-tdt-0.6b-v3` @ 575de92 — 25 European languages (measured). */
export const PARAKEET_LANGS: ReadonlySet<string> = new Set([
  'bg', 'cs', 'da', 'de', 'el', 'en', 'es', 'et', 'fi', 'fr',
  'hr', 'hu', 'it', 'lt', 'lv', 'mt', 'nl', 'pl', 'pt', 'ro',
  'ru', 'sk', 'sl', 'sv', 'uk',
]);

/** TranslateGemma-4B (fast, fully GPU-resident) local coverage — 40. */
export const TRANSLATE_TIER1: ReadonlySet<string> = new Set([
  'ar', 'bg', 'ca', 'cs', 'da', 'de', 'el', 'en', 'es', 'et',
  'fa', 'fi', 'fr', 'he', 'hi', 'hr', 'hu', 'id', 'it', 'ja',
  'ko', 'lt', 'lv', 'ms', 'nb', 'nl', 'no', 'pl', 'pt', 'ro',
  'ru', 'sk', 'sl', 'sr', 'sv', 'th', 'tr', 'uk', 'vi', 'zh',
]);

/** TranslateGemma-12B (partial offload, labelled SLOW) local coverage — 12. */
export const TRANSLATE_TIER2: ReadonlySet<string> = new Set([
  'bn', 'gu', 'is', 'kn', 'ml', 'mr', 'pa', 'sw', 'ta', 'te', 'ur', 'zu',
]);

/** engine -> the languages it can transcribe. */
const ENGINE_LANGS: Readonly<Record<AsrEngine, ReadonlySet<string>>> = {
  whisper: WHISPER_LANGS,
  parakeet: PARAKEET_LANGS,
};

/** The engines in advice order (the always-installed default first). */
const ENGINE_ORDER: readonly AsrEngine[] = ['whisper', 'parakeet'];

/**
 * The curated creator head of the picker (the pre-v1.5 list), in its own order.
 * NOT a capability claim — purely an ordering so the common choices come first.
 */
export const COMMON_CODES: readonly string[] = [
  'en', 'es', 'pt', 'fr', 'de', 'it', 'nl', 'pl', 'ru', 'uk',
  'tr', 'ar', 'hi', 'id', 'vi', 'th', 'ja', 'ko', 'zh',
] as const;

/**
 * Every language the app offers — the union of what the ASR engines transcribe and
 * what the local translator covers — in picker order: COMMON_CODES first, then the
 * rest sorted by label. The sidecar mirror holds the same codes, labels and order.
 */
export const LANGUAGES: readonly LanguageOption[] = [
  { code: 'en', label: 'English' },
  { code: 'es', label: 'Spanish' },
  { code: 'pt', label: 'Portuguese' },
  { code: 'fr', label: 'French' },
  { code: 'de', label: 'German' },
  { code: 'it', label: 'Italian' },
  { code: 'nl', label: 'Dutch' },
  { code: 'pl', label: 'Polish' },
  { code: 'ru', label: 'Russian' },
  { code: 'uk', label: 'Ukrainian' },
  { code: 'tr', label: 'Turkish' },
  { code: 'ar', label: 'Arabic' },
  { code: 'hi', label: 'Hindi' },
  { code: 'id', label: 'Indonesian' },
  { code: 'vi', label: 'Vietnamese' },
  { code: 'th', label: 'Thai' },
  { code: 'ja', label: 'Japanese' },
  { code: 'ko', label: 'Korean' },
  { code: 'zh', label: 'Chinese' },
  { code: 'af', label: 'Afrikaans' },
  { code: 'sq', label: 'Albanian' },
  { code: 'am', label: 'Amharic' },
  { code: 'hy', label: 'Armenian' },
  { code: 'as', label: 'Assamese' },
  { code: 'az', label: 'Azerbaijani' },
  { code: 'ba', label: 'Bashkir' },
  { code: 'eu', label: 'Basque' },
  { code: 'be', label: 'Belarusian' },
  { code: 'bn', label: 'Bengali' },
  { code: 'bs', label: 'Bosnian' },
  { code: 'br', label: 'Breton' },
  { code: 'bg', label: 'Bulgarian' },
  { code: 'my', label: 'Burmese' },
  { code: 'yue', label: 'Cantonese' },
  { code: 'ca', label: 'Catalan' },
  { code: 'hr', label: 'Croatian' },
  { code: 'cs', label: 'Czech' },
  { code: 'da', label: 'Danish' },
  { code: 'et', label: 'Estonian' },
  { code: 'fo', label: 'Faroese' },
  { code: 'fi', label: 'Finnish' },
  { code: 'gl', label: 'Galician' },
  { code: 'ka', label: 'Georgian' },
  { code: 'el', label: 'Greek' },
  { code: 'gu', label: 'Gujarati' },
  { code: 'ht', label: 'Haitian Creole' },
  { code: 'ha', label: 'Hausa' },
  { code: 'haw', label: 'Hawaiian' },
  { code: 'he', label: 'Hebrew' },
  { code: 'hu', label: 'Hungarian' },
  { code: 'is', label: 'Icelandic' },
  { code: 'jw', label: 'Javanese' },
  { code: 'kn', label: 'Kannada' },
  { code: 'kk', label: 'Kazakh' },
  { code: 'km', label: 'Khmer' },
  { code: 'lo', label: 'Lao' },
  { code: 'la', label: 'Latin' },
  { code: 'lv', label: 'Latvian' },
  { code: 'ln', label: 'Lingala' },
  { code: 'lt', label: 'Lithuanian' },
  { code: 'lb', label: 'Luxembourgish' },
  { code: 'mk', label: 'Macedonian' },
  { code: 'mg', label: 'Malagasy' },
  { code: 'ms', label: 'Malay' },
  { code: 'ml', label: 'Malayalam' },
  { code: 'mt', label: 'Maltese' },
  { code: 'mi', label: 'Maori' },
  { code: 'mr', label: 'Marathi' },
  { code: 'mn', label: 'Mongolian' },
  { code: 'ne', label: 'Nepali' },
  { code: 'no', label: 'Norwegian' },
  { code: 'nb', label: 'Norwegian Bokmal' },
  { code: 'nn', label: 'Norwegian Nynorsk' },
  { code: 'oc', label: 'Occitan' },
  { code: 'ps', label: 'Pashto' },
  { code: 'fa', label: 'Persian' },
  { code: 'pa', label: 'Punjabi' },
  { code: 'ro', label: 'Romanian' },
  { code: 'sa', label: 'Sanskrit' },
  { code: 'sr', label: 'Serbian' },
  { code: 'sn', label: 'Shona' },
  { code: 'sd', label: 'Sindhi' },
  { code: 'si', label: 'Sinhala' },
  { code: 'sk', label: 'Slovak' },
  { code: 'sl', label: 'Slovenian' },
  { code: 'so', label: 'Somali' },
  { code: 'su', label: 'Sundanese' },
  { code: 'sw', label: 'Swahili' },
  { code: 'sv', label: 'Swedish' },
  { code: 'tl', label: 'Tagalog' },
  { code: 'tg', label: 'Tajik' },
  { code: 'ta', label: 'Tamil' },
  { code: 'tt', label: 'Tatar' },
  { code: 'te', label: 'Telugu' },
  { code: 'bo', label: 'Tibetan' },
  { code: 'tk', label: 'Turkmen' },
  { code: 'ur', label: 'Urdu' },
  { code: 'uz', label: 'Uzbek' },
  { code: 'cy', label: 'Welsh' },
  { code: 'yi', label: 'Yiddish' },
  { code: 'yo', label: 'Yoruba' },
  { code: 'zu', label: 'Zulu' },
] as const;

const LABEL_BY_CODE: ReadonlyMap<string, string> = new Map(
  LANGUAGES.map((l) => [l.code, l.label]),
);

/** Map a code to its label, including the auto sentinel; unknown codes echo back. */
export function languageLabel(code: string): string {
  if (code === AUTO_DETECT) return 'Auto-detect';
  return LABEL_BY_CODE.get(code) ?? code;
}

/**
 * Normalize a language tag to a bare lowercase primary subtag, leniently:
 * `pt-BR`/`pt_BR` -> `pt`, `zh_Hant` -> `zh`, `EN` -> `en`, anything blank or
 * non-string -> `''`. Mirrors the sidecar's `normalize_code` (a persisted setting
 * is untyped at runtime, so `7` must not become the language `'7'`).
 */
export function normalizeCode(raw: unknown): string {
  if (typeof raw !== 'string') return '';
  return raw.trim().toLowerCase().replace(/_/g, '-').split('-', 1)[0].trim();
}

/**
 * The value to put on the wire for a SOURCE language, or `undefined` for
 * auto-detect.
 *
 * This is the boundary the audit flagged as almost-certain breakage: the sidecar
 * validates `language` only as "a string when given" and `transcribe_file` hands
 * it straight to `whisper_model.transcribe(language=...)`, so a literal `"auto"`
 * would be read as a language id. `normalizeCode` already folds `auto-detect` and
 * `Auto` onto `auto`, so one comparison covers every spelling.
 */
export function toWireLanguage(code: unknown): string | undefined {
  const norm = normalizeCode(code);
  if (!norm || norm === AUTO_DETECT) return undefined;
  return norm;
}

/** The engine id if `raw` names a wired ASR engine, else `null`. */
function asAsrEngine(raw: unknown): AsrEngine | null {
  const name = typeof raw === 'string' ? raw.trim().toLowerCase() : '';
  return ENGINE_ORDER.find((e) => e === name) ?? null;
}

/** The wired ASR engines that can transcribe `code` (the default engine first). */
export function transcriptionEngines(code: unknown): readonly AsrEngine[] {
  const norm = normalizeCode(code);
  return ENGINE_ORDER.filter((e) => ENGINE_LANGS[e].has(norm));
}

/**
 * Whether `engine` can transcribe `code`. An unknown engine name is `false` — this
 * answers "is this combination safe to offer", and guessing would turn a typo into
 * a false promise. (Resolving an unknown *setting* to whisper is a different
 * question, answered by the sidecar's `selected_asr_engine`.)
 */
export function supportsTranscription(engine: unknown, code: unknown): boolean {
  const known = asAsrEngine(engine);
  if (known === null) return false;
  return ENGINE_LANGS[known].has(normalizeCode(code));
}

/** The translation tier `code` routes to (mirrors the sidecar's `mt_tier`). */
export function mtTier(code: unknown): MtTier {
  const norm = normalizeCode(code);
  if (TRANSLATE_TIER1.has(norm)) return 'tier1';
  if (TRANSLATE_TIER2.has(norm)) return 'tier2';
  return 'tier3';
}

/**
 * The per-language caveat to show beside a picked language, or `null` when there
 * is nothing to disclose.
 *
 * Ordered hardest-blocker-first, so a user sees the thing that would actually make
 * the job fail rather than a softer note about the same language:
 *   1. no ASR engine covers it at all (translation target only);
 *   2. the CHOSEN engine does not cover it (and how to fix that);
 *   3. translating into it needs the hosted provider (network + credentials);
 *   4. translating into it uses the slower local model.
 *
 * `engine` is the current `asrEngine` setting. It is free-form at runtime, so an
 * unrecognized value is IGNORED rather than reported as a gap.
 */
export function capabilityNote(code: unknown, engine?: unknown): string | null {
  const norm = normalizeCode(code);
  if (!norm || norm === AUTO_DETECT) return null;
  const label = languageLabel(norm);

  if (transcriptionEngines(norm).length === 0) {
    return `${label} cannot be transcribed — no speech engine here covers it. Use it as a translation target instead.`;
  }

  const chosen = asAsrEngine(engine);
  if (chosen !== null && !supportsTranscription(chosen, norm)) {
    const name = ASR_ENGINE_LABELS[chosen];
    return `${name} cannot transcribe ${label} — switch the speech engine to ${ASR_ENGINE_LABELS.whisper} in Settings, or pick a language ${name} covers.`;
  }

  const tier = mtTier(norm);
  if (tier === 'tier3') {
    return `Translating into ${label} uses the hosted provider (needs internet and an API key) — the offline translator does not cover it.`;
  }
  if (tier === 'tier2') {
    return `Translating into ${label} uses the slower high-quality local model, so it takes longer than a common language.`;
  }
  return null;
}
