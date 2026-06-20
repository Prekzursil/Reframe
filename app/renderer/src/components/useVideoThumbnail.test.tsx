// useVideoThumbnail.test.tsx — the pure poster-URL helper + the on-demand hook
// (UX/QoL WU-4).
//
// A near-clone of useShortThumbnail's test, repointed at the SOURCE-library
// poster engine: `library.thumbnail({id})` + the `thumb:` mstream resolver
// (WU-2 + WU-3). The pure `videoThumbnailSrc` mapping is pinned directly; the
// `useVideoThumbnail` hook is exercised for serve-existing, generate-on-demand,
// the no-rpc / empty-id short-circuit, and the error/empty-result fallbacks.
//
// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { videoThumbnailSrc, useVideoThumbnail, type VideoThumbnailRpc } from './useVideoThumbnail';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

describe('videoThumbnailSrc', () => {
  it('routes a poster path through the thumb: mstream resolver', () => {
    const url = videoThumbnailSrc('/data/thumbnails/v1.jpg');
    expect(url).toContain('mstream://media/');
    expect(url).toContain('thumb%3A'); // encoded "thumb:"
    expect(url).toContain('v1.jpg');
  });

  it('returns "" for an empty path (caller shows the glyph fallback)', () => {
    expect(videoThumbnailSrc('')).toBe('');
  });
});

describe('useVideoThumbnail (hook)', () => {
  let container: HTMLDivElement;
  let root: Root;
  let resolved = '';

  function Harness(props: {
    rpc: VideoThumbnailRpc | null;
    videoId: string;
    thumbnailPath: string;
  }): React.ReactElement {
    resolved = useVideoThumbnail(props.rpc, props.videoId, props.thumbnailPath);
    return React.createElement('div', null, resolved);
  }

  async function render(props: {
    rpc: VideoThumbnailRpc | null;
    videoId: string;
    thumbnailPath: string;
  }): Promise<void> {
    await act(async () => {
      root.render(React.createElement(Harness, props));
    });
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
  }

  beforeEach(() => {
    resolved = '';
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  it('serves an existing poster path immediately without an RPC call', async () => {
    const rpc: VideoThumbnailRpc = { thumbnail: vi.fn() };
    await render({
      rpc,
      videoId: 'v1',
      thumbnailPath: '/data/thumbnails/v1.jpg',
    });
    expect(resolved).toBe(videoThumbnailSrc('/data/thumbnails/v1.jpg'));
    expect(rpc.thumbnail).not.toHaveBeenCalled();
  });

  it('resolves to "" when no rpc client is available', async () => {
    await render({ rpc: null, videoId: 'v1', thumbnailPath: '' });
    expect(resolved).toBe('');
  });

  it('resolves to "" when the video id is empty (no RPC fired)', async () => {
    const rpc: VideoThumbnailRpc = { thumbnail: vi.fn() };
    await render({ rpc, videoId: '', thumbnailPath: '' });
    expect(resolved).toBe('');
    expect(rpc.thumbnail).not.toHaveBeenCalled();
  });

  it('generates the poster on demand and serves the returned path', async () => {
    const rpc: VideoThumbnailRpc = {
      thumbnail: vi.fn().mockResolvedValue({ thumbnailPath: '/data/thumbnails/gen.jpg' }),
    };
    await render({ rpc, videoId: 'v1', thumbnailPath: '' });
    expect(rpc.thumbnail).toHaveBeenCalledWith('v1');
    expect(resolved).toBe(videoThumbnailSrc('/data/thumbnails/gen.jpg'));
  });

  it('keeps "" when the generation returns an empty thumbnailPath', async () => {
    const rpc: VideoThumbnailRpc = {
      thumbnail: vi.fn().mockResolvedValue({ thumbnailPath: '' }),
    };
    await render({ rpc, videoId: 'v1', thumbnailPath: '' });
    expect(resolved).toBe('');
  });

  it('falls back to "" when the generation RPC rejects', async () => {
    const rpc: VideoThumbnailRpc = {
      thumbnail: vi.fn().mockRejectedValue(new Error('no poster')),
    };
    await render({ rpc, videoId: 'v1', thumbnailPath: '' });
    expect(resolved).toBe('');
  });
});
