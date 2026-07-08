// mediaProtocol.ts — the `mstream://` privileged custom protocol (P2 U1).
//
// WHY: the renderer is served from http://localhost in dev (and a bundled
// origin in prod), so raw `file://` video sources are blocked. This module
// streams local media files to the <video> tag over a privileged custom
// scheme WITH HTTP Range support — Chromium will not scrub/seek media from a
// protocol that ignores `Range: bytes=...` (and it ALWAYS sends an
// open-ended `bytes=0-` for the first media request).
//
// Wiring (see WIRING-U1.md):
//   1. `registerMediaSchemePrivileges()` at main.ts module top level —
//      Electron requires registerSchemesAsPrivileged BEFORE app `ready`.
//   2. `registerMediaProtocol(getPathForVideoId)` once inside bootstrap()
//      (after `app.whenReady()`), where `getPathForVideoId` resolves a
//      library videoId to the absolute path that should be PLAYED for it
//      (the original file, or the cached remux/proxy from `media.playable`).
//
// URL form (built by renderer/components/Player.tsx `mediaUrl()`):
//   mstream://media/<encodeURIComponent(videoId)>
// The fixed `media` host keeps the videoId in the PATH segment — a
// `standard:true` scheme lower-cases its host during URL normalization, so a
// host-embedded id would silently corrupt any non-lowercase videoId. The
// handler still accepts the bare `mstream://<id>` host form as a fallback
// (library ids are lowercase hex today).
//
// The request-shaping core (`parseRangeHeader` / `planRequest` /
// `videoIdFromUrl` / `contentTypeFor`) is pure and unit-tested in
// mediaProtocol.test.ts; only the thin handler touches fs/streams.
import { protocol } from 'electron';
import { createReadStream, promises as fsp } from 'node:fs';
import { Readable } from 'node:stream';
import { extname } from 'node:path';

export const MEDIA_SCHEME = 'mstream';
export const MEDIA_HOST = 'media';

/**
 * Thrown by a {@link GetPathForVideoId} resolver when the BACKEND that would
 * resolve the id is unavailable (e.g. the Python sidecar is down/restarting) —
 * as opposed to the id being genuinely unknown. The handler maps this to HTTP
 * 503 (transient — retry) instead of 404 (permanent — absent), so a dead sidecar
 * is diagnosable in DevTools Network instead of looking like a missing video.
 */
export class SidecarUnavailableError extends Error {
  constructor(message = 'sidecar unavailable') {
    super(message);
    this.name = 'SidecarUnavailableError';
  }
}

/**
 * Thrown by a resolver (WU B3) when a source needs a playback proxy and the
 * single-flight build has not finished within the bounded await. The build is
 * STILL running — the handler maps this to a transient HTTP 503 ("building")
 * distinct from a 404 (absent) or a 502 (build failed), so a slow transcode
 * never falls back to streaming the raw, non-Chromium-decodable original (the
 * "media error code 4" bug). The renderer's proxy-state channel shows a
 * "building…" note and reloads once the build completes.
 */
export class ProxyBuildingError extends Error {
  constructor(message = 'playback proxy is still building') {
    super(message);
    this.name = 'ProxyBuildingError';
  }
}

/**
 * Thrown by a resolver (WU B3) when the playback-proxy build FAILED (e.g.
 * ffmpeg exited non-zero). Mapped to HTTP 502 so the failure is surfaced
 * LOUDLY — never silently falling back to the undecodable original. Pairs with
 * the renderer's proxy-state "error" push so the reason reaches the UI.
 */
export class ProxyBuildFailedError extends Error {
  constructor(message = 'playback proxy build failed') {
    super(message);
    this.name = 'ProxyBuildFailedError';
  }
}

/**
 * Resolve a library videoId to the absolute path of the file to stream, or
 * null/undefined when unknown. May be async (the wiring implementation asks
 * the sidecar). Returning the PLAYABLE path (original or cached proxy) is the
 * caller's policy — this module just streams whatever path comes back.
 */
export type GetPathForVideoId = (
  videoId: string,
) => string | null | undefined | Promise<string | null | undefined>;

// ---------------------------------------------------------------------------
// pure: Range parsing (RFC 7233 single-range subset — what Chromium sends)
// ---------------------------------------------------------------------------

export type ParsedRange =
  /** No usable Range header (absent, malformed, or multi-range): serve 200 full. */
  | { kind: 'none' }
  /** A satisfiable single byte range (inclusive bounds, clamped to size). */
  | { kind: 'range'; start: number; end: number }
  /** Syntactically valid but unsatisfiable (e.g. start >= size): respond 416. */
  | { kind: 'unsatisfiable' };

