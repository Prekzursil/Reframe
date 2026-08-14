// ShortMakerBrandKit.tsx — the short-maker brand-kit section (presentational).
//
// Extracted from ShortMaker.tsx to keep that file under the 800-line budget
// (coding-style.md: files <800 lines). Pure presentational: state (open/closed,
// the BrandSettings) and persistence live in the ShortMaker container; this
// component only renders + forwards events. The DOM is byte-identical to the
// inline JSX it replaced (same aria-labels/classes), so component tests stay green.

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
              {/* THE FOURTH BARE "Loading…", now the shared <Skeleton />. The
                  EmptyState/Skeleton lane enumerated three surfaces and shipped
                  components/Skeleton.tsx; this site was named nowhere on that
                  branch, so it kept the hand-rolled
                  `<span aria-live="polite">Loading…</span>` that Library.tsx's
                  own comment writes down as forbidden.

                  WHY THE INLINE WIDTH — this is a correction, not decoration.
                  Shipped without it, the adoption MEASURED 0.00 x 10 px in real
                  Chromium (the engine Electron renders with) and was invisible,
                  where the bare span it replaced measured 54.72 x 14 px. Cause:
                  `.skeleton-group` is a shrink-to-fit flex item of
                  `.sm-data-folder-row`, its only in-flow child is an EMPTY span
                  with `width: 100%`, and a percentage against an indefinite
                  width contributes 0 to intrinsic sizing (the label that would
                  have given it content is `position: absolute`). So the ghost
                  needs a definite width from somewhere. A rule in
                  shortmaker-p3.css would be the tidier home but that file is
                  another lane's; the width lives here instead, which is also
                  where the sibling `max-width: 240px` idiom already puts a
                  hard px value, and where the house already accepts static
                  inline styles (ErrorBoundary, Timeline). 160px ≈ the caption
                  width of a typical path. Pinned by ShortMakerBrandKit.test.tsx
                  so a future edit cannot silently make it invisible again.

                  Two more things about this adoption:

                  * `variant="line"` — the real thing that lands here is ONE
                    inline value (a path), not a panel, so the ghost is one bar.
                  * `aria-live="polite"` is not lost, it MOVES: a labelled
                    Skeleton is `role="status"`, whose implicit live semantics
                    are exactly `aria-live="polite"` + `aria-atomic="true"` per
                    WAI-ARIA, so the wait stays announceable and gains a specific
                    string where it used to say only "Loading…". Whether an AT
                    SPEAKS a freshly-inserted status region is NOT-CHECKED, for
                    the three reasons Skeleton.tsx already documents; this is a
                    semantics claim, not an announcement promise.
                  The `sm-data-folder-loading` class is kept for the SELECTOR
                  (the existing test, and any future CSS hook) — not for its
                  paint: the only rule on it is font-size + colour, and this
                  subtree has no visible text, so that treatment is now a no-op.

                  ENUMERATED ≠ CONVERTED. Re-measured at this commit with a
                  controlled grep over renderer/src (the control finds known hits
                  in 9 files; an earlier run of mine missed App.tsx because a
                  doubled-star glob under src does not match a top-level
                  file, and PathsPanel lives in components, not features). Cited by
                  selector, not by line — these files belong to other lanes and
                  line anchors drift. SEVEN bare-text loading placeholders remain
                  live outside this lane's scope, not three: the three
                  `panel panel--loading` Suspense fallbacks (App.tsx, Workspace.tsx
                  x2), plus `.paths-panel__loading` in components/PathsPanel.tsx,
                  `.lineage-panel__loading` in LineagePanel.tsx, the
                  `[data-state="loading"]` paragraph in TranscriptEditor.tsx, and
                  the one in Transcribe.tsx. Six of the seven carry no live
                  semantics at all; Transcribe's already has an explicit
                  `aria-live="polite"` and needs only the visual shape. Two
                  further sites are deliberately NOT counted: Settings.tsx has
                  already adopted <Skeleton />, and Tracks.tsx's
                  `busy.kind === 'list' ? 'Loading…' : 'Refresh'` is a button's
                  own busy LABEL, a different shape from a placeholder surface. */}
              {!dataFolderLoaded ? (
                <span style={{ display: 'inline-block', width: '160px' }}>
                  <Skeleton
                    variant="line"
                    className="sm-data-folder-loading"
                    label="Loading data folder"
                  />
                </span>
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
