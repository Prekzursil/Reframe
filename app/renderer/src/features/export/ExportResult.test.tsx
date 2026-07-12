// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { ExportResult, type ExportResultProps } from './ExportResult';

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;
const onReveal = vi.fn();
const onDeliver = vi.fn();
const onExportAgain = vi.fn();

beforeEach(() => {
  onReveal.mockReset();
  onDeliver.mockReset();
  onExportAgain.mockReset();
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
const all = (sel: string): Element[] => Array.from(container.querySelectorAll(sel));

function render(props: Partial<ExportResultProps> & Pick<ExportResultProps, 'outcome'>): void {
  act(() => {
    root.render(
      <ExportResult
        outcome={props.outcome}
        destination={props.destination ?? 'TikTok'}
        paths={props.paths ?? []}
        error={props.error}
        onReveal={props.onReveal}
        onDeliver={props.onDeliver ?? onDeliver}
        onExportAgain={props.onExportAgain ?? onExportAgain}
      />,
    );
  });
}

describe('ExportResult', () => {
  it('SUCCESS wires output locations to a reveal and links into Deliver', () => {
    render({ outcome: 'done', paths: ['/out/a.mp4', '/out/b.mp4'], onReveal });
    expect(q('.export-result')?.className).toContain('is-done');
    expect(q('.export-result__title')?.textContent).toBe('Exported to TikTok');
    // The completion is announced (role=status) and HONEST about framing: Export saved
    // the CURRENT framing locally — it never claims a per-destination aspect output.
    const blurb = q('.export-result__blurb');
    expect(blurb?.getAttribute('role')).toBe('status');
    expect(blurb?.textContent).toBe(
      'Saved to your machine at its current framing — nothing was uploaded.',
    );
    expect(all('.export-result__output').length).toBe(2);
    // Reveal each written file in the OS explorer.
    act(() => q<HTMLButtonElement>('.export-result__reveal')?.click());
    expect(onReveal).toHaveBeenCalledWith('/out/a.mp4');
    // Continue into Deliver + export another.
    act(() => q<HTMLButtonElement>('.export-result__deliver')?.click());
    expect(onDeliver).toHaveBeenCalledTimes(1);
    act(() => q<HTMLButtonElement>('.export-result__again')?.click());
    expect(onExportAgain).toHaveBeenCalledTimes(1);
  });

  it('SUCCESS without a reveal bridge omits the reveal button', () => {
    render({ outcome: 'done', paths: ['/out/a.mp4'] });
    expect(q('.export-result__reveal')).toBeNull();
    expect(q('.export-result__path')?.textContent).toBe('/out/a.mp4');
  });

  it('FAILURE surfaces the error in an assertive alert with a retry', () => {
    render({ outcome: 'failed', error: 'ffmpeg exploded' });
    expect(q('.export-result')?.className).toContain('is-failed');
    expect(q('.export-result__title')?.textContent).toBe('Export failed');
    const alert = q('.export-result__error');
    expect(alert?.getAttribute('role')).toBe('alert');
    expect(alert?.textContent).toBe('ffmpeg exploded');
    act(() => q<HTMLButtonElement>('.export-result__again')?.click());
    expect(onExportAgain).toHaveBeenCalledTimes(1);
  });

  it('CANCEL states plainly that no file was written and announces via role=status', () => {
    render({ outcome: 'cancelled' });
    expect(q('.export-result')?.className).toContain('is-cancelled');
    expect(q('.export-result__title')?.textContent).toBe('Export cancelled');
    const blurb = q('.export-result__blurb');
    expect(blurb?.textContent).toBe('No file was written.');
    // The terminal cancel reaches SR users through a polite live region (not just visually).
    expect(blurb?.getAttribute('role')).toBe('status');
    expect(q('.export-result__error')).toBeNull();
  });
});
