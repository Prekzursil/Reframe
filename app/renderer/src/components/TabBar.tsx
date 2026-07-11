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

/**
 * A named cluster of tabs (WU-3a2 progressive disclosure). `tabIds` reference
 * TabDef ids in render order; a group flagged `advanced` sits behind the
 * "Advanced" disclosure toggle. This is a purely VISUAL grouping layer — every
 * referenced tab still renders as a real, reachable `role="tab"` button (nothing
 * is removed), so the tablist stays complete.
 */
export interface TabGroup {
  id: string;
  label: string;
  tabIds: string[];
  advanced?: boolean;
}

export interface TabBarProps {
  tabs: TabDef[];
  active: string;
  onSelect: (id: string) => void;
  /**
   * ADDITIVE (WU-3a2): when provided, the tabs render in NAMED clusters with
   * section labels + separators instead of one flat strip. Omitted → the
   * original flat behaviour (unchanged). Every tab in `tabs` should be covered
   * by exactly one group's `tabIds`, but the flat fallback remains authoritative
   * for the full set.
   */
  groups?: TabGroup[];
  /** Whether the advanced cluster(s) are expanded. Ignored without `groups`. */
  advancedOpen?: boolean;
  /** Toggle handler for the "Advanced" disclosure. Ignored without `groups`. */
  onToggleAdvanced?: () => void;
  /**
   * ADDITIVE (design-review P1): a persistent Export/Deliver action rendered in
   * the grouped strip. EXPORT is the user's terminal goal, so it gets a standing
   * affordance even though the full Deliver cluster stays collapsed behind
   * "Advanced". When provided (grouped mode only), a prominent "Export" button
   * renders; omitted → nothing extra (unchanged). The host owns what Export does
   * (jump to the deliver panel), keeping this component presentational.
   */
  onExport?: () => void;
}

/**
 * The keyboard/focus context threaded to every rendered tab so the flat strip and
 * the grouped clusters share ONE roving-tabindex + arrow-key model (mirrors
 * TopTabBar's tabs pattern). `onKeyDown` is bound per-tab by id; `registerRef`
 * records each button so `onKeyDown` can move focus to the newly-selected tab.
 */
interface TabNav {
  active: string;
  onSelect: (id: string) => void;
  onKeyDown: (event: React.KeyboardEvent<HTMLButtonElement>, id: string) => void;
  registerRef: (id: string) => (el: HTMLButtonElement | null) => void;
}

/** One tab button. Shared by the flat strip and the grouped clusters so the
 *  `role="tab"` / `aria-selected` / roving-tabindex / id-wiring / test-pinned class
 *  contract is identical. */
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
      aria-controls={tabPanelId(tab.id)}
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

/** One labelled cluster of tab buttons. The `<section>` is a PURELY VISUAL
 *  wrapper, so it carries `role="presentation"` to flatten it out of the
 *  accessibility tree — this exposes its `role="tab"` children as DIRECT children
 *  of the enclosing `role="tablist"` (satisfying WCAG aria-required-parent /
 *  aria-required-children, which resolve ownership on the presentation-flattened
 *  tree). It deliberately has NO `aria-label`: a labelled section maps to
 *  `role="region"`, which would (a) revoke `role="presentation"` and (b) sit as a
 *  non-tab node between the tablist and its tabs. The visible cluster name stays
 *  as the decorative, `aria-hidden` caption below. */
function renderGroup(
  group: TabGroup,
  byId: Record<string, TabDef>,
  nav: TabNav,
): React.ReactElement {
  return (
    <section className="tabbar__group" key={group.id} role="presentation">
      <span className="tabbar__group-label" aria-hidden="true">
        {group.label}
      </span>
      {group.tabIds.map((id) => renderTab(byId[id], nav))}
    </section>
  );
}

/**
 * A horizontal tab strip. Accessible: role=tablist + aria-selected.
 *
 * Two rendering modes, chosen by the presence of `groups`:
 *   - FLAT (default, unchanged): one row of tab buttons.
 *   - GROUPED (WU-3a2): NAMED clusters with section labels; clusters flagged
 *     `advanced` are collapsed behind an "Advanced" disclosure toggle. Purely a
 *     visual layer — the tab behaviour (select-on-click) is identical.
 */
export function TabBar({
  tabs,
  active,
  onSelect,
  groups,
  advancedOpen = false,
  onToggleAdvanced,
  onExport,
}: TabBarProps): React.ReactElement {
  // A plain ref map (NOT useRef) so this presentational component stays hook-free
  // and can still be invoked directly in unit tests. React populates it via each
  // tab's ref callback after commit; the last committed render's map is the one the
  // keydown handler closes over, so focus targets the live buttons.
  const btnRefs: { current: Record<string, HTMLButtonElement | null> } = { current: {} };

  // The flat, keyboard-REACHABLE tab order for roving-tabindex arrow nav. In flat
  // mode that is every tab; in grouped mode it is the primary clusters' tabs plus
  // the advanced clusters' tabs ONLY when the advanced disclosure is open, so arrow
  // keys never land focus on a tab inside a `hidden` collapsed cluster.
  const orderedIds = groups
    ? [
        ...groups.filter((group) => !group.advanced).flatMap((group) => group.tabIds),
        ...(advancedOpen
          ? groups.filter((group) => group.advanced).flatMap((group) => group.tabIds)
          : []),
      ]
    : tabs.map((tab) => tab.id);

  const move = (toIndex: number): void => {
    const nextId = orderedIds[toIndex];
    onSelect(nextId);
    // Move focus to the newly-selected tab so keyboard users stay in sync. A
    // rendered, reachable tab always has its ref recorded, so assert non-null and
    // fail loud rather than silently skip focus (no silent fallback).
    btnRefs.current[nextId]!.focus();
  };

  const onKeyDown = (event: React.KeyboardEvent<HTMLButtonElement>, id: string): void => {
    const index = orderedIds.indexOf(id);
    // A tab outside the reachable order (a hidden collapsed-cluster tab) does not
    // participate in arrow navigation.
    if (index === -1) return;
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

  if (!groups) {
    return (
      <div className="tabbar" role="tablist">
        {tabs.map((tab) => renderTab(tab, nav))}
      </div>
    );
  }

  const byId: Record<string, TabDef> = {};
  for (const tab of tabs) {
    byId[tab.id] = tab;
  }
  const primary = groups.filter((group) => !group.advanced);
  const advanced = groups.filter((group) => group.advanced);

  return (
    <div className="tabbar tabbar--grouped">
      {/* The role="tablist" is an INNER wrapper holding ONLY the tab clusters, so
          in the accessibility tree it owns EXCLUSIVELY role="tab" elements
          (surfaced through the presentation group wrappers). The non-tab controls
          — the Advanced disclosure toggle and Export — are rendered as SIBLINGS of
          the tablist, never descendants, so the tablist never owns a non-tab
          child (WCAG aria-required-children). */}
      <div className="tabbar__tablist" role="tablist">
        {primary.map((group) => renderGroup(group, byId, nav))}
        {advanced.length > 0 ? (
          <div className="tabbar__advanced-panel" hidden={!advancedOpen}>
            {advanced.map((group) => renderGroup(group, byId, nav))}
          </div>
        ) : null}
      </div>
      {advanced.length > 0 ? (
        <button
          type="button"
          className="tabbar__advanced-toggle"
          aria-expanded={advancedOpen}
          onClick={onToggleAdvanced}
        >
          Advanced
        </button>
      ) : null}
      {onExport ? (
        <button type="button" className="tabbar__export" onClick={onExport}>
          Export
        </button>
      ) : null}
    </div>
  );
}

export default TabBar;
