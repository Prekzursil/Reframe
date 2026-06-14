// Shorts.tsx — the generated-shorts gallery (P4 §6 / C11).
//
// A global view across ALL produced clips: a grid of cards (thumbnail, source
// title, caption template, virality badge, duration) with per-card actions —
// Play (inline preview over the exported file), Open folder, Re-export, Delete.
// Loads `shorts.list` (omitted videoId = every source) on mount and reloads
// after a delete.
//
// Wiring seams (all owned by earlier WUs, used here):
//   * client.shorts.{list,delete,reexport}  (lib/rpc.ts — typed wrappers / C8)
//   * shortMediaUrl(path)                    (components/Player.tsx — C10)
//   * window.api.openInFolder(path)          (preload bridge — §6 / C9)
// Re-export is a NAVIGATION concern: this view fires `shorts.reexport` and hands
// the returned hint to an injected `onReexport` callback (App re-opens the
// Short-maker primed), keeping the view free of routing knowledge.
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { client, hasApi, type ShortInfo, type ShortReexportHint } from '../lib/rpc';
import { Player, shortMediaUrl } from '../components/Player';
import { ShortClipActions } from '../components/ShortClipActions';
import { useShortThumbnail } from '../components/useShortThumbnail';
import './shorts.css';

// ---- pure helpers (exported for unit tests; no React render) ----------------

/** How the gallery is ordered (P4 §7: newest-first or by virality). */
export type ShortsSort = 'recent' | 'virality';

/** Newest-first by `createdAt`. Returns a NEW array (never mutates input). */
export function sortByCreatedAt(shorts: readonly ShortInfo[]): ShortInfo[] {
  return [...shorts].sort((a, b) => b.createdAt - a.createdAt);
}

/** A short's virality for SORTING: absent/invalid sinks to -1 (sorts last). */
function shortVirality(s: ShortInfo): number {
  return typeof s.viralityPct === 'number' && Number.isFinite(s.viralityPct) ? s.viralityPct : -1;
}

/**
 * Sort the gallery (P4 §7), NON-DESTRUCTIVELY:
 * - 'recent': newest `createdAt` first (the default).
 * - 'virality': highest viralityPct first; missing scores sink, ties fall back
 *   to newest-first so the order is always deterministic.
 */
export function sortShorts(shorts: readonly ShortInfo[], mode: ShortsSort): ShortInfo[] {
  if (mode === 'virality') {
    return [...shorts].sort((a, b) => {
      const d = shortVirality(b) - shortVirality(a);
      return d !== 0 ? d : b.createdAt - a.createdAt;
    });
  }
  return sortByCreatedAt(shorts);
}

