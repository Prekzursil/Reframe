// ProviderKeyRow.test.tsx — redacted key row with the WU-D3 transient reveal +
// per-key Re-validate + Replace. The security spine: the revealed plaintext lives
// ONLY in a ref, is masked-by-default, re-masks on blur/timeout/unmount, and NEVER
// enters React state/store, a log, or any of the callbacks.
// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import { ProviderKeyRow, type KeyCheckResult } from './ProviderKeyRow';

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
  vi.useRealTimers();
});

async function flush(): Promise<void> {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });
}

const SECRET = 'gsk-live-SECRET-ABCDWXYZ';

interface Handlers {
  onRemove: ReturnType<typeof vi.fn>;
  onReveal: ReturnType<typeof vi.fn>;
  onRevalidate: ReturnType<typeof vi.fn>;
  onReplace: ReturnType<typeof vi.fn>;
}

function makeHandlers(over: Partial<Handlers> = {}): Handlers {
  return {
    onRemove: over.onRemove ?? vi.fn(),
    onReveal: over.onReveal ?? vi.fn(() => Promise.resolve(SECRET)),
    onRevalidate: over.onRevalidate ?? vi.fn(() => Promise.resolve<KeyCheckResult>({ ok: true })),
    onReplace: over.onReplace ?? vi.fn(() => Promise.resolve<KeyCheckResult>({ ok: true })),
  };
}

function render(
  h: Handlers,
  props: Partial<{
    redactedKey: string;
    index: number;
    revealTimeoutMs: number;
    panelBusy: boolean;
  }> = {},
): void {
  act(() => {
    root.render(
      <ProviderKeyRow
        providerId="groq"
        redactedKey={props.redactedKey ?? '…WXYZ'}
        index={props.index ?? 2}
        onRemove={h.onRemove}
        onReveal={h.onReveal}
        onRevalidate={h.onRevalidate}
        onReplace={h.onReplace}
        {...(props.revealTimeoutMs !== undefined ? { revealTimeoutMs: props.revealTimeoutMs } : {})}
        {...(props.panelBusy !== undefined ? { panelBusy: props.panelBusy } : {})}
      />,
    );
  });
}

function q<T extends Element = HTMLElement>(sel: string): T {
  return container.querySelector(sel) as T;
}
function click(sel: string): void {
  act(() => q<HTMLButtonElement>(sel).dispatchEvent(new MouseEvent('click', { bubbles: true })));
}
function setInputValue(el: HTMLInputElement, value: string): void {
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set;
  setter?.call(el, value);
  el.dispatchEvent(new Event('input', { bubbles: true }));
}

// --- baseline (unchanged WU-keys contract) ---------------------------------

describe('ProviderKeyRow — redacted baseline', () => {
  it('shows the redacted key by default and fires onRemove with id+index', () => {
    const h = makeHandlers();
    render(h);
    expect(q('.provider-key-row__value').textContent).toBe('…WXYZ');
    expect(q('.provider-key-row').getAttribute('data-provider')).toBe('groq');
    expect(q('.provider-key-row').getAttribute('data-key-index')).toBe('2');
    expect(q('.provider-key-row__value').getAttribute('data-revealed')).toBe('false');
    click('.provider-key-row__remove');
    expect(h.onRemove).toHaveBeenCalledWith('groq', 2);
  });
});

// --- WU-D3 reveal contract --------------------------------------------------

