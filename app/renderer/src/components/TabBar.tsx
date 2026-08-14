import React from 'react';

export interface TabDef {
  id: string;
  label: string;
}

/** DOM id for a tab button — paired with its panel's `aria-labelledby`. */
export function tabId(id: string): string {
  return `tab-${id}`;
}

/** DOM id for a tab's panel — paired with the tab's `aria-controls`. */
export function tabPanelId(id: string): string {
  return `tabpanel-${id}`;
}

export interface TabBarProps {
  tabs: TabDef[];
  active: string;
  onSelect: (id: string) => void;
  /**
   * ADDITIVE (F18): ids whose activation navigates AWAY from this tablist, so
   * arrow-stepping must MOVE FOCUS onto them WITHOUT activating them. This is the
   * ARIA APG "manual activation" carve-out: automatic activation is only legal
   * when activation is instantaneous, and these ids activate into a route change
   * that UNMOUNTS the very tablist being navigated (focus would land on `<body>`
   * on another screen, unannounced). Deliberate activation still works — the
   * button's own `onClick` fires on click and on Enter/Space. Omitted → every tab
   * activates on arrow (the original behaviour, unchanged).
   *
   * TWO DISCLOSED RESIDUALS (do not read this prop as a complete APG fix):
   *   1. The roving tabindex DESYNCS. Skipping `onSelect` leaves `active`
   *      unchanged, so the DOM-focused nav tab keeps `tabIndex={-1}` while the
   *      still-active tab keeps `tabIndex={0}` — Tab away and Shift+Tab back
   *      returns to `active`, not to the arrowed-onto tab. A full fix needs a
   *      focused-tab state separate from `active` (a contract refactor).
   *   2. The tablist now has a MIXED activation model (automatic for most tabs,
   *      manual for the `navIds` members). Defensible under the APG carve-out
   *      above, but non-obvious — hence documented here, at the prop.
   */
  navIds?: string[];
}

/**
 * The keyboard/focus context threaded to every rendered tab, carrying ONE
 * roving-tabindex + arrow-key model (mirrors TopTabBar's tabs pattern).
 * `onKeyDown` is bound per-tab by id; `registerRef` records each button so
 * `onKeyDown` can move focus to the newly-selected tab.
 */
interface TabNav {
  active: string;
  onSelect: (id: string) => void;
  onKeyDown: (event: React.KeyboardEvent<HTMLButtonElement>, id: string) => void;
  registerRef: (id: string) => (el: HTMLButtonElement | null) => void;
}

/** One tab button, holding the `role="tab"` / `aria-selected` / roving-tabindex /
 *  id-wiring / test-pinned class contract. */
function renderTab(tab: TabDef, nav: TabNav): React.ReactElement {
  const isActive = tab.id === nav.active;
  return (
    <button
      key={tab.id}
      ref={nav.registerRef(tab.id)}
      type="button"
      role="tab"
      id={tabId(tab.id)}
      data-tab-id={tab.id}
      aria-selected={isActive}
      // Every TabBar consumer renders exactly ONE `role="tabpanel"`, whose id is
      // `tabPanelId(active)`. So `aria-controls` on a NON-selected tab would point
      // at an element that is not in the DOM — a dangling IDREF, which axe reports
      // as the CRITICAL `aria-valid-attr-value` violation
      // (`Invalid ARIA attribute value: aria-controls="tabpanel-make"`, measured in
      // CI on the Make Shorts screen). ARIA 1.2 makes `aria-controls` OPTIONAL on
      // `role="tab"`, so emitting it only for the selected tab is the correct fix —
      // strictly better than mounting every panel just to satisfy the reference.
      aria-controls={isActive ? tabPanelId(tab.id) : undefined}
      // Roving tabindex: only the active tab is in the tab order; the rest are
      // reached with the arrow keys.
      tabIndex={isActive ? 0 : -1}
      className={isActive ? 'tab tab--active' : 'tab'}
      onClick={() => nav.onSelect(tab.id)}
      onKeyDown={(event) => nav.onKeyDown(event, tab.id)}
    >
      {tab.label}
    </button>
  );
}

