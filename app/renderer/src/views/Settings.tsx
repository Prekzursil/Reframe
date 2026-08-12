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
// `SETTINGS_SECTIONS` is therefore the SSOT for which sub-sections exist; read it,
// not a list here. This header used to carry its own three-entry list describing
// `providers` as a "NEW placeholder (real empty-state; later WUs wire
// components/ProviderKeyRow + AddKeyRow here)". By then the array held EIGHT
// sections and the wiring was DONE — <ProvidersKeys> is imported and rendered
// below, and ProvidersKeys.tsx / ProviderKeyRow.tsx / AddKeyRow.tsx all exist. A
// false "this is a stub" disclosure is worse than a stale one: it tells a reader a
// shipped feature is unbuilt, so the next WU either rebuilds it or skips reviewing
// it. The list is gone rather than corrected, because a duplicated enumeration next
// to its own source is what produced the false claim in the first place.
import React, {
  Suspense,
  lazy,
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from 'react';
import { TabBar, tabId, tabPanelId, type TabDef } from '../components/TabBar';
import { SystemHealth } from '../features/SystemHealth';
import { ProvidersKeys } from '../features/ProvidersKeys';
import { PathsPanel, type PathsBridge } from '../components/PathsPanel';
import { ManagedStoreMeter } from '../components/ManagedStoreMeter';
import { SetupStatusPanel } from '../components/SetupStatusPanel';
import { Skeleton } from '../components/Skeleton';
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
    // Q8: the fallback was the literal string "Loading…" — the exact thing
    // Library.tsx's own comment writes down as forbidden ("never a bare
    // LOADING…"), on the heaviest panel in the app. It is now the shared
    // <Skeleton />, which buys two things and no more:
    //   * the layout JUMP IS REDUCED, not removed — the ghost echoes the SHAPE
    //     (heading bar over body lines) of what lands, not its HEIGHT, and
    //     ModelsSystemPanel is far taller than four bars. UNVERIFIED at pixel
    //     level; settle it by measuring the fallback's offsetHeight against the
    //     loaded panel's with the chunk throttled.
    //   * the wait is a NAMED busy status region carrying real text, where it
    //     used to be an unnamed div. Whether a screen reader SPEAKS it on
    //     insertion is NOT-CHECKED — see the a11y note in Skeleton.tsx for why
    //     that is a weaker claim than it looks, and the experiment that settles it.
    render: (ctx) => (
      <Suspense
        fallback={
          <Skeleton
            variant="panel"
            className="panel panel--loading"
            label="Loading Models & System"
          />
        }
      >
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

/** The Settings view: a sub-tabbed area over every `SETTINGS_SECTIONS` entry. */
export function Settings({ initialSection }: SettingsProps): React.ReactElement {
  const known = SETTINGS_SECTIONS.some((s) => s.id === initialSection);
  const [active, setActive] = useState(
    known ? (initialSection as string) : SETTINGS_SECTIONS[0].id,
  );

  // `active` is always a known section id, so `find` always resolves; the
  // fallback satisfies the `T | undefined` return type only.
  /* v8 ignore next -- find always resolves for a known active id. */
  const current = SETTINGS_SECTIONS.find((s) => s.id === active) ?? SETTINGS_SECTIONS[0];

  // C1 (docs/plans/v1.5/uiux-qol-audit-2026-08.md §5) — Settings LANDED SCROLLED,
  // so a section's own title and its primary CTA started above the fold. Measured
  // on the installed app at ~503 px for MODELS & SYSTEM — the DEFAULT tab, hence
  // the first screen a new user sees, with the ONLY "Download the Multimodal
  // model" button off-screen.
  //
  // `.settings__panel` (settings.css:12, `overflow: auto`) is this view's ONE
  // scroll container, and React reuses that DOM node across sections — it carries
  // no `key`, and a section change only swaps its children — so the offset the
  // user left on the PREVIOUS section survives into the next one. Measured in
  // Settings.test.tsx by reading the container's own `scrollTop`.
  //
  // A layout effect (not `useEffect`) so the reset lands in the same frame as the
  // swap and the user never sees the mid-panel paint. `panelRef` is always
  // attached by the time an effect runs, so assert non-null rather than adding an
  // unreachable branch (the `btnRefs.current[nextId]!` / `goalRef.current!`
  // convention already used in TabBar.tsx:201 and DirectorPanel.tsx:473).
  //
  // SCOPE — this fixes the offset CARRIED ACROSS a section change, which is the
  // audit's HEALTH→MODELS entry. UNVERIFIED: whether the audit's other entry
  // (Library→Settings, a fresh mount, which starts at 0 and is reset again here)
  // shares this cause; no renderer code scrolls this container (`scrollIntoView`,
  // `scrollTo` and `window.scroll` have zero hits under renderer/src), so any
  // residual offset there would have to come from the browser (focus restoration
  // or scroll anchoring) AFTER this effect, which a mount-time reset would not
  // catch. Settling experiment: open the packaged app with `Ctrl+Shift+I`, enter
  // Settings from the Library, and log `.settings__panel.scrollTop` on an
  // interval across the first second — a value that starts 0 and grows names an
  // asynchronous scroller this reset cannot see.
  const panelRef = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    panelRef.current!.scrollTop = 0;
  }, [active]);

  return (
    <div className="settings" aria-label="Settings">
      <TabBar tabs={SUB_TABS} active={active} onSelect={setActive} />
      <div
        className="settings__panel"
        ref={panelRef}
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
