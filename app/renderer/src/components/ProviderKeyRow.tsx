// ProviderKeyRow.tsx — one stored provider API key: redacted by default, with a
// transient reveal + per-key Re-validate + Replace (WU-keys + WU-D3).
//
// SECURITY (WU-D3, R7) — the reveal contract:
//   * The full key is fetched ONLY on an explicit user click, via the injected
//     onReveal callback (panel -> providers.revealKey RPC) — the ONE sanctioned
//     exception to redact-over-RPC.
//   * The revealed plaintext is held ONLY in a transient ref (`revealedRef`),
//     NEVER in React state/store, and NEVER passed to a log/telemetry/crash sink
//     or to the onRemove/onRevalidate/onReplace callbacks. A boolean `revealed`
//     flag (carrying NO secret) drives the re-render; render reads the ref.
//   * It is masked-by-default and auto-re-masks on BLUR or after a TIMEOUT, and is
//     wiped from the ref on re-mask AND on unmount (so an await that resolves after
//     unmount can never re-populate the secret).
// The "Replace" flow takes a NEW key the user types (same category as AddKeyRow's
// draft) and re-runs validation via onReplace; "Re-validate" re-checks the stored
// key via onRevalidate (panel: revealKey -> testKey, plaintext held in a local
// const only). Neither the revealed nor the redacted key is ever logged.
import React, { useCallback, useEffect, useRef, useState } from 'react';

/** Pass/fail outcome of a validation ping (mirrors providers.testKey; NO key). */
export interface KeyCheckResult {
  ok: boolean;
  /** A SCRUBBED error string on failure (the sidecar strips the key). */
  error?: string;
}

export interface ProviderKeyRowProps {
  /** The provider id this key belongs to (passed back to callbacks). */
  providerId: string;
  /** The REDACTED key as returned by the sidecar (last-4, e.g. "…WXYZ"). */
  redactedKey: string;
  /** Zero-based index within the provider's key list (passed back to callbacks). */
  index: number;
  /** Remove this key (provider id + index). Only called when the button is clicked. */
  onRemove: (providerId: string, index: number) => void;
  /**
   * Fetch the FULL plaintext key for a transient display (WU-D3). Resolves to the
   * raw key; the row holds it in a ref only and wipes it on re-mask/unmount.
   */
  onReveal: (providerId: string, index: number) => Promise<string>;
  /** Re-validate the STORED key (panel: revealKey -> testKey). */
  onRevalidate: (providerId: string, index: number) => Promise<KeyCheckResult>;
  /** Replace this key with a NEW one, re-running validation (WU-D3). */
  onReplace: (providerId: string, index: number, newKey: string) => Promise<KeyCheckResult>;
  /** Auto-re-mask delay (ms) after a reveal. Injectable for tests; default 15s. */
  revealTimeoutMs?: number;
}

const DEFAULT_REVEAL_TIMEOUT_MS = 15_000;

/** Status text for a pass/fail validation outcome (never contains a key). */
function checkStatus(result: KeyCheckResult): string {
  return result.ok ? 'Key verified — working.' : `Key failed: ${result.error ?? 'invalid'}`;
}

