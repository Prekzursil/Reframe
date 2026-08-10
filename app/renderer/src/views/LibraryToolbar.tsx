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
  /**
   * Number of videos in the library BEFORE `query`/`sort` are applied (0 hides
   * the search + sort controls).
   *
   * W54: this is deliberately the RAW count, not the filtered/visible one. Gating
   * on the visible count would remove the search box the moment a query matched
   * nothing — i.e. delete the only control that can undo the filter — and strand
   * the user in the "No matches" state.
   */
  videoCount: number;
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
  videoCount,
  selectedCount,
  onRemoveSelected,
  onClearSelection,
}: LibraryToolbarProps): React.ReactElement | null {
  // W54: search + sort used to mount unconditionally, so a first-run library
  // offered a live, enabled search box and sort select over zero rows — a promise
  // of scale affordances with nothing to apply them to. They now ride the SAME
  // gate the batch bar below already used, keyed on the video count.
  const showFilters = videoCount > 0;
  const showBatch = selectedCount > 0;
  // Nothing to show -> no strip. `.library-toolbar` carries its own padding
  // (components/library-shell.css), so keeping an empty wrapper would leave a
  // blank band between the capabilities chip and the first-run poster.
  if (!showFilters && !showBatch) return null;

  return (
    <div className="library-toolbar">
      {showFilters ? (
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
      ) : null}

      {showBatch ? (
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
