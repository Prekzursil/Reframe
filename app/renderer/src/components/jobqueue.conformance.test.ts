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
const SCHEMAS_TS = resolve(HERE, '..', 'lib', 'rpc', 'schemas.ts');

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

/**
 * The `JobInfo.status` union, read OUT OF THE SCHEMA rather than restated here.
 *
 * W45: the first version of this guard hardcoded a five-name array and carved
 * `queued` out in a comment. That made it structurally unable to see the defect
 * class it exists for — a status shipping with no colour rule. Adding a SEVENTH
 * member to the union in schemas.ts would have left this file green, exactly as
 * `cancelled` (the sixth) was green before H4c was reported. Deriving the list
 * from the declaration means a new status cannot ship unstyled by omission: it
 * either gets a rule or this test fails.
 *
 * DETECTOR LIMIT (stated, not hidden): this reads the single-line
 * `status: 'a' | 'b';` form that `JobInfo` uses today. A union reformatted across
 * lines, or aliased to a named type, would return an empty list — which is why
 * the control test below asserts a member COUNT and two specific members rather
 * than trusting the parse.
 */
/**
 * Status pairs that resolve to the SAME `color` token, as `"--token: a + b"`.
 *
 * A status with no rule at all is SKIPPED, not folded in as a collision: absence
 * is the completeness test's finding, and reporting it here too would make one
 * cause fail two tests and obscure which is which.
 */
function colourCollisions(css: string, statuses: readonly string[]): readonly string[] {
  const byToken = new Map<string, string[]>();
  for (const status of statuses) {
    const token = colorToken(ruleBody(css, `.jobqueue__status--${status}`));
    if (token === null) continue;
    byToken.set(token, [...(byToken.get(token) ?? []), status]);
  }
  return [...byToken.entries()]
    .filter(([, names]) => names.length > 1)
    .map(([token, names]) => `${token}: ${[...names].sort().join(' + ')}`)
    .sort();
}

function wireStatuses(): readonly string[] {
  const src = readFileSync(SCHEMAS_TS, 'utf8');
  const decl = /\bstatus:\s*((?:'[a-z-]+'\s*\|\s*)+'[a-z-]+')\s*;/.exec(src);
  if (decl === null) return [];
  return [...decl[1].matchAll(/'([a-z-]+)'/g)].map((m) => m[1]);
}

const CSS = stripComments(readFileSync(JOBQUEUE_CSS, 'utf8'));

describe('jobqueue status pills (W13 / audit H4b-c / W45)', () => {
  it('reads the status union out of schemas.ts (the parser actually parsed)', () => {
    // Control the instrument BEFORE trusting the completeness test below: a regex
    // that silently stopped matching would return [] and make that test vacuous.
    const statuses = wireStatuses();
    expect(statuses).toHaveLength(6);
    // Spot-anchor both ends of the union so a partial match cannot pass on count.
    expect(statuses).toContain('queued');
    expect(statuses).toContain('interrupted');
    // …and prove it is not just echoing anything asked of it.
    expect(statuses).not.toContain('definitely-not-a-status');
  });

  it('every wire status has its OWN colour rule — all six, none by omission', () => {
    const missing = wireStatuses()
      .filter((status) => ruleBody(CSS, `.jobqueue__status--${status}`) === null)
      .sort();
    expect(
      missing,
      'These JobInfo.status values render a `.jobqueue__status--<status>` class ' +
        '(components/JobQueue.tsx:225) with no rule at all, so they fall through to ' +
        'the base `.jobqueue__status` colour and read identically to each other. ' +
        'Add a rule in components/jobqueue.css (tokens only).',
    ).toEqual([]);
  });

  it('cancelled uses a token colour that no sibling status and no base rule uses', () => {
    const base = colorToken(ruleBody(CSS, '.jobqueue__status'));
    const cancelled = colorToken(ruleBody(CSS, '.jobqueue__status--cancelled'));
    // It routes through the token layer (no one-off hex in component CSS)…
    expect(cancelled).toMatch(/^--/);
    // …and it is not the base fallback it used to silently inherit.
    expect(base).toBe('--text-muted');
    expect(cancelled).not.toBe(base);
    // …nor any other status hue (which would make two states look alike). Derived
    // from the union, so a new status is compared too rather than silently skipped.
    for (const status of wireStatuses().filter((s) => s !== 'cancelled')) {
      expect(cancelled).not.toBe(colorToken(ruleBody(CSS, `.jobqueue__status--${status}`)));
    }
  });

  it('the colour-collision finder FIRES on a known collision (both-states control)', () => {
    // Run the finder against a fixture where two statuses DELIBERATELY share a
    // token, and require it to report that pair. Without this, an always-empty
    // result would make the assertion below vacuously green — the exact failure
    // mode that let H4c ship under a suite that was already passing.
    const collided = [
      '.jobqueue__status--queued { color: var(--text-muted); }',
      '.jobqueue__status--cancelled { color: var(--text-muted); }',
    ].join('\n');
    expect(colourCollisions(collided, ['queued', 'cancelled'])).toEqual([
      '--text-muted: cancelled + queued',
    ]);
    // …and stays silent when the same two carry different tokens. `replace` with a
    // STRING pattern rewrites only the first hit, so this re-tokens `queued` alone.
    const distinct = collided.replace('var(--text-muted)', 'var(--text-faint)');
    expect(distinct).not.toBe(collided); // the fixture really did change
    expect(colourCollisions(distinct, ['queued', 'cancelled'])).toEqual([]);
  });

  it('no two wire statuses share a colour token (W45 — the H4c defect, generalised)', () => {
    // H4c was reported as one pair (`cancelled` reading identically to `queued`).
    // The requirement it implies is pairwise: any two statuses that resolve to the
    // same token are indistinguishable at a glance, whichever pair they are. Every
    // member now carries its own rule, so this is checkable across the whole union
    // instead of for the one pair that happened to be noticed.
    expect(
      colourCollisions(CSS, wireStatuses()),
      'Two or more job statuses resolve to the SAME colour token, so a user cannot ' +
        'tell them apart by hue. Either give one its own token or separate them on a ' +
        'non-colour channel (as `cancelled` does with line-through).',
    ).toEqual([]);
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
