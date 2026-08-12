// Edit.empty.test.tsx — Edit's no-video state is the SHARED anatomy, not a copy.
//
// Edit.test.tsx already pins what the user sees (poster / title / hint / back
// button). This file pins the thing that keeps every OTHER surface at that bar:
// Edit renders through <EmptyState /> instead of hand-rolling the markup, so the
// anatomy has exactly one definition. The spy calls through to the real
// component, so the DOM assertions below still hold against the real render —
// this is not a mock standing in for the thing under test.
//
// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

// The heavy per-video bodies own their own tests and never mount here (video is
// null in every case below); stub them so this file stays a leaf.
vi.mock('./Workspace', () => ({ Workspace: () => <div data-testid="workspace" /> }));
vi.mock('./TaskHub', () => ({ TaskHub: () => <div data-testid="taskhub" /> }));
vi.mock('../lib/rpc', () => ({ rpc: vi.fn(), hasApi: () => false }));

vi.mock('../components/EmptyState', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../components/EmptyState')>();
  return { ...actual, EmptyState: vi.fn(actual.EmptyState) };
});

import { Edit } from './Edit';
import { EmptyState } from '../components/EmptyState';

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  vi.mocked(EmptyState).mockClear();
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => {
    root.unmount();
  });
  container.remove();
});

async function mount(node: React.ReactElement): Promise<void> {
  await act(async () => {
    root.render(node);
  });
}

describe('Edit — the no-video state rides the shared <EmptyState />', () => {
  it('delegates to the shared component with the Edit skin', async () => {
    await mount(<Edit video={null} onBack={vi.fn()} />);

    expect(vi.mocked(EmptyState)).toHaveBeenCalledTimes(1);
    const props = vi.mocked(EmptyState).mock.calls[0][0];
    expect(props.className).toBe('edit edit--empty');
    expect(props.block).toBe('edit__empty');
    expect(props.label).toBe('Edit');
    expect(props.title).toBe('No video open');
    expect(props.poster).toBe(true);
    expect(props.action?.className).toBe('edit__empty-back');
  });

  it('names the SHIPPED region with a role that permits the name', async () => {
    // origin/main rendered `<div className="edit edit--empty" aria-label="Edit">`
    // — a name on a role-less div, which ARIA 1.2 lists as "Name from:
    // prohibited" for `generic` and this repo's own axe-core 4.12.1 reports as a
    // needs-review, not a violation (see resolveA11y in EmptyState.tsx). The
    // component-level pin (EmptyState.test.tsx) is what went red for this; this
    // one is the end-to-end regression pin, asserted on the DOM Edit actually
    // ships rather than on a prop object.
    await mount(<Edit video={null} onBack={vi.fn()} />);

    const region = container.querySelector('.edit.edit--empty');
    expect(region?.getAttribute('role')).toBe('region');
    expect(region?.getAttribute('aria-label')).toBe('Edit');
  });

  it('still renders the exact same skin the reference screen shipped', async () => {
    await mount(<Edit video={null} onBack={vi.fn()} />);

    // Every class the shell.css `.edit--empty` family styles must survive the
    // extraction (cited by selector — those line anchors have already drifted).
    for (const sel of [
      '.edit.edit--empty',
      '.edit__empty-poster',
      '.edit__empty-glyph',
      '.edit__empty-timecode',
      '.edit__empty-title',
      '.edit__empty-hint',
      '.edit__empty-back',
    ]) {
      expect(container.querySelector(sel), sel).not.toBeNull();
    }
  });

  it('keeps the way forward wired to the Library', async () => {
    const onBack = vi.fn();
    await mount(<Edit video={null} onBack={onBack} />);

    await act(async () => {
      container.querySelector<HTMLButtonElement>('.edit__empty-back')?.click();
    });
    expect(onBack).toHaveBeenCalledTimes(1);
  });
});
