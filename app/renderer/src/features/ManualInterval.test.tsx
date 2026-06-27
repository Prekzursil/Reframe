// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { ManualInterval } from './ManualInterval';

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

describe('<ManualInterval />', () => {
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

  function render(props: Partial<React.ComponentProps<typeof ManualInterval>> = {}): {
    onSubmit: ReturnType<typeof vi.fn>;
  } {
    const onSubmit = props.onSubmit ?? vi.fn();
    act(() => root.render(<ManualInterval {...props} onSubmit={onSubmit} />));
    return { onSubmit: onSubmit as ReturnType<typeof vi.fn> };
  }

  function input(label: string): HTMLInputElement {
    return container.querySelector(`input[aria-label="${label}"]`) as HTMLInputElement;
  }
  function type(el: HTMLInputElement, value: string): void {
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
    act(() => {
      setter.call(el, value);
      el.dispatchEvent(new Event('input', { bubbles: true }));
    });
  }
  function button(text: string): HTMLButtonElement | undefined {
    return [...container.querySelectorAll('button')].find((b) => b.textContent === text);
  }

  function addRange(start: string, end: string): void {
    type(input('Range start'), start);
    type(input('Range end'), end);
    act(() => button('Add range')?.click());
  }

  it('adds a valid range and lists it formatted', () => {
    render();
    addRange('1:23', '4:10');
    const items = container.querySelectorAll('.manual-interval__range');
    expect(items.length).toBe(1);
    expect(items[0].textContent).toContain('1:23');
    expect(items[0].textContent).toContain('4:10');
  });

  it('rejects an unparseable timecode with a clear error', () => {
    render();
    addRange('oops', '4:10');
    expect(container.querySelector('.manual-interval__error')?.textContent).toMatch(/valid/i);
    expect(container.querySelectorAll('.manual-interval__range').length).toBe(0);
  });

  it('rejects a range whose end is not after its start', () => {
    render();
    addRange('4:10', '1:23');
    expect(container.querySelector('.manual-interval__error')?.textContent).toMatch(/after/i);
    expect(container.querySelectorAll('.manual-interval__range').length).toBe(0);
  });

  it('removes a range', () => {
    render();
    addRange('0:10', '0:40');
    expect(container.querySelectorAll('.manual-interval__range').length).toBe(1);
    act(() =>
      (container.querySelector('[aria-label="Remove range"]') as HTMLButtonElement).click(),
    );
    expect(container.querySelectorAll('.manual-interval__range').length).toBe(0);
  });

  it('submits the built candidates and is disabled until a range exists', () => {
    const { onSubmit } = render();
    // No ranges yet -> the make button is disabled.
    expect(button('Make shorts from ranges')?.disabled).toBe(true);
    addRange('0:10', '0:40');
    addRange('1:23', '4:10');
    act(() => button('Make shorts from ranges')?.click());
    expect(onSubmit).toHaveBeenCalledTimes(1);
    const cands = onSubmit.mock.calls[0][0];
    expect(cands.map((c: { rank: number }) => c.rank)).toEqual([1, 2]);
    expect(cands[1].sourceStart).toBe(83);
    expect(cands[1].end).toBe(250);
  });

  it('disables the make button while busy', () => {
    render({ busy: true });
    // Even with a range, busy disables submission.
    addRange('0:10', '0:40');
    expect(button('Make shorts from ranges')?.disabled).toBe(true);
  });

  it('disables inputs + add when the disabled prop is set (no video)', () => {
    render({ disabled: true });
    expect(input('Range start').disabled).toBe(true);
    expect(button('Add range')?.disabled).toBe(true);
  });
});
