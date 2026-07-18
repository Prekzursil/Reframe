// shellIpc.test.ts — unit tests for the P4 shell IPC handlers (WU-MAIN-IPC §6,
// C9): `shell.showItemInFolder` (open-in-folder) + the logo open-file picker.
// Electron is fully mocked: these tests pin the channel names, the
// showItemInFolder delegation, the single-select image-filter picker options,
// cancel semantics, window parenting and the disposer. Runs in node env.
import { describe, it, expect, vi, beforeEach } from 'vitest';

const mocks = vi.hoisted(() => ({
  handle: vi.fn(),
  removeHandler: vi.fn(),
  showItemInFolder: vi.fn(),
  showOpenDialog: vi.fn(),
  fromWebContents: vi.fn(),
  getPath: vi.fn(),
}));

vi.mock('electron', () => ({
  ipcMain: { handle: mocks.handle, removeHandler: mocks.removeHandler },
  shell: { showItemInFolder: mocks.showItemInFolder },
  dialog: { showOpenDialog: mocks.showOpenDialog },
  BrowserWindow: { fromWebContents: mocks.fromWebContents },
  app: { getPath: mocks.getPath },
}));

import {
  SHELL_SHOW_ITEM_CHANNEL,
  DIALOG_PICK_LOGO_CHANNEL,
  LOGO_FILE_FILTERS,
  registerShellIpc,
} from './shellIpc';

type OpenInFolderHandler = (event: unknown, path: unknown) => Promise<boolean>;
type PickLogoHandler = (event: { sender: unknown }) => Promise<string | null>;

/** Register and capture both ipc handlers the module installs. */
function install(): {
  openInFolder: OpenInFolderHandler;
  pickLogo: PickLogoHandler;
  dispose: () => void;
} {
  const dispose = registerShellIpc();
  expect(mocks.handle).toHaveBeenCalledTimes(2);
  const calls = mocks.handle.mock.calls as Array<[string, unknown]>;
  const showItem = calls.find((c) => c[0] === SHELL_SHOW_ITEM_CHANNEL);
  const pickLogo = calls.find((c) => c[0] === DIALOG_PICK_LOGO_CHANNEL);
  expect(showItem).toBeDefined();
  expect(pickLogo).toBeDefined();
  return {
    openInFolder: showItem![1] as OpenInFolderHandler,
    pickLogo: pickLogo![1] as PickLogoHandler,
    dispose,
  };
}

const fakeEvent = { sender: {} };

beforeEach(() => {
  mocks.handle.mockReset();
  mocks.removeHandler.mockReset();
  mocks.showItemInFolder.mockReset();
  mocks.showOpenDialog.mockReset();
  mocks.fromWebContents.mockReset();
  mocks.getPath.mockReset();
  mocks.fromWebContents.mockReturnValue(null);
  // E43: the logo picker passes an explicit defaultPath (the Pictures folder)
  // now that showOpenDialog no longer restores the OS last-used dir.
  mocks.getPath.mockReturnValue('/mock/Pictures');
});

describe('registerShellIpc — registration + teardown', () => {
  it('registers both channels and the disposer removes both', () => {
    const { dispose } = install();
    dispose();
    expect(mocks.removeHandler).toHaveBeenCalledWith(SHELL_SHOW_ITEM_CHANNEL);
    expect(mocks.removeHandler).toHaveBeenCalledWith(DIALOG_PICK_LOGO_CHANNEL);
  });
});

describe('shell.showItemInFolder handler', () => {
  it('delegates a valid path to shell.showItemInFolder and resolves true', async () => {
    const { openInFolder } = install();
    const ok = await openInFolder(fakeEvent, 'C:/exports/shorts-abc/clip.mp4');
    expect(ok).toBe(true);
    expect(mocks.showItemInFolder).toHaveBeenCalledTimes(1);
    expect(mocks.showItemInFolder).toHaveBeenCalledWith('C:/exports/shorts-abc/clip.mp4');
  });

  it('rejects a non-string path without calling shell and resolves false', async () => {
    const { openInFolder } = install();
    await expect(openInFolder(fakeEvent, 123)).resolves.toBe(false);
    await expect(openInFolder(fakeEvent, '')).resolves.toBe(false);
    await expect(openInFolder(fakeEvent, null)).resolves.toBe(false);
    expect(mocks.showItemInFolder).not.toHaveBeenCalled();
  });
});

describe('dialog.pickLogoFile handler', () => {
  it('opens a single-select image picker and returns the picked path', async () => {
    const { pickLogo } = install();
    mocks.showOpenDialog.mockResolvedValueOnce({
      canceled: false,
      filePaths: ['C:/brand/logo.png'],
    });

    const path = await pickLogo(fakeEvent);

    expect(path).toBe('C:/brand/logo.png');
    expect(mocks.showOpenDialog).toHaveBeenCalledTimes(1);
    const options = mocks.showOpenDialog.mock.calls[0][0] as {
      properties: string[];
      filters: typeof LOGO_FILE_FILTERS;
      defaultPath?: string;
    };
    expect(options.properties).toContain('openFile');
    expect(options.properties).not.toContain('multiSelections');
    expect(options.filters).toBe(LOGO_FILE_FILTERS);
    expect(options.filters[0].extensions).toContain('png');
    // E43: explicit defaultPath (Pictures folder).
    expect(mocks.getPath).toHaveBeenCalledWith('pictures');
    expect(options.defaultPath).toBe('/mock/Pictures');
  });

  it('returns null when the user cancels', async () => {
    const { pickLogo } = install();
    mocks.showOpenDialog.mockResolvedValueOnce({ canceled: true, filePaths: [] });
    await expect(pickLogo(fakeEvent)).resolves.toBeNull();
  });

  it('returns null when the dialog yields no path', async () => {
    const { pickLogo } = install();
    mocks.showOpenDialog.mockResolvedValueOnce({ canceled: false, filePaths: [] });
    await expect(pickLogo(fakeEvent)).resolves.toBeNull();
  });

  it('parents the dialog to the live window resolved from the sender', async () => {
    const { pickLogo } = install();
    const win = { isDestroyed: () => false };
    mocks.fromWebContents.mockReturnValueOnce(win);
    mocks.showOpenDialog.mockResolvedValueOnce({ canceled: false, filePaths: ['/logo.png'] });

    await expect(pickLogo(fakeEvent)).resolves.toBe('/logo.png');

    expect(mocks.fromWebContents).toHaveBeenCalledWith(fakeEvent.sender);
    // Two-argument overload: (parentWindow, options).
    expect(mocks.showOpenDialog.mock.calls[0][0]).toBe(win);
    expect(mocks.showOpenDialog.mock.calls[0][1]).toMatchObject({
      properties: ['openFile'],
      defaultPath: '/mock/Pictures',
    });
  });

  it('falls back to the unparented dialog when the window is destroyed', async () => {
    const { pickLogo } = install();
    mocks.fromWebContents.mockReturnValueOnce({ isDestroyed: () => true });
    mocks.showOpenDialog.mockResolvedValueOnce({ canceled: false, filePaths: ['/logo.png'] });

    await pickLogo(fakeEvent);

    // Single-argument overload: options only.
    expect(mocks.showOpenDialog.mock.calls[0][1]).toBeUndefined();
  });
});
