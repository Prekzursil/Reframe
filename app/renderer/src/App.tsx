// App.tsx — the renderer shell + TOP-LEVEL TABBED NAVIGATION (CONTRACTS.md §1).
//
// The app is organised into five top-level tabs (components/TopTabBar.tsx):
//   * Library    — the video library home; opening a video drills into its
//                  per-video Workspace (a sub-state of this tab; "← Library"
//                  returns home),
//   * Create     — the global generated-Shorts gallery + ShortMaker flow,
//   * Director    — the prompt-driven AI video-editing panel (lazy),
//   * Repurpose  — the batch/template/export-preset surface (with a (N) badge +
//                  resume toast for interrupted batches),
//   * Settings   — a sub-navigated area: Models & System, Providers & Keys, and
//                  System Health (views/Settings.tsx).
//
// The active tab is DERIVED from the route (one source of truth), so navigation
// and the tab strip can never desync. Workspace lives under the Library tab.
//
// Also hosts the Local/Cloud quality toggle (CONTRACTS.md §0/§2: settings.useCloud)
// and the global Jobs slide-over (components/JobQueue.tsx).
import React, { Suspense, lazy, useCallback, useEffect, useMemo, useState } from 'react';
import { Library } from './views/Library';
import { Workspace } from './views/Workspace';
import { Shorts } from './views/Shorts';
import { Repurpose } from './views/Repurpose';
import { Settings } from './views/Settings';
import { incompleteBatches, remainingCount } from './features/repurposeLogic';
import { useToast } from './components/toast/useToast';
import { TopTabBar, topTabId, topTabPanelId, type TopTab } from './components/TopTabBar';
import {
  CreateIcon,
  DirectorIcon,
  LibraryIcon,
  RepurposeIcon,
  SettingsIcon,
} from './components/navIcons';
// AI Director panel (lazy: it pulls the storyboard/diff + cost-banner surface).
const DirectorPanel = lazy(() => import('./panels/DirectorPanel'));
import { client, hasApi, rpc, type ShortReexportHint, type Video } from './lib/rpc';
import { ToastProvider } from './components/toast/ToastProvider';
import { ToastHost } from './components/toast/ToastHost';
import { JobQueue } from './components/JobQueue';
import { SidecarBanner } from './components/SidecarBanner';
import { registerJobRetry } from './components/useJob';
// Foundation owns the top-level CSS import (per components/shell.css note).
// Tokens FIRST so every sheet can consume the custom properties.
import './styles/tokens.css';
import './components/shell.css';
import './components/toast/toast.css';
import './components/SidecarBanner.css';

// U3 §2: error toasts show a Retry button only when a retry callable is
// registered. U5's job.retry RPC is a protocol.py built-in, so wire it once.
registerJobRetry((jobId) => rpc<{ jobId: string }>('job.retry', { jobId }));

type Quality = 'local' | 'cloud';

/** The five top-level tab ids (the surface switcher). */
type TabId = 'library' | 'create' | 'director' | 'repurpose' | 'settings';

type Route =
  // The Library tab. `video` drills into a per-video Workspace (Library sub-state).
  | { name: 'library'; video?: Video }
  // Create: the global generated-shorts gallery + ShortMaker flow.
  | { name: 'create' }
  // Director: the prompt-driven AI video-editing panel.
  | { name: 'director' }
  // Repurpose: the batch queue / templates / export presets surface.
  | { name: 'repurpose'; resumeId?: string }
  // Settings: a sub-navigated area (Models & System / Providers & Keys / Health).
  | { name: 'settings'; section?: string };

/** Map a route to the top-level tab it belongs to (Workspace ⇒ Library). */
function routeTab(route: Route): TabId {
  switch (route.name) {
    case 'create':
      return 'create';
    case 'director':
      return 'director';
    case 'repurpose':
      return 'repurpose';
    case 'settings':
      return 'settings';
    case 'library':
    default:
      return 'library';
  }
}

