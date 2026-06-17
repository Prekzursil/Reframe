// AddKeyRow.test.tsx — paste-to-add a key; clears after add; Add gated on input.
// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import { AddKeyRow } from './AddKeyRow';

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

function input(): HTMLInputElement {
  return container.querySelector('.add-key-row__input') as HTMLInputElement;
}
function addBtn(): HTMLButtonElement {
  return container.querySelector('.add-key-row__add') as HTMLButtonElement;
}
function typeValue(value: string): void {
  const el = input();
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set;
  setter?.call(el, value);
  act(() => el.dispatchEvent(new Event('input', { bubbles: true })));
}

describe('AddKeyRow', () => {
  it('Add is disabled until a non-empty (trimmed) value is entered', () => {
    act(() => root.render(<AddKeyRow providerId="groq" onAdd={vi.fn()} />));
    expect(addBtn().disabled).toBe(true);
    typeValue('   '); // whitespace only -> still disabled
    expect(addBtn().disabled).toBe(true);
    typeValue('gsk-realkey');
    expect(addBtn().disabled).toBe(false);
  });

  it('fires onAdd with the trimmed RAW key and clears the input', () => {
    const onAdd = vi.fn();
    act(() => root.render(<AddKeyRow providerId="groq" onAdd={onAdd} />));
    typeValue('  gsk-pasted-RAW  ');
    act(() => addBtn().dispatchEvent(new MouseEvent('click', { bubbles: true })));
    expect(onAdd).toHaveBeenCalledWith('groq', 'gsk-pasted-RAW');
    // Field cleared so the full key does not linger.
    expect(input().value).toBe('');
  });

  it('Enter submits the trimmed key', () => {
    const onAdd = vi.fn();
    act(() => root.render(<AddKeyRow providerId="groq" onAdd={onAdd} />));
    typeValue('gsk-enter-key');
    act(() => input().dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })));
    expect(onAdd).toHaveBeenCalledWith('groq', 'gsk-enter-key');
  });

  it('Enter on an empty field hits the canAdd guard (no-op)', () => {
    const onAdd = vi.fn();
    act(() => root.render(<AddKeyRow providerId="groq" onAdd={onAdd} />));
    act(() => input().dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })));
    expect(onAdd).not.toHaveBeenCalled();
  });

  it('a non-Enter keydown does not submit', () => {
    const onAdd = vi.fn();
    act(() => root.render(<AddKeyRow providerId="groq" onAdd={onAdd} />));
    typeValue('gsk-key');
    act(() => input().dispatchEvent(new KeyboardEvent('keydown', { key: 'a', bubbles: true })));
    expect(onAdd).not.toHaveBeenCalled();
  });
});
