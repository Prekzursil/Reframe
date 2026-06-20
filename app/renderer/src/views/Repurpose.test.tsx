// Repurpose.test.tsx — the tabbed Repurpose view (BatchQueue default landing).

// @vitest-environment jsdom
import { describe, it, expect, vi, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

// Stub the three panels so the view test exercises ONLY the tab switch + the
// resumeId pass-through (the panels own their own tests).
vi.mock('../features/BatchQueue', () => ({
  BatchQueue: ({ resumeId }: { resumeId?: string }) => (
    <div data-testid="queue" data-resume={resumeId ?? ''} />
  ),
}));
vi.mock('../features/TemplateEditor', () => ({
  TemplateEditor: () => <div data-testid="templates" />,
}));
vi.mock('../features/ExportPresetsPanel', () => ({
  ExportPresetsPanel: () => <div data-testid="presets" />,
}));

import { Repurpose } from './Repurpose';

let container: HTMLElement;
let root: Root;

function render(props: { resumeId?: string } = {}): void {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  act(() => {
    root.render(<Repurpose {...props} />);
  });
}

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

function clickTab(label: string): void {
  const tab = [...container.querySelectorAll('[role="tab"]')].find((t) => t.textContent === label);
  if (!tab) throw new Error(`tab not found: ${label}`);
  act(() => tab.dispatchEvent(new MouseEvent('click', { bubbles: true })));
}

describe('Repurpose', () => {
  it('lands on the Batch queue and passes the resumeId through', () => {
    render({ resumeId: 'b1' });
    const queue = container.querySelector('[data-testid="queue"]');
    expect(queue).not.toBeNull();
    expect(queue?.getAttribute('data-resume')).toBe('b1');
    expect(container.querySelector('[data-testid="templates"]')).toBeNull();
  });

  it('switches to Templates and Export presets tabs', () => {
    render();
    clickTab('Templates');
    expect(container.querySelector('[data-testid="templates"]')).not.toBeNull();
    expect(container.querySelector('[data-testid="queue"]')).toBeNull();
    clickTab('Export presets');
    expect(container.querySelector('[data-testid="presets"]')).not.toBeNull();
    clickTab('Batch queue');
    expect(container.querySelector('[data-testid="queue"]')).not.toBeNull();
  });

  it('marks the active tab with aria-selected', () => {
    render();
    const tabs = [...container.querySelectorAll('[role="tab"]')];
    const queueTab = tabs.find((t) => t.textContent === 'Batch queue');
    expect(queueTab?.getAttribute('aria-selected')).toBe('true');
  });
});
