// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import type { EditorSeed } from '../../lib/editorState';
import { TRUST_REVERSIBLE, TRUST_TEXT_EGRESS } from '../../lib/directorHandoff';
import { EditorProvider } from '../EditorContext';
import { DirectorHandoff } from './DirectorHandoff';

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

const WINDOW = { start: 0, end: 10 };
const CUE = (index: number) => ({ index, start: index, end: index + 1, text: `w${index}` });

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
});

const q = <T extends Element>(sel: string): T | null => container.querySelector<T>(sel);

function render(over: Partial<EditorSeed> = {}): void {
  const seed: EditorSeed = {
    video: { videoId: 'v1', window: WINDOW, durationSec: 10 },
    ...over,
  };
  act(() => {
    root.render(
      <EditorProvider seed={seed}>
        <DirectorHandoff />
      </EditorProvider>,
    );
  });
}

describe('DirectorHandoff', () => {
  it('titles the surface and restates the reversible trust line verbatim', () => {
    render();
    expect(q('.director-handoff__title')?.textContent).toBe('Where your edit lands');
    expect(q('.director-handoff__lede')?.textContent).toBe(TRUST_REVERSIBLE);
  });

  it('renders the three per-phase routes in order with their destinations', () => {
    render();
    const routes = Array.from(container.querySelectorAll('.director-handoff__route'));
    expect(routes.map((r) => r.getAttribute('data-phase'))).toEqual(['edit', 'caption', 'reframe']);
    expect(
      Array.from(container.querySelectorAll('.director-handoff__dest')).map((d) => d.textContent),
    ).toEqual(['Edit', 'Caption', 'Reframe']);
    // Every route carries a plain-language change label + a blurb.
    expect(q('[data-phase="edit"] .director-handoff__change')?.textContent).toBe('Cuts & pacing');
    expect(
      q('[data-phase="reframe"] .director-handoff__blurb')?.textContent?.length,
    ).toBeGreaterThan(0);
  });

  it('reflects a fully-seeded editor state as ready landing zones', () => {
    render({ cues: [CUE(1), CUE(2)], cropPlan: { engine: 'x' } });
    expect(q('[data-phase="edit"]')?.getAttribute('data-ready')).toBe('yes');
    expect(q('[data-phase="caption"]')?.getAttribute('data-ready')).toBe('yes');
    expect(q('[data-phase="reframe"]')?.getAttribute('data-ready')).toBe('yes');
    expect(q('[data-testid="zone-caption"]')?.textContent).toBe(
      'Transcript ready — 2 words to re-time.',
    );
  });

  it('reflects a bare editor state as pending caption + reframe zones', () => {
    render();
    expect(q('[data-phase="edit"]')?.getAttribute('data-ready')).toBe('yes');
    expect(q('[data-phase="caption"]')?.getAttribute('data-ready')).toBe('no');
    expect(q('[data-phase="reframe"]')?.getAttribute('data-ready')).toBe('no');
    expect(q('[data-testid="zone-caption"]')?.textContent).toBe(
      'No transcript yet — the Director reads the speech first.',
    );
    expect(q('[data-testid="zone-reframe"]')?.textContent).toBe(
      'No crop plan yet — framing starts from center.',
    );
  });

  it('surfaces the verbatim text-egress privacy beat', () => {
    render();
    expect(q('.director-handoff__egress')?.textContent).toBe(TRUST_TEXT_EGRESS);
  });
});
