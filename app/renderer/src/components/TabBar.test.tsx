// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { readFileSync, readdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { TabBar, tabId, tabPanelId, type TabDef } from './TabBar';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const TABS: TabDef[] = [
  { id: 'a', label: 'Alpha' },
  { id: 'b', label: 'Beta' },
];

describe('TabBar', () => {
  it('renders all tab labels with role=tab', () => {
    const html = renderToStaticMarkup(<TabBar tabs={TABS} active="a" onSelect={() => {}} />);
    expect(html).toContain('Alpha');
    expect(html).toContain('Beta');
    expect(html).toContain('role="tablist"');
    expect((html.match(/role="tab"/g) ?? []).length).toBe(2);
  });

  it('marks only the active tab as selected', () => {
    const html = renderToStaticMarkup(<TabBar tabs={TABS} active="b" onSelect={() => {}} />);
    // Beta (active) gets aria-selected="true"; exactly one true.
    expect((html.match(/aria-selected="true"/g) ?? []).length).toBe(1);
    expect(html).toContain('tab--active');
  });

  it('declares aria-controls on the SELECTED tab only (no dangling IDREFs)', () => {
    // CRITICAL a11y regression (axe `aria-valid-attr-value`, measured in CI):
    // every consumer of TabBar renders exactly ONE `role="tabpanel"` whose id is
    // `tabPanelId(active)` — so an `aria-controls` on a NON-selected tab points at
    // an element that does not exist in the DOM. axe reported
    // `Invalid ARIA attribute value: aria-controls="tabpanel-make"` on Make Shorts.
    //
    // ARIA 1.2 makes `aria-controls` on `tab` OPTIONAL, so the correct fix is to
    // emit it only for the selected tab rather than to mount every panel.
    const html = renderToStaticMarkup(<TabBar tabs={TABS} active="a" onSelect={() => {}} />);
    const controls = html.match(/aria-controls="([^"]+)"/g) ?? [];
    expect(controls.length).toBe(1);
    expect(html).toContain(`aria-controls="${tabPanelId('a')}"`);
    // The inactive tab must NOT claim to control a panel that is not rendered.
    expect(html).not.toContain(`aria-controls="${tabPanelId('b')}"`);
  });

  it('moves aria-controls with the selection', () => {
    const html = renderToStaticMarkup(<TabBar tabs={TABS} active="b" onSelect={() => {}} />);
    expect(html).toContain(`aria-controls="${tabPanelId('b')}"`);
    expect(html).not.toContain(`aria-controls="${tabPanelId('a')}"`);
  });

  it('calls onSelect with the clicked tab id', () => {
    // Verify the onClick handler wiring via a shallow invocation.
    const onSelect = vi.fn();
    const el = TabBar({ tabs: TABS, active: 'a', onSelect }) as React.ReactElement;
    // The rendered element is a div containing two button elements.
    const children = el.props.children as React.ReactElement[];
    children[1].props.onClick();
    expect(onSelect).toHaveBeenCalledWith('b');
  });
});

// The grouped-cluster suite that stood here (WU-3a2: `groups` / `advancedOpen` /
// `onToggleAdvanced` / `onExport`) was REMOVED with the branch it exercised. Those
// eight tests were green the whole time #431 shipped a Workspace with no grouped
// skin — they asserted on emitted markup and never asked whether that markup had a
// stylesheet, so they read as coverage of a path no caller could safely use. The
// skin contract at the bottom of this file is the guard that would have caught it.

