// ShortMakerBrandKit.tsx — the short-maker brand-kit section (presentational).
//
// Extracted from ShortMaker.tsx to keep that file under the 800-line budget
// (coding-style.md: files <800 lines). Pure presentational: state (open/closed,
// the BrandSettings) and persistence live in the ShortMaker container; this
// component only renders + forwards events. The DOM is byte-identical to the
// inline JSX it replaced (same aria-labels/classes), so component tests stay green.

import React from 'react';

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
              <button
                type="button"
                aria-label="Change data folder"
                onClick={onChangeDataFolder}
              >
                Change…
              </button>
              {!dataFolderLoaded ? (
                <span className="sm-data-folder-loading" aria-live="polite">
                  Loading…
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
