// socialTokens.test.ts — C14 social OAuth tokens in the EXISTING DPAPI keystore.
//
// C14 must not introduce a second secret store: `keystore.ts` already owns every
// at-rest credential (safeStorage-wrapped, atomic write, pre-overwrite backup,
// fail-closed on an unreadable blob). Social tokens therefore live in a new `social`
// section of that same file.
//
// THE HAZARD THESE TESTS EXIST FOR
// --------------------------------
// `saveDecryptedKeys` does not patch the keystore — it REBUILDS the whole document
// from the `DecryptedKeys` it is handed. So if the social section were not part of
// that value, the very next `providers.upsert` (a user typing an API key) would
// rewrite the file WITHOUT it and silently destroy every connected social account.
// The reverse holds too: connecting YouTube must not drop the provider keys.
//
// Both directions are asserted below, plus backward compatibility (a keystore
// written before C14 has no `social` key at all and must still load) and the
// fail-closed rule (a corrupt social section must be reported unreadable rather
// than reported empty, because "empty" is what makes the next write permanent).
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { KeyBridge } from './keyBridge';
import {
  type DecryptedKeys,
  type SafeStorageLike,
  type SocialToken,
  loadDecryptedKeys,
  readKeystore,
  saveDecryptedKeys,
} from './keystore';

/** Reversible fake (the keystore.test.ts idiom): ciphertext = "enc:" + plaintext. */
function makeSafeStorage(opts: { available?: boolean } = {}): SafeStorageLike {
  const available = opts.available ?? true;
  return {
    isEncryptionAvailable: () => available,
    encryptString: (plaintext: string) => Buffer.from(`enc:${plaintext}`, 'utf8'),
    decryptString: (encrypted: Buffer) => encrypted.toString('utf8').replace(/^enc:/, ''),
  };
}

const TOKEN: SocialToken = {
  accessToken: 'ya29.access-SECRET-1111',
  refreshToken: '1//refresh-SECRET-2222',
  expiresAt: 1_800_003_600,
  accountLabel: 'My Channel',
  scopes: ['https://www.googleapis.com/auth/youtube.upload'],
};

let dir: string;
let keystorePath: string;

beforeEach(() => {
  dir = mkdtempSync(join(tmpdir(), 'reframe-social-'));
  keystorePath = join(dir, 'secure-keys.json');
});

afterEach(() => {
  rmSync(dir, { recursive: true, force: true });
});

describe('social tokens round-trip through the DPAPI keystore', () => {
  it('saves and reloads a social token', () => {
    const safeStorage = makeSafeStorage();
    saveDecryptedKeys(safeStorage, keystorePath, { providers: {}, social: { youtube: TOKEN } });
    const loaded = loadDecryptedKeys(safeStorage, keystorePath);
    expect(loaded.social?.youtube).toEqual(TOKEN);
  });

  it('never writes a token in plaintext', () => {
    const safeStorage = makeSafeStorage();
    saveDecryptedKeys(safeStorage, keystorePath, { providers: {}, social: { youtube: TOKEN } });
    const raw = readFileSync(keystorePath, 'utf8');
    // The fake cipher is "enc:"-prefixed, so a plaintext leak is detectable: the
    // bare secret must not appear, only the enc: form.
    expect(raw).not.toContain('"ya29.access-SECRET-1111"');
    expect(raw).not.toContain('"1//refresh-SECRET-2222"');
    expect(raw).toContain('social');
  });

  it('refuses to persist when there is no secure backend (no plaintext fallback)', () => {
    const safeStorage = makeSafeStorage({ available: false });
    expect(() =>
      saveDecryptedKeys(safeStorage, keystorePath, { providers: {}, social: { youtube: TOKEN } }),
    ).toThrow();
  });
});

describe('THE NO-WIPE INVARIANT (both directions)', () => {
  it('a providers.upsert does NOT destroy stored social tokens', () => {
    const safeStorage = makeSafeStorage();
    // 1. The user connects YouTube.
    saveDecryptedKeys(safeStorage, keystorePath, { providers: {}, social: { youtube: TOKEN } });
    // 2. Later the user pastes a Groq API key. This goes through the SAME keystore
    //    writer, which rebuilds the whole document.
    const bridge = new KeyBridge({ safeStorage, keystorePath });
    bridge.forwardParams('providers.upsert', { id: 'groq', apiKeys: ['gsk-live-KEY1'] });
    // 3. The social token must still be there.
    const loaded = loadDecryptedKeys(safeStorage, keystorePath);
    expect(loaded.social?.youtube).toEqual(TOKEN);
    expect(loaded.providers.groq).toEqual(['gsk-live-KEY1']);
  });

  it('a providers.remove does NOT destroy stored social tokens', () => {
    const safeStorage = makeSafeStorage();
    saveDecryptedKeys(safeStorage, keystorePath, {
      providers: { groq: ['gsk-live-KEY1'] },
      social: { youtube: TOKEN },
    });
    const bridge = new KeyBridge({ safeStorage, keystorePath });
    bridge.forwardParams('providers.remove', { id: 'groq' });
    const loaded = loadDecryptedKeys(safeStorage, keystorePath);
    expect(loaded.social?.youtube).toEqual(TOKEN);
    expect(loaded.providers.groq).toBeUndefined();
  });

  it('saving a social token does NOT destroy provider keys', () => {
    const safeStorage = makeSafeStorage();
    saveDecryptedKeys(safeStorage, keystorePath, { providers: { groq: ['gsk-live-KEY1'] } });
    const existing = loadDecryptedKeys(safeStorage, keystorePath);
    saveDecryptedKeys(safeStorage, keystorePath, { ...existing, social: { youtube: TOKEN } });
    const loaded = loadDecryptedKeys(safeStorage, keystorePath);
    expect(loaded.providers.groq).toEqual(['gsk-live-KEY1']);
    expect(loaded.social?.youtube).toEqual(TOKEN);
  });
});

