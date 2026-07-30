// keystore.test.ts — WU-D2 DPAPI keystore + one-time plaintext migration.
//
// safeStorage is faked with a REVERSIBLE, deterministic transform so encrypt ->
// base64 -> decrypt round-trips without a real OS keychain. The filesystem is a
// per-test tmp dir. The headline assertion (§D2 acceptance a): after a migration
// ZERO plaintext key bytes remain across settings.json + its .tmp + backups.
import {
  constants as fsConstants,
  linkSync,
  mkdtempSync,
  mkdirSync,
  readFileSync,
  readdirSync,
  symlinkSync,
  writeFileSync,
  existsSync,
  rmSync,
} from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import {
  BASIC_TEXT_BACKEND,
  KEYSTORE_BACKUP_RETENTION,
  KEYSTORE_FILENAME,
  KeystoreBackupError,
  KeystoreUnavailableError,
  KeystoreUnreadableError,
  SESSION_ONLY_BANNER,
  type SafeStorageLike,
  backupKeystore,
  decryptFromBase64,
  encryptToBase64,
  extractPlaintextKeys,
  keystoreBackupPath,
  keystorePathFor,
  loadDecryptedKeys,
  migrateLegacyPlaintextKeys,
  priorCopies,
  pruneKeystoreBackups,
  readKeystore,
  saveDecryptedKeys,
  secureStatus,
  selectedBackend,
  shredFile,
  shredOpenFlags,
  stripKeysFromSettings,
} from './keystore';

/** A reversible fake: ciphertext = "enc:" + plaintext (survives a base64 round-trip). */
function makeSafeStorage(
  opts: {
    available?: boolean;
    backend?: string | null | (() => string);
    decryptThrows?: boolean;
  } = {},
): SafeStorageLike {
  const available = opts.available ?? true;
  const store: SafeStorageLike = {
    isEncryptionAvailable: () => available,
    encryptString: (plaintext: string) => Buffer.from(`enc:${plaintext}`, 'utf8'),
    decryptString: (encrypted: Buffer) => {
      // Stands in for a real DPAPI failure: a foreign-machine / post-profile-move
      // keystore whose ciphertext this OS user simply cannot unwrap.
      if (opts.decryptThrows) throw new Error('decrypt failed');
      return encrypted.toString('utf8').replace(/^enc:/, '');
    },
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
  it('FAILS CLOSED on a malformed keystore instead of reporting it EMPTY', () => {
    // REGRESSION PIN (T7, the credential WIPE). This case previously returned
    // `{providers:{}}` — indistinguishable from "no keystore yet" — so the very next
    // providers.upsert wrote a fresh store OVER the unreadable one and PERMANENTLY
    // destroyed every stored credential. An unreadable keystore is now a typed
    // refusal the caller MUST handle; it can no longer masquerade as empty.
    writeFileSync(keystorePath(), '{not json');
    expect(() => loadDecryptedKeys(makeSafeStorage(), keystorePath())).toThrow(
      KeystoreUnreadableError,
    );
    writeFileSync(keystorePath(), JSON.stringify({ version: 1, providers: { groq: 'nope' } }));
    expect(() => loadDecryptedKeys(makeSafeStorage(), keystorePath())).toThrow(
      KeystoreUnreadableError,
    );
  });

  it('carries the classified reason on the fail-closed error', () => {
    writeFileSync(keystorePath(), '{not json');
    try {
      loadDecryptedKeys(makeSafeStorage(), keystorePath());
      expect.unreachable('loadDecryptedKeys must refuse an unparseable keystore');
    } catch (err) {
      expect(err).toBeInstanceOf(KeystoreUnreadableError);
      expect((err as KeystoreUnreadableError).reason).toBe('parse-failed');
      // The diagnostic must never carry key material.
      expect((err as Error).message).not.toContain('gsk');
    }
  });
});

