// useShortsGallery.ts — per-video produced-shorts state + card-action handlers.
//
// Extracted from ShortMaker.tsx to keep that file under the 800-line budget
// (coding-style.md: files <800 lines). P4 §6 / C11: after every export the host
// reloads `shorts.list {videoId}` so the exported list gains the gallery card
// actions (play / open-folder / re-export / delete). This hook owns that small
// slice of state + the four best-effort handlers; the ShortMaker container wires
// `reloadVideoShorts` into its export/batch flows. Behaviour is identical to the
// inline callbacks it replaced (same RPC method/field names, same error paths).

import type React from 'react';
import { useCallback, useState } from 'react';

import { useConfirm } from '../components/ConfirmDialog';
import type { Api } from './shortMakerLogic';
import { errMsg } from './shortMakerLogic';
import type { ShortInfo, ShortReexportHint } from '../lib/rpc';

export interface ShortsGallery {
  /** The produced shorts FOR THIS VIDEO (enriched ShortInfo from shorts.list). */
  videoShorts: ShortInfo[];
  /**
   * W04: the themed delete gate. This hook is not a component, so it cannot put
   * the dialog on screen itself — the container that renders the gallery must
   * render this node, or `deleteShort` will ask a question nobody can answer.
   */
  confirmDialog: React.ReactElement | null;
  /** Path of the clip currently inline-playing ('' = none). */
  playingShortPath: string;
  /** Reload shorts.list for this video (best-effort; clears on failure). */
  reloadVideoShorts: () => Promise<void>;
  /** Toggle inline playback of a clip (clicking the playing one stops it). */
  playShort: (path: string) => void;
  openShortFolder: (path: string) => Promise<void>;
  reexportShort: (path: string) => Promise<void>;
  deleteShort: (path: string) => Promise<void>;
}

export interface UseShortsGalleryOptions {
  resolvedApi: Api;
  videoId: string;
  /** Surface an error to the container's error banner. */
  setError: (msg: string | null) => void;
  /** C11: re-export is a NAVIGATION concern — the host re-opens Short-maker. */
  onReexport?: (hint: ShortReexportHint) => void;
}

/**
 * Owns the per-video produced-shorts list + its four card actions. Best-effort
 * sugar: a `shorts.list` failure leaves the plain exported summary intact rather
 * than blocking the review loop.
 */
export function useShortsGallery({
  resolvedApi,
  videoId,
  setError,
  onReexport,
}: UseShortsGalleryOptions): ShortsGallery {
  const [videoShorts, setVideoShorts] = useState<ShortInfo[]>([]);
  const [playingShortPath, setPlayingShortPath] = useState<string>('');
  const { confirm, confirmDialog } = useConfirm();

  const reloadVideoShorts = useCallback(async () => {
    if (!resolvedApi || !videoId) return;
    try {
      const res = await resolvedApi.rpc<{ shorts?: ShortInfo[] }>('shorts.list', { videoId });
      setVideoShorts(Array.isArray(res?.shorts) ? res.shorts : []);
    } catch {
      setVideoShorts([]);
    }
  }, [resolvedApi, videoId]);

  const playShort = useCallback((path: string) => {
    setPlayingShortPath((cur) => (cur === path ? '' : path));
  }, []);

  const openShortFolder = useCallback(
    async (path: string) => {
      if (typeof resolvedApi?.openInFolder !== 'function') {
        setError('Open folder is unavailable (preload openInFolder bridge not wired).');
        return;
      }
      try {
        await resolvedApi.openInFolder(path);
      } catch (e) {
        setError(errMsg(e));
      }
    },
    [resolvedApi, setError],
  );

  const reexportShort = useCallback(
    async (path: string) => {
      if (!resolvedApi) return;
      setError(null);
      try {
        const hint = await resolvedApi.rpc<ShortReexportHint>('shorts.reexport', { path });
        onReexport?.(hint);
      } catch (e) {
        setError(errMsg(e));
      }
    },
    [resolvedApi, onReexport, setError],
  );

  const deleteShort = useCallback(
    async (path: string) => {
      // W04: the themed gate, not the native `confirm()`. Native confirm is
      // unthemeable, carries no author-controlled accessible name/description,
      // and in Electron it blocks the whole renderer process while it is open.
      const ok = await confirm({
        title: 'Delete this short?',
        blurb: `${path}\n\nThis removes the exported file.`,
        confirmLabel: 'Delete short',
        cancelLabel: 'Keep it',
      });
      if (!ok || !resolvedApi) return;
      setError(null);
      try {
        await resolvedApi.rpc('shorts.delete', { path });
        await reloadVideoShorts();
      } catch (e) {
        setError(errMsg(e));
      }
    },
    [confirm, resolvedApi, reloadVideoShorts, setError],
  );

  return {
    videoShorts,
    confirmDialog,
    playingShortPath,
    reloadVideoShorts,
    playShort,
    openShortFolder,
    reexportShort,
    deleteShort,
  };
}
