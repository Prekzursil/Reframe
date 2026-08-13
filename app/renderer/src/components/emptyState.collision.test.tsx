// emptyState.collision.test.tsx — the shared skin may reach the components that
// own it, and NOTHING else.
//
// WHY THIS FILE EXISTS (measured, not hypothetical). The first cut of
// emptyState.css declared a BARE `.empty-state` root rule. That name was already
// taken: panels/ModelsSystemPanel.tsx renders `<div className="empty-state">` for
// its pre-analysis prompt, skinned by panels/modelsSystem.css under
// `.models-system-panel .empty-state`. The panel rule wins every property it
// declares (0,2,0 beats 0,1,0) but it declares NO `text-align`, so the shared
// rule's `text-align: center` was the ONLY declaration matching that element and
// leaked into a live surface — order-independent, and invisible to every gate the
// branch runs: vitest's jsdom has no layout, no e2e selector mentions the class,
// and the visual baselines are stale.
//
// The probe that missed it measured consumers of the <EmptyState /> COMPONENT and
// concluded the stylesheet had none. The right probe is one collection lower: who
// emits the CLASS. Both are pinned here — the cascade behaviour (tests 1-2) and
// the ownership rule that would have caught it in the first place (test 3).
// @vitest-environment jsdom
import { readFileSync, readdirSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { EmptyState } from './EmptyState';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

// `import.meta.url` is not a file:// URL under the jsdom environment, so resolve
// from the vitest root (app/) instead — the same dir CI runs the suite from, and
// the convention Skeleton.test.tsx already uses.
const SRC_ROOT = resolve(process.cwd(), 'renderer', 'src');
const SHARED_CSS = readFileSync(join(SRC_ROOT, 'components', 'emptyState.css'), 'utf8');
const PANEL_CSS = readFileSync(join(SRC_ROOT, 'panels', 'modelsSystem.css'), 'utf8');

/** Every property the shared root rule declares — the whole leak surface. */
const ROOT_PROPS = [
  'display',
  'flexDirection',
  'alignItems',
  'gap',
  'padding',
  'textAlign',
] as const;

type RootStyle = Record<(typeof ROOT_PROPS)[number], string>;

/** Read the declared-and-cascaded values of {@link ROOT_PROPS} off one element. */
function snapshot(el: Element): RootStyle {
  const cs = getComputedStyle(el);
  const out = {} as RootStyle;
  for (const prop of ROOT_PROPS) out[prop] = cs[prop];
  return out;
}

/** Run `fn` with `sheets` live in the document, in the order given, then remove them. */
function withSheets<T>(sheets: readonly string[], fn: () => T): T {
  const nodes = sheets.map((css) => {
    const node = document.createElement('style');
    node.textContent = css;
    document.head.appendChild(node);
    return node;
  });
  try {
    return fn();
  } finally {
    for (const node of nodes) node.remove();
  }
}

/** The foreign surface, copied from ModelsSystemPanel's pre-analysis prompt. */
const FOREIGN_SHAPE = `
  <section class="feature-panel models-system-panel" aria-label="Models and System">
    <div class="empty-state" data-section="prompt">
      <p class="empty-state__title">See what your machine can run</p>
      <p class="empty-state__body">Run a quick local check to see which models fit.</p>
      <button class="empty-state__cta" type="button">Analyze my system</button>
    </div>
  </section>`;

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => {
    root.unmount();
  });
  container.remove();
});

async function mount(node: React.ReactElement): Promise<void> {
  await act(async () => {
    root.render(node);
  });
}