// WU-a11y: the ARIA tabs keyboard model (roving tabindex + arrow/Home/End nav +
// tab↔panel id wiring), ported from TopTabBar. Rendered under jsdom so focus and
// key handling are exercised for real.
describe('TabBar keyboard model (roving tabindex + arrow nav)', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });
  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  const renderBar = (props: React.ComponentProps<typeof TabBar>): void => {
    act(() => root.render(<TabBar {...props} />));
  };
  const btn = (id: string): HTMLButtonElement =>
    container.querySelector(`[data-tab-id="${id}"]`) as HTMLButtonElement;
  const key = (el: HTMLElement, k: string): void => {
    act(() => {
      el.dispatchEvent(new KeyboardEvent('keydown', { key: k, bubbles: true, cancelable: true }));
    });
  };

  it('applies roving tabindex (only active is 0) and id/aria-controls wiring', () => {
    renderBar({ tabs: TABS, active: 'a', onSelect: () => {} });
    expect(btn('a').getAttribute('tabindex')).toBe('0');
    expect(btn('b').getAttribute('tabindex')).toBe('-1');
    expect(btn('a').id).toBe(tabId('a'));
    expect(btn('a').getAttribute('aria-controls')).toBe(tabPanelId('a'));
    // REVISED: this previously asserted the INACTIVE tab also carried
    // `aria-controls="tabpanel-b"`. That assertion pinned a defect — consumers
    // render only ONE tabpanel (`tabPanelId(active)`), so the inactive tab's IDREF
    // dangled and axe failed CI with a CRITICAL `aria-valid-attr-value`. The
    // original claim was never checked against whether that panel exists.
    expect(btn('b').getAttribute('aria-controls')).toBeNull();
  });

  it('ArrowRight / ArrowLeft move selection and focus, wrapping at both ends', () => {
    const onSelect = vi.fn();
    renderBar({ tabs: TABS, active: 'a', onSelect });
    // ArrowRight from a (index 0, not last) -> b, and focus follows.
    key(btn('a'), 'ArrowRight');
    expect(onSelect).toHaveBeenLastCalledWith('b');
    expect(document.activeElement).toBe(btn('b'));
    // ArrowRight from b (last) wraps to a.
    key(btn('b'), 'ArrowRight');
    expect(onSelect).toHaveBeenLastCalledWith('a');
    expect(document.activeElement).toBe(btn('a'));
    // ArrowLeft from a (index 0) wraps to b (last).
    key(btn('a'), 'ArrowLeft');
    expect(onSelect).toHaveBeenLastCalledWith('b');
    // ArrowLeft from b (index 1, not 0) -> a.
    key(btn('b'), 'ArrowLeft');
    expect(onSelect).toHaveBeenLastCalledWith('a');
  });

  it('Home selects the first tab and End selects the last', () => {
    const onSelect = vi.fn();
    renderBar({ tabs: TABS, active: 'a', onSelect });
    key(btn('b'), 'Home');
    expect(onSelect).toHaveBeenLastCalledWith('a');
    key(btn('a'), 'End');
    expect(onSelect).toHaveBeenLastCalledWith('b');
  });

  it('ignores non-navigation keys (no selection change)', () => {
    const onSelect = vi.fn();
    renderBar({ tabs: TABS, active: 'a', onSelect });
    key(btn('a'), 'x');
    expect(onSelect).not.toHaveBeenCalled();
  });

  // F18: `navIds` marks the tabs whose activation navigates AWAY and unmounts this
  // tablist. Arrow-stepping onto one of those must MOVE FOCUS ONLY (ARIA APG
  // manual activation) — automatic activation there ejected the keyboard user out
  // of the surface being navigated.
  //
  // RETARGETED to the flat strip. These three previously drove `navIds` through the
  // grouped branch, but `navIds` is checked in `move()` for BOTH modes, so grouped
  // mode was never what they measured — it was scaffolding. Deleting it changes the
  // fixture, not the behaviour under test.
  it('arrow-stepping onto a navIds tab moves focus only, never activating it', () => {
    const onSelect = vi.fn();
    renderBar({ tabs: TABS, active: 'a', onSelect, navIds: ['b'] });
    key(btn('a'), 'ArrowRight');
    expect(onSelect).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(btn('b'));
  });

  // Membership is per-TARGET, not "navIds is non-empty ⇒ the whole strip is
  // manual". This pins the scope so a later implementation cannot silently convert
  // every tab to manual activation the moment one nav id exists.
  it('arrow-stepping onto a NON-member still activates while navIds is present', () => {
    const onSelect = vi.fn();
    renderBar({ tabs: TABS, active: 'b', onSelect, navIds: ['b'] });
    // ArrowRight from b (last) wraps to a, which is NOT a nav id.
    key(btn('b'), 'ArrowRight');
    expect(onSelect).toHaveBeenLastCalledWith('a');
    expect(document.activeElement).toBe(btn('a'));
  });

  it('still ACTIVATES a navIds tab on a deliberate click', () => {
    const onSelect = vi.fn();
    renderBar({ tabs: TABS, active: 'a', onSelect, navIds: ['b'] });
    act(() => {
      btn('b').dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    expect(onSelect).toHaveBeenCalledWith('b');
  });
});

