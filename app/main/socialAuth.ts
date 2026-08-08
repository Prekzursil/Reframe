// socialAuth.ts — C14 desktop OAuth for social publishing: PKCE, the loopback
// redirect, and the two pure URL/body builders.
//
// WHY A DESKTOP LOOPBACK FLOW AT ALL
// ----------------------------------
// Reframe is a local app with no server and no public domain, so it cannot host an
// https OAuth callback. The only flow available to it is the installed-app pattern:
// open the provider's consent page in the OS browser, listen on an ephemeral
// loopback port, and receive the authorization code there. Both platforms wired
// here document that flow explicitly:
//
//   * Google/YouTube — accepts `http://127.0.0.1:<port>` (and `http://[::1]:<port>`)
//     for a Desktop-app client and supports PKCE S256. The old copy/paste "OOB"
//     redirect is retired, so loopback is the only remaining option.
//     https://developers.google.com/identity/protocols/oauth2/native-app
//   * TikTok — its DESKTOP configuration permits only `localhost` / `127.0.0.1` as
//     the redirect host and REQUIRES PKCE S256. (It is the *web* configuration that
//     demands an absolute https URI — reading only that page would wrongly rule
//     TikTok out for a desktop app.)
//     https://developers.tiktok.com/doc/login-kit-desktop
//
// Instagram and Facebook are DELIBERATELY absent from OAUTH_ENDPOINTS. Meta's login
// does not offer a loopback desktop redirect, and Instagram's API additionally
// refuses a personal account outright (see the sidecar capability matrix in
// `media_studio/features/social_publish.py`). An endpoint entry we cannot actually
// complete would be a stub that lies about being wired, so there is none.
//
// SECRETS
// -------
// Nothing here reads, writes, or persists a credential: it is pure string work over
// values the caller supplies. Two rules are enforced structurally rather than by
// convention, because each is a single mistake away from account takeover:
//
//   1. Every redirect URI that reaches an authorize URL or a token exchange is
//      re-validated as LOOPBACK (`assertLoopback`). The authorization code is
//      delivered to that host; pointing it anywhere else hands the code away.
//      The check parses the URI and compares the resolved HOSTNAME, so a
//      `127.0.0.1.evil.com` suffix and a `127.0.0.1@evil.example` userinfo trick
//      both fail — a `startsWith`/`includes` check passes both.
//   2. The authorize URL never carries the client secret. It is handed to the OS
//      browser, so it lands in browser history, the OS "recent" lists, and any
//      shell/process log along the way. Only the token exchange (an https POST
//      body) may carry it.
import { timingSafeEqual } from 'node:crypto';

/** The only PKCE method used. `plain` would put the verifier in the browser URL. */
export const PKCE_METHOD = 'S256';

/** Bytes of entropy behind a verifier: 32 bytes -> 43 base64url chars (the RFC floor). */
export const VERIFIER_BYTES = 32;

/** The loopback path the callback listener serves. */
export const CALLBACK_PATH = '/oauth/callback';

/** Hostnames that cannot leave this machine. Compared to the RESOLVED hostname. */
const LOOPBACK_HOSTS: ReadonlySet<string> = new Set(['127.0.0.1', 'localhost', '[::1]', '::1']);

/** One platform's OAuth endpoints + the scopes Reframe asks for. */
export interface OauthEndpoint {
  /** Matches the sidecar capability-matrix id. */
  platform: string;
  authorizeUrl: string;
  tokenUrl: string;
  /** The narrowest scope set that permits an upload — never a blanket scope. */
  scopes: readonly string[];
  /** The doc this entry was read from (2026-08-08). */
  docUrl: string;
}

