// App.tsx — the renderer shell + the TOP-LEVEL RAIL (L5, owner-locked).
//
// The `tabs` array below is the SSOT for the rail (components/TopTabBar.tsx
// renders it). This comment mirrors it in the SAME ORDER and must be re-read
// against it on any change.
//
// L5 took the rail from EIGHT destinations to FOUR + Settings. The eight were
// Library / Make Shorts / Edit / Caption / Export / Deliver / Director / Settings
// — four of which ("where do I make a short?", "where do I finish?") had two
// answers in two places. Nothing was deleted: each old destination is now a MODE
// of the destination that owns its job, reached by a small sub-navigation inside
// it. The rail:
//   * Library  — the video library home; opening a video routes into Refine,
//   * Produce  — BOTH AI paths in one place (L5 G-6): "Make Shorts"
//                (candidate-driven, views/MakeShorts.tsx, carries the
//                interrupted-batch badge) and "Director" (prompt-driven,
//                views/Director.tsx, lazy). Same job — AI proposes, you review,
//   * Refine   — the editor: "Editor" (views/Edit.tsx) and "Caption design" (the
//                v1.5 Caption phase pilot). SCOPE, because the obvious reading is
//                wrong: "Editor" is not the Workspace directly. views/Edit.tsx
//                still opens on its Task Hub (Edit.tsx:69 `useState('hub')`, :163)
//                and mounts the Workspace — preview + docked timeline +
//                selection-driven inspector — only after a card is picked, or
//                immediately when a remembered hub choice resumes there, which is
//                exactly the two choices `resumeFor` maps to `{kind:'workspace'}`
//                (lib/taskHub.ts:109 'subtitles', :111 'advanced'). So the L5
//                "timeline with zero navigation actions" invariant holds from the
//                Workspace mount, NOT from a first open of this destination.
//
//                THAT GAP IS REAL AND UNOWNED — and the reason previously given for
//                deferring it is now FALSE. This block used to close with "Edit.tsx
//                is outside its file scope and byte-unchanged on this branch",
//                which was true when the L5 lane wrote it and was invalidated two
//                commits later: #427 (a4dbec7c) adopted the shared EmptyState in
//                views/Edit.tsx, so `git diff --name-status 1fa9a69f a4dbec7c --
//                app` lists `M app/renderer/src/views/Edit.tsx`. The deferral was
//                therefore resting on a premise that no longer holds, with no lane
//                owning the fix — which is how a locked acceptance invariant stays
//                broken indefinitely while every individual PR looks reasonable.
//                (#427 changed only the no-video empty state, so it did NOT make
//                the invariant worse. The defect is the orphaned ownership.)
//
//                OWNER DECISION REQUIRED, deliberately not taken here: closing it
//                means flipping Edit.tsx:70 `useState<'hub'|'workspace'>('hub')` to
//                land on 'workspace' when a video is already open. That is a
//                PRODUCT change — it demotes the Task Hub from the default landing
//                surface — not a mechanical repair, so it is surfaced rather than
//                applied. Until it is taken, G-7 invariant 2 does not hold and no
//                doc, comment or PR body may claim otherwise.
//   * Deliver  — getting files out: "Finish" (Phase-5 guarded commit for ONE
//                video, views/Export.tsx) and "Publish" (cross-video / batch
//                publish + platform presets + the pro EDL/CSV handoff),
//   * Settings — a sub-tabbed area; views/Settings.tsx `SETTINGS_SECTIONS` is the
//                SSOT for which sub-sections exist (deliberately not re-listed
//                here — the duplicate list is what rotted).
//
// UNVERIFIED that this comment stays in step: nothing mechanically checks prose
// against `tabs`, so the only guard is the re-read above. What IS mechanical is
// the COUNT — App.test.tsx pins the rail at exactly 5 entries (L5 G-7 invariant
// 3), which is the number that actually regressed before.
//
// The active destination is DERIVED from the route (one source of truth), so
// navigation and the rail can never desync. The currently-open video is held in
// shell state so switching destinations and coming back keeps the same video.
//
// Also hosts the Local/Cloud quality toggle (CONTRACTS.md §0/§2: settings.useCloud)
// and the global Jobs slide-over (components/JobQueue.tsx).
import React, { Suspense, lazy, useCallback, useEffect, useMemo, useState } from 'react';
import { Library } from './views/Library';
import { Edit } from './views/Edit';
import { Caption } from './views/Caption';
import { Export } from './views/Export';
import { Deliver } from './views/Deliver';
import { MakeShorts } from './views/MakeShorts';
import { Settings } from './views/Settings';
import { incompleteBatches, remainingCount } from './features/repurposeLogic';
import { DirectorSessionProvider } from './features/directorSession';
import { lineageActions } from './features/lineageActionsClient';
import { libraryShortsClient } from './features/libraryShortsClient';
import { useToast } from './components/toast/useToast';
import { TopTabBar, topTabId, topTabPanelId, type TopTab } from './components/TopTabBar';
import { TabBar, tabId, tabPanelId, type TabDef } from './components/TabBar';
import {
  CreateIcon,
  DeliverIcon,
  LibraryIcon,
  RepurposeIcon,
  SettingsIcon,
} from './components/navIcons';
// Director rail destination (lazy: it pulls the DirectorPanel storyboard/diff +
// cost-banner surface, the shared editor stage, and the per-phase hand-off).
const Director = lazy(() => import('./views/Director'));
import {
  client,
  hasApi,
  rpc,
  type ReadinessAction,
  type RoutingMode,
  type ShortInfo,
  type Video,
} from './lib/rpc';
import { RoutingToggle } from './components/RoutingToggle';
import { actionSection } from './features/providersKeysLogic';
import { ToastProvider } from './components/toast/ToastProvider';
import { ToastHost } from './components/toast/ToastHost';
import { JobQueue, JOBQUEUE_PANEL_ID } from './components/JobQueue';
import { useActiveJobs } from './components/useActiveJobs';
import { SidecarBanner } from './components/SidecarBanner';
import { FirstRunSetup, useFirstRunSetup } from './components/FirstRunSetup';
import { SecureKeysBanner } from './components/SecureKeysBanner';
import { UpdateBanner } from './components/UpdateBanner';
import { registerJobRetry } from './components/useJob';
// Foundation owns the top-level CSS import (per components/shell.css note).
// Tokens FIRST so every sheet can consume the custom properties.
import './styles/tokens.css';
// Self-hosted @font-face bindings for the type trio the tokens lead with (Inter /
// Newsreader / IBM Plex Mono); without them those leads decay to system fallbacks.
import './styles/fonts.css';
// H5: the GLOBAL form-control floor (select / fieldset / legend). Element
// selectors only, so every component sheet below still overrides it by class.
// Must load BEFORE the component sheets for that ordering to hold.
import './styles/controls.css';
import './components/shell.css';
import './components/toast/toast.css';
import './components/SidecarBanner.css';
import './components/SecureKeysBanner.css';
import './components/UpdateBanner.css';

