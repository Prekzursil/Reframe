// updateVerify.test.ts — WU-U2 authenticity verifier, exhaustive to 100% branch.
//
// Real Node crypto is used end-to-end: each round-trip generates an EPHEMERAL
// Ed25519 keypair, signs the SAME `buildSignedMessage(version, sha512(bytes))` the
// app verifies, and checks the pure verifier accepts/rejects. No private key ever
// lives in the repo — the embedded PUBLIC keys are only asserted parseable + used
// as the "wrong key" for rejection paths. Fixtures cover: valid, tampered file
// (digest mismatch), wrong version, downgrade, missing/empty sig, malformed sig,
// wrong key, rotation (next-key accepted), read-throws, and fetch-throws.
import { generateKeyPairSync, sign as cryptoSign, createHash, type KeyObject } from 'node:crypto';
import { describe, it, expect, vi } from 'vitest';

import {
  EMBEDDED_UPDATE_PUBLIC_KEYS,
  UPDATE_MESSAGE_CONTEXT,
  UPDATE_RELEASE_BASE_URL,
  buildSignedMessage,
  isNotDowngrade,
  sha512Base64,
  signatureAssetUrl,
  verifyDownloadedUpdate,
  verifyEd25519,
  type VerifyDownloadedUpdateDeps,
} from './updateVerify';

/** An ephemeral Ed25519 keypair with its public key already exported to PEM SPKI. */
function makeKeypair(): { privateKey: KeyObject; pubPem: string } {
  const { publicKey, privateKey } = generateKeyPairSync('ed25519');
  return { privateKey, pubPem: publicKey.export({ type: 'spki', format: 'pem' }).toString() };
}

/** Sign `version‖sha512(bytes)` with `privateKey`, returning the base64 signature. */
function signUpdate(privateKey: KeyObject, version: string, bytes: Buffer): string {
  const message = buildSignedMessage(version, sha512Base64(bytes));
  return cryptoSign(null, Buffer.from(message, 'utf8'), privateKey).toString('base64');
}

const INSTALLER = 'C:\\cache\\media-studio-1.5.0-win-x64.exe';

/** Assemble {@link VerifyDownloadedUpdateDeps} with sensible defaults per test. */
function makeDeps(over: Partial<VerifyDownloadedUpdateDeps> = {}): VerifyDownloadedUpdateDeps {
  return {
    version: '1.5.0',
    currentVersion: '1.4.1',
    downloadedFile: INSTALLER,
    readFile: async () => Buffer.from('installer-bytes'),
    fetchSignature: async () => '',
    ...over,
  };
}

describe('sha512Base64', () => {
  it('matches node crypto SHA-512 base64 of the same bytes', () => {
    const bytes = Buffer.from('hello reframe');
    const expected = createHash('sha512').update(bytes).digest('base64');
    expect(sha512Base64(bytes)).toBe(expected);
  });
});

describe('buildSignedMessage — PINNED wire format (build/sign-release.mjs MUST match)', () => {
  it('is the domain-separated, newline-delimited version‖digest binding', () => {
    expect(UPDATE_MESSAGE_CONTEXT).toBe('reframe:update:v1');
    expect(buildSignedMessage('1.5.0', 'DIGEST==')).toBe('reframe:update:v1\n1.5.0\nDIGEST==');
  });
});

describe('signatureAssetUrl', () => {
  it('builds the release .sig URL under the default GitHub base', () => {
    expect(signatureAssetUrl('1.5.0', 'media-studio-1.5.0-win-x64.exe')).toBe(
      `${UPDATE_RELEASE_BASE_URL}/v1.5.0/media-studio-1.5.0-win-x64.exe.sig`,
    );
  });

  it('honours an explicit base and percent-encodes hostile path segments', () => {
    expect(signatureAssetUrl('1.0/../evil', 'a b/c.exe', 'https://example.test/dl')).toBe(
      'https://example.test/dl/v1.0%2F..%2Fevil/a%20b%2Fc.exe.sig',
    );
  });
});

describe('EMBEDDED_UPDATE_PUBLIC_KEYS', () => {
  it('are two distinct, parseable Ed25519 public keys (current + next)', () => {
    expect(EMBEDDED_UPDATE_PUBLIC_KEYS).toHaveLength(2);
    for (const pem of EMBEDDED_UPDATE_PUBLIC_KEYS) {
      // A round-trip sign under an ephemeral key must NOT verify against an embedded
      // key (proves each is a real, independent Ed25519 key, not the test's own).
      const { privateKey } = makeKeypair();
      const sig = signUpdate(privateKey, '1.5.0', Buffer.from('x'));
      const message = buildSignedMessage('1.5.0', sha512Base64(Buffer.from('x')));
      expect(verifyEd25519(message, sig, [pem])).toBe(false);
    }
    expect(EMBEDDED_UPDATE_PUBLIC_KEYS[0]).not.toBe(EMBEDDED_UPDATE_PUBLIC_KEYS[1]);
  });
});

