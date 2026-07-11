// updateVerify.ts — WU-U2: AUTHENTICITY gate for the in-place auto-update.
//
// THREAT MODEL: electron-updater already proves INTEGRITY (it checks the SHA-512
// block-map in `latest.yml`), but NOT AUTHENTICITY — a party who controls the
// update feed can serve their own `latest.yml` + installer and electron-updater
// would happily install it. Reframe ships UNSIGNED (no Authenticode/EV cert), so
// there is no OS-level publisher check either. This module closes that gap with a
// FREE, offline, zero-runtime-dependency authenticity check:
//
//   * At release time a human/CI step signs `version‖sha512(installer)` with an
//     OFFLINE Ed25519 private key and publishes the detached signature as a
//     `<installer>.sig` release asset (see build/sign-release.mjs).
//   * The shipping app embeds the matching Ed25519 PUBLIC key(s) below and, before
//     it will apply a downloaded update, recomputes sha512(installer), fetches the
//     `.sig`, rebuilds the signed message, and verifies it with Node's built-in
//     `crypto` (Ed25519 `crypto.verify(null, …)`). A compromised feed cannot forge
//     a valid signature over `version‖sha512` without the offline private key.
//
// The message binds BOTH the version AND the file digest, so it blocks tampering
// (wrong digest) AND downgrade replay of an old-but-validly-signed release (the
// {@link isNotDowngrade} guard). This module is a PURE verifier: it imports only
// `node:crypto` + `node:path`, takes ALL I/O (file read, signature fetch) as
// injected deps, and NEVER throws — every failure is a typed `{ ok:false, reason }`
// so the caller can gate the install without a try/catch. That keeps it trivially
// unit-testable to the mandatory 100% branch bar, the same injected-fake seam used
// by keystore.ts / updater.ts.
import { createHash, createPublicKey, verify as cryptoVerify } from 'node:crypto';
import { basename } from 'node:path';

/**
 * Domain-separation prefix baked into every signed message. Prevents a signature
 * produced for some OTHER Ed25519 protocol (that happened to sign the same bytes)
 * from being replayed as a valid Reframe update signature. Bump the `v1` suffix if
 * the signed-message format ever changes.
 */
export const UPDATE_MESSAGE_CONTEXT = 'reframe:update:v1';

/**
 * The Ed25519 PUBLIC keys (PEM SPKI) the app accepts an update signature from.
 * Ordered `[current, next]`: BOTH are accepted so a release can be signed by a
 * pre-provisioned rotation key WITHOUT a code change — sign the next release with
 * `next`, ship it, then drop the retired `current` in a later build. The matching
 * PRIVATE keys live OFFLINE (never in this repo); only the public halves are here,
 * and a public key is safe to publish — that is the whole point of asymmetric
 * signing.
 *
 * SECURITY NOTE (draft): these two keys were generated for this proof-of-concept
 * PR. Before the first PRODUCTION signed release, regenerate a fresh keypair on an
 * offline machine (`node build/sign-release.mjs --generate-keypair`) whose private
 * half has NEVER touched a shared/agent environment, and replace the entries below.
 */
export const EMBEDDED_UPDATE_PUBLIC_KEYS: readonly string[] = [
  // current
  '-----BEGIN PUBLIC KEY-----\n' +
    'MCowBQYDK2VwAyEAvxb7zIqSUpXa94lNtkp+pY4IhPK+Mm+qq3NJq9pKD0w=\n' +
    '-----END PUBLIC KEY-----\n',
  // next (rotation)
  '-----BEGIN PUBLIC KEY-----\n' +
    'MCowBQYDK2VwAyEANt9M1z7diybhHYnUBJx0P/x8AIDi65USJ+jXkmWF7qk=\n' +
    '-----END PUBLIC KEY-----\n',
];

