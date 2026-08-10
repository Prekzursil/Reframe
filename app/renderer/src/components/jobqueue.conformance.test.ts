// jobqueue.conformance.test.ts — status-pill legibility guard for the Jobs
// slide-over (W13 / audit H4b-c).
//
// The pain this pins: jobqueue.css shipped colour rules for `--running`,
// `--error`, `--done` and `--interrupted` but NOT for `--cancelled`, so a
// cancelled row fell through to the base `.jobqueue__status` colour
// (`--text-muted`) — byte-identical to a `queued` row. A user could not tell a
// job they had stopped from a job that had not started
// (docs/plans/v1.5/uiux-qol-audit-2026-08.md:198-199).
//
// Style of check follows styles/tokens.conformance.test.ts: read the sheet as
// text, assert token discipline. This file imports no TS source; it is a pure
// style-file conformance check (styles are .css, outside the coverage scope).

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

import { describe, it, expect } from 'vitest';

const HERE = dirname(fileURLToPath(import.meta.url));
const JOBQUEUE_CSS = resolve(HERE, 'jobqueue.css');

/** Strip comment blocks so documentation prose never trips the scan.
 * (Deliberately a local copy of the same two-line helper in
 * styles/tokens.conformance.test.ts — importing across test files would execute
 * that suite's module body here too.) */
function stripComments(css: string): string {
  return css.replace(/\/\*[\s\S]*?\*\//g, '');
}

/** The declaration body of the FIRST rule whose selector matches exactly. */
function ruleBody(css: string, selector: string): string | null {
  const escaped = selector.replace(/[.\\+*?[^\]$(){}=!<>|:\-#]/g, '\\$&');
  const match = new RegExp(`${escaped}\\s*\\{([^}]*)\\}`).exec(css);
  return match ? match[1] : null;
}

/** The `--token` a rule body sets `color` to, or null if it is not a var(). */
function colorToken(body: string | null): string | null {
  if (body === null) return null;
  const match = /color:\s*var\((--[a-z0-9-]+)\)/i.exec(body);
  return match ? match[1] : null;
}

const CSS = stripComments(readFileSync(JOBQUEUE_CSS, 'utf8'));

describe('jobqueue status pills (W13 / audit H4b-c)', () => {
  it('every wire status except queued has its OWN colour rule', () => {
    // JobInfo.status is the six-value union in lib/rpc/schemas.ts:1467. `queued`
    // is the one deliberate omission: waiting-to-start IS the neutral base state,
    // so it inherits `.jobqueue__status`.
    for (const status of ['running', 'error', 'done', 'interrupted', 'cancelled']) {
      expect(ruleBody(CSS, `.jobqueue__status--${status}`)).not.toBeNull();
    }
  });

  it('cancelled uses a token colour that no sibling status and no base rule uses', () => {
    const base = colorToken(ruleBody(CSS, '.jobqueue__status'));
    const cancelled = colorToken(ruleBody(CSS, '.jobqueue__status--cancelled'));
    // It routes through the token layer (no one-off hex in component CSS)…
    expect(cancelled).toMatch(/^--/);
    // …and it is not the base fallback it used to silently inherit.
    expect(base).toBe('--text-muted');
    expect(cancelled).not.toBe(base);
    // …nor any other status hue (which would make two states look alike).
    for (const status of ['running', 'error', 'done', 'interrupted']) {
      expect(cancelled).not.toBe(colorToken(ruleBody(CSS, `.jobqueue__status--${status}`)));
    }
  });

  it('cancelled is separated by more than hue alone', () => {
    // HONEST SCOPE: --text-faint and --text-muted are adjacent steps on the text
    // ladder (#a6aebd vs #adb4c2 in styles/tokens.css:51,58), so the hue delta by
    // itself is small and would be a weak signal for a low-vision reader. The
    // strikethrough — the conventional "voided" mark — is what actually carries
    // the distinction; the token swap only stops it reading as loud as a live
    // label. This asserts the non-colour channel exists.
    const body = ruleBody(CSS, '.jobqueue__status--cancelled') ?? '';
    expect(body).toMatch(/text-decoration:\s*line-through/);
  });
});