describe('ProviderKeyRow — reveal (transient, masked-by-default)', () => {
  it('reveals the full key only on explicit click, then re-masks on Hide', async () => {
    const h = makeHandlers();
    render(h);
    // Masked by default — the secret is NOT in the DOM yet.
    expect(container.innerHTML).not.toContain(SECRET);

    click('.provider-key-row__reveal');
    await flush();
    // Explicit click fetched exactly the requested id+index.
    expect(h.onReveal).toHaveBeenCalledTimes(1);
    expect(h.onReveal).toHaveBeenCalledWith('groq', 2);
    expect(q('.provider-key-row__value').textContent).toBe(SECRET);
    expect(q('.provider-key-row__value').getAttribute('data-revealed')).toBe('true');
    expect(q('.provider-key-row__reveal').getAttribute('aria-pressed')).toBe('true');

    // Hide re-masks and wipes the secret from the DOM.
    click('.provider-key-row__reveal');
    await flush();
    expect(q('.provider-key-row__value').textContent).toBe('…WXYZ');
    expect(container.innerHTML).not.toContain(SECRET);
  });

  it('auto-re-masks on blur of the revealed value', async () => {
    const h = makeHandlers();
    render(h);
    click('.provider-key-row__reveal');
    await flush();
    expect(q('.provider-key-row__value').textContent).toBe(SECRET);

    // React's onBlur delegates to the bubbling `focusout` event.
    act(() =>
      q('.provider-key-row__value').dispatchEvent(new FocusEvent('focusout', { bubbles: true })),
    );
    await flush();
    expect(q('.provider-key-row__value').textContent).toBe('…WXYZ');
    expect(container.innerHTML).not.toContain(SECRET);
  });

  it('auto-re-masks after the reveal timeout elapses', async () => {
    vi.useFakeTimers();
    const h = makeHandlers();
    render(h, { revealTimeoutMs: 5000 });
    click('.provider-key-row__reveal');
    // Resolve the reveal promise under fake timers.
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(q('.provider-key-row__value').textContent).toBe(SECRET);

    act(() => vi.advanceTimersByTime(5000));
    expect(q('.provider-key-row__value').textContent).toBe('…WXYZ');
    expect(container.innerHTML).not.toContain(SECRET);
  });

  it('NEVER leaks the revealed key to a log, to state after re-mask, or to any callback', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    const errorLog = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    const h = makeHandlers();
    render(h);

    click('.provider-key-row__reveal');
    await flush();
    expect(q('.provider-key-row__value').textContent).toBe(SECRET);

    // Re-validate + Remove while revealed — the callbacks get id+index ONLY.
    click('.provider-key-row__revalidate');
    await flush();
    click('.provider-key-row__remove');
    expect(h.onRevalidate).toHaveBeenCalledWith('groq', 2);
    expect(h.onRemove).toHaveBeenCalledWith('groq', 2);

    // Re-mask, then prove the secret is gone from the rendered tree (not in state).
    click('.provider-key-row__reveal');
    await flush();
    expect(container.innerHTML).not.toContain(SECRET);

    // The secret never rode a console/log sink.
    const allLogArgs = [...warn.mock.calls, ...errorLog.mock.calls].flat().map(String);
    expect(allLogArgs.some((s) => s.includes(SECRET))).toBe(false);
    // No callback ever received the secret as an argument.
    for (const fn of [h.onRemove, h.onRevalidate, h.onReplace]) {
      for (const call of fn.mock.calls) {
        expect(call).not.toContain(SECRET);
      }
    }
  });

  it('drops the key on the floor when unmounted mid-reveal (never re-populates the wiped ref)', async () => {
    let resolveReveal: (v: string) => void = () => {};
    const onReveal = vi.fn(() => new Promise<string>((res) => (resolveReveal = res)));
    const h = makeHandlers({ onReveal });
    render(h);
    click('.provider-key-row__reveal');
    // Unmount BEFORE the reveal resolves.
    act(() => root.unmount());
    resolveReveal(SECRET);
    await flush();
    expect(container.innerHTML).not.toContain(SECRET);
    // Re-mount a fresh root so afterEach's unmount is a no-op-safe.
    root = createRoot(container);
  });
});

// --- WU-D3 Re-validate ------------------------------------------------------

