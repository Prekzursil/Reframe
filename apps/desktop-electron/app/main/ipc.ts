// ipc.ts — bridge renderer <-> sidecar (CONTRACTS.md §1: main/ipc.ts).
//
// Renderer side (via preload `window.api`):
//   - invoke('rpc', {method, params})  -> forwarded to the sidecar, resolves
//     with the sidecar's `result` (or rejects with its error).
//   - listens on 'job.progress' / 'job.done' channels for streamed
//     notifications, which we relay from the Sidecar's events via
//     webContents.send to every live renderer.
//
// CONTRACT-NOTE (CONTRACTS.md §2): progress is a stream of `job.progress`
// notifications and long jobs also emit a terminal `job.done`. The frozen
// `window.api.onProgress(cb)` carries `job.progress`; we ALSO relay `job.done`
// on a separate channel so the optional `window.api.onJobDone(cb)` (used by
// ShortMaker's deferred-job path) can resolve `{jobId}` handles into terminal
// results. Both are best-effort fan-out to all renderer windows.
import { ipcMain, type BrowserWindow, type WebContents } from 'electron';
import type {
  DoneNotification,
  ProgressNotification,
  Sidecar,
  SidecarState,
} from './sidecar';

export const RPC_CHANNEL = 'rpc';
export const PROGRESS_CHANNEL = 'job.progress';
export const DONE_CHANNEL = 'job.done';
/** Self-healing supervisor: renderer-invoked manual restart (returns {ok}). */
export const SIDECAR_RESTART_CHANNEL = 'sidecar.restart';
/** Self-healing supervisor: main -> renderer lifecycle state push. */
export const SIDECAR_STATUS_CHANNEL = 'sidecar.status';

export interface RpcInvocation {
  method: string;
  params?: Record<string, unknown>;
}

/** Narrow the untrusted ipc payload into a valid {method, params}. */
function parseInvocation(raw: unknown): RpcInvocation {
  if (!raw || typeof raw !== 'object') {
    throw new Error('rpc invocation must be an object {method, params}');
  }
  const obj = raw as Record<string, unknown>;
  const method = obj.method;
  if (typeof method !== 'string' || method === '') {
    throw new Error('rpc invocation requires a non-empty string "method"');
  }
  const params = obj.params;
  if (params !== undefined && (typeof params !== 'object' || params === null)) {
    throw new Error('rpc invocation "params" must be an object when present');
  }
  return { method, params: (params as Record<string, unknown> | undefined) ?? undefined };
}

/**
 * Register the `rpc` handler and wire sidecar notifications to renderers.
 *
 * @param sidecar      the supervised Python process bridge
 * @param getWindows   returns the current set of windows to fan-out notifications to
 * @returns a disposer that removes the handler + listeners
 */
export function registerIpc(
  sidecar: Sidecar,
  getWindows: () => BrowserWindow[],
): () => void {
  // Renderer -> sidecar request/response.
  ipcMain.handle(RPC_CHANNEL, async (_event, raw: unknown) => {
    const { method, params } = parseInvocation(raw);
    return sidecar.request(method, params);
  });

  // Renderer -> supervisor: self-healing manual restart. Resets the crash
  // window + respawns even after the supervisor gave up auto-restart ('down').
  // Returns {ok}; never throws (A6.3: surface, don't swallow — the boolean lets
  // the banner re-offer Restart on failure).
  ipcMain.handle(SIDECAR_RESTART_CHANNEL, async () => sidecar.restart());

  // Sidecar -> renderer notifications (fan-out to every live window).
  const broadcast = (channel: string, payload: unknown): void => {
    for (const win of getWindows()) {
      if (win.isDestroyed()) continue;
      const wc: WebContents = win.webContents;
      if (wc.isDestroyed()) continue;
      wc.send(channel, payload);
    }
  };

  const onProgress = (p: ProgressNotification): void => broadcast(PROGRESS_CHANNEL, p);
  const onDone = (d: DoneNotification): void => broadcast(DONE_CHANNEL, d);
  const onStatus = (state: SidecarState): void => broadcast(SIDECAR_STATUS_CHANNEL, state);

  sidecar.on('progress', onProgress);
  sidecar.on('done', onDone);
  sidecar.on('status', onStatus);

  return (): void => {
    ipcMain.removeHandler(RPC_CHANNEL);
    ipcMain.removeHandler(SIDECAR_RESTART_CHANNEL);
    sidecar.off('progress', onProgress);
    sidecar.off('done', onDone);
    sidecar.off('status', onStatus);
  };
}
