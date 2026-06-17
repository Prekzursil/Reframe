// useShortThumbnail.test.ts — the pure poster-URL helper + the on-demand hook
// (P4 §6).
//
// The pure `thumbnailSrc` mapping is pinned directly. The `useShortThumbnail`
// hook is also exercised here (no JSX so the file stays .ts): serve-existing,
// generate-on-demand, the no-rpc / empty-clip short-circuit, and the
// error/empty-result fallbacks.

// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { thumbnailSrc, useShortThumbnail, type ThumbnailRpc } from './useShortThumbnail';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

describe('thumbnailSrc', () => {
  it('routes a poster path through the short: mstream resolver', () => {
    const url = thumbnailSrc('/exports/shorts-v1/a.thumb.jpg');
    expect(url).toContain('mstream://media/');
    expect(url).toContain('short%3A'); // encoded "short:"
    expect(url).toContain('a.thumb.jpg');
  });

  it('returns "" for an empty path (caller shows the glyph fallback)', () => {
    expect(thumbnailSrc('')).toBe('');
  });
});

describe('useShortThumbnail (hook)', () => {
  let container: HTMLDivElement;
  let root: Root;
  let resolved = '';

  function Harness(props: {
    rpc: ThumbnailRpc | null;
    clipPath: string;
    thumbnailPath: string;
  }): React.ReactElement {
    resolved = useShortThumbnail(props.rpc, props.clipPath, props.thumbnailPath);
    return React.createElement('div', null, resolved);
  }

  async function render(props: {
    rpc: ThumbnailRpc | null;
    clipPath: string;
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
    const rpc: ThumbnailRpc = { thumbnail: vi.fn() };
    await render({
      rpc,
      clipPath: '/exports/v1/clip.mp4',
      thumbnailPath: '/exports/v1/a.thumb.jpg',
    });
    expect(resolved).toBe(thumbnailSrc('/exports/v1/a.thumb.jpg'));
    expect(rpc.thumbnail).not.toHaveBeenCalled();
  });

  it('resolves to "" when no rpc client is available (useShortThumbnail.ts:55-57)', async () => {
    await render({ rpc: null, clipPath: '/exports/v1/clip.mp4', thumbnailPath: '' });
    expect(resolved).toBe('');
  });

  it('resolves to "" when the clip path is empty (no RPC fired)', async () => {
    const rpc: ThumbnailRpc = { thumbnail: vi.fn() };
    await render({ rpc, clipPath: '', thumbnailPath: '' });
    expect(resolved).toBe('');
    expect(rpc.thumbnail).not.toHaveBeenCalled();
  });

  it('generates the poster on demand and serves the returned path', async () => {
    const rpc: ThumbnailRpc = {
      thumbnail: vi.fn().mockResolvedValue({ thumbnailPath: '/exports/v1/gen.thumb.jpg' }),
    };
    await render({ rpc, clipPath: '/exports/v1/clip.mp4', thumbnailPath: '' });
    expect(rpc.thumbnail).toHaveBeenCalledWith('/exports/v1/clip.mp4');
    expect(resolved).toBe(thumbnailSrc('/exports/v1/gen.thumb.jpg'));
  });

  it('keeps "" when the generation returns an empty thumbnailPath', async () => {
    const rpc: ThumbnailRpc = {
      thumbnail: vi.fn().mockResolvedValue({ thumbnailPath: '' }),
    };
    await render({ rpc, clipPath: '/exports/v1/clip.mp4', thumbnailPath: '' });
    expect(resolved).toBe('');
  });

  it('falls back to "" when the generation RPC rejects', async () => {
    const rpc: ThumbnailRpc = {
      thumbnail: vi.fn().mockRejectedValue(new Error('no poster')),
    };
    await render({ rpc, clipPath: '/exports/v1/clip.mp4', thumbnailPath: '' });
    expect(resolved).toBe('');
  });
});