export function ProviderKeyRow({
  providerId,
  redactedKey,
  index,
  onRemove,
  onReveal,
  onRevalidate,
  onReplace,
  revealTimeoutMs = DEFAULT_REVEAL_TIMEOUT_MS,
}: ProviderKeyRowProps): React.ReactElement {
  // The revealed plaintext lives ONLY here — never in React state/store (R7).
  const revealedRef = useRef<string | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const aliveRef = useRef(true);

  // A boolean flag (carries NO secret) drives the re-render; render reads the ref.
  const [revealed, setRevealed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState('');
  const [replacing, setReplacing] = useState(false);
  const [draft, setDraft] = useState('');

  const clearTimer = useCallback((): void => {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  // Wipe the plaintext from the ref and re-mask. Safe when already masked.
  const remask = useCallback((): void => {
    clearTimer();
    revealedRef.current = null;
    setRevealed(false);
  }, [clearTimer]);

  // On unmount: wipe the secret from memory and drop any pending timer.
  useEffect(() => {
    aliveRef.current = true;
    return () => {
      aliveRef.current = false;
      clearTimer();
      revealedRef.current = null;
    };
  }, [clearTimer]);

  const reveal = useCallback(async (): Promise<void> => {
    setBusy(true);
    try {
      const key = await onReveal(providerId, index);
      // If we unmounted mid-fetch, drop the key on the floor — never write it into
      // a detached ref that the unmount-cleanup already wiped.
      if (!aliveRef.current) return;
      revealedRef.current = key;
      setRevealed(true);
      clearTimer();
      timerRef.current = setTimeout(remask, revealTimeoutMs);
    } finally {
      if (aliveRef.current) setBusy(false);
    }
  }, [onReveal, providerId, index, clearTimer, remask, revealTimeoutMs]);

  const revalidate = useCallback(async (): Promise<void> => {
    setBusy(true);
    setStatus('Re-validating…');
    try {
      const result = await onRevalidate(providerId, index);
      if (aliveRef.current) setStatus(checkStatus(result));
    } finally {
      if (aliveRef.current) setBusy(false);
    }
  }, [onRevalidate, providerId, index]);

  const submitReplace = useCallback(async (): Promise<void> => {
    const trimmed = draft.trim();
    if (trimmed.length === 0) return;
    setBusy(true);
    setStatus('Validating new key…');
    try {
      const result = await onReplace(providerId, index, trimmed);
      if (!aliveRef.current) return;
      setStatus(checkStatus(result));
      setDraft(''); // clear so the new key does not linger in the field
      if (result.ok) setReplacing(false);
    } finally {
      if (aliveRef.current) setBusy(false);
    }
  }, [draft, onReplace, providerId, index]);

  // Render reads the ref directly; `revealed` (a bool, no secret) gates it.
  const shown: string | null = revealed ? revealedRef.current : redactedKey;

  return (
    <li className="provider-key-row" data-provider={providerId} data-key-index={index}>
      <div className="provider-key-row__main">
        <code
          className="provider-key-row__value"
          data-revealed={revealed}
          aria-label={
            revealed ? `Revealed API key for ${providerId}` : `API key ending ${redactedKey}`
          }
          tabIndex={revealed ? 0 : undefined}
          onBlur={revealed ? remask : undefined}
        >
          {shown}
        </code>

        <button
          type="button"
          className="provider-key-row__reveal"
          aria-label={revealed ? `Hide key for ${providerId}` : `Reveal key for ${providerId}`}
          aria-pressed={revealed}
          onClick={() => (revealed ? remask() : void reveal())}
        >
          {revealed ? 'Hide' : 'Reveal'}
        </button>

        <button
          type="button"
          className="provider-key-row__revalidate"
          aria-label={`Re-validate key for ${providerId}`}
          disabled={busy}
          onClick={() => void revalidate()}
        >
          Re-validate
        </button>

        <button
          type="button"
          className="provider-key-row__replace-toggle"
          aria-label={`Replace key for ${providerId}`}
          aria-expanded={replacing}
          disabled={busy}
          onClick={() => {
            setStatus('');
            setDraft('');
            setReplacing((r) => !r);
          }}
        >
          {replacing ? 'Cancel replace' : 'Replace'}
        </button>

        <button
          type="button"
          className="provider-key-row__remove"
          aria-label={`Remove key ${redactedKey} from ${providerId}`}
          disabled={busy}
          onClick={() => onRemove(providerId, index)}
        >
          Remove
        </button>
      </div>

      {replacing ? (
        <div className="provider-key-row__replace">
          <input
            type="password"
            className="provider-key-row__replace-input"
            aria-label={`New API key for ${providerId}`}
            placeholder="Paste replacement key"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') void submitReplace();
            }}
          />
          <button
            type="button"
            className="provider-key-row__replace-save"
            aria-label={`Save replacement key for ${providerId}`}
            disabled={busy || draft.trim().length === 0}
            onClick={() => void submitReplace()}
          >
            Save &amp; validate
          </button>
        </div>
      ) : null}

      {status ? (
        <p className="provider-key-row__status" role="status" aria-live="polite">
          {status}
        </p>
      ) : null}
    </li>
  );
}

export default ProviderKeyRow;