/**
 * Parse a `Range` header against a known resource size.
 *
 * Handles the forms Chromium emits for media:
 *   `bytes=0-`        open-ended (ALWAYS sent first for <video>)
 *   `bytes=100-199`   bounded (end clamped to size-1)
 *   `bytes=-500`      suffix (last 500 bytes)
 * Per RFC 7233 a malformed or multi-range header is IGNORED (full response),
 * while a well-formed range that cannot be satisfied yields 416.
 */
export function parseRangeHeader(header: string | null | undefined, size: number): ParsedRange {
  if (!header) return { kind: 'none' };
  const match = /^\s*bytes\s*=\s*(\d*)\s*-\s*(\d*)\s*$/i.exec(header);
  if (!match) return { kind: 'none' }; // malformed or multi-range -> ignore
  const [, rawStart, rawEnd] = match;

  if (rawStart === '' && rawEnd === '') return { kind: 'none' };

  if (rawStart === '') {
    // suffix form: bytes=-N (the last N bytes)
    const suffix = Number(rawEnd);
    if (!Number.isFinite(suffix) || suffix <= 0 || size <= 0) return { kind: 'unsatisfiable' };
    const start = Math.max(0, size - suffix);
    return { kind: 'range', start, end: size - 1 };
  }

  const start = Number(rawStart);
  if (!Number.isFinite(start)) return { kind: 'none' };
  const end = rawEnd === '' ? size - 1 : Math.min(Number(rawEnd), size - 1);
  if (rawEnd !== '' && Number(rawEnd) < start) return { kind: 'none' }; // invalid spec -> ignore
  if (start >= size) return { kind: 'unsatisfiable' };
  return { kind: 'range', start, end };
}

export interface StreamPlan {
  /** HTTP status for the response: 200 full, 206 partial, 416 unsatisfiable. */
  status: 200 | 206 | 416;
  /** First byte to read (inclusive). 0 when status is 416. */
  start: number;
  /** Last byte to read (inclusive). -1 means "empty body" (zero-size file / 416). */
  end: number;
  /** Response headers (Accept-Ranges / Content-Length / Content-Range). */
  headers: Record<string, string>;
}

/**
 * Turn a raw Range header + file size into a complete response plan (pure).
 * The handler reads bytes [start..end] and sends `status` + `headers`.
 */
export function planRequest(rangeHeader: string | null | undefined, size: number): StreamPlan {
  const base: Record<string, string> = { 'Accept-Ranges': 'bytes' };
  const parsed = parseRangeHeader(rangeHeader, size);

  if (parsed.kind === 'unsatisfiable') {
    return {
      status: 416,
      start: 0,
      end: -1,
      headers: { ...base, 'Content-Range': `bytes */${size}` },
    };
  }

  if (parsed.kind === 'range') {
    const length = parsed.end - parsed.start + 1;
    return {
      status: 206,
      start: parsed.start,
      end: parsed.end,
      headers: {
        ...base,
        'Content-Length': String(length),
        'Content-Range': `bytes ${parsed.start}-${parsed.end}/${size}`,
      },
    };
  }

  return {
    status: 200,
    start: 0,
    end: size - 1,
    headers: { ...base, 'Content-Length': String(size) },
  };
}

// ---------------------------------------------------------------------------
// pure: URL + content-type helpers
// ---------------------------------------------------------------------------

/**
 * Extract the videoId from an `mstream://` request URL.
 * Canonical form `mstream://media/<id>` (id in the path, case-preserved);
 * fallback form `mstream://<id>` (id as host — lowercase ids only).
 */
export function videoIdFromUrl(rawUrl: string): string | null {
  let url: URL;
  try {
    url = new URL(rawUrl);
  } catch {
    return null;
  }
  if (url.protocol !== `${MEDIA_SCHEME}:`) return null;
  const segments = url.pathname.split('/').filter((s) => s.length > 0);
  try {
    if (url.hostname === MEDIA_HOST) {
      return segments.length > 0 ? decodeURIComponent(segments[0]) : null;
    }
    if (url.hostname) return decodeURIComponent(url.hostname);
    return segments.length > 0 ? decodeURIComponent(segments[0]) : null;
  } catch {
    return null; // malformed percent-encoding
  }
}

