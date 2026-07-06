import React, { useCallback, useEffect, useRef, useState } from 'react';
import { rpc, type Video } from '../components/api';
import { useVideoThumbnail, type VideoThumbnailRpc } from '../components/useVideoThumbnail';
import { ReadinessRollup } from '../components/ReadinessRollup';
import { LineagePanel, type LineageAsset } from '../features/LineagePanel';
import { LibraryProvenance, type ProvenanceHandlers } from '../features/LibraryProvenance';
import { lineageActions } from '../features/lineageActionsClient';
import type { LineageResult, ReadinessAction } from '../lib/rpc';
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

function formatDuration(sec: number): string {
  if (!Number.isFinite(sec) || sec <= 0) return '--:--';
  const total = Math.round(sec);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const mm = String(m).padStart(2, '0');
  const ss = String(s).padStart(2, '0');
  return h > 0 ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

// ---- Poster-frame thumbnails (WU-4 wiring, WU-14) ---------------------------

/**
 * `library.thumbnail({id})` adapter over the shared `rpc` bridge — the thin RPC
 * slice `useVideoThumbnail` needs. Stable across renders so the hook's effect
 * does not re-fire every card render.
 */
const thumbnailRpc: VideoThumbnailRpc = {
  thumbnail: (videoId: string) =>
    rpc<{ thumbnailPath: string }>('library.thumbnail', { id: videoId }),
};

/**
 * `library.lineage({id})` loader over the shared `rpc` bridge — the injected
 * `loadLineage` the L4 `LineagePanel` drawer consumes. Module-level so it is
 * stable across renders (the drawer's fetch effect must not re-fire each render).
 */
function loadLineage(id: string): Promise<LineageResult> {
  return rpc<LineageResult>('library.lineage', { id });
}

/**
 * Library-card poster: consumes `useVideoThumbnail` (WU-4) to serve the source
 * video's `thumb:` poster as a real <img>, generating it on demand (idempotent
 * server-side). Inherits WU-4's graceful degradation: a missing / failed poster
 * (empty resolved URL, or an <img> load error) falls back to the ▶ glyph and
 * NEVER blocks the gallery. The duration badge always renders (mm:ss).
 */
function VideoThumb({ video }: { video: Video }): React.ReactElement {
  const posterUrl = useVideoThumbnail(thumbnailRpc, video.id, video.thumbnailPath ?? '');
  const [imgFailed, setImgFailed] = useState(false);
  const showImg = posterUrl !== '' && !imgFailed;

  return (
    <div className="library__thumb">
      {showImg ? (
        <img
          className="library__thumb-img"
          src={posterUrl}
          alt=""
          aria-hidden="true"
          onError={() => setImgFailed(true)}
        />
      ) : (
        <div className="library__thumb-fallback" aria-hidden="true">
          ▶
        </div>
      )}
      <span className="library__thumb-duration">{formatDuration(video.durationSec)}</span>
    </div>
  );
}

/**
 * Library.tsx — the video-manager home.
 * Lists videos (library.list), adds via the NATIVE picker (window.api.openVideos
 * -> dialog.openVideos ipc) or drag-drop onto the view (multi-add, per-file
 * typed error toasts, de-dupe by id), removes (library.remove), and opens a
 * video into the Workspace on click.
 */
export function Library({
  onOpen,
  toast: externalToast,
  onReadinessAction,
  provenance,
}: LibraryProps): React.ReactElement {
  const [videos, setVideos] = useState<Video[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  // L4 Lineage view: an opt-in toggle (default OFF -> the flat list opens videos
  // in the Workspace, §3.5). When ON, clicking an asset opens its provenance
  // drawer (lineageAsset) instead. Leaving the mode closes any open drawer.
  const [lineageView, setLineageView] = useState(false);
  const [lineageAsset, setLineageAsset] = useState<LineageAsset | null>(null);
  const [toasts, setToasts] = useState<LocalToast[]>([]);
  const toastIdRef = useRef(0);
  const toastTimersRef = useRef<ReturnType<typeof setTimeout>[]>([]);

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
    (video: Video) => {
      if (lineageView) {
        setLineageAsset({ id: video.id, title: video.title });
      } else {
        onOpen(video);
      }
    },
    [lineageView, onOpen],
  );

  const handleRemove = useCallback(
    async (id: string, event: React.MouseEvent) => {
      event.stopPropagation();
      setError(null);
      // Optimistic removal; restore on failure.
      const snapshot = videos;
      setVideos((prev) => prev.filter((v) => v.id !== id));
      try {
        await rpc<{ ok: boolean }>('library.remove', { id });
      } catch (err) {
        setError(errText(err));
        setVideos(snapshot);
      }
    },
    [videos],
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

      <ReadinessRollup title="What works right now" onAction={onReadinessAction} />

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
        <div className="library__loading">Loading…</div>
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
      ) : (
        <ul className="library__list">
          {videos.map((video) => (
            // A11Y: the row is a plain <li> (so the <ul> only contains list
            // items — fixes axe `list`/`only-listitems`). The OPEN affordance is
            // a real <button> wrapping the thumb + title (natively keyboard- and
            // screen-reader-operable), and Remove is its SIBLING button — not a
            // focusable nested inside another control (fixes `nested-interactive`
            // / `no-focusable-content`).
            <li key={video.id} className="library__item">
              <button
                type="button"
                className="library__item-open"
                aria-label={lineageView ? `Show history of ${video.title}` : `Open ${video.title}`}
                onClick={() => handleItemClick(video)}
              >
                <VideoThumb video={video} />
                <div className="library__item-main">
                  <span className="library__item-title">{video.title}</span>
                  {/* WU-1f: the clear source path moves into <LibraryProvenance>;
                      without the provenance handlers, keep the legacy compact line. */}
                  {provenance ? null : (
                    <span className="library__item-path" title={video.path}>
                      {video.path}
                    </span>
                  )}
                </div>
              </button>
              {provenance ? (
                <LibraryProvenance
                  video={{ id: video.id, path: video.path, title: video.title }}
                  handlers={provenance}
                />
              ) : null}
              <div className="library__item-meta">
                {video.hasTranscript ? (
                  <span className="library__badge" title="Has transcript">
                    T
                  </span>
                ) : null}
                <button
                  type="button"
                  className="library__remove-btn"
                  aria-label={`Remove ${video.title}`}
                  onClick={(e) => handleRemove(video.id, e)}
                >
                  Remove
                </button>
              </div>
            </li>
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
    </div>
  );
}

export default Library;
