// ConfirmDialog.test.tsx — the shared THEMED destructive-confirm gate (W04).
//
// The six destructive actions in this app used to call the native `confirm()`.
// Native confirm is unthemeable, cannot be labelled/described for AT, and in
// Electron it blocks the renderer process outright. This suite pins the themed
// replacement: an announced `alertdialog`, focus moved onto its primary action,
// Escape as the cancel affordance, and a promise-shaped `useConfirm()` so a call
// site keeps its `const ok = await confirm(...)` shape.
//
// It ALSO pins the modality contract, which an adversarial review found broken:
// the three things that make a dialog modal — a scrim ELEMENT over the page, a Tab
// cage, and `aria-modal="true"` — must ship together or not at all. `modal={true}`
// gets all three; `modal={false}` (the Export inspector's inline card) gets none.
// The pointer half is a hit-testing fact jsdom cannot observe, so the geometry of
// the scrim is pinned by confirmDialog.overlay.test.ts and its real-Chromium
// behaviour by e2e/confirm-scrim.hittest.spec.ts.

// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import { ConfirmDialog, useConfirm, type Confirmer } from './ConfirmDialog';

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

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

const q = <T extends Element>(sel: string): T | null => container.querySelector<T>(sel);

describe('ConfirmDialog', () => {
  const onConfirm = vi.fn();
  const onCancel = vi.fn();

  function render(block = 'confirm-dialog', modal = true): void {
    act(() => {
      root.render(
        <ConfirmDialog
          block={block}
          modal={modal}
          title="Delete this short?"
          blurb={'/out/clip-1.mp4\n\nThis removes the exported file.'}
          confirmLabel="Delete short"
          cancelLabel="Keep it"
          onConfirm={onConfirm}
          onCancel={onCancel}
        />,
      );
    });
  }

  beforeEach(() => {
    onConfirm.mockReset();
    onCancel.mockReset();
  });

  it('is an announced alertdialog labelled + described by its own copy', () => {
    render();
    const dialog = q('.confirm-dialog');
    expect(dialog?.getAttribute('role')).toBe('alertdialog');
    const titleId = q('.confirm-dialog-title')?.id;
    const bodyId = q('.confirm-dialog-blurb')?.id;
    expect(titleId).toBeTruthy();
    expect(bodyId).toBeTruthy();
    expect(dialog?.getAttribute('aria-labelledby')).toBe(titleId);
    expect(dialog?.getAttribute('aria-describedby')).toBe(bodyId);
    // aria-modal is only honest because BOTH halves of modality are present: the
    // Tab cage (pinned below) and the scrim element (pinned in the next case).
    expect(dialog?.getAttribute('aria-modal')).toBe('true');
    // The whole message survives — including the detail line the native confirm
    // used to carry after a blank line.
    expect(q('.confirm-dialog-title')?.textContent).toBe('Delete this short?');
    expect(q('.confirm-dialog-blurb')?.textContent).toContain('/out/clip-1.mp4');
    expect(q('.confirm-dialog-blurb')?.textContent).toContain('This removes the exported file.');
  });

  it('moves focus onto the primary action so the gate is never announced to <body>', () => {
    render();
    expect(document.activeElement).toBe(q('.confirm-dialog-approve'));
  });

  it('takes its BEM block from the caller, so an existing themed gate can reuse it', () => {
    render('export-inspector__confirm', false);
    expect(q('.confirm-dialog')).toBeNull();
    expect(q('.export-inspector__confirm')?.getAttribute('role')).toBe('alertdialog');
    expect(q('.export-inspector__confirm-title')?.textContent).toBe('Delete this short?');
    expect(q('.export-inspector__confirm-approve')?.textContent).toBe('Delete short');
    expect(q('.export-inspector__confirm-cancel')?.textContent).toBe('Keep it');
  });

  it('wraps a MODAL gate in a scrim element, so aria-modal has a pointer half', () => {
    // The scrim is what stops a mouse reaching the page while `aria-modal` tells a
    // screen reader that page is inert. It has to be a real ELEMENT: a `::before`
    // on a `transform`-centred card is clipped to the card (CSS Transforms L1 §3),
    // which is exactly how the first cut shipped no scrim at all.
    render();
    const scrim = q<HTMLDivElement>('.confirm-dialog-scrim');
    expect(scrim).not.toBeNull();
    // The card is INSIDE the scrim — a sibling scrim would not cover the card's
    // own stacking context reliably, and would let the wrapper drift away from it.
    expect(scrim?.firstElementChild).toBe(q('.confirm-dialog'));
    // The scrim answers nothing: a stray background click must not resolve a
    // destructive question in either direction.
    act(() => scrim?.click());
    expect(onConfirm).not.toHaveBeenCalled();
    expect(onCancel).not.toHaveBeenCalled();
  });

  it('a NON-modal gate ships no scrim, no aria-modal and no Tab cage', () => {
    // The Export inspector's gate is an inline card in a live panel. Claiming
    // aria-modal there is false to assistive tech, and caging Tab strands a
    // keyboard user inside a card a mouse user can click straight past.
    render('export-inspector__confirm', false);
    const dialog = q<HTMLDivElement>('.export-inspector__confirm');
    expect(q('.export-inspector__confirm-scrim')).toBeNull();
    expect(dialog?.hasAttribute('aria-modal')).toBe(false);
    // Tab off the LAST control is left alone (jsdom moves no focus of its own, so
    // "unchanged" is precisely "the hook did not wrap it back to the first").
    const cancel = q<HTMLButtonElement>('.export-inspector__confirm-cancel');
    act(() => cancel?.focus());
    act(() => {
      dialog?.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true }));
    });
    expect(document.activeElement).toBe(cancel);
    // Escape IS still wired — the one affordance the shared component adds here.
    act(() => {
      dialog?.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    });
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it('fires onConfirm from the primary and onCancel from the secondary', () => {
    render();
    act(() => q<HTMLButtonElement>('.confirm-dialog-approve')?.click());
    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(onCancel).not.toHaveBeenCalled();
    act(() => q<HTMLButtonElement>('.confirm-dialog-cancel')?.click());
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it('traps Tab inside the gate, so aria-modal="true" is not a false claim', () => {
    // Without a trap, Tab off the last control lands on the surface the question
    // is about — while aria-modal tells a screen reader that surface is inert.
    render();
    const dialog = q<HTMLDivElement>('.confirm-dialog');
    const approve = q<HTMLButtonElement>('.confirm-dialog-approve');
    const cancel = q<HTMLButtonElement>('.confirm-dialog-cancel');
    // Forward off the LAST control wraps to the first.
    act(() => cancel?.focus());
    act(() => {
      dialog?.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true }));
    });
    expect(document.activeElement).toBe(approve);
    // Backward off the FIRST control wraps to the last.
    act(() => {
      dialog?.dispatchEvent(
        new KeyboardEvent('keydown', { key: 'Tab', shiftKey: true, bubbles: true }),
      );
    });
    expect(document.activeElement).toBe(cancel);
  });

  it('cancels on Escape and ignores every other key', () => {
    render();
    const dialog = q<HTMLDivElement>('.confirm-dialog');
    act(() => {
      dialog?.dispatchEvent(new KeyboardEvent('keydown', { key: 'a', bubbles: true }));
    });
    expect(onCancel).not.toHaveBeenCalled();
    act(() => {
      dialog?.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    });
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onConfirm).not.toHaveBeenCalled();
  });
});

