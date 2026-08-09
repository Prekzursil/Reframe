// SocialPublishPanel.test.tsx — C14 Publish panel.
//
// The assertions that matter here are the honesty ones, because the panel's whole
// reason to exist is to not promise a publish that cannot happen:
//
//   * a BLOCKED platform is un-selectable and shows its own reason verbatim;
//   * a `local-queue` plan shows the server's warning that Reframe must be running;
//   * a `platform` plan says the opposite (it posts with the computer off);
//   * the pre-audit visibility cap is shown BEFORE the first publish.

// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { SocialCapability, SocialQueueEntry, SocialSchedulePlan } from '../lib/rpc';

const capabilitiesMock = vi.fn();
const planMock = vi.fn();
const enqueueMock = vi.fn();
const queueMock = vi.fn();
const cancelMock = vi.fn();

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

import {
  SocialPublishPanel,
  platformLabel,
  statusLabel,
  toEpochSeconds,
} from './SocialPublishPanel';

const YOUTUBE: SocialCapability = {
  id: 'youtube',
  label: 'YouTube',
  publishable: true,
  personalAccount: true,
  desktopLoopbackOauth: true,
  nativeScheduling: true,
  nativeScheduleMaxSec: null,
  requiresClientSecret: true,
  unauditedVisibility: 'Until your project passes the audit, uploads are forced PRIVATE.',
  docUrl: 'https://developers.google.com/youtube/v3/docs/videos/insert',
  blockedReason: null,
};

const INSTAGRAM: SocialCapability = {
  ...YOUTUBE,
  id: 'instagram_reels',
  label: 'Instagram Reels',
  publishable: false,
  personalAccount: false,
  nativeScheduling: false,
  blockedReason: "Instagram's API only serves a PROFESSIONAL account.",
};

const IMMEDIATE_PLAN: SocialSchedulePlan = {
  platform: 'youtube',
  kind: 'immediate',
  publishAt: null,
  requiresAppRunning: false,
  warning: '',
  unauditedVisibility: YOUTUBE.unauditedVisibility,
};

const ENTRY: SocialQueueEntry = {
  id: 'e1',
  platform: 'youtube',
  videoId: 'v1',
  clipPath: 'clip.mp4',
  title: 'My clip',
  description: '',
  publishAt: null,
  kind: 'immediate',
  requiresAppRunning: false,
  status: 'pending',
  createdAt: 1_800_000_000,
  error: '',
};

let container: HTMLElement | undefined;
let root: Root | undefined;

beforeEach(() => {
  vi.clearAllMocks();
  capabilitiesMock.mockResolvedValue({ platforms: [YOUTUBE, INSTAGRAM] });
  planMock.mockResolvedValue({ plan: IMMEDIATE_PLAN });
  queueMock.mockResolvedValue({ entries: [] });
  enqueueMock.mockResolvedValue({ entry: ENTRY });
  cancelMock.mockResolvedValue({ ok: true });
});

