// libraryShortsClient.ts — the rpc/bridge-backed produced-shorts port for the
// content-first Library (v1.5 §4 P0).
//
// Mirrors lineageActionsClient: it reuses the SHIPPED shorts RPCs
// (`client.shorts.list` / `client.shorts.delete`, lib/rpc/client.ts §2) and the
// existing `openInFolder` preload bridge (CONTRACTS.md §1) — no new machinery —
// so the Library's per-card "N shorts" count + gallery modal have a real backing.
// The bridge is read STRUCTURALLY at call time; the Library owns the fail-soft
// handling (a rejected listAll degrades to an empty index; a rejected openFolder/
// remove surfaces a typed toast), matching the lane-independent seam pattern.

import { client } from '../lib/rpc';
import type { ShortInfo } from '../lib/rpc';
import type { LibraryShortsApi } from '../views/Library';

/** The single optional preload-bridge member this port uses (read structurally). */
interface FolderBridge {
  openInFolder?: (path: string) => Promise<boolean>;
}

function folderBridge(): FolderBridge | null {
  const api = (globalThis as { window?: { api?: unknown } }).window?.api;
  return api && typeof api === 'object' ? (api as FolderBridge) : null;
}

export const libraryShortsClient: LibraryShortsApi = {
  // Every produced clip across all sources (omitted videoId = all); the Library
  // groups them by `videoId` for the per-card count. A `null`/absent payload
  // list degrades to an empty array so grouping never throws.
  listAll: async (): Promise<ShortInfo[]> => {
    const { shorts } = await client.shorts.list();
    return shorts ?? [];
  },
  // Reveal a clip in the OS file explorer. A missing bridge is surfaced (the
  // Library toasts the thrown message) rather than silently doing nothing.
  openFolder: async (path: string): Promise<void> => {
    const bridge = folderBridge();
    if (!bridge?.openInFolder) {
      throw new Error('Reveal in folder is unavailable (openInFolder bridge not wired).');
    }
    await bridge.openInFolder(path);
  },
  // Delete a produced clip file (path-traversal guarded sidecar-side); the
  // Library confirms + updates its index from the resolved deletion.
  remove: async (path: string): Promise<void> => {
    await client.shorts.delete(path);
  },
};

export default libraryShortsClient;
