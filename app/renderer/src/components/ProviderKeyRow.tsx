// ProviderKeyRow.tsx — one stored provider API key, shown REDACTED (last-4 only).
//
// WU-keys (PLAN §WU-keys): the renderer NEVER receives a full key — the sidecar
// returns each key already redacted (e.g. "…WXYZ") via providers.list /
// settings.get. This row just displays that redacted string and offers a Remove
// button; it owns NO rpc and NO state (the panel supplies onRemove).
import React from 'react';

export interface ProviderKeyRowProps {
  /** The provider id this key belongs to (passed back to onRemove). */
  providerId: string;
  /** The REDACTED key as returned by the sidecar (last-4, e.g. "…WXYZ"). */
  redactedKey: string;
  /** Zero-based index within the provider's key list (passed back to onRemove). */
  index: number;
  /** Remove this key (provider id + index). Only called when the button is clicked. */
  onRemove: (providerId: string, index: number) => void;
}

export function ProviderKeyRow({
  providerId,
  redactedKey,
  index,
  onRemove,
}: ProviderKeyRowProps): React.ReactElement {
  return (
    <li className="provider-key-row" data-provider={providerId} data-key-index={index}>
      <code className="provider-key-row__value" aria-label={`API key ending ${redactedKey}`}>
        {redactedKey}
      </code>
      <button
        type="button"
        className="provider-key-row__remove"
        aria-label={`Remove key ${redactedKey} from ${providerId}`}
        onClick={() => onRemove(providerId, index)}
      >
        Remove
      </button>
    </li>
  );
}

export default ProviderKeyRow;
