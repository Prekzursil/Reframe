// repurposeTemplates.test.ts — curated catalog + no-raw-method-id contract.

import { describe, it, expect } from 'vitest';

import {
  STARTER_TEMPLATES,
  EXPORT_METHOD,
  buildTemplateFromStarter,
  starterById,
} from './repurposeTemplates';

describe('STARTER_TEMPLATES', () => {
  it('every starter has a friendly name (no method id) and a build', () => {
    for (const starter of STARTER_TEMPLATES) {
      expect(starter.name).not.toContain('.');
      expect(typeof starter.build).toBe('function');
    }
  });

  it('every starter ends in an export step', () => {
    for (const starter of STARTER_TEMPLATES) {
      const steps = starter.build('v1');
      expect(steps.at(-1)?.method).toBe(EXPORT_METHOD);
    }
  });
});

describe('starterById', () => {
  it('returns the matching starter', () => {
    expect(starterById(STARTER_TEMPLATES[1].id)).toBe(STARTER_TEMPLATES[1]);
  });
  it('falls back to the first starter for an unknown id', () => {
    expect(starterById('__nope__')).toBe(STARTER_TEMPLATES[0]);
  });
});

describe('buildTemplateFromStarter', () => {
  const starter = STARTER_TEMPLATES[0];

  it('attaches exportTargets to the template field and the export step', () => {
    const tmpl = buildTemplateFromStarter(starter, 'My style', { count: 5 }, ['tiktok', 'shorts']);
    expect(tmpl.exportTargets).toEqual(['tiktok', 'shorts']);
    expect(tmpl.name).toBe('My style');
    expect(tmpl.defaultControls).toEqual({ count: 5 });
    const exportStep = tmpl.steps.find((s) => s.method === EXPORT_METHOD);
    expect(exportStep?.params.exportTargets).toEqual(['tiktok', 'shorts']);
  });

  it('leaves non-export steps untouched', () => {
    const tmpl = buildTemplateFromStarter(starter, 'X', {}, ['tiktok']);
    const nonExport = tmpl.steps.filter((s) => s.method !== EXPORT_METHOD);
    for (const step of nonExport) {
      expect(step.params).not.toHaveProperty('exportTargets');
    }
  });
});