describe('verifyEd25519', () => {
  it('accepts a signature from the (single) matching key', () => {
    const { privateKey, pubPem } = makeKeypair();
    const bytes = Buffer.from('a');
    const message = buildSignedMessage('1.5.0', sha512Base64(bytes));
    expect(verifyEd25519(message, signUpdate(privateKey, '1.5.0', bytes), [pubPem])).toBe(true);
  });

  it('accepts a signature from the SECOND (rotation) key in the list', () => {
    const wrong = makeKeypair();
    const right = makeKeypair();
    const bytes = Buffer.from('a');
    const message = buildSignedMessage('1.5.0', sha512Base64(bytes));
    const sig = signUpdate(right.privateKey, '1.5.0', bytes);
    expect(verifyEd25519(message, sig, [wrong.pubPem, right.pubPem])).toBe(true);
  });

  it('rejects a valid signature made by a key NOT in the list', () => {
    const signer = makeKeypair();
    const other = makeKeypair();
    const bytes = Buffer.from('a');
    const message = buildSignedMessage('1.5.0', sha512Base64(bytes));
    const sig = signUpdate(signer.privateKey, '1.5.0', bytes);
    expect(verifyEd25519(message, sig, [other.pubPem])).toBe(false);
  });

  it('rejects a malformed (wrong-length) signature without throwing', () => {
    const { pubPem } = makeKeypair();
    expect(verifyEd25519('msg', 'AA==', [pubPem])).toBe(false);
  });

  it('rejects when a candidate public key is not valid PEM without throwing', () => {
    const { privateKey } = makeKeypair();
    const bytes = Buffer.from('a');
    const message = buildSignedMessage('1.5.0', sha512Base64(bytes));
    const sig = signUpdate(privateKey, '1.5.0', bytes);
    expect(
      verifyEd25519(message, sig, ['-----BEGIN PUBLIC KEY-----\nnope\n-----END PUBLIC KEY-----']),
    ).toBe(false);
  });
});

describe('isNotDowngrade — the signed-downgrade-replay guard', () => {
  it('accepts a strictly newer core version', () => {
    expect(isNotDowngrade('1.5.0', '1.4.1')).toBe(true);
    expect(isNotDowngrade('2.0.0', '1.9.9')).toBe(true);
  });

  it('rejects an older core version', () => {
    expect(isNotDowngrade('1.4.0', '1.5.0')).toBe(false);
    expect(isNotDowngrade('1.4.1', '1.4.2')).toBe(false);
  });

  it('rejects the SAME version (no strict increase)', () => {
    expect(isNotDowngrade('1.5.0', '1.5.0')).toBe(false);
  });

  it('treats a final release as newer than its prerelease and vice-versa', () => {
    expect(isNotDowngrade('1.5.0', '1.5.0-beta.1')).toBe(true);
    expect(isNotDowngrade('1.5.0-beta.1', '1.5.0')).toBe(false);
  });

  it('orders two prereleases of the same core lexically', () => {
    expect(isNotDowngrade('1.5.0-beta.2', '1.5.0-beta.1')).toBe(true);
    expect(isNotDowngrade('1.5.0-alpha', '1.5.0-beta')).toBe(false);
    expect(isNotDowngrade('1.5.0-rc.1', '1.5.0-rc.1')).toBe(false);
  });

  it('handles unequal-length cores and build metadata', () => {
    expect(isNotDowngrade('1.5.1', '1.5')).toBe(true); // current has fewer parts
    expect(isNotDowngrade('1.5', '1.5.1')).toBe(false); // candidate has fewer parts
    expect(isNotDowngrade('1.5.0+build9', '1.5.0')).toBe(false); // build metadata is not precedence
  });

  it('treats a non-numeric core identifier as zero', () => {
    expect(isNotDowngrade('abc', '1.0.0')).toBe(false); // parseInt('abc') -> NaN -> 0
    expect(isNotDowngrade('1.0.0', 'abc')).toBe(true);
  });
});

