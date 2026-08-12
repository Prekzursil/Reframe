import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { rpc, type Video } from '../components/api';
import { useConfirm } from '../components/ConfirmDialog';
import { LibraryCard } from './LibraryCard';
import { LibraryToolbar } from './LibraryToolbar';
import { ShortsGalleryModal } from './ShortsGalleryModal';
import { LineagePanel, type LineageAsset } from '../features/LineagePanel';
import type { ProvenanceHandlers } from '../features/LibraryProvenance';
import { lineageActions } from '../features/lineageActionsClient';
import type { LineageResult, ReadinessAction, ShortInfo } from '../lib/rpc';
import {
  type LibrarySort,
  type LibraryVideo,
  filterVideos,
  groupShortsByVideo,
  sortVideos,
} from './libraryModel';
import '../components/library-cards.css';

// ---- Toasts (P2 U2) ---------------------------------------------------------
// Per-file import failures surface as TYPED toasts. U3 owns the app-wide toast
// system (components/toast/*); to stay lane-independent, Library accepts an
// OPTIONAL `toast` prop the wiring agent connects to U3's useToast (see
// docs/wiring/WIRING-U2.md). When the prop is absent, a small local fallback strip renders
// the toasts inline so no failure is ever silent.

export type ToastKind = 'error' | 'success' | 'info';

export interface ToastMessage {
  kind: ToastKind;
  message: string;
}

interface LocalToast extends ToastMessage {
  id: number;
}

/** How long a fallback toast stays on screen. */
const TOAST_TTL_MS = 6000;

/**
 * The injected produced-shorts port (v1.5 §4 P0). When provided, Library loads
 * ALL produced shorts once, groups them by source video for the per-card "N
 * shorts" count, and the gallery modal reveals/deletes clips through it. Absent
 * -> the shorts affordances simply don't render (lane-independent, like the
 * `provenance`/`toast` seams; the App-side adapter is a documented follow-up).
 */
export interface LibraryShortsApi {
  /** Load EVERY produced short (grouped client-side by source `videoId`). */
  listAll: () => Promise<ShortInfo[]>;
  /** Reveal a produced clip in the OS file explorer. */
  openFolder: (path: string) => Promise<void>;
  /** Delete a produced clip file (the adapter owns any confirm). */
  remove: (path: string) => Promise<void>;
}

export interface LibraryProps {
  /** Called when the user opens a video into the Workspace. */
  onOpen: (video: Video) => void;
  /**
   * Optional external toast sink (the U3 useToast adapter, injected by the
   * wiring agent). When provided, ALL toasts route here and the local
   * fallback strip is not rendered.
   */
  toast?: (toast: ToastMessage) => void;
  /**
   * INERT (Q3). This used to feed the Library's readiness roll-up / capabilities
   * chip, which is DELETED: nothing in this view raises a readiness action any
   * more, so this prop is deliberately NOT destructured below and no handler is
   * wired to it.
   *
   * It stays DECLARED for exactly one reason: `App.tsx:543` still passes
   * `onReadinessAction={handleReadinessAction}`, and removing the prop from this
   * interface would make that call site a TS2322 excess-property error and break
   * `npm run typecheck`. Retiring the prop and its `App.tsx:429-434` handler is
   * owned by the rail/flow (`App.tsx`) lane — delete this declaration in the same
   * commit that removes the call site, not before.
   *
   * WARNING for that lane, because the obvious signal LIES: `App.tsx:429-434`
   * still reports 100% covered, and that coverage is PHANTOM. `App.quality.test.tsx`
   * replaces this view with a `vi.mock('./views/Library')` stub whose
   * `readiness-fix` / `readiness-fix-key` buttons synthesize `assets.ensure` /
   * `openProviders` actions that the REAL Library can no longer emit, and the
   * "App readiness deep-link → Settings" tests drive those buttons. So the handler
   * is unreachable from the product while the coverage gate stays green, and those
   * two tests now assert a Library→Settings journey that does not exist. They must
   * be deleted in the SAME commit as the handler and this declaration; do not read
   * the coverage number as evidence the handler is still live.
   */
  onReadinessAction?: (action: ReadinessAction) => void;
  /**
   * WU-1f: the injected L5 provenance handlers (`library.reveal`/`pinHash`/
   * `relink` + the reveal/pick bridges). When provided, each card renders its
   * source-file provenance row (clear path + on-disk/missing badge + reveal/relink
   * actions, and the lazy pin-on-view hash back-fill); absent -> cards keep the
   * legacy compact path line and no provenance row (the app wires the real one).
   */
  provenance?: ProvenanceHandlers;
  /**
   * v1.5 §4 P0: the produced-shorts port. When provided, each card shows a
   * "N shorts" label opening the gallery modal for that video.
   */
  shorts?: LibraryShortsApi;
  /** v1.5 §4: "edit in Studio" for a produced short (from the gallery modal). */
  onEditShort?: (short: ShortInfo) => void;
}