/** Local/Cloud quality toggle. Maps to settings.useCloud (CONTRACTS.md §2). */
function QualityToggle({
  quality,
  onChange,
}: {
  quality: Quality;
  onChange: (q: Quality) => void;
}): React.ReactElement {
  return (
    <div className="quality-toggle" role="group" aria-label="Quality">
      <span className="quality-toggle__label">Quality</span>
      <button
        type="button"
        className={`quality-toggle__btn${quality === 'local' ? ' is-active' : ''}`}
        aria-pressed={quality === 'local'}
        onClick={() => onChange('local')}
      >
        Local
      </button>
      <button
        type="button"
        className={`quality-toggle__btn${quality === 'cloud' ? ' is-active' : ''}`}
        aria-pressed={quality === 'cloud'}
        onClick={() => onChange('cloud')}
      >
        Cloud
      </button>
    </div>
  );
}

/**
 * Reads `batch.list` once on mount and reports the count of interrupted batches
 * (rendered as the Repurpose tab's (N) badge), plus a one-time dismissible toast
 * deep-linking into the oldest interrupted batch (§7.2). Renders nothing itself.
 */
function useRepurposeBadge(onResume: (resumeId: string) => void): number {
  const [badge, setBadge] = useState(0);
  const toast = useToast();
  const toastedRef = React.useRef(false);

  useEffect(() => {
    if (!hasApi()) return;
    let cancelled = false;
    void client.batch
      .list()
      .then(({ batches }) => {
        if (cancelled) return;
        const incomplete = incompleteBatches(batches);
        setBadge(incomplete.length);
        if (incomplete.length > 0 && !toastedRef.current) {
          toastedRef.current = true;
          const first = incomplete[0];
          const left = remainingCount(first.counts);
          toast.info(
            `A batch ('${first.name}') was interrupted — ${left} of ${first.counts.total} sources left.`,
            { action: { label: 'Resume', onClick: () => onResume(first.id) } },
          );
        }
      })
      .catch(() => {
        // best-effort: no badge/toast if the read fails.
      });
    return () => {
      cancelled = true;
    };
  }, [toast, onResume]);

  return badge;
}

/**
 * The app shell. Rendered INSIDE ToastProvider (App below) so the Repurpose
 * badge hook (useToast) has a provider in context. Owns all route + UI state.
 */
