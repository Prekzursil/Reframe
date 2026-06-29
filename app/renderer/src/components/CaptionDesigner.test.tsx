// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { CaptionDesigner } from './CaptionDesigner';
import { DEFAULT_CAPTION_DESIGN, type CaptionDesign } from '../lib/captionDesign';
import { bandBox, moveBox } from '../lib/captionPosition';
import type { Cue } from '../lib/rpc';

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

const WIN = { start: 10, end: 20 };
const CUES: Cue[] = [
  { index: 0, start: 11, end: 12, text: 'Hello' },
  { index: 1, start: 12, end: 13, text: 'world' },
];

/** Drive the Player's onTimeUpdate by setting the <video> time + firing timeupdate. */
function tick(container: HTMLElement, t: number): void {
  const video = container.querySelector('video') as HTMLVideoElement;
  Object.defineProperty(video, 'currentTime', { value: t, configurable: true });
  act(() => video.dispatchEvent(new Event('timeupdate')));
}

describe('<CaptionDesigner />', () => {
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

  function render(props: Partial<React.ComponentProps<typeof CaptionDesigner>> = {}): {
    onChange: ReturnType<typeof vi.fn>;
    design: CaptionDesign;
  } {
    const onChange = props.onChange ?? vi.fn();
    const design = props.design ?? DEFAULT_CAPTION_DESIGN;
    act(() =>
      root.render(
        <CaptionDesigner
          videoId="v1"
          window={WIN}
          cues={CUES}
          {...props}
          design={design}
          onChange={onChange}
        />,
      ),
    );
    return { onChange: onChange as ReturnType<typeof vi.fn>, design };
  }

  it('mounts the player, position box, band buttons, and style picker', () => {
    render();
    expect(container.querySelector('video')).toBeTruthy();
    expect(container.querySelector('[data-testid="caption-box"]')).toBeTruthy();
    expect(container.querySelectorAll('.caption-designer__band')).toHaveLength(3);
    expect(container.querySelector('.caption-style-picker')).toBeTruthy();
  });

  it('shows a placeholder before any caption word is active', () => {
    render();
    expect(container.querySelector('.caption-designer__hint')?.textContent).toBe('Caption preview');
  });

  it('renders the live word-highlighted line at the current time', () => {
    render({ design: { style: 'karaoke', box: DEFAULT_CAPTION_DESIGN.box } });
    tick(container, 11.5); // inside cue 0 "Hello"
    const line = container.querySelector('.caption-designer__line');
    expect(line?.textContent).toContain('Hello');
    // The active word carries the template's active background.
    const spans = line?.querySelectorAll('span');
    expect(spans && spans.length).toBeGreaterThan(0);
  });

  it('paints the opusclip-karaoke preset look with an alternating accent (V1.1 WU SP1)', () => {
    render({ design: { style: 'opusclip-karaoke', box: DEFAULT_CAPTION_DESIGN.box } });
    tick(container, 11.5); // inside cue 0 "Hello" — line index 0 -> yellow accent
    const line = container.querySelector('.caption-designer__line') as HTMLElement;
    // The karaoke preset is all-caps (Anton) — uppercase look renders live.
    expect(line.style.textTransform).toBe('uppercase');
    expect(line.style.fontFamily).toContain('Anton');
    const active = [...line.querySelectorAll('span')].find((s) => s.textContent === 'Hello');
    expect(active?.style.color.replace(/\s/g, '')).toContain('255,255,0');
  });

  it('uppercases the live line for an uppercase template', () => {
    render({ design: { style: 'bold', box: DEFAULT_CAPTION_DESIGN.box } });
    tick(container, 11.5);
    const line = container.querySelector('.caption-designer__line') as HTMLElement;
    expect(line.style.textTransform).toBe('uppercase');
  });

  it('renders the hook title slot when provided', () => {
    render({ hookTitle: '  Big hook  ' });
    expect(container.querySelector('.caption-designer__hook')?.textContent).toBe('Big hook');
  });

  it('shows "No captions" for the none style', () => {
    render({ design: { style: 'none', box: DEFAULT_CAPTION_DESIGN.box } });
    tick(container, 11.5);
    expect(container.querySelector('.caption-designer__hint')?.textContent).toBe('No captions');
  });

  it('changes the style via the picker', () => {
    const { onChange, design } = render();
    act(() => (container.querySelector('[data-style="neon"]') as HTMLButtonElement).click());
    expect(onChange).toHaveBeenCalledWith({ ...design, style: 'neon' });
  });

  it('re-seats the box to a band via the quick buttons', () => {
    const { onChange, design } = render();
    const topBtn = [...container.querySelectorAll('.caption-designer__band')].find(
      (b) => b.textContent === 'Top',
    ) as HTMLButtonElement;
    act(() => topBtn.click());
    expect(onChange).toHaveBeenCalledWith({ ...design, box: bandBox('top') });
  });

  it('moves the caption box by dragging it', () => {
    const { onChange, design } = render();
    const frame = container.querySelector('.caption-box-frame') as HTMLElement;
    frame.getBoundingClientRect = () =>
      ({
        width: 100,
        height: 100,
        top: 0,
        left: 0,
        right: 100,
        bottom: 100,
        x: 0,
        y: 0,
      }) as DOMRect;
    const boxEl = container.querySelector('[data-testid="caption-box"]') as HTMLElement;
    const fire = (type: string, x: number, y: number): void => {
      const ev = new MouseEvent(type, { bubbles: true, clientX: x, clientY: y });
      Object.defineProperty(ev, 'pointerId', { value: 1 });
      act(() => boxEl.dispatchEvent(ev));
    };
    fire('pointerdown', 0, 0);
    fire('pointermove', 10, 0); // +0.1 x
    expect(onChange).toHaveBeenLastCalledWith({ ...design, box: moveBox(design.box, 0.1, 0) });
  });

  it('marks the active band button from the box position', () => {
    render({ design: { style: 'libass', box: bandBox('center') } });
    const centerBtn = [...container.querySelectorAll('.caption-designer__band')].find(
      (b) => b.textContent === 'Center',
    ) as HTMLButtonElement;
    expect(centerBtn.getAttribute('aria-pressed')).toBe('true');
  });

  it('renders the T2 "Customize…" disclosure under the style row', () => {
    render();
    expect(container.querySelector('.caption-customizer__toggle')?.textContent).toBe('Customize…');
  });

  it('threads a customizer edit back into the design override', () => {
    const { onChange, design } = render();
    act(() =>
      (container.querySelector('.caption-customizer__toggle') as HTMLButtonElement).click(),
    );
    const upper = container.querySelector(
      '.caption-customizer__bool-uppercase input',
    ) as HTMLInputElement;
    Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'checked')?.set?.call(
      upper,
      true,
    );
    act(() => upper.dispatchEvent(new Event('click', { bubbles: true })));
    expect(onChange).toHaveBeenLastCalledWith({ ...design, override: { uppercase: true } });
  });

  it('threads the content context into the customizer per-language reading-speed default (WU S4)', () => {
    render({ content: { language: 'en' } });
    act(() =>
      (container.querySelector('.caption-customizer__toggle') as HTMLButtonElement).click(),
    );
    const cps = container.querySelector('.caption-customizer__cps input') as HTMLInputElement;
    expect(cps.value).toBe('20');
    const readout = container.querySelector('.caption-customizer__resolved') as HTMLElement;
    expect(readout.textContent?.replace(/\s+/g, ' ')).toContain('≤20 cps');
  });

  it('reflects the override (font + size scale) in the live preview line', () => {
    render({
      design: {
        style: 'karaoke',
        box: DEFAULT_CAPTION_DESIGN.box,
        override: { fontFamily: 'Anton', sizeScale: 1.4 },
      },
    });
    tick(container, 11.5);
    const line = container.querySelector('.caption-designer__line') as HTMLElement;
    expect(line.style.fontFamily).toContain('Anton');
    expect(line.style.fontSize).toBe('1.4em');
  });
});
