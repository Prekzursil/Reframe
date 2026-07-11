// Settings.tsx — the top-level "Settings" tab's surface.
//
// Settings is itself a sub-navigated area (DESIGN: top-level tabs → Settings →
// sub-sections). It reuses the lightweight in-view `TabBar` (role=tablist/tab/
// aria-selected) for the sub-nav, mirroring the Repurpose view's pattern.
//
// EXTENSION PATTERN — later WUs add a sub-section by appending ONE entry to the
// `SETTINGS_SECTIONS` array below: an `{ id, label, render }` tuple. The tab
// strip, the active-panel switch, and the a11y wiring all derive from that array,
// so a new section needs no edits to the switch logic.
//
// Sub-sections this WU:
//   * models    — the existing Phase-8 "Models & System" panel (lazy),
//   * providers — NEW "Providers & Keys" placeholder (real empty-state; later
//                 WUs wire components/ProviderKeyRow + AddKeyRow here),
//   * health    — the existing app-global System Health diagnostic screen.
import React, { Suspense, lazy, useCallback, useEffect, useState } from 'react';
import { TabBar, tabId, tabPanelId, type TabDef } from '../components/TabBar';
import { SystemHealth } from '../features/SystemHealth';
import { ProvidersKeys } from '../features/ProvidersKeys';
import { PathsPanel, type PathsBridge } from '../components/PathsPanel';
import { ManagedStoreMeter } from '../components/ManagedStoreMeter';
import { SetupStatusPanel } from '../components/SetupStatusPanel';
import { CaptionPreferences } from '../components/CaptionPreferences';
import { SavePresetsControls } from '../components/SavePresetsControls';
import { ThirdPartyNotices } from '../features/ThirdPartyNotices';
import { client } from '../lib/rpc';
import type { AutosaveSettings, ExportDefaults, SavePreset } from '../lib/rpc';
import { resolveWindowApi } from '../features/shortMakerLogic';
import './settings.css';

/**
 * The MAIN-process bridge slice PathsPanel needs (open-in-folder + data-root
 * flow). It lives on `window.api` (NOT a sidecar RPC), so we read it via the
 * shared `resolveWindowApi` accessor — the SAME structural-cast pattern
 * ShortMaker's data-root section uses. A missing preload degrades each control
 * to its own "Unavailable" state (PathsPanel fails soft per-capability), so an
 * empty object is a safe default that never throws.
 */
function pathsBridge(): PathsBridge {
  return (resolveWindowApi() as PathsBridge | undefined) ?? {};
}

// Lazy: the model-card grid + onboarding is heavy and rarely the first thing a
// user opens. Mirrors App's previous lazy import of the same panel.
const ModelsSystemPanel = lazy(() => import('../panels/ModelsSystemPanel'));

/** Context a section's `render` receives — lets a section route to a sibling. */
export interface SettingsRenderContext {
  /** Switch the active sub-section to `id` (used for cross-section actions). */
  goTo: (id: string) => void;
}

/** One Settings sub-section. `render` returns the panel body for that section. */
export interface SettingsSection {
  id: string;
  label: string;
  render: (ctx: SettingsRenderContext) => React.ReactNode;
}

// The live QoL settings a Saved preset bundles. These mirror the sidecar
// DEFAULT_SETTINGS (settings_store.py:113/117) so the initial (pre-fetch) bundle
// matches what the store would return, and every merge below has a full base.
const DEFAULT_AUTOSAVE: AutosaveSettings = { enabled: true, debounceMs: 1500 };
const DEFAULT_EXPORT_DEFAULTS: ExportDefaults = {
  subtitleFormat: 'srt',
  nleFormat: 'edl',
  nleFps: 30,
};