/** GitHub Releases asset base URL Reframe publishes installers + `.sig`s under. */
export const UPDATE_RELEASE_BASE_URL = 'https://github.com/Prekzursil/Reframe/releases/download';

/** Verifier outcome — a typed union so the caller gates the install without a try/catch. */
export type UpdateVerifyResult = { ok: true } | { ok: false; reason: string };

/** Wiring {@link verifyDownloadedUpdate} needs; ALL I/O is injected for testability. */
export interface VerifyDownloadedUpdateDeps {
  /** The candidate update's version (from electron-updater's `update-downloaded`). */
  version: string;
  /** The running app's version (`app.getVersion()`), for the downgrade guard. */
  currentVersion: string;
  /** Absolute local path electron-updater wrote the installer to. */
  downloadedFile: string;
  /** Read the downloaded installer's bytes (main binds `node:fs/promises` readFile). */
  readFile: (path: string) => Promise<Buffer>;
  /** Fetch the detached `.sig` (base64) for `{version, fileName}` (main binds the net GET). */
  fetchSignature: (args: { version: string; fileName: string }) => Promise<string>;
  /** Ed25519 keys to accept; defaults to {@link EMBEDDED_UPDATE_PUBLIC_KEYS}. */
  publicKeys?: readonly string[];
  /** Optional diagnostic logger (a rejection reason is invisible in a packaged build otherwise). */
  log?: (message: string) => void;
}

/** SHA-512 of `bytes`, base64-encoded — the file digest half of the signed message. */
export function sha512Base64(bytes: Buffer): string {
  return createHash('sha512').update(bytes).digest('base64');
}

/**
 * The exact bytes an update signature is computed over: a domain-separated,
 * newline-delimited binding of the version to the file digest. Both the release
 * signer (build/sign-release.mjs) and this verifier MUST build it identically —
 * the exact format is pinned by updateVerify.test.ts so any drift fails the gate.
 */
export function buildSignedMessage(version: string, sha512Digest: string): string {
  return `${UPDATE_MESSAGE_CONTEXT}\n${version}\n${sha512Digest}`;
}

/** The GitHub Releases URL of the `.sig` asset for `fileName` at `version`'s tag. */
export function signatureAssetUrl(
  version: string,
  fileName: string,
  base: string = UPDATE_RELEASE_BASE_URL,
): string {
  // encodeURIComponent both path segments so a hostile feed value cannot break out
  // of the release path (no `..`/`/`/scheme injection) — the base host stays fixed.
  return `${base}/v${encodeURIComponent(version)}/${encodeURIComponent(fileName)}.sig`;
}

/**
 * True iff `signatureB64` is a valid Ed25519 signature of `message` under ANY of
 * `publicKeys` (rotation: current OR next). NEVER throws — a malformed key or
 * signature for one candidate is caught and the next is tried; an all-miss returns
 * false. Ed25519 verifies the message DIRECTLY (no pre-hash), hence `verify(null, …)`.
 */
export function verifyEd25519(
  message: string,
  signatureB64: string,
  publicKeys: readonly string[],
): boolean {
  const data = Buffer.from(message, 'utf8');
  const signature = Buffer.from(signatureB64, 'base64');
  for (const pem of publicKeys) {
    try {
      if (cryptoVerify(null, data, createPublicKey(pem), signature)) {
        return true;
      }
    } catch {
      // Malformed candidate key or signature length — reject this key, try the next.
    }
  }
  return false;
}

/** Numeric `[major, minor, patch, …]` core of a version (before any `-pre`/`+build`). */
function coreParts(version: string): number[] {
  const core = version.split('+', 1)[0].split('-', 1)[0];
  return core.split('.').map((part) => {
    const n = Number.parseInt(part, 10);
    return Number.isNaN(n) ? 0 : n;
  });
}

/** The prerelease tag (after `-`, before `+`), or `''` for a final release. */
function prereleaseTag(version: string): string {
  const beforeBuild = version.split('+', 1)[0];
  const dash = beforeBuild.indexOf('-');
  return dash === -1 ? '' : beforeBuild.slice(dash + 1);
}

