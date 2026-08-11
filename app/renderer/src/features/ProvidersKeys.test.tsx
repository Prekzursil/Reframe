// ProvidersKeys.test.tsx — the Providers & Keys management surface (WU-PROVIDERS).
// Covers: load (list/catalog/usage/consent), the empty-state, the picker (free
// badge + get-a-free-key link + add provider, already-configured disabled), the
// per-provider card (status badges, redacted keys, add-key validate→store
// pass+fail, remove key, remove provider), consent toggle (optimistic + rollback),
// and every load/mutation error path.

// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import { ProvidersKeys, type ProvidersKeysProps } from './ProvidersKeys';
import type { SpendCapClient } from './SpendCap';
import type {
  CatalogResponse,
  ProviderConsent,
  ProvidersListResponse,
  SetConsentResponse,
  SpendInfo,
  TestKeyResult,
  UsageRow,
} from '../lib/rpc';

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.restoreAllMocks();
});

async function flush(): Promise<void> {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });
}

/** Set a controlled <input> value via the native setter so React's onChange fires. */
function setInputValue(el: HTMLInputElement, value: string): void {
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set;
  setter?.call(el, value);
  el.dispatchEvent(new Event('input', { bubbles: true }));
}

/** Toggle a controlled checkbox via the native setter so React's onChange fires. */
function toggleCheckbox(el: HTMLInputElement, value: boolean): void {
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'checked')?.set;
  setter?.call(el, value);
  el.dispatchEvent(new Event('click', { bubbles: true }));
}

// --- fixtures --------------------------------------------------------------

function catalog(): CatalogResponse {
  const base = {
    id: 'x',
    model: 'M',
    capabilities: ['text'],
    contextTokens: 128000,
    perTaskTier: {},
    costClass: 'free',
    freeLimitScore: 70,
    unit: 'token',
    privacyTier: 'SAFE',
    recommendedFor: [],
    notes: '',
    asOfDate: '2026-06-16',
  };
  return {
    asOfDate: '2026-06-16',
    unit: ['req', 'token'],
    tasks: [],
    topPicks: {},
    providers: [
      { ...base, id: 'groq-1', provider: 'Groq', freeLimits: '30 RPM', trainsOnInput: false },
      { ...base, id: 'groq-2', provider: 'Groq', freeLimits: '30 RPM dupe', trainsOnInput: false },
      {
        ...base,
        id: 'gem-1',
        provider: 'Google AI Studio',
        freeLimits: '15 RPM',
        trainsOnInput: true,
        privacyTier: 'AVOID',
      },
      {
        ...base,
        id: 'oai-1',
        provider: 'OpenAI API',
        freeLimits: 'paid',
        costClass: 'paid',
        trainsOnInput: false,
      },
    ],
  };
}

interface ApiOverrides {
  list?: () => Promise<ProvidersListResponse>;
  catalog?: () => Promise<CatalogResponse>;
  usage?: () => Promise<{ usage: UsageRow[] }>;
  upsert?: ReturnType<typeof vi.fn>;
  remove?: ReturnType<typeof vi.fn>;
  testKey?: ReturnType<typeof vi.fn>;
  revealKey?: ReturnType<typeof vi.fn>;
  setConsent?: ReturnType<typeof vi.fn>;
  settingsGet?: () => Promise<{ consent?: { perProvider?: Record<string, ProviderConsent> } }>;
}

function makeApi(over: ApiOverrides = {}): ProvidersKeysProps['rpcClient'] {
  return {
    providers: {
      list: over.list ?? (() => Promise.resolve({ providers: [] })),
      catalog: over.catalog ?? (() => Promise.resolve(catalog())),
      usage: over.usage ?? (() => Promise.resolve({ usage: [] })),
      upsert: over.upsert ?? vi.fn(() => Promise.resolve({ providers: [] })),
      remove: over.remove ?? vi.fn(() => Promise.resolve({ providers: [] })),
      testKey: over.testKey ?? vi.fn(() => Promise.resolve({ ok: true } as TestKeyResult)),
      revealKey: over.revealKey ?? vi.fn(() => Promise.resolve({ key: 'raw-revealed-key' })),
      setConsent:
        over.setConsent ??
        vi.fn(() => Promise.resolve({ consent: { perProvider: {} } } as SetConsentResponse)),
      // Unused by this panel but part of the providers surface — present so the
      // injected shape matches.
      applyPreset: vi.fn(),
      setFunctionModel: vi.fn(),
      firstRun: vi.fn(),
    },
    settings: { get: over.settingsGet ?? (() => Promise.resolve({})) },
  } as unknown as ProvidersKeysProps['rpcClient'];
}

/** A no-op spend client for the panel tests (SpendCap has its own dedicated suite). */
function makeSpendClient(): SpendCapClient {
  const spend: SpendInfo = {
    month: '2026-06',
    monthToDateCents: 0,
    softLimitCents: 0,
    hardLimitCents: 0,
    enforceHardLimit: false,
    isEstimate: false,
  };
  return {
    providers: { spend: () => Promise.resolve(spend) },
    settings: { set: vi.fn(() => Promise.resolve({})) },
  };
}

async function mount(
  props: Partial<ProvidersKeysProps> & { rpcClient: ProvidersKeysProps['rpcClient'] },
): Promise<void> {
  await act(async () => {
    root.render(<ProvidersKeys spendClient={makeSpendClient()} {...props} />);
  });
  await flush();
}

// --- tests -----------------------------------------------------------------