interface ListResult {
  videos: Video[];
}

interface AddResult {
  video: Video;
}

// ---- Preload bridge (P2 U2 additions) ---------------------------------------
// `openVideos` / `pathForFile` are P2 additions to window.api that are not on
// the frozen MediaApi type in components/api.ts (a shared file). Library views
// the bridge structurally and degrades gracefully when the wiring has not
// landed yet. Exact preload lines: docs/wiring/WIRING-U2.md.

interface PickerBridge {
  openVideos?: () => Promise<string[]>;
  pathForFile?: (file: File) => string;
}

function pickerBridge(): PickerBridge | null {
  const api = (globalThis as { window?: { api?: unknown } }).window?.api;
  return api && typeof api === 'object' ? (api as PickerBridge) : null;
}

/**
 * Resolve a dropped File to its absolute filesystem path.
 *
 * Electron >=32 removed the Chromium `File.path` extension — the preload must
 * expose `webUtils.getPathForFile` as `window.api.pathForFile` (WIRING-U2.md).
 * We prefer that bridge and fall back to the legacy `.path` property for older
 * runtimes; `null` when no path is recoverable (browser-style File).
 */
function resolveDroppedPath(file: File): string | null {
  const bridge = pickerBridge();
  if (bridge && typeof bridge.pathForFile === 'function') {
    try {
      const p = bridge.pathForFile(file);
      if (typeof p === 'string' && p !== '') return p;
    } catch {
      // fall through to the legacy property
    }
  }
  const legacy = (file as File & { path?: unknown }).path;
  return typeof legacy === 'string' && legacy !== '' ? legacy : null;
}

/** Last path component, for compact per-file toast messages. */
function baseName(p: string): string {
  const parts = p.split(/[\\/]/);
  return parts[parts.length - 1] || p;
}

