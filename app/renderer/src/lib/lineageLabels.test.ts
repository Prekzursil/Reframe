import { describe, expect, it } from 'vitest';

import { captionLabel, makerLabel, modelLabel, opLabel, presetLabel } from './lineageLabels';
import type { LineageProvenance } from './rpc';

function prov(over: Partial<LineageProvenance> = {}): LineageProvenance {
  return {
    op: 'shortmaker.select',
    status: 'done',
    startedAt: '2026-06-29T00:00:00Z',
    endedAt: '2026-06-29T00:00:00Z',
    params: null,
    appVersion: '1.1.0',
    preset: 'Punchy',
    route: { mode: 'local', model: 'qwen2.5:7b' },
    ...over,
  };
}

describe('opLabel', () => {
  it('maps a known op id to a friendly verb, keeping the raw id', () => {
    expect(opLabel('shortmaker.select')).toEqual({
      label: 'Found highlights',
      raw: 'shortmaker.select',
    });
  });

  it('shows an UNKNOWN op verbatim (no faked friendliness)', () => {
    expect(opLabel('mystery.op')).toEqual({ label: 'mystery.op', raw: 'mystery.op' });
  });

  it('returns null for a blank op', () => {
    expect(opLabel('')).toBeNull();
  });
});

describe('modelLabel', () => {
  it('returns null for a null route', () => {
    expect(modelLabel(null)).toBeNull();
  });

  it('returns null when the route names neither model nor mode', () => {
    expect(modelLabel({})).toBeNull();
  });

  it('combines a known model name with its locality', () => {
    expect(modelLabel({ mode: 'local', model: 'qwen2.5:7b' })).toEqual({
      label: 'Qwen2.5 7B (on this PC)',
      raw: 'qwen2.5:7b',
    });
  });

  it('shows an unknown model + unknown mode verbatim', () => {
    expect(modelLabel({ mode: 'fog', model: 'gpt-x' })).toEqual({
      label: 'gpt-x (fog)',
      raw: 'gpt-x',
    });
  });

  it('uses just the model name when no mode is recorded', () => {
    expect(modelLabel({ model: 'qwen2.5:7b' })).toEqual({ label: 'Qwen2.5 7B', raw: 'qwen2.5:7b' });
  });

  it('uses just the locality when no model is recorded', () => {
    expect(modelLabel({ mode: 'cloud' })).toEqual({ label: 'cloud', raw: 'cloud' });
  });

  it('ignores non-string model/mode values (treated as absent)', () => {
    expect(modelLabel({ model: 123, mode: 456 })).toBeNull();
  });
});

describe('presetLabel', () => {
  it('passes a preset through (already friendly), with raw parity', () => {
    expect(presetLabel('Punchy')).toEqual({ label: 'Punchy', raw: 'Punchy' });
  });

  it('returns null for a null preset', () => {
    expect(presetLabel(null)).toBeNull();
  });

  it('returns null for an empty preset', () => {
    expect(presetLabel('')).toBeNull();
  });
});

describe('captionLabel', () => {
  it('maps a known caption template to its display name', () => {
    expect(captionLabel({ template: 'bold' })).toEqual({ label: 'Bold', raw: 'bold' });
  });

  it('shows an unknown caption template verbatim', () => {
    expect(captionLabel({ template: 'neon' })).toEqual({ label: 'neon', raw: 'neon' });
  });

  it('returns null when params are null', () => {
    expect(captionLabel(null)).toBeNull();
  });

  it('returns null when no template field is present', () => {
    expect(captionLabel({ prompt: 'x' })).toBeNull();
  });
});

describe('makerLabel', () => {
  it('builds the "Reframe vX" maker line from the agent app version', () => {
    expect(makerLabel(prov({ appVersion: '1.1.0' }))).toBe('Reframe v1.1.0');
  });

  it('returns null when the agent recorded no app version', () => {
    expect(makerLabel(prov({ appVersion: null }))).toBeNull();
  });

  it('returns null for an empty app version', () => {
    expect(makerLabel(prov({ appVersion: '' }))).toBeNull();
  });
});