describe('emptyState.css — the shared skin cannot reach a surface it does not own', () => {
  it('is a NO-OP on another surface that already owns the class name', () => {
    const host = document.createElement('div');
    host.innerHTML = FOREIGN_SHAPE;
    document.body.appendChild(host);
    const foreign = host.querySelector('.models-system-panel .empty-state');
    expect(foreign).not.toBeNull();
    if (foreign === null) return;

    // Sheet order is ADVERSARIAL against this assertion: the shared sheet goes
    // LAST, the position most favourable to it. Comparing the two states (with
    // and without the shared sheet) rather than hardcoding an expected value
    // keeps this honest if a sibling lane edits the panel skin — both sides move
    // together, and only a rule that MATCHES this element breaks the equality.
    //
    // SCOPE, measured rather than assumed: jsdom's cascade is order-driven, not
    // specificity-aware (proven by running this probe in both sheet orders — the
    // winner follows position, so `.models-system-panel .empty-state` at (0,2,0)
    // does NOT beat `.empty-state` at (0,1,0) here). So the failure this printed
    // before the fix over-states WHICH properties a real browser loses: Chromium
    // leaks only the property the panel rule never declares (`text-align`). The
    // invariant asserted here is the engine-independent one — no rule in this
    // sheet may match a foreign element at all — which is the actual defect.
    const withShared = withSheets([PANEL_CSS, SHARED_CSS], () => snapshot(foreign));
    const panelOnly = withSheets([PANEL_CSS], () => snapshot(foreign));
    host.remove();

    expect(withShared).toEqual(panelOnly);
  });

  it('DOES skin the root the component emits (control: the probe can see this sheet)', async () => {
    await mount(
      <EmptyState
        poster
        title="No video open"
        hint="Open a video from the Library."
        action={{ label: '← Library', onClick: vi.fn() }}
      />,
    );
    const own = container.firstElementChild;
    expect(own).not.toBeNull();
    if (own === null) return;

    // Without this control, test 1 could pass because jsdom ignores the sheet
    // entirely — an inert control that proves only that the file parsed. These
    // two assertions are the properties test 1 says must NOT leak, measured on
    // the element that SHOULD carry them.
    const skinned = withSheets([SHARED_CSS], () => snapshot(own));
    expect(skinned.display).toBe('flex');
    expect(skinned.textAlign).toBe('center');
  });

  it('declares no unscoped class that production markup outside these components emits', () => {
    const owners = ['components/EmptyState.tsx', 'components/Skeleton.tsx'];
    const emitters = classAttributeEmitters();

    const offenders = firstCompoundClasses(SHARED_CSS)
      .map((cls) => ({ cls, files: (emitters.get(cls) ?? []).filter((f) => !owners.includes(f)) }))
      .filter((hit) => hit.files.length > 0);

    expect(offenders).toEqual([]);
  });
});

/**
 * The first compound class of every rule — what the sheet can reach with no
 * ancestor to scope it. `.skeleton-group .skeleton--line` is scoped and cannot
 * touch a bare `.skeleton--line`, so only the LEADING class matters here.
 *
 * Deliberately a 20-line reader rather than a CSS parser dependency: the sheet
 * has no at-rules today, and an `@media` prelude has no leading `.` so it is
 * skipped rather than mis-read.
 */
function firstCompoundClasses(css: string): string[] {
  const found = new Set<string>();
  for (const block of css.replace(/\/\*[\s\S]*?\*\//g, '').split('}')) {
    const selectorList = block.split('{')[0];
    if (selectorList === undefined) continue;
    for (const selector of selectorList.split(',')) {
      const match = /^\s*\.([A-Za-z0-9_-]+)/.exec(selector);
      if (match?.[1] !== undefined) found.add(match[1]);
    }
  }
  return [...found];
}

/**
 * class token -> the renderer sources that emit it in STATIC markup, keyed by a
 * path relative to `app/renderer/src`.
 *
 * Scope disclosed: STATIC `className="…"` / `class="…"` / `` className={`…`} ``
 * attributes in non-test `.tsx` only. A computed `className={block}` is invisible
 * to it — that is exactly why test 1 measures the cascade too, and neither test
 * subsumes the other. Tests are excluded on purpose: they name classes in
 * SELECTORS, which is a mention, not an emission.
 */
function classAttributeEmitters(): Map<string, string[]> {
  const attr = /class(?:Name)?=(?:"([^"]*)"|'([^']*)'|\{`([^`]*)`\})/g;
  const emitters = new Map<string, string[]>();

  for (const file of tsxFiles(SRC_ROOT)) {
    const rel = file.slice(SRC_ROOT.length + 1).replaceAll('\\', '/');
    const text = readFileSync(file, 'utf8');
    for (const match of text.matchAll(attr)) {
      const value = match[1] ?? match[2] ?? match[3] ?? '';
      for (const token of value.split(/[\s${}]+/)) {
        if (token === '') continue;
        const seen = emitters.get(token);
        if (seen === undefined) emitters.set(token, [rel]);
        else if (!seen.includes(rel)) seen.push(rel);
      }
    }
  }
  return emitters;
}

/** Every non-test `.tsx` under `dir`, recursively. */
function tsxFiles(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) {
      if (entry.name !== 'node_modules') out.push(...tsxFiles(full));
    } else if (entry.name.endsWith('.tsx') && !entry.name.includes('.test.')) {
      out.push(full);
    }
  }
  return out;
}
