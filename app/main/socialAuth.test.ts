// socialAuth.test.ts — C14 desktop OAuth (PKCE + loopback) for social publishing.
//
// This is the security-critical half of C14, so the tests are written against the
// SPEC rather than against the implementation:
//
//   * the PKCE challenge is checked with the PUBLISHED RFC 7636 Appendix-B test
//     vector, so a self-consistent-but-wrong SHA/base64 pairing fails here instead
//     of failing silently against a real provider;
//   * the redirect URI guard is checked with real-world hostile shapes (a remote
//     host, a `127.0.0.1.evil.com` suffix trick, a userinfo `@` trick), because
//     sending the authorization CODE to a non-loopback host is the one mistake in
//     this flow that hands an attacker the account;
//   * the token endpoint is asserted https-only, because the exchange carries the
//     client secret.
//
// No socket is opened anywhere in this file: randomness and hashing are injected.
import { createHash } from 'node:crypto';
import { describe, expect, it } from 'vitest';
import {
  OAUTH_ENDPOINTS,
  PKCE_METHOD,
  buildAuthorizeUrl,
  buildTokenExchangeBody,
  challengeFor,
  createVerifier,
  isLoopbackRedirectUri,
  loopbackRedirectUri,
  oauthEndpoint,
  parseCallbackUrl,
} from './socialAuth';

const sha256 = (input: string): Buffer => createHash('sha256').update(input, 'ascii').digest();

/** Deterministic byte source: 0,1,2,… so a verifier is reproducible in tests. */
const countingBytes = (n: number): Buffer =>
  Buffer.from(Array.from({ length: n }, (_, i) => i % 256));

describe('PKCE (RFC 7636)', () => {
  it('derives the challenge exactly as the RFC 7636 Appendix-B vector does', () => {
    // The ONLY externally-anchored assertion in the PKCE unit: both values are
    // published in the RFC, so this fails if the hash, the encoding, or the
    // padding-strip is wrong — none of which a self-referential test would catch.
    const verifier = 'dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk';
    expect(challengeFor(verifier, sha256)).toBe('E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM');
  });

  it('uses the S256 method, never plain', () => {
    // `plain` sends the verifier itself in the authorize URL, defeating PKCE.
    expect(PKCE_METHOD).toBe('S256');
  });

  it('creates a verifier inside the RFC length window', () => {
    const verifier = createVerifier(countingBytes);
    expect(verifier.length).toBeGreaterThanOrEqual(43);
    expect(verifier.length).toBeLessThanOrEqual(128);
  });

  it('creates a verifier from the RFC unreserved character set only', () => {
    // base64url must be un-padded: `=`, `+` and `/` are not unreserved characters
    // and would be re-encoded in transit.
    expect(createVerifier(countingBytes)).toMatch(/^[A-Za-z0-9\-._~]+$/);
  });

  it('creates a different verifier for different randomness', () => {
    const a = createVerifier(countingBytes);
    const b = createVerifier((n) =>
      Buffer.from(Array.from({ length: n }, (_, i) => (i + 7) % 256)),
    );
    expect(a).not.toBe(b);
  });
});

describe('loopback redirect URI', () => {
  it('builds a 127.0.0.1 redirect on the given port', () => {
    expect(loopbackRedirectUri(51789)).toBe('http://127.0.0.1:51789/oauth/callback');
  });

  it('accepts its own output', () => {
    expect(isLoopbackRedirectUri(loopbackRedirectUri(8080))).toBe(true);
  });

  it('accepts the IPv6 loopback and localhost', () => {
    expect(isLoopbackRedirectUri('http://[::1]:8080/oauth/callback')).toBe(true);
    expect(isLoopbackRedirectUri('http://localhost:8080/oauth/callback')).toBe(true);
  });

  it('REJECTS a remote host', () => {
    expect(isLoopbackRedirectUri('https://evil.example/oauth/callback')).toBe(false);
  });

  it('REJECTS a host that merely starts with the loopback literal', () => {
    // `127.0.0.1.evil.com` resolves off-box; a `startsWith` check would pass it.
    expect(isLoopbackRedirectUri('http://127.0.0.1.evil.com/oauth/callback')).toBe(false);
  });

  it('REJECTS a userinfo trick that hides the real host', () => {
    // The real host here is evil.example — `127.0.0.1` is only the username.
    expect(isLoopbackRedirectUri('http://127.0.0.1@evil.example/oauth/callback')).toBe(false);
  });

  it('REJECTS an unparseable URI rather than defaulting to allow', () => {
    expect(isLoopbackRedirectUri('not a url')).toBe(false);
  });

  it('REJECTS a non-http scheme on the loopback host', () => {
    expect(isLoopbackRedirectUri('file://127.0.0.1/oauth/callback')).toBe(false);
  });

  it('rejects an out-of-range port', () => {
    expect(() => loopbackRedirectUri(0)).toThrow(/port/i);
    expect(() => loopbackRedirectUri(70000)).toThrow(/port/i);
  });

  it('rejects a non-integer port', () => {
    // A float would stringify into the URI as "8080.5" and never bind.
    expect(() => loopbackRedirectUri(8080.5)).toThrow(/port/i);
  });
});

