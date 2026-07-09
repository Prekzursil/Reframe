// keystore.test.ts — WU-D2 DPAPI keystore + one-time plaintext migration.
//
// safeStorage is faked with a REVERSIBLE, deterministic transform so encrypt ->
// base64 -> decrypt round-trips without a real OS keychain. The filesystem is a
// per-test tmp dir. The headline assertion (§D2 acceptance a): after a migration
// ZERO plaintext key bytes remain across settings.json + its .tmp + backups.
import { mkdtempSync, mkdirSync, readFileSync, writeFileSync, existsSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import {
  BASIC_TEXT_BACKEND,
  KEYSTORE_FILENAME,
  KeystoreUnavailableError,
  SESSION_ONLY_BANNER,
  type SafeStorageLike,
  decryptFromBase64,
  encryptToBase64,
  extractPlaintextKeys,
  keystorePathFor,
  loadDecryptedKeys,
  migrateLegacyPlaintextKeys,
  priorCopies,
  saveDecryptedKeys,
  secureStatus,
  selectedBackend,
  shredFile,
  stripKeysFromSettings,
} from './keystore';

/** A reversible fake: ciphertext = "enc:" + plaintext (survives a base64 round-trip). */
function makeSafeStorage(
  opts: { available?: boolean; backend?: string | null | (() => string) } = {},
): SafeStorageLike {
  const available = opts.available ?? true;
  const store: SafeStorageLike = {
    isEncryptionAvailable: () => available,
    encryptString: (plaintext: string) => Buffer.from(`enc:${plaintext}`, 'utf8'),
    decryptString: (encrypted: Buffer) => encrypted.toString('utf8').replace(/^enc:/, ''),
  };
  if (opts.backend !== undefined) {
    store.getSelectedStorageBackend =
      typeof opts.backend === 'function'
        ? (opts.backend as () => string)
        : () => opts.backend as string;
  }
  return store;
}

let dir: string;
beforeEach(() => {
  dir = mkdtempSync(join(tmpdir(), 'keystore-test-'));
});
afterEach(() => {
  rmSync(dir, { recursive: true, force: true });
});

const settingsPath = (): string => join(dir, 'settings.json');
const keystorePath = (): string => join(dir, KEYSTORE_FILENAME);

describe('selectedBackend', () => {
  it('returns null when the platform does not implement the query', () => {
    expect(selectedBackend(makeSafeStorage())).toBeNull();
  });
  it('returns the backend string on Linux', () => {
    expect(selectedBackend(makeSafeStorage({ backend: 'gnome_libsecret' }))).toBe(
      'gnome_libsecret',
    );
  });
  it('returns null when the query throws (win/mac not implemented)', () => {
    const throwing = (): string => {
      throw new Error('not implemented');
    };
    expect(selectedBackend(makeSafeStorage({ backend: throwing }))).toBeNull();
  });
  it('returns null when the query yields a non-string', () => {
    const nonString = (): string => 42 as unknown as string;
    expect(selectedBackend(makeSafeStorage({ backend: nonString }))).toBeNull();
  });
});

describe('saveDecryptedKeys', () => {
  it('encrypts and round-trips the full key map (providers + cloud)', () => {
    const store = makeSafeStorage();
    saveDecryptedKeys(store, keystorePath(), {
      providers: { groq: ['gsk_a', 'gsk_b'] },
      cloudApiKey: 'sk-cloud',
    });
    // No plaintext key byte is written to disk.
    const onDisk = readFileSync(keystorePath(), 'utf8');
    expect(onDisk).not.toContain('gsk_a');
    expect(onDisk).not.toContain('sk-cloud');
    // But it decrypts back to the raw material.
    const loaded = loadDecryptedKeys(store, keystorePath());
    expect(loaded.providers.groq).toEqual(['gsk_a', 'gsk_b']);
    expect(loaded.cloudApiKey).toBe('sk-cloud');
  });

  it('refuses to persist (throws) when no secure backend exists', () => {
    const store = makeSafeStorage({ available: false });
    expect(() =>
      saveDecryptedKeys(store, keystorePath(), { providers: { groq: ['gsk_a'] } }),
    ).toThrow(KeystoreUnavailableError);
    expect(existsSync(keystorePath())).toBe(false);
  });
});

describe('secureStatus', () => {
  it('is secure when encryption is available and backend is not basic_text', () => {
    const status = secureStatus(makeSafeStorage({ backend: 'kwallet' }));
    expect(status).toEqual({
      available: true,
      backend: 'kwallet',
      sessionOnly: false,
      banner: null,
    });
  });
  it('is secure on win/mac (no backend query) when encryption is available', () => {
    const status = secureStatus(makeSafeStorage());
    expect(status.sessionOnly).toBe(false);
    expect(status.banner).toBeNull();
  });
  it('refuses (session-only + banner) when only basic_text is available', () => {
    const status = secureStatus(makeSafeStorage({ backend: BASIC_TEXT_BACKEND }));
    expect(status.sessionOnly).toBe(true);
    expect(status.banner).toBe(SESSION_ONLY_BANNER);
  });
  it('refuses when encryption is unavailable', () => {
    const status = secureStatus(makeSafeStorage({ available: false }));
    expect(status.sessionOnly).toBe(true);
    expect(status.banner).toBe(SESSION_ONLY_BANNER);
  });
});

describe('encrypt/decrypt', () => {
  it('round-trips a key through base64 ciphertext', () => {
    const ss = makeSafeStorage();
    const b64 = encryptToBase64(ss, 'sk-live-SECRET');
    expect(b64).not.toContain('sk-live-SECRET'); // ciphertext is base64, not the plaintext
    expect(decryptFromBase64(ss, b64)).toBe('sk-live-SECRET');
  });
  it('refuses to encrypt when no secure backend exists', () => {
    const ss = makeSafeStorage({ backend: BASIC_TEXT_BACKEND });
    expect(() => encryptToBase64(ss, 'sk-x')).toThrow(KeystoreUnavailableError);
  });
});

describe('extractPlaintextKeys', () => {
  it('pulls raw provider + cloud keys, skipping redacted and empty values', () => {
    const keys = extractPlaintextKeys({
      providers: [
        { id: 'groq', apiKeys: ['gsk-raw-1', '…WXYZ', ''] },
        { id: 'empty', apiKeys: ['…redacted'] },
      ],
      cloudApiKey: 'sk-cloud-raw',
    });
    expect(keys.providers).toEqual({ groq: ['gsk-raw-1'] });
    expect(keys.cloudApiKey).toBe('sk-cloud-raw');
  });
  it('ignores a redacted cloudApiKey', () => {
    expect(extractPlaintextKeys({ cloudApiKey: '…1234' }).cloudApiKey).toBeUndefined();
  });
  it('tolerates non-object settings and malformed provider entries', () => {
    expect(extractPlaintextKeys(null)).toEqual({ providers: {} });
    expect(extractPlaintextKeys({ providers: 'nope' })).toEqual({ providers: {} });
    expect(
      extractPlaintextKeys({
        providers: ['x', { id: 5, apiKeys: ['k'] }, { id: 'p', apiKeys: 'no' }],
      }),
    ).toEqual({ providers: {} });
  });
});

describe('stripKeysFromSettings', () => {
  it('empties apiKeys, drops cloudApiKey, and preserves every other setting', () => {
    const out = stripKeysFromSettings({
      useCloud: true,
      cloudApiKey: 'sk-secret',
      providers: [{ id: 'groq', provider: 'Groq', apiKeys: ['gsk-secret'], enabled: true }],
    });
    expect(out.useCloud).toBe(true);
    expect('cloudApiKey' in out).toBe(false);
    expect(out.providers).toEqual([{ id: 'groq', provider: 'Groq', apiKeys: [], enabled: true }]);
  });
  it('passes non-array providers + non-dict entries through untouched', () => {
    expect(stripKeysFromSettings({ providers: 'nope' }).providers).toBe('nope');
    expect(stripKeysFromSettings({ providers: ['x', { id: 'p', model: 'm' }] }).providers).toEqual([
      'x',
      { id: 'p', model: 'm' },
    ]);
  });
  it('returns an empty object for non-object settings', () => {
    expect(stripKeysFromSettings(undefined)).toEqual({});
  });
});

describe('loadDecryptedKeys', () => {
  it('returns empty when no keystore file exists', () => {
    expect(loadDecryptedKeys(makeSafeStorage(), keystorePath())).toEqual({ providers: {} });
  });
  it('round-trips provider + cloud keys written by a migration', () => {
    const ss = makeSafeStorage();
    writeFileSync(
      settingsPath(),
      JSON.stringify({ providers: [{ id: 'groq', apiKeys: ['gsk-1'] }], cloudApiKey: 'sk-c' }),
    );
    migrateLegacyPlaintextKeys(ss, settingsPath(), keystorePath());
    expect(loadDecryptedKeys(ss, keystorePath())).toEqual({
      providers: { groq: ['gsk-1'] },
      cloudApiKey: 'sk-c',
    });
  });
  it('tolerates a malformed keystore file / non-array provider values', () => {
    writeFileSync(keystorePath(), '{not json');
    expect(loadDecryptedKeys(makeSafeStorage(), keystorePath())).toEqual({ providers: {} });
    writeFileSync(keystorePath(), JSON.stringify({ version: 1, providers: { groq: 'nope' } }));
    expect(loadDecryptedKeys(makeSafeStorage(), keystorePath())).toEqual({ providers: {} });
  });
});

describe('migrateLegacyPlaintextKeys', () => {
  const LIVE = 'sk-plaintext-DO-NOT-KEEP-9999';

  it('is a no-op when there are no plaintext keys', () => {
    writeFileSync(settingsPath(), JSON.stringify({ useCloud: false, providers: [] }));
    const res = migrateLegacyPlaintextKeys(makeSafeStorage(), settingsPath(), keystorePath());
    expect(res.status).toBe('noop');
    expect(existsSync(keystorePath())).toBe(false);
  });

  it('re-encrypts keys and leaves ZERO plaintext across settings.json + .tmp + backups', () => {
    const ss = makeSafeStorage();
    // Seed the legacy plaintext settings + a stale .tmp + two backups all holding the key.
    writeFileSync(
      settingsPath(),
      JSON.stringify({
        useCloud: true,
        providers: [{ id: 'groq', apiKeys: [LIVE] }],
        cloudApiKey: LIVE,
      }),
    );
    writeFileSync(
      `${settingsPath()}.tmp`,
      JSON.stringify({ providers: [{ id: 'groq', apiKeys: [LIVE] }] }),
    );
    writeFileSync(`${settingsPath()}.bak`, `stale backup ${LIVE}`);
    writeFileSync(`${settingsPath()}.backup`, `older backup ${LIVE}`);

    const res = migrateLegacyPlaintextKeys(ss, settingsPath(), keystorePath());

    expect(res.status).toBe('migrated');
    expect(res.migratedProviderKeys).toBe(1);
    expect(res.migratedCloudKey).toBe(true);
    // The encrypted keystore now holds the key (recoverable only via safeStorage).
    expect(loadDecryptedKeys(ss, keystorePath())).toEqual({
      providers: { groq: [LIVE] },
      cloudApiKey: LIVE,
    });
    // Non-secret settings survived the strip.
    const scrubbed = JSON.parse(readFileSync(settingsPath(), 'utf8'));
    expect(scrubbed.useCloud).toBe(true);
    expect(scrubbed.providers[0].apiKeys).toEqual([]);
    expect('cloudApiKey' in scrubbed).toBe(false);
    // HEADLINE (§D2 acceptance a): scan every on-disk copy — no plaintext key byte survives.
    const survivors = [
      settingsPath(),
      `${settingsPath()}.tmp`,
      `${settingsPath()}.bak`,
      `${settingsPath()}.backup`,
    ]
      .filter((p) => existsSync(p))
      .map((p) => readFileSync(p, 'utf8'));
    for (const text of survivors) {
      expect(text).not.toContain(LIVE);
    }
    expect(res.shredded.length).toBeGreaterThanOrEqual(2); // .tmp + backups shredded
  });

  it('refuses (session-only + banner) and preserves the key when no secure store exists', () => {
    const ss = makeSafeStorage({ backend: BASIC_TEXT_BACKEND });
    writeFileSync(settingsPath(), JSON.stringify({ providers: [{ id: 'groq', apiKeys: [LIVE] }] }));
    const res = migrateLegacyPlaintextKeys(ss, settingsPath(), keystorePath());
    expect(res.status).toBe('refused');
    expect(res.sessionOnly).toBe(true);
    expect(res.banner).toBe(SESSION_ONLY_BANNER);
    // No encrypted store written, and the user's ONLY copy is not destroyed.
    expect(existsSync(keystorePath())).toBe(false);
    expect(readFileSync(settingsPath(), 'utf8')).toContain(LIVE);
  });

  it('is idempotent: a second run after migration is a no-op', () => {
    const ss = makeSafeStorage();
    writeFileSync(settingsPath(), JSON.stringify({ providers: [{ id: 'groq', apiKeys: [LIVE] }] }));
    migrateLegacyPlaintextKeys(ss, settingsPath(), keystorePath());
    const second = migrateLegacyPlaintextKeys(ss, settingsPath(), keystorePath());
    expect(second.status).toBe('noop');
  });

  it('tolerates a missing settings file (nothing to migrate)', () => {
    const res = migrateLegacyPlaintextKeys(makeSafeStorage(), settingsPath(), keystorePath());
    expect(res.status).toBe('noop');
  });

  it('shreds a subdirectory sibling name only when it is a stale file copy', () => {
    // priorCopies globs by basename prefix; a real dir seed proves readdir works.
    const ss = makeSafeStorage();
    mkdirSync(join(dir, 'sub'));
    writeFileSync(settingsPath(), JSON.stringify({ cloudApiKey: LIVE }));
    const res = migrateLegacyPlaintextKeys(ss, settingsPath(), keystorePath());
    expect(res.status).toBe('migrated');
  });

  it('surfaces a prior copy that could NOT be shredded in `unshreddable` (not `shredded`)', () => {
    // A sibling whose basename starts with the settings basename is a prior-copy
    // candidate priorCopies yields; when that candidate is itself un-scrubbable
    // (both shredFile arms fail), the migration must list it in `unshreddable[]` so
    // a lingering, still-recoverable plaintext copy is surfaced for manual removal —
    // never dropped, and never miscounted as `shredded`. A directory whose name
    // matches the prior-copy pattern is the deterministic cross-platform instance
    // (openSync r+ -> EISDIR and unlink -> EISDIR/EPERM), standing in for a locked /
    // read-only file that behaves identically.
    const ss = makeSafeStorage();
    const stuck = join(dir, 'settings.json.d'); // matches base prefix -> a prior copy
    mkdirSync(stuck);
    writeFileSync(settingsPath(), JSON.stringify({ cloudApiKey: LIVE }));

    const res = migrateLegacyPlaintextKeys(ss, settingsPath(), keystorePath());

    expect(res.status).toBe('migrated');
    expect(res.unshreddable).toContain(stuck); // surfaced for manual removal
    expect(res.shredded).not.toContain(stuck); // never miscounted as destroyed
  });

  it('re-reports an un-shreddable prior copy on a no-op run (warning persists across restarts)', () => {
    // Boot 1 migrated + shredded, but a locked/undeletable plaintext copy survived.
    // Boot 2: settings.json has been stripped, so migration is a no-op — yet the
    // recoverable plaintext copy is STILL on disk. It must be re-swept and re-reported,
    // else the security warning silently vanishes on the next restart while the exposure
    // persists. A directory is the deterministic un-shreddable stand-in.
    const ss = makeSafeStorage();
    const stuck = join(dir, 'settings.json.d');
    mkdirSync(stuck);
    writeFileSync(settingsPath(), JSON.stringify({ theme: 'dark' })); // NO keys -> noop path
    const res = migrateLegacyPlaintextKeys(ss, settingsPath(), keystorePath());
    expect(res.status).toBe('noop');
    expect(res.unshreddable).toContain(stuck); // still surfaced -> banner persists
    expect(res.shredded).not.toContain(stuck);
  });

  it('shreds a lingering plaintext copy even on a no-op run (self-correcting cleanup)', () => {
    // A stale pre-migration copy that still holds plaintext keys must be destroyed even
    // when settings.json itself has none (the app only ever writes key-free siblings),
    // so the exposure is cleaned up rather than lingering until the next accidental
    // migration.
    const ss = makeSafeStorage();
    const leftover = `${settingsPath()}.bak`;
    writeFileSync(leftover, JSON.stringify({ providers: [{ id: 'groq', apiKeys: [LIVE] }] }));
    writeFileSync(settingsPath(), JSON.stringify({ theme: 'dark' })); // no keys -> noop
    const res = migrateLegacyPlaintextKeys(ss, settingsPath(), keystorePath());
    expect(res.status).toBe('noop');
    expect(res.shredded).toContain(leftover);
    expect(existsSync(leftover)).toBe(false); // the recoverable plaintext copy is gone
  });
});

describe('shredFile', () => {
  it("reports 'absent' for a missing file", () => {
    // ENOENT -> nothing to shred and nothing for the user to clean up.
    expect(shredFile(join(dir, 'nope.json'))).toBe('absent');
  });
  it("truncates + removes a real plaintext file and reports it 'shredded'", () => {
    const f = join(dir, 'plain.json');
    writeFileSync(f, '{"cloudApiKey":"sk-live-should-be-scrubbed"}');
    expect(shredFile(f)).toBe('shredded');
    expect(existsSync(f)).toBe(false); // the plaintext copy is genuinely gone
  });
  it("reports 'intact' for a path that exists but cannot be scrubbed — never falsely reports a surviving plaintext copy as shredded", () => {
    // SECURITY (Codex stop-time review): a target that EXISTS but where BOTH the
    // truncate and the unlink fail — a locked / read-only / unwritable plaintext
    // copy, or a directory — is still fully recoverable on disk, so shredFile must
    // NOT report it handled (the migration would wrongly list it in `shredded[]`).
    // "Existed" is not "shredded"; it is 'intact', and the caller surfaces it in
    // `unshreddable[]` for manual removal. A directory is the deterministic
    // cross-platform instance of that class: openSync(dir,'r+') -> EISDIR and
    // unlinkSync(dir) -> EISDIR/EPERM, so both arms fail exactly as for a locked file.
    const asDir = join(dir, 'a-directory');
    mkdirSync(asDir);
    expect(shredFile(asDir)).toBe('intact'); // NOT falsely reported as shredded
    expect(existsSync(asDir)).toBe(true); // the intact copy is still on disk
  });
});

describe('priorCopies', () => {
  it('returns [] when the settings directory is unreadable/absent', () => {
    expect(priorCopies(join(dir, 'no-such-dir', 'settings.json'))).toEqual([]);
  });
});

describe('keystorePathFor', () => {
  it('joins the userData dir with the keystore filename', () => {
    expect(keystorePathFor('/data/user')).toBe(join('/data/user', KEYSTORE_FILENAME));
  });
});
