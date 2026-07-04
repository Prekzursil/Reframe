// preload.ts — the contextBridge that exposes `window.api` to the renderer
// (CONTRACTS.md §1). The renderer NEVER touches ipcRenderer directly; it only
// sees the frozen `window.api` surface below.
//
// SHAPE (matched EXACTLY against the already-written renderer):
//   components/api.ts        -> rpc<T>(method, params?) : Promise<T>   (positional)
//                               onProgress(cb) : () => void            (unsubscribe)
//   components/api.test.ts   -> pins rpc('library.list') called with ('library.list', undefined)
//                               and onProgress(cb) returning the unsubscribe fn
//   features/_api.ts         -> same rpc / onProgress signatures (MediaStudioApi)
//   features/ShortMaker.tsx  -> Api { rpc, onProgress, onJobDone? } — onJobDone is
//                               OPTIONAL and used to resolve deferred {jobId} jobs
//                               via the terminal `job.done` notification.
//
// We therefore expose exactly: rpc, onProgress, AND onJobDone. The progress and
// done callbacks receive the notification PARAMS object straight from the
// sidecar ({jobId,pct,message} / {jobId,result}), and each subscribe returns an
// unsubscribe function (frozen contract: `onProgress(cb): () => void`).
import { contextBridge, ipcRenderer, webUtils, type IpcRendererEvent } from 'electron';

const RPC_CHANNEL = 'rpc';
const PROGRESS_CHANNEL = 'job.progress';
const DONE_CHANNEL = 'job.done';
const DIALOG_OPEN_VIDEOS_CHANNEL = 'dialog.openVideos'; // must match app/main/dialogIpc.ts
const SHELL_SHOW_ITEM_CHANNEL = 'shell.showItemInFolder'; // must match app/main/shellIpc.ts
const DIALOG_PICK_LOGO_CHANNEL = 'dialog.pickLogoFile'; // must match app/main/shellIpc.ts
const SIDECAR_RESTART_CHANNEL = 'sidecar.restart'; // must match app/main/ipc.ts
const SIDECAR_STATUS_CHANNEL = 'sidecar.status'; // must match app/main/ipc.ts
const BOOTSTRAP_ERROR_CHANNEL = 'bootstrap.error'; // must match app/main/main.ts
const SETUP_REPAIR_CHANNEL = 'setup.repair'; // must match app/main/repairSetupIpc.ts
const PROXY_STATE_CHANNEL = 'proxy.state'; // must match app/main/main.ts (WU B3)
const DATA_FOLDER_GET_CHANNEL = 'dataFolder.get'; // must match app/main/dataFolderIpc.ts
const DATA_FOLDER_PICK_CHANNEL = 'dataFolder.pick'; // must match app/main/dataFolderIpc.ts
const DATA_FOLDER_SET_CHANNEL = 'dataFolder.set'; // must match app/main/dataFolderIpc.ts
const SECURE_STATUS_CHANNEL = 'secure.status'; // must match app/main/ipc.ts (WU-D2b-1)

export interface ProgressEvent {
  jobId: string;
  pct: number;
  message: string;
}

export interface DoneEvent {
  jobId: string;
  result?: unknown;
}

/** WU B3: playback-proxy build lifecycle pushed per videoId to the renderer. */
export interface ProxyStateEvent {
  videoId: string;
  state: 'building' | 'ready' | 'error';
  detail: string;
}

/** Self-healing supervisor lifecycle states (mirrors sidecar.ts SidecarState). */
export type SidecarStatus = 'running' | 'restarting' | 'down';

/**
 * WU-D2b-1: the secure-key-storage availability decision (mirrors keystore.ts
 * SecureStatus). `sessionOnly` true means keys cannot be saved at rest on this
 * system, so the renderer shows the loud session-only banner.
 */
export interface SecureStatus {
  available: boolean;
  backend: string | null;
  sessionOnly: boolean;
  banner: string | null;
}