describe('verifyDownloadedUpdate — the download→install authenticity gate', () => {
  it('accepts a correctly signed, newer update', async () => {
    const { privateKey, pubPem } = makeKeypair();
    const bytes = Buffer.from('the-real-installer');
    const log = vi.fn();
    const res = await verifyDownloadedUpdate(
      makeDeps({
        readFile: async () => bytes,
        fetchSignature: async () => signUpdate(privateKey, '1.5.0', bytes),
        publicKeys: [pubPem],
        log,
      }),
    );
    expect(res).toEqual({ ok: true });
    expect(log).not.toHaveBeenCalled(); // success never logs a rejection
  });

  it('rejects a blank version', async () => {
    const res = await verifyDownloadedUpdate(makeDeps({ version: '' }));
    expect(res).toEqual({ ok: false, reason: 'missing update version or downloaded file' });
  });

  it('rejects a blank downloaded file', async () => {
    const res = await verifyDownloadedUpdate(makeDeps({ downloadedFile: '' }));
    expect(res).toEqual({ ok: false, reason: 'missing update version or downloaded file' });
  });

  it('rejects a downgrade and logs the reason', async () => {
    const log = vi.fn();
    const res = await verifyDownloadedUpdate(
      makeDeps({ version: '1.4.0', currentVersion: '1.5.0', log }),
    );
    expect(res.ok).toBe(false);
    expect(res).toMatchObject({ reason: expect.stringContaining('refusing downgrade') });
    expect(log).toHaveBeenCalledWith(expect.stringContaining('refusing downgrade'));
  });

  it('rejects when the downloaded file cannot be read', async () => {
    const res = await verifyDownloadedUpdate(
      makeDeps({
        readFile: async () => {
          throw new Error('EACCES');
        },
      }),
    );
    expect(res).toMatchObject({
      ok: false,
      reason: expect.stringContaining('cannot read downloaded update'),
    });
    expect(res).toMatchObject({ reason: expect.stringContaining('EACCES') });
  });

  it('rejects when the signature cannot be fetched (non-Error throw covered)', async () => {
    const res = await verifyDownloadedUpdate(
      makeDeps({
        readFile: async () => Buffer.from('bytes'),
        fetchSignature: async () => {
          throw '404 Not Found';
        },
      }),
    );
    expect(res).toMatchObject({
      ok: false,
      reason: expect.stringContaining('cannot fetch update signature'),
    });
    expect(res).toMatchObject({ reason: expect.stringContaining('404 Not Found') });
  });

  it('rejects an empty signature (no .sig published)', async () => {
    const res = await verifyDownloadedUpdate(
      makeDeps({ readFile: async () => Buffer.from('bytes'), fetchSignature: async () => '' }),
    );
    expect(res).toEqual({ ok: false, reason: 'update signature is empty (no .sig published?)' });
  });

  it('rejects a TAMPERED file — signature valid but bytes swapped after signing', async () => {
    const { privateKey, pubPem } = makeKeypair();
    const original = Buffer.from('original-installer');
    const tampered = Buffer.from('MALICIOUS-installer');
    const res = await verifyDownloadedUpdate(
      makeDeps({
        readFile: async () => tampered, // what is on disk now
        fetchSignature: async () => signUpdate(privateKey, '1.5.0', original), // signed the original
        publicKeys: [pubPem],
      }),
    );
    expect(res).toEqual({
      ok: false,
      reason: 'signature does not match the embedded update key',
    });
  });

  it('rejects a WRONG-VERSION signature — proves the version binding', async () => {
    const { privateKey, pubPem } = makeKeypair();
    const bytes = Buffer.from('installer');
    const res = await verifyDownloadedUpdate(
      makeDeps({
        version: '1.5.0',
        readFile: async () => bytes,
        fetchSignature: async () => signUpdate(privateKey, '9.9.9', bytes), // signed a different version
        publicKeys: [pubPem],
      }),
    );
    expect(res).toMatchObject({ ok: false, reason: expect.stringContaining('does not match') });
  });

  it('rejects a valid signature from a key that is NOT embedded (default keys, no log)', async () => {
    const { privateKey } = makeKeypair();
    const bytes = Buffer.from('installer');
    // No publicKeys override -> falls back to EMBEDDED_UPDATE_PUBLIC_KEYS; no log -> default noop.
    const res = await verifyDownloadedUpdate(
      makeDeps({
        readFile: async () => bytes,
        fetchSignature: async () => signUpdate(privateKey, '1.5.0', bytes),
      }),
    );
    expect(res).toMatchObject({ ok: false, reason: expect.stringContaining('does not match') });
  });
});