export const OAUTH_ENDPOINTS: Readonly<Record<string, OauthEndpoint>> = {
  youtube: {
    platform: 'youtube',
    authorizeUrl: 'https://accounts.google.com/o/oauth2/v2/auth',
    tokenUrl: 'https://oauth2.googleapis.com/token',
    // `youtube.upload` is upload-only: it cannot read or delete the user's
    // existing videos, which a blanket `youtube` scope would allow.
    scopes: ['https://www.googleapis.com/auth/youtube.upload'],
    docUrl: 'https://developers.google.com/identity/protocols/oauth2/native-app',
  },
  tiktok: {
    platform: 'tiktok',
    authorizeUrl: 'https://www.tiktok.com/v2/auth/authorize/',
    tokenUrl: 'https://open.tiktokapis.com/v2/oauth/token/',
    // `video.publish` is direct-post; `user.info.basic` is what identifies the
    // connected account in the UI. `video.upload` (draft-only) is deliberately not
    // requested here — a draft the user must finish inside the TikTok app is not
    // the "direct publish" C14 asks for.
    scopes: ['user.info.basic', 'video.publish'],
    docUrl: 'https://developers.tiktok.com/doc/login-kit-desktop',
  },
};

/** base64url WITHOUT padding — `=`, `+`, `/` are not RFC 7636 unreserved chars. */
function base64Url(bytes: Buffer): string {
  return bytes.toString('base64').replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

/**
 * A fresh PKCE code verifier (RFC 7636 §4.1).
 *
 * `randomBytes` is injected so tests are deterministic without stubbing the crypto
 * module; production passes `node:crypto`'s `randomBytes`.
 */
export function createVerifier(randomBytes: (size: number) => Buffer): string {
  return base64Url(randomBytes(VERIFIER_BYTES));
}

/**
 * The S256 code challenge for `verifier` (RFC 7636 §4.2).
 *
 * `sha256` is injected for the same reason. Verified against the RFC's published
 * Appendix-B vector in the unit test, so the hash/encoding pairing is anchored to
 * the spec rather than to this implementation.
 */
export function challengeFor(verifier: string, sha256: (input: string) => Buffer): string {
  return base64Url(sha256(verifier));
}

/** The loopback redirect URI the callback listener binds. */
export function loopbackRedirectUri(port: number): string {
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    throw new Error(`socialAuth: port must be an integer in 1-65535, got ${port}`);
  }
  return `http://127.0.0.1:${port}${CALLBACK_PATH}`;
}

/**
 * Whether `uri` delivers the authorization code to THIS machine.
 *
 * Parses the URI and tests the RESOLVED hostname against an exact allowlist, so
 * neither a suffix (`127.0.0.1.evil.com`) nor a userinfo prefix
 * (`127.0.0.1@evil.example`) can pass — both defeat a substring check. An
 * unparseable URI is denied rather than defaulting to allow.
 */
export function isLoopbackRedirectUri(uri: string): boolean {
  let parsed: URL;
  try {
    parsed = new URL(uri);
  } catch {
    return false;
  }
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
    return false;
  }
  return LOOPBACK_HOSTS.has(parsed.hostname);
}

function assertLoopback(redirectUri: string): void {
  if (!isLoopbackRedirectUri(redirectUri)) {
    throw new Error(
      'socialAuth: redirectUri must be a loopback address; refusing to send the auth code off-box',
    );
  }
}

function assertPresent(value: string, field: string): string {
  const trimmed = value.trim();
  if (trimmed === '') {
    throw new Error(`socialAuth: ${field} is required`);
  }
  return trimmed;
}

/** The endpoint set for `platform`, or a throw naming the desktop-flow limitation. */
export function oauthEndpoint(platform: string): OauthEndpoint {
  const endpoint = OAUTH_ENDPOINTS[platform];
  if (endpoint === undefined) {
    throw new Error(
      `socialAuth: ${platform} has no desktop loopback OAuth flow, so Reframe cannot connect it from this computer`,
    );
  }
  return endpoint;
}

export interface AuthorizeUrlOptions {
  platform: string;
  clientId: string;
  redirectUri: string;
  /** Opaque per-attempt CSRF value; echoed back on the callback. */
  state: string;
  codeChallenge: string;
}

/**
 * The consent URL to open in the OS browser.
 *
 * Carries the PKCE challenge, the state, and the loopback redirect — and, by
 * construction, NO client secret (see the module note: this URL is logged by the
 * browser and the OS).
 */
