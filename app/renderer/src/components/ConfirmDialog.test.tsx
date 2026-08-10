// ConfirmDialog.test.tsx — the shared THEMED destructive-confirm gate (W04).
//
// The six destructive actions in this app used to call the native `confirm()`.
// Native confirm is unthemeable, cannot be labelled/described for AT, and in
// Electron it blocks the renderer process outright. This suite pins the themed
// replacement: an announced `alertdialog`, focus moved onto its primary action,
// Escape as the cancel affordance, and a promise-shaped `useConfirm()` so a call
// site keeps its `const ok = await confirm(...)` shape.

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

  function render(block = 'confirm-dialog'): void {
    act(() => {
      root.render(
        <ConfirmDialog
          block={block}
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
    // aria-modal is only honest because Tab is actually trapped — pinned below.
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
    render('export-inspector__confirm');
    expect(q('.confirm-dialog')).toBeNull();
    expect(q('.export-inspector__confirm')?.getAttribute('role')).toBe('alertdialog');
    expect(q('.export-inspector__confirm-title')?.textContent).toBe('Delete this short?');
    expect(q('.export-inspector__confirm-approve')?.textContent).toBe('Delete short');
    expect(q('.export-inspector__confirm-cancel')?.textContent).toBe('Keep it');
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
