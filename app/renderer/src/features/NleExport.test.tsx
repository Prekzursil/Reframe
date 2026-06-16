// NleExport.test.tsx — tests for the NLE timeline-export panel (captions-export).
//
// Mocks the typed client (lib/rpc) so `nle.export` is deterministic; renders with
// React 18 createRoot + act under jsdom and drives the format/fps selects + the
// export button. Mirrors the Shorts/Library test strategy.

// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

const exportMock = vi.fn();

vi.mock('../lib/rpc', () => ({
  client: { nle: { export: (...a: unknown[]) => exportMock(...a) } },
  hasApi: () => true,
}));

import { NleExport } from './NleExport';

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  exportMock.mockReset();
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

async function flush(): Promise<void> {
  await act(async () => {
    await Promise.resolve();
  });
}

function render(): void {
  act(() => {
    root.render(<NleExport videoId="v1" />);
  });
}

function click(label: string): void {
  const btn = Array.from(container.querySelectorAll('button')).find((b) =>
    (b.textContent ?? '').includes(label),
  );
  if (!btn) throw new Error(`button not found: ${label}`);
  act(() => btn.dispatchEvent(new MouseEvent('click', { bubbles: true })));
}

describe('NleExport', () => {
  it('renders the format + fps selects and the export button', () => {
    render();
    expect(container.querySelector('#nle-format')).toBeTruthy();
    expect(container.querySelector('#nle-fps')).toBeTruthy();
    expect(container.textContent).toContain('Export timeline');
  });

  it('offers all four frame rates', () => {
    render();
    const fps = container.querySelector('#nle-fps') as HTMLSelectElement;
    const values = Array.from(fps.options).map((o) => o.value);
    expect(values).toEqual(['24', '25', '30', '60']);
  });

  it('exports with the selected format + fps and shows the saved path', async () => {
    exportMock.mockResolvedValue({ path: '/exports/v1-timeline.edl', clipCount: 3 });
    render();
    // Change format -> csv, fps -> 25.
    const fmt = container.querySelector('#nle-format') as HTMLSelectElement;
    const fps = container.querySelector('#nle-fps') as HTMLSelectElement;
    act(() => {
      fmt.value = 'csv';
      fmt.dispatchEvent(new Event('change', { bubbles: true }));
      fps.value = '25';
      fps.dispatchEvent(new Event('change', { bubbles: true }));
    });
    click('Export timeline');
    await flush();
    expect(exportMock).toHaveBeenCalledWith('v1', { format: 'csv', fps: 25 });
    expect(container.textContent).toContain('Exported 3 clips');
    expect(container.textContent).toContain('/exports/v1-timeline.edl');
  });

  it('reports an empty-timeline export distinctly', async () => {
    exportMock.mockResolvedValue({ path: '/exports/v1-timeline.edl', clipCount: 0 });
    render();
    click('Export timeline');
    await flush();
    expect(container.textContent).toContain('no approved clips');
  });

  it('surfaces an export error', async () => {
    exportMock.mockRejectedValue(new Error('disk full'));
    render();
    click('Export timeline');
    await flush();
    const alert = container.querySelector('[role="alert"]');
    expect(alert?.textContent).toContain('disk full');
  });
});