/** WU A5: outcome of an on-demand "Retry setup / Repair" bootstrap re-run. */
export interface RepairSetupResult {
  ok: boolean;
  reason?: string;
}

export interface MediaApi {
  /** Forward a JSON-RPC method to the sidecar; resolves with its result. */
  rpc<T = unknown>(method: string, params?: Record<string, unknown>): Promise<T>;
  /** Subscribe to `job.progress` notifications. Returns an unsubscribe fn. */
  onProgress(cb: (event: ProgressEvent) => void): () => void;
  /** Subscribe to `job.done` notifications. Returns an unsubscribe fn. */
  onJobDone(cb: (event: DoneEvent) => void): () => void;
  /**
   * WU B3: subscribe to playback-proxy build-state pushes (`proxy.state`). The
   * Workspace shows a "building…" note, reloads the player on 'ready', and
   * surfaces the reason LOUDLY on 'error'. Returns an unsubscribe fn.
   */
  onProxyState(cb: (event: ProxyStateEvent) => void): () => void;
  /** Native multi-select video picker; resolves with absolute paths ([] when cancelled). */
  openVideos(): Promise<string[]>;
  /**
   * P4 (§6, C9): reveal a path in the OS file explorer (`shell.showItemInFolder`).
   * Resolves true when the path was passed to the shell, false on a bad arg.
   */
  openInFolder(path: string): Promise<boolean>;
  /**
   * P4 (8d, C9): native single-select brand-logo picker. Resolves with the
   * chosen absolute path, or null when the user cancels.
   */
  pickLogoFile(): Promise<string | null>;
  /**
   * Resolve a dropped File to its absolute filesystem path.
   * Electron >=32 removed File.path — webUtils.getPathForFile is the only path bridge.
   */
  pathForFile(file: File): string;
  /**
   * Self-healing supervisor: ask the main process to restart the sidecar. Resets
   * the crash-budget window so it works even after auto-restart gave up.
   * Resolves with `{ ok }` (true once a fresh process spawned).
   */
  restartSidecar(): Promise<{ ok: boolean }>;
  /** Subscribe to sidecar lifecycle transitions. Returns an unsubscribe fn. */
  onSidecarStatus(cb: (status: SidecarStatus) => void): () => void;
  /**
   * WU-1 FAIL-LOUD: subscribe to first-run setup failures. The main process
   * relays bootstrap.py's terminal `FAILED:bootstrap …` line (an actionable
   * message: what failed + where + how to fix) so a broken first run surfaces in
   * the UI instead of leaving an empty, silently-failing app. Returns an
   * unsubscribe fn.
   */
  onBootstrapError(cb: (message: string) => void): () => void;
  /**
   * WU A5: re-run the idempotent first-run bootstrap on demand ("Retry setup /
   * Repair"). Recovers a partially-failed first run in place — pip re-checks
   * satisfied deps, only missing assets re-download — and (re)starts the sidecar
   * on success. Resolves `{ ok, reason? }`.
   */
  repairSetup(): Promise<RepairSetupResult>;
  /**
   * DATA ROOT: the data folder (models/envs/exports/...) in use THIS session.
   * Resolves with the absolute path the sidecar also derives its tree from.
   */
  getDataFolder(): Promise<string>;
  /**
   * DATA ROOT: native open-DIRECTORY picker for the data folder. Resolves with
   * the chosen absolute path, or null when the user cancels.
   */
  pickDataFolder(): Promise<string | null>;
  /**
   * DATA ROOT: persist the chosen data folder to the marker file. Resolves with
   * `{ ok }`. Does NOT move files — a restart applies the new root.
   */
  setDataFolder(path: string): Promise<{ ok: boolean }>;
  /**
   * WU-D2b-1: query the secure-key-storage availability. When `sessionOnly` is
   * true the OS keychain (DPAPI/Keychain/libsecret) is unavailable or plaintext,
   * so API keys can only live in memory this session — the renderer shows the
   * loud `banner` telling the user keys cannot be saved.
   */
  getSecureStatus(): Promise<SecureStatus>;
}

