// App.tsx — the renderer shell + TOP-LEVEL TABBED NAVIGATION (V1 IA §h).
//
// The app is organised into the FIVE V1 sections (components/TopTabBar.tsx):
//   * Library    — the video library home; opening a video routes into the Edit
//                  section for that video,
//   * Make Shorts — the novice front door: AI moment-pick + manual intervals +
//                   the single produced-shorts gallery + batch/templates
//                   (views/MakeShorts.tsx; carries the interrupted-batch badge),
//   * Edit       — the per-video manual surface (trim/cut/join/reframe/caption/
//                  audio…) hosted in the Workspace (views/Edit.tsx),
//   * Director   — the prompt-driven AI video-editing panel (lazy),
//   * Settings   — Models & System / Providers & Keys / Storage / Health.
//
// The active tab is DERIVED from the route (one source of truth), so navigation
// and the tab strip can never desync. The currently-open Edit video is held in
// shell state so switching tabs and re-entering Edit keeps the same video.
//
// Also hosts the Local/Cloud quality toggle (CONTRACTS.md §0/§2: settings.useCloud)
// and the global Jobs slide-over (components/JobQueue.tsx).
import React, { Suspense, lazy, useCallback, useEffect, useMemo, useState } from 'react';
import { Library } from './views/Library';
import { Edit } from './views/Edit';
import { MakeShorts } from './views/MakeShorts';
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
import { client, hasApi, rpc, type ReadinessAction, type RoutingMode, type Video } from './lib/rpc';
import { RoutingToggle } from './components/RoutingToggle';
import { actionSection } from './features/providersKeysLogic';
import { ToastProvider } from './components/toast/ToastProvider';
import { ToastHost } from './components/toast/ToastHost';
import { JobQueue, JOBQUEUE_PANEL_ID } from './components/JobQueue';
import { SidecarBanner } from './components/SidecarBanner';
import { SecureKeysBanner } from './components/SecureKeysBanner';
import { UpdateBanner } from './components/UpdateBanner';
import { registerJobRetry } from './components/useJob';
// Foundation owns the top-level CSS import (per components/shell.css note).
// Tokens FIRST so every sheet can consume the custom properties.
import './styles/tokens.css';
import './components/shell.css';
import './components/toast/toast.css';
import './components/SidecarBanner.css';
import './components/SecureKeysBanner.css';
import './components/UpdateBanner.css';

// U3 §2: error toasts show a Retry button only when a retry callable is
// registered. U5's job.retry RPC is a protocol.py built-in, so wire it once.
registerJobRetry((jobId) => rpc<{ jobId: string }>('job.retry', { jobId }));

type Quality = 'local' | 'cloud';

/** The five V1 top-level tab ids (the surface switcher). */
type TabId = 'library' | 'makeshorts' | 'edit' | 'director' | 'settings';

type Route =
  // The Library home.
  | { name: 'library' }
  // Make Shorts: AI/manual making + the gallery + batch (resume deep-link).
  | { name: 'makeshorts'; resumeId?: string }
  // Edit: the per-video manual surface (the open video lives in shell state).
  | { name: 'edit' }
  // Director: the prompt-driven AI video-editing panel.
  | { name: 'director' }
  // Settings: a sub-navigated area (Models & System / Providers & Keys / Health).
  | { name: 'settings'; section?: string };