describe('readKeystore (3-state: loaded | absent | unreadable)', () => {
  it("reports 'absent' with empty keys when no keystore file exists", () => {
    const read = readKeystore(makeSafeStorage(), keystorePath());
    expect(read.outcome).toBe('absent');
    expect(read.keys).toEqual({ providers: {} });
    expect(read.reason).toBeNull();
  });

  it("reports 'loaded' with the decrypted keys for a healthy keystore", () => {
    const ss = makeSafeStorage();
    saveDecryptedKeys(ss, keystorePath(), {
      providers: { groq: ['gsk_fakeAAAA'] },
      cloudApiKey: 'sk-fake-cloud',
    });
    const read = readKeystore(ss, keystorePath());
    expect(read.outcome).toBe('loaded');
    expect(read.keys).toEqual({
      providers: { groq: ['gsk_fakeAAAA'] },
      cloudApiKey: 'sk-fake-cloud',
    });
    expect(read.reason).toBeNull();
  });

  it("reports 'unreadable' + parse-failed for a corrupt / partially-written blob", () => {
    writeFileSync(keystorePath(), '{"version":1,"providers":{"groq":["ZW5j'); // truncated write
    const read = readKeystore(makeSafeStorage(), keystorePath());
    expect(read.outcome).toBe('unreadable');
    expect(read.reason).toBe('parse-failed');
    // keys === null makes "silently continue as empty" structurally impossible.
    expect(read.keys).toBeNull();
  });

  it("reports 'unreadable' + read-failed when the blob cannot be read at all", () => {
    // A directory at the keystore path is the deterministic cross-platform stand-in
    // for a locked / permission-denied file (readFileSync -> EISDIR|EACCES|EPERM).
    mkdirSync(keystorePath());
    const read = readKeystore(makeSafeStorage(), keystorePath());
    expect(read.outcome).toBe('unreadable');
    expect(read.reason).toBe('read-failed');
  });

  it("reports 'unreadable' + decrypt-failed when the ciphertext cannot be unwrapped", () => {
    // The DPAPI-failure / foreign-machine / profile-move case: the file is perfectly
    // well-formed, but this OS user cannot decrypt it. Treating that as empty is the
    // wipe; it must be a refusal.
    saveDecryptedKeys(makeSafeStorage(), keystorePath(), { providers: { groq: ['gsk_fakeAAAA'] } });
    const read = readKeystore(makeSafeStorage({ decryptThrows: true }), keystorePath());
    expect(read.outcome).toBe('unreadable');
    expect(read.reason).toBe('decrypt-failed');
    expect(read.keys).toBeNull();
  });

  it("reports 'unreadable' + decrypt-failed when the CLOUD key cannot be unwrapped", () => {
    saveDecryptedKeys(makeSafeStorage(), keystorePath(), {
      providers: {},
      cloudApiKey: 'sk-fake-cloud',
    });
    const read = readKeystore(makeSafeStorage({ decryptThrows: true }), keystorePath());
    expect(read.outcome).toBe('unreadable');
    expect(read.reason).toBe('decrypt-failed');
  });

  it.each([
    ['a JSON array', '[]'],
    ['a JSON scalar', '"nope"'],
    ['JSON null', 'null'],
    ['a non-object providers map', JSON.stringify({ version: 1, providers: 'nope' })],
    ['a providers array', JSON.stringify({ version: 1, providers: [] })],
    ['a non-array provider value', JSON.stringify({ version: 1, providers: { groq: 'nope' } })],
    ['a non-string cloudApiKey', JSON.stringify({ version: 1, providers: {}, cloudApiKey: 7 })],
  ])("reports 'unreadable' + shape-invalid for %s", (_label, body) => {
    writeFileSync(keystorePath(), body);
    const read = readKeystore(makeSafeStorage(), keystorePath());
    expect(read.outcome).toBe('unreadable');
    expect(read.reason).toBe('shape-invalid');
  });

  it('loads a keystore with no providers map at all as an empty (but LOADED) store', () => {
    writeFileSync(keystorePath(), JSON.stringify({ version: 1 }));
    const read = readKeystore(makeSafeStorage(), keystorePath());
    expect(read.outcome).toBe('loaded');
    expect(read.keys).toEqual({ providers: {} });
  });

  it('SKIPS a prototype-polluting provider id while still loading the rest', () => {
    // A `__proto__` entry can never have been written by writeKeystore (it filters
    // unsafe ids), and it is not loadable provider material — so it is dropped
    // rather than escalated to a store-wide refusal, exactly as before.
    const ss = makeSafeStorage();
    writeFileSync(
      keystorePath(),
      `{"version":1,"providers":{"__proto__":["${Buffer.from('enc:pollute', 'utf8').toString(
        'base64',
      )}"],"groq":["${Buffer.from('enc:gsk_fakeAAAA', 'utf8').toString('base64')}"]}}`,
    );
    const read = readKeystore(ss, keystorePath());
    expect(read.outcome).toBe('loaded');
    expect(read.keys).toEqual({ providers: { groq: ['gsk_fakeAAAA'] } });
  });
});