const api: MediaApi = {
  rpc<T = unknown>(method: string, params?: Record<string, unknown>): Promise<T> {
    return ipcRenderer.invoke(RPC_CHANNEL, { method, params }) as Promise<T>;
  },

  onProgress(cb: (event: ProgressEvent) => void): () => void {
    const listener = (_event: IpcRendererEvent, payload: ProgressEvent): void => cb(payload);
    ipcRenderer.on(PROGRESS_CHANNEL, listener);
    return () => ipcRenderer.removeListener(PROGRESS_CHANNEL, listener);
  },

  onJobDone(cb: (event: DoneEvent) => void): () => void {
    const listener = (_event: IpcRendererEvent, payload: DoneEvent): void => cb(payload);
    ipcRenderer.on(DONE_CHANNEL, listener);
    return () => ipcRenderer.removeListener(DONE_CHANNEL, listener);
  },

  onProxyState(cb: (event: ProxyStateEvent) => void): () => void {
    const listener = (_event: IpcRendererEvent, payload: ProxyStateEvent): void => cb(payload);
    ipcRenderer.on(PROXY_STATE_CHANNEL, listener);
    return () => ipcRenderer.removeListener(PROXY_STATE_CHANNEL, listener);
  },

  openVideos(): Promise<string[]> {
    return ipcRenderer.invoke(DIALOG_OPEN_VIDEOS_CHANNEL) as Promise<string[]>;
  },

  openInFolder(path: string): Promise<boolean> {
    return ipcRenderer.invoke(SHELL_SHOW_ITEM_CHANNEL, path) as Promise<boolean>;
  },

  pickLogoFile(): Promise<string | null> {
    return ipcRenderer.invoke(DIALOG_PICK_LOGO_CHANNEL) as Promise<string | null>;
  },

  pathForFile(file: File): string {
    return webUtils.getPathForFile(file);
  },

  restartSidecar(): Promise<{ ok: boolean }> {
    return ipcRenderer.invoke(SIDECAR_RESTART_CHANNEL) as Promise<{ ok: boolean }>;
  },

  onSidecarStatus(cb: (status: SidecarStatus) => void): () => void {
    const listener = (_event: IpcRendererEvent, status: SidecarStatus): void => cb(status);
    ipcRenderer.on(SIDECAR_STATUS_CHANNEL, listener);
    return () => ipcRenderer.removeListener(SIDECAR_STATUS_CHANNEL, listener);
  },

  onBootstrapError(cb: (message: string) => void): () => void {
    const listener = (_event: IpcRendererEvent, message: string): void => cb(message);
    ipcRenderer.on(BOOTSTRAP_ERROR_CHANNEL, listener);
    return () => ipcRenderer.removeListener(BOOTSTRAP_ERROR_CHANNEL, listener);
  },

  repairSetup(): Promise<RepairSetupResult> {
    return ipcRenderer.invoke(SETUP_REPAIR_CHANNEL) as Promise<RepairSetupResult>;
  },

  getDataFolder(): Promise<string> {
    return ipcRenderer.invoke(DATA_FOLDER_GET_CHANNEL) as Promise<string>;
  },

  pickDataFolder(): Promise<string | null> {
    return ipcRenderer.invoke(DATA_FOLDER_PICK_CHANNEL) as Promise<string | null>;
  },

  setDataFolder(path: string): Promise<{ ok: boolean }> {
    return ipcRenderer.invoke(DATA_FOLDER_SET_CHANNEL, path) as Promise<{ ok: boolean }>;
  },

  getSecureStatus(): Promise<SecureStatus> {
    return ipcRenderer.invoke(SECURE_STATUS_CHANNEL) as Promise<SecureStatus>;
  },
};

contextBridge.exposeInMainWorld('api', api);
