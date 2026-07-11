import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { rpc, type Video } from '../components/api';
import { CapabilitiesChip } from './CapabilitiesChip';
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
// WIRING-U2.md). When the prop is absent, a small local fallback strip renders
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
   * WU-14: fired when the library's readiness roll-up action button is clicked
   * (e.g. download a model / add a provider key). The parent owns the routing
   * to the providers/assets flows; absent -> the roll-up still renders, the
   * action is simply a no-op.
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
// landed yet. Exact preload lines: WIRING-U2.md.

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
  onReadinessAction,
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
      // Optimistic removal; restore on failure.
      const snapshot = videos;
      setVideos((prev) => prev.filter((v) => v.id !== id));
      unselect(id);
      try {
        await rpc<{ ok: boolean }>('library.remove', { id });
      } catch (err) {
        setError(errText(err));
        setVideos(snapshot);
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
    for (const id of ids) {
      try {
        await rpc<{ ok: boolean }>('library.remove', { id });
        setVideos((prev) => prev.filter((v) => v.id !== id));
      } catch {
        failed.push(id);
      }
    }
    if (failed.length > 0) {
      setError(`Could not remove ${failed.length} video${failed.length === 1 ? '' : 's'}.`);
    }
  }, [selected]);

  // ---- Produced-shorts gallery (P0 one-to-many) -----------------------------

  const shortsCountFor = useCallback(
    (id: string): number => (shorts ? (shortsByVideo[id]?.length ?? 0) : 0),
    [shorts, shortsByVideo],
  );

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
    [emitToast],
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

      {/* design-review P2/§4: the model-readiness roll-up demoted to a compact
          "Capabilities: N of M installed" disclosure chip (a plumbing count, kept
          separate from the visible card count). */}
      <CapabilitiesChip onAction={onReadinessAction} />

      <LibraryToolbar
        query={query}
        onQueryChange={setQuery}
        sort={sortMode}
        onSortChange={setSortMode}
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
        <div className="library__empty">
          <div className="library__empty-poster" aria-hidden="true">
            <span className="library__empty-glyph">▶</span>
            <span className="library__empty-timecode">--:--</span>
          </div>
          <p className="library__empty-title">No videos yet</p>
          <p className="library__empty-hint">
            Click “Add videos” or drop video files anywhere here.
          </p>
        </div>
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
    </div>
  );
}

export default Library;
