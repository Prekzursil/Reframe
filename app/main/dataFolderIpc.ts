// dataFolderIpc.ts — main-process IPC for the relocatable DATA ROOT (the
// user-facing "data folder" that holds models/envs/exports/proxies/dubs/...).
//
// Three MAIN-process actions the renderer cannot do itself (they are NOT sidecar
// JSON-RPC methods):
//   * `dataFolder.get`  — return the data root currently IN USE this session.
//     Exposed as `window.api.getDataFolder()`.
//   * `dataFolder.pick` — a native open-DIRECTORY picker (createDirectory). Exposed
//     as `window.api.pickDataFolder()` returning the chosen path or null.
//   * `dataFolder.set`  — persist the chosen path to `<exeDir>/data-dir.txt` (the
//     marker chooseDataRoot reads next launch). Exposed as
//     `window.api.setDataFolder(path)` returning `{ ok }`. It does NOT move any
//     files — a restart applies the new root via resolveDataRoot.
//
// Mirrors the proven `shellIpc.ts` pattern: dotted channel names, a disposer the
// bootstrap() wires + tears down in will-quit, a parented dialog. The active
// data root + the marker's destination path are injected (main.ts owns the IO
// wiring) so this module stays thin and testable.
import {
  BrowserWindow,
  dialog,
  ipcMain,
  type IpcMainInvokeEvent,
  type OpenDialogOptions,
} from 'electron';
import { writeFileSync } from 'node:fs';

/** ipc channel: read the data root currently in use this session. */
export const DATA_FOLDER_GET_CHANNEL = 'dataFolder.get';

/** ipc channel: native open-directory picker for the data folder. */
export const DATA_FOLDER_PICK_CHANNEL = 'dataFolder.pick';

/** ipc channel: persist the chosen data folder to the marker file. */
export const DATA_FOLDER_SET_CHANNEL = 'dataFolder.set';

const PICK_FOLDER_OPTIONS: OpenDialogOptions = {
  title: 'Choose a data folder',
  buttonLabel: 'Choose',
  // createDirectory lets the user make a fresh folder from the dialog (macOS);
  // openDirectory restricts the selection to a single directory.
  properties: ['openDirectory', 'createDirectory'],
};

/** Wiring the handlers need from main.ts (keeps this module electron-IO-free). */
export interface DataFolderIpcDeps {
  /** The data root resolved + in use THIS session (returned to the renderer). */
  getDataRoot: () => string;
  /** Absolute path of the marker file to write (`<exeDir>/data-dir.txt`). */
  markerPath: string;
}

/** Result of `dataFolder.set`: `{ ok }` — false when the write failed. */
export interface SetDataFolderResult {
  ok: boolean;
}

/**
 * Show the native single-select directory picker, parented to the requesting
 * window when it is still alive. Resolves with the absolute path, or null on
 * cancel / empty selection.
 */
async function pickDataFolderDialog(event: IpcMainInvokeEvent): Promise<string | null> {
  const win = BrowserWindow.fromWebContents(event.sender);
  const result =
    win && !win.isDestroyed()
      ? await dialog.showOpenDialog(win, PICK_FOLDER_OPTIONS)
      : await dialog.showOpenDialog(PICK_FOLDER_OPTIONS);
  if (result.canceled) return null;
  return result.filePaths?.[0] ?? null;
}

/**
 * Persist the chosen data folder to the marker file. Returns `{ ok:false }`
 * (without throwing) for a non-string/empty path or a write failure — a bad
 * arg or a read-only install dir must never crash the handler.
 */
function setDataFolder(markerPath: string, path: unknown): SetDataFolderResult {
  if (typeof path !== 'string') return { ok: false };
  const trimmed = path.trim();
  if (trimmed === '') return { ok: false };
  try {
    writeFileSync(markerPath, trimmed, 'utf8');
    return { ok: true };
  } catch {
    // Fail-soft: a read-only install dir / AV lock surfaces as ok:false in the
    // UI rather than crashing the main process.
    return { ok: false };
  }
}

/**
 * Register the data-folder ipc handlers. Returns a disposer that removes all
 * three (mirrors `registerShellIpc`). bootstrap() in main.ts calls this and
 * tears the disposer down in will-quit.
 */
export function registerDataFolderIpc(deps: DataFolderIpcDeps): () => void {
  ipcMain.handle(DATA_FOLDER_GET_CHANNEL, () => deps.getDataRoot());
  ipcMain.handle(DATA_FOLDER_PICK_CHANNEL, pickDataFolderDialog);
  ipcMain.handle(DATA_FOLDER_SET_CHANNEL, (_event, path: unknown) =>
    setDataFolder(deps.markerPath, path),
  );
  return (): void => {
    ipcMain.removeHandler(DATA_FOLDER_GET_CHANNEL);
    ipcMain.removeHandler(DATA_FOLDER_PICK_CHANNEL);
    ipcMain.removeHandler(DATA_FOLDER_SET_CHANNEL);
  };
}