function errText(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

/**
 * `library.lineage({id})` loader over the shared `rpc` bridge — the injected
 * `loadLineage` the L4 `LineagePanel` drawer consumes. Module-level so it is
 * stable across renders (the drawer's fetch effect must not re-fire each render).
 */
function loadLineage(id: string): Promise<LineageResult> {
  return rpc<LineageResult>('library.lineage', { id });
}

/**
 * Library.tsx — the content-first video-manager home (v1.5 §4 re-skin).
 * Lists videos (library.list) in a poster grid, adds via the NATIVE picker or
 * drag-drop (multi-add, per-file typed error toasts, de-dupe by id), removes
 * (single + batch), searches/sorts in-context, opens a video into the Workspace,
 * and — via the injected shorts port — opens each video's produced-shorts gallery.
 */
export function Library({
  onOpen,
  toast: externalToast,
  // `onReadinessAction` is intentionally NOT destructured — see LibraryProps.
  provenance,
  shorts,
  onEditShort,
}: LibraryProps): React.ReactElement {
  const [videos, setVideos] = useState<LibraryVideo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  // L4 Lineage view: an opt-in toggle (default OFF -> the flat grid opens videos
  // in the Workspace, §3.5). When ON, clicking an asset opens its provenance
  // drawer (lineageAsset) instead. Leaving the mode closes any open drawer.
  const [lineageView, setLineageView] = useState(false);
  const [lineageAsset, setLineageAsset] = useState<LineageAsset | null>(null);
  const [toasts, setToasts] = useState<LocalToast[]>([]);
  const toastIdRef = React.useRef(0);
  const toastTimersRef = React.useRef<ReturnType<typeof setTimeout>[]>([]);

  // v1.5 scale + one-to-many state.
  const [query, setQuery] = useState('');
  const [sortMode, setSortMode] = useState<LibrarySort>('recent');
  const [selected, setSelected] = useState<Set<string>>(() => new Set());
  const [shortsByVideo, setShortsByVideo] = useState<Record<string, ShortInfo[]>>({});
  const [shortsVideo, setShortsVideo] = useState<LibraryVideo | null>(null);

  // Clear any pending fallback-toast expiry timers on unmount.
  useEffect(() => {
    const timers = toastTimersRef.current;
    return () => {
      for (const t of timers) clearTimeout(t);
    };
  }, []);

  const dismissToast = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const emitToast = useCallback(
    (kind: ToastKind, message: string) => {
      if (externalToast) {
        externalToast({ kind, message });
        return;
      }
      const id = ++toastIdRef.current;
      setToasts((prev) => [...prev, { id, kind, message }]);
      toastTimersRef.current.push(
        setTimeout(() => {
          setToasts((prev) => prev.filter((t) => t.id !== id));
        }, TOAST_TTL_MS),
      );
    },
    [externalToast],
  );

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await rpc<ListResult>('library.list');
      setVideos(result?.videos ?? []);
    } catch (err) {
      setError(errText(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // Load the produced-shorts index once (best-effort) when the port is wired, so
  // each card can show its "N shorts" count and open the gallery.
  const loadShorts = useCallback(async (api: LibraryShortsApi) => {
    try {
      setShortsByVideo(groupShortsByVideo(await api.listAll()));
    } catch {
      setShortsByVideo({});
    }
  }, []);

  useEffect(() => {
    if (shorts) void loadShorts(shorts);
  }, [shorts, loadShorts]);

  /**
   * Multi-add: one library.add per path, sequential so list order is stable.
   * Per-file failures become typed error toasts; the batch continues.
   * Successful inserts de-dupe by id (a re-add floats to the top).
   */
  const addPaths = useCallback(
    async (paths: string[]) => {
      if (paths.length === 0) return;
      setAdding(true);
      setError(null);
      let addedCount = 0;
      for (const p of paths) {
        try {
          const result = await rpc<AddResult>('library.add', { path: p });
          const added = result?.video;
          if (added) {
            setVideos((prev) => [added, ...prev.filter((v) => v.id !== added.id)]);
            addedCount += 1;
          } else {
            emitToast('error', `${baseName(p)}: library.add returned no video`);
          }
        } catch (err) {
          emitToast('error', `${baseName(p)}: ${errText(err)}`);
        }
      }
      if (addedCount > 0) {
        emitToast('success', addedCount === 1 ? 'Added 1 video' : `Added ${addedCount} videos`);
      }
      setAdding(false);
    },
    [emitToast],
  );

  /** "Add videos" button -> native multi-select picker via the preload bridge. */
  const handlePick = useCallback(async () => {
    // Defensive re-entrancy guard. The Add button is bound `disabled={adding}`,
    // so its onClick can never fire while `adding` is true (React does not
    // dispatch onClick for a control it rendered disabled) — the guard is
    // therefore unreachable via the UI but kept as defence-in-depth.
    /* v8 ignore next */
    if (adding) return;
    const bridge = pickerBridge();
    if (!bridge || typeof bridge.openVideos !== 'function') {
      emitToast('error', 'Native file picker unavailable (preload openVideos bridge not wired)');
      return;
    }
    try {
      const paths = await bridge.openVideos();
      await addPaths(Array.isArray(paths) ? paths : []);
    } catch (err) {
      emitToast('error', errText(err));
    }
  }, [adding, addPaths, emitToast]);

  // ---- Drag-drop onto the library -------------------------------------------

  const handleDragOver = useCallback((event: React.DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = 'copy';
    setDragOver(true);
  }, []);

  const handleDragLeave = useCallback(() => {
    setDragOver(false);
  }, []);

  const handleDrop = useCallback(
    (event: React.DragEvent<HTMLDivElement>) => {
      event.preventDefault();
      setDragOver(false);
      const files = Array.from(event.dataTransfer?.files ?? []);
      if (files.length === 0) return;
      const paths: string[] = [];
      for (const file of files) {
        const p = resolveDroppedPath(file);
        if (p) {
          paths.push(p);
        } else {
          emitToast('error', `${file.name}: dropped file has no filesystem path`);
        }
      }
      void addPaths(paths);
    },
    [addPaths, emitToast],
  );

  const toggleLineageView = useCallback(() => {
    setLineageView((on) => !on);
    setLineageAsset(null);
  }, []);

  const closeLineage = useCallback(() => {
    setLineageAsset(null);
  }, []);

  /** Click an asset: open its lineage drawer in Lineage view, else the Workspace. */
  const handleItemClick = useCallback(
    (video: LibraryVideo) => {
      if (lineageView) {
        setLineageAsset({ id: video.id, title: video.title });
      } else {
        onOpen(video);
      }
    },
    [lineageView, onOpen],
  );

  /** Prune an id from the selection (kept in sync when a video leaves the list). */
  const unselect = useCallback((id: string) => {
    setSelected((prev) => {
      if (!prev.has(id)) return prev;
      const next = new Set(prev);
      next.delete(id);
      return next;
    });
  }, []);

  const handleRemove = useCallback(
    async (id: string, event: React.MouseEvent) => {
      event.stopPropagation();
      setError(null);
      // Optimistic removal; on failure restore ONLY this video, at its original
      // index, through a FUNCTIONAL update.
      //
      // A whole-list snapshot (`const snapshot = videos` + `setVideos(snapshot)`)
      // clobbered every state change that landed while this RPC was in flight: it
      // resurrected a video whose OWN remove had succeeded — a phantom card whose
      // manifest and poster the sidecar had already unlinked (library_ops.py:160-161)
      // and which opens into failing path-resolving RPCs — and it erased a
      // just-dropped import that WAS in the library DB.
      //
      // Deliberately BRANCH-FREE, for the same 100%-branch-coverage reason spelled
      // out in removeSelected below: with `at === -1` (the id already gone),
      // `slice(-1, 0)` is `[]` and the reassembly `slice(0, -1) + [] + slice(-1)`
      // reconstitutes the list exactly, so the unreachable not-found case needs no
      // conditional and mints no uncovered branch.
      const at = videos.findIndex((v) => v.id === id);
      const removed = videos.slice(at, at + 1);
      setVideos((prev) => prev.filter((v) => v.id !== id));
      unselect(id);
      try {
        await rpc<{ ok: boolean }>('library.remove', { id });
      } catch (err) {
        setError(errText(err));
        setVideos((prev) => {
          // Re-filter first so a double-fire cannot duplicate the restored card.
          const without = prev.filter((v) => v.id !== id);
          return [...without.slice(0, at), ...removed, ...without.slice(at)];
        });
      }
    },
    [videos, unselect],
  );

  const toggleSelect = useCallback((id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const clearSelection = useCallback(() => setSelected(new Set()), []);

  /** Batch remove: one library.remove per selected id; failures are counted. */
  const removeSelected = useCallback(async () => {
    const ids = [...selected];
    setSelected(new Set());
    setError(null);
    const failed: string[] = [];
    // Surface a REASON, not just a count. `library.remove` now refuses LOUD when a video's
    // app-managed copy is the only surviving copy of it (keep-a-copy opted in and the
    // original source gone), and that refusal names the file — an actionable message. A
    // bare `catch {}` threw it away and left the user with an unexplained count.
    //
    // Deliberately BRANCH-FREE: it keeps the most recent reason rather than the first, so
    // there is no "did we get a reason?" conditional. `failed.length > 0` already implies a
    // catch ran and therefore that `reason` was assigned, so such a conditional would have
    // an unreachable arm — which is exactly what broke the 100% branch-coverage gate. For a
    // bulk remove the reasons are near-always identical (the same guard fires per video),
    // so first-vs-last is immaterial.
    let reason = '';
    for (const id of ids) {
      try {
        await rpc<{ ok: boolean }>('library.remove', { id });
        setVideos((prev) => prev.filter((v) => v.id !== id));
      } catch (err) {
        failed.push(id);
        reason = errText(err);
      }
    }
    if (failed.length > 0) {
      const count = `Could not remove ${failed.length} video${failed.length === 1 ? '' : 's'}.`;
      setError(`${count} ${reason}`.trim());
    }
  }, [selected]);

  // ---- Produced-shorts gallery (P0 one-to-many) -----------------------------

  const shortsCountFor = useCallback(
    (id: string): number => (shorts ? (shortsByVideo[id]?.length ?? 0) : 0),
    [shorts, shortsByVideo],
  );

  // W04: the themed destructive gate that replaced the native `confirm()`.
  const { confirm, confirmDialog } = useConfirm();

  const openShorts = useCallback((video: LibraryVideo) => setShortsVideo(video), []);
  const closeShorts = useCallback(() => setShortsVideo(null), []);

  const openShortFolder = useCallback(
    async (api: LibraryShortsApi, path: string) => {
      try {
        await api.openFolder(path);
      } catch (err) {
        emitToast('error', errText(err));
      }
    },
    [emitToast],
  );

  const deleteShort = useCallback(
    async (api: LibraryShortsApi, path: string) => {
      // CONFIRM before the destructive call. `shorts.delete` hard-unlinks the .mp4,
      // its .thumb.jpg and its .json (features/shorts.py:442-455) with no OS recycle
      // bin, so an unguarded click destroyed a finished render outright. The other
      // two call sites of this action already confirm (views/Shorts.tsx:147,
      // features/useShortsGallery.ts:99) and KeepCopyControl.tsx:21 states the
      // standard — "never a silent one-click destructive action". This surface was
      // the lone exception because four separate comments each delegated the confirm
      // to another layer and it landed nowhere.
      //
      // W04: the THEMED gate replaced the native `confirm()` here — native confirm
      // is unthemeable, carries no author-controlled accessible name/description,
      // and blocks the whole Electron renderer while it is open.
      const ok = await confirm({
        title: 'Delete this short?',
        blurb: `${path}\n\nThis removes the exported file.`,
        confirmLabel: 'Delete short',
        cancelLabel: 'Keep it',
      });
      if (!ok) return;
      try {
        await api.remove(path);
        setShortsByVideo((prev) => {
          const next: Record<string, ShortInfo[]> = {};
          for (const [vid, list] of Object.entries(prev)) {
            const kept = list.filter((s) => s.path !== path);
            if (kept.length > 0) next[vid] = kept;
          }
          return next;
        });
      } catch (err) {
        emitToast('error', errText(err));
      }
    },
    [confirm, emitToast],
  );

  // The visible grid: in-context search + sort, layered over the raw list.
  const visible = useMemo(
    () => sortVideos(filterVideos(videos, query), sortMode, shortsCountFor),
    [videos, query, sortMode, shortsCountFor],
  );

  return (
    <div
      className={`library${dragOver ? ' library--dragover' : ''}`}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      <header className="library__header">
        <h1 className="library__title">Library</h1>
        <div className="library__actions">
          <button
            type="button"
            className="library__lineage-toggle"
            aria-pressed={lineageView}
            onClick={toggleLineageView}
          >
            Lineage view
          </button>
          <button
            type="button"
            className="library__add-btn"
            onClick={() => void handlePick()}
            disabled={adding}
          >
            {adding ? 'Adding…' : 'Add videos'}
          </button>
        </div>
      </header>

      {/* Q3: NOTHING readiness-shaped renders here any more. The
          "Capabilities: N of M installed" disclosure chip that used to sit
          between the header and the toolbar is DELETED, for two measured reasons:

            1. It was a DECOY on the app's landing surface. Stated precisely,
               because the earlier wording ("a button on the landing surface") was
               wider than the evidence: the CHIP was painted here unconditionally,
               but its action button was ONE EXPAND CLICK deep — the row list was
               gated behind the disclosure's own `open` state
               (origin/main:views/CapabilitiesChip.tsx:37,82,98, `{open && items &&
               total > 0 ? <ul>`), so the button was reachable-in-one-click, not
               on screen at rest. Once revealed, for an `assets.ensure` row that
               button's accessible name was "Download the <X> model"
               (components/readinessMeta.ts:113), but the chip only forwarded the
               action to its parent, and the Library's parent handler is
               `App.tsx:429-434` — `openSettings(actionSection(action))`, pure
               navigation. No download ever started. Contrast Settings, which
               renders the SAME shared parts — `<ReadinessBadge>` and the
               `readinessActionLabel` builder — inside its own `<ReadinessRollup>`
               (the chip itself was bespoke, so what is shared is the button, not
               the container): there the very same `assets.ensure` action reaches
               `runAssetJob(action.assets)` and really downloads
               (panels/ModelsSystemPanel.tsx:746-765). Identical button, identical
               label, one works and one did not.

               The destination did not even land the user near the row: Settings
               force-resets its scroll container to the top on every section change
               (`panelRef.current!.scrollTop = 0`, views/Settings.tsx:273-275) and
               nothing scrolls to or highlights the relevant row — there is no
               `scrollIntoView` CALL SITE anywhere under renderer/src (the only
               textual hits are this comment, its test, and Settings.tsx:264 saying
               the same thing). Measured: the panel it lands in,
               ModelsSystemPanel.tsx, is 1136 lines. Announced as a download, it
               downloaded nothing.
            2. Its counter was not user-meaningful. The denominator was an internal
               capability enumeration (already moved 11 -> 12; the owner reports
               seeing 13), so it was DELETED rather than relocated — moving a
               meaningless denominator to a new home preserves the defect.

          Readiness now lives in ONE place, Settings -> Models & System, where the
          fix actions are in reach of the controls that perform them. If an
          in-Library readiness signal is ever wanted back, the bar is: a
          CONDITIONAL single-line banner whose button runs the shared asset-download
          path (ModelsSystemPanel.tsx:682-714) IN PLACE — never a navigation decoy,
          and never an always-on chip.

          SCOPE: the decoy verdict covers `assets.ensure` rows only. `openProviders`
          and `setConsent` rows SHOULD navigate, and they still do — from Settings.
          Nothing here removes navigation from those. Pinned by Library.test.tsx
          "Library readiness surface (Q3 — chip deleted, not relocated)".

          THIS ROUTE'S PIXEL BASELINE IS NOW STALE — known-red, not merely
          unchecked. `e2e/visual/library.visual.spec.ts:31` diffs a full-page
          screenshot of this route against the committed
          `library.visual.spec.ts-snapshots/library-win32.png` (63,097 B,
          1280x820), and that PNG still shows the pill "Capabilities: 6 of 11
          installed" between the title and the search/SORT row. `.library` is a
          column flex with no `gap` (components/shell.css), so deleting the pill
          shifts the toolbar and the whole card grid UP by that row's height (the
          exact px delta is not measured here — only its sign and that it is
          nonzero). Any nonzero shift busts the budget: the tolerance is
          `maxDiffPixelRatio: 0.01` (e2e/visual/_visualSetup.ts:111) = 10,496 of
          1,049,600 px, while the colour-bar thumbnail that moves is ~230x140 in
          that baseline ≈ 32k high-frequency px on its own. `npm run test:e2e:visual`
          (.github/workflows/e2e.yml:485-490, Windows, no continue-on-error) will
          therefore fail until the baseline is regenerated. It does NOT gate this
          PR: e2e.yml is workflow_dispatch + nightly cron only (:38-51; :3 "This
          NEVER gates a normal PR"). The PNG is outside this lane's file scope, so
          this is a routed SCOPE-ESCAPE, not a gap closed here — dispatch e2e.yml
          with `update_visual_baselines: true`, then download the
          `updated-visual-baselines` artifact and commit the PNG (the regen step
          uploads, it does not commit: e2e.yml:492-516,743-745). Whether the
          header-to-toolbar rhythm now READS right with the row gone is a separate
          question and is still genuinely unmeasured.

          ALSO ROUTED (CSS lane, out of scope here): the chip's stylesheet block
          outlived the chip — nine dead `.capabilities-chip*` rules at
          components/library-shell.css:9,16,39,44,49,54,60,73,80 with zero
          consumers, plus that file's header at :2 still advertising "the
          capabilities disclosure chip". Delete the BLOCK, not the file:
          views/LibraryToolbar.tsx:9 and views/ShortsGalleryModal.tsx:25 still
          import it. */}

      {/* W54: `videos.length` — the RAW count — gates the search + sort controls,
          which used to mount unconditionally as a sibling of the
          `videos.length === 0` arm below and so offered a live, enabled search box
          over a first-run library of zero rows. NOT `visible.length`: gating on the
          filtered count would remove the search box the moment a query matched
          nothing and trap the user in the "No matches" arm with no way to clear it
          (pinned by Library.test.tsx "keeps search reachable when a query matches
          nothing").

          `loading` rides along because the count alone is ambiguous: it is also 0
          while the first `library.list` is in flight, and hiding the strip there
          made it mount when the data landed, pushing the whole list down by the
          strip's box — the opposite of what the skeleton below exists to do. This
          view remounts on every tab switch (App.tsx renderRoute()), so that was a
          shift on every return, not just a first-run one. Pinned by
          Library.test.tsx "keeps the toolbar mounted across the first listing so
          the list cannot shift". */}
      <LibraryToolbar
        query={query}
        onQueryChange={setQuery}
        sort={sortMode}
        onSortChange={setSortMode}
        videoCount={videos.length}
        loading={loading}
        selectedCount={selected.size}
        onRemoveSelected={() => void removeSelected()}
        onClearSelection={clearSelection}
      />

      {dragOver ? (
        <div className="library__drophint" aria-hidden="true">
          Drop videos to add them
        </div>
      ) : null}

      {error ? (
        <div className="library__error" role="alert">
          {error}
        </div>
      ) : null}

      {externalToast || toasts.length === 0 ? null : (
        <div className="library__toasts" aria-live="polite">
          {toasts.map((t) => (
            <div
              key={t.id}
              className={`library__toast library__toast--${t.kind}`}
              role={t.kind === 'error' ? 'alert' : 'status'}
            >
              <span className="library__toast-msg">{t.message}</span>
              <button
                type="button"
                className="library__toast-dismiss"
                aria-label="Dismiss notification"
                onClick={() => dismissToast(t.id)}
              >
                ×
              </button>
            </div>
          ))}
        </div>
      )}

      {loading ? (
        // Skeleton-shimmer placeholders shaped like the real library cards —
        // never a bare "LOADING…". aria-busy + label carry the state to AT while
        // the ghost rows (aria-hidden) hold the layout so it doesn't jump.
        <div
          className="library__loading"
          role="status"
          aria-busy="true"
          aria-label="Loading your videos"
        >
          <ul className="library__skeleton" aria-hidden="true">
            {[0, 1, 2, 3].map((i) => (
              <li key={i} className="library__skeleton-row">
                <span className="skeleton library__skeleton-thumb" />
                <span className="library__skeleton-lines">
                  <span className="skeleton library__skeleton-line library__skeleton-line--title" />
                  <span className="skeleton library__skeleton-line library__skeleton-line--path" />
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : videos.length === 0 ? (
        // A FAILED `library.list` also lands here with `videos === []`, so the
        // first-run poster used to render UNDER the error alert and tell the user
        // their library was empty when we had merely failed to read it. SUPPRESS
        // the poster then; the single `.library__error` alert above stays the one
        // error surface (restating the message would duplicate it on screen, once
        // inside a role="alert").
        //
        // The `error` test must live strictly INSIDE this arm: hoisting it above
        // `videos.length === 0` would also suppress the LIST, and a failed
        // `library.remove` legitimately renders error != null WITH videos > 0.
        error ? null : (
          <div className="library__empty">
            <div className="library__empty-poster" aria-hidden="true">
              <span className="library__empty-glyph">▶</span>
              <span className="library__empty-timecode">--:--</span>
            </div>
            <p className="library__empty-title">No videos yet</p>
            {/* W53 — this used to read "drop video files anywhere here". "anywhere"
                is wider than the app: this view's root div carries the only React
                drag-and-drop HANDLERS in the renderer (:521-523 above), so it is
                the only surface that HANDLES a dropped video, and the copy now
                names it.

                Two earlier versions of this comment were refuted and are corrected
                here rather than deleted, so the next reader inherits the scope and
                not the overclaim:
                  * "the ONLY drop target in the whole renderer" was wider than the
                    grep behind it. `onDrop=`/`onDragOver=` cannot see a NATIVE drop
                    target, and there is one: features/Subtitles.tsx:348 renders
                    <input type="file" accept=".srt,.vtt,.ass,.ssa"> (:48), which
                    Chromium treats as a drop target. It cannot take a video (that
                    `accept` filters it out), so the operative conclusion holds — but
                    "only React DnD handlers" is the claim the evidence supports.
                  * "the browser navigates away or ignores it" asserted a runtime
                    behaviour nobody ran. What IS grounded: no view outside the
                    Library registers a drop handler, so nothing in the app reacts;
                    and main.ts:1111-1117 preventDefault()s any navigation failing
                    isAllowedNavigation, which for a packaged `file:` app pins the
                    target to the app's own bundle pathname and so denies any
                    sibling `file:` document (security.ts:32-35) — a dropped
                    clip.mp4 included. UNVERIFIED: whether a drop onto a
                    handler-less view even reaches `will-navigate` in Electron, and
                    what the user actually sees; no drop was executed outside the
                    Library. Settling experiment: an e2e that drags a file onto
                    Edit/Caption/Export and asserts no `library.add` RPC, no route
                    change, and no window navigation.
                Independent corroboration of the drop scope, from the audit that
                raised W53: docs/plans/v1.5/uiux-qol-audit-2026-08.md:299 ("M6.
                Drag-and-drop works only on Library"). Pinned by Library.test.tsx.
                If an app-level drop target ever lands, widen this sentence in the
                SAME commit that ships it. */}
            <p className="library__empty-hint">
              Click “Add videos”, or drop video files onto the Library.
            </p>
          </div>
        )
      ) : visible.length === 0 ? (
        <div className="library__empty library__empty--filtered">
          <p className="library__empty-title">No matches</p>
          <p className="library__empty-hint">No videos match “{query}”.</p>
        </div>
      ) : (
        <ul className="library__list">
          {visible.map((video) => (
            <LibraryCard
              key={video.id}
              video={video}
              lineageView={lineageView}
              selected={selected.has(video.id)}
              onToggleSelect={toggleSelect}
              onOpen={handleItemClick}
              onRemove={handleRemove}
              shortsCount={shortsCountFor(video.id)}
              onOpenShorts={openShorts}
              provenance={provenance}
            />
          ))}
        </ul>
      )}

      {lineageAsset ? (
        <LineagePanel
          asset={lineageAsset}
          loadLineage={loadLineage}
          onClose={closeLineage}
          actions={lineageActions}
        />
      ) : null}

      {shorts && shortsVideo ? (
        <ShortsGalleryModal
          title={shortsVideo.title}
          shorts={shortsByVideo[shortsVideo.id] ?? []}
          onClose={closeShorts}
          onOpenFolder={(path) => void openShortFolder(shorts, path)}
          onDelete={(path) => void deleteShort(shorts, path)}
          onEdit={onEditShort}
        />
      ) : null}

      {confirmDialog}
    </div>
  );
}

export default Library;