// SKIN CONTRACT. A component may not ship a class name that no stylesheet styles.
//
// This pins the exact cross-branch defect that produced it: PR #431 deleted the
// grouped-TabBar block (`.tabbar--grouped` / `.tabbar__*`) from views/workspace.css
// while TabBar.tsx still implemented grouped mode in full. Nothing went red, because
// every unit test asserted on the emitted MARKUP and no test ever asked whether that
// markup had a skin. The next caller to pass `groups=` would have rendered a
// completely unstyled strip.
//
// Reading the SOURCE (not one rendered instance) is deliberate: a prop-gated branch
// renders only when some caller opts in, so a render-based check is blind to exactly
// the case that bites — the branch nobody calls yet. The source always shows it.
describe('TabBar skin contract (every emitted class has a rule)', () => {
  const SRC_ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');

  /** Every `.css` under the renderer source tree — the full corpus that could
   *  legitimately style this component (shell.css, views/workspace.css, ...). */
  const cssFiles = (dir: string): string[] =>
    readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
      const full = join(dir, entry.name);
      if (entry.isDirectory()) return cssFiles(full);
      return entry.name.endsWith('.css') ? [full] : [];
    });

  /** Class names a component emits: plain `className="a b"` plus the string
   *  literals inside a `className={cond ? 'a b' : 'a'}` expression. */
  const emittedClasses = (source: string): string[] => {
    const found = new Set<string>();
    const add = (list: string): void => {
      for (const cls of list.split(/\s+/)) if (cls) found.add(cls);
    };
    for (const m of source.matchAll(/className="([^"]*)"/g)) add(m[1]);
    for (const m of source.matchAll(/className=\{([^}]*)\}/g))
      for (const literal of m[1].matchAll(/'([^']*)'/g)) add(literal[1]);
    return [...found].sort();
  };

  it('declares a CSS rule for every class name TabBar.tsx renders', () => {
    const source = readFileSync(join(SRC_ROOT, 'components', 'TabBar.tsx'), 'utf8');
    const classes = emittedClasses(source);
    // Detector control: if the extractor ever silently stops finding classes, an
    // empty list would make the assertion below vacuously true. `.tab` is the one
    // class this component cannot stop emitting.
    expect(classes).toContain('tab');

    const css = cssFiles(SRC_ROOT)
      .map((file) => readFileSync(file, 'utf8'))
      // USE, NOT MENTION. Comments must be stripped before the search or a class
      // merely NAMED in prose reads as styled. Measured, not theorised: on the first
      // run of this test `.tabbar__advanced-toggle` — deleted from workspace.css by
      // #431 — was reported STYLED, because shell.css's focus-ring comment still
      // cited it as a live example. 6 of the 7 unstyled classes were found and the
      // 7th was masked by a sentence about it.
      .map((sheet) => sheet.replace(/\/\*[\s\S]*?\*\//g, ' '))
      .join('\n');
    // `(?![\w-])` is load-bearing: without it `.tab` would match `.tabbar` and a
    // genuinely unstyled class could report as styled by a longer neighbour.
    const unstyled = classes.filter((cls) => !new RegExp(`\\.${cls}(?![\\w-])`).test(css));
    expect(unstyled).toEqual([]);
  });
});