export function buildAuthorizeUrl(options: AuthorizeUrlOptions): string {
  const endpoint = oauthEndpoint(options.platform);
  assertLoopback(options.redirectUri);
  const clientId = assertPresent(options.clientId, 'clientId');
  const state = assertPresent(options.state, 'state');
  const codeChallenge = assertPresent(options.codeChallenge, 'codeChallenge');

  const url = new URL(endpoint.authorizeUrl);
  url.searchParams.set('client_id', clientId);
  url.searchParams.set('redirect_uri', options.redirectUri);
  url.searchParams.set('response_type', 'code');
  url.searchParams.set('scope', endpoint.scopes.join(' '));
  url.searchParams.set('state', state);
  url.searchParams.set('code_challenge', codeChallenge);
  url.searchParams.set('code_challenge_method', PKCE_METHOD);
  return url.toString();
}

/** Constant-time state comparison (length is the only thing it leaks). */
function statesMatch(actual: string, expected: string): boolean {
  const a = Buffer.from(actual, 'utf8');
  const b = Buffer.from(expected, 'utf8');
  return a.length === b.length && timingSafeEqual(a, b);
}

/**
 * Extract the authorization code from a callback URL, validating `state` first.
 *
 * `rawUrl` must be ABSOLUTE. Node's http server hands the handler a path+query, so
 * the listener is responsible for resolving it against the redirect URI before
 * calling this (`new URL(req.url, redirectUri).toString()`).
 *
 * Order matters: a provider ERROR is surfaced before the state check, because a
 * user who clicked "deny" gets a callback that may carry no state at all, and
 * reporting "state missing" there would hide the real, actionable reason.
 *
 * The thrown message never echoes the EXPECTED state — that value is a live CSRF
 * secret for the in-flight attempt and the message can reach a log.
 */
export function parseCallbackUrl(rawUrl: string, expectedState: string): { code: string } {
  let parsed: URL;
  try {
    parsed = new URL(rawUrl);
  } catch {
    throw new Error('socialAuth: the OAuth callback URL could not be parsed');
  }
  const params = parsed.searchParams;

  const error = params.get('error');
  if (error !== null) {
    // The provider's own machine-readable reason (e.g. `access_denied`), which the
    // UI shows so the user knows the sign-in was declined rather than broken.
    throw new Error(`socialAuth: the platform refused the connection (${error})`);
  }

  const state = params.get('state');
  if (state === null || !statesMatch(state, expectedState)) {
    throw new Error(
      'socialAuth: the OAuth callback state did not match this sign-in attempt; discarding it',
    );
  }

  const code = params.get('code');
  if (code === null || code === '') {
    throw new Error('socialAuth: the OAuth callback carried no authorization code');
  }
  return { code };
}

export interface TokenExchangeOptions {
  platform: string;
  clientId: string;
  /** `''` when the user's OAuth app has no secret — the field is then OMITTED. */
  clientSecret: string;
  code: string;
  codeVerifier: string;
  redirectUri: string;
}

/**
 * The `application/x-www-form-urlencoded` body for the code->token exchange.
 *
 * Returns a BODY string (never a URL): the secret must travel in a POST body over
 * https, not in a query string that a proxy or an access log would record.
 *
 * An empty `clientSecret` omits the field entirely rather than sending
 * `client_secret=`, which some token endpoints treat as a malformed credential
 * instead of an absent one.
 */
export function buildTokenExchangeBody(options: TokenExchangeOptions): string {
  oauthEndpoint(options.platform);
  assertLoopback(options.redirectUri);
  const clientId = assertPresent(options.clientId, 'clientId');
  const code = assertPresent(options.code, 'code');
  const codeVerifier = assertPresent(options.codeVerifier, 'codeVerifier');

  const body = new URLSearchParams({
    grant_type: 'authorization_code',
    client_id: clientId,
    code,
    code_verifier: codeVerifier,
    redirect_uri: options.redirectUri,
  });
  if (options.clientSecret.trim() !== '') {
    body.set('client_secret', options.clientSecret.trim());
  }
  return body.toString();
}