describe('backward compatibility + fail-closed reads', () => {
  it('a pre-C14 keystore with no social section still loads', () => {
    const safeStorage = makeSafeStorage();
    // Exactly the shape keystore.ts wrote before this change.
    writeFileSync(
      keystorePath,
      JSON.stringify({
        version: 1,
        providers: { groq: [Buffer.from('enc:gsk-old').toString('base64')] },
      }),
      'utf8',
    );
    const read = readKeystore(safeStorage, keystorePath);
    expect(read.outcome).toBe('loaded');
    expect(read.keys?.providers.groq).toEqual(['gsk-old']);
    expect(read.keys?.social).toBeUndefined();
  });

  it('a NON-OBJECT social section is unreadable, never silently empty', () => {
    // Reported "empty" would let the next save overwrite real tokens for good.
    const safeStorage = makeSafeStorage();
    writeFileSync(
      keystorePath,
      JSON.stringify({ version: 1, providers: {}, social: 'nope' }),
      'utf8',
    );
    const read = readKeystore(safeStorage, keystorePath);
    expect(read.outcome).toBe('unreadable');
    expect(read.reason).toBe('shape-invalid');
    expect(read.keys).toBeNull();
  });

  it('a non-string social ENTRY is unreadable', () => {
    const safeStorage = makeSafeStorage();
    writeFileSync(
      keystorePath,
      JSON.stringify({ version: 1, providers: {}, social: { youtube: 7 } }),
      'utf8',
    );
    expect(readKeystore(safeStorage, keystorePath).reason).toBe('shape-invalid');
  });

  it('a social entry that does not decrypt is unreadable', () => {
    const safeStorage: SafeStorageLike = {
      ...makeSafeStorage(),
      decryptString: () => {
        throw new Error('DPAPI failed');
      },
    };
    writeFileSync(
      keystorePath,
      JSON.stringify({ version: 1, providers: {}, social: { youtube: 'Y2lwaGVy' } }),
      'utf8',
    );
    expect(readKeystore(safeStorage, keystorePath).reason).toBe('decrypt-failed');
  });

  it('a social entry whose plaintext is not valid JSON is unreadable', () => {
    const safeStorage = makeSafeStorage();
    writeFileSync(
      keystorePath,
      JSON.stringify({
        version: 1,
        providers: {},
        social: { youtube: Buffer.from('enc:{not json').toString('base64') },
      }),
      'utf8',
    );
    expect(readKeystore(safeStorage, keystorePath).reason).toBe('shape-invalid');
  });

  it('a social entry missing its accessToken is unreadable', () => {
    // A record with no usable credential is corruption, not a connected account.
    const safeStorage = makeSafeStorage();
    const blob = Buffer.from(`enc:${JSON.stringify({ accountLabel: 'x' })}`).toString('base64');
    writeFileSync(
      keystorePath,
      JSON.stringify({ version: 1, providers: {}, social: { youtube: blob } }),
      'utf8',
    );
    expect(readKeystore(safeStorage, keystorePath).reason).toBe('shape-invalid');
  });

  it('fills absent optional fields with safe defaults', () => {
    const safeStorage = makeSafeStorage();
    const blob = Buffer.from(`enc:${JSON.stringify({ accessToken: 'at-1' })}`).toString('base64');
    writeFileSync(
      keystorePath,
      JSON.stringify({ version: 1, providers: {}, social: { youtube: blob } }),
      'utf8',
    );
    const read = readKeystore(safeStorage, keystorePath);
    expect(read.keys?.social?.youtube).toEqual({
      accessToken: 'at-1',
      refreshToken: '',
      expiresAt: 0,
      accountLabel: '',
      scopes: [],
    });
  });

  it('drops a prototype-polluting platform id rather than writing it', () => {
    const safeStorage = makeSafeStorage();
    // Built via JSON.parse, NOT an object literal: `{__proto__: x}` in a literal
    // sets the PROTOTYPE and creates no own property, so Object.entries would not
    // see it and this test would pass without the guard ever running.
    const social = JSON.parse(
      '{"__proto__": {"accessToken": "bad"}, "youtube": {"accessToken": "ok"}}',
    );
    const keys: DecryptedKeys = { providers: {}, social: social as Record<string, SocialToken> };
    expect(Object.keys(social)).toContain('__proto__'); // detector control
    saveDecryptedKeys(safeStorage, keystorePath, keys);
    const raw = readFileSync(keystorePath, 'utf8');
    expect(raw).not.toContain('__proto__');
    expect(raw).toContain('youtube');
  });

  it('drops a prototype-polluting platform id on the READ path too', () => {
    const safeStorage = makeSafeStorage();
    const blob = Buffer.from(`enc:${JSON.stringify({ accessToken: 'at-1' })}`).toString('base64');
    // Written by hand (a hostile/corrupt file), since writeKeystore filters it out.
    writeFileSync(
      keystorePath,
      `{"version":1,"providers":{},"social":{"__proto__":"${blob}","youtube":"${blob}"}}`,
      'utf8',
    );
    const read = readKeystore(safeStorage, keystorePath);
    expect(read.outcome).toBe('loaded');
    expect(Object.keys(read.keys?.social ?? {})).toEqual(['youtube']);
  });
});