describe('OAUTH_ENDPOINTS', () => {
  it('only covers the platforms that support a desktop loopback flow', () => {
    // instagram_reels and facebook_page are absent DELIBERATELY: Meta's login does
    // not offer a loopback desktop redirect, and Instagram additionally refuses a
    // personal account outright. Shipping an endpoint we cannot complete would be
    // a stub that lies about being wired.
    expect(Object.keys(OAUTH_ENDPOINTS).sort()).toEqual(['tiktok', 'youtube']);
  });

  it('uses an https token endpoint everywhere (the exchange carries the secret)', () => {
    for (const endpoint of Object.values(OAUTH_ENDPOINTS)) {
      expect(endpoint.tokenUrl.startsWith('https://')).toBe(true);
      expect(endpoint.authorizeUrl.startsWith('https://')).toBe(true);
    }
  });

  it('requests a narrow, purpose-scoped scope set', () => {
    expect(OAUTH_ENDPOINTS.youtube.scopes).toContain(
      'https://www.googleapis.com/auth/youtube.upload',
    );
  });

  it('resolves a known platform', () => {
    expect(oauthEndpoint('youtube').platform).toBe('youtube');
  });

  it('throws for a platform with no desktop flow', () => {
    expect(() => oauthEndpoint('instagram_reels')).toThrow(/desktop/i);
  });
});

describe('buildAuthorizeUrl', () => {
  const base = {
    platform: 'youtube',
    clientId: 'client-123.apps.googleusercontent.com',
    redirectUri: 'http://127.0.0.1:51789/oauth/callback',
    state: 'state-abc',
    codeChallenge: 'E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM',
  };

  it('carries the PKCE challenge and the S256 method', () => {
    const url = new URL(buildAuthorizeUrl(base));
    expect(url.searchParams.get('code_challenge')).toBe(base.codeChallenge);
    expect(url.searchParams.get('code_challenge_method')).toBe('S256');
  });

  it('carries the state, redirect and response_type=code', () => {
    const url = new URL(buildAuthorizeUrl(base));
    expect(url.searchParams.get('state')).toBe('state-abc');
    expect(url.searchParams.get('redirect_uri')).toBe(base.redirectUri);
    expect(url.searchParams.get('response_type')).toBe('code');
    expect(url.searchParams.get('client_id')).toBe(base.clientId);
  });

  it('NEVER carries a client secret (the authorize URL opens in a browser)', () => {
    // The authorize URL is handed to the OS browser and lands in history/logs.
    expect(buildAuthorizeUrl(base)).not.toMatch(/secret/i);
  });

  it('refuses a non-loopback redirect', () => {
    expect(() => buildAuthorizeUrl({ ...base, redirectUri: 'https://evil.example/cb' })).toThrow(
      /loopback/i,
    );
  });

  it('refuses an empty client id rather than building a URL that cannot work', () => {
    expect(() => buildAuthorizeUrl({ ...base, clientId: '  ' })).toThrow(/clientId/i);
  });

  it('refuses an empty state (state is the CSRF defence)', () => {
    expect(() => buildAuthorizeUrl({ ...base, state: '' })).toThrow(/state/i);
  });

  it('refuses an empty code challenge', () => {
    expect(() => buildAuthorizeUrl({ ...base, codeChallenge: '' })).toThrow(/challenge/i);
  });
});