// CONTRACT-NOTE: the contract does not freeze a MIME map; this covers the
// containers U1/media_compat can produce or pass through. Unknown extensions
// fall back to video/mp4 (Chromium sniffs the actual bytes anyway, and a
// generic application/octet-stream makes <video> refuse some sources).
const CONTENT_TYPES: Record<string, string> = {
  '.mp4': 'video/mp4',
  '.m4v': 'video/mp4',
  '.mov': 'video/quicktime',
  '.mkv': 'video/x-matroska',
  '.webm': 'video/webm',
  '.avi': 'video/x-msvideo',
  '.ts': 'video/mp2t',
  '.wmv': 'video/x-ms-wmv',
  '.mpg': 'video/mpeg',
  '.mpeg': 'video/mpeg',
  '.ogv': 'video/ogg',
  '.mp3': 'audio/mpeg',
  '.m4a': 'audio/mp4',
  '.aac': 'audio/aac',
  '.wav': 'audio/wav',
  '.flac': 'audio/flac',
  '.ogg': 'audio/ogg',
  '.opus': 'audio/ogg',
  // P4 §6: short poster frames (`<clip>.thumb.jpg`) are served over the same
  // `short:` mstream resolver — an <img> needs an image MIME, not video/mp4.
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.png': 'image/png',
  '.webp': 'image/webp',
  '.gif': 'image/gif',
};

/** Map a file path to the Content-Type served for it. */
export function contentTypeFor(filePath: string): string {
  const ext = extname(filePath).toLowerCase();
  return CONTENT_TYPES[ext] ?? 'video/mp4';
}

// ---------------------------------------------------------------------------
// the protocol handler (thin I/O shell over the pure planners)
// ---------------------------------------------------------------------------

/**
 * Build the `(Request) => Response` handler used by `protocol.handle`.
 * Exported separately so tests can exercise it without an Electron app.
 */
export function createMediaRequestHandler(
  getPathForVideoId: GetPathForVideoId,
): (request: Request) => Promise<Response> {
  return async (request: Request): Promise<Response> => {
    const videoId = videoIdFromUrl(request.url);
    if (!videoId) {
      return new Response('bad mstream url', { status: 400 });
    }

    let filePath: string | null | undefined;
    try {
      filePath = await getPathForVideoId(videoId);
    } catch (err) {
      // A dead/throwing backend (sidecar down) is TRANSIENT -> 503 (retry),
      // distinct from a genuinely-absent id -> 404. Any other resolver throw is
      // treated conservatively as "could not resolve" -> 404 (unchanged).
      if (err instanceof SidecarUnavailableError) {
        return new Response(`sidecar unavailable: ${videoId}`, { status: 503 });
      }
      // WU B3: the source needs a playback proxy and the bounded single-flight
      // build is still running -> transient 503 (never stream the raw,
      // undecodable original). Distinct body so DevTools/renderer can tell it
      // apart from a dead sidecar.
      if (err instanceof ProxyBuildingError) {
        return new Response(`building playback proxy: ${videoId}`, { status: 503 });
      }
      // WU B3: the proxy build FAILED -> loud 502 (no silent fallback to the
      // undecodable source). The reason rides the response body + the renderer's
      // proxy-state channel.
      if (err instanceof ProxyBuildFailedError) {
        return new Response(`proxy build failed for ${videoId}: ${err.message}`, { status: 502 });
      }
      filePath = null;
    }
    if (!filePath) {
      return new Response(`unknown videoId: ${videoId}`, { status: 404 });
    }

    let size: number;
    try {
      const stat = await fsp.stat(filePath);
      if (!stat.isFile()) {
        return new Response('not a file', { status: 404 });
      }
      size = stat.size;
    } catch {
      return new Response('file missing', { status: 404 });
    }

    const plan = planRequest(request.headers.get('range'), size);
    const headers = { ...plan.headers, 'Content-Type': contentTypeFor(filePath) };

    if (plan.status === 416 || plan.end < plan.start) {
      // 416, or a zero-length body (empty file): no stream to attach.
      return new Response(null, { status: plan.status, headers });
    }

    const nodeStream = createReadStream(filePath, { start: plan.start, end: plan.end });
    const body = Readable.toWeb(nodeStream) as unknown as ReadableStream<Uint8Array>;
    return new Response(body, { status: plan.status, headers });
  };
}

/**
 * Declare the `mstream` scheme privileges. MUST run before app `ready`
 * (Electron hard requirement for registerSchemesAsPrivileged) — call it at
 * main.ts module top level. `stream: true` lets Chromium treat responses as
 * streaming media; `standard: true` gives the scheme URL semantics.
 */
export function registerMediaSchemePrivileges(): void {
  protocol.registerSchemesAsPrivileged([
    {
      scheme: MEDIA_SCHEME,
      privileges: {
        standard: true,
        secure: true,
        supportFetchAPI: true,
        stream: true,
        corsEnabled: false,
      },
    },
  ]);
}

/**
 * Mount the `mstream://` handler on the default session. Call once after
 * `app.whenReady()`, passing the videoId -> playable-path resolver.
 */
export function registerMediaProtocol(getPathForVideoId: GetPathForVideoId): void {
  protocol.handle(MEDIA_SCHEME, createMediaRequestHandler(getPathForVideoId));
}