describe('keystore pre-overwrite backup', () => {
  const AT = new Date(Date.UTC(2026, 6, 25, 5, 47, 51, 123));
  const stamped = (): string => keystoreBackupPath(keystorePath(), AT);

  it('renders a fixed-width, lexicographically-sortable timestamp suffix', () => {
    expect(stamped()).toBe(`${keystorePath()}.20260725T054751123.bak`);
    // Fixed width => lexicographic order IS chronological order (the prune relies on it).
    const later = keystoreBackupPath(keystorePath(), new Date(AT.getTime() + 1));
    expect([later, stamped()].sort()).toEqual([stamped(), later]);
  });

  it('copies the existing ciphertext aside BYTE-FOR-BYTE before an overwrite', () => {
    const ss = makeSafeStorage();
    saveDecryptedKeys(ss, keystorePath(), { providers: { groq: ['gsk_originalAAAA'] } });
    const before = readFileSync(keystorePath(), 'utf8');
    expect(backupKeystore(keystorePath(), AT)).toBe('backed-up');
    expect(readFileSync(stamped(), 'utf8')).toBe(before);
  });

  it("reports 'nothing-to-back-up' on the very first write (no prior blob)", () => {
    expect(backupKeystore(keystorePath(), AT)).toBe('nothing-to-back-up');
    expect(readdirSync(dir)).toEqual([]);
  });

  it('THROWS when a blob EXISTS but cannot be copied (never overwrite the unbacked-up)', () => {
    mkdirSync(keystorePath()); // copyFileSync -> EISDIR/EPERM
    expect(() => backupKeystore(keystorePath(), AT)).toThrow(KeystoreBackupError);
  });

  it('saveDecryptedKeys backs up the PREVIOUS blob so a bad decrypt is never destructive', () => {
    const ss = makeSafeStorage();
    saveDecryptedKeys(ss, keystorePath(), { providers: { groq: ['gsk_generation1'] } });
    const gen1 = readFileSync(keystorePath(), 'utf8');
    saveDecryptedKeys(ss, keystorePath(), { providers: { groq: ['gsk_generation2'] } });
    const backups = readdirSync(dir).filter((n) => n.endsWith('.bak'));
    expect(backups).toHaveLength(1);
    expect(readFileSync(join(dir, backups[0]), 'utf8')).toBe(gen1);
    // ...and the recovered generation still decrypts to the ORIGINAL key.
    expect(loadDecryptedKeys(ss, join(dir, backups[0]))).toEqual({
      providers: { groq: ['gsk_generation1'] },
    });
  });

  it('REFUSES the overwrite when the existing blob cannot be backed up', () => {
    mkdirSync(keystorePath());
    expect(() =>
      saveDecryptedKeys(makeSafeStorage(), keystorePath(), {
        providers: { groq: ['gsk_newAAAA'] },
      }),
    ).toThrow(KeystoreBackupError);
    // The pre-existing blob is untouched (still the directory we planted).
    expect(existsSync(keystorePath())).toBe(true);
  });

  it('prunes the OLDEST backups beyond the retention cap', () => {
    for (let i = 0; i < KEYSTORE_BACKUP_RETENTION + 3; i += 1) {
      writeFileSync(keystorePath(), `blob-${i}`);
      backupKeystore(keystorePath(), new Date(Date.UTC(2026, 6, 25, 0, 0, i, 0)));
    }
    const backups = readdirSync(dir)
      .filter((n) => n.endsWith('.bak'))
      .sort();
    expect(backups).toHaveLength(KEYSTORE_BACKUP_RETENTION);
    // The survivors are the NEWEST generations, not the oldest.
    expect(readFileSync(join(dir, backups[backups.length - 1]), 'utf8')).toBe(
      `blob-${KEYSTORE_BACKUP_RETENTION + 2}`,
    );
    expect(backups.some((n) => n.includes('T000000000'))).toBe(false); // generation 0 pruned
  });

  it('ignores siblings that are not backups, and tolerates an unreadable directory', () => {
    writeFileSync(keystorePath(), 'blob');
    writeFileSync(`${keystorePath()}.tmp`, 'not-a-backup'); // right prefix, wrong extension
    writeFileSync(join(dir, 'settings.json'), '{}'); // wrong prefix entirely
    expect(pruneKeystoreBackups(keystorePath(), 0)).toEqual([]);
    expect(existsSync(`${keystorePath()}.tmp`)).toBe(true);
    expect(existsSync(join(dir, 'settings.json'))).toBe(true);
    // A missing directory is not an error — nothing to prune.
    expect(pruneKeystoreBackups(join(dir, 'no-such-dir', KEYSTORE_FILENAME), 0)).toEqual([]);
  });

  it('leaves an un-deletable stale backup in place rather than throwing', () => {
    writeFileSync(keystorePath(), 'blob');
    const stuck = `${keystorePath()}.20260101T000000000.bak`;
    mkdirSync(stuck); // unlinkSync -> EISDIR/EPERM
    expect(pruneKeystoreBackups(keystorePath(), 0)).toEqual([]);
    expect(existsSync(stuck)).toBe(true);
  });
});

