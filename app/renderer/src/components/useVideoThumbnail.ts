// useVideoThumbnail.ts — generate + serve a SOURCE-library video's poster frame
// (UX/QoL WU-4).
//
// A near-clone of `useShortThumbnail` repointed at the source-library poster
// engine. Two facts it builds on:
//   1. `library.thumbnail({id})` (WU-2) extracts a poster from a SOURCE video by
//      reusing the shorts ffmpeg poster engine, persists `thumbnailPath` onto the
//      Video, and returns it. It is idempotent server-side (an existing
//      `data_dir/thumbnails/<id>.jpg` short-circuits — the runner never re-runs).
//   2. A raw filesystem path in `<img src>` cannot load in the sandboxed
//      renderer — image bytes must ride the `thumb:` mstream resolver (WU-3,
//      traversal-guarded inside the thumbnails root), so `thumbMediaUrl(path)`
//      resolves it.
//
// `videoThumbnailSrc(path)` is the pure URL helper (unit-tested without React).
// The `useVideoThumbnail` hook fetches the poster ON DEMAND (idempotent
// server-side) when a card has no `thumbnailPath` yet, and returns the mstream
// URL to render.
import { useEffect, useState } from 'react';
import { thumbMediaUrl } from './Player';

/** RPC surface this hook needs (a thin slice of lib/rpc's `client.library`). */
export interface VideoThumbnailRpc {
  thumbnail(videoId: string): Promise<{ thumbnailPath: string }>;
}

/**
 * The `<img src>` URL for a poster-frame path, routed through the `thumb:`
 * mstream resolver (image bytes can't load from a raw fs path in the sandbox).
 * Returns "" for an empty path (the caller falls back to the ▶ glyph). Pure.
 */
export function videoThumbnailSrc(thumbnailPath: string): string {
  return thumbnailPath ? thumbMediaUrl(thumbnailPath) : '';
}

/**
 * Resolve a renderable poster URL for a SOURCE-library video, generating it on
 * demand.
 *
 * - If `thumbnailPath` is already set, serve it immediately (no RPC).
 * - Otherwise call `rpc.thumbnail(videoId)` once (idempotent: the sidecar
 *   caches `data_dir/thumbnails/<id>.jpg`) and serve the returned path.
 * Best-effort: any failure leaves "" so the card shows the ▶ glyph fallback —
 * a missing poster never blocks the gallery. Never mutates inputs.
 */
export function useVideoThumbnail(
  rpc: VideoThumbnailRpc | null,
  videoId: string,
  thumbnailPath: string,
): string {
  const [resolved, setResolved] = useState<string>(() => videoThumbnailSrc(thumbnailPath));

  useEffect(() => {
    // An existing poster wins — serve it without an RPC round-trip.
    if (thumbnailPath) {
      setResolved(videoThumbnailSrc(thumbnailPath));
      return undefined;
    }
    if (!rpc || !videoId) {
      setResolved('');
      return undefined;
    }
    let alive = true;
    setResolved('');
    Promise.resolve(rpc.thumbnail(videoId))
      .then((res) => {
        if (alive && res && res.thumbnailPath) setResolved(videoThumbnailSrc(res.thumbnailPath));
      })
      .catch(() => {
        // No poster -> the card keeps the ▶ glyph fallback.
      });
    return () => {
      alive = false;
    };
  }, [rpc, videoId, thumbnailPath]);

  return resolved;
}
