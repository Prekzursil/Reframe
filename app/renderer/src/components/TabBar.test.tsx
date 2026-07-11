// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { TabBar, tabId, tabPanelId, type TabDef, type TabGroup } from './TabBar';

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

// WU-3a2: the optional `groups` prop renders tabs in NAMED clusters with an
// "Advanced" disclosure. Purely ADDITIVE — the flat path above is unchanged.
const GROUP_TABS: TabDef[] = [
  { id: 't1', label: 'One' },
  { id: 't2', label: 'Two' },
  { id: 't3', label: 'Three' },
];
const GROUPS: TabGroup[] = [
  { id: 'g1', label: 'Primary', tabIds: ['t1', 't2'] },
  { id: 'g2', label: 'More', tabIds: ['t3'], advanced: true },
];

describe('TabBar (grouped clusters, WU-3a2)', () => {
  it('renders named clusters with section labels and stable data-tab-id', () => {
    const html = renderToStaticMarkup(
      <TabBar tabs={GROUP_TABS} active="t1" onSelect={() => {}} groups={GROUPS} />,
    );
    expect(html).toContain('tabbar--grouped');
    expect(html).toContain('tabbar__group-label');
    expect(html).toContain('Primary');
    expect(html).toContain('More');
    expect(html).toContain('data-tab-id="t1"');
    expect(html).toContain('data-tab-id="t3"');
    // All 3 tabs stay real role="tab" buttons even with one cluster collapsed.
    expect((html.match(/role="tab"/g) ?? []).length).toBe(3);
  });

  it('collapses the advanced cluster by default (aria-expanded=false, panel hidden)', () => {
    const html = renderToStaticMarkup(
      <TabBar tabs={GROUP_TABS} active="t1" onSelect={() => {}} groups={GROUPS} />,
    );
    expect(html).toContain('aria-expanded="false"');
    expect(html).toMatch(/class="tabbar__advanced-panel"[^>]*hidden/);
  });

  it('expands the advanced cluster when advancedOpen is true (panel not hidden)', () => {
    const html = renderToStaticMarkup(
      <TabBar tabs={GROUP_TABS} active="t1" onSelect={() => {}} groups={GROUPS} advancedOpen />,
    );
    expect(html).toContain('aria-expanded="true"');
    expect(html).not.toMatch(/class="tabbar__advanced-panel"[^>]*hidden/);
  });

  it('omits the Advanced toggle when no cluster is flagged advanced', () => {
    const primaryOnly: TabGroup[] = [{ id: 'g1', label: 'Primary', tabIds: ['t1', 't2', 't3'] }];
    const html = renderToStaticMarkup(
      <TabBar tabs={GROUP_TABS} active="t2" onSelect={() => {}} groups={primaryOnly} />,
    );
    expect(html).not.toContain('tabbar__advanced-toggle');
    expect(html).toContain('tabbar--grouped');
    expect((html.match(/role="tab"/g) ?? []).length).toBe(3);
  });

  it('renders a persistent Export action only when onExport is provided', () => {
    // design-review P1: EXPORT is the terminal goal, so it gets a standing button
    // in the grouped strip — absent by default (no onExport).
    const without = renderToStaticMarkup(
      <TabBar tabs={GROUP_TABS} active="t1" onSelect={() => {}} groups={GROUPS} />,
    );
    expect(without).not.toContain('tabbar__export');

    const withExport = renderToStaticMarkup(
      <TabBar
        tabs={GROUP_TABS}
        active="t1"
        onSelect={() => {}}
        groups={GROUPS}
        onExport={() => {}}
      />,
    );
    expect(withExport).toContain('tabbar__export');
    expect(withExport).toContain('Export');
  });

  it('invokes onExport when the Export action is clicked', () => {
    const onExport = vi.fn();
    const el = TabBar({
      tabs: GROUP_TABS,
      active: 't1',
      onSelect: () => {},
      groups: GROUPS,
      onExport,
    }) as React.ReactElement;
    const children = el.props.children as React.ReactNode[];
    // The Export button is the last child of the grouped root.
    const exportButton = children[children.length - 1] as React.ReactElement;
    exportButton.props.onClick();
    expect(onExport).toHaveBeenCalledTimes(1);
  });

  it('invokes onToggleAdvanced when the disclosure toggle is clicked', () => {
    const onToggle = vi.fn();
    const el = TabBar({
      tabs: GROUP_TABS,
      active: 't1',
      onSelect: () => {},
      groups: GROUPS,
      advancedOpen: false,
      onToggleAdvanced: onToggle,
    }) as React.ReactElement;
    // The Advanced disclosure toggle now sits as a direct SIBLING of the tablist
    // (moved OUT of role="tablist" so the list owns only tabs). The grouped root's
    // children are [tablistDiv, toggleOrNull, exportOrNull]; locate the toggle by
    // its stable class rather than by position.
    const children = (el.props.children as React.ReactNode[]).flat();
    const toggleButton = children.find(
      (c): c is React.ReactElement =>
        typeof c === 'object' &&
        c !== null &&
        String((c as React.ReactElement).props?.className ?? '') === 'tabbar__advanced-toggle',
    ) as React.ReactElement;
    toggleButton.props.onClick();
    expect(onToggle).toHaveBeenCalledTimes(1);
  });
});

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
    expect(btn('b').getAttribute('aria-controls')).toBe(tabPanelId('b'));
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

  it('grouped mode: arrow nav traverses primary tabs and skips a collapsed advanced tab', () => {
    const onSelect = vi.fn();
    renderBar({ tabs: GROUP_TABS, active: 't1', onSelect, groups: GROUPS, advancedOpen: false });
    // ArrowRight from t1 -> t2 (t3 is in the collapsed cluster, not in the order).
    key(btn('t1'), 'ArrowRight');
    expect(onSelect).toHaveBeenLastCalledWith('t2');
    // ArrowRight from t2 (last reachable) wraps to t1, NOT t3.
    key(btn('t2'), 'ArrowRight');
    expect(onSelect).toHaveBeenLastCalledWith('t1');
    // A keydown on the hidden advanced tab t3 is a no-op (index -1 branch).
    onSelect.mockClear();
    key(btn('t3'), 'ArrowRight');
    expect(onSelect).not.toHaveBeenCalled();
  });

  it('grouped mode: an open advanced cluster joins the arrow-nav order', () => {
    const onSelect = vi.fn();
    renderBar({ tabs: GROUP_TABS, active: 't2', onSelect, groups: GROUPS, advancedOpen: true });
    // ArrowRight from t2 (last primary) -> t3 (advanced now reachable), focus follows.
    key(btn('t2'), 'ArrowRight');
    expect(onSelect).toHaveBeenLastCalledWith('t3');
    expect(document.activeElement).toBe(btn('t3'));
  });
});