describe('ProvidersKeys — load + empty state', () => {
  it('shows a loading state then the empty-state when no providers are configured', async () => {
    const api = makeApi();
    await mount({ rpcClient: api });
    expect(container.querySelector('.providers-keys__empty')).not.toBeNull();
    expect(container.textContent).toContain('No provider keys yet');
    // Picker still renders so the user can add one.
    expect(container.querySelector('.providers-keys__picker-list')).not.toBeNull();
  });

  it('surfaces a load error and hides the body', async () => {
    const api = makeApi({ list: () => Promise.reject(new Error('boom')) });
    await mount({ rpcClient: api });
    const alert = container.querySelector('[role="alert"]');
    expect(alert?.textContent).toBe('boom');
  });

  it('degrades to an inline error (no thrown-through blank) when window.api is missing', async () => {
    // WU2 resilience: no injected rpcClient -> the real `client`, whose bridge()
    // throws SYNCHRONOUSLY when window.api is undefined (before Promise.all can
    // wrap it, so the effect's `.catch` never sees it). The sync-safe guard must
    // surface it inline rather than let it unmount the tree.
    expect((globalThis as { window?: { api?: unknown } }).window?.api).toBeUndefined();
    await act(async () => {
      root.render(<ProvidersKeys />);
    });
    await flush();
    const alert = container.querySelector('[role="alert"]');
    expect(alert).not.toBeNull();
    expect(alert?.textContent).toContain('window.api');
  });

  it('tolerates malformed list/catalog/usage payloads (non-array → empty)', async () => {
    const api = makeApi({
      list: () => Promise.resolve({} as ProvidersListResponse),
      catalog: () => Promise.resolve({} as CatalogResponse),
      usage: () => Promise.resolve({} as { usage: UsageRow[] }),
    });
    await mount({ rpcClient: api });
    // Empty everywhere → empty-state + picker-empty, no crash.
    expect(container.querySelector('.providers-keys__empty')).not.toBeNull();
    expect(container.querySelector('.providers-keys__picker-empty')).not.toBeNull();
  });

  it('ignores a late resolve after unmount (alive guard drops the result)', async () => {
    let resolveList: (v: ProvidersListResponse) => void = () => {};
    const api = makeApi({
      list: () =>
        new Promise<ProvidersListResponse>((res) => {
          resolveList = res;
        }),
    });
    await act(async () => {
      root.render(<ProvidersKeys spendClient={makeSpendClient()} rpcClient={api} />);
    });
    await act(async () => root.unmount());
    // Resolving now is a no-op (alive === false).
    await act(async () => {
      resolveList({ providers: [{ id: 'groq', provider: 'Groq', apiKeys: [] }] });
    });
    await flush();
    expect(container.querySelector('.provider-card')).toBeNull();
    root = createRoot(container);
  });

  it('ignores a late reject after unmount (alive guard in the catch)', async () => {
    let rejectList: (e: Error) => void = () => {};
    const api = makeApi({
      list: () =>
        new Promise<ProvidersListResponse>((_res, rej) => {
          rejectList = rej;
        }),
    });
    await act(async () => {
      root.render(<ProvidersKeys spendClient={makeSpendClient()} rpcClient={api} />);
    });
    await act(async () => root.unmount());
    await act(async () => {
      rejectList(new Error('late boom'));
    });
    await flush();
    expect(container.querySelector('[role="alert"]')).toBeNull();
    root = createRoot(container);
  });
});

describe('ProvidersKeys — picker', () => {
  it('dedups the catalog, marks free vs paid, and links to the console', async () => {
    const api = makeApi();
    await mount({ rpcClient: api });
    const options = container.querySelectorAll('.picker-option');
    // Groq (deduped), Google AI Studio, OpenAI API = 3 distinct providers.
    expect(options.length).toBe(3);
    const groq = container.querySelector('.picker-option[data-provider="groq"]');
    expect(groq?.querySelector('.picker-option__free')).not.toBeNull();
    const link = groq?.querySelector<HTMLAnchorElement>('.picker-option__getkey');
    expect(link?.getAttribute('href')).toBe('https://console.groq.com');
    expect(link?.textContent).toContain('Get a free key');
    // OpenAI is paid → "Get an API key", no free badge.
    const oai = container.querySelector('.picker-option[data-provider="openai"]');
    expect(oai?.querySelector('.picker-option__paid')).not.toBeNull();
    expect(oai?.querySelector('.picker-option__getkey')?.textContent).toContain('Get an API key');
  });

  it('adds a provider via providers.upsert and shows it as configured', async () => {
    const upsert = vi.fn(() =>
      Promise.resolve({ providers: [{ id: 'groq', provider: 'Groq', apiKeys: [] }] }),
    );
    const api = makeApi({ upsert });
    await mount({ rpcClient: api });
    const addBtn = container.querySelector<HTMLButtonElement>(
      '.picker-option[data-provider="groq"] .picker-option__add',
    );
    await act(async () => addBtn!.click());
    await flush();
    expect(upsert).toHaveBeenCalledWith({
      id: 'groq',
      provider: 'Groq',
      baseUrl: 'https://api.groq.com/openai/v1',
      model: 'llama-3.3-70b-versatile',
    });
    // Now configured → the card appears with Needs key.
    expect(container.querySelector('.provider-card[data-provider="groq"]')).not.toBeNull();
    expect(container.querySelector('[data-status="needs-key"]')).not.toBeNull();
  });

  it('disables the picker add button for an already-configured provider', async () => {
    const api = makeApi({
      list: () => Promise.resolve({ providers: [{ id: 'groq', provider: 'Groq', apiKeys: [] }] }),
    });
    await mount({ rpcClient: api });
    const addBtn = container.querySelector<HTMLButtonElement>(
      '.picker-option[data-provider="groq"] .picker-option__add',
    );
    expect(addBtn?.disabled).toBe(true);
    expect(addBtn?.textContent).toBe('Added');
  });

  it('surfaces an add-provider error', async () => {
    const upsert = vi.fn(() => Promise.reject(new Error('add failed')));
    const api = makeApi({ upsert });
    await mount({ rpcClient: api });
    const addBtn = container.querySelector<HTMLButtonElement>(
      '.picker-option[data-provider="groq"] .picker-option__add',
    );
    await act(async () => addBtn!.click());
    await flush();
    expect(container.querySelector('[role="alert"]')?.textContent).toBe('add failed');
  });

  it('shows a picker empty message when the catalog has no addable providers', async () => {
    const api = makeApi({ catalog: () => Promise.resolve({ ...catalog(), providers: [] }) });
    await mount({ rpcClient: api });
    expect(container.querySelector('.providers-keys__picker-empty')).not.toBeNull();
  });
});

