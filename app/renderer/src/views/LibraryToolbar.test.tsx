// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import { LibraryToolbar } from './LibraryToolbar';
import type { LibrarySort } from './libraryModel';

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

interface Over {
  query?: string;
  onQueryChange?: (q: string) => void;
  sort?: LibrarySort;
  onSortChange?: (s: LibrarySort) => void;
  videoCount?: number;
  selectedCount?: number;
  onRemoveSelected?: () => void;
  onClearSelection?: () => void;
}

function renderToolbar(over: Over = {}): void {
  act(() => {
    root.render(
      <LibraryToolbar
        query={over.query ?? ''}
        onQueryChange={over.onQueryChange ?? (() => {})}
        sort={over.sort ?? 'recent'}
        onSortChange={over.onSortChange ?? (() => {})}
        // W54: the filters only exist over a NON-empty library, so a populated
        // library is the default state for every pre-existing case below (each
        // one is about the controls' behaviour, which presupposes content). The
        // empty-library cases pass 0 explicitly.
        videoCount={over.videoCount ?? 2}
        selectedCount={over.selectedCount ?? 0}
        onRemoveSelected={over.onRemoveSelected ?? (() => {})}
        onClearSelection={over.onClearSelection ?? (() => {})}
      />,
    );
  });
}

describe('LibraryToolbar', () => {
  it('renders the search + sort controls with the current values', () => {
    renderToolbar({ query: 'talk', sort: 'title' });
    const search = container.querySelector('.library-toolbar__search') as HTMLInputElement;
    const sort = container.querySelector('.library-toolbar__sort-select') as HTMLSelectElement;
    expect(search.value).toBe('talk');
    expect(sort.value).toBe('title');
    // Every sort mode is offered.
    expect(sort.querySelectorAll('option').length).toBeGreaterThanOrEqual(4);
  });

  it('forwards search input changes', () => {
    const onQueryChange = vi.fn();
    renderToolbar({ onQueryChange });
    const search = container.querySelector('.library-toolbar__search') as HTMLInputElement;
    // Use the native value setter so React's _valueTracker sees the change and
    // fires onChange on a controlled input (a direct `.value =` is swallowed).
    const setValue = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')
      ?.set as (v: string) => void;
    act(() => {
      setValue.call(search, 'keynote');
      search.dispatchEvent(new Event('input', { bubbles: true }));
    });
    expect(onQueryChange).toHaveBeenCalledWith('keynote');
  });

  it('forwards sort changes', () => {
    const onSortChange = vi.fn();
    renderToolbar({ onSortChange });
    const sort = container.querySelector('.library-toolbar__sort-select') as HTMLSelectElement;
    act(() => {
      sort.value = 'duration';
      sort.dispatchEvent(new Event('change', { bubbles: true }));
    });
    expect(onSortChange).toHaveBeenCalledWith('duration');
  });

  it('hides the batch bar when nothing is selected', () => {
    renderToolbar({ selectedCount: 0 });
    expect(container.querySelector('.library-toolbar__batch')).toBeNull();
  });

  it('shows the batch bar and forwards remove + clear when a selection exists', () => {
    const onRemoveSelected = vi.fn();
    const onClearSelection = vi.fn();
    renderToolbar({ selectedCount: 3, onRemoveSelected, onClearSelection });
    expect(container.querySelector('.library-toolbar__batch-count')?.textContent).toBe(
      '3 selected',
    );

    act(() => {
      (
        container.querySelector('.library-toolbar__batch-remove') as HTMLButtonElement
      ).dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    expect(onRemoveSelected).toHaveBeenCalledTimes(1);

    act(() => {
      (container.querySelector('.library-toolbar__batch-clear') as HTMLButtonElement).dispatchEvent(
        new MouseEvent('click', { bubbles: true }),
      );
    });
    expect(onClearSelection).toHaveBeenCalledTimes(1);
  });

  // W54 — search + sort were the one part of this toolbar that rendered
  // unconditionally: on an empty library the user got an enabled search box and
  // sort select over zero rows. They now ride the SAME gate the batch bar above
  // already used, just keyed on the video count instead of the selection count.
  it('hides search + sort when there is nothing to filter', () => {
    renderToolbar({ videoCount: 0 });
    expect(container.querySelector('.library-toolbar__search')).toBeNull();
    expect(container.querySelector('.library-toolbar__sort-select')).toBeNull();
    expect(container.querySelector('.library-toolbar__filters')).toBeNull();
  });

  it('renders no toolbar strip at all when there is neither content nor a selection', () => {
    renderToolbar({ videoCount: 0, selectedCount: 0 });
    // Keeping the wrapper would leave an empty padded strip above the first-run
    // poster (.library-toolbar carries its own padding in library-shell.css).
    expect(container.querySelector('.library-toolbar')).toBeNull();
  });

  it('still shows the batch bar when a selection exists with the filters hidden', () => {
    renderToolbar({ videoCount: 0, selectedCount: 2 });
    expect(container.querySelector('.library-toolbar')).not.toBeNull();
    expect(container.querySelector('.library-toolbar__batch-count')?.textContent).toBe(
      '2 selected',
    );
    expect(container.querySelector('.library-toolbar__filters')).toBeNull();
  });
});
