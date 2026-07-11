// security.test.ts — pure unit tests for the Electron defense-in-depth helpers
// (Lane-0 F3c). These are the Node-testable units extracted from main.ts so the
// security boundary is verified WITHOUT spinning up a real BrowserWindow:
//   * will-navigate allowlist (only the app's own origin),
//   * openExternal scheme allowlist (http/https only, parse-fail = deny),
//   * deny-by-default permission decisions,
//   * the CSP header value served via onHeadersReceived (no `file:`).
import { describe, it, expect } from 'vitest';
import {
  isAllowedNavigation,
  isAllowedExternalUrl,
  shouldGrantPermission,
  buildCspHeaderValue,
  cspResponseHeaders,
} from './security';

describe('isAllowedNavigation', () => {
  const APP = 'file:///C:/app/out/renderer/index.html';

  it('allows navigation to the SAME origin (the app bundle)', () => {
    expect(isAllowedNavigation('file:///C:/app/out/renderer/index.html', APP)).toBe(true);
    // a hash/route change within the same document is same-origin
    expect(isAllowedNavigation('file:///C:/app/out/renderer/index.html#/edit', APP)).toBe(true);
  });

  it('allows a dev-server origin when that is the app origin', () => {
    const dev = 'http://localhost:5173/';
    expect(isAllowedNavigation('http://localhost:5173/index.html', dev)).toBe(true);
  });

  it('blocks navigation to a different origin (remote http)', () => {
    expect(isAllowedNavigation('https://evil.example.com/', APP)).toBe(false);
  });

  it('blocks a DIFFERENT file: path (opaque null origin is no longer a bypass)', () => {
    // file: origins are all "null"/opaque in the URL spec, so an origin-equality
    // check would let ANY local file through. We instead pin the target to the
    // app's own bundle pathname: a sibling/downloaded local file is now blocked.
    expect(
      isAllowedNavigation('file:///C:/Users/victim/Downloads/evil.html', APP),
    ).toBe(false);
    // A non-file scheme against a file: app is likewise blocked (the file: branch's
    // target.protocol sub-condition false-path).
    expect(isAllowedNavigation('http://localhost:9999/', APP)).toBe(false);
  });

  it('blocks an unparseable target (fail-closed)', () => {
    expect(isAllowedNavigation('::::not a url', APP)).toBe(false);
  });

  it('blocks when the app origin itself is unparseable (fail-closed)', () => {
    expect(isAllowedNavigation('https://x/', 'not-a-url')).toBe(false);
  });
});

describe('isAllowedExternalUrl', () => {
  it('allows http and https', () => {
    expect(isAllowedExternalUrl('https://example.com/page')).toBe(true);
    expect(isAllowedExternalUrl('http://example.com/page')).toBe(true);
  });

  it('rejects file:, javascript:, data:, and other schemes', () => {
    expect(isAllowedExternalUrl('file:///C:/Windows/system32/calc.exe')).toBe(false);
    expect(isAllowedExternalUrl('javascript:alert(1)')).toBe(false);
    expect(isAllowedExternalUrl('data:text/html,<script>1</script>')).toBe(false);
    expect(isAllowedExternalUrl('vbscript:msgbox(1)')).toBe(false);
    expect(isAllowedExternalUrl('smb://attacker/share')).toBe(false);
  });

  it('rejects an unparseable url (try/catch deny)', () => {
    expect(isAllowedExternalUrl('::::')).toBe(false);
    expect(isAllowedExternalUrl('')).toBe(false);
  });
});

describe('shouldGrantPermission (deny-by-default)', () => {
  it('denies every requested permission (local app needs none)', () => {
    for (const p of [
      'media',
      'geolocation',
      'notifications',
      'midi',
      'camera',
      'clipboard-read',
      'unknown',
    ]) {
      expect(shouldGrantPermission(p)).toBe(false);
    }
  });
});

describe('buildCspHeaderValue', () => {
  const csp = buildCspHeaderValue();

  it('pins default-src to self and forbids object/base hijack', () => {
    expect(csp).toContain("default-src 'self'");
    expect(csp).toContain("object-src 'none'");
    expect(csp).toContain("base-uri 'self'");
  });

  it('allows the mstream: media scheme for img/media but NOT file:', () => {
    expect(csp).toContain('mstream:');
    // F3c: the unused file: source is dropped from media-src.
    expect(csp).not.toContain('file:');
  });

  it('keeps connect-src local-only (no remote origins)', () => {
    expect(csp).toContain("connect-src 'self'");
    expect(csp).not.toContain('http://');
    expect(csp).not.toContain('https://');
  });
});

describe('cspResponseHeaders (onHeadersReceived shape)', () => {
  it('merges the CSP header into existing response headers (case preserved)', () => {
    const existing = { 'X-Test': ['1'] };
    const out = cspResponseHeaders(existing);
    expect(out['X-Test']).toEqual(['1']);
    expect(out['Content-Security-Policy']).toEqual([buildCspHeaderValue()]);
  });

  it('works when there are no existing headers', () => {
    const out = cspResponseHeaders(undefined);
    expect(out['Content-Security-Policy']).toEqual([buildCspHeaderValue()]);
  });

  it('overwrites any header-injected CSP from the response (ours wins)', () => {
    const out = cspResponseHeaders({ 'Content-Security-Policy': ['default-src *'] });
    expect(out['Content-Security-Policy']).toEqual([buildCspHeaderValue()]);
  });
});