describe('shredFile link safety', () => {
  it('REFUSES to truncate through a SYMLINK — the external target survives intact', () => {
    // T7(3): shredFile opened with 'r+', which FOLLOWS a symlink, so a hostile or
    // stale `settings.json.bak -> <anything>` link made the shred destroy an
    // unrelated file. A symlink is not a plaintext key copy (its bytes live
    // elsewhere), so it must never be truncated.
    const victim = join(dir, 'victim.txt');
    writeFileSync(victim, 'PRECIOUS-EXTERNAL-BYTES');
    const link = join(dir, 'settings.json.bak');
    symlinkSync(victim, link, 'file');
    expect(shredFile(link)).toBe('intact'); // surfaced for manual review, never followed
    expect(readFileSync(victim, 'utf8')).toBe('PRECIOUS-EXTERNAL-BYTES');
    expect(existsSync(link)).toBe(true);
  });

  it('REFUSES to truncate a HARD LINK — its bytes are shared with an external file', () => {
    // Same defect class, and the variant that needs no symlink privilege at all:
    // truncating one hard link zeroes the shared inode, so the other name's content
    // is destroyed too (measured: 23 bytes -> 0).
    const victim = join(dir, 'hard-victim.txt');
    writeFileSync(victim, 'PRECIOUS-EXTERNAL-BYTES');
    const link = join(dir, 'settings.json.hard');
    linkSync(victim, link);
    expect(shredFile(link)).toBe('intact');
    expect(readFileSync(victim, 'utf8')).toBe('PRECIOUS-EXTERNAL-BYTES');
  });

  it('still shreds an ordinary single-link file', () => {
    const f = join(dir, 'settings.json.tmp');
    writeFileSync(f, '{"cloudApiKey":"sk-fake-should-be-scrubbed"}');
    expect(shredFile(f)).toBe('shredded');
    expect(existsSync(f)).toBe(false);
  });

  it('does not throw when the link probe itself fails on a malformed path', () => {
    // lstatSync rejects a NUL-bearing path with ERR_INVALID_ARG_VALUE; shredFile must
    // stay total (its callers sweep in a loop and must not abort mid-sweep).
    const malformed = join(dir, 'a' + String.fromCharCode(0) + 'b');
    expect(shredFile(malformed)).toBe('intact');
  });

  it('adds O_NOFOLLOW where the platform defines it and is a no-op where it does not', () => {
    // POSIX closes the lstat->open TOCTOU window in the open itself; Windows does not
    // define the flag (fs.constants.O_NOFOLLOW === undefined), so the lstat check is
    // the whole guard there. Both shapes are pinned so neither platform regresses.
    expect(shredOpenFlags({ O_RDWR: 2, O_NOFOLLOW: 131072 })).toBe(2 | 131072);
    expect(shredOpenFlags({ O_RDWR: 2 })).toBe(2);
    expect(shredOpenFlags(fsConstants)).toBeGreaterThanOrEqual(fsConstants.O_RDWR);
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

  it('PRESERVES a non-secret settings backup on a no-op run (never destroys user data)', () => {
    // Codex: the every-boot sweep must NOT delete a user's key-FREE settings backup.
    // A readable, valid-JSON sibling that holds no plaintext keys is not a security
    // exposure, so it is left untouched — only key-bearing (or unprovable) copies are
    // swept.
    const ss = makeSafeStorage();
    const backup = `${settingsPath()}.backup`;
    writeFileSync(backup, JSON.stringify({ theme: 'dark', useCloud: true })); // NO keys
    writeFileSync(settingsPath(), JSON.stringify({ theme: 'dark' })); // noop
    const res = migrateLegacyPlaintextKeys(ss, settingsPath(), keystorePath());
    expect(res.status).toBe('noop');
    expect(res.shredded).not.toContain(backup);
    expect(res.unshreddable).not.toContain(backup);
    expect(existsSync(backup)).toBe(true); // the non-secret backup survives untouched
    expect(readFileSync(backup, 'utf8')).toContain('dark'); // and its contents are intact
  });

  it('PRESERVES a key-free backup even during a real migration', () => {
    // The same protection applies on the migrated path: a user's key-free backup is
    // not collateral damage of the one-time key migration.
    const ss = makeSafeStorage();
    const backup = `${settingsPath()}.backup`;
    writeFileSync(backup, JSON.stringify({ theme: 'light' })); // NO keys -> preserve
    writeFileSync(settingsPath(), JSON.stringify({ cloudApiKey: LIVE })); // keys -> migrate
    const res = migrateLegacyPlaintextKeys(ss, settingsPath(), keystorePath());
    expect(res.status).toBe('migrated');
    expect(res.shredded).not.toContain(backup);
    expect(existsSync(backup)).toBe(true);
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