function AppShell(): React.ReactElement {
  const [route, setRoute] = useState<Route>({ name: 'library' });
  const [quality, setQuality] = useState<Quality>('local');
  // T6: the global job-queue slide-over (components/JobQueue.tsx). Closed by
  // default — the panel polls job.list only while open.
  const [jobsOpen, setJobsOpen] = useState(false);

  // Best-effort hydrate the quality toggle from persisted settings.
  useEffect(() => {
    if (!hasApi()) return;
    let cancelled = false;
    void rpc<{ useCloud?: boolean }>('settings.get')
      .then((settings) => {
        if (!cancelled && settings && typeof settings.useCloud === 'boolean') {
          setQuality(settings.useCloud ? 'cloud' : 'local');
        }
      })
      .catch(() => {
        // Settings may be unavailable early; keep the local default.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const changeQuality = useCallback((q: Quality) => {
    setQuality(q);
    if (!hasApi()) return;
    void rpc('settings.set', { useCloud: q === 'cloud' }).catch(() => {
      // Persisting is best-effort; the in-memory toggle still reflects intent.
    });
  }, []);

  // WU-13: restore the last-opened video on launch. Read the persisted
  // `lastOpenedVideoId`, resolve the Video via library.list, and drill into its
  // Workspace on a match; fall back to the Library home otherwise.
  useEffect(() => {
    if (!hasApi()) return;
    let cancelled = false;
    void (async () => {
      try {
        const settings = await rpc<{ lastOpenedVideoId?: string }>('settings.get');
        const id = settings?.lastOpenedVideoId;
        if (cancelled || !id) return;
        const { videos } = await client.library.list();
        const match = videos.find((v) => v.id === id);
        if (!cancelled && match) {
          setRoute({ name: 'library', video: match });
        }
      } catch {
        // Best-effort restore; stay on the Library default on any failure.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const openVideo = useCallback((video: Video) => {
    setRoute({ name: 'library', video });
    // WU-13: persist the last-opened video so launch can restore it. Best-effort.
    if (!hasApi()) return;
    void rpc('settings.set', { lastOpenedVideoId: video.id }).catch(() => {
      // Persisting is best-effort; navigation already happened in-memory.
    });
  }, []);

  const backToLibrary = useCallback(() => {
    setRoute({ name: 'library' });
  }, []);

  // WU11: the Repurpose nav (optionally deep-linking a resume from the toast).
  const openRepurpose = useCallback((resumeId?: string) => {
    setRoute({ name: 'repurpose', resumeId });
  }, []);

  // Open Settings, optionally pre-selecting a sub-section (e.g. a readiness fix
  // jumps straight to Models & System).
  const openSettings = useCallback((section?: string) => {
    setRoute({ name: 'settings', section });
  }, []);

  // The top-level tab strip switches surfaces (Workspace returns to the Library
  // home rather than staying drilled-in).
  const selectTab = useCallback(
    (id: string) => {
      switch (id as TabId) {
        case 'create':
          setRoute({ name: 'create' });
          break;
        case 'director':
          setRoute({ name: 'director' });
          break;
        case 'repurpose':
          openRepurpose();
          break;
        case 'settings':
          openSettings();
          break;
        case 'library':
        default:
          setRoute({ name: 'library' });
          break;
      }
    },
    [openRepurpose, openSettings],
  );

  // P4 §6: Re-export reopens the source video's Workspace (where the Short-maker
  // tab lives). Resolve the source Video by id, then drill into its Workspace
  // under the Library tab; fall back to the Library home when it is gone.
  const handleReexport = useCallback(async (hint: ShortReexportHint) => {
    if (!hint.videoId || !hasApi()) {
      setRoute({ name: 'library' });
      return;
    }
    try {
      const { videos } = await client.library.list();
      const source = videos.find((v) => v.id === hint.videoId);
      setRoute(source ? { name: 'library', video: source } : { name: 'library' });
    } catch {
      setRoute({ name: 'library' });
    }
  }, []);

  const repurposeBadge = useRepurposeBadge(openRepurpose);

  const tabs: TopTab[] = useMemo(
    () => [
      { id: 'library', label: 'Library', icon: <LibraryIcon /> },
      { id: 'create', label: 'Create', icon: <CreateIcon /> },
      { id: 'director', label: 'Director', icon: <DirectorIcon /> },
      { id: 'repurpose', label: 'Repurpose', icon: <RepurposeIcon />, badge: repurposeBadge },
      { id: 'settings', label: 'Settings', icon: <SettingsIcon /> },
    ],
    [repurposeBadge],
  );

  const activeTab = routeTab(route);

  function renderRoute(): React.ReactElement {
    switch (route.name) {
      case 'create':
        return <Shorts onReexport={(hint) => void handleReexport(hint)} />;
      case 'director':
        return (
          <Suspense fallback={<div className="panel panel--loading">Loading…</div>}>
            <DirectorPanel />
          </Suspense>
        );
      case 'repurpose':
        return <Repurpose resumeId={route.resumeId} />;
      case 'settings':
        return <Settings initialSection={route.section} />;
      case 'library':
      default:
        // Drilled into a video → its Workspace; otherwise the Library home.
        // WU-14: a readiness fix action routes to Settings → Models & System.
        return route.video ? (
          <Workspace video={route.video} onBack={backToLibrary} />
        ) : (
          <Library onOpen={openVideo} onReadinessAction={() => openSettings('models')} />
        );
    }
  }

  return (
    <>
      <div className="app">
        <header className="app__bar">
          <span className="app__brand">Reframe - Media Studio</span>
          <QualityToggle quality={quality} onChange={changeQuality} />
          <button
            type="button"
            className="app__jobs-toggle"
            aria-expanded={jobsOpen}
            onClick={() => setJobsOpen((open) => !open)}
          >
            Jobs
          </button>
        </header>

        <TopTabBar tabs={tabs} active={activeTab} onSelect={selectTab} />

        <main
          className="app__main"
          role="tabpanel"
          id={topTabPanelId(activeTab)}
          aria-labelledby={topTabId(activeTab)}
        >
          {renderRoute()}
        </main>
      </div>
      <JobQueue open={jobsOpen} onClose={() => setJobsOpen(false)} />
      <SidecarBanner />
      <ToastHost />
    </>
  );
}

/** Root: provides the toast context, then renders the app shell. */
export function App(): React.ReactElement {
  return (
    <ToastProvider>
      <AppShell />
    </ToastProvider>
  );
}

export default App;
