// security.ts — Electron defense-in-depth helpers (Lane-0 F3c).
//
// CONTRACT-NOTE (CONTRACTS.md §0/§7): Reframe is a LOCAL personal app — no auth,
// no remote servers, no telemetry. The renderer only ever loads the app's own
// bundle and talks to the sidecar through the sandboxed `window.api` bridge. That
// makes the threat model narrow but concrete: a compromised/poisoned renderer (or
// injected content) must not be able to (a) navigate the window to a remote/hostile
// origin, (b) open arbitrary non-web URIs via the OS (file:/javascript:/smb:…),
// (c) be granted device permissions, or (d) relax the CSP.
//
// These are PURE functions so the security decisions are unit-tested without a
// real BrowserWindow; main.ts wires them into the webContents/session events.

/**
 * The renderer may only navigate WITHIN its own origin (the app bundle, or the
 * dev server when running `electron-vite dev`). Any cross-origin `will-navigate`
 * is denied. Fail-closed: an unparseable target OR app origin returns false.
 *
 * `file:` SPECIAL-CASE: every `file:` URL shares the opaque `null` origin, so a
 * bare `target.origin === app.origin` check is a NO-OP for a packaged build (any
 * two local files compare equal). For a `file:` app we therefore pin the target
 * to the app's OWN bundle document (same protocol + pathname) — the app only ever
 * loads its own index.html, and same-document hash/route changes (index.html#/edit)
 * do not fire will-navigate and share app.pathname anyway (hash is excluded from
 * pathname), so legitimate navigation still passes while any sibling/downloaded
 * `file:` document is denied. Dev-server (http) origins keep the origin comparison.
 */
export function isAllowedNavigation(targetUrl: string, appUrl: string): boolean {
  try {
    const target = new URL(targetUrl);
    const app = new URL(appUrl);
    if (app.protocol === 'file:') {
      // Origin equality is a no-op for the opaque file: origin — pin to the
      // app's own bundle document (protocol + pathname) instead.
      return target.protocol === 'file:' && target.pathname === app.pathname;
    }
    return target.origin === app.origin;
  } catch {
    return false;
  }
}

/** Schemes the OS browser may be asked to open via shell.openExternal. */
const EXTERNAL_SCHEMES = new Set(['http:', 'https:']);

/**
 * `shell.openExternal` hands a URL to the OS, which will happily launch
 * `file:`-pointed executables, run `javascript:`, etc. Restrict it to web links
 * only. Fail-closed: an unparseable URL is denied (try/catch).
 */
export function isAllowedExternalUrl(url: string): boolean {
  try {
    return EXTERNAL_SCHEMES.has(new URL(url).protocol);
  } catch {
    return false;
  }
}

/**
 * Deny-by-default permission handler decision. A local media app needs NO web
 * permissions (camera/mic/geolocation/notifications/midi/clipboard/…), so every
 * request is refused. Wired into both `setPermissionRequestHandler` (async grant)
 * and `setPermissionCheckHandler` (sync check).
 */
export function shouldGrantPermission(_permission: string): boolean {
  return false;
}

/**
 * The single source of truth for the renderer CSP. Mirrors the meta-tag CSP but
 * is now ALSO served as a real response header (via onHeadersReceived) so it
 * cannot be stripped by a poisoned index.html. F3c drops the unused `file:`
 * media source (media is streamed through the privileged `mstream:` scheme, never
 * file://) and keeps everything else local-only.
 */
export function buildCspHeaderValue(): string {
  return [
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob: mstream:",
    "media-src 'self' data: blob: mstream:",
    "connect-src 'self'",
    // Self-hosted woff2 (styles/fonts.css) load from the app's own origin; explicit
    // font-src 'self' documents the policy and blocks any remote font CDN.
    "font-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
  ].join('; ');
}

/** Response-header shape Electron's onHeadersReceived expects/returns. */
export type ResponseHeaders = Record<string, string[]>;

/**
 * Merge our authoritative CSP into a response's headers (onHeadersReceived). Our
 * header WINS over any CSP the response already carried. Existing unrelated
 * headers are preserved.
 */
export function cspResponseHeaders(existing: ResponseHeaders | undefined): ResponseHeaders {
  const out: ResponseHeaders = {};
  // Copy through every header EXCEPT any case-variant of CSP (so ours is the only
  // one and a header-injected `content-security-policy` can't survive alongside it).
  for (const [key, value] of Object.entries(existing ?? {})) {
    if (key.toLowerCase() !== 'content-security-policy') {
      out[key] = value;
    }
  }
  out['Content-Security-Policy'] = [buildCspHeaderValue()];
  return out;
}
