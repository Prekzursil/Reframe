// AddKeyRow.tsx — paste-to-add a new API key for a provider (WU-keys).
//
// The user pastes a full key into a password-type input and clicks Add; the
// component hands the RAW pasted value to onAdd (the panel forwards it to the
// providers.upsert RPC, where it is stored RAW and only ever read back redacted).
// The input is cleared after a successful add so the full key never lingers in
// the field. Add is disabled while the trimmed input is empty. Owns only its own
// draft-input state; no rpc.
import React, { useCallback, useState } from 'react';

export interface AddKeyRowProps {
  /** The provider id the pasted key is added to. */
  providerId: string;
  /** Receives the trimmed RAW pasted key. Only called for a non-empty value. */
  onAdd: (providerId: string, key: string) => void;
}

export function AddKeyRow({ providerId, onAdd }: AddKeyRowProps): React.ReactElement {
  const [draft, setDraft] = useState<string>('');
  const trimmed = draft.trim();
  const canAdd = trimmed.length > 0;

  const submit = useCallback(() => {
    if (!canAdd) return;
    onAdd(providerId, trimmed);
    setDraft(''); // clear so the full key does not linger in the field
  }, [canAdd, onAdd, providerId, trimmed]);

  return (
    <div className="add-key-row" data-provider={providerId}>
      <input
        type="password"
        className="add-key-row__input"
        aria-label={`New API key for ${providerId}`}
        placeholder="Paste API key"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          // Enter submits (and exercises the canAdd guard for an empty field —
          // the Add button is disabled when empty, but Enter is not gated by it).
          if (e.key === 'Enter') submit();
        }}
      />
      <button
        type="button"
        className="add-key-row__add"
        aria-label={`Add key to ${providerId}`}
        disabled={!canAdd}
        onClick={submit}
      >
        Add key
      </button>
    </div>
  );
}

export default AddKeyRow;
