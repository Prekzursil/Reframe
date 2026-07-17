// fonts.conformance.test.ts — self-hosted @font-face conformance guard (WU-1.5 fonts).
//
// tokens.css leads each type family with a BUNDLED, non-generic face (Inter for
// --font-ui, Newsreader for --font-editorial, IBM Plex Mono for --font-mono). For
// those leads to actually render — instead of silently decaying to the system
// fallback — the binaries must be self-hosted and bound by `@font-face`. This file
// pins that binding so it can never regress:
//
//   1. Every `@font-face` `src` is a LOCAL, self-origin reference (a relative
//      `../assets/…` url) — NEVER a remote font CDN. The renderer CSP resolves
//      `font-src` from `default-src 'self'` (plus an explicit `font-src 'self'`),
//      so a `https://fonts.gstatic.com/…` url would be BLOCKED at runtime and
//      break the offline-first guarantee. This is the load-bearing security check.
//   2. Every referenced `.woff2` actually EXISTS on disk (a scaffolded-but-missing
//      binary would ship the bug this WU closes — a blank/fallback render).
//   3. `@font-face` family names EXACTLY match the token leads in tokens.css, so
//      the binding and the token can never drift apart.
//   4. `font-display: swap` on every face (text paints in the fallback immediately,
//      then swaps — no invisible-text flash on a local-but-not-yet-decoded font).
//   5. The variable faces expose the full weight ramp (Inter 100–900,
//      Newsreader 200–800) so the tokens' non-standard 650/750 steps render
//      natively rather than rounding to a static cut; IBM Plex Mono ships its
//      static 400/500 cuts (it has no official variable version).
//   6. The editorial serif ships an italic face (the pull-quote voice uses it).
//
// This file imports no TS source; it is a pure style-file conformance check and is
// excluded from the renderer coverage scope (styles/assets are not .ts/.tsx).

import { existsSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

import { describe, it, expect } from 'vitest';

const HERE = dirname(fileURLToPath(import.meta.url));
const FONTS_CSS = resolve(HERE, 'fonts.css');
const TOKENS_CSS = resolve(HERE, 'tokens.css');

/** One parsed `@font-face` rule. */
interface FontFace {
  family: string;
  style: string;
  weight: string;
  display: string;
  urls: string[];
}

/** The raw text of a single `@font-face { … }` body. */
function faceBodies(css: string): string[] {
  return Array.from(css.matchAll(/@font-face\s*\{([^}]*)\}/g)).map((m) => m[1]);
}

/** Read a single `prop: value;` declaration out of a face body (unquoted). */
function decl(body: string, prop: string): string {
  const m = new RegExp(`${prop}\\s*:\\s*([^;]+);`, 'i').exec(body);
  return (m?.[1] ?? '').trim().replace(/^["']|["']$/g, '');
}

/** Every `url(...)` target in a face body (quotes stripped). */
function urls(body: string): string[] {
  return Array.from(body.matchAll(/url\(\s*['"]?([^'")]+)['"]?\s*\)/g)).map((m) => m[1]);
}

function parseFaces(css: string): FontFace[] {
  return faceBodies(css).map((body) => ({
    family: decl(body, 'font-family'),
    style: decl(body, 'font-style'),
    weight: decl(body, 'font-weight'),
    display: decl(body, 'font-display'),
    urls: urls(body),
  }));
}

/** The FIRST family in a `font-family` list (before the first comma), unquoted. */
function leadFamily(value: string): string {
  return (value.split(',')[0] ?? '').trim().replace(/^["']|["']$/g, '');
}

/** The lead family of a `--token` in tokens.css. */
function tokenLead(tokensCss: string, token: string): string {
  const m = new RegExp(`${token}\\s*:\\s*([^;]+);`).exec(tokensCss);
  return leadFamily(m?.[1] ?? '');
}

const faces = parseFaces(readFileSync(FONTS_CSS, 'utf8'));
const tokensCss = readFileSync(TOKENS_CSS, 'utf8');

describe('self-hosted @font-face conformance (WU-1.5 fonts)', () => {
  it('defines at least one @font-face for each of the three type families', () => {
    const families = new Set(faces.map((f) => f.family));
    expect(families).toContain('Inter');
    expect(families).toContain('Newsreader');
    expect(families).toContain('IBM Plex Mono');
  });

  it('binds every @font-face to a LOCAL self-origin url — never a remote font CDN (CSP)', () => {
    const allUrls = faces.flatMap((f) => f.urls);
    expect(allUrls.length).toBeGreaterThan(0);
    for (const url of allUrls) {
      // No absolute/remote scheme or protocol-relative host: a font-src 'self'
      // CSP would block it and the offline-first guarantee would break.
      expect(url).not.toMatch(/^(https?:)?\/\//i);
      expect(url).not.toMatch(/gstatic|googleapis|fonts\.google/i);
      // Self-hosted assets are referenced relative to this stylesheet.
      expect(url.startsWith('./') || url.startsWith('../')).toBe(true);
    }
  });

  it('resolves every referenced .woff2 to a file that actually exists on disk', () => {
    const allUrls = faces.flatMap((f) => f.urls);
    for (const url of allUrls) {
      expect(url).toMatch(/\.woff2$/);
      expect(existsSync(resolve(HERE, url))).toBe(true);
    }
  });

  it('sets font-display: swap on every face (no invisible-text flash)', () => {
    expect(faces.length).toBeGreaterThan(0);
    for (const f of faces) {
      expect(f.display).toBe('swap');
    }
  });

  it('matches every @font-face family to the token lead it binds (no drift)', () => {
    expect(tokenLead(tokensCss, '--font-ui')).toBe('Inter');
    expect(tokenLead(tokensCss, '--font-editorial')).toBe('Newsreader');
    expect(tokenLead(tokensCss, '--font-mono')).toBe('IBM Plex Mono');
    const families = new Set(faces.map((f) => f.family));
    for (const token of ['--font-ui', '--font-editorial', '--font-mono'] as const) {
      expect(families).toContain(tokenLead(tokensCss, token));
    }
  });

  it('exposes the variable weight ramp so 650/750 render natively, plus static mono cuts', () => {
    const inter = faces.filter((f) => f.family === 'Inter');
    const news = faces.filter((f) => f.family === 'Newsreader');
    const mono = faces.filter((f) => f.family === 'IBM Plex Mono');
    // Variable faces carry a `min max` weight RANGE spanning the whole ramp.
    expect(inter.every((f) => f.weight === '100 900')).toBe(true);
    expect(news.every((f) => f.weight === '200 800')).toBe(true);
    // Mono is static: the 400 + 500 cuts the timecode voice uses.
    const monoWeights = new Set(mono.map((f) => f.weight));
    expect(monoWeights).toEqual(new Set(['400', '500']));
  });

  it('ships an italic face for the editorial serif (the pull-quote voice uses it)', () => {
    const newsItalic = faces.filter((f) => f.family === 'Newsreader' && f.style === 'italic');
    expect(newsItalic.length).toBeGreaterThan(0);
  });
});
