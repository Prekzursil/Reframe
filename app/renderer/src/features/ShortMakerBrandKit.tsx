// ShortMakerBrandKit.tsx — the short-maker brand-kit section (presentational).
//
// Extracted from ShortMaker.tsx to keep that file under the 800-line budget
// (coding-style.md: files <800 lines). Pure presentational: state (open/closed,
// the BrandSettings) and persistence live in the ShortMaker container; this
// component only renders + forwards events. The DOM is byte-identical to the
// inline JSX it replaced (same aria-labels/classes), so component tests stay green.
//
// LOADING PLACEHOLDERS STILL UNCONVERTED — a FLOOR, not a total. Two successive
// revisions of this count were undercounts (three, then seven), so it ships with
// its criterion, its probe and its blind spot instead of a bare number. CRITERION:
// a region standing in for content that has NOT arrived, rendering the wait as
// VISIBLE text. FOURTEEN remain outside this lane, found by the UNION of three
// probes, because each one alone undercounts: a `__loading`/`--loading` class grep
// (blind to ReadinessRollup, which reuses `jobqueue__empty`, and to
// TranscriptEditor, which has no class), a single-line visible-text grep (blind to
// every multi-line JSX text node), and an indented bare-text-line grep (blind to
// single-line nodes, and to any copy outside its verb list — the residual hole;
// settle it with an AST pass over JSX text nodes). Cited by selector, not by line:
// these files belong to other lanes and line anchors drift.
//   * SEVEN carry NO live semantics: App.tsx + Workspace.tsx x2 (the
//     `panel panel--loading` Suspense fallbacks), components/PathsPanel.tsx,
//     LineagePanel.tsx, TranscriptEditor.tsx, KeepCopyControl.tsx.
//   * ONE already has an explicit `aria-live`: Transcribe.tsx — needs only the shape.
//   * SIX already carry `aria-busy`, so they are lower priority but the same bare
//     text: components/ManagedStoreMeter.tsx, SetupStatusPanel.tsx,
//     ReadinessRollup.tsx, features/BatchQueue.tsx, ProvidersKeys.tsx, SpendCap.tsx.
// EXCLUDED WITH REASON, so the next lane can argue with the criterion instead of
// rediscovering the site: Library.tsx, Shorts.tsx and Settings.tsx already ship a
// shaped skeleton; Tracks.tsx, DirectorPanel.tsx and SystemHealth.tsx are button
// busy LABELS; SavePresetsControls.tsx is a mutation-progress live region and
// LibraryProvenance.tsx a per-row phase badge — neither stands in for absent
// content. Whoever converts them: a <Skeleton /> dropped into a flex row hits this
// file's 0px trap unless something carries a definite width.

import React from 'react';

import { Skeleton } from '../components/Skeleton';
import { CAPTION_STYLES } from './shortMakerLogic';
import { type BrandSettings } from './shortMakerPresets';

export interface ShortMakerBrandKitProps {
  brand: BrandSettings;
  open: boolean;
  onToggle: () => void;
  onPickLogo: () => void;
  setBrandField: (key: keyof BrandSettings, value: string) => void;
  /**
   * DATA ROOT (the user-facing "data folder"): the folder currently in use this
   * session, or null while it is still loading / when the bridge is unavailable.
   */
  dataFolder: string | null;
  /** True once the data folder has been resolved (distinguishes loading from "unknown"). */
  dataFolderLoaded: boolean;
  /** True after a successful Change… until the app restarts (shows the apply-on-restart note). */
  dataFolderPendingRestart: boolean;
  /** Open the native directory picker + persist the choice (no-op when the bridge is missing). */
  onChangeDataFolder: () => void;
}

/**
 * P4 §8d brand kit: logo watermark picker + default caption template/font.
 * Collapsible; persistence is the container's concern (settings.set).
 */
