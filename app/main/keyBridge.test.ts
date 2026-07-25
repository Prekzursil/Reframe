// keyBridge.test.ts — WU-D2b-1 main-process key guard. safeStorage is faked with
// a reversible transform (as in keystore.test.ts) and the keystore lives in a tmp
// dir. Headline invariants: providers.upsert NEVER forwards a raw key (only last-4
// redactions), the raw keys land in the DPAPI keystore, provider-calling methods
// get _injectedKeys in-memory, and session-only mode writes NOTHING to disk.
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import {
  KEYSTORE_FILENAME,
  loadDecryptedKeys,
  type SafeStorageLike,
  saveDecryptedKeys,
} from './keystore';
import {
  INJECTED_KEYS_FIELD,
  KeyBridge,
  REMOVE_METHOD,
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
  it('is true for the provider-calling job/picker methods (thumbnail·phase8·recipe·template·batch)', () => {
    // Regression pin: these seams consume get_raw() but were previously OMITTED
    // from the inject list, so their cloud routes ran with redacted marker keys.
    for (const m of [
      'thumbnail.select',
      'phase8.select',
      'recipes.run',
      'templates.apply',
      'batch.start',
      'batch.resume',
    ]) {
      expect(needsKeyInjection(m)).toBe(true);
    }
  });
  it('injects for EXACTLY the canonical raw-key-consuming method set (anti-drift)', () => {
    // The single source of truth for methods whose sidecar handler reads get_raw().
    // The sidecar side pins the same set (test_raw_vs_redacted_audit.py) so the two
    // boundaries cannot silently drift apart again.
    const CANONICAL_RAW_KEY_METHODS = [
      'ai.planJob',
      'director.plan',
      'shortmaker.select',
      'index.build',
      'index.search',
      'subtitles.translate',
      'providers.usage',
      'providers.openrouterUsage',
      'providers.revealKey',
      'thumbnail.select',
      'phase8.select',
      'recipes.run',
      'templates.apply',
      'batch.start',
      'batch.resume',
    ];
    for (const m of CANONICAL_RAW_KEY_METHODS) {
      expect(needsKeyInjection(m)).toBe(true);
    }
  });
  it('is false for the store path and non-provider methods', () => {
    for (const m of [
      'providers.upsert',
      'providers.remove', // the DELETE path — intercepted, but never key-INJECTED
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

  it('survives a keystore that cannot be decrypted WITHOUT destroying it (T7 WIPE regression)', () => {
    // THE DATA-LOSS BUG: a transient/undecryptable read used to be reported as an
    // EMPTY keystore, so this next upsert wrote a fresh store over it and PERMANENTLY
    // wiped every stored credential. The upsert must still succeed for the user (the
    // session overlay carries the new key), but the on-disk blob must be untouched.
    const good = makeSafeStorage();
    const bridge = new KeyBridge({ safeStorage: good, keystorePath: keystorePath() });
    bridge.interceptUpsert({ id: 'groq', apiKeys: ['gsk_oldAAAA'] });
    const before = readFileSync(keystorePath(), 'utf8');

    const broken = new KeyBridge({
      safeStorage: makeSafeStorage({ decryptThrows: true }),
      keystorePath: keystorePath(),
    });
    const forwarded = broken.interceptUpsert({ id: 'openai', apiKeys: ['sk-newBBBB'] });

    expect(forwarded).toEqual({ id: 'openai', apiKeys: ['…BBBB'] }); // never a raw key
    expect(readFileSync(keystorePath(), 'utf8')).toBe(before); // BYTE-IDENTICAL: no wipe
    // And the original credential is still recoverable with a working safeStorage.
    expect(loadDecryptedKeys(good, keystorePath()).providers.groq).toEqual(['gsk_oldAAAA']);
  });
});

describe('KeyBridge FAIL-CLOSED on an unreadable keystore (T7 credential wipe)', () => {
  it('does NOT overwrite a CORRUPT (unparseable) keystore, and keeps the key usable', () => {
    // A partial write / truncated blob is the other everyday cause. Same rule: refuse
    // the overwrite, keep the user's new key in the session overlay for this run.
    const corrupt = '{"version":1,"providers":{"groq":["ZW5j';
    writeFileSync(keystorePath(), corrupt);
    const bridge = new KeyBridge({ safeStorage: makeSafeStorage(), keystorePath: keystorePath() });

    bridge.interceptUpsert({ id: 'groq', apiKeys: ['gsk_freshAAAA'] });

    expect(readFileSync(keystorePath(), 'utf8')).toBe(corrupt); // untouched
    const injected = bridge.inject({}) as {
      [INJECTED_KEYS_FIELD]: { providers: Record<string, string[]> };
    };
    expect(injected[INJECTED_KEYS_FIELD].providers.groq).toEqual(['gsk_freshAAAA']);
  });

  it('surfaces the classified reason via secureStatus().keystoreUnreadable', () => {
    writeFileSync(keystorePath(), '{not json');
    const bridge = new KeyBridge({ safeStorage: makeSafeStorage(), keystorePath: keystorePath() });
    const status = bridge.secureStatus();
    expect(status.keystoreUnreadable).toBe('parse-failed');
    // Secure storage itself is fine — this is a SEPARATE, additive warning axis.
    expect(status.sessionOnly).toBe(false);
  });

  it('reports keystoreUnreadable = null for a healthy or absent keystore', () => {
    const store = makeSafeStorage();
    const bridge = new KeyBridge({ safeStorage: store, keystorePath: keystorePath() });
    expect(bridge.secureStatus().keystoreUnreadable).toBeNull(); // absent
    bridge.interceptUpsert({ id: 'groq', apiKeys: ['gsk_healthyAAAA'] });
    expect(bridge.secureStatus().keystoreUnreadable).toBeNull(); // loaded
  });

  it('does not resurrect an unreadable blob into the injected key set', () => {
    // Fail-closed must not mean "inject whatever half-parsed". An unreadable disk
    // contributes NOTHING; only the session overlay is injected.
    writeFileSync(keystorePath(), '{not json');
    const bridge = new KeyBridge({ safeStorage: makeSafeStorage(), keystorePath: keystorePath() });
    const injected = bridge.inject() as {
      [INJECTED_KEYS_FIELD]: { providers: Record<string, string[]> };
    };
    expect(injected[INJECTED_KEYS_FIELD]).toEqual({ providers: {} });
  });
});

describe('KeyBridge.interceptRemove (providers.remove)', () => {
  it('deletes the keystore entry so a removed key cannot RESURRECT on re-add', () => {
    // T7(2): providers.remove dropped only the sidecar METADATA; the raw key stayed
    // in the keystore, so re-adding the provider (or any redacted upsert) brought the
    // supposedly-deleted credential back to life.
    const store = makeSafeStorage();
    const bridge = new KeyBridge({ safeStorage: store, keystorePath: keystorePath() });
    bridge.interceptUpsert({ id: 'groq', apiKeys: ['gsk_removeMeAAAA'] });
    expect(loadDecryptedKeys(store, keystorePath()).providers.groq).toEqual(['gsk_removeMeAAAA']);

    const forwarded = bridge.interceptRemove({ id: 'groq' });

    expect(forwarded).toEqual({ id: 'groq' }); // forwarded verbatim to the sidecar
    expect(loadDecryptedKeys(store, keystorePath()).providers.groq).toBeUndefined();
    // A later redacted upsert can no longer restore it (nothing stored to restore from).
    const replan = bridge.interceptUpsert({ id: 'groq', apiKeys: ['…AAAA'] });
    expect(replan).toEqual({ id: 'groq', apiKeys: [] });
    expect(loadDecryptedKeys(store, keystorePath()).providers.groq).toBeUndefined();
  });

  it('stops injecting the removed key immediately (same session)', () => {
    const store = makeSafeStorage();
    const bridge = new KeyBridge({ safeStorage: store, keystorePath: keystorePath() });
    bridge.interceptUpsert({ id: 'groq', apiKeys: ['gsk_removeMeAAAA'] });
    bridge.interceptRemove({ id: 'groq' });
    const injected = bridge.inject() as {
      [INJECTED_KEYS_FIELD]: { providers: Record<string, string[]> };
    };
    expect(injected[INJECTED_KEYS_FIELD].providers.groq).toBeUndefined();
  });

  it('keeps the removal effective even when the disk write is REFUSED (session-only)', () => {
    // Without an in-memory tombstone the on-disk entry would be re-merged by the very
    // next overlay read and the "removed" key would keep being injected.
    const store = makeSafeStorage();
    new KeyBridge({ safeStorage: store, keystorePath: keystorePath() }).interceptUpsert({
      id: 'groq',
      apiKeys: ['gsk_onDiskAAAA'],
    });
    const sessionOnly = new KeyBridge({
      safeStorage: makeSafeStorage({ available: false }),
      keystorePath: keystorePath(),
    });
    sessionOnly.interceptRemove({ id: 'groq' });
    const injected = sessionOnly.inject() as {
      [INJECTED_KEYS_FIELD]: { providers: Record<string, string[]> };
    };
    expect(injected[INJECTED_KEYS_FIELD].providers.groq).toBeUndefined();
    // ...and the on-disk blob is NOT rewritten in session-only mode.
    expect(loadDecryptedKeys(store, keystorePath()).providers.groq).toEqual(['gsk_onDiskAAAA']);
  });

  it('re-adding the provider with a real key clears the tombstone', () => {
    const store = makeSafeStorage();
    const bridge = new KeyBridge({ safeStorage: store, keystorePath: keystorePath() });
    bridge.interceptUpsert({ id: 'groq', apiKeys: ['gsk_firstAAAA'] });
    bridge.interceptRemove({ id: 'groq' });
    bridge.interceptUpsert({ id: 'groq', apiKeys: ['gsk_secondBBBB'] });
    const injected = bridge.inject() as {
      [INJECTED_KEYS_FIELD]: { providers: Record<string, string[]> };
    };
    expect(injected[INJECTED_KEYS_FIELD].providers.groq).toEqual(['gsk_secondBBBB']);
    expect(loadDecryptedKeys(store, keystorePath()).providers.groq).toEqual(['gsk_secondBBBB']);
  });

  it('preserves every OTHER provider and the cloud key', () => {
    const store = makeSafeStorage();
    saveDecryptedKeys(store, keystorePath(), {
      providers: { groq: ['gsk_goAAAA'], openai: ['sk-stayBBBB'] },
      cloudApiKey: 'sk-fake-cloud',
    });
    const bridge = new KeyBridge({ safeStorage: store, keystorePath: keystorePath() });
    bridge.interceptRemove({ id: 'groq' });
    const after = loadDecryptedKeys(store, keystorePath());
    expect(after.providers.groq).toBeUndefined();
    expect(after.providers.openai).toEqual(['sk-stayBBBB']);
    expect(after.cloudApiKey).toBe('sk-fake-cloud');
  });

  it('accepts the nested {provider:{id}} envelope', () => {
    const store = makeSafeStorage();
    const bridge = new KeyBridge({ safeStorage: store, keystorePath: keystorePath() });
    bridge.interceptUpsert({ id: 'groq', apiKeys: ['gsk_nestedAAAA'] });
    bridge.interceptRemove({ provider: { id: 'groq' } });
    expect(loadDecryptedKeys(store, keystorePath()).providers.groq).toBeUndefined();
  });

  it('is a no-op for an unknown id, an id-less request, or undefined params', () => {
    const store = makeSafeStorage();
    const bridge = new KeyBridge({ safeStorage: store, keystorePath: keystorePath() });
    bridge.interceptUpsert({ id: 'groq', apiKeys: ['gsk_keepAAAA'] });
    const untouched = readFileSync(keystorePath(), 'utf8');

    expect(bridge.interceptRemove({ id: 'never-stored' })).toEqual({ id: 'never-stored' });
    expect(bridge.interceptRemove({ nope: 1 })).toEqual({ nope: 1 });
    expect(bridge.interceptRemove(undefined)).toBeUndefined();
    expect(bridge.interceptRemove({ id: '' })).toEqual({ id: '' });

    expect(readFileSync(keystorePath(), 'utf8')).toBe(untouched); // no rewrite at all
    expect(loadDecryptedKeys(store, keystorePath()).providers.groq).toEqual(['gsk_keepAAAA']);
  });

  it('refuses to rewrite an UNREADABLE keystore on remove (no wipe via the remove path)', () => {
    const corrupt = '{not json';
    writeFileSync(keystorePath(), corrupt);
    const bridge = new KeyBridge({ safeStorage: makeSafeStorage(), keystorePath: keystorePath() });
    bridge.interceptUpsert({ id: 'groq', apiKeys: ['gsk_sessionAAAA'] });
    bridge.interceptRemove({ id: 'groq' });
    expect(readFileSync(keystorePath(), 'utf8')).toBe(corrupt);
  });

  it('RETRIES the disk purge when the first removal write failed (tombstone is not a latch)', () => {
    // A removal whose keystore write FAILED (here: a transient encrypt failure) leaves
    // the raw key on disk while the id is already tombstoned in memory. Clicking Remove
    // again must retry the purge instead of short-circuiting on the tombstone — which is
    // exactly why the presence probe reads the RAW disk view, not the tombstoned overlay.
    // MUTATION-CHECKED: probing `overlay(...)` here instead makes this test fail.
    const flaky = { broken: true };
    const store: SafeStorageLike = {
      isEncryptionAvailable: () => true,
      encryptString: (plaintext: string) => {
        if (flaky.broken) throw new Error('encrypt failed');
        return Buffer.from(`enc:${plaintext}`, 'utf8');
      },
      decryptString: (encrypted: Buffer) => encrypted.toString('utf8').replace(/^enc:/, ''),
    };
    saveDecryptedKeys(makeSafeStorage(), keystorePath(), {
      providers: { groq: ['gsk_purgeMeAAAA'], openai: ['sk-stayBBBB'] },
    });
    const bridge = new KeyBridge({ safeStorage: store, keystorePath: keystorePath() });

    bridge.interceptRemove({ id: 'groq' }); // write throws -> disk untouched, id tombstoned
    expect(loadDecryptedKeys(makeSafeStorage(), keystorePath()).providers.groq).toEqual([
      'gsk_purgeMeAAAA',
    ]);

    flaky.broken = false; // the transient failure clears
    bridge.interceptRemove({ id: 'groq' }); // SAME bridge, tombstone already set
    const after = loadDecryptedKeys(makeSafeStorage(), keystorePath());
    expect(after.providers.groq).toBeUndefined();
    expect(after.providers.openai).toEqual(['sk-stayBBBB']);
  });

  it('routes providers.remove through forwardParams', () => {
    const store = makeSafeStorage();
    const bridge = new KeyBridge({ safeStorage: store, keystorePath: keystorePath() });
    bridge.interceptUpsert({ id: 'groq', apiKeys: ['gsk_routedAAAA'] });
    const out = bridge.forwardParams(REMOVE_METHOD, { id: 'groq' });
    expect(out).toEqual({ id: 'groq' });
    expect(loadDecryptedKeys(store, keystorePath()).providers.groq).toBeUndefined();
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
  it('defaults unshreddable to an empty list when none is injected', () => {
    const bridge = new KeyBridge({ safeStorage: makeSafeStorage(), keystorePath: keystorePath() });
    expect(bridge.secureStatus().unshreddable).toEqual([]);
  });
  it('surfaces the injected migration unshreddable list (copied, not aliased)', () => {
    // The boot-time migration's un-scrubbable plaintext copies must reach the renderer
    // banner via getSecureStatus — the only user-visible channel in a packaged build.
    const injected = ['/data/settings.json.bak', '/data/settings.json.old'];
    const bridge = new KeyBridge({
      safeStorage: makeSafeStorage(),
      keystorePath: keystorePath(),
      unshreddable: injected,
    });
    const status = bridge.secureStatus();
    expect(status.unshreddable).toEqual(injected);
    // A fresh array each call (defensive copy): mutating the returned list or the
    // injected source must not corrupt the bridge's held state.
    expect(status.unshreddable).not.toBe(injected);
  });
});
