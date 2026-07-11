// shellIpc.ts — P4 main-process shell IPC handlers (WU-MAIN-IPC §6, C9).
//
// Two MAIN-process actions the renderer cannot do itself (they are NOT sidecar
// JSON-RPC methods — they never reach protocol.py):
//   * `shell.showItemInFolder` — reveal an exported clip in the OS file
//     explorer. Exposed to the renderer as `window.api.openInFolder(path)`.
//   * `dialog.pickLogoFile` — a native single-select open-file picker for the
//     brand-kit logo. Exposed as `window.api.pickLogoFile()` returning the
//     picked ABSOLUTE path, or null when the user cancels.
//
// Mirrors the proven `dialogIpc.ts` pattern: dotted channel names, a disposer
// the bootstrap() wires + tears down in will-quit, and a parented dialog.
//
// CONTRACT-NOTE: the channel names use the rpc-style dotted naming
// ('shell.showItemInFolder' / 'dialog.pickLogoFile') but are plain Electron ipc
// channels, NOT sidecar JSON-RPC methods.
import {
  app,
  BrowserWindow,
  dialog,
  ipcMain,
  shell,
  type FileFilter,
  type IpcMainInvokeEvent,
  type OpenDialogOptions,
} from 'electron';

/** ipc channel for reveal-in-OS-file-explorer (open-in-folder). */
export const SHELL_SHOW_ITEM_CHANNEL = 'shell.showItemInFolder';

/** ipc channel for the native single-select brand-logo picker. */
export const DIALOG_PICK_LOGO_CHANNEL = 'dialog.pickLogoFile';

/** Common raster/vector logo image extensions (no leading dot, per FileFilter). */
export const LOGO_EXTENSIONS: readonly string[] = [
  'png',
  'jpg',
  'jpeg',
  'webp',
  'gif',
  'bmp',
  'svg',
];

/** Dialog filters: images first, with an explicit "All files" escape hatch. */
export const LOGO_FILE_FILTERS: FileFilter[] = [
  { name: 'Images', extensions: [...LOGO_EXTENSIONS] },
  { name: 'All files', extensions: ['*'] },
];

const PICK_LOGO_OPTIONS: OpenDialogOptions = {
  title: 'Choose a brand logo',
  buttonLabel: 'Choose',
  properties: ['openFile'],
  filters: LOGO_FILE_FILTERS,
};

/**
 * Reveal `path` in the OS file explorer. Returns false (without touching the
 * shell) when the renderer passed a non-string/empty path — never throws so a
 * bad arg can't crash the handler.
 */
async function showItemInFolder(_event: IpcMainInvokeEvent, path: unknown): Promise<boolean> {
  if (typeof path !== 'string' || path === '') return false;
  shell.showItemInFolder(path);
  return true;
}

/**
 * Show the native single-select logo picker, parented to the requesting window
 * when it is still alive. Resolves with the absolute path, or null on cancel /
 * empty selection.
 */
async function pickLogoDialog(event: IpcMainInvokeEvent): Promise<string | null> {
  const win = BrowserWindow.fromWebContents(event.sender);
  // Electron 43: showOpenDialog no longer restores the OS last-used directory
  // and defaults `defaultPath` to Downloads. Pass an explicit start dir (the
  // user's Pictures folder) where logos naturally live. Computed at call time
  // (post app-ready), not at module load.
  const options: OpenDialogOptions = { ...PICK_LOGO_OPTIONS, defaultPath: app.getPath('pictures') };
  const result =
    win && !win.isDestroyed()
      ? await dialog.showOpenDialog(win, options)
      : await dialog.showOpenDialog(options);
  if (result.canceled) return null;
  return result.filePaths?.[0] ?? null;
}

/**
 * Register the P4 shell ipc handlers. Returns a disposer that removes both
 * (mirrors `registerDialogIpc` in dialogIpc.ts). bootstrap() in main.ts calls
 * this and tears the disposer down in will-quit.
 */
export function registerShellIpc(): () => void {
  ipcMain.handle(SHELL_SHOW_ITEM_CHANNEL, showItemInFolder);
  ipcMain.handle(DIALOG_PICK_LOGO_CHANNEL, pickLogoDialog);
  return (): void => {
    ipcMain.removeHandler(SHELL_SHOW_ITEM_CHANNEL);
    ipcMain.removeHandler(DIALOG_PICK_LOGO_CHANNEL);
  };
}