/**
 * A horizontal tab strip: one row of tab buttons.
 * Accessible: role=tablist + aria-selected.
 *
 * HISTORY (do not re-add without its stylesheet). This component also carried a
 * GROUPED mode — `groups` / `advancedOpen` / `onToggleAdvanced` / `onExport`,
 * emitting `.tabbar--grouped`, `.tabbar__tablist`, `.tabbar__group`,
 * `.tabbar__group-label`, `.tabbar__advanced-panel`, `.tabbar__advanced-toggle`
 * and `.tabbar__export`. PR #431 rebuilt the Workspace IA and deleted that skin
 * from views/workspace.css, but left the branch here, so the two halves only
 * disagreed when read together: the code shipped, the CSS did not, and the next
 * caller to pass `groups=` would have rendered a completely unstyled strip.
 *
 * NO PRODUCTION CALLER — two probes at the pre-deletion tree f8cfbd6c, one at
 * HEAD. At f8cfbd6c: (1) `git grep "groups="` over app/renderer/src, restricted to
 * non-test `.tsx`, returned no matches; and (2) enumerating call sites instead —
 * the probe a prop spread would defeat — showed all seven production sites
 * (App.tsx:678, Deliver.tsx:62, MakeShorts.tsx:314, Repurpose.tsx:28,
 * Settings.tsx:308, Workspace.tsx:619 and :647) passing exactly `tabs` / `active`
 * / `onSelect`. Those two query different FIELDS but are one instrument on one
 * tree. The mechanically different probe is `npx tsc --noEmit` -> exit 0, and it
 * belongs at HEAD: with `groups?` gone from TabBarProps, a surviving caller is an
 * excess JSX attribute and a type error, so the compiler resolves the re-exports,
 * aliases and spreads grep cannot see. CORRECTS commit abae7b61, which presented
 * all three as mechanically independent probes run at f8cfbd6c — run THERE, tsc is
 * INERT rather than circular: `groups?` was a legal optional prop, so exit 0 reads
 * identically whether or not a caller passes it. Workspace.test.tsx:894-967
 * independently asserts the grouped classes are ABSENT.
 *
 * WHAT THE SKIN CONTRACT GUARANTEES, exactly. TabBar.test.tsx fails on any class
 * this file emits that no renderer stylesheet declares, and its reach is measured
 * rather than asserted: "sees a re-added class in every shape a caller can write
 * it" pins one case per shape — a quoted attribute (the shape the deleted code
 * used, so a `git revert` of that deletion IS caught), a single- OR double-quoted
 * literal inside a brace expression (ternary or a clsx-style helper), and a
 * template literal with or without interpolation. Comments are stripped first, so
 * naming a class in this very block is a mention, not an emission. MEASURED LIMIT:
 * a class held in a CONSTANT stays invisible — resolving it needs a parser and a
 * scope model, which a source-text extractor is not. That hole has its own pinning
 * test, so widening the extractor forces this paragraph to be widened with it.
 *
 * SECOND UNCALLED SURFACE, disclosed not fixed. `navIds` also has ZERO production
 * callers: measured at this commit and at origin/main, every reference to it lives
 * in TabBar.tsx or TabBar.test.tsx, and the same seven call sites above pass none.
 * It is NOT deleted on grouped mode's grounds — that rationale was the code/skin
 * SPLIT, and `navIds` emits no class, so it carries no unstyled-render defect. But
 * it is the F18 manual-activation carve-out, so that a11y protection is wired into
 * no screen today, and the three retargeted `navIds` tests cover a behaviour no
 * shipped surface exercises. Whichever lane owns App.tsx / Workspace.tsx should
 * either pass `navIds` on the tablists whose tabs navigate away and unmount them,
 * or retire the prop.
 *
 * RESIDUAL, out of this file's scope — TWO stale surfaces, not one.
 *
 * (1) app/e2e/preview.spec.ts. Three tests would fail if run, their references
 * unguarded: "Advanced disclosure actually COLLAPSES the Deliver cluster (F17)" at
 * :190 (toggle/panel at :197-198, `toBeInViewport()` at :258), "Workspace tabs
 * mount, including SemanticSearch" at :279 (click at :298), and "export action
 * yields a real file" at :307 (click at :314). Of the 11 references only SIX are
 * executable `locator()` calls (:77, :197, :198, :258, :298, :314); the other five
 * are comments (:212, :244, :251, :295, :296). CORRECTS abae7b61, which counted all
 * 11 alike and named the global `test.afterEach` at :74 beside the three failing
 * tests: that hook returns early on `count() === 0` inside a try/catch (:79-85), so
 * it degrades to a no-op and cannot fail anything. Widening the removing commit's
 * "one stale test" to three was right; the hook is stale prose, not blast radius.
 *
 * (2) docs/validation/v15-audit-ledger.md — LARGER, and previously undisclosed.
 * 56 lines there cite the deleted classes, in two kinds of rot. DANGLING LINE
 * NUMBERS: 41 lines cite a `TabBar.tsx:` line at 200 or beyond (this file is 200
 * lines, so `:231` and `:239` are past EOF), and others cite `workspace.css:116` /
 * `:148-152` / `:189-192` in a 302-line file that has had ZERO `tabbar__` matches
 * since #431. IMPOSSIBLE PRESCRIPTIONS: eight lines (:379, :417, :766, :781, :798,
 * :807, :814, :924) tell a reader to add a `.tabbar__advanced-panel[hidden]` rule
 * for a defect that can no longer occur.
 *
 * Neither surface ships a defect and neither is on the merge path: docs are not
 * executable, `docs/validation/tools/verify_ssot_claims.py` is wired into no
 * workflow, and `.github/workflows/e2e.yml` triggers on `workflow_dispatch` plus a
 * nightly `schedule` ONLY — no `pull_request`, no `push`. Deleting grouped mode did
 * not break either; both were already dead, since those selectors can only match
 * markup grouped mode renders and no production caller has passed `groups=` since
 * #431. Recorded rather than fixed because both belong to other lanes, and recorded
 * rather than dropped for the reason the shell.css repair already established:
 * correct the sentence, never quietly delete it.
 */