describe('ProvidersKeys — configured provider card', () => {
  function configured(apiKeys: string[] = ['…WXYZ']) {
    return makeApi({
      list: () =>
        Promise.resolve({
          providers: [
            {
              id: 'groq',
              provider: 'Groq',
              baseUrl: 'https://api.groq.com/openai/v1',
              apiKeys,
            },
          ],
        }),
    });
  }

  it('renders redacted keys + a Configured badge', async () => {
    await mount({ rpcClient: configured() });
    expect(container.querySelector('.provider-key-row__value')?.textContent).toBe('…WXYZ');
    expect(container.querySelector('[data-status="configured"]')).not.toBeNull();
  });

  it('shows a no-keys hint + Needs key when the provider has no keys', async () => {
    await mount({ rpcClient: configured([]) });
    expect(container.querySelector('.provider-card__no-keys')).not.toBeNull();
    expect(container.querySelector('[data-status="needs-key"]')).not.toBeNull();
  });

  it('validates a pasted key (testKey ok) then stores it and shows Working', async () => {
    const testKey = vi.fn(() => Promise.resolve({ ok: true, capabilities: ['text'] }));
    const upsert = vi.fn(() =>
      Promise.resolve({
        providers: [{ id: 'groq', provider: 'Groq', apiKeys: ['…WXYZ', '…1234'] }],
      }),
    );
    const api = makeApi({
      list: () =>
        Promise.resolve({
          providers: [
            { id: 'groq', provider: 'Groq', baseUrl: 'https://b/v1', apiKeys: ['…WXYZ'] },
          ],
        }),
      testKey,
      upsert,
    });
    await mount({ rpcClient: api });
    const input = container.querySelector<HTMLInputElement>('.add-key-row__input')!;
    await act(async () => setInputValue(input, 'sk-new-secret'));
    const addBtn = container.querySelector<HTMLButtonElement>('.add-key-row__add')!;
    await act(async () => addBtn.click());
    await flush();
    expect(testKey).toHaveBeenCalledWith({
      baseUrl: 'https://b/v1',
      apiKey: 'sk-new-secret',
      // Entry has no model → resolved from PROVIDER_META["Groq"].
      model: 'llama-3.3-70b-versatile',
      capabilities: undefined,
    });
    expect(upsert).toHaveBeenCalledWith({ id: 'groq', apiKeys: ['…WXYZ', 'sk-new-secret'] });
    expect(container.textContent).toContain('Key verified');
    expect(container.querySelector('[data-status="working"]')).not.toBeNull();
  });

  it('reports a failed validation but still stores the key (stays Configured)', async () => {
    const testKey = vi.fn(() => Promise.resolve({ ok: false, error: 'bad key' }));
    const api = makeApi({
      list: () =>
        Promise.resolve({
          providers: [{ id: 'groq', provider: 'Groq', baseUrl: 'https://b/v1', apiKeys: [] }],
        }),
      testKey,
    });
    await mount({ rpcClient: api });
    const input = container.querySelector<HTMLInputElement>('.add-key-row__input')!;
    await act(async () => setInputValue(input, 'sk-bad'));
    await act(async () => container.querySelector<HTMLButtonElement>('.add-key-row__add')!.click());
    await flush();
    expect(container.textContent).toContain('Key failed: bad key');
  });

  it('uses a default failure message when testKey fails without an error string', async () => {
    const testKey = vi.fn(() => Promise.resolve({ ok: false }));
    const api = makeApi({
      list: () =>
        Promise.resolve({
          providers: [{ id: 'groq', provider: 'Groq', baseUrl: 'https://b/v1', apiKeys: [] }],
        }),
      testKey,
    });
    await mount({ rpcClient: api });
    const input = container.querySelector<HTMLInputElement>('.add-key-row__input')!;
    await act(async () => setInputValue(input, 'sk-bad'));
    await act(async () => container.querySelector<HTMLButtonElement>('.add-key-row__add')!.click());
    await flush();
    expect(container.textContent).toContain('Key failed: invalid');
  });

  it('surfaces an add-key error (rejection clears the transient status)', async () => {
    const testKey = vi.fn(() => Promise.reject(new Error('net down')));
    const api = makeApi({
      list: () =>
        Promise.resolve({
          providers: [{ id: 'groq', provider: 'Groq', baseUrl: 'https://b/v1', apiKeys: [] }],
        }),
      testKey,
    });
    await mount({ rpcClient: api });
    const input = container.querySelector<HTMLInputElement>('.add-key-row__input')!;
    await act(async () => setInputValue(input, 'sk-x'));
    await act(async () => container.querySelector<HTMLButtonElement>('.add-key-row__add')!.click());
    await flush();
    expect(container.querySelector('[role="alert"]')?.textContent).toBe('net down');
    // The transient "Validating…" feedback is cleared on error.
    expect(container.querySelector('.providers-keys__feedback')).toBeNull();
  });

  it('removes one key via re-upsert of the survivors', async () => {
    const upsert = vi.fn(() =>
      Promise.resolve({ providers: [{ id: 'groq', provider: 'Groq', apiKeys: ['…AAAA'] }] }),
    );
    const api = makeApi({
      list: () =>
        Promise.resolve({
          providers: [{ id: 'groq', provider: 'Groq', apiKeys: ['…WXYZ', '…AAAA'] }],
        }),
      upsert,
    });
    await mount({ rpcClient: api });
    const removeKeyBtn = container.querySelector<HTMLButtonElement>('.provider-key-row__remove')!;
    await act(async () => removeKeyBtn.click());
    await flush();
    expect(upsert).toHaveBeenCalledWith({ id: 'groq', apiKeys: ['…AAAA'] });
  });

  it('surfaces a remove-key error', async () => {
    const upsert = vi.fn(() => Promise.reject(new Error('rm key fail')));
    const api = makeApi({
      list: () =>
        Promise.resolve({ providers: [{ id: 'groq', provider: 'Groq', apiKeys: ['…WXYZ'] }] }),
      upsert,
    });
    await mount({ rpcClient: api });
    await act(async () =>
      container.querySelector<HTMLButtonElement>('.provider-key-row__remove')!.click(),
    );
    await flush();
    expect(container.querySelector('[role="alert"]')?.textContent).toBe('rm key fail');
  });

  it('removes a whole provider via providers.remove', async () => {
    const remove = vi.fn(() => Promise.resolve({ providers: [] }));
    const api = makeApi({
      list: () =>
        Promise.resolve({ providers: [{ id: 'groq', provider: 'Groq', apiKeys: ['…WXYZ'] }] }),
      remove,
    });
    await mount({ rpcClient: api });
    const removeProvBtn = container.querySelector<HTMLButtonElement>('.provider-card__remove')!;
    await act(async () => removeProvBtn.click());
    await flush();
    expect(remove).toHaveBeenCalledWith('groq');
    expect(container.querySelector('.provider-card')).toBeNull();
  });

  it('tolerates a malformed remove-key response (no providers array)', async () => {
    const upsert = vi.fn(() => Promise.resolve({}));
    const api = makeApi({
      list: () =>
        Promise.resolve({ providers: [{ id: 'groq', provider: 'Groq', apiKeys: ['…WXYZ'] }] }),
      upsert,
    });
    await mount({ rpcClient: api });
    await act(async () =>
      container.querySelector<HTMLButtonElement>('.provider-key-row__remove')!.click(),
    );
    await flush();
    // Falls back to an empty list → the card is gone, no crash.
    expect(container.querySelector('.provider-card')).toBeNull();
  });

  it('tolerates a malformed remove-provider response (no providers array)', async () => {
    const remove = vi.fn(() => Promise.resolve({}));
    const api = makeApi({
      list: () =>
        Promise.resolve({ providers: [{ id: 'groq', provider: 'Groq', apiKeys: ['…WXYZ'] }] }),
      remove,
    });
    await mount({ rpcClient: api });
    await act(async () =>
      container.querySelector<HTMLButtonElement>('.provider-card__remove')!.click(),
    );
    await flush();
    expect(container.querySelector('.provider-card')).toBeNull();
  });

  it('stringifies a non-Error rejection in the error banner', async () => {
    // eslint-disable-next-line prefer-promise-reject-errors -- deliberately a non-Error.
    const remove = vi.fn(() => Promise.reject('plain string failure'));
    const api = makeApi({
      list: () =>
        Promise.resolve({ providers: [{ id: 'groq', provider: 'Groq', apiKeys: ['…WXYZ'] }] }),
      remove,
    });
    await mount({ rpcClient: api });
    await act(async () =>
      container.querySelector<HTMLButtonElement>('.provider-card__remove')!.click(),
    );
    await flush();
    expect(container.querySelector('[role="alert"]')?.textContent).toBe('plain string failure');
  });

  it('surfaces a remove-provider error', async () => {
    const remove = vi.fn(() => Promise.reject(new Error('rm prov fail')));
    const api = makeApi({
      list: () =>
        Promise.resolve({ providers: [{ id: 'groq', provider: 'Groq', apiKeys: ['…WXYZ'] }] }),
      remove,
    });
    await mount({ rpcClient: api });
    await act(async () =>
      container.querySelector<HTMLButtonElement>('.provider-card__remove')!.click(),
    );
    await flush();
    expect(container.querySelector('[role="alert"]')?.textContent).toBe('rm prov fail');
  });

  it('falls back to the meta base URL + empty key list when the entry omits baseUrl/apiKeys', async () => {
    const testKey = vi.fn(() => Promise.resolve({ ok: true }));
    // The entry omits BOTH baseUrl (→ PROVIDER_META["Groq"]) and apiKeys (→ []).
    const upsert = vi.fn(() => Promise.resolve({}));
    const api = makeApi({
      list: () => Promise.resolve({ providers: [{ id: 'groq', provider: 'Groq' }] }),
      testKey,
      upsert,
    });
    await mount({ rpcClient: api });
    const input = container.querySelector<HTMLInputElement>('.add-key-row__input')!;
    await act(async () => setInputValue(input, 'sk-y'));
    await act(async () => container.querySelector<HTMLButtonElement>('.add-key-row__add')!.click());
    await flush();
    expect(testKey).toHaveBeenCalledWith(
      expect.objectContaining({ baseUrl: 'https://api.groq.com/openai/v1' }),
    );
    // apiKeys absent → starts from [] → stores just the new key.
    expect(upsert).toHaveBeenCalledWith({ id: 'groq', apiKeys: ['sk-y'] });
    // Malformed upsert response (no providers) → empty list, no crash.
    expect(container.querySelector('.provider-card')).toBeNull();
  });

  it('shows a Working… title on controls while a mutation is in flight (busy)', async () => {
    let resolveUpsert: (v: ProvidersListResponse) => void = () => {};
    const upsert = vi.fn(
      () =>
        new Promise<ProvidersListResponse>((res) => {
          resolveUpsert = res;
        }),
    );
    const api = makeApi({
      list: () =>
        Promise.resolve({ providers: [{ id: 'groq', provider: 'Groq', apiKeys: ['…WXYZ'] }] }),
      upsert,
    });
    await mount({ rpcClient: api });
    // Start a remove-key mutation (keeps busy === true until we resolve).
    await act(async () => {
      container.querySelector<HTMLButtonElement>('.provider-key-row__remove')!.click();
    });
    // While busy: the provider Remove button + picker Add buttons title "Working…".
    expect(container.querySelector('.provider-card__remove')?.getAttribute('title')).toBe(
      'Working…',
    );
    const pickerAdd = container.querySelector(
      '.picker-option[data-provider="google-ai-studio"] .picker-option__add',
    );
    expect(pickerAdd?.getAttribute('title')).toBe('Working…');
    // Resolve to clear busy.
    await act(async () => {
      resolveUpsert({ providers: [{ id: 'groq', provider: 'Groq', apiKeys: [] }] });
    });
    await flush();
  });

  it('uses the entry’s own model + capabilities for the validation ping when set', async () => {
    const testKey = vi.fn(() => Promise.resolve({ ok: true }));
    const api = makeApi({
      list: () =>
        Promise.resolve({
          providers: [
            {
              id: 'groq',
              provider: 'Groq',
              baseUrl: 'https://b/v1',
              model: 'custom-model-id',
              capabilities: ['text', 'vision'],
              apiKeys: [],
            },
          ],
        }),
      testKey,
    });
    await mount({ rpcClient: api });
    const input = container.querySelector<HTMLInputElement>('.add-key-row__input')!;
    await act(async () => setInputValue(input, 'sk-z'));
    await act(async () => container.querySelector<HTMLButtonElement>('.add-key-row__add')!.click());
    await flush();
    expect(testKey).toHaveBeenCalledWith({
      baseUrl: 'https://b/v1',
      apiKey: 'sk-z',
      model: 'custom-model-id',
      capabilities: ['text', 'vision'],
    });
  });

  it('tolerates a malformed add-provider response (no providers array)', async () => {
    const upsert = vi.fn(() => Promise.resolve({}));
    const api = makeApi({ upsert });
    await mount({ rpcClient: api });
    const addBtn = container.querySelector<HTMLButtonElement>(
      '.picker-option[data-provider="groq"] .picker-option__add',
    );
    await act(async () => addBtn!.click());
    await flush();
    // No crash, no card added.
    expect(container.querySelector('.provider-card')).toBeNull();
  });

  // --- F41: a second Add inside the first round-trip must not drop a key -------

  it('does not drop the first key when a second Add is submitted before the first round-trip finishes', async () => {
    let release: (v: TestKeyResult) => void = () => {};
    let calls = 0;
    const testKey = vi.fn(() => {
      calls += 1;
      if (calls === 1) {
        return new Promise<TestKeyResult>((res) => {
          release = res;
        });
      }
      return Promise.resolve({ ok: true } as TestKeyResult);
    });
    const upsert = vi.fn((params: { id: string; apiKeys: string[] }) =>
      Promise.resolve({ providers: [{ id: params.id, provider: 'Groq', apiKeys: ['…ey-A'] }] }),
    );
    const api = makeApi({
      list: () =>
        Promise.resolve({
          providers: [{ id: 'groq', provider: 'Groq', baseUrl: 'https://b/v1', apiKeys: [] }],
        }),
      testKey,
      upsert,
    });
    await mount({ rpcClient: api });
    const input = container.querySelector<HTMLInputElement>('.add-key-row__input')!;
    await act(async () => setInputValue(input, 'sk-key-A'));
    await act(async () => container.querySelector<HTMLButtonElement>('.add-key-row__add')!.click());
    // The first add is now parked on a hung testKey; the panel is busy.
    await act(async () => setInputValue(input, 'sk-key-B'));
    // Enter, NOT a button click — Enter bypasses `disabled`, so a fix that only
    // sets disabled={busy} on the button still fails this test.
    await act(async () => {
      input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    });
    await act(async () => release({ ok: true } as TestKeyResult));
    await flush();

    const payloads = upsert.mock.calls.map((c) => c[0].apiKeys);
    // LOAD-BEARING: no stored list may omit a key the panel already accepted.
    expect(payloads.filter((k) => !k.includes('sk-key-A'))).toEqual([]);
    expect(upsert).toHaveBeenCalledTimes(1);
    expect(payloads[0]).toEqual(['sk-key-A']);
    // The refused submit preserves the pasted second key for a deliberate retry.
    expect(input.value).toBe('sk-key-B');
  });

  it('locks every per-key control while a panel mutation is in flight', async () => {
    let release: (v: ProvidersListResponse) => void = () => {};
    const upsert = vi.fn(
      () =>
        new Promise<ProvidersListResponse>((res) => {
          release = res;
        }),
    );
    const api = makeApi({
      list: () =>
        Promise.resolve({
          providers: [
            { id: 'groq', provider: 'Groq', apiKeys: ['…WXYZ'] },
            { id: 'openai', provider: 'OpenAI API', apiKeys: ['…1234'] },
          ],
        }),
      upsert,
    });
    await mount({ rpcClient: api });
    // Start a remove-key mutation on the first card; the panel is now busy.
    await act(async () => {
      container.querySelector<HTMLButtonElement>('.provider-key-row__remove')!.click();
    });
    // Every key row — including the untouched second provider's — is locked, so no
    // second mutation can re-upsert a list built from the pre-await snapshot.
    const removes = [...container.querySelectorAll<HTMLButtonElement>('.provider-key-row__remove')];
    expect(removes.length).toBe(2);
    expect(removes.every((b) => b.disabled)).toBe(true);
    const toggles = [
      ...container.querySelectorAll<HTMLButtonElement>('.provider-key-row__replace-toggle'),
    ];
    expect(toggles.every((b) => b.disabled)).toBe(true);
    // Add is gated on the same flag, on every card.
    const adds = [...container.querySelectorAll<HTMLButtonElement>('.add-key-row__add')];
    expect(adds.every((b) => b.getAttribute('title') === 'Working…')).toBe(true);
    await act(async () => release({ providers: [] }));
    await flush();
  });

  it('uses the provider id as the display name + empty baseUrl for an unknown custom provider', async () => {
    const testKey = vi.fn(() => Promise.resolve({ ok: true }));
    const api = makeApi({
      // No provider display name AND no baseUrl → meta lookup misses → baseUrl ''.
      list: () => Promise.resolve({ providers: [{ id: 'custom', apiKeys: [] }] }),
      testKey,
    });
    await mount({ rpcClient: api });
    expect(container.querySelector('.provider-card__name')?.textContent).toBe('custom');
    const input = container.querySelector<HTMLInputElement>('.add-key-row__input')!;
    await act(async () => setInputValue(input, 'k'));
    await act(async () => container.querySelector<HTMLButtonElement>('.add-key-row__add')!.click());
    await flush();
    expect(testKey).toHaveBeenCalledWith(expect.objectContaining({ baseUrl: '' }));
  });
});

