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
});

describe('unshreddableBannerText', () => {
  it('uses singular grammar for one lingering copy', () => {
    const text = unshreddableBannerText(['/a/settings.json.bak']);
    expect(text).toContain('1 old plaintext API-key file ');
    expect(text).toContain('Delete it manually: /a/settings.json.bak');
  });

  it('uses plural grammar and joins every path for multiple copies', () => {
    const text = unshreddableBannerText(['/a/x.bak', '/b/y.old']);
    expect(text).toContain('2 old plaintext API-key files ');
    expect(text).toContain('Delete them manually: /a/x.bak, /b/y.old');
  });
});
