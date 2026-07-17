// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { ExportProgress } from './ExportProgress';

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;
const onCancel = vi.fn();

beforeEach(() => {
  onCancel.mockReset();
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

describe('ExportProgress', () => {
  it('renders determinate progress with a rounded percent and a polite message', () => {
    act(() => {
      root.render(
        <ExportProgress
          destination="TikTok"
          pct={42.7}
          message="Rendering frames…"
          onCancel={onCancel}
        />,
      );
    });
    expect(q('.export-progress__title')?.textContent).toBe('Exporting to TikTok');
    expect(q('.export-progress__pct')?.textContent).toBe('43%');
    const bar = q<HTMLProgressElement>('progress.export-progress__track');
    expect(bar?.max).toBe(100);
    expect(bar?.value).toBeCloseTo(42.7);
    const status = q('.export-progress__message');
    expect(status?.getAttribute('aria-live')).toBe('polite');
    expect(status?.textContent).toBe('Rendering frames…');
  });

  it('exposes a real cancel control', () => {
    act(() => {
      root.render(<ExportProgress destination="Reels" pct={10} message="" onCancel={onCancel} />);
    });
    act(() => q<HTMLButtonElement>('.export-progress__cancel')?.click());
    expect(onCancel).toHaveBeenCalledTimes(1);
  });
});