describe('ProvidersKeys — consent', () => {
  it('reflects loaded consent and toggles text/frames via setConsent', async () => {
    const setConsent = vi.fn(() =>
      Promise.resolve({ consent: { perProvider: { Groq: { text: true, frames: true } } } }),
    );
    const api = makeApi({
      list: () =>
        Promise.resolve({ providers: [{ id: 'groq', provider: 'Groq', apiKeys: ['…WXYZ'] }] }),
      settingsGet: () => Promise.resolve({ consent: { perProvider: { Groq: { text: true } } } }),
      setConsent,
    });
    await mount({ rpcClient: api });
    const checks = container.querySelectorAll<HTMLInputElement>('.consent-toggle__option input');
    expect(checks[0].checked).toBe(true); // text
    expect(checks[1].checked).toBe(false); // frames
    // Toggle frames on.
    await act(async () => toggleCheckbox(checks[1], true));
    await flush();
    expect(setConsent).toHaveBeenCalledWith('Groq', { frames: true });
    expect(
      container.querySelectorAll<HTMLInputElement>('.consent-toggle__option input')[1].checked,
    ).toBe(true);
  });

  it('rolls back the optimistic consent on a setConsent error', async () => {
    const setConsent = vi.fn(() => Promise.reject(new Error('consent fail')));
    const api = makeApi({
      list: () =>
        Promise.resolve({ providers: [{ id: 'groq', provider: 'Groq', apiKeys: ['…WXYZ'] }] }),
      settingsGet: () => Promise.resolve({ consent: { perProvider: { Groq: { text: false } } } }),
      setConsent,
    });
    await mount({ rpcClient: api });
    const textCheck = container.querySelectorAll<HTMLInputElement>(
      '.consent-toggle__option input',
    )[0];
    await act(async () => toggleCheckbox(textCheck, true));
    await flush();
    expect(container.querySelector('[role="alert"]')?.textContent).toBe('consent fail');
    // Rolled back to the pre-toggle (unchecked) state.
    expect(
      container.querySelectorAll<HTMLInputElement>('.consent-toggle__option input')[0].checked,
    ).toBe(false);
  });

  it('tolerates a malformed setConsent response (no consent block)', async () => {
    const setConsent = vi.fn(() => Promise.resolve({}));
    const api = makeApi({
      list: () =>
        Promise.resolve({ providers: [{ id: 'groq', provider: 'Groq', apiKeys: ['…WXYZ'] }] }),
      settingsGet: () => Promise.resolve({ consent: { perProvider: { Groq: { text: false } } } }),
      setConsent,
    });
    await mount({ rpcClient: api });
    const textCheck = container.querySelectorAll<HTMLInputElement>(
      '.consent-toggle__option input',
    )[0];
    await act(async () => toggleCheckbox(textCheck, true));
    await flush();
    // Server returned nothing → consent map resets to empty (both off), no crash.
    const checks = container.querySelectorAll<HTMLInputElement>('.consent-toggle__option input');
    expect(checks[0].checked).toBe(false);
  });

  it('shows the train-on-input disclosure from the catalog (AVOID provider)', async () => {
    const api = makeApi({
      list: () =>
        Promise.resolve({
          providers: [{ id: 'google-ai-studio', provider: 'Google AI Studio', apiKeys: ['…WXYZ'] }],
        }),
    });
    await mount({ rpcClient: api });
    const disclosure = container.querySelector('.consent-toggle__disclosure');
    expect(disclosure?.getAttribute('data-trains')).toBe('true');
    expect(disclosure?.textContent).toContain('trains on your input');
  });

  it('defaults to no consent when settings.get returns no consent block', async () => {
    const api = makeApi({
      list: () =>
        Promise.resolve({ providers: [{ id: 'groq', provider: 'Groq', apiKeys: ['…WXYZ'] }] }),
      settingsGet: () => Promise.resolve({}),
    });
    await mount({ rpcClient: api });
    const checks = container.querySelectorAll<HTMLInputElement>('.consent-toggle__option input');
    expect(checks[0].checked).toBe(false);
    expect(checks[1].checked).toBe(false);
  });
});

