// SocialPublishPanel.test.tsx — Deliver -> "Publish" is ONE honest blocked state (Q4).
//
// Most of what is asserted here is ABSENCE, because the defect being fixed was a
// surface that LOOKED operable and was not: a platform picker, a title field, a
// scheduler and a "Publish now / Schedule" button whose enable condition required a
// non-empty clip path that the only production mount never passed and no other
// surface in the tree supplies. Directly above that permanently-disabled button the
// panel asserted that a platform-held schedule survives the machine being switched
// off — a capability claim painted over a control that cannot fire.
//
// So the guard has to be written against the shapes that made it look alive:
// controls, a queue, and a backend round-trip. Each is anchored on a DIFFERENT
// locator (element vocabulary, class, RPC spy) so a partial re-introduction cannot
// slip past one of them.

// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// 52 sibling renderer tests set this; the pre-Q4 version of THIS file did not, so
// every `act()` here printed "the current testing environment is not configured to
// support act(...)" to stderr. Warning noise in a suite is how a real warning stops
// being read.
(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

const capabilitiesMock = vi.fn();
const planMock = vi.fn();
const enqueueMock = vi.fn();
const queueMock = vi.fn();
const cancelMock = vi.fn();

// Mocked even though the panel no longer imports it. A spy that is never called is
// the only way to assert the panel does NOT consult a backend that cannot publish,
// and it keeps this file honest if someone re-wires one of the five social.* calls:
// the RPC methods, the planner and the queue store are all still built and
// registered (docs/wiring/WIRING-social-publish.md), so re-wiring is easy and would
// be wrong until an uploader exists.
vi.mock('../lib/rpc', () => ({
  client: {
    social: {
      capabilities: (...a: unknown[]) => capabilitiesMock(...a),
      plan: (...a: unknown[]) => planMock(...a),
      enqueue: (...a: unknown[]) => enqueueMock(...a),
      queue: (...a: unknown[]) => queueMock(...a),
      cancel: (...a: unknown[]) => cancelMock(...a),
    },
  },
}));

import type { SocialCapability, SocialSchedulePlan } from '../lib/rpc';
import { SocialPublishPanel } from './SocialPublishPanel';

/**
 * A publishable platform and a PLATFORM-HELD plan — the exact server state under
 * which the old panel printed its worst sentence, the one claiming the post goes
 * out with the machine switched off, directly above a button that could not enable.
 *
 * Seeded even though nothing consumes it: without it the absence assertions below
 * would pass vacuously (an unmocked panel simply errors out of that branch), and a
 * guard that cannot observe the state it guards against is not a guard. Measured:
 * with these two mocks in place the pre-fix panel renders `.social-publish__held`
 * and the assertion goes red.
 *
 * Facebook Page, not YouTube, because `describe_capabilities()` returns the matrix
 * id-sorted (sidecar/media_studio/features/social_publish.py:250) and the panel
 * defaulted to the first PUBLISHABLE row — so Facebook Page is what a real user saw.
 */
const FACEBOOK_PAGE: SocialCapability = {
  id: 'facebook_page',
  label: 'Facebook Page',
  publishable: true,
  personalAccount: false,
  desktopLoopbackOauth: false,
  nativeScheduling: true,
  nativeScheduleMaxSec: 6_000_000,
  requiresClientSecret: true,
  unauditedVisibility: 'Publishing needs Advanced Access to pages_manage_posts.',
  docUrl: 'https://developers.facebook.com/docs/pages-api',
  blockedReason: null,
};

const PLATFORM_HELD_PLAN: SocialSchedulePlan = {
  platform: 'facebook_page',
  kind: 'platform',
  publishAt: 1_800_003_600,
  requiresAppRunning: false,
  warning: '',
  unauditedVisibility: FACEBOOK_PAGE.unauditedVisibility,
};

let container: HTMLElement | undefined;
let root: Root | undefined;

beforeEach(() => {
  vi.clearAllMocks();
  capabilitiesMock.mockResolvedValue({ platforms: [FACEBOOK_PAGE] });
  planMock.mockResolvedValue({ plan: PLATFORM_HELD_PLAN });
  queueMock.mockResolvedValue({ entries: [] });
});

afterEach(() => {
  if (root !== undefined) {
    const mounted = root;
    act(() => mounted.unmount());
  }
  container?.remove();
  root = undefined;
  container = undefined;
});

function dom(): HTMLElement {
  if (container === undefined) throw new Error('not rendered');
  return container;
}

async function render(): Promise<void> {
  const host = document.createElement('div');
  document.body.appendChild(host);
  container = host;
  const mounted = createRoot(host);
  root = mounted;
  await act(async () => {
    mounted.render(<SocialPublishPanel />);
  });
  // A second flush: if the panel still opened an async effect, its state update
  // would land here, so the assertions below cannot pass merely by being early.
  await act(async () => {
    await Promise.resolve();
  });
}

describe('<SocialPublishPanel /> — the honest blocked state', () => {
  it('says direct publish is unavailable in this build', async () => {
    await render();
    expect(dom().querySelector('.social-publish__blocked')?.textContent).toContain(
      'Direct publish is not available in this build',
    );
  });

  it('names the surface that DOES work instead of leaving the user stuck', async () => {
    // The old empty state said "Export a clip first" — an instruction with no
    // affordance anywhere on this screen to satisfy it.
    await render();
    expect(dom().textContent).toContain('Platform presets');
    expect(dom().textContent).not.toContain('Export a clip first');
  });

  it('carries an accessible name for the destination', async () => {
    await render();
    expect(dom().querySelector('section.social-publish')?.getAttribute('aria-label')).toBe(
      'Direct publish',
    );
  });
});

describe('<SocialPublishPanel /> — nothing that cannot fire', () => {
  it('renders no button, select, input or textarea at all', async () => {
    await render();
    expect(dom().querySelectorAll('button')).toHaveLength(0);
    expect(dom().querySelectorAll('select')).toHaveLength(0);
    expect(dom().querySelectorAll('input')).toHaveLength(0);
    expect(dom().querySelectorAll('textarea')).toHaveLength(0);
  });

  it('offers no queue, because nothing can enqueue', async () => {
    await render();
    expect(dom().querySelector('.social-publish__queue')).toBeNull();
    expect(dom().textContent).not.toContain('Nothing queued yet');
    expect(dom().querySelectorAll('h4')).toHaveLength(0);
  });

  it('makes no social RPC call', async () => {
    await render();
    expect(capabilitiesMock).not.toHaveBeenCalled();
    expect(planMock).not.toHaveBeenCalled();
    expect(enqueueMock).not.toHaveBeenCalled();
    expect(queueMock).not.toHaveBeenCalled();
    expect(cancelMock).not.toHaveBeenCalled();
  });
});

describe('<SocialPublishPanel /> — the claims it must not make', () => {
  it('no longer promises a post goes out with the computer switched off', async () => {
    await render();
    expect(dom().querySelector('.social-publish__held')).toBeNull();
    expect(dom().textContent ?? '').not.toMatch(/computer is off/i);
  });

  it('makes no scheduling promise of any kind', async () => {
    await render();
    const text = dom().textContent ?? '';
    expect(text).not.toMatch(/schedule/i);
    expect(text).not.toMatch(/publish now/i);
  });
});