/** Map a route to the top-level tab it belongs to. */
function routeTab(route: Route): TabId {
  switch (route.name) {
    case 'makeshorts':
      return 'makeshorts';
    case 'edit':
      return 'edit';
    case 'director':
      return 'director';
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
  // M3: the cross-cutting RoutingPolicy.global header toggle (Local/Cloud/Auto).
  // DECISION §4: defaults to 'local' and never auto-promotes — it only moves on an
  // explicit user click (RoutingToggle no-ops a re-click). `routingBusy` disables
  // the control while the setRoutingPolicy write is in flight.
  const [routingGlobal, setRoutingGlobal] = useState<RoutingMode>('local');
  const [routingBusy, setRoutingBusy] = useState(false);
  // The currently-open Edit video (kept in shell state so it survives tab
  // switches; null until a video is opened from the Library).
  const [editVideo, setEditVideo] = useState<Video | null>(null);
  // T6: the global job-queue slide-over (components/JobQueue.tsx). Closed by
  // default — the panel polls job.list only while open.
  const [jobsOpen, setJobsOpen] = useState(false);

  // Best-effort hydrate the quality toggle + M3 routing-policy global from
  // persisted settings (one read). An out-of-enum / missing routingPolicy.global
  // keeps the local default (the sidecar read is fail-closed to local anyway).
  useEffect(() => {
    if (!hasApi()) return;
    let cancelled = false;
    void rpc<{ useCloud?: boolean; routingPolicy?: { global?: string } }>('settings.get')
      .then((settings) => {
        if (cancelled || !settings) return;
        if (typeof settings.useCloud === 'boolean') {
          setQuality(settings.useCloud ? 'cloud' : 'local');
        }
        const g = settings.routingPolicy?.global;
        if (g === 'local' || g === 'cloud' || g === 'auto') setRoutingGlobal(g);
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

  // M3: persist the global routing mode via the dedicated, fail-closed write RPC
  // (NOT settings.set — the sidecar sanitises + clamps the policy). Best-effort:
  // the in-memory toggle reflects intent even if the write fails; `routingBusy`
  // gates double-writes.
  const changeRouting = useCallback((mode: RoutingMode) => {
    setRoutingGlobal(mode);
    if (!hasApi()) return;
    setRoutingBusy(true);
    void client.models
      .setRoutingPolicy({ global: mode })
      .catch(() => {
        // Persisting is best-effort; the in-memory toggle still reflects intent.
      })
      .finally(() => setRoutingBusy(false));
  }, []);

  // WU-13: restore the last-opened video on launch. Read the persisted
  // `lastOpenedVideoId`, resolve the Video via library.list, and open it in the
  // Edit section on a match; fall back to the Library home otherwise.
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
          setEditVideo(match);
          setRoute({ name: 'edit' });
        }
      } catch {
        // Best-effort restore; stay on the Library default on any failure.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // Opening a video from the Library routes into the Edit section for it.
  const openVideo = useCallback((video: Video) => {
    setEditVideo(video);
    setRoute({ name: 'edit' });
    // WU-13: persist the last-opened video so launch can restore it. Best-effort.
    if (!hasApi()) return;
    void rpc('settings.set', { lastOpenedVideoId: video.id }).catch(() => {
      // Persisting is best-effort; navigation already happened in-memory.
    });
  }, []);

  const backToLibrary = useCallback(() => {
    setRoute({ name: 'library' });
  }, []);

  // The Make Shorts nav (optionally deep-linking a batch resume from the toast).
  const openMakeShorts = useCallback((resumeId?: string) => {
    setRoute({ name: 'makeshorts', resumeId });
  }, []);

  // Open Settings, optionally pre-selecting a sub-section (e.g. a readiness fix
  // jumps straight to Models & System).
  const openSettings = useCallback((section?: string) => {
    setRoute({ name: 'settings', section });
  }, []);

  // WU-PROVIDERS: a readiness fix action from the Library roll-up routes to the
  // matching Settings section — download actions to Models & System, key/consent
  // actions to Providers & Keys (fixes the always-to-models dead-end).
  const handleReadinessAction = useCallback(
    (action: ReadinessAction) => {
      openSettings(actionSection(action));
    },
    [openSettings],
  );

  // The top-level tab strip switches surfaces. Re-entering Edit shows the
  // currently-open video (or its empty state when none is open yet).
  const selectTab = useCallback(
    (id: string) => {
      switch (id as TabId) {
        case 'makeshorts':
          openMakeShorts();
          break;
        case 'edit':
          setRoute({ name: 'edit' });
          break;
        case 'director':
          setRoute({ name: 'director' });
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
    [openMakeShorts, openSettings],
  );

  // The interrupted-batch badge now rides the Make Shorts tab (batch lives in
  // that section); a resume deep-links into Make Shorts → Batch.
  const batchBadge = useRepurposeBadge(openMakeShorts);

  const tabs: TopTab[] = useMemo(
    () => [
      { id: 'library', label: 'Library', icon: <LibraryIcon /> },
      { id: 'makeshorts', label: 'Make Shorts', icon: <CreateIcon />, badge: batchBadge },
      { id: 'edit', label: 'Edit', icon: <RepurposeIcon /> },
      { id: 'director', label: 'Director', icon: <DirectorIcon /> },
      { id: 'settings', label: 'Settings', icon: <SettingsIcon /> },
    ],
    [batchBadge],
  );

  const activeTab = routeTab(route);

  function renderRoute(): React.ReactElement {
    switch (route.name) {
      case 'makeshorts':
        return <MakeShorts resumeId={route.resumeId} />;
      case 'edit':
        return <Edit video={editVideo} onBack={backToLibrary} />;
      case 'director':
        return (
          <Suspense fallback={<div className="panel panel--loading">Loading…</div>}>
            {/* WU-E1: thread the app-selected video so the Director plans against
                video.id (never the goal text); the empty-state CTA routes to the
                Library to pick one. */}
            <DirectorPanel video={editVideo} onChooseVideo={backToLibrary} />
          </Suspense>
        );
      case 'settings':
        return <Settings initialSection={route.section} />;
      case 'library':
      default:
        // WU-14: a readiness fix action routes to Settings → Models & System.
        return <Library onOpen={openVideo} onReadinessAction={handleReadinessAction} />;
    }
  }

  return (
    <>
      <div className="app">
        <header className="app__bar">
          <span className="app__brand">Reframe</span>
          <QualityToggle quality={quality} onChange={changeQuality} />
          <RoutingToggle value={routingGlobal} onChange={changeRouting} busy={routingBusy} />
          <button
            type="button"
            className="app__jobs-toggle"
            aria-expanded={jobsOpen}
            aria-controls={JOBQUEUE_PANEL_ID}
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
      <SecureKeysBanner />
      <UpdateBanner />
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
