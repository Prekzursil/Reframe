// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { CaptionGallery } from './CaptionGallery';

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;
const onChange = vi.fn();

beforeEach(() => {
  onChange.mockReset();
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

const q = <T extends Element>(sel: string): T | null => container.querySelector<T>(sel);
function render(value: string): void {
  act(() => {
    root.render(<CaptionGallery value={value} onChange={onChange} />);
  });
}
function expand(): void {
  act(() => {
    q<HTMLButtonElement>('.caption-gallery__toggle')?.click();
  });
}

describe('CaptionGallery', () => {
  it('shows the active look name in the collapsed bar (no grid)', () => {
    render('hormozi');
    expect(q('.caption-gallery__current')?.textContent).toBe('Keyword highlight');
    expect(q('.caption-gallery__toggle')?.textContent).toBe('Browse styles');
    expect(q('.caption-gallery__grid')).toBeNull();
  });

  it('expands into a grouped grid of look-named swatches', () => {
    render('hormozi');
    expand();
    expect(q('.caption-gallery__grid')).not.toBeNull();
    expect(q('.caption-gallery__toggle')?.textContent).toBe('Done');
    // grouped by family — the headline word-by-word section comes first
    const titles = [...container.querySelectorAll('.caption-gallery__group-title')].map(
      (t) => t.textContent,
    );
    expect(titles[0]).toBe('Word by word');
    // look names, never brand/engine jargon
    const names = [...container.querySelectorAll('.caption-gallery__name')].map(
      (n) => n.textContent,
    );
    expect(names).toContain('Word-by-word pop');
    expect(names).toContain('Editorial serif');
    expect(names.join(' ')).not.toMatch(/hormozi|libass|opusclip/i);
  });

  it('marks the selected swatch active and previews the none style as Off', () => {
    render('serif');
    expand();
    const serif = q<HTMLButtonElement>('[data-style="serif"]');
    expect(serif?.classList.contains('is-active')).toBe(true);
    expect(serif?.getAttribute('aria-checked')).toBe('true');
    const none = q<HTMLButtonElement>('[data-style="none"]');
    expect(none?.getAttribute('aria-checked')).toBe('false');
    expect(none?.querySelector('.caption-gallery__off')?.textContent).toBe('Off');
    // a non-none swatch renders a live styled sample, not the Off text
    expect(q('[data-style="serif"] .caption-gallery__sample')?.textContent).toBe('Aa');
  });

  it('emits the chosen style id on selection', () => {
    render('hormozi');
    expand();
    act(() => {
      q<HTMLButtonElement>('[data-style="serif"]')?.click();
    });
    expect(onChange).toHaveBeenCalledWith('serif');
  });

  it('collapses again when Done is pressed', () => {
    render('hormozi');
    expand();
    expand();
    expect(q('.caption-gallery__grid')).toBeNull();
  });
});
