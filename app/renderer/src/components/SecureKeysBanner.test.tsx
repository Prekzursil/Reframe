// @vitest-environment jsdom
// SecureKeysBanner.test.tsx — WU-D2b-1 session-only banner. The banner reads the
// preload bridge structurally (window.api.getSecureStatus) and shows a loud alert
// only when main reports `sessionOnly`. Pins: nothing without a bridge, nothing
// for a healthy store, the banner (with explicit or fallback text) on sessionOnly,
// silence on a rejected query, and no state write after unmount.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import {
  keystoreUnreadableBannerText,
  SecureKeysBanner,
  SESSION_ONLY_BANNER,
  unshreddableBannerText,
  type SecureStatus,
} from './SecureKeysBanner';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const getSecureStatus = vi.fn<() => Promise<SecureStatus>>();

/** Install a bridge exposing getSecureStatus. Pass `false` to omit the method. */
function installBridge(withMethod = true): void {
  (window as unknown as { api?: unknown }).api = withMethod ? { getSecureStatus } : {};
}

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  getSecureStatus.mockReset();
  delete (window as unknown as { api?: unknown }).api;
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

/** Mount the banner and flush the mount effect. */
function mount(): void {
  act(() => {
    root.render(<SecureKeysBanner />);
  });
}

/** Flush pending microtasks (the getSecureStatus promise + its .then). */
async function flush(): Promise<void> {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

function banner(): HTMLElement | null {
  return container.querySelector('.secure-keys-banner');
}

describe('SecureKeysBanner', () => {
  it('renders nothing when no bridge is present', async () => {
    mount();
    await flush();
    expect(banner()).toBeNull();
    expect(getSecureStatus).not.toHaveBeenCalled();
  });

  it('renders nothing when the bridge lacks getSecureStatus', async () => {
    installBridge(false);
    mount();
    await flush();
    expect(banner()).toBeNull();
  });

  it('stays hidden when secure storage is available (sessionOnly false)', async () => {
    installBridge();
    getSecureStatus.mockResolvedValue({
      available: true,
      backend: null,
      sessionOnly: false,
      banner: null,
    });
    mount();
    await flush();
    expect(banner()).toBeNull();
  });

  it('stays hidden when the status resolves nullish', async () => {
    installBridge();
    getSecureStatus.mockResolvedValue(null as unknown as SecureStatus);
    mount();
    await flush();
    expect(banner()).toBeNull();
  });

  it('shows the provided banner text on sessionOnly', async () => {
    installBridge();
    getSecureStatus.mockResolvedValue({
      available: false,
      backend: 'basic_text',
      sessionOnly: true,
      banner: 'Keys cannot be saved — session only.',
    });
    mount();
    await flush();
    const el = banner();
    expect(el).not.toBeNull();
    expect(el?.getAttribute('role')).toBe('alert');
    expect(el?.textContent).toBe('Keys cannot be saved — session only.');
  });

  it('falls back to SESSION_ONLY_BANNER when sessionOnly has no message', async () => {
    installBridge();
    getSecureStatus.mockResolvedValue({
      available: false,
      backend: null,
      sessionOnly: true,
      banner: null,
    });
    mount();
    await flush();
    expect(banner()?.textContent).toBe(SESSION_ONLY_BANNER);
  });

  it('stays hidden (never crashes) when the query rejects', async () => {
    installBridge();
    getSecureStatus.mockRejectedValue(new Error('ipc down'));
    mount();
    await flush();
    expect(banner()).toBeNull();
  });

  it('does not update state after unmount (cancelled)', async () => {
    installBridge();
    let resolve!: (s: SecureStatus) => void;
    getSecureStatus.mockReturnValue(
      new Promise<SecureStatus>((r) => {
        resolve = r;
      }),
    );
    mount();
    // Unmount BEFORE the query resolves, then resolve: the cancelled guard must
    // swallow the late result without a React "update on unmounted" warning.
    act(() => root.unmount());
    await act(async () => {
      resolve({ available: false, backend: null, sessionOnly: true, banner: 'late' });
      await Promise.resolve();
    });
    expect(banner()).toBeNull();
    // Re-create a root so afterEach's unmount is a no-op-safe call.
    root = createRoot(container);
  });

  it('surfaces the unshreddable warning even when secure storage is healthy (sessionOnly false)', async () => {
    // The whole point of #263: a migration that SUCCEEDED (keys encrypted, sessionOnly
    // false) but left an old plaintext copy it could not delete must still tell the
    // user — a console.warn in the main process is invisible in a packaged build.
    installBridge();
    getSecureStatus.mockResolvedValue({
      available: true,
      backend: null,
      sessionOnly: false,
      banner: null,
      unshreddable: ['C:/data/settings.json.bak'],
    });
    mount();
    await flush();
    const el = banner();
    expect(el).not.toBeNull();
    expect(el?.getAttribute('role')).toBe('alert');
    expect(el?.textContent).toContain('could not be removed');
    expect(el?.textContent).toContain('C:/data/settings.json.bak');
  });

  it('stacks BOTH the session-only and unshreddable warnings when both apply', async () => {
    installBridge();
    getSecureStatus.mockResolvedValue({
      available: false,
      backend: 'basic_text',
      sessionOnly: true,
      banner: 'Keys cannot be saved — session only.',
      unshreddable: ['/home/u/.config/media-studio/settings.json.old'],
    });
    mount();
    await flush();
    const el = banner();
    expect(el?.querySelectorAll('.secure-keys-banner__message')).toHaveLength(2);
    expect(el?.textContent).toContain('Keys cannot be saved — session only.');
    expect(el?.textContent).toContain('/home/u/.config/media-studio/settings.json.old');
  });

  it('shows no unshreddable warning for an empty list (defined but length 0)', async () => {
    installBridge();
    getSecureStatus.mockResolvedValue({
      available: true,
      backend: null,
      sessionOnly: false,
      banner: null,
      unshreddable: [],
    });
    mount();
    await flush();
    expect(banner()).toBeNull();
  });

  it('surfaces the keystore-unreadable warning even when secure storage is healthy (sessionOnly false)', async () => {
    // F39: main COMPUTES this (keyBridge.ts:234 `keystoreUnreadable: this.readDisk().reason`)
    // and refuses to overwrite the keystore while it is set (keyBridge.ts:276-279), so a
    // saved key silently does not persist. The reason crosses IPC intact, and the renderer
    // dropped it: `messagesFor` emitted lines only for sessionOnly/unshreddable, so with a
    // healthy store and no lingering plaintext the component returned null and the user was
    // told NOTHING. Modelled on the passing additive-axis test above so a harness fault is
    // excluded by construction: identical bridge, identical `sessionOnly:false` shape.
    installBridge();
    getSecureStatus.mockResolvedValue({
      available: true,
      backend: null,
      sessionOnly: false,
      banner: null,
      unshreddable: [],
      keystoreUnreadable: 'decrypt-failed',
    });
    mount();
    await flush();
    const el = banner();
    expect(el).not.toBeNull();
    expect(el?.getAttribute('role')).toBe('alert');
    expect(el?.textContent).toContain('could not be read');
  });

  it('stacks all THREE warnings when sessionOnly, unshreddable and unreadable all apply', async () => {
    installBridge();
    getSecureStatus.mockResolvedValue({
      available: false,
      backend: 'basic_text',
      sessionOnly: true,
      banner: 'Keys cannot be saved — session only.',
      unshreddable: ['/a/x.bak'],
      keystoreUnreadable: 'read-failed',
    });
    mount();
    await flush();
    const el = banner();
    expect(el?.querySelectorAll('.secure-keys-banner__message')).toHaveLength(3);
    expect(el?.textContent).toContain('Keys cannot be saved — session only.');
    expect(el?.textContent).toContain('/a/x.bak');
    expect(el?.textContent).toContain('could not be read');
  });

  // REGRESSION GUARD — passes BOTH before and after the fix (stated honestly: this is not
  // a red-proof). It pins the falsy arm of the new branch for the explicit `null` the wire
  // actually sends for a healthy/absent keystore (keyBridge.test.ts:305-310), so a future
  // truthiness slip cannot start alerting on a perfectly healthy store.
  it('stays hidden when keystoreUnreadable is null (healthy or absent keystore)', async () => {
    installBridge();
    getSecureStatus.mockResolvedValue({
      available: true,
      backend: null,
      sessionOnly: false,
      banner: null,
      unshreddable: [],
      keystoreUnreadable: null,
    });
    mount();
    await flush();
    expect(banner()).toBeNull();
  });
});

describe('unshreddableBannerText', () => {
  it('uses singular grammar for one lingering copy', () => {
    const text = unshreddableBannerText(['/a/settings.json.bak']);
    expect(text).toContain('1 old plaintext API-key file ');
    expect(text).toContain('remains readable on disk');
    expect(text).toContain('Delete it manually: /a/settings.json.bak');
  });

  it('uses plural grammar and joins every path for multiple copies', () => {
    const text = unshreddableBannerText(['/a/x.bak', '/b/y.old']);
    expect(text).toContain('2 old plaintext API-key files ');
    expect(text).toContain('remain readable on disk');
    expect(text).toContain('Delete them manually: /a/x.bak, /b/y.old');
  });
});

describe('keystoreUnreadableBannerText', () => {
  // One case per KeystoreUnreadableReason. These PIN THE COPY; they are not needed for
  // the branch gate (a Record property read is a statement, not a branch under v8).
  it.each([
    ['read-failed', 'another program may be holding it open'],
    ['parse-failed', 'an earlier save was probably interrupted'],
    ['shape-invalid', 'not in the expected format'],
    ['decrypt-failed', 'copied from another machine or user profile'],
  ] as const)('names the cause for %s', (reason, cause) => {
    const text = keystoreUnreadableBannerText(reason);
    expect(text).toContain('could not be read');
    expect(text).toContain(cause);
  });

  it('never claims permanent loss and never names a data folder', () => {
    // Both refusals are load-bearing: a `read-failed` lock can be transient, and the
    // keystore lives under Electron's userData dir — NOT the user-chosen data folder —
    // so naming that folder would send the user to the wrong place.
    for (const reason of [
      'read-failed',
      'parse-failed',
      'shape-invalid',
      'decrypt-failed',
    ] as const) {
      const text = keystoreUnreadableBannerText(reason);
      expect(text).toContain('Try restarting the app');
      expect(text).not.toMatch(/permanent|lost forever|deleted/i);
      expect(text).not.toMatch(/data folder/i);
    }
  });
});
