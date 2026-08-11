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
   * the search + sort controls unless `loading`).
   *
   * W54: this is deliberately the RAW count, not the filtered/visible one. Gating
   * on the visible count would remove the search box the moment a query matched
   * nothing — i.e. delete the only control that can undo the filter — and strand
   * the user in the "No matches" state.
   */
  videoCount: number;
  /**
   * True while the owning listing RPC is outstanding. A count of 0 then means
   * "unknown", not "empty", so the controls stay mounted: see the gate below.
   */
  loading: boolean;
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
  loading,
  selectedCount,
  onRemoveSelected,
  onClearSelection,
}: LibraryToolbarProps): React.ReactElement | null {
  // W54: search + sort used to mount unconditionally, so a first-run library
  // offered a live, enabled search box and sort select over zero rows — a promise
  // of scale affordances with nothing to apply them to. They now ride the SAME
  // gate the batch bar below already used, keyed on the video count.
  //
  // `|| loading` is load-bearing, not defensive. The first version of this gate was
  // `videoCount > 0` alone, which ALSO unmounted the strip while the owning
  // `library.list` was in flight (the count is 0 then) and remounted it on arrival
  // — displacing the entire list by this strip's box at first paint, and again on
  // every remount of the view. Adversarial review refuted that as a regression; a
  // count of 0 with the listing outstanding is "unknown", not "empty".
  const showFilters = videoCount > 0 || loading;
  const showBatch = selectedCount > 0;
  // Nothing to show -> no strip. `.library-toolbar` carries its own padding
  // (components/library-shell.css), so keeping an empty wrapper would leave a
  // blank band between the capabilities chip and the first-run poster.
  //
  // `showBatch` here is a DEFENSIVE disjunct, not a reachable app state: a
  // selection cannot outlive its videos in the sole caller (Library.tsx:391,
  // :419-420, :221-236 — see LibraryToolbar.test.tsx for the trace). It is kept so
  // a future caller that does reach it still gets its batch bar.
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
