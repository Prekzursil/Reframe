// TopTabBar.test.tsx — the top-level tablist: rendering, active state, roving
// tabindex, ARIA wiring, and the full keyboard model (Arrow/Home/End + wrap +
// no-op). Every keydown branch is exercised independently for branch coverage.

// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import { TopTabBar, topTabId, topTabPanelId, type TopTab } from './TopTabBar';

const ICON = <svg data-testid="icon" />;

const TABS: TopTab[] = [
  { id: 'library', label: 'Library', icon: ICON },
  { id: 'create', label: 'Create', icon: ICON },
  { id: 'repurpose', label: 'Repurpose', icon: ICON, badge: 3 },
];

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
  vi.restoreAllMocks();
});

function render(active: string, onSelect: (id: string) => void): void {
  act(() => {
    root.render(<TopTabBar tabs={TABS} active={active} onSelect={onSelect} />);
  });
}

function tabs(): HTMLButtonElement[] {
  return Array.from(container.querySelectorAll<HTMLButtonElement>('[role="tab"]'));
}

function tab(label: string): HTMLButtonElement {
  const found = tabs().find((b) => b.textContent?.includes(label));
  if (!found) throw new Error(`tab "${label}" not found`);
  return found;
}

function press(el: HTMLButtonElement, key: string): void {
  act(() => {
    el.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true }));
  });
}

describe('TopTabBar — rendering + ARIA', () => {
  it('renders a tablist with one tab per entry and their labels + icons', () => {
    render('library', () => {});
    const list = container.querySelector('[role="tablist"]')!;
    expect(list.getAttribute('aria-label')).toBe('Primary');
    expect(tabs()).toHaveLength(3);
    expect(tab('Library').textContent).toContain('Library');
    expect(container.querySelectorAll('[data-testid="icon"]')).toHaveLength(3);
  });

  it('marks the tablist vertical (role-complete left rail)', () => {
    render('library', () => {});
    expect(container.querySelector('[role="tablist"]')!.getAttribute('aria-orientation')).toBe(
      'vertical',
    );
  });

  it('accepts a custom tablist label', () => {
    render('library', () => {});
    act(() => {
      root.render(<TopTabBar tabs={TABS} active="library" onSelect={() => {}} label="Surfaces" />);
    });
    expect(container.querySelector('[role="tablist"]')!.getAttribute('aria-label')).toBe(
      'Surfaces',
    );
  });

  it('marks only the active tab selected, with class + roving tabindex', () => {
    render('create', () => {});
    expect(tab('Create').getAttribute('aria-selected')).toBe('true');
    expect(tab('Create').classList.contains('toptab--active')).toBe(true);
    expect(tab('Create').tabIndex).toBe(0);
    // The inactive tabs are out of the tab order (roving tabindex).
    expect(tab('Library').getAttribute('aria-selected')).toBe('false');
    expect(tab('Library').tabIndex).toBe(-1);
    // Exactly one tab is selected.
    expect(tabs().filter((b) => b.getAttribute('aria-selected') === 'true')).toHaveLength(1);
  });

  it('wires each tab id ↔ its panel via aria-controls / id helpers', () => {
    render('library', () => {});
    expect(tab('Library').id).toBe(topTabId('library'));
    expect(tab('Library').getAttribute('aria-controls')).toBe(topTabPanelId('library'));
    expect(topTabId('library')).toBe('toptab-library');
    expect(topTabPanelId('library')).toBe('toptabpanel-library');
  });

  it('renders a numeric badge only when badge > 0', () => {
    render('library', () => {});
    // Repurpose has badge:3.
    expect(tab('Repurpose').querySelector('.toptab__badge')!.textContent).toBe('3');
    expect(tab('Repurpose').querySelector('.toptab__badge')!.getAttribute('aria-label')).toBe(
      '3 pending',
    );
    // Library has no badge.
    expect(tab('Library').querySelector('.toptab__badge')).toBeNull();
  });

  it('hides the badge when the count is zero', () => {
    const zeroTabs: TopTab[] = [
      { id: 'library', label: 'Library', icon: ICON },
      { id: 'repurpose', label: 'Repurpose', icon: ICON, badge: 0 },
    ];
    act(() => {
      root.render(<TopTabBar tabs={zeroTabs} active="library" onSelect={() => {}} />);
    });
    const rep = tabs().find((b) => b.textContent?.includes('Repurpose'))!;
    expect(rep.querySelector('.toptab__badge')).toBeNull();
  });
});

