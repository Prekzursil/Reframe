// App.tsx — the renderer router skeleton (CONTRACTS.md §1: src/App.tsx).
// Two views: the Library home and the per-video Workspace. Selecting a video in
// the Library navigates to its Workspace; "← Library" returns home.
//
// Also hosts the Local/Cloud quality toggle stub (CONTRACTS.md §0/§2:
// settings.useCloud). It is a thin control that flips local vs cloud quality and
// persists the choice through `settings.set` when the bridge is available; if no
// bridge is present (e.g. early boot / tests) it degrades to local-only state.
import React, { Suspense, lazy, useCallback, useEffect, useState } from 'react';
import { Library } from './views/Library';
import { Workspace } from './views/Workspace';
import { Shorts } from './views/Shorts';
import { SystemHealth } from './features/SystemHealth';
// Phase-8 "Models & System" panel (lazy: it pulls the model-card grid + onboarding).
const ModelsSystemPanel = lazy(() => import('./panels/ModelsSystemPanel'));
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

type Route =
  | { name: 'library' }
  | { name: 'workspace'; video: Video }
  // P4 §6 / C11: the global generated-shorts gallery (across all videos).
  | { name: 'shorts' }
  // system-advanced: the app-global System Health diagnostic screen.
  | { name: 'health' }
  // Phase-8: the app-global "Models & System" graphics-settings panel.
  | { name: 'models' };

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

export function App(): React.ReactElement {
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

  // WU-13: restore the last-opened video on launch. This is its own async path
  // (NOT bolted onto the sync quality-hydrate effect above): read the persisted
  // `lastOpenedVideoId` from settings, then resolve the Video via library.list
  // (mirroring handleReexport). Navigate to its Workspace on a match; fall back
  // to the Library home (the default route) when the video is gone or absent.
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
          setRoute({ name: 'workspace', video: match });
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
    setRoute({ name: 'workspace', video });
    // WU-13: persist the last-opened video so launch can restore it. Best-effort.
    if (!hasApi()) return;
    void rpc('settings.set', { lastOpenedVideoId: video.id }).catch(() => {
      // Persisting is best-effort; navigation already happened in-memory.
    });
  }, []);

  const backToLibrary = useCallback(() => {
    setRoute({ name: 'library' });
  }, []);

  // P4 §6 / C11: the top-level Shorts gallery nav.
  const openShorts = useCallback(() => {
    setRoute({ name: 'shorts' });
  }, []);

  // system-advanced: the top-level System Health nav.
  const openHealth = useCallback(() => {
    setRoute({ name: 'health' });
  }, []);

  // Phase-8: the top-level "Models & System" nav.
  const openModels = useCallback(() => {
    setRoute({ name: 'models' });
  }, []);

  // P4 §6: Re-export reopens the source video's Workspace (where the
  // Short-maker tab lives) so the user can replay the export. Resolve the
  // source Video by id via library.list, then navigate; fall back to the
  // Library home when the source is no longer present.
  const handleReexport = useCallback(async (hint: ShortReexportHint) => {
    if (!hint.videoId || !hasApi()) {
      setRoute({ name: 'library' });
      return;
    }
    try {
      const { videos } = await client.library.list();
      const source = videos.find((v) => v.id === hint.videoId);
      setRoute(source ? { name: 'workspace', video: source } : { name: 'library' });
    } catch {
      setRoute({ name: 'library' });
    }
  }, []);

  function renderRoute(): React.ReactElement {
    switch (route.name) {
      case 'workspace':
        return <Workspace video={route.video} onBack={backToLibrary} />;
      case 'shorts':
        return <Shorts onReexport={(hint) => void handleReexport(hint)} />;
      case 'health':
        return <SystemHealth />;
      case 'models':
        return (
          <Suspense fallback={<div className="panel panel--loading">Loading…</div>}>
            <ModelsSystemPanel />
          </Suspense>
        );
      case 'library':
      default:
        // WU-14: a readiness fix action on the library roll-up routes to the
        // Models & System panel, where the provider/asset flows live.
        return <Library onOpen={openVideo} onReadinessAction={openModels} />;
    }
  }

  return (
    <ToastProvider>
      <div className="app">
        <header className="app__bar">
          <span className="app__brand">Reframe - Media Studio</span>
          {/* P4 §6 / C11: top-level view nav (Library vs the Shorts gallery). */}
          <nav className="app__nav" aria-label="Views">
            <button
              type="button"
              className={`app__nav-btn${route.name === 'library' ? ' is-active' : ''}`}
              aria-current={route.name === 'library' ? 'page' : undefined}
              onClick={backToLibrary}
            >
              Library
            </button>
            <button
              type="button"
              className={`app__nav-btn${route.name === 'shorts' ? ' is-active' : ''}`}
              aria-current={route.name === 'shorts' ? 'page' : undefined}
              onClick={openShorts}
            >
              Shorts
            </button>
            <button
              type="button"
              className={`app__nav-btn${route.name === 'health' ? ' is-active' : ''}`}
              aria-current={route.name === 'health' ? 'page' : undefined}
              onClick={openHealth}
            >
              Health
            </button>
            <button
              type="button"
              className={`app__nav-btn${route.name === 'models' ? ' is-active' : ''}`}
              aria-current={route.name === 'models' ? 'page' : undefined}
              onClick={openModels}
            >
              Models &amp; System
            </button>
          </nav>
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

        <main className="app__main">{renderRoute()}</main>
      </div>
      <JobQueue open={jobsOpen} onClose={() => setJobsOpen(false)} />
      <SidecarBanner />
      <ToastHost />
    </ToastProvider>
  );
}

export default App;
