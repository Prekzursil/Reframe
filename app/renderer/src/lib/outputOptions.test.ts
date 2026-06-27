import { describe, expect, it } from 'vitest';
import {
  DEFAULT_OUTPUT_OPTIONS,
  type OutputOptions,
  SUBTITLE_MODES,
  SUBTITLE_MODE_META,
  coerceSubtitleMode,
  describeOutputs,
  embedsSubtitles,
  hasOutput,
  outputArtifacts,
  resolveBurn,
  sanitizeOutputOptions,
  writesSubtitleFile,
} from './outputOptions';

const opts = (over: Partial<OutputOptions> = {}): OutputOptions => ({
  ...DEFAULT_OUTPUT_OPTIONS,
  ...over,
});

describe('subtitle mode metadata', () => {
  it('has label + help for every mode', () => {
    for (const mode of SUBTITLE_MODES) {
      expect(SUBTITLE_MODE_META[mode].label).toBeTruthy();
      expect(SUBTITLE_MODE_META[mode].help).toBeTruthy();
    }
  });
});

describe('resolveBurn / embedsSubtitles', () => {
  it('burns only the burn mode', () => {
    expect(resolveBurn('burn')).toBe(true);
    expect(resolveBurn('softmux')).toBe(false);
    expect(resolveBurn('sidecar')).toBe(false);
    expect(resolveBurn('none')).toBe(false);
  });

  it('embeds for burn + soft track only', () => {
    expect(embedsSubtitles('burn')).toBe(true);
    expect(embedsSubtitles('softmux')).toBe(true);
    expect(embedsSubtitles('sidecar')).toBe(false);
    expect(embedsSubtitles('none')).toBe(false);
  });
});

describe('writesSubtitleFile', () => {
  it('writes a file for sidecar delivery', () => {
    expect(writesSubtitleFile(opts({ subtitleMode: 'sidecar', saveSrt: false }))).toBe(true);
  });
  it('writes a file when SRT save is requested', () => {
    expect(writesSubtitleFile(opts({ subtitleMode: 'burn', saveSrt: true }))).toBe(true);
  });
  it('does not write a file for burn/softmux without an SRT save', () => {
    expect(writesSubtitleFile(opts({ subtitleMode: 'burn', saveSrt: false }))).toBe(false);
    expect(writesSubtitleFile(opts({ subtitleMode: 'softmux', saveSrt: false }))).toBe(false);
  });
});

describe('coerceSubtitleMode', () => {
  it('accepts a known mode (case-insensitive, trimmed)', () => {
    expect(coerceSubtitleMode('  SoftMux ')).toBe('softmux');
  });
  it('falls back to the default for unknown/non-string', () => {
    expect(coerceSubtitleMode('nonsense')).toBe('burn');
    expect(coerceSubtitleMode(42)).toBe('burn');
  });
});

describe('sanitizeOutputOptions', () => {
  it('validates a partial object', () => {
    expect(sanitizeOutputOptions({ subtitleMode: 'sidecar', saveClip: true })).toEqual({
      subtitleMode: 'sidecar',
      saveClip: true,
      saveShort: true,
      saveSrt: false,
    });
  });
  it('falls back to defaults for null + non-boolean fields', () => {
    expect(sanitizeOutputOptions(null)).toEqual(DEFAULT_OUTPUT_OPTIONS);
    expect(sanitizeOutputOptions({ saveShort: 'yes' as unknown as boolean })).toEqual(
      DEFAULT_OUTPUT_OPTIONS,
    );
  });
  it('defaults undefined input', () => {
    expect(sanitizeOutputOptions(undefined)).toEqual(DEFAULT_OUTPUT_OPTIONS);
  });
});

describe('outputArtifacts / hasOutput', () => {
  it('lists artifacts in stable order', () => {
    expect(outputArtifacts(opts({ saveClip: true, saveShort: true, saveSrt: true }))).toEqual([
      'clip',
      'short',
      'srt',
    ]);
  });
  it('includes srt when delivery is sidecar even without saveSrt', () => {
    expect(outputArtifacts(opts({ saveShort: false, subtitleMode: 'sidecar' }))).toEqual(['srt']);
  });
  it('hasOutput is false when nothing is selected', () => {
    expect(hasOutput(opts({ saveShort: false, saveClip: false, saveSrt: false }))).toBe(false);
    expect(hasOutput(DEFAULT_OUTPUT_OPTIONS)).toBe(true);
  });
});

describe('describeOutputs', () => {
  it('summarises the selection', () => {
    expect(describeOutputs(opts({ saveClip: true, saveShort: true }))).toBe(
      'Save cut, short (captions: burn in).',
    );
  });
  it('reports nothing selected', () => {
    expect(describeOutputs(opts({ saveShort: false }))).toBe('Nothing selected to save.');
  });
});