// U3 §2: error toasts show a Retry button only when a retry callable is
// registered. U5's job.retry RPC is a protocol.py built-in, so wire it once.
registerJobRetry((jobId) => rpc<{ jobId: string }>('job.retry', { jobId }));

type Quality = 'local' | 'cloud';

/** The rail's destination ids (L5 G-6: 4 + Settings, and no more). */
type TabId = 'library' | 'produce' | 'refine' | 'deliver' | 'settings';

/** Produce hosts BOTH AI paths — candidate-driven and prompt-driven. */
type ProduceMode = 'shorts' | 'director';
/** Refine hosts the editor and the caption-design pilot. */
type RefineMode = 'editor' | 'caption';
/** Deliver hosts the single-video finish and the cross-video publish. */
type DeliverMode = 'finish' | 'publish';

/**
 * The MODE sub-navigations. These are what let the rail shrink to five without
 * dropping a destination: each old top-level entry became a mode of the
 * destination that owns its job.
 *
 * They are deliberately TINY and fixed — two entries each. A destination whose
 * mode list starts growing is the tab-strip ratchet reappearing one level down;
 * the answer there is selection-driven disclosure INSIDE the destination (as
 * Refine does), not a sixth mode.
 */
export const PRODUCE_MODES: TabDef[] = [
  { id: 'shorts', label: 'Make Shorts' },
  { id: 'director', label: 'Director' },
];
export const REFINE_MODES: TabDef[] = [
  { id: 'editor', label: 'Editor' },
  { id: 'caption', label: 'Caption design' },
];
export const DELIVER_MODES: TabDef[] = [
  { id: 'finish', label: 'Finish' },
  { id: 'publish', label: 'Publish' },
];

