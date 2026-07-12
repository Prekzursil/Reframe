// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { EditorProvider } from '../EditorContext';
import type { EditorSeed } from '../../lib/editorState';
import { ExportStage } from './ExportStage';

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

function render(seed: EditorSeed): void {
  act(() => {
    root.render(
      <EditorProvider seed={seed}>
        <ExportStage />
      </EditorProvider>,
    );
  });
}

const labelValue = (label: string): string | undefined => {
  const items = Array.from(container.querySelectorAll('.export-stage__item'));
  const item = items.find((el) => el.querySelector('.export-stage__label')?.textContent === label);
  return item?.querySelector('.export-stage__value')?.textContent ?? undefined;
};

describe('ExportStage', () => {
  it('previews the clip and summarizes the baked length, captions, and framing', () => {
    render({
      video: { videoId: 'v1', window: { start: 0, end: 45 } },
      cues: [
        { index: 1, start: 1, end: 2, text: 'Hi' },
        { index: 2, start: 3, end: 4, text: 'there' },
      ],
      cropPlan: { engine: 'verthor' },
    });
    expect(q('.export-stage')).not.toBeNull();
    expect(q('video')).not.toBeNull();
    expect(labelValue('Length')).toBe('0:45');
    expect(labelValue('Captions')).toBe('2 captions');
    // Framing reads "Reframed" — never the raw engine id.
    expect(labelValue('Framing')).toBe('Reframed');
    expect(q('.export-stage')?.textContent).not.toContain('verthor');
  });

  it('summarizes an un-captioned, un-reframed clip', () => {
    render({ video: { videoId: 'v2', window: { start: 0, end: 12 } } });
    expect(labelValue('Captions')).toBe('No captions');
    expect(labelValue('Framing')).toBe('Original framing');
  });
});