describe('useConfirm', () => {
  let confirmer: Confirmer;

  function mount(): void {
    function Harness(): React.ReactElement {
      confirmer = useConfirm();
      return <div className="harness">{confirmer.confirmDialog}</div>;
    }
    act(() => {
      root.render(<Harness />);
    });
  }

  const request = {
    title: 'Delete this short?',
    blurb: 'clip.mp4',
    confirmLabel: 'Delete short',
    cancelLabel: 'Keep it',
  };

  it('renders nothing until a confirm is requested', () => {
    mount();
    expect(confirmer.confirmDialog).toBeNull();
    expect(q('[role="alertdialog"]')).toBeNull();
  });

  it('resolves TRUE when the primary is pressed, and never touches native confirm', async () => {
    const native = vi.spyOn(window, 'confirm');
    mount();
    let answer!: Promise<boolean>;
    act(() => {
      answer = confirmer.confirm(request);
    });
    expect(q('.confirm-dialog-title')?.textContent).toBe('Delete this short?');
    act(() => q<HTMLButtonElement>('.confirm-dialog-approve')?.click());
    await expect(answer!).resolves.toBe(true);
    // The gate closes behind the answer.
    expect(q('.confirm-dialog')).toBeNull();
    expect(native).not.toHaveBeenCalled();
  });

  it('opens a MODAL gate — the six native-confirm sites froze the page, so this must hold it', () => {
    mount();
    act(() => {
      void confirmer.confirm(request);
    });
    // All three halves of modality, together: scrim element, aria-modal, Tab cage.
    expect(q('.confirm-dialog-scrim')).not.toBeNull();
    expect(q('.confirm-dialog')?.getAttribute('aria-modal')).toBe('true');
    const approve = q<HTMLButtonElement>('.confirm-dialog-approve');
    const cancel = q<HTMLButtonElement>('.confirm-dialog-cancel');
    act(() => cancel?.focus());
    act(() => {
      q('.confirm-dialog')?.dispatchEvent(
        new KeyboardEvent('keydown', { key: 'Tab', bubbles: true }),
      );
    });
    expect(document.activeElement).toBe(approve);
  });

  it('resolves FALSE when the secondary is pressed', async () => {
    mount();
    let answer!: Promise<boolean>;
    act(() => {
      answer = confirmer.confirm(request);
    });
    act(() => q<HTMLButtonElement>('.confirm-dialog-cancel')?.click());
    await expect(answer!).resolves.toBe(false);
    expect(q('.confirm-dialog')).toBeNull();
  });

  it('supersedes an open request: the older awaiter is declined, not left hanging', async () => {
    mount();
    let first!: Promise<boolean>;
    let second!: Promise<boolean>;
    act(() => {
      first = confirmer.confirm(request);
    });
    act(() => {
      second = confirmer.confirm({ ...request, title: 'Reset presets?' });
    });
    // The first caller is settled immediately so its `await` cannot dangle.
    await expect(first!).resolves.toBe(false);
    expect(q('.confirm-dialog-title')?.textContent).toBe('Reset presets?');
    act(() => q<HTMLButtonElement>('.confirm-dialog-approve')?.click());
    await expect(second!).resolves.toBe(true);
  });
});