/** mm:ss for a clip duration; "--:--" for non-finite / non-positive input. */
export function formatShortDuration(sec: number): string {
  if (!Number.isFinite(sec) || sec <= 0) return '--:--';
  const total = Math.round(sec);
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

function errText(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

/** Last path component, for a compact card filename. */
function baseName(p: string): string {
  const parts = p.split(/[\\/]/);
  return parts[parts.length - 1] || p;
}

/** Reveal a clip in the OS file explorer via the preload bridge (best-effort). */
function openInFolderBridge(): ((path: string) => Promise<boolean>) | null {
  const api = (globalThis as { window?: { api?: { openInFolder?: unknown } } }).window?.api;
  return api && typeof api.openInFolder === 'function'
    ? (api.openInFolder as (path: string) => Promise<boolean>)
    : null;
}

// ---- view -------------------------------------------------------------------

export interface ShortsProps {
  /**
   * Re-export reopens the Short-maker primed. This view only fires
   * `shorts.reexport` and hands the hint up; App owns the navigation.
   */
  onReexport?: (hint: ShortReexportHint) => void;
}

export function Shorts({ onReexport }: ShortsProps): React.ReactElement {
  const [shorts, setShorts] = useState<ShortInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // The clip currently playing inline (by id); null = no preview open.
  const [playingId, setPlayingId] = useState<string | null>(null);
  // P4 §7: gallery ordering — newest-first (default) or by virality.
  const [sortMode, setSortMode] = useState<ShortsSort>('recent');

  const refresh = useCallback(async () => {
    if (!hasApi()) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const res = await client.shorts.list();
      // Store unsorted; the display sort is applied at render so the toggle
      // re-orders without a refetch.
      setShorts(res?.shorts ?? []);
    } catch (err) {
      setError(errText(err));
    } finally {
      setLoading(false);
    }
  }, []);

  // P4 §7: apply the chosen sort for display (never mutates the stored list).
  const sortedShorts = useMemo(() => sortShorts(shorts, sortMode), [shorts, sortMode]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const handlePlay = useCallback((id: string) => {
    setPlayingId((cur) => (cur === id ? null : id));
  }, []);

  const handleOpenFolder = useCallback(
    async (path: string) => {
      const open = openInFolderBridge();
      if (!open) {
        setError('Open folder is unavailable (preload openInFolder bridge not wired).');
        return;
      }
      try {
        await open(path);
      } catch (err) {
        setError(errText(err));
      }
    },
    [],
  );

  const handleReexport = useCallback(
    async (path: string) => {
      setError(null);
      try {
        const hint = await client.shorts.reexport(path);
        onReexport?.(hint);
      } catch (err) {
        setError(errText(err));
      }
    },
    [onReexport],
  );

  const handleDelete = useCallback(
    async (path: string) => {
      // Confirm before any destructive call (UI confirms first — §2 shorts.delete).
      const ok = (globalThis as { confirm?: (m: string) => boolean }).confirm?.(
        `Delete this short?\n\n${baseName(path)}\n\nThis removes the exported file.`,
      );
      if (!ok) return;
      setError(null);
      try {
        await client.shorts.delete(path);
        await refresh();
      } catch (err) {
        setError(errText(err));
      }
    },
    [refresh],
  );

  return (
    <div className="shorts">
      <header className="shorts__header">
        <h1 className="shorts__title">Shorts</h1>
        <span className="shorts__count" aria-label="Shorts count">
          {shorts.length} clip{shorts.length === 1 ? '' : 's'}
        </span>
        {/* P4 §7: sort the gallery by recency or virality. */}
        {shorts.length > 0 ? (
          <div className="shorts__sort" role="group" aria-label="Sort shorts">
            <span className="shorts__sort-label">Sort</span>
            <button
              type="button"
              className={`shorts__sort-btn${sortMode === 'recent' ? ' is-active' : ''}`}
              aria-pressed={sortMode === 'recent'}
              onClick={() => setSortMode('recent')}
            >
              Recent
            </button>
            <button
              type="button"
              className={`shorts__sort-btn${sortMode === 'virality' ? ' is-active' : ''}`}
              aria-pressed={sortMode === 'virality'}
              onClick={() => setSortMode('virality')}
            >
              Virality
            </button>
          </div>
        ) : null}
      </header>

      {error ? (
        <div className="shorts__error" role="alert">
          {error}
        </div>
      ) : null}

      {loading ? (
        <div className="shorts__loading">Loading…</div>
      ) : shorts.length === 0 ? (
        <div className="shorts__empty">
          <div className="shorts__empty-poster" aria-hidden="true">
            <span className="shorts__empty-glyph">▶</span>
          </div>
          <p className="shorts__empty-title">No shorts yet</p>
          <p className="shorts__empty-hint">
            Open a video, run the Short-maker, and export clips — they show up here.
          </p>
        </div>
      ) : (
        <ul className="shorts__grid">
          {sortedShorts.map((short) => (
            <ShortCard
              key={short.id}
              short={short}
              playing={playingId === short.id}
              onPlay={handlePlay}
              onOpenFolder={handleOpenFolder}
              onReexport={handleReexport}
              onDelete={handleDelete}
            />
          ))}
        </ul>
      )}
    </div>
  );
}

// ---- card -------------------------------------------------------------------

interface ShortCardProps {
  short: ShortInfo;
  playing: boolean;
  onPlay: (id: string) => void;
  onOpenFolder: (path: string) => void;
  onReexport: (path: string) => void;
  onDelete: (path: string) => void;
}

function ShortCard({
  short,
  playing,
  onPlay,
  onOpenFolder,
  onReexport,
  onDelete,
}: ShortCardProps): React.ReactElement {
  const title = short.sourceTitle || baseName(short.path);
  const virality = typeof short.viralityPct === 'number' ? short.viralityPct : null;
  // P4 §6: generate the poster on demand (idempotent) + serve it over the
  // `short:` mstream resolver — a raw fs path can't load in the sandbox.
  const thumbSrc = useShortThumbnail(
    hasApi() ? client.shorts : null,
    short.path,
    short.thumbnailPath,
  );
  return (
    <li className="shorts__card" data-id={short.id}>
      <div className="shorts__thumb">
        {playing ? (
          <Player
            className="shorts__player"
            src={shortMediaUrl(short.path)}
            autoPlay
            controls
          />
        ) : (
          <button
            type="button"
            className="shorts__thumb-btn"
            aria-label={`Play preview of ${title}`}
            onClick={() => onPlay(short.id)}
          >
            {thumbSrc ? (
              <img className="shorts__thumb-img" src={thumbSrc} alt="" aria-hidden="true" />
            ) : (
              <span className="shorts__thumb-glyph" aria-hidden="true">
                ▶
              </span>
            )}
            <span className="shorts__thumb-duration">{formatShortDuration(short.durationSec)}</span>
          </button>
        )}
        {virality !== null ? (
          <span className="shorts__virality" aria-label="Virality">
            {virality}
            <span className="shorts__virality-pct">%</span>
          </span>
        ) : null}
      </div>

      <div className="shorts__meta">
        <span className="shorts__card-title" title={title}>
          {title}
        </span>
        {short.template ? (
          <span className="shorts__template" aria-label="Caption template">
            {short.template}
          </span>
        ) : null}
      </div>

      {short.hook ? <p className="shorts__hook">{short.hook}</p> : null}

      <ShortClipActions
        path={short.path}
        label={title}
        playing={playing}
        onPlay={() => onPlay(short.id)}
        onOpenFolder={onOpenFolder}
        onReexport={onReexport}
        onDelete={onDelete}
      />
    </li>
  );
}

export default Shorts;
