import { describe, expect, it } from 'vitest';
import {
  AUTO_DETECT,
  COMMON_CODES,
  LANGUAGES,
  PARAKEET_LANGS,
  TRANSLATE_TIER1,
  TRANSLATE_TIER2,
  WHISPER_LANGS,
  capabilityNote,
  languageLabel,
  mtTier,
  normalizeCode,
  supportsTranscription,
  toWireLanguage,
  transcriptionEngines,
} from './languages';

// Counts here are MEASURED, never hand-counted — see the module header and
// sidecar/tests/test_languages.py for the two probes and their pinned sources.
describe('language inventory', () => {
  it('offers the FULL engine-derived set, not a curated short list', () => {
    expect(LANGUAGES.length).toBe(102);
    expect(WHISPER_LANGS.size).toBe(100);
    expect(PARAKEET_LANGS.size).toBe(25);
    expect(TRANSLATE_TIER1.size).toBe(40);
    expect(TRANSLATE_TIER2.size).toBe(12);
  });

  it('reaches the languages the old 19-entry list could not', () => {
    const codes = new Set(LANGUAGES.map((l) => l.code));
    // Romanian: both ASR engines and tier1 MT cover it, yet it was unreachable.
    expect(codes.has('ro')).toBe(true);
    // A spread across the previously-missing groups.
    for (const code of ['sv', 'cs', 'he', 'fa', 'ta', 'yue', 'sw', 'nb', 'zu']) {
      expect(codes.has(code)).toBe(true);
    }
  });

  it('excludes the auto sentinel from the language list', () => {
    expect(LANGUAGES.some((l) => l.code === AUTO_DETECT)).toBe(false);
  });

  it('has unique codes and unique labels', () => {
    expect(new Set(LANGUAGES.map((l) => l.code)).size).toBe(LANGUAGES.length);
    expect(new Set(LANGUAGES.map((l) => l.label)).size).toBe(LANGUAGES.length);
  });

  it('leads with the curated creator head, then sorts the tail by label', () => {
    expect(COMMON_CODES.length).toBe(19);
    expect(COMMON_CODES[0]).toBe('en');
    expect(LANGUAGES.slice(0, COMMON_CODES.length).map((l) => l.code)).toEqual([...COMMON_CODES]);
    const tail = LANGUAGES.slice(COMMON_CODES.length).map((l) => l.label);
    expect(tail).toEqual([...tail].sort());
  });

  it('languageLabel resolves known codes, the sentinel, and echoes the rest', () => {
    expect(languageLabel('en')).toBe('English');
    expect(languageLabel('ro')).toBe('Romanian');
    expect(languageLabel(AUTO_DETECT)).toBe('Auto-detect');
    expect(languageLabel('zz')).toBe('zz');
  });
});

describe('normalizeCode', () => {
  it('lowercases, trims and drops the region subtag', () => {
    expect(normalizeCode('EN')).toBe('en');
    expect(normalizeCode('  pt-BR ')).toBe('pt');
    expect(normalizeCode('zh_Hant')).toBe('zh');
  });
  it('returns an empty string for anything blank or non-string', () => {
    expect(normalizeCode('')).toBe('');
    expect(normalizeCode('   ')).toBe('');
    expect(normalizeCode('-')).toBe('');
    expect(normalizeCode(undefined)).toBe('');
    expect(normalizeCode(7)).toBe('');
  });
});

describe('toWireLanguage (the AUTO -> undefined boundary)', () => {
  it('drops the sentinel so the sidecar auto-detects instead of seeing "auto"', () => {
    // transcribe.py forwards `language` STRAIGHT to faster-whisper, so a literal
    // "auto" would be read as a language id. It must never reach the wire.
    expect(toWireLanguage(AUTO_DETECT)).toBeUndefined();
    expect(toWireLanguage('AUTO')).toBeUndefined();
    expect(toWireLanguage('')).toBeUndefined();
    expect(toWireLanguage('   ')).toBeUndefined();
  });
  it('normalizes and forwards a real code', () => {
    expect(toWireLanguage('en')).toBe('en');
    expect(toWireLanguage(' PT-br ')).toBe('pt');
  });
});

describe('capability model', () => {
  it('transcriptionEngines reports which ASR engines cover a code', () => {
    expect(transcriptionEngines('ro')).toEqual(['whisper', 'parakeet']);
    expect(transcriptionEngines('ja')).toEqual(['whisper']);
    // nb / zu are local-MT-only: no ASR engine covers them (measured).
    expect(transcriptionEngines('nb')).toEqual([]);
    expect(transcriptionEngines('zu')).toEqual([]);
    expect(transcriptionEngines('zz')).toEqual([]);
  });

  it('supportsTranscription is per-engine and rejects an unknown engine', () => {
    expect(supportsTranscription('whisper', 'ja')).toBe(true);
    expect(supportsTranscription('parakeet', 'ja')).toBe(false);
    expect(supportsTranscription('parakeet', 'ro')).toBe(true);
    expect(supportsTranscription('Whisper', 'ja')).toBe(true);
    expect(supportsTranscription('nope', 'en')).toBe(false);
  });

  it('mtTier routes by language, hosted outside local coverage', () => {
    expect(mtTier('ro')).toBe('tier1');
    expect(mtTier('ta')).toBe('tier2');
    expect(mtTier('yue')).toBe('tier3');
    expect(mtTier('zz')).toBe('tier3');
    expect(mtTier('PT_br')).toBe('tier1');
  });
});

describe('capabilityNote — the per-language "say so" text', () => {
  it('is silent for the sentinel and for a blank code', () => {
    expect(capabilityNote(AUTO_DETECT)).toBeNull();
    expect(capabilityNote('')).toBeNull();
  });

  it('is silent for a fully-covered tier1 language', () => {
    expect(capabilityNote('ro')).toBeNull();
    expect(capabilityNote('ro', 'parakeet')).toBeNull();
  });

  it('names the translation-target-only languages', () => {
    const note = capabilityNote('nb');
    expect(note).toContain('Norwegian Bokmal');
    expect(note).toContain('cannot be transcribed');
  });

  it('names the engine gap AND the fix when the chosen engine cannot cover it', () => {
    const note = capabilityNote('ja', 'parakeet');
    expect(note).toContain('Parakeet');
    expect(note).toContain('Japanese');
    expect(note).toContain('Whisper');
  });

  it('discloses the hosted translation tier (network + credentials)', () => {
    const note = capabilityNote('yue');
    expect(note).toContain('Cantonese');
    expect(note).toContain('hosted');
  });

  it('discloses the slower local tier', () => {
    const note = capabilityNote('ta');
    expect(note).toContain('Tamil');
    expect(note).toContain('slower');
  });

  it('ignores an unrecognized engine id rather than inventing a gap', () => {
    // asrEngine settings are free-form strings; the sidecar resolves an unknown
    // one to whisper (transcribe.selected_asr_engine), so claiming "X cannot
    // transcribe Japanese" for a typo would be a false warning.
    expect(capabilityNote('ja', 'nope')).toBeNull();
    expect(capabilityNote('ja', '')).toBeNull();
  });

  it('prefers the ASR gap over the MT tier when both apply', () => {
    // zu has no ASR at all AND is tier2 — the harder blocker wins.
    expect(capabilityNote('zu')).toContain('cannot be transcribed');
    // th is whisper-only AND tier1 -> only the engine note can fire.
    expect(capabilityNote('th', 'parakeet')).toContain('Parakeet');
  });

  it('echoes an unknown code rather than pretending it is supported', () => {
    expect(capabilityNote('zz')).toContain('zz');
  });
});
