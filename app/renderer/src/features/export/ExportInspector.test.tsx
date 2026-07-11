// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { EditorProvider } from '../EditorContext';
import type { EditorSeed } from '../../lib/editorState';
import { EXPORT_CONFIRM_BLURB, EXPORT_PRIVACY_NOTE, ExportInspector } from './ExportInspector';
import { exportConvertOptions, presetById } from './exportModel';

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
    expect(values).toEqual(['1', '9:16', '0:40', '~0:20', '$0.00']);
    expect(q('.export-inspector__privacy')?.textContent).toBe(EXPORT_PRIVACY_NOTE);
    // The primary CTA is present and NOT yet a confirm.
    expect(q('.export-inspector__primary')?.textContent).toBe('Export to TikTok');
    expect(q('.export-inspector__confirm')).toBeNull();
  });

  it('re-summarizes when a different destination is chosen', () => {
    render(SEED);
    act(() => q<HTMLButtonElement>('[data-preset="square"]')?.click());
    expect(q('.export-inspector__preflight-title')?.textContent).toBe(
      'Ready to export to Square post',
    );
    const aspect = container.querySelectorAll('.export-inspector__cell-value')[1]?.textContent;
    expect(aspect).toBe('1:1');
    expect(q('.export-inspector__primary')?.textContent).toBe('Export to Square post');
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
    expect(onCommit).toHaveBeenCalledWith(presetById('tiktok'), exportConvertOptions());
    // The gate closes after committing.
    expect(q('.export-inspector__confirm')).toBeNull();
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
