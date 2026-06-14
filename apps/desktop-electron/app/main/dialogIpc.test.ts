// dialogIpc.test.ts — unit tests for the native "Add videos" picker handler
// (P2 U2). Electron is fully mocked: these tests pin the channel name, the
// multi-select + video-filter options, cancel semantics, window parenting and
// the disposer. Runs in the default node environment.
import { describe, it, expect, vi, beforeEach } from 'vitest';

const mocks = vi.hoisted(() => ({
  handle: vi.fn(),
  removeHandler: vi.fn(),
  showOpenDialog: vi.fn(),
  fromWebContents: vi.fn(),
}));

vi.mock('electron', () => ({
  ipcMain: { handle: mocks.handle, removeHandler: mocks.removeHandler },
  dialog: { showOpenDialog: mocks.showOpenDialog },
  BrowserWindow: { fromWebContents: mocks.fromWebContents },
}));

import {
  DIALOG_OPEN_VIDEOS_CHANNEL,
  VIDEO_FILE_FILTERS,
  registerDialogIpc,
} from './dialogIpc';

type Handler = (event: { sender: unknown }) => Promise<string[]>;

/** Register and capture the ipc handler the module installs. */
function install(): { handler: Handler; dispose: () => void } {
  const dispose = registerDialogIpc();
  expect(mocks.handle).toHaveBeenCalledTimes(1);
  const [channel, handler] = mocks.handle.mock.calls[0] as [string, Handler];
  expect(channel).toBe(DIALOG_OPEN_VIDEOS_CHANNEL);
  return { handler, dispose };
}

const fakeEvent = { sender: {} };

beforeEach(() => {
  mocks.handle.mockReset();
  mocks.removeHandler.mockReset();
  mocks.showOpenDialog.mockReset();
  mocks.fromWebContents.mockReset();
  // Default: no live window resolved from the sender.
  mocks.fromWebContents.mockReturnValue(null);
});

describe('registerDialogIpc', () => {
  it('registers on the dialog.openVideos channel and the disposer removes it', () => {
    const { dispose } = install();
    dispose();
    expect(mocks.removeHandler).toHaveBeenCalledWith(DIALOG_OPEN_VIDEOS_CHANNEL);
  });

  it('opens a multi-select dialog with video filters and returns the picked paths', async () => {
    const { handler } = install();
    mocks.showOpenDialog.mockResolvedValueOnce({
      canceled: false,
      filePaths: ['C:/clips/a.mp4', 'C:/clips/b with space.mkv'],
    });

    const paths = await handler(fakeEvent);

    expect(paths).toEqual(['C:/clips/a.mp4', 'C:/clips/b with space.mkv']);
    expect(mocks.showOpenDialog).toHaveBeenCalledTimes(1);
    // No live window -> the single-argument overload.
    const options = mocks.showOpenDialog.mock.calls[0][0] as {
      properties: string[];
      filters: typeof VIDEO_FILE_FILTERS;
    };
    expect(options.properties).toContain('openFile');
    expect(options.properties).toContain('multiSelections');
    expect(options.filters).toBe(VIDEO_FILE_FILTERS);
    expect(options.filters[0].extensions).toContain('mp4');
    expect(options.filters[0].extensions).toContain('mkv');
  });

  it('returns [] when the user cancels', async () => {
    const { handler } = install();
    mocks.showOpenDialog.mockResolvedValueOnce({ canceled: true, filePaths: [] });
    await expect(handler(fakeEvent)).resolves.toEqual([]);
  });

  it('parents the dialog to the live window resolved from the sender', async () => {
    const { handler } = install();
    const win = { isDestroyed: () => false };
    mocks.fromWebContents.mockReturnValueOnce(win);
    mocks.showOpenDialog.mockResolvedValueOnce({ canceled: false, filePaths: ['/v.mp4'] });

    await expect(handler(fakeEvent)).resolves.toEqual(['/v.mp4']);

    expect(mocks.fromWebContents).toHaveBeenCalledWith(fakeEvent.sender);
    // Two-argument overload: (parentWindow, options).
    expect(mocks.showOpenDialog.mock.calls[0][0]).toBe(win);
    expect(mocks.showOpenDialog.mock.calls[0][1]).toMatchObject({
      properties: ['openFile', 'multiSelections'],
    });
  });

  it('falls back to the unparented dialog when the window is destroyed', async () => {
    const { handler } = install();
    mocks.fromWebContents.mockReturnValueOnce({ isDestroyed: () => true });
    mocks.showOpenDialog.mockResolvedValueOnce({ canceled: false, filePaths: ['/v.mp4'] });

    await handler(fakeEvent);

    // Single-argument overload: options only.
    expect(mocks.showOpenDialog.mock.calls[0][1]).toBeUndefined();
  });
});