describe('parseCallbackUrl', () => {
  const uri = 'http://127.0.0.1:51789/oauth/callback';

  it('returns the code when the state matches', () => {
    expect(parseCallbackUrl(`${uri}?code=auth-code-1&state=st-1`, 'st-1')).toEqual({
      code: 'auth-code-1',
    });
  });

  it('REJECTS a state mismatch (CSRF / code-injection defence)', () => {
    expect(() => parseCallbackUrl(`${uri}?code=c&state=WRONG`, 'st-1')).toThrow(/state/i);
  });

  it('REJECTS a missing state', () => {
    expect(() => parseCallbackUrl(`${uri}?code=c`, 'st-1')).toThrow(/state/i);
  });

  it('REJECTS an EQUAL-LENGTH state mismatch', () => {
    // The comparison is constant-time, which short-circuits on unequal length; a
    // same-length mismatch is the case that actually exercises the compare itself.
    expect(() => parseCallbackUrl(`${uri}?code=c&state=st-2`, 'st-1')).toThrow(/state/i);
  });

  it('surfaces a provider error instead of reporting success', () => {
    expect(() => parseCallbackUrl(`${uri}?error=access_denied&state=st-1`, 'st-1')).toThrow(
      /access_denied/,
    );
  });

  it('surfaces a provider error even when the state is absent', () => {
    // A denial can come back without state; reporting "state missing" would hide
    // the real, user-actionable reason.
    expect(() => parseCallbackUrl(`${uri}?error=access_denied`, 'st-1')).toThrow(/access_denied/);
  });

  it('REJECTS a callback with neither code nor error', () => {
    expect(() => parseCallbackUrl(`${uri}?state=st-1`, 'st-1')).toThrow(/code/i);
  });

  it('REJECTS an unparseable callback URL', () => {
    expect(() => parseCallbackUrl('%%%', 'st-1')).toThrow();
  });

  it('does not leak the expected state into the thrown message', () => {
    // The message can reach a log; echoing the expected state would let a reader
    // replay it.
    let message = '';
    try {
      parseCallbackUrl(`${uri}?code=c&state=WRONG`, 'secret-state-value');
    } catch (err) {
      message = (err as Error).message;
    }
    expect(message).not.toContain('secret-state-value');
  });
});

describe('buildTokenExchangeBody', () => {
  const base = {
    platform: 'youtube',
    clientId: 'client-123',
    clientSecret: 'secret-xyz',
    code: 'auth-code-1',
    codeVerifier: 'dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk',
    redirectUri: 'http://127.0.0.1:51789/oauth/callback',
  };

  it('sends the verifier so the server can re-derive the challenge', () => {
    const body = new URLSearchParams(buildTokenExchangeBody(base));
    expect(body.get('code_verifier')).toBe(base.codeVerifier);
    expect(body.get('grant_type')).toBe('authorization_code');
    expect(body.get('code')).toBe('auth-code-1');
    expect(body.get('redirect_uri')).toBe(base.redirectUri);
  });

  it('includes the client secret (these platforms require it)', () => {
    expect(new URLSearchParams(buildTokenExchangeBody(base)).get('client_secret')).toBe(
      'secret-xyz',
    );
  });

  it('omits client_secret entirely when the app has none configured', () => {
    // An empty string would be sent as `client_secret=`, which some servers treat
    // as a malformed credential rather than as absent.
    const body = new URLSearchParams(buildTokenExchangeBody({ ...base, clientSecret: '' }));
    expect(body.has('client_secret')).toBe(false);
  });

  it('refuses a non-loopback redirect', () => {
    expect(() =>
      buildTokenExchangeBody({ ...base, redirectUri: 'https://evil.example/cb' }),
    ).toThrow(/loopback/i);
  });

  it('refuses an empty verifier (that would silently downgrade PKCE)', () => {
    expect(() => buildTokenExchangeBody({ ...base, codeVerifier: '' })).toThrow(/verifier/i);
  });

  it('refuses an empty code', () => {
    expect(() => buildTokenExchangeBody({ ...base, code: '' })).toThrow(/code/i);
  });

  it('refuses an empty client id', () => {
    expect(() => buildTokenExchangeBody({ ...base, clientId: '' })).toThrow(/clientId/i);
  });

  it('NEVER carries the verifier or secret in a loggable joined form', () => {
    // The body is a URLSearchParams string that a naive error path could log. It
    // legitimately contains the secret, so callers must treat it as secret — this
    // test pins that it is a plain body string and NOT wrapped into a URL that
    // could end up in a browser history or an OS process list.
    expect(buildTokenExchangeBody(base)).not.toMatch(/^https?:\/\//);
  });
});
