// dataFolderIpc.ts — main-process IPC for the relocatable DATA ROOT (the
// user-facing "data folder" that holds models/envs/exports/proxies/dubs/...).
//
// Three MAIN-process actions the renderer cannot do itself (they are NOT sidecar
// JSON-RPC methods):
//   * `dataFolder.get`  — return the data root currently IN USE this session.
//     Exposed as `window.api.getDataFolder()`.
//   * `dataFolder.pick` — a native open-DIRECTORY picker (createDirectory). Exposed
//     as `window.api.pickDataFolder()` returning the chosen path or null.
//   * `dataFolder.set`  — persist the chosen path to the STABLE per-user marker
//     `<userData>/data-dir.txt` (the marker chooseDataRoot reads next launch),
//     mirrored best-effort into the legacy `<exeDir>/data-dir.txt` for downgrade
//     safety. Exposed as `window.api.setDataFolder(path)` returning `{ ok }`. It
//     does NOT move any files — a restart applies the new root via resolveDataRoot.
//     T13: writing ONLY inside `<exeDir>` lost the user's folder on every update,
//     because that dir is the NSIS `$INSTDIR` an in-place upgrade REPLACES.
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
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname } from 'node:path';

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
  /**
   * Absolute path of the AUTHORITATIVE marker to write — the STABLE per-user
   * `<userData>/data-dir.txt` (see dataRootIo.stableDataDirMarkerPath). T13: the
   * marker used to be written ONLY inside `<exeDir>` = the NSIS `$INSTDIR`, which
   * an in-place auto-update REPLACES, so every update forgot the user's folder.
   */
  markerPath: string;
  /**
   * Optional LEGACY `<exeDir>/data-dir.txt` path, MIRRORED best-effort after the
   * authoritative write succeeds so that rolling BACK to a build which only reads
   * the legacy location still finds the folder. Its failure (a read-only Program
   * Files install) never affects `ok`.
   */
  legacyMarkerPath?: string;
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
async function pickDataFolderDialog(
  event: IpcMainInvokeEvent,
  defaultPath: string,
): Promise<string | null> {
  const win = BrowserWindow.fromWebContents(event.sender);
  // Electron 43: showOpenDialog no longer restores the OS last-used directory
  // and defaults `defaultPath` to Downloads. Open the picker at the data root
  // currently in use so the user sees where their data lives today.
  const options: OpenDialogOptions = { ...PICK_FOLDER_OPTIONS, defaultPath };
  const result =
    win && !win.isDestroyed()
      ? await dialog.showOpenDialog(win, options)
      : await dialog.showOpenDialog(options);
  if (result.canceled) return null;
  return result.filePaths?.[0] ?? null;
}

/**
 * Write `value` to `markerPath`, creating its parent dir. Returns false — never
 * throwing — on any failure (a read-only install dir / AV lock / absent parent
 * must surface as `ok:false` in the UI, never crash the main process).
 */
function writeMarker(markerPath: string, value: string): boolean {
  try {
    mkdirSync(dirname(markerPath), { recursive: true });
    writeFileSync(markerPath, value, 'utf8');
    return true;
  } catch {
    return false;
  }
}

/**
 * Persist the chosen data folder. The AUTHORITATIVE write is `markerPath` (the
 * STABLE per-user copy that survives an app update — T13); on success the choice is
 * MIRRORED into the legacy `<exeDir>` marker best-effort for downgrade safety.
 *
 * Returns `{ ok:false }` (without throwing) for a non-string/empty path or when the
 * AUTHORITATIVE write fails. The legacy mirror is deliberately skipped in that
 * failure case: a legacy copy NEWER than a stale stable copy would silently send
 * the next launch — which prefers the stable copy — to the OLD folder.
 */
function setDataFolder(
  markerPath: string,
  legacyMarkerPath: string | undefined,
  path: unknown,
): SetDataFolderResult {
  if (typeof path !== 'string') return { ok: false };
  const trimmed = path.trim();
  if (trimmed === '') return { ok: false };
  if (!writeMarker(markerPath, trimmed)) return { ok: false };
  if (legacyMarkerPath !== undefined) writeMarker(legacyMarkerPath, trimmed);
  return { ok: true };
}

/**
 * Register the data-folder ipc handlers. Returns a disposer that removes all
 * three (mirrors `registerShellIpc`). bootstrap() in main.ts calls this and
 * tears the disposer down in will-quit.
 */
export function registerDataFolderIpc(deps: DataFolderIpcDeps): () => void {
  ipcMain.handle(DATA_FOLDER_GET_CHANNEL, () => deps.getDataRoot());
  ipcMain.handle(DATA_FOLDER_PICK_CHANNEL, (event: IpcMainInvokeEvent) =>
    pickDataFolderDialog(event, deps.getDataRoot()),
  );
  ipcMain.handle(DATA_FOLDER_SET_CHANNEL, (_event, path: unknown) =>
    setDataFolder(deps.markerPath, deps.legacyMarkerPath, path),
  );
  return (): void => {
    ipcMain.removeHandler(DATA_FOLDER_GET_CHANNEL);
    ipcMain.removeHandler(DATA_FOLDER_PICK_CHANNEL);
    ipcMain.removeHandler(DATA_FOLDER_SET_CHANNEL);
  };
}
