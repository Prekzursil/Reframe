// ipc.test.ts — WU-D2b-1 wiring of the DPAPI key guard into the `rpc` bridge.
// Electron ipcMain is mocked; a fake Sidecar records forwarded requests and a real
// KeyBridge (fake safeStorage + tmp keystore) drives the transform. Pins: raw keys
// are stripped from providers.upsert before they reach the sidecar, provider-calling
// methods gain _injectedKeys, non-provider methods pass through, the secure.status
// channel is served only with a bridge, and the disposer removes every handler.
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  handle: vi.fn(),
  removeHandler: vi.fn(),
}));

vi.mock('electron', () => ({
  ipcMain: { handle: mocks.handle, removeHandler: mocks.removeHandler },
}));

import { KEYSTORE_FILENAME, loadDecryptedKeys, type SafeStorageLike } from './keystore';
import { INJECTED_KEYS_FIELD, KeyBridge } from './keyBridge';
import { RPC_CHANNEL, SECURE_STATUS_CHANNEL, SIDECAR_RESTART_CHANNEL, registerIpc } from './ipc';
import type { Sidecar } from './sidecar';

function makeSafeStorage(available = true): SafeStorageLike {
  return {
    isEncryptionAvailable: () => available,
    encryptString: (plaintext: string) => Buffer.from(`enc:${plaintext}`, 'utf8'),
    decryptString: (encrypted: Buffer) => encrypted.toString('utf8').replace(/^enc:/, ''),
  };
}

/** A fake Sidecar recording forwarded requests; on/off are inert no-ops. */
function makeSidecar(): { sidecar: Sidecar; request: ReturnType<typeof vi.fn> } {
  const request = vi.fn(async () => ({ ok: true }));
  const sidecar = {
    request,
    restart: vi.fn(async () => ({ ok: true })),
    on: vi.fn(),
    off: vi.fn(),
  } as unknown as Sidecar;
  return { sidecar, request };
}

/** Invoke the ipcMain.handle handler registered for `channel`. */
function invoke(channel: string, ...args: unknown[]): unknown {
  const call = mocks.handle.mock.calls.find(([ch]) => ch === channel);
  if (!call) throw new Error(`no handler registered for ${channel}`);
  return (call[1] as (...a: unknown[]) => unknown)({}, ...args);
}

function registeredChannels(): string[] {
  return mocks.handle.mock.calls.map(([ch]) => ch as string);
}

let dir: string;
beforeEach(() => {
  mocks.handle.mockReset();
  mocks.removeHandler.mockReset();
  dir = mkdtempSync(join(tmpdir(), 'ipc-test-'));
});
afterEach(() => {
  rmSync(dir, { recursive: true, force: true });
});
const keystorePath = (): string => join(dir, KEYSTORE_FILENAME);

describe('registerIpc — key guard wiring', () => {
  it('strips raw keys from providers.upsert before forwarding to the sidecar', async () => {
    const { sidecar, request } = makeSidecar();
    const bridge = new KeyBridge({ safeStorage: makeSafeStorage(), keystorePath: keystorePath() });
    registerIpc(sidecar, () => [], bridge);

    await invoke(RPC_CHANNEL, {
      method: 'providers.upsert',
      params: { id: 'groq', apiKeys: ['gsk_topSECRET1'] },
    });

    const [method, forwarded] = request.mock.calls[0];
    expect(method).toBe('providers.upsert');
    expect(JSON.stringify(forwarded)).not.toContain('gsk_topSECRET1');
    expect(forwarded).toEqual({ id: 'groq', apiKeys: ['…RET1'] });
    // The raw key was diverted into the keystore.
    expect(loadDecryptedKeys(makeSafeStorage(), keystorePath()).providers.groq).toEqual([
      'gsk_topSECRET1',
    ]);
  });

  it('injects decrypted keys into a provider-calling method', async () => {
    const { sidecar, request } = makeSidecar();
    const bridge = new KeyBridge({ safeStorage: makeSafeStorage(), keystorePath: keystorePath() });
    registerIpc(sidecar, () => [], bridge);
    // Seed a key so injection carries something.
    await invoke(RPC_CHANNEL, {
      method: 'providers.upsert',
      params: { id: 'groq', apiKeys: ['gsk_liveKEY1'] },
    });

    await invoke(RPC_CHANNEL, { method: 'ai.planJob', params: { goal: 'x' } });
    const call = request.mock.calls.find(([m]) => m === 'ai.planJob');
    const forwarded = call?.[1] as Record<string, unknown> & {
      [INJECTED_KEYS_FIELD]: { providers: Record<string, string[]> };
    };
    expect(forwarded.goal).toBe('x');
    expect(forwarded[INJECTED_KEYS_FIELD].providers.groq).toEqual(['gsk_liveKEY1']);
  });

  it('passes non-provider methods through unchanged', async () => {
    const { sidecar, request } = makeSidecar();
    const bridge = new KeyBridge({ safeStorage: makeSafeStorage(), keystorePath: keystorePath() });
    registerIpc(sidecar, () => [], bridge);
    await invoke(RPC_CHANNEL, { method: 'library.list' });
    expect(request).toHaveBeenCalledWith('library.list', undefined);
  });

  it('forwards params verbatim when no keyBridge is wired (legacy behavior)', async () => {
    const { sidecar, request } = makeSidecar();
    registerIpc(sidecar, () => []);
    await invoke(RPC_CHANNEL, {
      method: 'providers.upsert',
      params: { id: 'groq', apiKeys: ['gsk_raw'] },
    });
    expect(request).toHaveBeenCalledWith('providers.upsert', { id: 'groq', apiKeys: ['gsk_raw'] });
    // Without a bridge there is no secure.status channel.
    expect(registeredChannels()).not.toContain(SECURE_STATUS_CHANNEL);
  });

  it('serves secure.status from the bridge', async () => {
    const { sidecar } = makeSidecar();
    const bridge = new KeyBridge({
      safeStorage: makeSafeStorage(false),
      keystorePath: keystorePath(),
    });
    registerIpc(sidecar, () => [], bridge);
    const status = (await invoke(SECURE_STATUS_CHANNEL)) as { sessionOnly: boolean };
    expect(status.sessionOnly).toBe(true);
  });

  it('the disposer removes every handler (incl. secure.status only when wired)', () => {
    const { sidecar } = makeSidecar();
    const bridge = new KeyBridge({ safeStorage: makeSafeStorage(), keystorePath: keystorePath() });
    const dispose = registerIpc(sidecar, () => [], bridge);
    dispose();
    const removed = mocks.removeHandler.mock.calls.map(([ch]) => ch as string);
    expect(removed).toContain(RPC_CHANNEL);
    expect(removed).toContain(SIDECAR_RESTART_CHANNEL);
    expect(removed).toContain(SECURE_STATUS_CHANNEL);
  });

  it('the disposer skips secure.status when no bridge was wired', () => {
    const { sidecar } = makeSidecar();
    const dispose = registerIpc(sidecar, () => []);
    dispose();
    const removed = mocks.removeHandler.mock.calls.map(([ch]) => ch as string);
    expect(removed).not.toContain(SECURE_STATUS_CHANNEL);
  });
});
