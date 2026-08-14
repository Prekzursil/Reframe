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

/** Source text with every comment blanked out.
 *
 *  USE, NOT MENTION — shared deliberately by BOTH contracts below, so they cannot
 *  drift apart. The skin contract strips comments so a class merely NAMED in
 *  TabBar.tsx's history block is not read as an emission; the self-citation
 *  contract strips them so a test name merely NAMED in a comment is not read as a
 *  live test. Round 3 shipped the second guard WITHOUT the strip and the two DID
 *  drift: a cited test renamed with its old name left behind in a comment stayed
 *  green. One definition is the fix for that class, not a second copy of the regex.
 */
const stripComments = (source: string): string =>
  source.replace(/\/\*[\s\S]*?\*\//g, ' ').replace(/\/\/[^\n]*/g, ' ');

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

  // ── VERTICAL ORIENTATION (the inspector tablist) ─────────────────────────
  //
  // THE DEFECT: views/workspace.css:260-263 renders
  // `.workspace .workspace__inspector .tabbar` with `flex-direction: column`, so that
  // tab list is VERTICAL on screen. TabBar declared no `aria-orientation` (which
  // DEFAULTS to horizontal per WAI-ARIA) and moved focus only on ArrowLeft/ArrowRight.
  //
  // So a keyboard user facing a visibly vertical list pressed Down and nothing
  // happened, while Right — which points across the list rather than along it — was
  // the only key that worked; a screen reader announced a horizontal list that is not.
  // WAI-ARIA APG: a vertical tablist declares aria-orientation="vertical" and moves
  // with Up/Down. The strip is mounted twice inside `.workspace`, so this is the most
  // exposed tab list in the app, not an edge case.
  it('declares aria-orientation="vertical" when asked for a vertical strip', () => {
    renderBar({ tabs: TABS, active: 'a', onSelect: () => {}, orientation: 'vertical' });
    expect(container.querySelector('[role="tablist"]')?.getAttribute('aria-orientation')).toBe(
      'vertical',
    );
  });

  it('still declares horizontal by DEFAULT, so no existing call site changes', () => {
    // DETECTOR CONTROL for the case above: a hardcoded attribute would pass that test
    // while telling us nothing. Every other call site relies on this default.
    renderBar({ tabs: TABS, active: 'a', onSelect: () => {} });
    expect(container.querySelector('[role="tablist"]')?.getAttribute('aria-orientation')).toBe(
      'horizontal',
    );
  });

  it('ArrowDown / ArrowUp move selection and focus when vertical, wrapping', () => {
    const onSelect = vi.fn();
    renderBar({ tabs: TABS, active: 'a', onSelect, orientation: 'vertical' });
    key(btn('a'), 'ArrowDown');
    expect(onSelect).toHaveBeenLastCalledWith('b');
    expect(document.activeElement).toBe(btn('b'));
    // wraps forward off the end...
    key(btn('b'), 'ArrowDown');
    expect(onSelect).toHaveBeenLastCalledWith('a');
    // ...and backward off the start.
    key(btn('a'), 'ArrowUp');
    expect(onSelect).toHaveBeenLastCalledWith('b');
  });

  it('a vertical strip ignores ArrowRight, and a horizontal one ignores ArrowDown', () => {
    // Keeps the two models DISTINCT. Handling every arrow everywhere would satisfy the
    // cases above while violating the APG in the other direction, so both halves are
    // pinned here rather than assumed.
    const onSelect = vi.fn();
    renderBar({ tabs: TABS, active: 'a', onSelect, orientation: 'vertical' });
    key(btn('a'), 'ArrowRight');
    expect(onSelect).not.toHaveBeenCalled();

    const onSelectH = vi.fn();
    renderBar({ tabs: TABS, active: 'a', onSelect: onSelectH });
    key(btn('a'), 'ArrowDown');
    expect(onSelectH).not.toHaveBeenCalled();
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

  /** The text inside each `className={…}`, read with a BRACE-BALANCING scan
   *  rather than a `[^}]*` capture. A capture stops at the FIRST `}`, which is
   *  the one closing a template literal's own `${…}` — so every class written as
   *  an interpolated template was silently invisible. */
  const braceExpressions = (source: string): string[] => {
    const out: string[] = [];
    const marker = 'className={';
    for (let at = source.indexOf(marker); at !== -1; at = source.indexOf(marker, at + 1)) {
      let depth = 0;
      let end = at + marker.length - 1; // the opening `{`
      while (end < source.length) {
        if (source[end] === '{') depth += 1;
        if (source[end] === '}') {
          depth -= 1;
          if (depth === 0) break;
        }
        end += 1;
      }
      out.push(source.slice(at + marker.length, end));
    }
    return out;
  };

  /** Every string literal inside one `className` brace expression: single-quoted,
   *  DOUBLE-quoted (the clsx/classnames idiom — previously unscanned, so
   *  `clsx("a")` was invisible while `clsx('a')` was seen), and the STATIC chunks
   *  of a template literal with its interpolations blanked out. */
  const literalsIn = (expr: string): string[] => [
    ...[...expr.matchAll(/'([^']*)'/g)].map((m) => m[1]),
    ...[...expr.matchAll(/"([^"]*)"/g)].map((m) => m[1]),
    ...[...expr.matchAll(/`([^`]*)`/g)].map((m) => m[1].replace(/\$\{[^}]*\}/g, ' ')),
  ];

  /** Class names a component emits: a plain quoted `className` attribute plus
   *  every string literal inside a `className={…}` expression.
   *
   *  Comments are stripped FIRST, for the same use-vs-mention reason the CSS side
   *  strips them: this reads TabBar.tsx's raw source, so a class merely named in
   *  that file's own history comment would otherwise read as an emission and
   *  demand a stylesheet rule for markup nothing renders. */
  const emittedClasses = (source: string): string[] => {
    const code = stripComments(source);
    const found = new Set<string>();
    // Only tokens SHAPED like a CSS class are kept. Blanking an interpolation can
    // leave debris (`?`, a bare `:`), and asserting a stylesheet rule for debris
    // would be a false failure.
    const add = (list: string): void => {
      for (const cls of list.split(/\s+/)) if (/^[A-Za-z_-][\w-]*$/.test(cls)) found.add(cls);
    };
    for (const m of code.matchAll(/className="([^"]*)"/g)) add(m[1]);
    for (const expr of braceExpressions(code)) {
      for (const literal of literalsIn(expr)) add(literal);
    }
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

  // EXTRACTOR CONTRACT. The guarantee TabBar.tsx's comment makes — a re-added
  // grouped class cannot silently ship unstyled — is only ever as wide as
  // `emittedClasses`. These are the SHAPES a re-add can take; each is measured
  // here rather than assumed, so the sentence in TabBar.tsx cannot drift wider
  // than the mechanism that backs it.
  // ONE SHAPE PER CASE, deliberately. Collapsing these into a single `it` hides
  // evidence: vitest aborts a test at its FIRST failed assertion, so a bundled
  // version proves only that the first shape was ever broken and leaves the rest
  // inferred. Split, each shape is independently falsifiable — and each was
  // observed RED against the pre-widening extractor.
  it('SEES a class re-added via a template literal with interpolation', () => {
    // A `className=\{([^}]*)\}` capture truncates at the interpolation's own `}`,
    // so every class written before it vanished.
    expect(emittedClasses('<div className={`tabbar__tablist ${mode}`}>')).toContain(
      'tabbar__tablist',
    );
  });

  it('SEES a class re-added via a bare template literal', () => {
    expect(emittedClasses('<div className={`tabbar--grouped`}>')).toContain('tabbar--grouped');
  });

  it('SEES a class re-added as a DOUBLE-quoted argument in a brace expression', () => {
    // The clsx/classnames idiom. Only single-quoted literals used to be scanned
    // inside `className={…}`, so this was invisible while the identical
    // single-quoted call was seen — the least obvious of the four holes.
    expect(emittedClasses('<div className={clsx("tabbar__group", open)}>')).toContain(
      'tabbar__group',
    );
  });

  it('still sees the two shapes that already worked (no trade-off)', () => {
    // The quoted attribute is the shape the DELETED grouped code used, so a HAND
    // re-add of that code in its original form is caught. CORRECTED: this comment
    // used to claim a `git revert` of the deletion is caught. It is not — d5b37dbe
    // ADDED this contract in the same commit that deleted the code, so reverting it
    // takes the guard away with the code it guards. Kept so a later rewrite cannot
    // swap the new shapes in at the old ones' expense.
    expect(emittedClasses('<div className="tabbar__export">')).toContain('tabbar__export');
    expect(emittedClasses("<div className={on ? 'tabbar__group-label' : 'tab'}>")).toContain(
      'tabbar__group-label',
    );
  });

  // USE, NOT MENTION — the TS side of the hole already closed on the CSS side.
  // Stylesheet comments are stripped before matching, but this extractor reads
  // TabBar.tsx's RAW source, so a class merely NAMED in a doc comment there read
  // as an emission and the contract would demand a rule for a class nothing
  // renders. That is a false failure, and it silently forbids the file from
  // documenting its own history in the shapes it documents.
  it('ignores a class merely NAMED in a comment (use, not mention)', () => {
    const block = '/* HISTORY: className="tabbar__ghost" shipped without a skin. */';
    const line = '// see also className={`tabbar__relic ${x}`}';
    expect(emittedClasses(`${block}\n${line}\n<div className="tab">`)).toEqual(['tab']);
  });

  // MEASURED LIMIT, pinned deliberately. This case is GREEN before and after the
  // widening — it is a characterization pin, not a red-first test. A class held in
  // a constant is invisible to a source-text extractor: resolving it needs a
  // parser and a scope model, which this is not. If a later change makes this
  // assertion fail, the extractor got wider and the "MEASURED LIMIT" sentence in
  // TabBar.tsx must be widened in the same commit.
  it('does NOT see a class held in a constant (documented residual, not a bug)', () => {
    const src = "const CLS = 'tabbar__advanced-panel';\n<div className={CLS}>";
    expect(emittedClasses(src)).not.toContain('tabbar__advanced-panel');
  });
});

// SELF-CITATION CONTRACT. TabBar.tsx's history comment makes two claims about
// ITSELF — its own length, and the names of tests in THIS file — and both are
// falsified by any later commit that grows the file or renames a test. Nothing in
// the suite could evaluate them, and that is structural, not luck: the skin-contract
// extractor above STRIPS comments by design (the use-vs-mention fix), so no test can
// read prose in that block. Round 1 of this branch shipped both defects. It gave a
// length measured on the PARENT tree in the very commit that grew the file by 46
// lines, and it quoted a test name that the NEXT commit split into four. That is the
// same shape as the defect this branch exists to close — #424 cited
// `.tabbar__advanced-toggle`, #431 deleted the rule, nobody updated the sentence — so
// it is closed mechanically here instead of by promising to remember.
//
// HOW THESE TWO FAIL ON THE PRE-FIX TEXT — recorded here because commit 3c89ad59's
// message got it wrong and a commit message cannot be corrected in place. That
// message pasted `expected 200 to be 247` and a `toEqual([])` diff as "RED, verbatim,
// against the shipped text". Neither can come from the guards as shipped. Against
// TabBar.tsx@e72d483b both fail at their DETECTOR CONTROLS, before any value is
// compared: `/this file is (\d+) lines/` matches ZERO times there, because the phrase
// wraps a comment line (`this file is 200\n * lines, so …`), so the first failure is
// `expect(claimed).toHaveLength(1)` with received 0; and the `file > "name"` citation
// form did not exist before the commit that added these tests, so the second is
// `expect(cited.length).toBeGreaterThan(0)` with received 0. The operand is wrong
// too — the shipped formula yields 246 at e72d483b, not 247. The transcript came
// from a pre-commit DRAFT of these guards and was never re-run after the assertions
// were rewritten. The substance survives (both DO go red on the pre-fix text, via
// those controls) but the evidence was misattributed, which is this lane's own
// subject one level up: a pasted failure message is a function of the instrument
// that produced it, so it MUST be re-run after any change to the assertion, the
// regex or the formula. Corrected, not quietly dropped, for the reason the shell.css
// repair established.
describe('TabBar self-citation contract (claims about this file are machine-checked)', () => {
  const HERE = dirname(fileURLToPath(import.meta.url));
  const readSource = (name: string): string => readFileSync(join(HERE, name), 'utf8');

  it('pins the line count TabBar.tsx claims about itself to its real length', () => {
    const source = readSource('TabBar.tsx');
    const claimed = [...source.matchAll(/this file is (\d+) lines/g)];
    // Detector control, in BOTH directions. Zero matches would make the assertion
    // below vacuously true (the sentence quietly deleted); two would mean a later
    // author quoted the refuted wording verbatim and this measured the wrong one.
    expect(claimed).toHaveLength(1);
    const lines = source.split(/\r?\n/);
    const actual = lines[lines.length - 1] === '' ? lines.length - 1 : lines.length;
    expect(Number(claimed[0][1])).toBe(actual);
  });

  /** Test names TabBar.tsx cites in vitest's own `file > name` form.
   *
   *  `TabBar.test.tsx > "…"` is that path, adopted as the citation form precisely so
   *  a machine can check it. Bare quoted prose is NOT scanned: the same comment
   *  quotes three preview.spec.ts names, which belong to another file and another
   *  lane, and demanding those here would be a false failure the moment that lane
   *  renames one.
   *
   *  USE, NOT MENTION, one level up — and this is the round-3 defect. The sentence
   *  that DESCRIBES the citation form has to write the form out, and it writes it
   *  with a metasyntactic `…` (TabBar.tsx:150). The bare regex captured that
   *  placeholder as a fourth "citation", which then resolved for free because `…`
   *  occurs incidentally in this file's own comment prose — so the detector control
   *  below passed identically whether the citation form was in use or every real
   *  citation had been deleted. Excluding the placeholder is what makes that control
   *  able to fail at all.
   *
   *  The exclusion is NARROW on purpose: only a capture that is nothing but ellipsis
   *  and whitespace is dropped. Dropping every name that merely CONTAINS a `…` would
   *  silently stop checking a real citation, which is the quiet weakening this whole
   *  guard exists to prevent; a mixed placeholder such as `"… name …"` is instead
   *  captured and fails LOUDLY against a name that does not exist here. Fail loud,
   *  never quiet.
   */
  const citedTestNames = (source: string): string[] =>
    [...source.matchAll(/TabBar\.test\.tsx > "([^"]+)"/g)]
      .map((m) => m[1])
      .filter((name) => name.replace(/[…\s]/g, '') !== '');

  /** Cited names this file does not declare. Comments are stripped first, for the
   *  same use-vs-mention reason the skin contract strips them: a cited test renamed
   *  with its old name left behind in a comment is exactly the drift this guard
   *  exists to catch, and a raw substring test over the whole file cannot see it.
   *
   *  RESIDUAL, disclosed rather than implied away: containment over comment-free
   *  text is not a parse of the suite's DECLARED names, so a cited name surviving in
   *  some unrelated non-comment string literal would still resolve. Settling
   *  experiment: extract `describe(`/`it(` string literals instead and re-run this
   *  file — if the three citations still resolve, that check is strictly stronger
   *  and should replace this one. */
  const unresolvedCitations = (cited: readonly string[], self: string): string[] => {
    const code = stripComments(self);
    return cited.filter((name) => !code.includes(name));
  };

  it('pins every TabBar.test.tsx name TabBar.tsx cites to a name that exists here', () => {
    const source = readSource('TabBar.tsx');
    const self = readSource('TabBar.test.tsx');
    const cited = citedTestNames(source);
    // Detector control. It now DISTINGUISHES its two hypotheses: with the
    // placeholder excluded, deleting every real citation while keeping the sentence
    // that describes the form leaves this at zero and fails HERE. What it proves is
    // exactly that — at least one real citation is in use, so the filter below is
    // not vacuously empty — and not that the three specific ones are still cited.
    expect(cited.length).toBeGreaterThan(0);
    expect(unresolvedCitations(cited, self)).toEqual([]);
  });

  // GUARD ON THE GUARD. The two cases above are only as good as the two helpers
  // they call, and round 3 shipped a detector control that could not fail. These
  // pin the helpers directly, against inputs chosen to separate the hypotheses.
  it('does NOT count the sentence that DESCRIBES the citation form as a citation', () => {
    const source = readSource('TabBar.tsx');
    // The settling experiment, executed rather than promised: keep ONLY the sentence
    // that describes the citation form and delete every real citation. If the
    // control above means anything, nothing is cited in this state.
    const describing = source.split(/\r?\n/).filter((line) => line.includes('> "…"'));
    // Detector control for THIS case: the placeholder sentence must be present and
    // unique, or the assertion below is about a string that no longer exists.
    expect(describing).toHaveLength(1);
    expect(citedTestNames(describing[0])).toEqual([]);
  });

  it('still checks a real name that merely CONTAINS an ellipsis (fail loud, never quiet)', () => {
    // The exclusion is deliberately narrow. Dropping every capture that CONTAINS a
    // `…` would silently stop checking a real citation — the same class of quiet
    // weakening this guard exists to catch. Only a capture that is nothing but the
    // placeholder is a mention; a mixed one like `"… name …"` is still captured and
    // fails loudly against a name that does not exist here.
    expect(citedTestNames('TabBar.test.tsx > "a real … name"')).toEqual(['a real … name']);
  });

  it('does NOT resolve a cited name that survives only in a COMMENT (use, not mention)', () => {
    const mentionOnly = "// CORRECTED: this case used to be called 'renamed away'.";
    expect(unresolvedCitations(['renamed away'], mentionOnly)).toEqual(['renamed away']);
  });

  it('DOES resolve a cited name that is really declared here', () => {
    // The other half of the pair: stripping comments must not blind the check to a
    // name that a live `it(...)` declares. Without this, deleting every citation
    // would also read as success.
    const declared = "it('renamed away', () => {});";
    expect(unresolvedCitations(['renamed away'], declared)).toEqual([]);
  });
});
