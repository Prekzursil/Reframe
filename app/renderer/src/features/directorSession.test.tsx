// directorSession.test.tsx — the hoisted Director session store (F32).
//
// Covers the resolution rule (which is where the subtle bug lives: keying purely on
// the OPEN video is circular when no video is open but a plan is on screen), the
// store/replace/per-video-isolation behaviour, and the provider-vs-fallback split.

// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

import {
  CLEAN_SESSION,
  DirectorSessionProvider,
  resolveSession,
  useDirectorSession,
  type DirectorSessionEntry,
  type DirectorSessionStore,
} from './directorSession';
import type { DirectorEditPlan, DirectorOp } from '../lib/directorTypes';

// ---- fixtures ---------------------------------------------------------------

function op(over: Partial<DirectorOp> = {}): DirectorOp {
  return {
    id: 'op-1',
    kind: 'trim',
    span: [0, 1000],
    params: {},
    reversible: true,
    rationale: '',
    status: 'planned',
    statusReason: null,
    ...over,
  };
}

function planFixture(videoId = 'vid-1'): DirectorEditPlan {
  return {
    planId: `plan-${videoId}`,
    videoId,
    goal: 'tighten',
    sourceHash: 'h',
    ops: [op()],
    inverse: [],
  };
}

function entry(videoId = 'vid-1', over: Partial<DirectorSessionEntry> = {}): DirectorSessionEntry {
  return {
    videoId,
    goal: `goal for ${videoId}`,
    plan: planFixture(videoId),
    opsStatus: null,
    applied: false,
    ...over,
  };
}

// ---- resolveSession --------------------------------------------------------

describe('resolveSession', () => {
  it('serves a clean session when nothing is stored', () => {
    expect(resolveSession(null, 'vid-1')).toBe(CLEAN_SESSION);
    expect(resolveSession(null, null)).toBe(CLEAN_SESSION);
  });

  it('serves the stored session for the SAME open video', () => {
    const stored = entry('vid-1');
    expect(resolveSession(stored, 'vid-1')).toBe(stored);
  });

  it('serves the stored session when NO video is open (WU-E1: no id to key by)', () => {
    // This is the case a naive "key by the open video id" rule gets wrong: with
    // video===null the only videoId in existence is the one INSIDE the session being
    // read, so refusing here would drop the "a video closed after planning keeps its
    // plan" guarantee that DirectorPanel deliberately implements.
    const stored = entry('vid-1');
    expect(resolveSession(stored, null)).toBe(stored);
  });

  it('REFUSES the stored session when a DIFFERENT video is open', () => {
    const stored = entry('vid-1');
    expect(resolveSession(stored, 'vid-2')).toBe(CLEAN_SESSION);
  });

  it('CLEAN_SESSION carries no work', () => {
    expect(CLEAN_SESSION).toEqual({ goal: '', plan: null, opsStatus: null, applied: false });
  });
});

// ---- the store (through the provider AND the fallback) ----------------------

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

/** Capture the live store from inside the tree so a test can drive it. */
function Probe({ onStore }: { onStore: (s: DirectorSessionStore) => void }): React.ReactElement {
  const store = useDirectorSession();
  onStore(store);
  return <div data-testid="probe" data-goal={store.stored?.goal ?? ''} />;
}

/** Render `Probe`, optionally wrapped in the provider; returns the latest store. */
async function renderProbe(withProvider: boolean): Promise<() => DirectorSessionStore> {
  let latest: DirectorSessionStore | null = null;
  const capture = (s: DirectorSessionStore): void => {
    latest = s;
  };
  await act(async () => {
    root.render(
      withProvider ? (
        <DirectorSessionProvider>
          <Probe onStore={capture} />
        </DirectorSessionProvider>
      ) : (
        <Probe onStore={capture} />
      ),
    );
  });
  // Non-null by construction: Probe runs during the act() render above.
  return () => latest as unknown as DirectorSessionStore;
}

describe('useDirectorSession store', () => {
  it('starts empty', async () => {
    const store = await renderProbe(true);
    expect(store().stored).toBeNull();
  });

  it('stores a session under its videoId', async () => {
    const store = await renderProbe(true);
    await act(async () => {
      store().update('vid-1', (prev) => ({ ...prev, goal: 'tighten the pacing' }));
    });
    expect(store().stored).toEqual({
      videoId: 'vid-1',
      goal: 'tighten the pacing',
      plan: null,
      opsStatus: null,
      applied: false,
    });
  });

  it('REPLACES fields on a second update for the same video', async () => {
    const store = await renderProbe(true);
    const plan = planFixture('vid-1');
    await act(async () => {
      store().update('vid-1', (prev) => ({ ...prev, goal: 'first' }));
    });
    await act(async () => {
      store().update('vid-1', (prev) => ({ ...prev, plan, applied: true }));
    });
    // The updater saw the PREVIOUS session, so the earlier goal is preserved.
    expect(store().stored).toEqual({
      videoId: 'vid-1',
      goal: 'first',
      plan,
      opsStatus: null,
      applied: true,
    });
  });

  it('ISOLATION: an update for a different video starts from a clean session', async () => {
    const store = await renderProbe(true);
    await act(async () => {
      store().update('vid-1', (prev) => ({ ...prev, goal: 'vid-1 goal', plan: planFixture() }));
    });
    let seen: string | null = null;
    await act(async () => {
      store().update('vid-2', (prev) => {
        seen = prev.goal;
        return { ...prev, goal: 'vid-2 goal' };
      });
    });
    // vid-2's updater must NOT inherit vid-1's goal or plan.
    expect(seen).toBe('');
    expect(store().stored).toEqual({
      videoId: 'vid-2',
      goal: 'vid-2 goal',
      plan: null,
      opsStatus: null,
      applied: false,
    });
  });

  it('carries opsStatus (the apply result) like any other field', async () => {
    const store = await renderProbe(true);
    const opsStatus = [op({ id: 'a', status: 'applied' })];
    await act(async () => {
      store().update('vid-1', (prev) => ({ ...prev, opsStatus, applied: true }));
    });
    expect(store().stored?.opsStatus).toBe(opsStatus);
  });

  it('FALLBACK: works with no provider mounted (a bare panel stays usable)', async () => {
    const store = await renderProbe(false);
    expect(store().stored).toBeNull();
    await act(async () => {
      store().update('vid-1', (prev) => ({ ...prev, goal: 'bare' }));
    });
    expect(store().stored?.goal).toBe('bare');
    expect(container.querySelector('[data-testid="probe"]')?.getAttribute('data-goal')).toBe(
      'bare',
    );
  });
});
