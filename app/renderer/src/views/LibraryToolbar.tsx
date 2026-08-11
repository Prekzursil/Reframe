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
  //
  // DISCLOSED COST of that disjunct, on a library that resolves EMPTY: `loading`
  // is unconditionally true while the listing is in flight, so this strip MOUNTS
  // above the skeleton and then UNMOUNTS when `{videos: []}` lands — a flash of a
  // live, ENABLED "Search videos" box on a library that has nothing, followed by a
  // collapse of this strip's own box. Neither behaviour this gate replaced had
  // that transient: the pre-W54 strip was always mounted, and the `videoCount > 0`
  // first attempt was never mounted while loading. It is new here, and it is the
  // reason this paragraph exists.
  //   - That the DOM sequence OCCURS: almost certain (90-99%) — it is the direct
  //     reading of this expression, and Library.test.tsx "flashes the toolbar over
  //     the skeleton before dropping it on an empty library" drives both edges in
  //     one render and pins them.
  //   - That it is PERCEPTIBLE, and the magnitude of the collapse: UNVERIFIED.
  //     It depends on `library.list` latency, and the box is token-driven
  //     (`--space-4` / `--control-pad-input` / `--type-body-size`,
  //     components/library-shell.css:87-114), so no figure is asserted here.
  //     jsdom has neither layout nor real timing, so NO test in this repo's unit
  //     suite can settle it. Settling experiment: a Playwright `boundingBox()` of
  //     `.library__empty` sampled across the resolve against a seeded-EMPTY data
  //     root — a y-shift is the collapse, no y-shift refutes it.
  //
  // Kept deliberately. The count is unknowable before the RPC resolves, so no gate
  // reading only `videoCount`/`loading` can avoid it — the choice is WHICH path
  // pays. This trades a first-run-only flicker on an empty library against a shift
  // on EVERY return to a non-empty Library tab (App.tsx renderRoute() remounts the
  // view with `videos` reset to []), which is by far the commoner path.
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
