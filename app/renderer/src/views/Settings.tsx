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
import React, { Suspense, lazy, useState } from 'react';
import { TabBar, type TabDef } from '../components/TabBar';
import { SystemHealth } from '../features/SystemHealth';
import { ProvidersKeys } from '../features/ProvidersKeys';
import { PathsPanel, type PathsBridge } from '../components/PathsPanel';
import { client } from '../lib/rpc';
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
    // bridge (fail-soft per control when the preload is absent).
    render: () => <PathsPanel rpc={client.paths} bridge={pathsBridge()} />,
  },
  {
    id: 'health',
    label: 'System Health',
    render: () => <SystemHealth />,
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
      <div className="settings__panel">{current.render({ goTo: setActive })}</div>
    </div>
  );
}

export default Settings;
