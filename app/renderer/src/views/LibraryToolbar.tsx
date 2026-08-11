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
  // DISCLOSED COST of that disjunct, whenever the listing TERMINATES with the count
  // still 0: `loading` is unconditionally true while it is in flight, so this strip
  // MOUNTS above the skeleton and then UNMOUNTS the moment `loading` goes false with
  // `videoCount` still 0 — a flash of a live, ENABLED "Search videos" box on a
  // library that has nothing, followed by a collapse of this strip's own box.
  //
  // That covers TWO paths, not one. An empty resolve, and a FAILED listing: the catch
  // arm sets `error` and leaves `videos` as `[]` (Library.tsx:227-230), so a rejection
  // reaches the identical `loading=false, videoCount=0` state. The failure path is
  // strictly worse — the first-run poster is suppressed under an error
  // (Library.tsx:637-648), so nothing backfills the collapsed box — and it recurs on
  // every return to the tab for as long as the failure persists. Both are pinned, by
  // Library.test.tsx "flashes the toolbar over the skeleton before dropping it on an
  // empty library" and "...on a FAILED listing".
  //
  // Only the mount->unmount SEQUENCE is new here. The enabled-over-zero-rows STATE was
  // already disclosed and deliberately chosen before this change, at
  // LibraryToolbar.test.tsx:142-161, which gives the reason — library-shell.css defines
  // no `:disabled` rule for these two controls (its only one is
  // `.capabilities-chip__toggle:disabled`, :44) so a `disabled` box would look identical
  // to a live one, i.e. looks-live-but-is-dead — and pins `search.disabled === false` at
  // :159. `disabled={loading}` would therefore mute the enabled half of this transient
  // at the price of reversing that merged decision and reddening its test: out of THIS
  // change's scope, not impossible. Recorded so a future reader knows which half is
  // still open and that the other one is a choice, not an oversight.
  //   - That the DOM sequence OCCURS: almost certain (90-99%) — it is the direct
  //     reading of this expression, and the two Library.test.tsx cases named above
  //     drive both edges of both paths in one render each and pin them.
  //   - That it is PERCEPTIBLE, and the magnitude of the collapse: UNVERIFIED.
  //     It depends on `library.list` latency, and the box is token-driven
  //     (`--space-4` / `--control-pad-input` / `--type-body-size`,
  //     components/library-shell.css:87-114), so no figure is asserted here.
  //     jsdom has neither layout nor real timing, so NO test in this repo's unit
  //     suite can settle it. Settling experiment, in Playwright against a
  //     seeded-EMPTY data root: sample `boundingBox().y` of `.library__loading`
  //     while the listing is in flight and of `.library__empty` after it resolves.
  //     Those two are the ARMS OF ONE ternary slot (Library.tsx:615/637/649), so
  //     they hold the same position in the flow and `y(loading) - y(empty)` IS the
  //     collapse. The magnitude alone needs a single sample and no diff:
  //     `boundingBox().height` of `.library-toolbar` while it is still mounted.
  //     REQUIRED both-states control before either reading is trusted — run the
  //     probe first with this gate forced to `true` (strip never unmounts) and
  //     confirm the delta reads 0 THERE; a probe that cannot go non-zero in the
  //     true state and zero in the false one is measuring nothing.
  //
  // Kept deliberately — but NOT because nothing else is possible. `showFilters = true`
  // (the pre-W54 always-mounted strip) avoids this transient outright. Every escape
  // reinstates a cost this gate exists to remove: `true` puts an enabled search box
  // PERMANENTLY over a zero-row library (the W54 defect at :48-51), and `videoCount > 0`
  // alone reinstates the first-paint shift refuted at :53-58. So no gate reading only
  // `videoCount`/`loading` can avoid the mount->unmount SEQUENCE *without* one of those
  // — the count is unknowable before the RPC resolves, and the choice is WHICH path
  // pays.
  //
  // The trade is per-remount on BOTH sides, so the asymmetry is a POPULATION one, not a
  // frequency one. `renderRoute()` returns <Library> only in the library case
  // (App.tsx:491, :532-548, called at :598), and Library.tsx:171-172 re-initialises
  // `videos=[]` / `loading=true` on every mount, so the flicker recurs on every entry
  // while the library is EMPTY exactly as the shift would recur on every entry once it
  // is NOT — and batch remove can return a populated library to empty. Kept because
  // non-empty is the permanent state and empty is the transient one.
  //
  // REFUTED WORDINGS, recorded rather than deleted (adversarial review, W5). Each was
  // wider than its evidence while the code was correct; the scoped versions are above.
  //   * "on a library that resolves EMPTY" — missed the rejection path.
  //   * "It is new here" (of the whole transient) — only the sequence is new.
  //   * "no gate reading only `videoCount`/`loading` can avoid it" — false as an
  //     unqualified universal; `showFilters = true` avoids it.
  //   * "a first-run-only flicker" — nothing distinguishes a first mount from a
  //     remount, so it is per-entry-while-empty, not once.
  //   * settling experiment "a `boundingBox()` of `.library__empty` across the
  //     resolve" — structurally incapable, and it would have answered "no y-shift" in
  //     BOTH states: `.library__empty` does not exist while the listing is in flight,
  //     so there is no before-sample to diff, and running it would have recorded this
  //     very disclosure as REFUTED.
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
