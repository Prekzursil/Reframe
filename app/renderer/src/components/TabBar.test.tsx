import { describe, it, expect, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import React from 'react';
import { TabBar, type TabDef, type TabGroup } from './TabBar';

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
      <TabBar tabs={GROUP_TABS} active="t1" onSelect={() => {}} groups={GROUPS} onExport={() => {}} />,
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
    // Walk the grouped tree: div → [primaryGroups, advancedSection, exportOrNull]
    // → advancedSection → [toggleButton, advancedPanel]. Locate the advanced
    // <section> by its stable class (robust to the appended Export slot).
    const children = (el.props.children as React.ReactNode[]).flat();
    const advancedSection = children.find(
      (c): c is React.ReactElement =>
        typeof c === 'object' &&
        c !== null &&
        String((c as React.ReactElement).props?.className ?? '').includes('tabbar__group--advanced'),
    ) as React.ReactElement;
    const sectionChildren = advancedSection.props.children as React.ReactElement[];
    const toggleButton = sectionChildren[0];
    toggleButton.props.onClick();
    expect(onToggle).toHaveBeenCalledTimes(1);
  });
});