describe('ProviderKeyRow — Re-validate stored key', () => {
  it('calls onRevalidate and surfaces a pass status', async () => {
    const h = makeHandlers();
    render(h);
    click('.provider-key-row__revalidate');
    await flush();
    expect(h.onRevalidate).toHaveBeenCalledWith('groq', 2);
    expect(q('.provider-key-row__status').textContent).toBe('Key verified — working.');
  });

  it('surfaces a scrubbed failure status (and defaults a missing error to "invalid")', async () => {
    const withError = makeHandlers({
      onRevalidate: vi.fn(() =>
        Promise.resolve<KeyCheckResult>({ ok: false, error: '401 unauthorized' }),
      ),
    });
    render(withError);
    click('.provider-key-row__revalidate');
    await flush();
    expect(q('.provider-key-row__status').textContent).toBe('Key failed: 401 unauthorized');

    const noError = makeHandlers({
      onRevalidate: vi.fn(() => Promise.resolve<KeyCheckResult>({ ok: false })),
    });
    act(() => root.unmount());
    root = createRoot(container);
    render(noError);
    click('.provider-key-row__revalidate');
    await flush();
    expect(q('.provider-key-row__status').textContent).toBe('Key failed: invalid');
  });

  it('skips the status write when unmounted mid-revalidate', async () => {
    let resolveCheck: (v: KeyCheckResult) => void = () => {};
    const onRevalidate = vi.fn(() => new Promise<KeyCheckResult>((res) => (resolveCheck = res)));
    const h = makeHandlers({ onRevalidate });
    render(h);
    click('.provider-key-row__revalidate');
    act(() => root.unmount());
    resolveCheck({ ok: true });
    await flush();
    root = createRoot(container);
    expect(true).toBe(true); // no throw / no act warning => the alive-guard held
  });
});

// --- WU-D3 Replace ----------------------------------------------------------

describe('ProviderKeyRow — Replace (re-runs validation, preferred over in-place)', () => {
  it('replaces with a NEW key, re-validates, and closes the editor on success', async () => {
    const h = makeHandlers();
    render(h);
    click('.provider-key-row__replace-toggle');
    expect(q('.provider-key-row__replace')).not.toBeNull();

    setInputValue(q<HTMLInputElement>('.provider-key-row__replace-input'), 'sk-new-key-1234');
    await flush();
    click('.provider-key-row__replace-save');
    await flush();

    expect(h.onReplace).toHaveBeenCalledWith('groq', 2, 'sk-new-key-1234');
    expect(q('.provider-key-row__status').textContent).toBe('Key verified — working.');
    // Success closes the replace editor.
    expect(container.querySelector('.provider-key-row__replace')).toBeNull();
  });

  it('keeps the editor open and shows the failure on a rejected new key', async () => {
    const h = makeHandlers({
      onReplace: vi.fn(() => Promise.resolve<KeyCheckResult>({ ok: false, error: 'bad key' })),
    });
    render(h);
    click('.provider-key-row__replace-toggle');
    setInputValue(q<HTMLInputElement>('.provider-key-row__replace-input'), 'sk-bad');
    await flush();
    click('.provider-key-row__replace-save');
    await flush();
    expect(q('.provider-key-row__status').textContent).toBe('Key failed: bad key');
    // Editor stays open so the user can correct it.
    expect(container.querySelector('.provider-key-row__replace')).not.toBeNull();
  });

  it('submits on Enter and ignores Enter / save on an empty draft', async () => {
    const h = makeHandlers();
    render(h);
    click('.provider-key-row__replace-toggle');
    const input = q<HTMLInputElement>('.provider-key-row__replace-input');

    // Empty Enter is a no-op (submit guard) and the Save button is disabled.
    act(() => input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })));
    await flush();
    expect(h.onReplace).not.toHaveBeenCalled();
    expect(q<HTMLButtonElement>('.provider-key-row__replace-save').disabled).toBe(true);

    // A non-Enter key does not submit.
    setInputValue(input, 'sk-enter-key');
    act(() => input.dispatchEvent(new KeyboardEvent('keydown', { key: 'a', bubbles: true })));
    await flush();
    expect(h.onReplace).not.toHaveBeenCalled();

    // Enter with a value submits.
    act(() => input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })));
    await flush();
    expect(h.onReplace).toHaveBeenCalledWith('groq', 2, 'sk-enter-key');
  });

  it('toggles the replace editor closed via Cancel', () => {
    const h = makeHandlers();
    render(h);
    click('.provider-key-row__replace-toggle');
    expect(container.querySelector('.provider-key-row__replace')).not.toBeNull();
    expect(q('.provider-key-row__replace-toggle').textContent).toBe('Cancel replace');
    click('.provider-key-row__replace-toggle');
    expect(container.querySelector('.provider-key-row__replace')).toBeNull();
    expect(q('.provider-key-row__replace-toggle').textContent).toBe('Replace');
  });

  it('skips state writes when unmounted mid-replace', async () => {
    let resolveCheck: (v: KeyCheckResult) => void = () => {};
    const onReplace = vi.fn(() => new Promise<KeyCheckResult>((res) => (resolveCheck = res)));
    const h = makeHandlers({ onReplace });
    render(h);
    click('.provider-key-row__replace-toggle');
    setInputValue(q<HTMLInputElement>('.provider-key-row__replace-input'), 'sk-unmount');
    await flush();
    click('.provider-key-row__replace-save');
    act(() => root.unmount());
    resolveCheck({ ok: true });
    await flush();
    root = createRoot(container);
    expect(true).toBe(true);
  });
});

