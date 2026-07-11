// TopTabBar.tsx — the application's TOP-LEVEL navigation, presented as a vertical
// LEFT RAIL (v1.5 pro-shell). Despite the historical name it renders a rail, not
// a top strip; the swap is PRESENTATIONAL ONLY — the component API, ids, roles,
// and routing contract are unchanged (App still derives `active` from the route).
//
// This is the primary surface switcher (Library · Make Shorts · Edit · Director ·
// Settings). It is a full ARIA tablist (role=tablist/tab) with
// aria-orientation="vertical" (the role-complete rail), distinct from the
// lightweight `TabBar` used for in-view sub-tabs:
//   * roving tabindex — exactly ONE tab is in the tab order at a time; the rest
//     are reached with the arrow keys (arrow moves selection AND focus, which
//     suits a router),
//   * ArrowUp/ArrowDown are the primary axis for the vertical rail, with
//     ArrowLeft/ArrowRight kept as equivalents; all four wrap around the ends;
//     Home/End jump to first/last,
//   * each tab is wired to its panel via id ↔ aria-controls / aria-labelledby,
//   * the active tab is unmistakable: accent color + a 2px accent EDGE BAR +
//     aria-selected="true" (color is NOT the only signal),
//   * icons are inline Lucide-style 24×24 SVGs (never emoji), decorative
//     (aria-hidden) since the visible label carries the accessible name.
//
// The component is presentational: it owns no route state. The host (App)
// derives `active` from the route and re-renders on select.
import React, { useRef } from 'react';
import './topTabBar.css';

/** A single top-level tab. `icon` is a decorative inline SVG (Lucide-style). */
export interface TopTab {
  id: string;
  label: string;
  icon: React.ReactNode;
  /** Optional count surfaced as a text badge (e.g. interrupted Repurpose batches). */
  badge?: number;
}

export interface TopTabBarProps {
  tabs: TopTab[];
  active: string;
  onSelect: (id: string) => void;
  /** Accessible name for the tablist (defaults to "Primary"). */
  label?: string;
}

/** DOM id for a tab button — paired with its panel's aria-labelledby. */
export function topTabId(id: string): string {
  return `toptab-${id}`;
}

/** DOM id for a tab's panel — paired with the tab's aria-controls. */
export function topTabPanelId(id: string): string {
  return `toptabpanel-${id}`;
}

/**
 * The left navigation rail. Keyboard model (roving tabindex + arrow nav):
 *   ArrowDown / ArrowRight → next tab (wraps to first past the end)
 *   ArrowUp   / ArrowLeft  → previous tab (wraps to last before the start)
 *   Home                   → first tab
 *   End                    → last tab
 * Any other key is a no-op (native button click/Enter/Space still activate).
 */
export function TopTabBar({
  tabs,
  active,
  onSelect,
  label = 'Primary',
}: TopTabBarProps): React.ReactElement {
  const btnRefs = useRef<Record<string, HTMLButtonElement | null>>({});

  const move = (toIndex: number): void => {
    const next = tabs[toIndex];
    onSelect(next.id);
    // Move focus to the newly-selected tab so keyboard users stay in sync.
    // The ref is always populated for a rendered tab; the guard is a runtime
    // safety net only (e.g. a tab removed mid-keypress).
    const el = btnRefs.current[next.id];
    /* v8 ignore next -- el is always set for a rendered tab. */
    if (el) el.focus();
  };

  const onKeyDown = (event: React.KeyboardEvent<HTMLButtonElement>, index: number): void => {
    const last = tabs.length - 1;
    // Vertical rail: Down/Up are the primary axis; Right/Left kept as equivalents.
    if (event.key === 'ArrowDown' || event.key === 'ArrowRight') {
      event.preventDefault();
      move(index === last ? 0 : index + 1);
      return;
    }
    if (event.key === 'ArrowUp' || event.key === 'ArrowLeft') {
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

  return (
    <div className="toptabs" role="tablist" aria-orientation="vertical" aria-label={label}>
      {tabs.map((tab, index) => {
        const isActive = tab.id === active;
        return (
          <button
            key={tab.id}
            ref={(el) => {
              btnRefs.current[tab.id] = el;
            }}
            type="button"
            role="tab"
            id={topTabId(tab.id)}
            aria-selected={isActive}
            aria-controls={topTabPanelId(tab.id)}
            // Roving tabindex: only the active tab is in the tab order.
            tabIndex={isActive ? 0 : -1}
            className={isActive ? 'toptab toptab--active' : 'toptab'}
            onClick={() => onSelect(tab.id)}
            onKeyDown={(event) => onKeyDown(event, index)}
          >
            <span className="toptab__icon" aria-hidden="true">
              {tab.icon}
            </span>
            <span className="toptab__label">{tab.label}</span>
            {tab.badge !== undefined && tab.badge > 0 ? (
              <span className="toptab__badge" aria-label={`${tab.badge} pending`}>
                {tab.badge}
              </span>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}

export default TopTabBar;
