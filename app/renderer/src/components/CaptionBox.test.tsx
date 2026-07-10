// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { CaptionBox } from './CaptionBox';
import {
  DEFAULT_CAPTION_BOX,
  moveBox,
  resizeBox,
  type CaptionBox as Box,
} from '../lib/captionPosition';

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

/** Dispatch a pointer event (jsdom has no PointerEvent ctor — use MouseEvent). */
function pointer(el: Element, type: string, x: number, y: number, pointerId = 7): void {
  const ev = new MouseEvent(type, { bubbles: true, clientX: x, clientY: y });
  Object.defineProperty(ev, 'pointerId', { value: pointerId });
  act(() => {
    el.dispatchEvent(ev);
  });
}

/** Stub the frame's measured size so fractional deltas are deterministic. */
function stubFrame(container: HTMLElement, width: number, height: number): void {
  const frame = container.querySelector('.caption-box-frame') as HTMLElement;
  frame.getBoundingClientRect = () =>
    ({ width, height, top: 0, left: 0, right: width, bottom: height, x: 0, y: 0 }) as DOMRect;
}

describe('<CaptionBox />', () => {
  let container: HTMLDivElement;
  let root: Root;
  const start: Box = { x: 0.2, y: 0.2, w: 0.4, h: 0.4 };

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });
  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  function render(props: Partial<React.ComponentProps<typeof CaptionBox>> = {}): {
    onChange: ReturnType<typeof vi.fn>;
  } {
    const onChange = props.onChange ?? vi.fn();
    act(() => root.render(<CaptionBox box={props.box ?? start} {...props} onChange={onChange} />));
    return { onChange: onChange as ReturnType<typeof vi.fn> };
  }

  const box = (): HTMLElement =>
    container.querySelector('[data-testid="caption-box"]') as HTMLElement;
  const handle = (h: string): HTMLElement =>
    container.querySelector(`[data-handle="${h}"]`) as HTMLElement;
  const keydown = (el: HTMLElement, key: string): void => {
    act(() => {
      el.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true }));
    });
  };

  it('renders the box + all eight resize handles', () => {
    render();
    expect(box()).toBeTruthy();
    expect(container.querySelectorAll('.caption-box__handle')).toHaveLength(8);
    expect(container.querySelector('.caption-box-frame')?.getAttribute('aria-label')).toBe(
      'Caption position',
    );
  });

  it('renders a custom label and children', () => {
    act(() =>
      root.render(
        <CaptionBox box={start} onChange={vi.fn()} label="Where">
          <span className="sample">Hi</span>
        </CaptionBox>,
      ),
    );
    expect(container.querySelector('.caption-box-frame')?.getAttribute('aria-label')).toBe('Where');
    expect(container.querySelector('.sample')?.textContent).toBe('Hi');
  });

  it('drags the body to move the box', () => {
    const { onChange } = render();
    stubFrame(container, 100, 100);
    pointer(box(), 'pointerdown', 0, 0);
    pointer(box(), 'pointermove', 50, 0); // +0.5 x
    expect(onChange).toHaveBeenLastCalledWith(moveBox(start, 0.5, 0));
    pointer(box(), 'pointerup', 50, 0);
  });

  it('drags a handle to resize the box', () => {
    const { onChange } = render();
    stubFrame(container, 100, 100);
    pointer(handle('e'), 'pointerdown', 0, 0);
    pointer(box(), 'pointermove', 10, 0); // +0.1 width
    expect(onChange).toHaveBeenLastCalledWith(resizeBox(start, 'e', 0.1, 0));
  });

  it('ignores pointer move when no drag is active', () => {
    const { onChange } = render();
    stubFrame(container, 100, 100);
    pointer(box(), 'pointermove', 50, 50);
    expect(onChange).not.toHaveBeenCalled();
  });

  it('treats an unmeasured frame (zero size) as no movement', () => {
    const { onChange } = render();
    stubFrame(container, 0, 0);
    pointer(box(), 'pointerdown', 0, 0);
    pointer(box(), 'pointermove', 50, 50);
    expect(onChange).toHaveBeenLastCalledWith(moveBox(start, 0, 0));
  });

  it('uses pointer capture when the element supports it', () => {
    render();
    stubFrame(container, 100, 100);
    const capture = vi.fn();
    const release = vi.fn();
    box().setPointerCapture = capture;
    box().releasePointerCapture = release;
    pointer(box(), 'pointerdown', 0, 0);
    expect(capture).toHaveBeenCalledWith(7);
    pointer(box(), 'pointerup', 0, 0);
    expect(release).toHaveBeenCalledWith(7);
  });

  it('does not interact when disabled (no handles, no onChange)', () => {
    const { onChange } = render({ disabled: true });
    expect(container.querySelectorAll('.caption-box__handle')).toHaveLength(0);
    expect(box().className).toContain('is-readonly');
    stubFrame(container, 100, 100);
    pointer(box(), 'pointerdown', 0, 0);
    pointer(box(), 'pointermove', 50, 0);
    expect(onChange).not.toHaveBeenCalled();
  });

  // WCAG 2.1.1 keyboard operability (bug-sweep fix).
  it('moves the box with arrow keys', () => {
    const { onChange } = render();
    keydown(box(), 'ArrowRight');
    expect(onChange).toHaveBeenLastCalledWith(moveBox(start, 0.02, 0));
    keydown(box(), 'ArrowLeft');
    expect(onChange).toHaveBeenLastCalledWith(moveBox(start, -0.02, 0));
    keydown(box(), 'ArrowDown');
    expect(onChange).toHaveBeenLastCalledWith(moveBox(start, 0, 0.02));
    keydown(box(), 'ArrowUp');
    expect(onChange).toHaveBeenLastCalledWith(moveBox(start, 0, -0.02));
  });

  it('ignores non-arrow keys on the box body', () => {
    const { onChange } = render();
    keydown(box(), 'Enter');
    expect(onChange).not.toHaveBeenCalled();
  });

  it('does not move via keyboard when disabled', () => {
    const { onChange } = render({ disabled: true });
    keydown(box(), 'ArrowRight');
    expect(onChange).not.toHaveBeenCalled();
  });

  it('resizes from a focused handle with arrow keys', () => {
    const { onChange } = render();
    keydown(handle('e'), 'ArrowRight');
    expect(onChange).toHaveBeenLastCalledWith(resizeBox(start, 'e', 0.02, 0));
  });

  it('ignores non-arrow keys on a handle', () => {
    const { onChange } = render();
    keydown(handle('e'), 'Enter');
    expect(onChange).not.toHaveBeenCalled();
  });

  it('ignores a pointer up with no active drag', () => {
    render();
    // pointerup with nothing started — exercises the early return.
    expect(() => pointer(box(), 'pointerup', 0, 0)).not.toThrow();
  });

  it('defaults to the shared default box geometry when seeded with it', () => {
    const { onChange } = render({ box: DEFAULT_CAPTION_BOX });
    stubFrame(container, 200, 200);
    pointer(box(), 'pointerdown', 0, 0);
    pointer(box(), 'pointermove', 0, 20); // +0.1 y
    expect(onChange).toHaveBeenLastCalledWith(moveBox(DEFAULT_CAPTION_BOX, 0, 0.1));
  });
});
