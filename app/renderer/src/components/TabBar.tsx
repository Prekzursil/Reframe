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
  /**
   * Which way this strip is LAID OUT, which decides both the announced
   * `aria-orientation` and which arrow keys walk it. Default `'horizontal'`.
   *
   * Not cosmetic. `views/workspace.css:260-263` renders
   * `.workspace .workspace__inspector .tabbar` with `flex-direction: column`, so
   * that strip is vertical on screen — while this component declared no
   * `aria-orientation` (WAI-ARIA DEFAULTS it to horizontal) and moved focus only on
   * ArrowLeft/ArrowRight. A keyboard user facing a visibly vertical list pressed
   * Down and nothing happened; Right, which points ACROSS the list rather than
   * along it, was the only key that worked, and a screen reader announced a
   * horizontal list that is not one.
   *
   * The two key models are kept DISTINCT rather than accepting every arrow
   * everywhere: the APG specifies Left/Right for horizontal and Up/Down for
   * vertical, and answering both would violate it in the other direction.
   */
  orientation?: 'horizontal' | 'vertical';
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
 * rather than asserted: the cases under
 * TabBar.test.tsx > "TabBar skin contract (every emitted class has a rule)"
 * pin one case per shape — a quoted attribute (the shape the deleted grouped code
 * used, so re-adding that code in its original form IS caught), a single- OR
 * double-quoted literal inside a brace expression (ternary or a clsx-style helper),
 * and a template literal with or without interpolation. Comments are stripped first,
 * so naming a class in this very block is a mention, not an emission. MEASURED LIMIT:
 * a class held in a CONSTANT stays invisible — resolving it needs a parser and a
 * scope model, which a source-text extractor is not. That hole has its own pinning
 * test —
 * TabBar.test.tsx > "does NOT see a class held in a constant (documented residual, not a bug)"
 * — so widening the extractor forces this paragraph to be widened with it.
 *
 * SCOPE LIMIT on that guarantee, mechanical — and CORRECTING the wording pushed in
 * 5614bdbc, which said a `git revert` of the deletion IS caught. It is not. A literal
 * `git revert` of the deleting commit d5b37dbe removes the guard along with the code
 * the guard watches: that ONE commit deleted grouped mode, ADDED this contract, and
 * repaired the shell.css citation (`git show d5b37dbe --stat` — TabBar.tsx,
 * TabBar.test.tsx and shell.css, 140 insertions / 297 deletions), so reverting it
 * also restores the false citation that masked the 7th unstyled class on the first
 * run. The contract protects a HAND re-add, not a revert of its own commit. Settling
 * experiment: `git revert -n d5b37dbe` on a scratch branch, then run the renderer
 * suite — it is green. Closing it properly needs the guard in a commit the deletion
 * can be reverted without.
 *
 * TWO CLAIMS IN THIS BLOCK ARE MACHINE-CHECKED, because the extractor above strips
 * comments by design and so can never read its own documentation: this file's line
 * count, and every `TabBar.test.tsx > "…"` name cited here. Both are pinned by
 * TabBar.test.tsx > "TabBar self-citation contract (claims about this file are machine-checked)"
 * — added because round 1 of this branch shipped both errors at once.
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
 * TWO PARTIALLY-OVERLAPPING rot surfaces, not one nested set. Measured over that
 * file as it stands in this tree (3157 lines; re-measure before acting on it, the
 * docs lane owns it): 56 lines mention a class this branch deleted, and of the 67
 * lines carrying a `TabBar.tsx:<n>` citation, 41 cite n >= 200. Their UNION is 73
 * lines and their INTERSECTION 24 — so neither set contains the other, and the two
 * counts cannot be read as kinds of one 56.
 *
 * WHY they are stale, in the only terms that stay true: 24 of the 41 ALSO name a
 * class this branch deleted, so they send a reader to a line for markup that exists
 * nowhere in this file any more — a reason INDEPENDENT of how long this file happens
 * to be. The other 17 are NOT-CHECKED here; settling experiment: read them against
 * this file one by one. Others cite `workspace.css:116` / `:148-152` / `:189-192` in a
 * 302-line file that has had ZERO `tabbar__` matches since #431. IMPOSSIBLE
 * PRESCRIPTIONS: eight lines (:379, :417, :766, :781, :798, :807, :814, :924) tell a
 * reader to add a `.tabbar__advanced-panel[hidden]` rule for a defect that can no
 * longer occur.
 *
 * PAST-EOF IS THE WRONG CRITERION — it has now produced two false sentences in a row,
 * and BOTH died in the commit that wrote them. 5614bdbc wrote that the file was 200
 * lines "so `:231` and `:239` are past EOF". True at the PARENT abae7b61, where it WAS
 * 200; the same commit grew it +70/-24 to 246 and left the sentence standing (two
 * probes: `git log -S` puts the sentence in 5614bdbc, `git diff --numstat abae7b61
 * 5614bdbc` puts the +46 there too). At 246, `:231` is blank, `:239` is a `return (`,
 * and 9 of the 11 distinct cited values >= 200 — 215, 231, 236, 238, 239, 243, 244,
 * 245, 246, 248, 254 — are in range. Rescoping that to "12 are past EOF at 246"
 * repeated the mistake ONE COMMIT LATER: 3c89ad59 asserted the 12 while its own added
 * lines pushed this file past 254, so the count was already ZERO when it landed. The
 * past-EOF count simply moves with this file's length, hitting zero at any length
 * >= 254, the largest value the ledger cites. A criterion whose value changes when you
 * edit the file it describes is not a criterion, so the stale-content reason above is
 * the one recorded. Kept as a correction rather than a quiet edit, for the reason the
 * shell.css repair established. The one claim here a machine CAN check is now checked,
 * so the next author is told rather than trusted: this file is 323 lines.
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
export function TabBar({
  tabs,
  active,
  onSelect,
  navIds,
  orientation = 'horizontal',
}: TabBarProps): React.ReactElement {
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
    // The APG pairs the walking keys to the ORIENTATION: Left/Right along a
    // horizontal strip, Up/Down along a vertical one. Answering both everywhere
    // would satisfy each case while violating the spec in the other direction, so
    // the off-axis key is deliberately ignored (pinned by test).
    const forward = orientation === 'vertical' ? 'ArrowDown' : 'ArrowRight';
    const backward = orientation === 'vertical' ? 'ArrowUp' : 'ArrowLeft';
    if (event.key === forward) {
      event.preventDefault();
      move(index === last ? 0 : index + 1);
      return;
    }
    if (event.key === backward) {
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
    <div className="tabbar" role="tablist" aria-orientation={orientation}>
      {tabs.map((tab) => renderTab(tab, nav))}
    </div>
  );
}

export default TabBar;