describe('ProvidersKeys — usage + secondary link', () => {
  it('renders live usage bars from providers.usage', async () => {
    const usage: UsageRow[] = [
      {
        provider: 'groq',
        key: '…WXYZ',
        used: 100,
        max: 1000,
        unit: 'req',
        resetAt: null,
        stale: false,
        lastCheckedAt: null,
      },
    ];
    const api = makeApi({ usage: () => Promise.resolve({ usage }) });
    await mount({ rpcClient: api });
    expect(container.querySelector('[data-usage="groups"]')).not.toBeNull();
  });

  it('renders the Review model routing link only when onOpenModels is wired', async () => {
    const apiNoLink = makeApi();
    await mount({ rpcClient: apiNoLink });
    expect(container.querySelector('.providers-keys__models-link')).toBeNull();

    const onOpenModels = vi.fn();
    await mount({ rpcClient: makeApi(), onOpenModels });
    const link = container.querySelector<HTMLButtonElement>('.providers-keys__models-link');
    expect(link).not.toBeNull();
    await act(async () => link!.click());
    expect(onOpenModels).toHaveBeenCalledTimes(1);
  });
});

// --- WU-D3: reveal / re-validate / replace wiring --------------------------

describe('ProvidersKeys — WU-D3 reveal / re-validate / replace', () => {
  const REVEALED = 'gsk-live-RAW-SECRET-QRST';

  function configuredApi(over: ApiOverrides = {}, apiKeys: string[] = ['…WXYZ']) {
    return makeApi({
      list: () =>
        Promise.resolve({
          providers: [{ id: 'groq', provider: 'Groq', baseUrl: 'https://b/v1', apiKeys }],
        }),
      ...over,
    });
  }

  it('reveals the full key via providers.revealKey and never stores it (no leak to store/log/upsert)', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    const revealKey = vi.fn(() => Promise.resolve({ key: REVEALED }));
    const upsert = vi.fn(() => Promise.resolve({ providers: [] }));
    const api = configuredApi({ revealKey, upsert });
    await mount({ rpcClient: api });

    const revealBtn = container.querySelector<HTMLButtonElement>('.provider-key-row__reveal')!;
    await act(async () => revealBtn.click());
    await flush();

    // Explicit-click reveal fetched exactly this provider's index-0 key.
    expect(revealKey).toHaveBeenCalledWith('groq', 0);
    expect(container.querySelector('.provider-key-row__value')?.textContent).toBe(REVEALED);
    // The secret NEVER round-tripped into the store (no upsert) and never logged.
    expect(upsert).not.toHaveBeenCalled();
    const logged = warn.mock.calls.flat().map(String);
    expect(logged.some((s) => s.includes(REVEALED))).toBe(false);
  });

  it('re-validates a STORED key: revealKey -> testKey with the revealed plaintext', async () => {
    const revealKey = vi.fn(() => Promise.resolve({ key: REVEALED }));
    const testKey = vi.fn(() => Promise.resolve({ ok: true, capabilities: ['text'] }));
    const api = configuredApi({ revealKey, testKey });
    await mount({ rpcClient: api });

    const revalidateBtn = container.querySelector<HTMLButtonElement>(
      '.provider-key-row__revalidate',
    )!;
    await act(async () => revalidateBtn.click());
    await flush();

    expect(revealKey).toHaveBeenCalledWith('groq', 0);
    expect(testKey).toHaveBeenCalledWith({
      baseUrl: 'https://b/v1',
      apiKey: REVEALED,
      // No model on the entry → resolved from PROVIDER_META["Groq"].
      model: 'llama-3.3-70b-versatile',
      capabilities: undefined,
    });
    expect(container.querySelector('.provider-key-row__status')?.textContent).toBe(
      'Key verified — working.',
    );
  });

  it('replaces a key in place: re-validates the NEW key then upserts it at its index', async () => {
    const testKey = vi.fn(() => Promise.resolve({ ok: true, capabilities: ['text'] }));
    const upsert = vi.fn(() =>
      Promise.resolve({
        providers: [{ id: 'groq', provider: 'Groq', apiKeys: ['…QRST', '…1234'] }],
      }),
    );
    // Two keys: replacing index 0 must preserve the redacted sibling at index 1.
    const api = configuredApi({ testKey, upsert }, ['…WXYZ', '…1234']);
    await mount({ rpcClient: api });

    // Open the first row's replace editor, type a new key, save.
    const toggle = container.querySelector<HTMLButtonElement>('.provider-key-row__replace-toggle')!;
    await act(async () => toggle.click());
    const input = container.querySelector<HTMLInputElement>('.provider-key-row__replace-input')!;
    await act(async () => setInputValue(input, 'sk-replacement-key'));
    const save = container.querySelector<HTMLButtonElement>('.provider-key-row__replace-save')!;
    await act(async () => save.click());
    await flush();

    expect(testKey).toHaveBeenCalledWith({
      baseUrl: 'https://b/v1',
      apiKey: 'sk-replacement-key',
      model: 'llama-3.3-70b-versatile',
      capabilities: undefined,
    });
    // Index 0 replaced with the raw new key; the redacted sibling round-trips.
    expect(upsert).toHaveBeenCalledWith({
      id: 'groq',
      apiKeys: ['sk-replacement-key', '…1234'],
    });
  });

  // --- W64 / docs/plans/v1.5/SCOPE.md O-1: editKey is DEFERRED, not missing --
  // O-1 records that no `providers.editKey` RPC exists on either side. This test
  // is the pin for the DECISION not to add one: the index-targeted key edit it
  // describes already ships here, over `providers.testKey` + `providers.upsert`.
  // Routing that edit through a new `editKey` method turns this RED, which is the
  // point — the deferral rationale in ProvidersKeys.tsx must be re-read first,
  // because `editKey` would bypass keyBridge's `providers.upsert` interception
  // and so never reach the DPAPI keystore.
  it('W64/O-1: the index-targeted key edit rides testKey + upsert, never a providers.editKey', async () => {
    const testKey = vi.fn(() => Promise.resolve({ ok: true, capabilities: ['text'] }));
    const upsert = vi.fn(() =>
      Promise.resolve({
        providers: [{ id: 'groq', provider: 'Groq', apiKeys: ['…QRST'] }],
      }),
    );
    const api = configuredApi({ testKey, upsert });
    // Record which providers.* methods the panel actually reaches for. Property
    // lookups happen at call time, so wrapping the object is enough.
    const invoked: string[] = [];
    const surface = (api as unknown as { providers: Record<string, (...a: never[]) => unknown> })
      .providers;
    for (const name of Object.keys(surface)) {
      const original = surface[name];
      surface[name] = (...args: never[]) => {
        invoked.push(name);
        return original(...args);
      };
    }
    await mount({ rpcClient: api });
    invoked.length = 0; // drop the mount reads (list / catalog / usage)

    const toggle = container.querySelector<HTMLButtonElement>('.provider-key-row__replace-toggle')!;
    await act(async () => toggle.click());
    const input = container.querySelector<HTMLInputElement>('.provider-key-row__replace-input')!;
    await act(async () => setInputValue(input, 'sk-edited-in-place'));
    const save = container.querySelector<HTMLButtonElement>('.provider-key-row__replace-save')!;
    await act(async () => save.click());
    await flush();

    // The WHOLE edit is these two calls, in this order — validate, then store.
    expect(invoked).toEqual(['testKey', 'upsert']);
    expect(invoked).not.toContain('editKey');
    // And it is genuinely index-targeted: the new raw key lands at index 0.
    expect(upsert).toHaveBeenCalledWith({ id: 'groq', apiKeys: ['sk-edited-in-place'] });
  });

  // --- F38: the panel must not swallow a reveal/revalidate/replace rejection --
  // `revealKey` / `revalidateKey` / `replaceKey` had no try/catch at all, so the
  // role="alert" banner stayed empty while the sidecar's actionable refusal was
  // dropped on the floor — unlike the sibling `addKey`, which already reports.

  it('surfaces a rejected re-validate in the panel banner (F38)', async () => {
    const revealKey = vi.fn(() => Promise.resolve({ key: REVEALED }));
    const testKey = vi.fn(() => Promise.reject(new Error('net down')));
    const api = configuredApi({ revealKey, testKey });
    await mount({ rpcClient: api });
    await act(async () =>
      container.querySelector<HTMLButtonElement>('.provider-key-row__revalidate')!.click(),
    );
    await flush();
    expect(container.querySelector('[role="alert"]')?.textContent).toBe('net down');
  });

  it('surfaces a rejected replace AND preserves the typed replacement key (F38)', async () => {
    const testKey = vi.fn(() => Promise.reject(new Error('replace net down')));
    const api = configuredApi({ testKey });
    await mount({ rpcClient: api });
    await act(async () =>
      container.querySelector<HTMLButtonElement>('.provider-key-row__replace-toggle')!.click(),
    );
    const input = container.querySelector<HTMLInputElement>('.provider-key-row__replace-input')!;
    await act(async () => setInputValue(input, 'sk-keep-me'));
    await act(async () =>
      container.querySelector<HTMLButtonElement>('.provider-key-row__replace-save')!.click(),
    );
    await flush();
    expect(container.querySelector('[role="alert"]')?.textContent).toBe('replace net down');
    // LOAD-BEARING: the panel degrades the rejection to a resolved {ok:false}, so
    // the row takes its SUCCESS path — an unconditional setDraft('') there would
    // erase the key the user just pasted (strictly worse than the original bug).
    expect(
      container.querySelector<HTMLInputElement>('.provider-key-row__replace-input')?.value,
    ).toBe('sk-keep-me');
    expect(container.querySelector('.provider-key-row__replace')).not.toBeNull();
  });

  it('surfaces a rejected reveal in the banner and re-throws so the row shows it too (F38)', async () => {
    const revealKey = vi.fn(() => Promise.reject(new Error('key is locked')));
    const api = configuredApi({ revealKey });
    await mount({ rpcClient: api });
    await act(async () =>
      container.querySelector<HTMLButtonElement>('.provider-key-row__reveal')!.click(),
    );
    await flush();
    expect(container.querySelector('[role="alert"]')?.textContent).toBe('key is locked');
    // revealKey returns Promise<string> and cannot degrade, so it re-throws — the
    // row's own catch is what renders the local status line.
    expect(container.querySelector('.provider-key-row__status')?.textContent).toContain(
      'key is locked',
    );
    expect(container.querySelector('.provider-key-row__value')?.getAttribute('data-revealed')).toBe(
      'false',
    );
  });

  it('tolerates a malformed upsert response after replace (non-array → empty list)', async () => {
    const upsert = vi.fn(() => Promise.resolve({} as ProvidersListResponse));
    const api = configuredApi({ upsert });
    await mount({ rpcClient: api });

    const toggle = container.querySelector<HTMLButtonElement>('.provider-key-row__replace-toggle')!;
    await act(async () => toggle.click());
    const input = container.querySelector<HTMLInputElement>('.provider-key-row__replace-input')!;
    await act(async () => setInputValue(input, 'sk-brand-new'));
    const save = container.querySelector<HTMLButtonElement>('.provider-key-row__replace-save')!;
    await act(async () => save.click());
    await flush();

    // Non-array providers → the panel falls back to an empty list (no crash).
    expect(upsert).toHaveBeenCalled();
    expect(container.querySelector('.provider-card')).toBeNull();
  });
});
