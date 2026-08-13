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
 * Measured before removal — zero production callers: `git grep "groups="`
 * matched test files only, and all seven `<TabBar` call sites (App.tsx:678,
 * Deliver.tsx:62, MakeShorts.tsx:314, Repurpose.tsx:28, Settings.tsx:308,
 * Workspace.tsx:619 and :647) pass exactly `tabs` / `active` / `onSelect`.
 * Workspace.test.tsx:894-967 independently asserts the grouped classes are
 * ABSENT. The skin contract in TabBar.test.tsx now fails on any emitted class
 * that no stylesheet declares, so this cannot silently recur.
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