afterEach(() => {
  // Guarded: the pure-helper tests never mount, so an unconditional unmount here
  // failed them all with a confusing "cannot read properties of undefined".
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

async function render(props: { clipPath?: string; videoId?: string } = {}): Promise<void> {
  const host = document.createElement('div');
  document.body.appendChild(host);
  container = host;
  const mounted = createRoot(host);
  root = mounted;
  await act(async () => {
    mounted.render(<SocialPublishPanel clipPath="clip.mp4" videoId="v1" {...props} />);
  });
  await act(async () => {
    await Promise.resolve();
  });
}

function select(): HTMLSelectElement {
  return dom().querySelector('select[aria-label="Platform"]') as HTMLSelectElement;
}

function input(label: string): HTMLInputElement {
  return dom().querySelector(`input[aria-label="${label}"]`) as HTMLInputElement;
}

/**
 * Set a CONTROLLED React field's value the way React notices.
 *
 * A plain `el.value = x` + `change` does NOT reach a controlled input: React caches
 * the node's value via the prototype setter and treats an unchanged cached value as
 * "no change", so onChange never fires. Going through the prototype descriptor keeps
 * React's tracker in sync, and inputs need an `input` event (selects use `change`).
 */
function setValue(el: HTMLInputElement | HTMLSelectElement, value: string): void {
  const isSelect = el instanceof HTMLSelectElement;
  const proto = isSelect ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
  setter?.call(el, value);
  el.dispatchEvent(new Event(isSelect ? 'change' : 'input', { bubbles: true }));
}

function buttonByText(text: string): HTMLButtonElement | undefined {
  return Array.from(dom().querySelectorAll('button')).find((b) => b.textContent?.trim() === text) as
    | HTMLButtonElement
    | undefined;
}

/** The action/load error slot (distinct from the schedule-preview one). */
function errorText(): string | undefined {
  return dom().querySelector('.social-publish__error')?.textContent ?? undefined;
}

/** The schedule-PREVIEW error slot. */
function planErrorText(): string | undefined {
  return dom().querySelector('.social-publish__plan-error')?.textContent ?? undefined;
}

describe('<SocialPublishPanel /> — pure helpers', () => {
  it('toEpochSeconds returns null for an empty value', () => {
    expect(toEpochSeconds('')).toBeNull();
  });

  it('toEpochSeconds returns null for an unparseable value', () => {
    expect(toEpochSeconds('not-a-date')).toBeNull();
  });

  it('toEpochSeconds converts a datetime-local value to whole seconds', () => {
    expect(toEpochSeconds('2026-08-09T10:30')).toBe(
      Math.floor(new Date('2026-08-09T10:30').getTime() / 1000),
    );
  });

  it('statusLabel distinguishes a platform-held schedule from a Reframe-held one', () => {
    // "pending" alone would wrongly imply the app must stay open for a
    // platform-scheduled post.
    expect(statusLabel({ ...ENTRY, kind: 'platform' })).toBe('scheduled on the platform');
    expect(statusLabel({ ...ENTRY, kind: 'local-queue', requiresAppRunning: true })).toBe(
      'queued in Reframe',
    );
  });

  it('statusLabel passes a terminal status through', () => {
    expect(statusLabel({ ...ENTRY, status: 'done' })).toBe('done');
    expect(statusLabel({ ...ENTRY, status: 'cancelled' })).toBe('cancelled');
  });

  it('platformLabel resolves a known id to its label', () => {
    expect(platformLabel([YOUTUBE, INSTAGRAM], 'instagram_reels')).toBe('Instagram Reels');
  });

  it('platformLabel falls back to the raw id for an unknown platform', () => {
    // The fallback arm, exercised directly. Inline in the JSX this arm was
    // unreachable, so the test that claimed to cover it was passing vacuously.
    expect(platformLabel([YOUTUBE], 'mastodon')).toBe('mastodon');
  });

  it('platformLabel handles an empty matrix', () => {
    expect(platformLabel([], 'youtube')).toBe('youtube');
  });
});

describe('<SocialPublishPanel /> — blocked platforms', () => {
  it('lists a blocked platform as disabled and marked unavailable', async () => {
    await render();
    const blocked = Array.from(select().options).find((o) => o.value === 'instagram_reels');
    expect(blocked?.disabled).toBe(true);
    expect(blocked?.textContent).toContain('unavailable');
  });

  it('defaults to the first PUBLISHABLE platform, never a blocked one', async () => {
    capabilitiesMock.mockResolvedValue({ platforms: [INSTAGRAM, YOUTUBE] });
    await render();
    expect(select().value).toBe('youtube');
  });

  it('shows the platform own reason verbatim when a blocked one is selected', async () => {
    await render();
    await act(async () => setValue(select(), 'instagram_reels'));
    expect(dom().textContent).toContain('PROFESSIONAL account');
  });

  it('does not ask the server for a plan for a blocked platform', async () => {
    await render();
    planMock.mockClear();
    await act(async () => setValue(select(), 'instagram_reels'));
    expect(planMock).not.toHaveBeenCalled();
  });

  it('selects nothing when NO platform is publishable', async () => {
    capabilitiesMock.mockResolvedValue({ platforms: [INSTAGRAM] });
    await render();
    expect(select().value).toBe('');
  });
});

describe('<SocialPublishPanel /> — the scheduling disclosure', () => {
  it('shows the server warning verbatim for a local-queue plan', async () => {
    planMock.mockResolvedValue({
      plan: {
        ...IMMEDIATE_PLAN,
        kind: 'local-queue',
        requiresAppRunning: true,
        warning: 'Reframe must be running then.',
      },
    });
    await render();
    expect(dom().querySelector('.social-publish__warning')?.textContent).toBe(
      'Reframe must be running then.',
    );
  });

  it('says a platform-held schedule survives the computer being off', async () => {
    planMock.mockResolvedValue({ plan: { ...IMMEDIATE_PLAN, kind: 'platform' } });
    await render();
    expect(dom().querySelector('.social-publish__held')?.textContent).toContain('computer is off');
  });

  it('names the platform the schedule is held on', async () => {
    planMock.mockResolvedValue({ plan: { ...IMMEDIATE_PLAN, kind: 'platform' } });
    await render();
    expect(dom().querySelector('.social-publish__held')?.textContent).toContain('YouTube');
  });

  it('shows the pre-audit visibility cap before any publish', async () => {
    await render();
    expect(dom().querySelector('.social-publish__audit')?.textContent).toContain('PRIVATE');
  });

  it('omits the audit note when the platform has none', async () => {
    planMock.mockResolvedValue({ plan: { ...IMMEDIATE_PLAN, unauditedVisibility: '' } });
    await render();
    expect(dom().querySelector('.social-publish__audit')).toBeNull();
  });

  it('re-previews the plan when the time changes', async () => {
    await render();
    planMock.mockClear();
    await act(async () => setValue(input('Publish at'), '2026-08-09T10:30'));
    expect(planMock).toHaveBeenCalledWith(
      'youtube',
      Math.floor(new Date('2026-08-09T10:30').getTime() / 1000),
    );
  });

  it('surfaces a plan failure and clears the stale plan', async () => {
    planMock.mockRejectedValue(new Error('bad time'));
    await render();
    expect(planErrorText()).toBe('bad time');
    expect(dom().querySelector('.social-publish__plan')).toBeNull();
  });

  it('stringifies a non-Error plan rejection', async () => {
    planMock.mockRejectedValue('nope');
    await render();
    expect(planErrorText()).toBe('Could not check that time');
  });
});

describe('<SocialPublishPanel /> — queueing', () => {
  it('disables the button until a clip and a title are present', async () => {
    await render({ clipPath: '' });
    expect(buttonByText('Publish now')?.disabled).toBe(true);
    expect(dom().textContent).toContain('Export a clip first');
  });

  it('disables the button when the title is only whitespace', async () => {
    await render();
    await act(async () => setValue(input('Post title'), '   '));
    expect(buttonByText('Publish now')?.disabled).toBe(true);
  });

  it('sends the job with the clip, title and provenance video id', async () => {
    await render();
    await act(async () => setValue(input('Post title'), 'My clip'));
    await act(async () => buttonByText('Publish now')?.click());
    expect(enqueueMock).toHaveBeenCalledWith({
      platform: 'youtube',
      clipPath: 'clip.mp4',
      title: 'My clip',
      description: '',
      videoId: 'v1',
      publishAt: null,
    });
  });

  it('labels the button Schedule once a time is chosen', async () => {
    await render();
    await act(async () => setValue(input('Publish at'), '2026-08-09T10:30'));
    expect(buttonByText('Schedule')).toBeDefined();
  });

  it('reloads the queue after a successful enqueue', async () => {
    await render();
    await act(async () => setValue(input('Post title'), 'My clip'));
    queueMock.mockClear();
    await act(async () => buttonByText('Publish now')?.click());
    expect(queueMock).toHaveBeenCalled();
  });

  it('surfaces an enqueue failure', async () => {
    enqueueMock.mockRejectedValue(new Error('refused'));
    await render();
    await act(async () => setValue(input('Post title'), 'My clip'));
    await act(async () => buttonByText('Publish now')?.click());
    expect(errorText()).toBe('refused');
  });

  it('stringifies a non-Error enqueue rejection', async () => {
    enqueueMock.mockRejectedValue('boom');
    await render();
    await act(async () => setValue(input('Post title'), 'My clip'));
    await act(async () => buttonByText('Publish now')?.click());
    expect(errorText()).toBe('Could not queue that publish');
  });
});

describe('<SocialPublishPanel /> — the queue list', () => {
  it('says so when nothing is queued', async () => {
    await render();
    expect(dom().textContent).toContain('Nothing queued yet');
  });

  it('lists an entry with its human status', async () => {
    queueMock.mockResolvedValue({ entries: [ENTRY] });
    await render();
    expect(dom().querySelector('.social-publish__queue')?.textContent).toContain('My clip');
  });

  it('cancels a pending entry and reloads', async () => {
    queueMock.mockResolvedValue({ entries: [ENTRY] });
    await render();
    await act(async () => buttonByText('Cancel')?.click());
    expect(cancelMock).toHaveBeenCalledWith('e1');
  });

  it('offers no Cancel for a terminal entry', async () => {
    queueMock.mockResolvedValue({ entries: [{ ...ENTRY, status: 'done' }] });
    await render();
    expect(buttonByText('Cancel')).toBeUndefined();
  });

  it('surfaces a cancel failure', async () => {
    queueMock.mockResolvedValue({ entries: [ENTRY] });
    cancelMock.mockRejectedValue(new Error('cancel boom'));
    await render();
    await act(async () => buttonByText('Cancel')?.click());
    expect(errorText()).toBe('cancel boom');
  });

  it('stringifies a non-Error cancel rejection', async () => {
    queueMock.mockResolvedValue({ entries: [ENTRY] });
    cancelMock.mockRejectedValue('x');
    await render();
    await act(async () => buttonByText('Cancel')?.click());
    expect(errorText()).toBe('Cancel failed');
  });
});

describe('<SocialPublishPanel /> — load failures', () => {
  it('surfaces a capabilities failure', async () => {
    capabilitiesMock.mockRejectedValue(new Error('no platforms'));
    await render();
    expect(errorText()).toBe('no platforms');
  });

  it('stringifies a non-Error capabilities rejection', async () => {
    capabilitiesMock.mockRejectedValue('nope');
    await render();
    expect(errorText()).toBe('Failed to load platforms');
  });

  it('surfaces a queue-load failure', async () => {
    queueMock.mockRejectedValue(new Error('queue down'));
    await render();
    expect(dom().textContent).toContain('queue down');
  });

  it('stringifies a non-Error queue rejection', async () => {
    queueMock.mockRejectedValue('nope');
    await render();
    expect(dom().textContent).toContain('Failed to load the publish queue');
  });

  it('renders with no props at all (defaults)', async () => {
    // Mounted by hand rather than via render(), which always supplies clipPath —
    // this exercises the prop DEFAULTS (clipPath='' / videoId='').
    const host = document.createElement('div');
    document.body.appendChild(host);
    container = host;
    const mounted = createRoot(host);
    root = mounted;
    await act(async () => {
      mounted.render(<SocialPublishPanel />);
    });
    await act(async () => {
      await Promise.resolve();
    });
    expect(dom().textContent).toContain('Export a clip first');
  });
});
