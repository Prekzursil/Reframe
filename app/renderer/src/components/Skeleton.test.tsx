// Skeleton.test.tsx — pins the ONE loading skeleton.
//
// Library.tsx already ships a shaped skeleton and its own comment says the app
// must never render "a bare LOADING..."; Settings.tsx rendered exactly that.
// This component is the shared shape so no surface has to hand-roll one again.
//
// The load-bearing pin is `rides the ONE .skeleton rule`: the shimmer + its
// reduced-motion handling already exist in components/shell.css. A second copy
// of that rule is the drift this lane exists to prevent, so the test reads the
// stylesheet and fails if emptyState.css redefines it. (Cited by selector, not
// by line — the `shell.css:634` anchor this file shipped with was already stale:
// the rule sits at :742 on today's main, +108 lines from the branch base.)
//
// @vitest-environment jsdom
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import { Skeleton } from './Skeleton';

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

const all = (sel: string): HTMLElement[] =>
  Array.from(container.querySelectorAll<HTMLElement>(sel));

describe('<Skeleton /> — the shared loading shape', () => {
  it('defaults to a single line that carries the shared .skeleton base', async () => {
    await mount(<Skeleton />);

    const group = container.querySelector('.skeleton-group');
    expect(group?.className).toContain('skeleton-group--line');
    const shapes = all('.skeleton');
    expect(shapes).toHaveLength(1);
    expect(shapes[0].className).toBe('skeleton skeleton--line');
  });

  it('renders the title variant', async () => {
    await mount(<Skeleton variant="title" />);

    expect(all('.skeleton')[0].className).toBe('skeleton skeleton--title');
  });

  it('renders the panel variant as a title + three body lines', async () => {
    await mount(<Skeleton variant="panel" />);

    expect(container.querySelector('.skeleton-group--panel')).not.toBeNull();
    expect(all('.skeleton--title')).toHaveLength(1);
    expect(all('.skeleton--line')).toHaveLength(3);
    // Every shape rides the shared base rule — none is a bespoke shimmer.
    expect(all('.skeleton')).toHaveLength(4);
  });

  it('is decoration by default: hidden from assistive tech, no role', async () => {
    await mount(<Skeleton variant="panel" />);

    const group = container.querySelector('.skeleton-group');
    expect(group?.getAttribute('aria-hidden')).toBe('true');
    expect(group?.getAttribute('role')).toBeNull();
  });

  it('becomes a BUSY status region carrying the wait as real text when labelled', async () => {
    await mount(<Skeleton variant="panel" label="Loading Models & System" />);

    const group = container.querySelector('.skeleton-group');
    expect(group?.getAttribute('role')).toBe('status');
    // `aria-busy` is what every other loading surface in this app carries
    // (Library's own skeleton, ManagedStoreMeter, SetupStatusPanel, ReadinessRollup).
    // Without it this component would be the only one that omits it.
    expect(group?.getAttribute('aria-busy')).toBe('true');
    // The wait is a TEXT NODE inside the region, not an `aria-label`: a live region
    // announces its CONTENT, and an accessible NAME is not content. Text is also
    // what a browse-mode reader meets linearly — which the bare "Loading…" did give.
    expect(group?.textContent).toContain('Loading Models & System');
    expect(group?.getAttribute('aria-label')).toBeNull();
    expect(group?.getAttribute('aria-hidden')).toBeNull();
  });

  it('keeps the four ghost bars as children 1-4 so the shape rules still match', async () => {
    await mount(<Skeleton variant="panel" label="Loading Models & System" />);

    const kids = Array.from(container.querySelector('.skeleton-group')?.children ?? []);
    // emptyState.css tapers and staggers the bars with :nth-child(2..4). The label
    // therefore MUST come last: putting it first shifts every index by one and
    // silently re-points the taper at the wrong bar. This pins the ordering.
    expect(kids).toHaveLength(5);
    expect(kids.slice(0, 4).every((el) => el.classList.contains('skeleton'))).toBe(true);
    expect(kids[4].className).toBe('skeleton-group__label');
  });

  it('appends the caller class so it can inherit a surface (e.g. .panel)', async () => {
    await mount(<Skeleton variant="panel" className="panel panel--loading" />);

    const group = container.querySelector('.skeleton-group');
    expect(group?.className).toBe('skeleton-group skeleton-group--panel panel panel--loading');
  });
});

describe('emptyState.css — rides the ONE .skeleton rule, never a second one', () => {
  // `import.meta.url` is not a file:// URL under the jsdom environment, so resolve
  // from the vitest root (app/) instead — the same dir CI runs the suite from.
  const css = readFileSync(
    resolve(process.cwd(), 'renderer', 'src', 'components', 'emptyState.css'),
    'utf8',
  );

  it('does not redefine the .skeleton base (it lives in shell.css)', () => {
    // A bare `.skeleton {` declaration block here would be a SECOND shimmer
    // definition racing the one in shell.css. Variant selectors (.skeleton--x,
    // .skeleton-group) are the extension point and are allowed.
    const bareBase = /^\s*\.skeleton\s*(,|\{)/m;
    expect(bareBase.test(css)).toBe(false);
    expect(css).toContain('.skeleton--line');
  });

  it('does not redefine the skeleton-pulse keyframes', () => {
    expect(css).not.toContain('@keyframes skeleton-pulse');
  });

  it('hides the status label visually — a shimmer must not sprout a caption', () => {
    // The label is real text so assistive tech has something to read; it must be
    // clipped, not merely `display: none` (which would drop it from the a11y tree
    // and put us back where we started) and not visible (which would be a caption
    // nobody designed). This repo has no shared sr-only utility to lean on.
    const rule = /\.skeleton-group__label\s*\{[^}]*\}/.exec(css)?.[0] ?? '';
    expect(rule).toContain('position: absolute');
    expect(rule).toContain('clip-path');
    expect(rule).not.toContain('display: none');
  });
});
