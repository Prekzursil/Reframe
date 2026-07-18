// dialogIpc.ts — native "Add videos" file picker for the renderer (P2 U2).
//
// Registers `ipcMain.handle('dialog.openVideos')` -> `dialog.showOpenDialog`
// (multi-select, video file filters) resolving with the picked ABSOLUTE paths,
// or `[]` when the user cancels. The renderer reaches this through the preload
// bridge as `window.api.openVideos()` — the exact preload.ts/main.ts lines the
// WIRING agent must apply are specified in WIRING-U2.md (preload.ts/main.ts are
// shared files per CONTRACTS.md A8 and are NOT touched by this unit).
//
// CONTRACT-NOTE: the channel name mirrors the rpc-style dotted method naming
// ('dialog.openVideos') but is a plain Electron ipc channel, NOT a sidecar
// JSON-RPC method — it never reaches protocol.py.
import {
  app,
  BrowserWindow,
  dialog,
  ipcMain,
  type FileFilter,
  type IpcMainInvokeEvent,
  type OpenDialogOptions,
} from 'electron';

/** ipc channel for the native multi-select video picker. */
export const DIALOG_OPEN_VIDEOS_CHANNEL = 'dialog.openVideos';

/** Common video container extensions (no leading dot, per Electron FileFilter). */
export const VIDEO_EXTENSIONS: readonly string[] = [
  'mp4',
  'mkv',
  'mov',
  'webm',
  'avi',
  'm4v',
  'mpg',
  'mpeg',
  'wmv',
  'flv',
  'ts',
  'm2ts',
  '3gp',
  'ogv',
];

/** Dialog filters: videos first, with an explicit "All files" escape hatch. */
export const VIDEO_FILE_FILTERS: FileFilter[] = [
  { name: 'Videos', extensions: [...VIDEO_EXTENSIONS] },
  { name: 'All files', extensions: ['*'] },
];

const OPEN_VIDEOS_OPTIONS: OpenDialogOptions = {
  title: 'Add videos',
  buttonLabel: 'Add',
  properties: ['openFile', 'multiSelections'],
  filters: VIDEO_FILE_FILTERS,
};

/**
 * Show the native multi-select picker, parented to the requesting window when
 * it is still alive. Resolves with absolute paths; `[]` on cancel.
 */
async function openVideosDialog(event: IpcMainInvokeEvent): Promise<string[]> {
  const win = BrowserWindow.fromWebContents(event.sender);
  // Electron 43: showOpenDialog no longer restores the OS last-used directory
  // and now defaults `defaultPath` to the Downloads folder. Pass an explicit,
  // semantically-correct start dir (the user's Videos folder) so the picker
  // opens where videos live. Computed at call time (post app-ready), not at
  // module load, so app.getPath is always valid.
  const options: OpenDialogOptions = { ...OPEN_VIDEOS_OPTIONS, defaultPath: app.getPath('videos') };
  const result =
    win && !win.isDestroyed()
      ? await dialog.showOpenDialog(win, options)
      : await dialog.showOpenDialog(options);
  if (result.canceled) return [];
  return result.filePaths ?? [];
}

/**
 * Register the `dialog.openVideos` ipc handler. Returns a disposer that
 * removes it again (mirrors `registerIpc` in ipc.ts). The wiring agent calls
 * this from main.ts bootstrap (see WIRING-U2.md).
 */
export function registerDialogIpc(): () => void {
  ipcMain.handle(DIALOG_OPEN_VIDEOS_CHANNEL, openVideosDialog);
  return (): void => {
    ipcMain.removeHandler(DIALOG_OPEN_VIDEOS_CHANNEL);
  };
}