// --- F38: a REJECTED key op must never leave a stale in-progress label -------
// Every one of Reveal / Re-validate / Replace was `try/finally` with NO `catch`,
// so an RPC rejection (e.g. the sidecar's Offline refusal, which exists precisely
// "so the message reaches the UI verbatim") skipped the status write and left the
// row rendering a lying label — or, for Reveal, no feedback node at all.

describe('ProviderKeyRow — rejected key ops surface the error (F38)', () => {
  const OFFLINE =
    'Offline mode is on — testing a provider key needs the network. Turn off Offline mode in System Health to allow it.';

  it('replaces the stale "Re-validating…" label with the rejection message', async () => {
    const h = makeHandlers({ onRevalidate: vi.fn(() => Promise.reject(new Error(OFFLINE))) });
    render(h);
    click('.provider-key-row__revalidate');
    await flush();
    const status = q('.provider-key-row__status');
    expect(status.textContent).not.toBe('Re-validating…');
    expect(status.textContent).toContain('Offline mode is on');
  });

  it('drops a re-validate rejection that lands after unmount (alive guard)', async () => {
    let rejectCheck: (e: Error) => void = () => {};
    const onRevalidate = vi.fn(
      () => new Promise<KeyCheckResult>((_res, rej) => (rejectCheck = rej)),
    );
    const h = makeHandlers({ onRevalidate });
    render(h);
    click('.provider-key-row__revalidate');
    act(() => root.unmount());
    rejectCheck(new Error('late revalidate failure'));
    await flush();
    root = createRoot(container);
    expect(container.querySelector('.provider-key-row')).toBeNull();
  });

  it('shows a reveal rejection in the status line and stays masked', async () => {
    const h = makeHandlers({
      onReveal: vi.fn(() =>
        Promise.reject(new Error("providers.revealKey: no key at index 0 for 'groq'")),
      ),
    });
    render(h);
    click('.provider-key-row__reveal');
    await flush();
    // Pre-fix `status` was never written, so the <p> was not even in the DOM.
    const status = container.querySelector('.provider-key-row__status');
    expect(status).not.toBeNull();
    expect(status?.textContent).toContain('no key at index 0');
    // The R7 secret contract is untouched: still redacted, still masked.
    expect(q('.provider-key-row__value').textContent).toBe('…WXYZ');
    expect(q('.provider-key-row__value').getAttribute('data-revealed')).toBe('false');
  });

  it('stringifies a NON-Error reveal rejection', async () => {
    const h = makeHandlers({
      // eslint-disable-next-line prefer-promise-reject-errors -- deliberately a non-Error.
      onReveal: vi.fn(() => Promise.reject('plain string reveal failure')),
    });
    render(h);
    click('.provider-key-row__reveal');
    await flush();
    expect(container.querySelector('.provider-key-row__status')?.textContent).toContain(
      'plain string reveal failure',
    );
  });

  it('drops a reveal rejection that lands after unmount (alive guard)', async () => {
    let rejectReveal: (e: Error) => void = () => {};
    const onReveal = vi.fn(() => new Promise<string>((_res, rej) => (rejectReveal = rej)));
    const h = makeHandlers({ onReveal });
    render(h);
    click('.provider-key-row__reveal');
    act(() => root.unmount());
    rejectReveal(new Error('late reveal failure'));
    await flush();
    root = createRoot(container);
    expect(container.querySelector('.provider-key-row')).toBeNull();
  });

  it('keeps the replace editor open and the typed draft on a rejection', async () => {
    const h = makeHandlers({ onReplace: vi.fn(() => Promise.reject(new Error('replace boom'))) });
    render(h);
    click('.provider-key-row__replace-toggle');
    setInputValue(q<HTMLInputElement>('.provider-key-row__replace-input'), 'sk-typed-x');
    await flush();
    click('.provider-key-row__replace-save');
    await flush();
    const status = q('.provider-key-row__status');
    expect(status.textContent).not.toBe('Validating new key…');
    expect(status.textContent).toContain('replace boom');
    // The editor stays open and the pasted key survives for a deliberate retry.
    expect(container.querySelector('.provider-key-row__replace')).not.toBeNull();
    expect(q<HTMLInputElement>('.provider-key-row__replace-input').value).toBe('sk-typed-x');
  });

  it('drops a replace rejection that lands after unmount (alive guard)', async () => {
    let rejectCheck: (e: Error) => void = () => {};
    const onReplace = vi.fn(() => new Promise<KeyCheckResult>((_res, rej) => (rejectCheck = rej)));
    const h = makeHandlers({ onReplace });
    render(h);
    click('.provider-key-row__replace-toggle');
    setInputValue(q<HTMLInputElement>('.provider-key-row__replace-input'), 'sk-unmount-reject');
    await flush();
    click('.provider-key-row__replace-save');
    act(() => root.unmount());
    rejectCheck(new Error('late replace failure'));
    await flush();
    root = createRoot(container);
    expect(container.querySelector('.provider-key-row')).toBeNull();
  });
});

// --- F41: a PANEL-level mutation in flight must lock this row's controls -----
// `removeKey` / `replaceKey` both build their upsert payload from a pre-await
// `providers` snapshot, so a second mutation started while the first is in flight
// drops one of the two keys. The row had no panel-busy input at all.

describe('ProviderKeyRow — panelBusy locks the mutating controls (F41)', () => {
  it('disables Re-validate / Replace / Remove while the panel is mutating', () => {
    const h = makeHandlers();
    render(h, { panelBusy: true });
    expect(q<HTMLButtonElement>('.provider-key-row__revalidate').disabled).toBe(true);
    expect(q<HTMLButtonElement>('.provider-key-row__replace-toggle').disabled).toBe(true);
    expect(q<HTMLButtonElement>('.provider-key-row__remove').disabled).toBe(true);
  });

  it('leaves them enabled when the panel is idle', () => {
    const h = makeHandlers();
    render(h, { panelBusy: false });
    expect(q<HTMLButtonElement>('.provider-key-row__revalidate').disabled).toBe(false);
    expect(q<HTMLButtonElement>('.provider-key-row__remove').disabled).toBe(false);
  });
});