function errText(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

/**
 * The "Export presets" section body. Self-fetches the live `autosave` +
 * `exportDefaults` slices from the SAME `client.settings` store CaptionPreferences
 * reads, so a Saved preset bundles the user's CURRENT choices; and on Apply it
 * pushes the applied bundle back into settings via `settings.set` so the rest of
 * the app seeds from it. Reads/writes FAIL LOUD — a rejected `settings.get`
 * surfaces an alert (keeping the defaults) instead of being silently swallowed.
 */
function SavePresetsSection(): React.ReactElement {
  const [autosave, setAutosave] = useState<AutosaveSettings>(DEFAULT_AUTOSAVE);
  const [exportDefaults, setExportDefaults] = useState<ExportDefaults>(DEFAULT_EXPORT_DEFAULTS);
  const [error, setError] = useState('');

  useEffect(() => {
    client.settings
      .get()
      .then((raw) => {
        const slice = raw as {
          autosave?: Partial<AutosaveSettings>;
          exportDefaults?: Partial<ExportDefaults>;
        };
        setAutosave({ ...DEFAULT_AUTOSAVE, ...slice.autosave });
        setExportDefaults({ ...DEFAULT_EXPORT_DEFAULTS, ...slice.exportDefaults });
      })
      .catch((err: unknown) => setError(errText(err)));
  }, []);

  const onApply = useCallback(
    (preset: SavePreset): void => {
      const nextAutosave = { ...autosave, ...preset.autosave };
      const nextDefaults = { ...exportDefaults, ...preset.exportDefaults };
      setAutosave(nextAutosave);
      setExportDefaults(nextDefaults);
      client.settings
        .set({ autosave: nextAutosave, exportDefaults: nextDefaults })
        .catch((err: unknown) => setError(errText(err)));
    },
    [autosave, exportDefaults],
  );

  return (
    <>
      {error ? (
        <div className="settings__error" role="alert">
          {error}
        </div>
      ) : null}
      <SavePresetsControls
        rpc={client.savePresets}
        autosave={autosave}
        exportDefaults={exportDefaults}
        onApply={onApply}
      />
    </>
  );
}

/**
 * The Settings sub-sections, in display order. APPEND here to add a section —
 * the sub-nav and the active-panel switch are both derived from this array.
 */
export const SETTINGS_SECTIONS: SettingsSection[] = [
  {
    id: 'models',
    label: 'Models & System',
    // WU-PROVIDERS: a readiness fix action of kind openProviders/setConsent on
    // this panel routes to the Providers & Keys section (where key + consent
    // management now lives), fixing the previous early-return dead-end.
    render: (ctx) => (
      <Suspense fallback={<div className="panel panel--loading">Loading…</div>}>
        <ModelsSystemPanel onOpenProviders={() => ctx.goTo('providers')} />
      </Suspense>
    ),
  },
  {
    id: 'setup',
    label: 'Setup',
    // WU-2: the first-run self-diagnostic. Validates the install end-to-end
    // (writable data dir, device probe, reframe deps, ASR backend, ffmpeg) and
    // reports LOUDLY with fix hints so the user never lands in a broken render.
    render: () => <SetupStatusPanel title="Setup status" />,
  },
  {
    id: 'providers',
    label: 'Providers & Keys',
    // The full key + consent management surface. Its secondary link routes back
    // to Models & System where per-function provider routing lives.
    render: (ctx) => <ProvidersKeys onOpenModels={() => ctx.goTo('models')} />,
  },
  {
    id: 'storage',
    label: 'Storage',
    // Wires the previously-orphaned PathsPanel: SHOW where data lives, change the
    // data root, and open folders in the OS explorer. Read-only layout via
    // `client.paths`; the data-root flow + open-in-folder via the window.api
    // bridge (fail-soft per control when the preload is absent). WU-3b2 appends
    // the managed-copy store meter (used/cap + evict/clear) beneath it.
    render: () => (
      <>
        <PathsPanel rpc={client.paths} bridge={pathsBridge()} />
        <ManagedStoreMeter rpc={client.library} />
      </>
    ),
  },
  {
    id: 'preferences',
    label: 'Caption defaults',
    // P4 §4: the Preferences area — caption style/position, subtitle delivery,
    // and language defaults every new short seeds from (persisted to settings).
    render: () => <CaptionPreferences />,
  },
  {
    id: 'health',
    label: 'System Health',
    render: () => <SystemHealth />,
  },
  {
    id: 'licenses',
    label: 'Licenses',
    // WU-F1 (security HIGH#1b): the mandatory user-facing third-party attribution
    // surface. ViNet-S is CC-BY-NC-SA-4.0 and REQUIRES attribution + a
    // non-commercial notice; this section reproduces it alongside the other
    // bundled model licenses (YuNet/EdgeTAM/TransNetV2/LR-ASD).
    render: () => <ThirdPartyNotices />,
  },
  {
    id: 'presets',
    label: 'Export presets',
    // WU-11: mounts the previously-orphaned SavePresetsControls — list / apply /
    // save / remove named `{autosave, exportDefaults}` bundles. The wrapper reads
    // the live settings a preset bundles and pushes an applied bundle back via
    // `settings.set`, reaching the `savePresets.*` RPCs from the UI at last.
    render: () => <SavePresetsSection />,
  },
];

const SUB_TABS: TabDef[] = SETTINGS_SECTIONS.map(({ id, label }) => ({ id, label }));

export interface SettingsProps {
  /** Which sub-section to open on mount (defaults to the first section). */
  initialSection?: string;
}

/** The Settings view: a sub-tabbed area over Models, Providers, and Health. */
export function Settings({ initialSection }: SettingsProps): React.ReactElement {
  const known = SETTINGS_SECTIONS.some((s) => s.id === initialSection);
  const [active, setActive] = useState(
    known ? (initialSection as string) : SETTINGS_SECTIONS[0].id,
  );

  // `active` is always a known section id, so `find` always resolves; the
  // fallback satisfies the `T | undefined` return type only.
  /* v8 ignore next -- find always resolves for a known active id. */
  const current = SETTINGS_SECTIONS.find((s) => s.id === active) ?? SETTINGS_SECTIONS[0];

  return (
    <div className="settings" aria-label="Settings">
      <TabBar tabs={SUB_TABS} active={active} onSelect={setActive} />
      <div
        className="settings__panel"
        role="tabpanel"
        id={tabPanelId(active)}
        aria-labelledby={tabId(active)}
      >
        {current.render({ goTo: setActive })}
      </div>
    </div>
  );
}

export default Settings;
