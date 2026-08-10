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
//
// The two SKINS also differ in MODALITY, and that is explicit in the `modal` prop
// rather than implied: `useConfirm()` gates are overlay modals (scrim + Tab cage +
// aria-modal); the Export inspector's gate is an inline card in a panel and gets
// none of the three. See the `modal` prop doc for why they cannot be mixed.

import React, { useCallback, useId, useRef, useState } from 'react';
import { useFocusTrap } from '../hooks/useFocusTrap';
import './confirmDialog.css';

export interface ConfirmDialogProps {
  /**
   * BEM block for the emitted classes: `{block}`, `{block}-title`, `{block}-blurb`,
   * `{block}-actions`, `{block}-approve`, `{block}-cancel`, plus `{block}-scrim`
   * on the overlay wrapper when `modal`. A prop rather than a constant so the
   * pre-existing Export gate keeps its own skin while sharing this implementation —
   * those suffixes are ITS vocabulary, adopted here unchanged so reuse costs the
   * export gate no renames.
   */
  block: string;
  /**
   * MODALITY IS ONE DECISION, NOT THREE. All three of these move together:
   *
   *   `true`  — renders a real `{block}-scrim` ELEMENT (fixed, full-viewport,
   *             opaque to the pointer) around the card, cages Tab inside the card,
   *             and sets `aria-modal="true"`. Pointer and keyboard are both held,
   *             so the ARIA claim that the rest of the page is inert is TRUE.
   *   `false` — renders the bare card with NO scrim, does NOT cage Tab, and emits
   *             NO `aria-modal`. Escape still cancels. This is the inline gate the
   *             Export inspector ships: a card inside a panel, with a live page
   *             around it.
   *
   * There is deliberately no way to ask for `aria-modal` without the scrim. The
   * first cut of this component did exactly that and it was a false claim to
   * assistive tech: it advertised the page as inert while every control behind the
   * card stayed clickable.
   */
  modal: boolean;
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
  modal,
  title,
  blurb,
  confirmLabel,
  cancelLabel,
  onConfirm,
  onCancel,
}: ConfirmDialogProps): React.ReactElement {
  const titleId = useId();
  const blurbId = useId();
  // Reuse the repo's focus trap (hooks/useFocusTrap.ts) rather than re-deriving
  // focus behaviour here: it moves focus to the primary on mount (WCAG 2.4.3 —
  // otherwise the gate opens with focus still on the button behind it), routes
  // Escape to cancel (the affordance the native confirm had), and restores focus
  // to the opener on unmount. Tab is caged ONLY when `modal`, because caging the
  // keyboard while the pointer roams free is the inconsistency `aria-modal` then
  // lies about — see the `modal` prop doc.
  const trapRef = useFocusTrap<HTMLDivElement>({
    onEscape: onCancel,
    initialFocus: `.${block}-approve`,
    trapTab: modal,
  });

  const card = (
    <div
      ref={trapRef}
      className={block}
      role="alertdialog"
      // Only ever set alongside the scrim + the Tab cage below. `undefined` omits
      // the attribute entirely rather than emitting aria-modal="false".
      aria-modal={modal ? 'true' : undefined}
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

  if (!modal) return card;

  // A real ELEMENT, not a `::before`. The first cut painted the scrim as a
  // pseudo-element of the card — and the card was `position: fixed` WITH a
  // `transform: translate(-50%,-50%)` centring, which makes the card its own
  // fixed-position containing block (CSS Transforms L1 §3). The "full-viewport"
  // scrim was therefore clipped to the card's own box: no page dim, no pointer
  // interception, while `aria-modal` claimed both. The wrapper both centres the
  // card and IS the scrim, so the two cannot drift apart again.
  //
  // It carries no onClick: a stray background click must not answer a destructive
  // question in either direction. Its job is to SWALLOW the click, not route it.
  return <div className={`${block}-scrim`}>{card}</div>;
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
        // The six former native-`confirm()` sites are genuine modals: the native
        // dialog they replace froze the whole renderer, so the themed gate holds
        // both pointer (scrim) and keyboard (Tab cage) instead.
        modal
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
