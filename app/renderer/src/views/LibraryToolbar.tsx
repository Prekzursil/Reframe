// LibraryToolbar.tsx — the Library scale affordances (v1.5 §4): per-library
// search + sort, and the multi-select batch bar. Purely presentational — the
// parent (Library) owns the query/sort/selection state and the batch action; this
// renders the controls and forwards intent. Cmd-K is global but must not replace
// in-context filtering at hundreds of videos, which is what this provides.
import React from 'react';

import { type LibrarySort, LIBRARY_SORT_MODES, LIBRARY_SORT_LABELS } from './libraryModel';
import '../components/library-shell.css';

export interface LibraryToolbarProps {
  query: string;
  onQueryChange: (query: string) => void;
  sort: LibrarySort;
  onSortChange: (sort: LibrarySort) => void;
  /** Number of currently-selected cards (0 hides the batch bar). */
  selectedCount: number;
  onRemoveSelected: () => void;
  onClearSelection: () => void;
}

export function LibraryToolbar({
  query,
  onQueryChange,
  sort,
  onSortChange,
  selectedCount,
  onRemoveSelected,
  onClearSelection,
}: LibraryToolbarProps): React.ReactElement {
  return (
    <div className="library-toolbar">
      <div className="library-toolbar__filters">
        <input
          type="search"
          className="library-toolbar__search"
          placeholder="Search videos"
          aria-label="Search videos"
          value={query}
          onChange={(event) => onQueryChange(event.target.value)}
        />
        <label className="library-toolbar__sort">
          <span className="library-toolbar__sort-label">Sort</span>
          <select
            className="library-toolbar__sort-select"
            aria-label="Sort videos"
            value={sort}
            onChange={(event) => onSortChange(event.target.value as LibrarySort)}
          >
            {LIBRARY_SORT_MODES.map((mode) => (
              <option key={mode} value={mode}>
                {LIBRARY_SORT_LABELS[mode]}
              </option>
            ))}
          </select>
        </label>
      </div>

      {selectedCount > 0 ? (
        <div className="library-toolbar__batch" role="group" aria-label="Batch actions">
          <span className="library-toolbar__batch-count" aria-live="polite">
            {selectedCount} selected
          </span>
          <button
            type="button"
            className="library-toolbar__batch-remove"
            onClick={onRemoveSelected}
          >
            Remove selected
          </button>
          <button type="button" className="library-toolbar__batch-clear" onClick={onClearSelection}>
            Clear
          </button>
        </div>
      ) : null}
    </div>
  );
}

export default LibraryToolbar;
