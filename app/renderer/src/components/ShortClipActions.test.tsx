// ShortClipActions.test.tsx — tests for the per-clip action row (captions-export
// adds the optional Package-for-upload action). Pure presentational component:
// render with React 18 createRoot + act under jsdom, click buttons, assert the
// injected callbacks fire with the clip path.

// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import { ShortClipActions } from './ShortClipActions';

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

function clickLabel(label: string): void {
  const btn = Array.from(container.querySelectorAll('button')).find(
    (b) => b.getAttribute('aria-label') === label,
  );
  if (!btn) throw new Error(`button not found: ${label}`);
  act(() => btn.dispatchEvent(new MouseEvent('click', { bubbles: true })));
}

const noop = () => {};

describe('ShortClipActions', () => {
  it('omits the Package button when onPackage is not provided', () => {
    act(() => {
      root.render(
        <ShortClipActions
          path="/c.mp4"
          label="Clip"
          playing={false}
          onPlay={noop}
          onOpenFolder={noop}
          onReexport={noop}
          onDelete={noop}
        />,
      );
    });
    const labels = Array.from(container.querySelectorAll('button')).map((b) =>
      b.getAttribute('aria-label'),
    );
    expect(labels).not.toContain('Package Clip for upload');
  });

  it('renders the Package button and fires onPackage with the path', () => {
    const onPackage = vi.fn();
    act(() => {
      root.render(
        <ShortClipActions
          path="/clip.mp4"
          label="Clip"
          playing={false}
          onPlay={noop}
          onOpenFolder={noop}
          onReexport={noop}
          onDelete={noop}
          onPackage={onPackage}
        />,
      );
    });
    clickLabel('Package Clip for upload');
    expect(onPackage).toHaveBeenCalledWith('/clip.mp4');
  });

  it('disables the Package button and shows Packaging… while in flight', () => {
    act(() => {
      root.render(
        <ShortClipActions
          path="/clip.mp4"
          label="Clip"
          playing={false}
          packaging
          onPlay={noop}
          onOpenFolder={noop}
          onReexport={noop}
          onDelete={noop}
          onPackage={vi.fn()}
        />,
      );
    });
    const btn = Array.from(container.querySelectorAll('button')).find(
      (b) => b.getAttribute('aria-label') === 'Package Clip for upload',
    ) as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
    expect(btn.textContent).toContain('Packaging');
  });
});
