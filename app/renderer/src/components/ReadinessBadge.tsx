// ReadinessBadge.tsx — the shared readiness status pill (WU-9). A thin render
// shell over readinessMeta.ts (WU-8): it mirrors the VerdictBadge PRIMITIVE
// (text label + role="status" + data attr + title) so status is announced by
// TEXT and role, never by hue alone (WCAG 1.4.1). It reuses ONLY the
// `verdict-badge` pill geometry; the tint comes from a parallel `readiness-badge`
// class map (readinessClass), NOT the verdict color map. The optional fix action
// is a REAL <button> with a capability-tied accessible name — never icon-only.
import React from 'react';
import type { ReadinessAction, ReadinessStatus } from '../lib/rpc';
import {
  readinessActionLabel,
  readinessClass,
  readinessHint,
  readinessLabel,
} from './readinessMeta';
import './readinessBadge.css';

export interface ReadinessBadgeProps {
  status: ReadinessStatus;
  /** Human-friendly capability name, woven into the action's accessible name. */
  capabilityLabel: string;
  /** Plain-language reason it is not ready; appended to the tooltip when set. */
  blockedBy?: string;
  /** The fix action; when null/absent no button renders (ready / blocked-no-fix). */
  action?: ReadinessAction | null;
  /** Fired with the action when the fix button is clicked. */
  onAction?: (action: ReadinessAction) => void;
}

export function ReadinessBadge({
  status,
  capabilityLabel,
  blockedBy,
  action,
  onAction,
}: ReadinessBadgeProps): React.ReactElement {
  const title = [readinessHint(status), blockedBy].filter(Boolean).join(' ');
  return (
    <span className="readiness-badge-group">
      <span
        className={`verdict-badge readiness-badge ${readinessClass(status)}`}
        data-readiness={status}
        role="status"
        title={title}
      >
        {readinessLabel(status)}
      </span>
      {action ? (
        <button
          type="button"
          className="readiness-badge__action"
          aria-label={readinessActionLabel(action, capabilityLabel)}
          onClick={() => onAction?.(action)}
        >
          {readinessActionLabel(action, capabilityLabel)}
        </button>
      ) : null}
    </span>
  );
}

export default ReadinessBadge;