export function ShortMakerBrandKit({
  brand,
  open,
  onToggle,
  onPickLogo,
  setBrandField,
  dataFolder,
  dataFolderLoaded,
  dataFolderPendingRestart,
  onChangeDataFolder,
}: ShortMakerBrandKitProps): React.JSX.Element {
  return (
    <section className="sm-brand" aria-label="Brand kit">
      <button
        type="button"
        className="sm-brand-toggle"
        aria-expanded={open}
        aria-controls="sm-brand-body"
        onClick={onToggle}
      >
        Brand kit {open ? '▾' : '▸'}
      </button>
      {open && (
        <div className="sm-brand-body" id="sm-brand-body">
          <div className="sm-field sm-brand-logo">
            <span>Logo watermark</span>
            <div className="sm-brand-logo-row">
              <button type="button" aria-label="Pick logo file" onClick={onPickLogo}>
                Choose logo…
              </button>
              {brand.brandLogoPath ? (
                <>
                  <span className="sm-brand-logo-path" title={brand.brandLogoPath}>
                    {brand.brandLogoPath}
                  </span>
                  <button
                    type="button"
                    aria-label="Clear logo"
                    onClick={() => setBrandField('brandLogoPath', '')}
                  >
                    Clear
                  </button>
                </>
              ) : (
                <span className="sm-brand-logo-empty">No logo set</span>
              )}
            </div>
          </div>

          <label className="sm-field">
            <span>Default caption template</span>
            <select
              aria-label="Default caption template"
              value={brand.brandCaptionTemplate}
              onChange={(e) => setBrandField('brandCaptionTemplate', e.target.value)}
            >
              <option value="">No default</option>
              {CAPTION_STYLES.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.label}
                </option>
              ))}
            </select>
          </label>

          <label className="sm-field">
            <span>Default font family</span>
            <input
              aria-label="Default font family"
              type="text"
              placeholder="e.g. Inter, Montserrat"
              value={brand.brandFontFamily}
              onChange={(e) => setBrandField('brandFontFamily', e.target.value)}
            />
          </label>

          {/* DATA ROOT: the one relocatable folder holding models / envs /
              exports / proxies / dubs / voices / feedback. Changing it writes a
              marker; a restart applies it (no files are moved here). */}
          <div className="sm-field sm-data-folder">
            <span>Data folder</span>
            <p className="sm-data-folder-hint">
              Where models, environments, exports and caches are stored.
            </p>
            <div className="sm-data-folder-row">
              <button type="button" aria-label="Change data folder" onClick={onChangeDataFolder}>
                Change…
              </button>
              {/* THE FOURTH BARE "Loading…", now the shared <Skeleton />: named
                  nowhere on the EmptyState/Skeleton lane, so it kept the
                  hand-rolled `<span aria-live="polite">Loading…</span>` that
                  Library.tsx's own comment writes down as forbidden. What is
                  still unconverted house-wide is counted in the file header.

                  WHY THE INLINE WIDTH — a correction, not decoration. Shipped
                  without it the adoption MEASURED 0.00 x 10 px in real Chromium
                  and was invisible, where the span it replaced measured
                  47.14 x 16.50 and this measures 160 x 10. Cause:
                  `.skeleton-group` is a shrink-to-fit flex item of
                  `.sm-data-folder-row` whose only in-flow child is an EMPTY span
                  at `width: 100%`, and a percentage against an indefinite width
                  contributes 0 to intrinsic sizing (the label that would have
                  given it content is `position: absolute`). A rule in
                  shortmaker-p3.css is the tidier home but that file is another
                  lane's, and its sibling `max-width: 240px` puts a hard px value
                  there anyway, so the idiom is the house's either way. The
                  wrapper is a <div> because <Skeleton /> renders a <div> root,
                  which a <span> may not contain. Both pinned by the test file.

                  REACHABILITY, so the impact is not overstated: this branch sits
                  behind TWO gates. `brandOpen` starts false in ShortMaker.tsx and
                  this whole body is inside `{open && …}`, while `dataFolderLoaded`
                  is flipped true by a mount effect after ONE main-process call. So
                  the wait renders only if the user expands Brand kit while
                  `getDataFolder()` is still pending — on a healthy machine, a race
                  they cannot win. NOT dead code: a slow or hung main process holds
                  it indefinitely. Inherited from the bare span, not introduced
                  here, but it bounds the 0px damage far more tightly than IPC
                  latency alone would.

                  A11Y — one axis preserved, one CHANGED. `role="status"` carries
                  an implicit `aria-live="polite"` + `aria-atomic` per WAI-ARIA, so
                  dropping the explicit attribute preserves the polite semantics
                  and gains a specific string over the old "Loading…". But this
                  also ADDS `aria-busy="true"`, which this site never carried: it
                  mounts true and unmounts without ever clearing, which Skeleton.tsx
                  names as the STRONGEST of three reasons an AT may stay silent. So
                  the fix introduces a suppression mechanism here rather than
                  inheriting one. Whether it changes what is spoken is NOT-CHECKED;
                  settle it with the both-states NVDA probe Skeleton.tsx specifies.
                  (`sm-data-folder-loading` is kept as a SELECTOR only — its one
                  rule is font-size + colour over a subtree with no visible text.)

                  OUT OF SCOPE, REPORTED NOT FIXED: this is the SECOND production
                  call site of <Skeleton /> and the first to ship `variant="line"`,
                  which falsifies two sentences in components/Skeleton.tsx — its
                  "exactly ONE non-test call site (Settings.tsx)" and its "`line`,
                  `title` … shipped-but-unused API, exercised only by
                  Skeleton.test.tsx". Both were TRUE at origin/main and are false at
                  this tip. That file is another lane's, so this branch must not
                  edit it; it needs a scope grant or a follow-up. */}
              {!dataFolderLoaded ? (
                <div style={{ width: '160px' }}>
                  <Skeleton
                    variant="line"
                    className="sm-data-folder-loading"
                    label="Loading data folder"
                  />
                </div>
              ) : dataFolder ? (
                <span className="sm-data-folder-path" title={dataFolder}>
                  {dataFolder}
                </span>
              ) : (
                <span className="sm-data-folder-empty">Unavailable</span>
              )}
            </div>
            {dataFolderPendingRestart && (
              <p className="sm-data-folder-restart" role="status">
                Restart to apply the new data folder.
              </p>
            )}
          </div>
        </div>
      )}
    </section>
  );
}

export default ShortMakerBrandKit;
