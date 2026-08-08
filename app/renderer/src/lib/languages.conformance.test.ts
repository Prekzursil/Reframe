// Conformance test for the renderer <-> sidecar LANGUAGE mirror (v1.5 captions §2 D5).
//
// The language inventory has to exist on both sides of the RPC boundary: the
// renderer needs it to build the picker, the sidecar needs it to validate and to
// route. Two hand-maintained copies is exactly the bug class that produced FOUR
// disagreeing vocabularies (docs/plans/v1.5/captions-translation-audit-2026-08.md
// §1.1). So the copies are pinned against each other here, the same way
// captionTemplates.conformance.test.ts pins the caption-style mirror.
//
// It reads the REAL sidecar sources (not a fixture), so adding a language on one
// side without the other fails the build. Runs in the default node environment
// (filesystem access, no jsdom). Tests run with cwd = app/, so repo paths are
// resolved relative to this file via import.meta.url.
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

import {
  COMMON_CODES,
  LANGUAGES,
  PARAKEET_LANGS,
  TRANSLATE_TIER1,
  TRANSLATE_TIER2,
  WHISPER_LANGS,
} from './languages';

// app/renderer/src/lib -> repo root is four levels up.
const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(HERE, '..', '..', '..', '..');

const SIDECAR_LANGUAGES = resolve(REPO_ROOT, 'sidecar', 'media_studio', 'features', 'languages.py');
const SIDECAR_TRANSLATION = resolve(
  REPO_ROOT,
  'sidecar',
  'media_studio',
  'models',
  'translation.py',
);

/** The body of a `<NAME>... = frozenset({ ... })` binding in a python source. */
function frozensetBody(src: string, name: string, where: string): string {
  const m = src.match(new RegExp(`${name}[^=]*=\\s*frozenset\\(\\s*\\{([\\s\\S]*?)\\}\\s*\\)`));
  if (!m) throw new Error(`could not find ${name} frozenset in ${where}`);
  return m[1];
}

/** Every double-quoted token in `body`, in source order. */
function quoted(body: string): string[] {
  return [...body.matchAll(/"([^"]*)"/g)].map((x) => x[1]);
}

function sidecarSrc(): string {
  return readFileSync(SIDECAR_LANGUAGES, 'utf8');
}

const asSet = (xs: Iterable<string>): Set<string> => new Set(xs);

describe('renderer <-> sidecar language mirror (v1.5 captions D5)', () => {
  it('WHISPER_LANGS matches, and is the measured 100', () => {
    const py = quoted(frozensetBody(sidecarSrc(), 'WHISPER_LANGS', 'languages.py'));
    expect(py.length).toBe(100);
    expect(new Set(py).size).toBe(py.length);
    expect(asSet(py)).toEqual(asSet(WHISPER_LANGS));
  });

  it('PARAKEET_LANGS matches, and is the measured 25', () => {
    const py = quoted(frozensetBody(sidecarSrc(), 'PARAKEET_LANGS', 'languages.py'));
    expect(py.length).toBe(25);
    expect(asSet(py)).toEqual(asSet(PARAKEET_LANGS));
  });

  it('the MT tiers match, and are the measured 40 / 12', () => {
    const src = sidecarSrc();
    const t1 = quoted(frozensetBody(src, 'TIER1_LANGS', 'languages.py'));
    const t2 = quoted(frozensetBody(src, 'TIER2_LANGS', 'languages.py'));
    expect(t1.length).toBe(40);
    expect(t2.length).toBe(12);
    expect(asSet(t1)).toEqual(asSet(TRANSLATE_TIER1));
    expect(asSet(t2)).toEqual(asSet(TRANSLATE_TIER2));
  });

  it('translation.py RE-EXPORTS the tiers instead of re-forking a copy', () => {
    // The routing table used to own these sets; they now live in languages.py so
    // the picker and the router share ONE definition. Re-declaring a literal here
    // would silently re-open the drift this whole file exists to close, so assert
    // the binding is an alias and carries no inline members.
    const tr = readFileSync(SIDECAR_TRANSLATION, 'utf8');
    for (const name of ['TIER1_LANGS', 'TIER2_LANGS']) {
      const m = tr.match(new RegExp(`^${name}[^=]*=\\s*(.+)$`, 'm'));
      if (!m) throw new Error(`translation.py no longer binds ${name}`);
      expect(m[1].trim()).toBe(`_languages.${name}`);
    }
    expect(tr).toMatch(/from \.\.features import languages as _languages/);
  });

  it('the ORDER and the LABELS match, code for code', () => {
    const src = sidecarSrc();
    const lm = src.match(/LANGUAGE_LABELS[^=]*=\s*\{([\s\S]*?)\n\}/);
    if (!lm) throw new Error('could not find LANGUAGE_LABELS dict in languages.py');
    const pairs = [...lm[1].matchAll(/"([^"]+)":\s*"([^"]+)"/g)].map((x) => [x[1], x[2]]);
    expect(pairs.length).toBe(102);
    // Same codes, same labels, SAME ORDER as the renderer picker list.
    expect(pairs).toEqual(LANGUAGES.map((l) => [l.code, l.label]));
  });

  it('COMMON_CODES matches, in the same curated order', () => {
    const src = sidecarSrc();
    const cm = src.match(/COMMON_CODES[^=]*=\s*\(([\s\S]*?)\)/);
    if (!cm) throw new Error('could not find COMMON_CODES tuple in languages.py');
    expect(quoted(cm[1])).toEqual([...COMMON_CODES]);
  });

  it('the parsers actually parse (detector control — a silent 0 would pass every set test)', () => {
    // A regex that stops matching would yield [] on BOTH sides of a `toEqual`
    // only if the renderer were empty too; these guards make a broken parser
    // fail loudly instead of quietly agreeing with nothing.
    expect(() => frozensetBody('nothing here', 'WHISPER_LANGS', 'x')).toThrow(/WHISPER_LANGS/);
    expect(quoted('"a", "b"')).toEqual(['a', 'b']);
    expect(quoted('no quotes')).toEqual([]);
  });
});