describe('TopTabBar — pointer selection', () => {
  it('calls onSelect with the clicked tab id', () => {
    const onSelect = vi.fn();
    render('library', onSelect);
    act(() => {
      tab('Create').click();
    });
    expect(onSelect).toHaveBeenCalledWith('create');
  });
});

describe('TopTabBar — keyboard model', () => {
  it('ArrowRight moves to the next tab and focuses it', () => {
    const onSelect = vi.fn();
    render('library', onSelect);
    press(tab('Library'), 'ArrowRight');
    expect(onSelect).toHaveBeenCalledWith('create');
    expect(document.activeElement).toBe(tab('Create'));
  });

  it('ArrowRight wraps from the last tab to the first', () => {
    const onSelect = vi.fn();
    render('repurpose', onSelect);
    press(tab('Repurpose'), 'ArrowRight');
    expect(onSelect).toHaveBeenCalledWith('library');
    expect(document.activeElement).toBe(tab('Library'));
  });

  it('ArrowLeft moves to the previous tab', () => {
    const onSelect = vi.fn();
    render('create', onSelect);
    press(tab('Create'), 'ArrowLeft');
    expect(onSelect).toHaveBeenCalledWith('library');
    expect(document.activeElement).toBe(tab('Library'));
  });

  it('ArrowLeft wraps from the first tab to the last', () => {
    const onSelect = vi.fn();
    render('library', onSelect);
    press(tab('Library'), 'ArrowLeft');
    expect(onSelect).toHaveBeenCalledWith('repurpose');
    expect(document.activeElement).toBe(tab('Repurpose'));
  });

  it('ArrowDown moves to the next tab (vertical rail) and focuses it', () => {
    const onSelect = vi.fn();
    render('library', onSelect);
    press(tab('Library'), 'ArrowDown');
    expect(onSelect).toHaveBeenCalledWith('create');
    expect(document.activeElement).toBe(tab('Create'));
  });

  it('ArrowDown wraps from the last tab to the first', () => {
    const onSelect = vi.fn();
    render('repurpose', onSelect);
    press(tab('Repurpose'), 'ArrowDown');
    expect(onSelect).toHaveBeenCalledWith('library');
    expect(document.activeElement).toBe(tab('Library'));
  });

  it('ArrowUp moves to the previous tab (vertical rail)', () => {
    const onSelect = vi.fn();
    render('create', onSelect);
    press(tab('Create'), 'ArrowUp');
    expect(onSelect).toHaveBeenCalledWith('library');
    expect(document.activeElement).toBe(tab('Library'));
  });

  it('ArrowUp wraps from the first tab to the last', () => {
    const onSelect = vi.fn();
    render('library', onSelect);
    press(tab('Library'), 'ArrowUp');
    expect(onSelect).toHaveBeenCalledWith('repurpose');
    expect(document.activeElement).toBe(tab('Repurpose'));
  });

  it('Home jumps to the first tab', () => {
    const onSelect = vi.fn();
    render('repurpose', onSelect);
    press(tab('Repurpose'), 'Home');
    expect(onSelect).toHaveBeenCalledWith('library');
    expect(document.activeElement).toBe(tab('Library'));
  });

  it('End jumps to the last tab', () => {
    const onSelect = vi.fn();
    render('library', onSelect);
    press(tab('Library'), 'End');
    expect(onSelect).toHaveBeenCalledWith('repurpose');
    expect(document.activeElement).toBe(tab('Repurpose'));
  });

  it('ignores other keys (no selection change)', () => {
    const onSelect = vi.fn();
    render('library', onSelect);
    press(tab('Library'), 'a');
    expect(onSelect).not.toHaveBeenCalled();
  });
});