/**
 * The mode nav's DOM ids are NAMESPACED, and the prefix is load-bearing.
 *
 * `components/TabBar` mints its ids from ONE flat global namespace — `tab-<id>` /
 * `tabpanel-<id>` — so NESTING a TabBar-based mode nav around a view that also uses
 * TabBar collides the moment a mode id equals one of that view's tab ids. It did:
 * `DELIVER_MODES` has `publish` and `views/Deliver.tsx`'s own TABS has `publish`,
 * so the route {deliver, publish} — reachable by click AND by `openDeliver()` when
 * a Phase-5 render finishes — carried TWO elements with `id="tab-publish"`, one of
 * them the target of the mode panel's `aria-labelledby` below. That is the same
 * invalid-ARIA-IDREF family the mode panel itself exists to prevent.
 *
 * Prefixing here fixes every present and future nesting rather than one pair, and
 * keeps the ROUTE's mode values (`publish`) readable — the prefix is a rendering
 * detail of the tablist, not part of the navigation model.
 */
const MODE_TAB_PREFIX = 'mode-';
const modeTabId = (mode: string): string => `${MODE_TAB_PREFIX}${mode}`;
const modeOfTabId = (tab: string): string => tab.slice(MODE_TAB_PREFIX.length);

type Route =
  // The Library home.
  | { name: 'library' }
  // Produce: AI proposes, you review. `resumeId` deep-links a batch resume from
  // the toast; `videoId` pre-selects a source video (the single ShortMaker owner
  // is here, so the Workspace's short-maker deep-link lands on it).
  | { name: 'produce'; mode: ProduceMode; resumeId?: string; videoId?: string }
  // Refine: the per-video editor (the open video lives in shell state).
  | { name: 'refine'; mode: RefineMode }
  // Deliver: get files out — finish one video, or publish across videos.
  | { name: 'deliver'; mode: DeliverMode }
  // Settings: a sub-navigated area (Models & System / Providers & Keys / Health).
  | { name: 'settings'; section?: string };

/** Map a route to the rail destination it belongs to. */
function routeTab(route: Route): TabId {
  switch (route.name) {
    case 'produce':
      return 'produce';
    case 'refine':
      return 'refine';
    case 'deliver':
      return 'deliver';
    case 'settings':
      return 'settings';
    case 'library':
    default:
      return 'library';
  }
}

/** A small monitor glyph anchoring the "AI model" scope (decorative — aria-hidden). */
function ModelIcon(): React.ReactElement {
  return (
    <svg
      className="quality-toggle__icon"
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      focusable="false"
      aria-hidden="true"
    >
      <rect x="2" y="3" width="20" height="14" rx="2" />
      <path d="M8 21h8" />
      <path d="M12 17v4" />
    </svg>
  );
}

/**
 * The "AI model" quality toggle. Maps to settings.useCloud (CONTRACTS.md §2) —
 * the coarse cloud-vs-local switch for the model backends (LLM/embedder/
 * translation/media). WU-D5: this control sits directly beside the routing toggle
 * and both are about local-vs-cloud, so it is scoped as a DISTINCT axis — "AI
 * model" (which model tier runs) vs the routing toggle's "Where jobs run" — and
 * shares the routing toggle's Local/Cloud vocabulary so the axis reads identically
 * in both. WU-2c's "This computer" wording is replaced by the shared "Local" label
 * (design-review P0: divergent vocab across the twin controls). The underlying
 * 'local'/'cloud' values + handler are unchanged (relabel + rescope only).
 */
