// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { CaptionStylePicker, sampleStyle } from './CaptionStylePicker';
import { captionVisualFor } from '../lib/captionTemplates';
import { CAPTION_STYLES } from '../features/shortMakerLogic';

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

describe('sampleStyle', () => {
  it('applies box background + outline stroke for a boxed/outlined template', () => {
    const hormozi = sampleStyle(captionVisualFor('hormozi')); // box: true
    expect(hormozi.backgroundColor).not.toBe('transparent');
    const neon = sampleStyle(captionVisualFor('neon')); // outline: true
    expect(neon.WebkitTextStroke).toContain('0.6px');
    expect(neon.textShadow).toBe('none');
  });

  it('uses transparent background + shadow for a plain template', () => {
    const clean = sampleStyle(captionVisualFor('clean')); // box:false, outline:false
    expect(clean.backgroundColor).toBe('transparent');
    expect(clean.WebkitTextStroke).toBeUndefined();
    expect(clean.textShadow).toContain('0 1px 2px');
    expect(clean.textTransform).toBe('none');
  });

  it('uppercases an uppercase template', () => {
    expect(sampleStyle(captionVisualFor('bold')).textTransform).toBe('uppercase');
  });
});

describe('<CaptionStylePicker />', () => {
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

  function render(props: Partial<React.ComponentProps<typeof CaptionStylePicker>> = {}): {
    onChange: ReturnType<typeof vi.fn>;
  } {
    const onChange = props.onChange ?? vi.fn();
    act(() =>
      root.render(
        <CaptionStylePicker value={props.value ?? 'karaoke'} {...props} onChange={onChange} />,
      ),
    );
    return { onChange: onChange as ReturnType<typeof vi.fn> };
  }

  const swatch = (id: string): HTMLButtonElement =>
    container.querySelector(`[data-style="${id}"]`) as HTMLButtonElement;

  it('renders a swatch for every catalog style', () => {
    render();
    expect(container.querySelectorAll('.caption-style-swatch')).toHaveLength(CAPTION_STYLES.length);
    expect(container.querySelector('.caption-style-picker')?.getAttribute('aria-label')).toBe(
      'Caption style',
    );
  });

  it('marks the selected style as pressed', () => {
    render({ value: 'hormozi' });
    expect(swatch('hormozi').getAttribute('aria-pressed')).toBe('true');
    expect(swatch('hormozi').className).toContain('is-active');
    expect(swatch('karaoke').getAttribute('aria-pressed')).toBe('false');
  });

  it('renders a "No captions" placeholder for the none style and a sample otherwise', () => {
    render();
    expect(swatch('none').querySelector('.caption-style-swatch__none')?.textContent).toBe(
      'No captions',
    );
    expect(swatch('karaoke').querySelector('.caption-style-swatch__sample')?.textContent).toBe(
      'Aa',
    );
  });

  it('emits the chosen style id on click', () => {
    const { onChange } = render();
    act(() => swatch('neon').click());
    expect(onChange).toHaveBeenCalledWith('neon');
  });

  it('accepts a custom style subset + label', () => {
    render({ styles: [{ id: 'bold', engine: 'remotion', label: 'Bold' }], label: 'Pick a look' });
    expect(container.querySelectorAll('.caption-style-swatch')).toHaveLength(1);
    expect(container.querySelector('.caption-style-picker')?.getAttribute('aria-label')).toBe(
      'Pick a look',
    );
  });
});
