// dataFolderIpc.test.ts — unit tests for the data-folder IPC handlers.
// Electron + node:fs are fully mocked: these pin the channel names, the
// get/pick/set delegation, the open-DIRECTORY picker options, cancel semantics,
// window parenting, the marker write, fail-soft semantics, and the disposer.
import { describe, it, expect, vi, beforeEach } from 'vitest';

const mocks = vi.hoisted(() => ({
  handle: vi.fn(),
  removeHandler: vi.fn(),
  showOpenDialog: vi.fn(),
  fromWebContents: vi.fn(),
  writeFileSync: vi.fn(),
}));

vi.mock('electron', () => ({
  ipcMain: { handle: mocks.handle, removeHandler: mocks.removeHandler },
  dialog: { showOpenDialog: mocks.showOpenDialog },
  BrowserWindow: { fromWebContents: mocks.fromWebContents },
}));

vi.mock('node:fs', () => ({ writeFileSync: mocks.writeFileSync }));

import {
  DATA_FOLDER_GET_CHANNEL,
  DATA_FOLDER_PICK_CHANNEL,
  DATA_FOLDER_SET_CHANNEL,
  registerDataFolderIpc,
} from './dataFolderIpc';

const MARKER_PATH = 'C:/Apps/Reframe/data-dir.txt';
const DATA_ROOT = 'D:/MediaStudioData';

type GetHandler = () => string;
type PickHandler = (event: { sender: unknown }) => Promise<string | null>;
type SetHandler = (event: unknown, path: unknown) => { ok: boolean };

function install(): {
  get: GetHandler;
  pick: PickHandler;
  set: SetHandler;
  dispose: () => void;
} {
  const dispose = registerDataFolderIpc({ getDataRoot: () => DATA_ROOT, markerPath: MARKER_PATH });
  expect(mocks.handle).toHaveBeenCalledTimes(3);
  const calls = mocks.handle.mock.calls as Array<[string, unknown]>;
  const find = (ch: string): unknown => calls.find((c) => c[0] === ch)?.[1];
  return {
    get: find(DATA_FOLDER_GET_CHANNEL) as GetHandler,
    pick: find(DATA_FOLDER_PICK_CHANNEL) as PickHandler,
    set: find(DATA_FOLDER_SET_CHANNEL) as SetHandler,
    dispose,
  };
}

const fakeEvent = { sender: {} };

beforeEach(() => {
  mocks.handle.mockReset();
  mocks.removeHandler.mockReset();
  mocks.showOpenDialog.mockReset();
  mocks.fromWebContents.mockReset();
  mocks.writeFileSync.mockReset();
  mocks.fromWebContents.mockReturnValue(null);
});

describe('registerDataFolderIpc — registration + teardown', () => {
  it('registers all three channels and the disposer removes them', () => {
    const { dispose } = install();
    dispose();
    expect(mocks.removeHandler).toHaveBeenCalledWith(DATA_FOLDER_GET_CHANNEL);
    expect(mocks.removeHandler).toHaveBeenCalledWith(DATA_FOLDER_PICK_CHANNEL);
    expect(mocks.removeHandler).toHaveBeenCalledWith(DATA_FOLDER_SET_CHANNEL);
  });
});

describe('dataFolder.get handler', () => {
  it('returns the injected data root', () => {
    const { get } = install();
    expect(get()).toBe(DATA_ROOT);
  });
});

describe('dataFolder.pick handler', () => {
  it('opens an open-DIRECTORY picker (with createDirectory) and returns the path', async () => {
    const { pick } = install();
    mocks.showOpenDialog.mockResolvedValueOnce({ canceled: false, filePaths: ['D:/Chosen'] });

    const path = await pick(fakeEvent);

    expect(path).toBe('D:/Chosen');
    const options = mocks.showOpenDialog.mock.calls[0][0] as {
      properties: string[];
      defaultPath?: string;
    };
    expect(options.properties).toContain('openDirectory');
    expect(options.properties).toContain('createDirectory');
    expect(options.properties).not.toContain('openFile');
    // E43: explicit defaultPath — open the picker at the data root currently in
    // use (best UX for "change data folder"; showOpenDialog no longer restores
    // the OS last-used dir).
    expect(options.defaultPath).toBe(DATA_ROOT);
  });

  it('returns null when the user cancels', async () => {
    const { pick } = install();
    mocks.showOpenDialog.mockResolvedValueOnce({ canceled: true, filePaths: [] });
    await expect(pick(fakeEvent)).resolves.toBeNull();
  });

  it('returns null when the dialog yields no path', async () => {
    const { pick } = install();
    mocks.showOpenDialog.mockResolvedValueOnce({ canceled: false, filePaths: [] });
    await expect(pick(fakeEvent)).resolves.toBeNull();
  });

  it('parents the dialog to the live window resolved from the sender', async () => {
    const { pick } = install();
    const win = { isDestroyed: () => false };
    mocks.fromWebContents.mockReturnValueOnce(win);
    mocks.showOpenDialog.mockResolvedValueOnce({ canceled: false, filePaths: ['/d'] });

    await expect(pick(fakeEvent)).resolves.toBe('/d');

    expect(mocks.fromWebContents).toHaveBeenCalledWith(fakeEvent.sender);
    expect(mocks.showOpenDialog.mock.calls[0][0]).toBe(win);
    expect(mocks.showOpenDialog.mock.calls[0][1]).toMatchObject({
      properties: ['openDirectory', 'createDirectory'],
      defaultPath: DATA_ROOT,
    });
  });

  it('falls back to the unparented dialog when the window is destroyed', async () => {
    const { pick } = install();
    mocks.fromWebContents.mockReturnValueOnce({ isDestroyed: () => true });
    mocks.showOpenDialog.mockResolvedValueOnce({ canceled: false, filePaths: ['/d'] });

    await pick(fakeEvent);

    expect(mocks.showOpenDialog.mock.calls[0][1]).toBeUndefined();
  });
});

describe('dataFolder.set handler', () => {
  it('writes the trimmed path to the marker file and returns ok', () => {
    const { set } = install();
    const res = set(fakeEvent, '  D:/MyData  ');
    expect(res).toEqual({ ok: true });
    expect(mocks.writeFileSync).toHaveBeenCalledWith(MARKER_PATH, 'D:/MyData', 'utf8');
  });

  it('rejects a non-string path without writing', () => {
    const { set } = install();
    expect(set(fakeEvent, 123)).toEqual({ ok: false });
    expect(set(fakeEvent, null)).toEqual({ ok: false });
    expect(mocks.writeFileSync).not.toHaveBeenCalled();
  });

  it('rejects an empty/whitespace path without writing', () => {
    const { set } = install();
    expect(set(fakeEvent, '')).toEqual({ ok: false });
    expect(set(fakeEvent, '   ')).toEqual({ ok: false });
    expect(mocks.writeFileSync).not.toHaveBeenCalled();
  });

  it('returns ok:false (fail-soft) when the write throws', () => {
    const { set } = install();
    mocks.writeFileSync.mockImplementationOnce(() => {
      throw new Error('EROFS: read-only file system');
    });
    expect(set(fakeEvent, 'D:/MyData')).toEqual({ ok: false });
  });
});
