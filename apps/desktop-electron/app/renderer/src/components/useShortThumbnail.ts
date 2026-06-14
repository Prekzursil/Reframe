// useShortThumbnail.ts — generate + serve a short clip's poster frame (P4 §6).
//
// Two review gaps this closes:
//   1. `shorts.thumbnail` was never called from the app, so `thumbnailPath` was
//      "" for every freshly-listed clip (the poster never existed).
//   2. A raw filesystem path in `<img src>` cannot load in the sandboxed
//      renderer — image bytes must ride the `short:` mstream resolver (the same
//      traversal-guarded exports-root resolver used for playback). The poster
//      `<clip>.thumb.jpg` lives next to the clip (inside the exports root), so
//      `shortMediaUrl(thumbnailPath)` resolves it.
//
// `thumbnailSrc(path)` is the pure URL helper (unit-tested without React). The
// `useShortThumbnail` hook fetches the poster ON DEMAND (idempotent server-side)
// when a card has no `thumbnailPath` yet, and returns the mstream URL to render.
import { useEffect, useState } from 'react';
import { shortMediaUrl } from './Player';

/** RPC surface this hook needs (a thin slice of lib/rpc's `client.shorts`). */
export interface ThumbnailRpc {
  thumbnail(path: string): Promise<{ thumbnailPath: string }>;
}

/**
 * The `<img src>` URL for a poster-frame path, routed through the `short:`
 * mstream resolver (image bytes can't load from a raw fs path in the sandbox).
 * Returns "" for an empty path (the caller falls back to the ▶ glyph). Pure.
 */
export function thumbnailSrc(thumbnailPath: string): string {
  return thumbnailPath ? shortMediaUrl(thumbnailPath) : '';
}

/**
 * Resolve a renderable poster URL for a short clip, generating it on demand.
 *
 * - If `thumbnailPath` is already set, serve it immediately (no RPC).
 * - Otherwise call `rpc.thumbnail(clipPath)` once (idempotent: the sidecar
 *   caches `<clip>.thumb.jpg`) and serve the returned path.
 * Best-effort: any failure leaves "" so the card shows the ▶ glyph fallback —
 * a missing poster never blocks the gallery. Never mutates inputs.
 */
export function useShortThumbnail(
  rpc: ThumbnailRpc | null,
  clipPath: string,
  thumbnailPath: string,
): string {
  const [resolved, setResolved] = useState<string>(() => thumbnailSrc(thumbnailPath));

  useEffect(() => {
    // An existing poster wins — serve it without an RPC round-trip.
    if (thumbnailPath) {
      setResolved(thumbnailSrc(thumbnailPath));
      return undefined;
    }
    if (!rpc || !clipPath) {
      setResolved('');
      return undefined;
    }
    let alive = true;
    setResolved('');
    Promise.resolve(rpc.thumbnail(clipPath))
      .then((res) => {
        if (alive && res && res.thumbnailPath) setResolved(thumbnailSrc(res.thumbnailPath));
      })
      .catch(() => {
        // No poster -> the card keeps the ▶ glyph fallback.
      });
    return () => {
      alive = false;
    };
  }, [rpc, clipPath, thumbnailPath]);

  return resolved;
}