function QualityToggle({
  quality,
  onChange,
}: {
  quality: Quality;
  onChange: (q: Quality) => void;
}): React.ReactElement {
  return (
    <div className="quality-toggle" role="group" aria-label="AI model">
      <span className="quality-toggle__label">
        <ModelIcon />
        AI model
      </span>
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
  // Mirror the toast API through a ref (the same pattern useJob uses) so the
  // effect can call it without depending on the unstable ToastApi identity —
  // useToast() returns a NEW object on every toast push/dismiss app-wide, and a
  // [toast, …] dep would re-run this effect (and re-fire client.batch.list) on
  // each one. With the ref, the effect keeps its once-on-mount contract above.
  const toastRef = React.useRef(toast);
  toastRef.current = toast;

  useEffect(() => {
    if (!hasApi()) return;
    let cancelled = false;
    void client.batch
      .list()
      .then(({ batches }) => {
        if (cancelled) return;
        const incomplete = incompleteBatches(batches);
        setBadge(incomplete.length);
        if (incomplete.length > 0) {
          const first = incomplete[0];
          const left = remainingCount(first.counts);
          toastRef.current.info(
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
  }, [onResume]);

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
  // WU-2c: the collapsed "Jobs" pill's live heartbeat — a slow job.list poll so
  // the header shows an in-flight count + a pulse even while the panel is shut.
  const jobCount = useActiveJobs();
  const jobsActive = jobCount > 0;

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
          setRoute({ name: 'refine', mode: 'editor' });
        }
      } catch {
        // Best-effort restore; stay on the Library default on any failure.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // Opening a video from the Library routes into Refine (the editor) for it.
  const openVideo = useCallback((video: Video) => {
    setEditVideo(video);
    setRoute({ name: 'refine', mode: 'editor' });
    // WU-13: persist the last-opened video so launch can restore it. Best-effort.
    if (!hasApi()) return;
    void rpc('settings.set', { lastOpenedVideoId: video.id }).catch(() => {
      // Persisting is best-effort; navigation already happened in-memory.
    });
  }, []);

  const backToLibrary = useCallback(() => {
    setRoute({ name: 'library' });
  }, []);

  // The Make Shorts nav — now Produce's candidate-driven mode (optionally
  // deep-linking a batch resume from the toast).
  const openMakeShorts = useCallback((resumeId?: string) => {
    setRoute({ name: 'produce', mode: 'shorts', resumeId });
  }, []);

  // WU-3a4: the Workspace's short-maker deep-link is a single-owner route — it
  // goes to Produce → Make Shorts (the ONE ShortMaker owner) with the open video
  // pre-selected, instead of mounting a second ShortMaker copy inside the editor.
  const openMakeShortsForVideo = useCallback((videoId: string) => {
    setRoute({ name: 'produce', mode: 'shorts', videoId });
  }, []);

  // v1.5 §4 P0: "edit in Studio" for a produced short (fired from the Library's
  // per-video gallery modal) reuses the SAME single-owner ShortMaker deep-link —
  // it reopens the Make Shorts section with the short's source video pre-selected.
  const editShort = useCallback(
    (short: ShortInfo) => openMakeShortsForVideo(short.videoId),
    [openMakeShortsForVideo],
  );

  // WU-3a1: the Task Hub's "Director" job card routes to Produce → Director (the
  // open video is already threaded from shell state).
  const openDirector = useCallback(() => {
    setRoute({ name: 'produce', mode: 'director' });
  }, []);

  // v1.5 §4: finishing a Phase-5 Export links INTO the cross-video publish half,
  // which is now Deliver's "Publish" mode rather than a separate destination.
  const openDeliver = useCallback(() => {
    setRoute({ name: 'deliver', mode: 'publish' });
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

  // The rail switches destinations, each landing on its FIRST mode. Re-entering
  // Refine shows the currently-open video (or its empty state when none is open).
  const selectTab = useCallback(
    (id: string) => {
      switch (id as TabId) {
        case 'produce':
          openMakeShorts();
          break;
        case 'refine':
          setRoute({ name: 'refine', mode: 'editor' });
          break;
        case 'deliver':
          setRoute({ name: 'deliver', mode: 'finish' });
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

  // Switching MODE inside a destination. Each destination owns its own mode ids,
  // so one handler per destination keeps the union type discriminated.
  const selectProduceMode = useCallback((mode: string) => {
    setRoute({ name: 'produce', mode: mode as ProduceMode });
  }, []);
  const selectRefineMode = useCallback((mode: string) => {
    setRoute({ name: 'refine', mode: mode as RefineMode });
  }, []);
  const selectDeliverMode = useCallback((mode: string) => {
    setRoute({ name: 'deliver', mode: mode as DeliverMode });
  }, []);

  // The interrupted-batch badge now rides the Make Shorts tab (batch lives in
  // that section); a resume deep-links into Make Shorts → Batch.
  const batchBadge = useRepurposeBadge(openMakeShorts);

  // L5 G-7 INVARIANT 3: exactly five. App.test.tsx pins the count and the ids.
  const tabs: TopTab[] = useMemo(
    () => [
      { id: 'library', label: 'Library', icon: <LibraryIcon /> },
      { id: 'produce', label: 'Produce', icon: <CreateIcon />, badge: batchBadge },
      { id: 'refine', label: 'Refine', icon: <RepurposeIcon /> },
      { id: 'deliver', label: 'Deliver', icon: <DeliverIcon /> },
      { id: 'settings', label: 'Settings', icon: <SettingsIcon /> },
    ],
    [batchBadge],
  );

  const activeTab = routeTab(route);

  /**
   * The mode sub-navigation for the current destination, or null for the two
   * that have exactly one surface (Library, Settings — Settings does its own
   * sub-navigation inside views/Settings.tsx).
   */
  function modeNav(): { tabs: TabDef[]; active: string; onSelect: (id: string) => void } | null {
    // Every mode list goes through `namespaced`, so no destination can reintroduce
    // the id collision by having its own mode named like one of its view's tabs.
    const namespaced = (
      modes: TabDef[],
      active: string,
      onSelect: (mode: string) => void,
    ): { tabs: TabDef[]; active: string; onSelect: (id: string) => void } => ({
      tabs: modes.map((mode) => ({ ...mode, id: modeTabId(mode.id) })),
      active: modeTabId(active),
      onSelect: (id: string) => onSelect(modeOfTabId(id)),
    });
    if (route.name === 'produce') {
      return namespaced(PRODUCE_MODES, route.mode, selectProduceMode);
    }
    if (route.name === 'refine') {
      return namespaced(REFINE_MODES, route.mode, selectRefineMode);
    }
    if (route.name === 'deliver') {
      return namespaced(DELIVER_MODES, route.mode, selectDeliverMode);
    }
    return null;
  }

  function renderRoute(): React.ReactElement {
    switch (route.name) {
      case 'produce':
        if (route.mode === 'director') {
          return (
            <Suspense fallback={<div className="panel panel--loading">Loading…</div>}>
              {/* L5 G-6 CARRIED RISK, honoured: Director is the app's one
                  consciously low-density, editorial-spacious screen (serif
                  display voice, illustrated empty state, left-anchored content
                  column) and folding it into Produce must NOT flatten it into a
                  generic form. It is therefore mounted UNCHANGED — Produce adds a
                  two-entry mode switch above it and nothing else. Do not wrap it
                  in a card, a grid cell, or a shared Produce chrome. */}
              <Director video={editVideo} onChooseVideo={backToLibrary} />
            </Suspense>
          );
        }
        return <MakeShorts resumeId={route.resumeId} videoId={route.videoId} />;
      case 'refine':
        if (route.mode === 'caption') {
          // v1.5 Caption pilot: the inspector-over-shared-stage phase for the open
          // video (empty-states + routes back to the Library when none is open).
          return <Caption video={editVideo} onBack={backToLibrary} />;
        }
        // WU-3a1: the Task Hub's section cards route to the Produce surfaces;
        // workspace-scoped cards stay inside the editor.
        return (
          <Edit
            video={editVideo}
            onBack={backToLibrary}
            onMakeShorts={openMakeShorts}
            onMakeShortsForVideo={openMakeShortsForVideo}
            onDirector={openDirector}
          />
        );
      case 'deliver':
        if (route.mode === 'publish') {
          // batch / cross-video publish + platform presets + pro handoff (the open
          // video drives the EDL/CSV handoff).
          return <Deliver video={editVideo} onBack={backToLibrary} />;
        }
        // v1.5 Phase-5: the guarded-commit render/finish for the open video;
        // finishing links INTO the Publish mode (the Export/Deliver split, §4).
        return <Export video={editVideo} onBack={backToLibrary} onDeliver={openDeliver} />;
      case 'settings':
        return <Settings initialSection={route.section} />;
      case 'library':
      default:
        // WU-14: a readiness fix action routes to Settings → Models & System.
        // WU-1f: the L5 provenance handlers drive each card's source-file row
        // (path + on-disk/missing badge + reveal/relink) and the lazy hash back-fill.
        // v1.5 §4 P0: the produced-shorts port (client.shorts + openInFolder bridge)
        // powers each card's "N shorts" gallery; onEditShort reopens the short in
        // the Make Shorts studio.
        return (
          <Library
            onOpen={openVideo}
            onReadinessAction={handleReadinessAction}
            provenance={lineageActions}
            shorts={libraryShortsClient}
            onEditShort={editShort}
          />
        );
    }
  }

  /**
   * The destination body: the surface, plus a mode sub-navigation when the
   * destination hosts more than one (Produce / Refine / Deliver).
   *
   * The wrapper's layout is set INLINE, deliberately. `components/shell.css`
   * gives `.app__main > *` `flex: 1`, so two direct children would each claim
   * half the height and the sub-nav would balloon; the surface must therefore sit
   * inside ONE flex column child. That sheet is owned by another lane, so writing
   * the rule there is out of this lane's file scope — the inline style is the
   * scoped alternative, not a shortcut. Follow-up: move `.app__destination` /
   * `.app__mode-panel` into shell.css when that file is next open.
   *
   * The mode panel is a GRID with one `1fr` row, not a flex column, and that is
   * load-bearing rather than a taste call. The nesting moved every mode-hosted view
   * off `.app__main > * { flex: 1; min-height: 0 }` (shell.css:376) and made it an
   * ordinary flex item — `flex: 0 1 auto`, i.e. CONTENT height. `views/director.css:9`
   * declares neither a height nor a flex-grow, so Director silently stopped filling
   * its destination: exactly the low-density editorial screen G-6 tells us not to
   * flatten. A single `1fr` row stretches the one child back to the full height
   * without adding a third wrapper div. (`.workspace` is unaffected either way —
   * shell.css:562 gives it `height: 100%`, which resolves against either.)
   *
   * The inner `role="tabpanel"` is required, not decorative: TabBar puts
   * `aria-controls={tabPanelId(active)}` on the selected tab, and without a
   * matching id that is a dangling IDREF — the CRITICAL axe `aria-valid-attr-value`
   * violation TabBar's own comment records from the Make Shorts screen.
   */
  function renderDestination(): React.ReactElement {
    const modes = modeNav();
    if (modes === null) return renderRoute();
    return (
      <div
        className="app__destination"
        style={{ display: 'flex', flexDirection: 'column', minHeight: 0 }}
      >
        <TabBar tabs={modes.tabs} active={modes.active} onSelect={modes.onSelect} />
        <div
          className="app__mode-panel"
          role="tabpanel"
          id={tabPanelId(modes.active)}
          aria-labelledby={tabId(modes.active)}
          style={{ display: 'grid', gridTemplateRows: '1fr', flex: 1, minHeight: 0 }}
        >
          {renderRoute()}
        </div>
      </div>
    );
  }

  return (
    // F32: the Director's session (goal / plan / review decisions) lives here,
    // OUTSIDE renderRoute()'s switch, so a tab click no longer destroys an
    // unapplied plan along with the subtree. It must stay outside the switch —
    // mounted inside it, it would be unmounted by the very navigation it guards.
    <DirectorSessionProvider>
      <div className="app">
        <header className="app__bar">
          <span className="app__brand">Reframe</span>
          {/* WU-D5: the two local-vs-cloud controls are DISTINCT scopes (AI model
              quality vs job routing) that used to sit adjacent with no boundary,
              reading as ~4 near-identical amber chips. They now live in one cluster
              split by an explicit vertical SEAM, each carrying its own scope label,
              sharing the Local/Cloud axis vocabulary. */}
          <div className="app__routing-cluster">
            <QualityToggle quality={quality} onChange={changeQuality} />
            <span className="app__routing-seam" aria-hidden="true" />
            <RoutingToggle value={routingGlobal} onChange={changeRouting} busy={routingBusy} />
          </div>
          <button
            type="button"
            className={`app__jobs-toggle${jobsActive ? ' app__jobs-toggle--active' : ''}`}
            aria-expanded={jobsOpen}
            aria-controls={JOBQUEUE_PANEL_ID}
            onClick={() => setJobsOpen((open) => !open)}
          >
            {/* The dot pulses amber only while work is in motion (CSS-gated on
                the --active modifier); it sits idle-hidden otherwise. */}
            <span className="app__jobs-dot" aria-hidden="true" />
            <span className="app__jobs-label">Jobs</span>
            {jobsActive ? (
              <span className="app__jobs-count" aria-label={`${jobCount} running`}>
                {jobCount}
              </span>
            ) : null}
          </button>
        </header>

        <TopTabBar tabs={tabs} active={activeTab} onSelect={selectTab} />

        <main
          className="app__main"
          role="tabpanel"
          id={topTabPanelId(activeTab)}
          aria-labelledby={topTabId(activeTab)}
        >
          {renderDestination()}
        </main>
      </div>
      <JobQueue open={jobsOpen} onClose={() => setJobsOpen(false)} />
      <SidecarBanner />
      <SecureKeysBanner />
      <UpdateBanner />
      <ToastHost />
    </DirectorSessionProvider>
  );
}

/**
 * WU-1b: the first-run provisioning GATE. While the sidecar is being provisioned
 * (the ~3-min env/model build on a first launch) we render the full-screen
 * FirstRunSetup INSTEAD of the shell, so the Library — and its mount-time RPCs
 * (library.list, the readiness roll-up) — never mount against a dead sidecar and
 * the "sidecar is not running" banner can't fire. When provisioning finishes
 * (the sidecar reaches 'running', the signal drops, no error) `visible` becomes
 * false and the normal shell mounts. A post-provisioning sidecar CRASH is NOT a
 * bootstrap error, so it surfaces via the in-shell SidecarBanner instead.
 */
function AppGate(): React.ReactElement | null {
  const setup = useFirstRunSetup();
  if (setup.visible) {
    return <FirstRunSetup view={setup} />;
  }
  // Withhold the shell until the initial provisioning query resolves: mounting it
  // now would fire the Library's RPCs on the very first frame of a first run,
  // before the sidecar exists — the exact "sidecar is not running" banner we kill.
  if (!setup.ready) {
    return null;
  }
  return <AppShell />;
}

/** Root: provides the toast context, then renders the first-run gate. */
export function App(): React.ReactElement {
  return (
    <ToastProvider>
      <AppGate />
    </ToastProvider>
  );
}

export default App;
