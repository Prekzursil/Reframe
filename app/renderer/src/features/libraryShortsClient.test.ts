// libraryShortsClient.test.ts — the produced-shorts port for the content-first
// Library (v1.5 §4 P0). Covers each rpc forward (listAll incl. the null-list
// fallback, remove) and the fail-soft openFolder bridge across present / missing
// / no-window.api shapes.

// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

const listMock = vi.fn();
const deleteMock = vi.fn();

vi.mock('../lib/rpc', () => ({
  client: {
    shorts: {
      list: (...a: unknown[]) => listMock(...a),
      delete: (...a: unknown[]) => deleteMock(...a),
    },
  },
}));

import { libraryShortsClient } from './libraryShortsClient';
import type { ShortInfo } from '../lib/rpc';

beforeEach(() => {
  listMock.mockReset();
  deleteMock.mockReset();
});

afterEach(() => {
  delete (window as { api?: unknown }).api;
});

describe('libraryShortsClient.listAll', () => {
  it('returns every produced short from shorts.list (all sources)', async () => {
    const shorts = [
      { id: 's1', videoId: 'v1', path: '/exports/a.mp4' },
      { id: 's2', videoId: 'v1', path: '/exports/b.mp4' },
    ] as unknown as ShortInfo[];
    listMock.mockResolvedValue({ shorts });
    expect(await libraryShortsClient.listAll()).toEqual(shorts);
    // No videoId -> every source's clips (the whole produced-shorts index).
    expect(listMock).toHaveBeenCalledWith();
  });

  it('degrades to an empty array when the payload carries no list', async () => {
    listMock.mockResolvedValue({});
    expect(await libraryShortsClient.listAll()).toEqual([]);
  });
});

describe('libraryShortsClient.openFolder (fail-soft bridge)', () => {
  it('reveals the clip via the preload bridge when present', async () => {
    const openInFolder = vi.fn(async () => true);
    (window as { api?: unknown }).api = { openInFolder };
    await libraryShortsClient.openFolder('/exports/a.mp4');
    expect(openInFolder).toHaveBeenCalledWith('/exports/a.mp4');
  });

  it('throws a clear error when the bridge lacks openInFolder', async () => {
    (window as { api?: unknown }).api = {}; // present, but no openInFolder member
    await expect(libraryShortsClient.openFolder('/exports/a.mp4')).rejects.toThrow(
      'openInFolder bridge not wired',
    );
  });

  it('throws when there is no window.api at all', async () => {
    // no window.api installed by this test
    await expect(libraryShortsClient.openFolder('/exports/a.mp4')).rejects.toThrow(
      'Reveal in folder is unavailable',
    );
  });
});

describe('libraryShortsClient.remove', () => {
  it('deletes the clip via shorts.delete', async () => {
    deleteMock.mockResolvedValue({ ok: true });
    await libraryShortsClient.remove('/exports/a.mp4');
    expect(deleteMock).toHaveBeenCalledWith('/exports/a.mp4');
  });
});
