// ConfirmDialog.tsx — the ONE themed destructive-confirm gate (W04).
//
// Six destructive actions used to call the native `confirm()`:
//   views/Shorts.tsx · views/Library.tsx · features/ExportPresetsPanel.tsx (×2)
//   features/Tracks.tsx · features/useShortsGallery.ts
// Native confirm is unthemeable, carries no author-controlled accessible name or
// description, and in Electron it BLOCKS the renderer process for as long as it
// is open. This is the replacement, lifted from the gate the Export inspector
// already shipped (features/export/ExportInspector.tsx) rather than invented a
// second time — that inspector now renders THIS component, which is why the BEM
// block is a prop: it keeps `export-inspector__confirm*` on the export gate and
// `confirm-dialog*` everywhere else, one implementation under two skins.
//
// Two entry points:
//   <ConfirmDialog/>  — the presentational gate, for a caller that already owns
//                       an "am I confirming?" boolean (the Export inspector).
//   useConfirm()      — a promise wrapper for the six call sites, so their code
//                       keeps its original shape: `const ok = await confirm(…)`.

import React, { useCallback, useId, useRef, useState } from 'react';
import { useFocusTrap } from '../hooks/useFocusTrap';
import './confirmDialog.css';

export interface ConfirmDialogProps {
  /**
   * BEM block for the emitted classes: `{block}`, `{block}-title`, `{block}-blurb`,
   * `{block}-actions`, `{block}-approve`, `{block}-cancel`. A prop rather than a
   * constant so the pre-existing Export gate keeps its own skin while sharing this
   * implementation — those suffixes are ITS vocabulary, adopted here unchanged so
   * reuse costs the export gate no renames.
   */
  block: string;
  /** The question. Rendered as the dialog's accessible NAME. */
  title: string;
  /** The consequence. Rendered as the accessible DESCRIPTION; `\n` is honoured. */
  blurb: string;
  confirmLabel: string;
  cancelLabel: string;
  onConfirm: () => void;
  onCancel: () => void;
}

export function ConfirmDialog({
  block,
  title,
  blurb,
  confirmLabel,
  cancelLabel,
  onConfirm,
  onCancel,
}: ConfirmDialogProps): React.ReactElement {
  const titleId = useId();
  const blurbId = useId();
  // Reuse the repo's modal trap (hooks/useFocusTrap.ts) rather than re-deriving
  // focus behaviour here: it moves focus to the primary on mount (WCAG 2.4.3 —
  // otherwise the gate opens with focus still on the button behind it), cycles
  // Tab/Shift+Tab inside the dialog, routes Escape to cancel (the affordance the
  // native confirm had), and restores focus to the opener on unmount. The Tab
  // trap is what makes `aria-modal` below TRUE rather than a claim.
  const trapRef = useFocusTrap<HTMLDivElement>({
    onEscape: onCancel,
    initialFocus: `.${block}-approve`,
  });

  return (
    <div
      ref={trapRef}
      className={block}
      role="alertdialog"
      aria-modal="true"
      aria-labelledby={titleId}
      aria-describedby={blurbId}
    >
      <h3 id={titleId} className={`${block}-title`}>
        {title}
      </h3>
      <p id={blurbId} className={`${block}-blurb`}>
        {blurb}
      </p>
      <div className={`${block}-actions`}>
        <button type="button" className={`${block}-approve`} onClick={onConfirm}>
          {confirmLabel}
        </button>
        <button type="button" className={`${block}-cancel`} onClick={onCancel}>
          {cancelLabel}
        </button>
      </div>
    </div>
  );
}

/** What a call site asks the user. Every field is required — no silent default copy. */
export interface ConfirmRequest {
  title: string;
  blurb: string;
  confirmLabel: string;
  cancelLabel: string;
}

export interface Confirmer {
  /** Opens the gate and resolves TRUE only if the user pressed the primary. */
  confirm: (request: ConfirmRequest) => Promise<boolean>;
  /** Render this in the owning component; `null` while no question is open. */
  confirmDialog: React.ReactElement | null;
}

interface Pending {
  request: ConfirmRequest;
  resolve: (answer: boolean) => void;
}

/**
 * Promise-shaped access to the themed gate, so a destructive handler keeps the
 * exact shape it had under the native confirm:
 *
 *     const ok = await confirm({ title, body, confirmLabel, cancelLabel });
 *     if (!ok) return;
 */
export function useConfirm(): Confirmer {
  const [pending, setPending] = useState<Pending | null>(null);
  // Mirrors `pending` for the supersede check: `confirm` is a stable callback
  // (call sites put it in `useCallback` dependency lists), so it cannot read the
  // state variable without changing identity on every open/close.
  const pendingRef = useRef<Pending | null>(null);

  const confirm = useCallback(
    (request: ConfirmRequest): Promise<boolean> =>
      new Promise<boolean>((resolve) => {
        // A second question while one is open SUPERSEDES it. The displaced
        // awaiter is settled as DECLINED — dropping it would leave a caller
        // awaiting a promise whose dialog no longer exists, i.e. a destructive
        // handler suspended forever.
        pendingRef.current?.resolve(false);
        const next: Pending = { request, resolve };
        pendingRef.current = next;
        setPending(next);
      }),
    [],
  );

  const settle = useCallback((entry: Pending, answer: boolean): void => {
    pendingRef.current = null;
    setPending(null);
    entry.resolve(answer);
  }, []);

  const confirmDialog =
    pending === null ? null : (
      <ConfirmDialog
        block="confirm-dialog"
        title={pending.request.title}
        blurb={pending.request.blurb}
        confirmLabel={pending.request.confirmLabel}
        cancelLabel={pending.request.cancelLabel}
        onConfirm={() => settle(pending, true)}
        onCancel={() => settle(pending, false)}
      />
    );

  return { confirm, confirmDialog };
}

export default ConfirmDialog;