export function TabBar({ tabs, active, onSelect, navIds }: TabBarProps): React.ReactElement {
  // A plain ref map (NOT useRef) so this presentational component stays hook-free
  // and can still be invoked directly in unit tests. React populates it via each
  // tab's ref callback after commit; the last committed render's map is the one the
  // keydown handler closes over, so focus targets the live buttons.
  const btnRefs: { current: Record<string, HTMLButtonElement | null> } = { current: {} };

  // The keyboard-REACHABLE tab order for roving-tabindex arrow nav: every tab.
  const orderedIds = tabs.map((tab) => tab.id);

  const move = (toIndex: number): void => {
    const nextId = orderedIds[toIndex];
    // MANUAL activation, scoped to the `navIds` members only (see the prop doc):
    // their activation destroys this tablist, so an arrow key may only move focus.
    // Every other tab keeps automatic activation (the ARIA APG default).
    if (!navIds?.includes(nextId)) {
      onSelect(nextId);
    }
    // Move focus to the newly-focused tab so keyboard users stay in sync. A
    // rendered, reachable tab always has its ref recorded, so assert non-null and
    // fail loud rather than silently skip focus (no silent fallback).
    btnRefs.current[nextId]!.focus();
  };

  const onKeyDown = (event: React.KeyboardEvent<HTMLButtonElement>, id: string): void => {
    // Always found: `onKeyDown` is bound only from the `tabs.map` below, and
    // `orderedIds` IS that same list, so every handler's id is a member. The
    // former `index === -1` guard existed only for grouped mode's hidden
    // collapsed-cluster tabs; with that branch gone it is unreachable, and an
    // unreachable branch cannot be covered by the 100% gate.
    const index = orderedIds.indexOf(id);
    const last = orderedIds.length - 1;
    if (event.key === 'ArrowRight') {
      event.preventDefault();
      move(index === last ? 0 : index + 1);
      return;
    }
    if (event.key === 'ArrowLeft') {
      event.preventDefault();
      move(index === 0 ? last : index - 1);
      return;
    }
    if (event.key === 'Home') {
      event.preventDefault();
      move(0);
      return;
    }
    if (event.key === 'End') {
      event.preventDefault();
      move(last);
      return;
    }
    // Any other key: let the browser handle it (no-op for nav).
  };

  const registerRef =
    (id: string) =>
    (el: HTMLButtonElement | null): void => {
      btnRefs.current[id] = el;
    };
  const nav: TabNav = { active, onSelect, onKeyDown, registerRef };

  return (
    <div className="tabbar" role="tablist">
      {tabs.map((tab) => renderTab(tab, nav))}
    </div>
  );
}

export default TabBar;
