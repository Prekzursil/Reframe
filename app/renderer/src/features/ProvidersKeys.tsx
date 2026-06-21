// ProvidersKeys.tsx — the "Providers & Keys" Settings sub-section.
//
// Scaffold WU: this surfaces the section so the Settings tab structure is
// complete and reachable. The full key-management UI (paste/add/remove provider
// API keys via components/AddKeyRow + ProviderKeyRow, backed by the providers.*
// RPCs) is wired by a later WU. Until then this is a deliberate empty-state with
// a helpful message AND an action — never a blank panel (design rail).
//
// The action routes the user to where provider routing currently lives (the
// Models & System section), via an `onOpenModels` callback the host wires.
import React from 'react';
import './providersKeys.css';
import { KeyIcon } from './providersKeysIcon';

export interface ProvidersKeysProps {
  /**
   * Open the Models & System section (where per-function provider routing lives
   * today). Optional: when absent the action is hidden rather than dead.
   */
  onOpenModels?: () => void;
}

/** Providers & Keys section — empty-state scaffold (full UI lands in a later WU). */
export function ProvidersKeys({ onOpenModels }: ProvidersKeysProps): React.ReactElement {
  return (
    <section className="feature-panel providers-keys" aria-labelledby="providers-keys-title">
      <div className="providers-keys__empty">
        <span className="providers-keys__icon" aria-hidden="true">
          <KeyIcon />
        </span>
        <h2 id="providers-keys-title" className="providers-keys__title">
          No provider keys yet
        </h2>
        <p className="providers-keys__hint">
          Add API keys for cloud providers (transcription, translation, and AI) to
          unlock Cloud-quality processing. Keys are stored locally and only ever read
          back redacted. Key management arrives in an upcoming update.
        </p>
        {onOpenModels ? (
          <button
            type="button"
            className="providers-keys__action"
            onClick={onOpenModels}
          >
            Review model routing
          </button>
        ) : null}
      </div>
    </section>
  );
}

export default ProvidersKeys;
