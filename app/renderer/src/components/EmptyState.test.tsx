// EmptyState.test.tsx — pins the ONE empty state, EXTRACTED (not invented).
//
// Reframe already cleared the professional bar on three screens that each
// hand-rolled the SAME anatomy: a ghost 16:9 poster (play glyph + mono
// placeholder timecode) -> title -> hint -> a way forward. The `edit__empty-*`,
// `make-shorts__empty` and `library__empty` blocks are three copies of it, and
// their skins live in components/shell.css / views/makeShorts.css. Cited by
// selector, not by line: those shell.css anchors have already drifted ~108 lines.
// This component is that anatomy, once — so a new surface inherits the bar
// instead of shipping a fourth grey paragraph.
//
// The pin that matters most is `reproduces the Edit skin byte-for-byte`: the
// extraction is only real if the component can render the reference screen with
// NO markup or class change (zero visual regression on the screen that set the
// bar). If that test is ever loosened, the component stopped being an extraction.
//
// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import { EmptyState, EMPTY_STATE_GLYPH, EMPTY_STATE_TIMECODE } from './EmptyState';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
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

const q = (sel: string): HTMLElement | null => container.querySelector<HTMLElement>(sel);

describe('<EmptyState /> — the shared empty-state anatomy', () => {
  it('renders poster + title + hint + action under the default block', async () => {
    await mount(
      <EmptyState
        poster
        title="No video open"
        hint="Open a video from the Library."
        action={{ label: '← Library', onClick: vi.fn() }}
      />,
    );

    expect(q('.empty-state')).not.toBeNull();
    expect(q('.empty-state-poster')).not.toBeNull();
    expect(q('.empty-state-title')?.textContent).toBe('No video open');
    expect(q('.empty-state-hint')?.textContent).toBe('Open a video from the Library.');
    expect(q('.empty-state-action')?.textContent).toBe('← Library');
  });

  it('ships the ghost poster as DECORATION with the shared glyph + timecode', async () => {
    await mount(<EmptyState poster title="No video open" />);

    // The poster is an illustration, not content: it must not reach the a11y tree.
    expect(q('.empty-state-poster')?.getAttribute('aria-hidden')).toBe('true');
    expect(q('.empty-state-glyph')?.textContent).toBe(EMPTY_STATE_GLYPH);
    expect(q('.empty-state-timecode')?.textContent).toBe(EMPTY_STATE_TIMECODE);
  });

  it('lets a surface override the poster glyph + timecode', async () => {
    await mount(<EmptyState poster={{ glyph: '✂', timecode: '00:00' }} title="No cuts yet" />);

    expect(q('.empty-state-glyph')?.textContent).toBe('✂');
    expect(q('.empty-state-timecode')?.textContent).toBe('00:00');
  });

  it('omits the poster when it is not asked for, and when it is switched off', async () => {
    await mount(<EmptyState title="No matches" />);
    expect(q('.empty-state-poster')).toBeNull();

    await mount(<EmptyState poster={false} title="No matches" />);
    expect(q('.empty-state-poster')).toBeNull();
  });

  it('omits the hint and the action when the surface has none', async () => {
    await mount(<EmptyState title="No matches" />);

    expect(q('.empty-state-hint')).toBeNull();
    expect(q('.empty-state-action')).toBeNull();
    expect(q('.empty-state-title')?.textContent).toBe('No matches');
  });

  it('wires the action as a real button that fires its handler', async () => {
    const onClick = vi.fn();
    await mount(<EmptyState title="No video open" action={{ label: '← Library', onClick }} />);

    const button = container.querySelector<HTMLButtonElement>('.empty-state-action');
    // type=button so an empty state inside a <form> can never submit it.
    expect(button?.type).toBe('button');
    await act(async () => {
      button?.click();
    });
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it('labels the region for assistive tech when the surface names it', async () => {
    await mount(<EmptyState title="No video open" label="Edit" />);

    expect(q('.empty-state')?.getAttribute('aria-label')).toBe('Edit');
  });

  it('reproduces the Edit skin byte-for-byte (the extraction pin)', async () => {
    // The Edit empty state as it shipped: root `edit edit--empty`, aria-label
    // Edit, `edit__empty-*` slots (styled in components/shell.css) and the
    // `edit__empty-back` CTA. Rendering it through the shared component must not
    // change one class, or the reference screen regresses visually.
    await mount(
      <EmptyState
        className="edit edit--empty"
        label="Edit"
        block="edit__empty"
        poster
        title="No video open"
        hint="Open a video from the Library."
        action={{ label: '← Library', onClick: vi.fn(), className: 'edit__empty-back' }}
      />,
    );

    const rootEl = q('.edit.edit--empty');
    expect(rootEl).not.toBeNull();
    expect(rootEl?.getAttribute('aria-label')).toBe('Edit');
    expect(q('.edit__empty-poster')).not.toBeNull();
    expect(q('.edit__empty-glyph')?.textContent).toBe('▶');
    expect(q('.edit__empty-timecode')?.textContent).toBe('--:--');
    expect(q('.edit__empty-title')?.textContent).toBe('No video open');
    expect(q('.edit__empty-hint')).not.toBeNull();
    expect(q('.edit__empty-back')).not.toBeNull();
    // The default block must NOT leak in alongside the skin.
    expect(q('.empty-state-title')).toBeNull();
  });
});