/** Semver-style compare: -1 if `a<b`, 0 if equal, 1 if `a>b` (release > its prerelease). */
function compareSemver(a: string, b: string): number {
  const ca = coreParts(a);
  const cb = coreParts(b);
  const len = Math.max(ca.length, cb.length);
  for (let i = 0; i < len; i += 1) {
    const diff = (ca[i] ?? 0) - (cb[i] ?? 0);
    if (diff !== 0) {
      return diff < 0 ? -1 : 1;
    }
  }
  const pa = prereleaseTag(a);
  const pb = prereleaseTag(b);
  if (pa === pb) {
    return 0;
  }
  if (pa === '') {
    return 1; // a is a final release, b is a prerelease -> a is newer
  }
  if (pb === '') {
    return -1; // b is a final release, a is a prerelease -> b is newer
  }
  return pa < pb ? -1 : 1; // both prerelease -> lexical order
}

/**
 * True iff `candidate` is STRICTLY newer than `current`. The downgrade guard: a
 * compromised feed could replay an OLD release that WAS validly signed with the
 * real key (so its signature verifies) to re-expose a since-patched vuln — the
 * signature alone cannot stop that, only this version check can.
 */
export function isNotDowngrade(candidate: string, current: string): boolean {
  return compareSemver(candidate, current) > 0;
}

/** Extract a human-readable message from an unknown thrown value. */
function errText(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

/** Build a rejection result, logging the reason (invisible in a packaged build otherwise). */
function reject(reason: string, log: (message: string) => void): UpdateVerifyResult {
  log(`[updateVerify] reject: ${reason}`);
  return { ok: false, reason };
}

/**
 * Verify a DOWNLOADED update's authenticity before it is allowed to install.
 *
 * Steps (each a fail-closed gate; never throws):
 *   1. Shape guard — a blank version or file path is rejected outright.
 *   2. Downgrade guard — {@link isNotDowngrade} blocks a signed-but-older replay.
 *   3. Read the installer bytes + fetch its detached `.sig` (both injected I/O).
 *   4. Recompute sha512, rebuild `version‖sha512`, and Ed25519-verify against the
 *      embedded key(s). A mismatch (tampered file, forged/absent signature, wrong
 *      key) is rejected.
 *
 * Returns `{ ok:true }` ONLY when every gate passes; otherwise `{ ok:false, reason }`.
 */
export async function verifyDownloadedUpdate(
  deps: VerifyDownloadedUpdateDeps,
): Promise<UpdateVerifyResult> {
  const { version, currentVersion, downloadedFile } = deps;
  const publicKeys = deps.publicKeys ?? EMBEDDED_UPDATE_PUBLIC_KEYS;
  const log = deps.log ?? ((): void => {});

  if (version === '' || downloadedFile === '') {
    return reject('missing update version or downloaded file', log);
  }
  if (!isNotDowngrade(version, currentVersion)) {
    return reject(`refusing downgrade (candidate ${version} <= current ${currentVersion})`, log);
  }

  const fileName = basename(downloadedFile);

  let bytes: Buffer;
  try {
    bytes = await deps.readFile(downloadedFile);
  } catch (err) {
    return reject(`cannot read downloaded update: ${errText(err)}`, log);
  }

  let signatureB64: string;
  try {
    signatureB64 = await deps.fetchSignature({ version, fileName });
  } catch (err) {
    return reject(`cannot fetch update signature: ${errText(err)}`, log);
  }
  if (signatureB64 === '') {
    return reject('update signature is empty (no .sig published?)', log);
  }

  const message = buildSignedMessage(version, sha512Base64(bytes));
  if (!verifyEd25519(message, signatureB64, publicKeys)) {
    return reject('signature does not match the embedded update key', log);
  }
  return { ok: true };
}
