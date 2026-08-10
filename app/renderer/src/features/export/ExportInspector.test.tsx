// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { EditorProvider } from '../EditorContext';
import type { EditorSeed } from '../../lib/editorState';
import {
  EXPORT_CONFIRM_BLURB,
  EXPORT_FRAMING_NOTE,
  EXPORT_PRIVACY_NOTE,
  ExportInspector,
} from './ExportInspector';
import { exportConvertOptions, presetsByIds } from './exportModel';

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;
const onCommit = vi.fn();

beforeEach(() => {
  onCommit.mockReset();
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

function render(seed: EditorSeed): void {
  act(() => {
    root.render(
      <EditorProvider seed={seed}>
        <ExportInspector onCommit={onCommit} />
      </EditorProvider>,
    );
  });
}

const SEED: EditorSeed = { video: { videoId: 'v1', window: { start: 0, end: 40 } } };

describe('ExportInspector', () => {
  it('shows the pre-flight summary + the restated privacy beat, and defaults to a fitting destination', () => {
    render(SEED);
    // 40s clip: the first destination (TikTok, 9:16) fits and is the default.
    expect(q('.export-inspector__preflight-title')?.textContent).toBe('Ready to export to TikTok');
    const values = Array.from(container.querySelectorAll('.export-inspector__cell-value')).map(
      (el) => el.textContent,
    );
    // SCOPE FIX (v1.5 aspect-matrix): the grid gained an ASPECTS cell and "Clips"
    // became "Files", because a multi-select fan-out writes one file per DISTINCT
    // aspect. The framing cell (now index 2) still states the framing the export
    // actually writes — never a per-destination aspect Export cannot produce.
    expect(values).toEqual(['1', '9:16', 'Original framing', '0:40', '~0:20', '$0.00']);
    expect(q('.export-inspector__privacy')?.textContent).toBe(EXPORT_PRIVACY_NOTE);
    // The primary CTA is present and NOT yet a confirm.
    expect(q('.export-inspector__primary')?.textContent).toBe('Export to TikTok');
    expect(q('.export-inspector__confirm')).toBeNull();
  });

  it('discloses that the fan-out never re-crops, where the fan-out is chosen', () => {
    render(SEED);
    // The disclosure the matrix hint used to carry. It has to stay SOMEWHERE
    // visible: the fan-out writes a file per aspect, but each file keeps the
    // upstream framing, so a user picking 1:1 must not expect a square re-crop.
    expect(q('.export-inspector__framing-note')?.textContent).toBe(EXPORT_FRAMING_NOTE);
    expect(EXPORT_FRAMING_NOTE).toContain('never re-crops');
  });

  it('ADDS a destination to the fan-out and re-summarizes files + aspects', () => {
    render(SEED);
    const cells = (): (string | null)[] =>
      Array.from(container.querySelectorAll('.export-inspector__cell-value')).map(
        (el) => el.textContent,
      );
    expect(cells()[0]).toBe('1');
    act(() => q<HTMLButtonElement>('[data-preset="square"]')?.click());
    // Two aspects -> two files, both listed, and the estimate doubles.
    expect(cells()[0]).toBe('2');
    expect(cells()[1]).toBe('9:16 · 1:1');
    expect(cells()[4]).toBe('~0:40');
    expect(q('.export-inspector__preflight-title')?.textContent).toBe(
      'Ready to export to TikTok + 1 more',
    );
    expect(q('.export-inspector__primary')?.textContent).toBe('Export to TikTok + 1 more');
    // Honest: adding a destination NEVER changes the framing — Export does not re-crop.
    expect(cells()[2]).toBe('Original framing');
  });

  it('collapses same-aspect destinations to a single file in the pre-flight', () => {
    render(SEED);
    act(() => q<HTMLButtonElement>('[data-preset="reels"]')?.click());
    const cells = Array.from(container.querySelectorAll('.export-inspector__cell-value')).map(
      (el) => el.textContent,
    );
    // TikTok + Reels are two destinations but one 9:16 render.
    expect(cells[0]).toBe('1');
    expect(cells[1]).toBe('9:16');
  });

  it('states the REFRAMED framing in the pre-flight when the clip carries a crop plan', () => {
    render({
      video: { videoId: 'v1', window: { start: 0, end: 40 } },
      cropPlan: { engine: 'verthor' },
    });
    const framingCell = container.querySelectorAll('.export-inspector__cell-value')[2]?.textContent;
    expect(framingCell).toBe('Reframed');
  });

  it('opens an announced alertdialog and moves focus to its primary action (WCAG 2.4.3)', () => {
    render(SEED);
    act(() => q<HTMLButtonElement>('.export-inspector__primary')?.click());
    const dialog = q('.export-inspector__confirm');
    // The confirm gate is an announced alertdialog, labelled + described by its own copy.
    expect(dialog?.getAttribute('role')).toBe('alertdialog');
    const titleId = q('.export-inspector__confirm-title')?.id;
    const blurbId = q('.export-inspector__confirm-blurb')?.id;
    expect(titleId).toBeTruthy();
    expect(blurbId).toBeTruthy();
    expect(dialog?.getAttribute('aria-labelledby')).toBe(titleId);
    expect(dialog?.getAttribute('aria-describedby')).toBe(blurbId);
    // Focus lands on the primary action, so it never drops to <body> when the gate opens.
    expect(document.activeElement).toBe(q('.export-inspector__confirm-approve'));
  });

  it('guards the commit behind an explicit confirm gate', () => {
    render(SEED);
    // Step 1: the primary opens the confirm gate — it does NOT commit yet.
    act(() => q<HTMLButtonElement>('.export-inspector__primary')?.click());
    expect(onCommit).not.toHaveBeenCalled();
    expect(q('.export-inspector__confirm-title')?.textContent).toBe('Export to TikTok?');
    expect(q('.export-inspector__confirm-blurb')?.textContent).toBe(EXPORT_CONFIRM_BLURB);
    // The matrix is locked while confirming.
    expect(q<HTMLButtonElement>('[data-preset="square"]')?.disabled).toBe(true);
    // Step 2: "Export now" fires the commit with the chosen preset + render profile.
    act(() => q<HTMLButtonElement>('.export-inspector__confirm-approve')?.click());
    expect(onCommit).toHaveBeenCalledTimes(1);
    // SCOPE FIX (v1.5 aspect-matrix): the commit carries the whole ORDERED SET of
    // destinations, not a single preset — the host de-dupes it into one render
    // per aspect. Still exactly one commit, still behind the same confirm gate.
    expect(onCommit).toHaveBeenCalledWith(presetsByIds(['tiktok']), exportConvertOptions());
    // The gate closes after committing.
    expect(q('.export-inspector__confirm')).toBeNull();
  });

  // -------------------------------------------------------------------------
  // The three things the W04 extraction actually changed on THIS surface.
  // -------------------------------------------------------------------------
  // Before W04 this gate was hand-rolled inline in ExportInspector.tsx: role,
  // labelledby/describedby and focus-on-open, and nothing else. Sharing the
  // ConfirmDialog component put three new behaviours within reach of it —
  // `aria-modal`, a Tab cage, and Escape — and the cases above (role, ids, focus,
  // copy, cancel) are structurally incapable of seeing any of them. Two are
  // deliberately NOT taken here (this gate is an inline card in a live panel, not
  // an overlay); one is. All three are pinned so the choice cannot drift silently.

  it('does NOT claim aria-modal — the page around this inline card stays live', () => {
    render(SEED);
    act(() => q<HTMLButtonElement>('.export-inspector__primary')?.click());
    const dialog = q('.export-inspector__confirm');
    // export.css `.export-inspector__confirm` is a plain in-flow block: no fixed
    // positioning, no scrim. `aria-modal="true"` here would tell a screen-reader
    // user the inspector, the tab bar and the timeline behind are inert while a
    // mouse user can still click every one of them.
    expect(dialog?.hasAttribute('aria-modal')).toBe(false);
    expect(q('.export-inspector__confirm-scrim')).toBeNull();
  });

  it('does NOT cage Tab — a keyboard user can leave a card a mouse user can click past', () => {
    render(SEED);
    act(() => q<HTMLButtonElement>('.export-inspector__primary')?.click());
    const dialog = q<HTMLDivElement>('.export-inspector__confirm');
    const cancel = q<HTMLButtonElement>('.export-inspector__confirm-cancel');
    act(() => cancel?.focus());
    act(() => {
      dialog?.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true }));
    });
    // jsdom moves no focus on Tab by itself, so "still on cancel" is exactly "the
    // trap did not wrap focus back to the approve button".
    expect(document.activeElement).toBe(cancel);
  });

  it('DOES back out on Escape — the one affordance the shared gate adds here', () => {
    render(SEED);
    act(() => q<HTMLButtonElement>('.export-inspector__primary')?.click());
    act(() => {
      q<HTMLDivElement>('.export-inspector__confirm')?.dispatchEvent(
        new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }),
      );
    });
    expect(onCommit).not.toHaveBeenCalled();
    expect(q('.export-inspector__confirm')).toBeNull();
    expect(q('.export-inspector__primary')).not.toBeNull();
  });

  it('lets the user back out of the confirm gate without committing', () => {
    render(SEED);
    act(() => q<HTMLButtonElement>('.export-inspector__primary')?.click());
    act(() => q<HTMLButtonElement>('.export-inspector__confirm-cancel')?.click());
    expect(onCommit).not.toHaveBeenCalled();
    // Back to the primary CTA, matrix re-enabled.
    expect(q('.export-inspector__primary')).not.toBeNull();
    expect(q<HTMLButtonElement>('[data-preset="square"]')?.disabled).toBe(false);
  });
});
