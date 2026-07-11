// @vitest-environment jsdom
import React from 'react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { EditorProvider, useEditor } from './EditorContext';
import { DEFAULT_CAPTION_DESIGN } from '../lib/captionDesign';

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

const WINDOW = { start: 1, end: 5 };

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

function q<T extends Element>(sel: string): T {
  const el = container.querySelector<T>(sel);
  if (!el) throw new Error(`missing ${sel}`);
  return el;
}

/** A probe consumer that renders the current style + a button to change it. */
function Probe(): React.ReactElement {
  const { state, dispatch } = useEditor();
  return (
    <div>
      <span data-testid="style">{state.design.style}</span>
      <span data-testid="playhead">{state.playhead}</span>
      <button type="button" onClick={() => dispatch({ type: 'setStyle', style: 'serif' })}>
        style
      </button>
      <button type="button" onClick={() => dispatch({ type: 'setPlayhead', playhead: 3 })}>
        seek
      </button>
    </div>
  );
}

class Boundary extends React.Component<
  { children: React.ReactNode; onError: (e: Error) => void },
  { failed: boolean }
> {
  state = { failed: false };
  static getDerivedStateFromError(): { failed: boolean } {
    return { failed: true };
  }
  componentDidCatch(err: Error): void {
    this.props.onError(err);
  }
  render(): React.ReactNode {
    return this.state.failed ? null : this.props.children;
  }
}

describe('EditorProvider + useEditor', () => {
  it('seeds the shared state and exposes it to a consumer', () => {
    act(() => {
      root.render(
        <EditorProvider seed={{ video: { videoId: 'v1', window: WINDOW } }}>
          <Probe />
        </EditorProvider>,
      );
    });
    expect(q('[data-testid="style"]').textContent).toBe(DEFAULT_CAPTION_DESIGN.style);
    expect(q('[data-testid="playhead"]').textContent).toBe('1');
  });

  it('dispatches reducer actions that update every consumer', () => {
    act(() => {
      root.render(
        <EditorProvider seed={{ video: { videoId: 'v1', window: WINDOW } }}>
          <Probe />
        </EditorProvider>,
      );
    });
    act(() => {
      q<HTMLButtonElement>('button:nth-of-type(1)').click();
      q<HTMLButtonElement>('button:nth-of-type(2)').click();
    });
    expect(q('[data-testid="style"]').textContent).toBe('serif');
    expect(q('[data-testid="playhead"]').textContent).toBe('3');
  });

  it('throws when used outside an EditorProvider', () => {
    let captured: Error | null = null;
    act(() => {
      root.render(
        <Boundary onError={(e) => (captured = e)}>
          <Probe />
        </Boundary>,
      );
    });
    expect(captured).not.toBeNull();
    expect((captured as unknown as Error).message).toMatch(/within an EditorProvider/);
  });
});
