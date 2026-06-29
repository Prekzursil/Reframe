// lineageActionsClient.ts — the rpc/bridge-backed L5 action slice (DESIGN §3.4).
// (Named with a `Client` suffix so it never case-collides with LineageActions.tsx.)
//
// Wires <LineageActions> to the real sidecar RPCs (`library.reveal/regenerate/
// relink`) + the existing preload bridge (`openInFolder` = `shell.showItemInFolder`,
// `openVideos` = the native file picker reused to choose a moved source). The
// bridge is read STRUCTURALLY at call time and degrades fail-soft (a missing
// capability returns false/null), so the component shows a clean "unavailable" /
// "could not reveal" state rather than crashing.

import { rpc } from '../components/api';
import type { RegenerateResult, RelinkResult, RevealResult } from '../lib/rpc';
import type { LineageActionHandlers } from './LineageActions';

/** The optional preload-bridge members the L5 actions use (read structurally). */
interface ActionBridge {
  openInFolder?: (path: string) => Promise<boolean>;
  openVideos?: () => Promise<string[]>;
}

function actionBridge(): ActionBridge | null {
  const api = (globalThis as { window?: { api?: unknown } }).window?.api;
  return api && typeof api === 'object' ? (api as ActionBridge) : null;
}

export const lineageActions: LineageActionHandlers = {
  reveal: (id) => rpc<RevealResult>('library.reveal', { id }),
  regenerate: (id) => rpc<RegenerateResult>('library.regenerate', { id }),
  relink: async (id, path) => {
    await rpc<RelinkResult>('library.relink', { id, path });
  },
  runRegenerate: async (descriptor) => {
    // Replay the producing op against the still-by-path source. `params` was
    // stored redacted (keys come from settings at run time, never params), so
    // re-dispatching the op verbatim reproduces the original run.
    await rpc(descriptor.op, descriptor.params ?? {});
  },
  openInFolder: (path) => {
    const bridge = actionBridge();
    if (!bridge?.openInFolder) return Promise.resolve(false);
    return bridge.openInFolder(path);
  },
  pickRelinkTarget: async () => {
    const bridge = actionBridge();
    if (!bridge?.openVideos) return null;
    const paths = await bridge.openVideos();
    return Array.isArray(paths) && paths.length > 0 ? paths[0] : null;
  },
};

export default lineageActions;
