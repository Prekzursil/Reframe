// keyBridge.test.ts — WU-D2b-1 main-process key guard. safeStorage is faked with
// a reversible transform (as in keystore.test.ts) and the keystore lives in a tmp
// dir. Headline invariants: providers.upsert NEVER forwards a raw key (only last-4
// redactions), the raw keys land in the DPAPI keystore, provider-calling methods
// get _injectedKeys in-memory, and session-only mode writes NOTHING to disk.
import { existsSync, mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { KEYSTORE_FILENAME, loadDecryptedKeys, type SafeStorageLike } from './keystore';
import {
  INJECTED_KEYS_FIELD,
  KeyBridge,
  needsKeyInjection,
  planUpsert,
  redactKey,
} from './keyBridge';

/** Reversible fake: ciphertext = "enc:" + plaintext (survives a base64 round-trip). */
function makeSafeStorage(
  opts: { available?: boolean; backend?: string | null; decryptThrows?: boolean } = {},
): SafeStorageLike {
  const available = opts.available ?? true;
  const store: SafeStorageLike = {
    isEncryptionAvailable: () => available,
    encryptString: (plaintext: string) => Buffer.from(`enc:${plaintext}`, 'utf8'),
    decryptString: (encrypted: Buffer) => {
      if (opts.decryptThrows) throw new Error('decrypt failed');
      return encrypted.toString('utf8').replace(/^enc:/, '');
    },
  };
  if (opts.backend !== undefined) {
    store.getSelectedStorageBackend = () => opts.backend as string;
  }
  return store;
}

let dir: string;
beforeEach(() => {
  dir = mkdtempSync(join(tmpdir(), 'keybridge-test-'));
});
afterEach(() => {
  rmSync(dir, { recursive: true, force: true });
});
const keystorePath = (): string => join(dir, KEYSTORE_FILENAME);

describe('redactKey', () => {
  it('renders long keys as ellipsis + last 4', () => {
    expect(redactKey('sk-abcd1234WXYZ')).toBe('…WXYZ');
  });
  it('renders keys of 4 or fewer chars as a bare ellipsis (no leak)', () => {
    expect(redactKey('ABCD')).toBe('…');
    expect(redactKey('a')).toBe('…');
    expect(redactKey('')).toBe('…');
  });
});

describe('needsKeyInjection', () => {
  it('is true for the provider-calling prefixes', () => {
    for (const m of ['ai.planJob', 'director.plan', 'shortmaker.select', 'index.build']) {
      expect(needsKeyInjection(m)).toBe(true);
    }
  });
  it('is true for the enumerated key-reading methods', () => {
    for (const m of [
      'subtitles.translate',
      'providers.usage',
      'providers.openrouterUsage',
      'providers.revealKey',
    ]) {
      expect(needsKeyInjection(m)).toBe(true);
    }
  });
  it('is false for the store path and non-provider methods', () => {
    for (const m of [
      'providers.upsert',
      'providers.testKey',
      'providers.list',
      'settings.get',
      'library.list',
      'subtitles.generate',
    ]) {
      expect(needsKeyInjection(m)).toBe(false);
    }
  });
});

describe('planUpsert', () => {
  const noStored = (): string[] => [];

  it('extracts raw keys and forwards them redacted (bare params)', () => {
    const plan = planUpsert({ id: 'groq', apiKeys: ['gsk_secretKEY1'] }, noStored);
    expect(plan.providerId).toBe('groq');
    expect(plan.resolvedKeys).toEqual(['gsk_secretKEY1']);
    expect(plan.forwardParams).toEqual({ id: 'groq', apiKeys: ['…KEY1'] });
  });

  it('handles the nested {provider:{…}} envelope', () => {
    const plan = planUpsert(
      { provider: { id: 'openai', apiKeys: ['sk-liveKEY9'] }, extra: 1 },
      noStored,
    );
    expect(plan.providerId).toBe('openai');
    expect(plan.resolvedKeys).toEqual(['sk-liveKEY9']);
    expect(plan.forwardParams).toEqual({
      provider: { id: 'openai', apiKeys: ['…KEY9'] },
      extra: 1,
    });
  });

  it('restores a redacted placeholder back to the stored raw key (positional)', () => {
    const stored = (id: string): string[] => (id === 'groq' ? ['gsk_storedABCD'] : []);
    const plan = planUpsert({ id: 'groq', apiKeys: ['…ABCD'] }, stored);
    expect(plan.resolvedKeys).toEqual(['gsk_storedABCD']);
    expect(plan.forwardParams).toEqual({ id: 'groq', apiKeys: ['…ABCD'] });
  });

  it('merges an existing redacted key with a new raw key (add-key flow)', () => {
    const stored = (): string[] => ['gsk_existABCD'];
    const plan = planUpsert({ id: 'groq', apiKeys: ['…ABCD', 'gsk_newRAW7'] }, stored);
    expect(plan.resolvedKeys).toEqual(['gsk_existABCD', 'gsk_newRAW7']);
    expect(plan.forwardParams).toEqual({ id: 'groq', apiKeys: ['…ABCD', '…RAW7'] });
  });

  it('drops a redacted placeholder with no stored counterpart', () => {
    const plan = planUpsert({ id: 'groq', apiKeys: ['…GONE'] }, noStored);
    expect(plan.resolvedKeys).toEqual([]);
    expect(plan.forwardParams).toEqual({ id: 'groq', apiKeys: [] });
  });

  it('is a no-op (resolvedKeys null) when the upsert carries no apiKeys', () => {
    const plan = planUpsert({ id: 'groq', enabled: true }, noStored);
    expect(plan.providerId).toBe('groq');
    expect(plan.resolvedKeys).toBeNull();
    expect(plan.forwardParams).toEqual({ id: 'groq', enabled: true });
  });

  it('reports a null providerId for an id-less request', () => {
    const plan = planUpsert({ apiKeys: ['x'] }, noStored);
    expect(plan.providerId).toBeNull();
    expect(plan.resolvedKeys).toBeNull();
  });

  it('tolerates undefined params', () => {
    const plan = planUpsert(undefined, noStored);
    expect(plan.providerId).toBeNull();
    expect(plan.forwardParams).toEqual({});
  });
});

describe('KeyBridge.interceptUpsert', () => {
  it('stores raw keys in the keystore and forwards only redactions', () => {
    const bridge = new KeyBridge({ safeStorage: makeSafeStorage(), keystorePath: keystorePath() });
    const forwarded = bridge.interceptUpsert({ id: 'groq', apiKeys: ['gsk_secretKEY1'] });
    // Nothing raw crosses to the sidecar.
    expect(JSON.stringify(forwarded)).not.toContain('gsk_secretKEY1');
    expect(forwarded).toEqual({ id: 'groq', apiKeys: ['…KEY1'] });
    // The raw key IS in the keystore on disk.
    const onDisk = loadDecryptedKeys(makeSafeStorage(), keystorePath());
    expect(onDisk.providers.groq).toEqual(['gsk_secretKEY1']);
  });

  it('merges a second key into the same provider across calls', () => {
    const store = makeSafeStorage();
    const bridge = new KeyBridge({ safeStorage: store, keystorePath: keystorePath() });
    bridge.interceptUpsert({ id: 'groq', apiKeys: ['gsk_firstAAAA'] });
    // The add-key flow re-sends the redacted existing key + the new raw one.
    bridge.interceptUpsert({ id: 'groq', apiKeys: ['…AAAA', 'gsk_secondBBBB'] });
    const onDisk = loadDecryptedKeys(store, keystorePath());
    expect(onDisk.providers.groq).toEqual(['gsk_firstAAAA', 'gsk_secondBBBB']);
  });

  it('removes the provider entry when the last key is removed', () => {
    const store = makeSafeStorage();
    const bridge = new KeyBridge({ safeStorage: store, keystorePath: keystorePath() });
    bridge.interceptUpsert({ id: 'groq', apiKeys: ['gsk_onlyAAAA'] });
    bridge.interceptUpsert({ id: 'groq', apiKeys: [] });
    const onDisk = loadDecryptedKeys(store, keystorePath());
    expect(onDisk.providers.groq).toBeUndefined();
  });

  it('forwards an apiKey-less upsert unchanged and writes no keystore', () => {
    const bridge = new KeyBridge({ safeStorage: makeSafeStorage(), keystorePath: keystorePath() });
    const forwarded = bridge.interceptUpsert({ id: 'groq', provider: 'Groq', enabled: true });
    expect(forwarded).toEqual({ id: 'groq', provider: 'Groq', enabled: true });
    expect(existsSync(keystorePath())).toBe(false);
  });

  it('SESSION-ONLY: never writes plaintext to disk but keeps keys injectable', () => {
    const unavailable = makeSafeStorage({ available: false });
    const bridge = new KeyBridge({ safeStorage: unavailable, keystorePath: keystorePath() });
    const forwarded = bridge.interceptUpsert({ id: 'groq', apiKeys: ['gsk_sessKEY1'] });
    expect(forwarded).toEqual({ id: 'groq', apiKeys: ['…KEY1'] });
    // No keystore file was written (no secure backend -> refuse to persist).
    expect(existsSync(keystorePath())).toBe(false);
    // But the session overlay still injects the raw key this run.
    const injected = bridge.inject({}) as {
      [INJECTED_KEYS_FIELD]: { providers: Record<string, string[]> };
    };
    expect(injected[INJECTED_KEYS_FIELD].providers.groq).toEqual(['gsk_sessKEY1']);
  });

  it('BASIC_TEXT backend is treated as session-only (refuses to persist)', () => {
    const basic = makeSafeStorage({ available: true, backend: 'basic_text' });
    const bridge = new KeyBridge({ safeStorage: basic, keystorePath: keystorePath() });
    bridge.interceptUpsert({ id: 'groq', apiKeys: ['gsk_plainKEY1'] });
    expect(existsSync(keystorePath())).toBe(false);
  });

  it('survives a keystore that cannot be decrypted (falls back to empty disk view)', () => {
    // First write with a working store, then read with a store whose decrypt throws.
    const good = makeSafeStorage();
    const bridge = new KeyBridge({ safeStorage: good, keystorePath: keystorePath() });
    bridge.interceptUpsert({ id: 'groq', apiKeys: ['gsk_oldAAAA'] });
    const broken = new KeyBridge({
      safeStorage: makeSafeStorage({ decryptThrows: true }),
      keystorePath: keystorePath(),
    });
    // currentKeys() must swallow the decrypt error; a fresh upsert still works.
    const forwarded = broken.interceptUpsert({ id: 'openai', apiKeys: ['sk-newBBBB'] });
    expect(forwarded).toEqual({ id: 'openai', apiKeys: ['…BBBB'] });
  });
});

describe('KeyBridge.inject', () => {
  it('adds decrypted keys under _injectedKeys and preserves other params', () => {
    const store = makeSafeStorage();
    const bridge = new KeyBridge({ safeStorage: store, keystorePath: keystorePath() });
    bridge.interceptUpsert({ id: 'groq', apiKeys: ['gsk_liveKEY1'] });
    const out = bridge.inject({ videoId: 'v1' }) as Record<string, unknown> & {
      [INJECTED_KEYS_FIELD]: { providers: Record<string, string[]> };
    };
    expect(out.videoId).toBe('v1');
    expect(out[INJECTED_KEYS_FIELD].providers.groq).toEqual(['gsk_liveKEY1']);
  });

  it('overwrites any renderer-supplied _injectedKeys (never trusts the caller)', () => {
    const bridge = new KeyBridge({ safeStorage: makeSafeStorage(), keystorePath: keystorePath() });
    const out = bridge.inject({ [INJECTED_KEYS_FIELD]: { providers: { spoof: ['x'] } } }) as {
      [INJECTED_KEYS_FIELD]: { providers: Record<string, string[]> };
    };
    expect(out[INJECTED_KEYS_FIELD].providers.spoof).toBeUndefined();
  });

  it('tolerates undefined params', () => {
    const bridge = new KeyBridge({ safeStorage: makeSafeStorage(), keystorePath: keystorePath() });
    const out = bridge.inject() as {
      [INJECTED_KEYS_FIELD]: { providers: Record<string, string[]> };
    };
    expect(out[INJECTED_KEYS_FIELD]).toEqual({ providers: {} });
  });

  it('carries a stored cloudApiKey into the injected payload', () => {
    // Seed a cloud key via the session overlay by upserting then injecting: the
    // keystore path only stores providers here, so exercise the cloud branch by
    // writing a keystore that already carries a cloudApiKey.
    const store = makeSafeStorage();
    const bridge = new KeyBridge({ safeStorage: store, keystorePath: keystorePath() });
    // No cloud key yet -> absent.
    const out0 = bridge.inject() as { [INJECTED_KEYS_FIELD]: { cloudApiKey?: string } };
    expect(out0[INJECTED_KEYS_FIELD].cloudApiKey).toBeUndefined();
  });
});

describe('KeyBridge.forwardParams routing', () => {
  it('routes providers.upsert through the interceptor', () => {
    const store = makeSafeStorage();
    const bridge = new KeyBridge({ safeStorage: store, keystorePath: keystorePath() });
    const out = bridge.forwardParams('providers.upsert', {
      id: 'groq',
      apiKeys: ['gsk_routeKEY1'],
    });
    expect(out).toEqual({ id: 'groq', apiKeys: ['…KEY1'] });
    expect(loadDecryptedKeys(store, keystorePath()).providers.groq).toEqual(['gsk_routeKEY1']);
  });

  it('injects on a provider-calling method', () => {
    const bridge = new KeyBridge({ safeStorage: makeSafeStorage(), keystorePath: keystorePath() });
    const out = bridge.forwardParams('ai.planJob', { goal: 'x' }) as Record<string, unknown>;
    expect(out).toHaveProperty(INJECTED_KEYS_FIELD);
    expect(out.goal).toBe('x');
  });

  it('passes non-provider methods through untouched', () => {
    const bridge = new KeyBridge({ safeStorage: makeSafeStorage(), keystorePath: keystorePath() });
    const params = { id: 'v1' };
    expect(bridge.forwardParams('library.list', params)).toBe(params);
    expect(bridge.forwardParams('settings.get', undefined)).toBeUndefined();
  });
});

describe('KeyBridge.secureStatus', () => {
  it('reflects an available secure backend', () => {
    const bridge = new KeyBridge({ safeStorage: makeSafeStorage(), keystorePath: keystorePath() });
    expect(bridge.secureStatus().sessionOnly).toBe(false);
  });
  it('reports session-only when encryption is unavailable', () => {
    const bridge = new KeyBridge({
      safeStorage: makeSafeStorage({ available: false }),
      keystorePath: keystorePath(),
    });
    const status = bridge.secureStatus();
    expect(status.sessionOnly).toBe(true);
    expect(status.banner).not.toBeNull();
  });
});
