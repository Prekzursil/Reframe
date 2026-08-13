// Workspace.seam.test.tsx — the Workspace ↔ Subtitles COMPOSITION seam (F19).
//
// This is a SEPARATE file from Workspace.test.tsx on purpose: that suite's
// file-wide `vi.mock('../features/Subtitles')` (Workspace.test.tsx:62) is hoisted
// and replaces the panel with a marker div, so it can never observe how the real
// panel treats a LATE `initialTrack`. Here the REAL panel renders.
//
// The defect this pins: `Workspace.renderPanel()` passes
// `initialTrack={tracks[0] ?? null}` derived from `project.tracks`, but
// `project.open` is fired from a POST-COMMIT effect (Workspace.tsx:173-176) while
// the lazy panel chunk is already in flight. When the chunk wins that race the
// panel mounts with `initialTrack === null`, and `useState(initialTrack)`
// (Subtitles.tsx:52) captures the null once — so the track that arrives moments
// later is ignored for the panel's whole lifetime.
//
// Scaffolding required for the REAL Workspace under jsdom (without these the test
// throws before reaching its assertion, i.e. it would be red in BOTH states and
// measure nothing):
//   * `../lib/rpc` must be mocked — Workspace.tsx:207-212 subscribes via
//     onProxyState, whose bridge() (lib/rpc/client.ts:96-102) THROWS when
//     window.api is absent;
//   * HTMLMediaElement load/play/pause must be backed — Workspace.tsx:317 mounts
//     the real <Player>, and jsdom does not implement media playback.

// @vitest-environment jsdom
import { describe, it, expect, vi, beforeAll, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

// REFUTED IN REVIEW, and the refuted wording is kept on purpose: this comment used
// to read "was the ONE renderer suite that never declared the act environment (64
// other renderer test files do)". That was false, by 76. Two mechanically
// independent detectors — a Python `re` scan and a PowerShell `-match` scan, both
// over renderer/src/**/*.test.ts{,x} — return the SAME triple: 209 renderer test
// files, 141 of them call `act(`, 65 declare the flag. So 76 act-using renderer test
// files still do not declare it, and 77 did not before this line existed. The
// detector was controlled before its counts were trusted: components/TopTabBar.test.tsx
// reports 6 `act(` hits and no flag (known-present, found), views/Caption.test.tsx
// reports 7 hits and the flag (known-declared, found). No global declaration rescues
// the original wording either — app/vitest.config.ts has no `setupFiles` key at all.
//
// CORRECTLY SCOPED: this file was one of 77 renderer test files that drive React
// through act() without declaring the act environment; 64 of the 141 act-using files
// already declared it (e.g. views/Caption.test.tsx:8), and this line makes it 65.
//
// What the line actually buys — and its measured LIMIT, which matters more here than
// the count did. In React 18.3.1 `IS_REACT_ACT_ENVIRONMENT` is read from exactly two
// places, warnIfUpdatesNotWrappedWithActDEV (react-dom.development.js:27598) and
// warnIfSuspenseResolutionNotWrappedWithActDEV (:27642) — both warning paths, via
// isConcurrentActEnvironment (:25292). It does NOT participate in scheduling and does
// NOT change how act() drains its queue. (Grep: 5 occurrences in
// react-dom/cjs/react-dom.development.js, 0 anywhere under react/.) So it re-enables
// React's own not-wrapped-in-act detector — measured: the isolated run emitted
// "The current testing environment is not configured to support act(...)" on every
// mount before this line and zero after — and it CANNOT be, and must not be cited as,
// a fix for any settling, adoption or timing behaviour in this file.
(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

beforeAll(() => {
  Object.defineProperty(HTMLMediaElement.prototype, 'load', {
    configurable: true,
    value: vi.fn(),
  });
  Object.defineProperty(HTMLMediaElement.prototype, 'play', {
    configurable: true,
    value: vi.fn(() => Promise.resolve()),
  });
  Object.defineProperty(HTMLMediaElement.prototype, 'pause', {
    configurable: true,
    value: vi.fn(),
  });
});

const rpcMock = vi.fn();
vi.mock('../components/api', () => ({
  rpc: (...args: unknown[]) => rpcMock(...args),
  onProgress: () => () => {},
  hasApi: () => true,
}));

type ProxyStateEvt = {
  videoId: string;
  state: 'building' | 'direct' | 'ready' | 'error';
  detail: string;
};
const onProxyStateMock = vi.fn<(cb: (e: ProxyStateEvt) => void) => () => void>();
vi.mock('../lib/rpc', () => ({
  onProxyState: (cb: (e: ProxyStateEvt) => void) => onProxyStateMock(cb),
}));

// NOTE: ../features/Subtitles is deliberately NOT mocked here.
//
// ../features/TranscriptEditor IS mocked: this suite pins the Subtitles seam, it
// never selects the Transcript-edit tab, and leaving that panel real only adds
// its module graph to the race this test is already timing. Measured: with the
// panel real the case intermittently trips the 5s default (2/5 full-suite runs)
// while passing in isolation at ~2.2s of test time, i.e. a transform-cost cliff
// under parallel load, not a behaviour change. UNVERIFIED whether CI's Linux
// runner ever crosses that cliff — settled by dropping this mock and reading the
// gate-tests-coverage vitest step; the stub is correct either way.
//
// That diagnosis held up FOR THE 5000ms TRIP, and only for it: the timeout cliff
// was transform cost, and it is now removed from the per-test budget wholesale by
// the warming beforeAll below rather than only trimmed by this one stub. It does
// NOT explain the `expected null not to be null` symptom, which review reproduced
// on the post-fix tree and also in a file with no lazy import at all — see the
// REFUTED block above flushUntil before treating any of this as a flake fix. The
// stub still earns its place (it keeps a panel this suite never opens out of the
// warm set at all).
vi.mock('../features/TranscriptEditor', () => ({ default: () => <div /> }));

import { Workspace } from './Workspace';
import type { Project, SubtitleTrack, Video } from '../components/api';

const video: Video = {
  id: 'v1',
  path: '/movies/talk.mp4',
  title: 'Talk',
  addedAt: '2026-06-11T00:00:00Z',
  durationSec: 605,
  hasTranscript: true,
};

const project: Project = { id: 'v1', video, tracks: [], clips: [], settings: {} };

// Mirrors the WIRE, not the declaration: tracks inside a persisted project pass
// through tracks._normalise (sidecar/media_studio/features/tracks.py:157-180),
// which guarantees all six frozen fields with `cues` a real list; a cue is
// {index, start, end, text} (features/subtitles.py:110).
const wireTrack: SubtitleTrack = {
  id: 'tr1',
  lang: 'en',
  name: 'English',
  format: 'srt',
  kind: 'soft',
  cues: [
    { index: 1, start: 0, end: 2, text: 'first' },
    { index: 2, start: 5, end: 7, text: 'second' },
  ],
};

// ─── why the lazy chunks are warmed HERE and not inside each test ────────────
//
// SCOPE FIRST, because the earlier version of this block overclaimed and was
// REFUTED by an executed run. What is measured below is a BUDGET-CONSUMPTION
// finding: where the 5000ms per-test budget went. It is NOT a demonstration that
// this file's reported `expected null not to be null` flake is gone. See the
// REFUTED block above flushUntil for that, and do not cite this block for it.
//
// WHERE THE BUDGET WENT, MEASURED (not inferred). Every case below used to open
// with its own `await import('../features/X')`. That call is a vite-node module
// transform+load over a server SHARED with every other parallel worker, and
// whichever test file requests a given panel FIRST in a run pays its whole cold
// graph — so the cost is order- and load-dependent, not a property of the test.
// Instrumenting each phase across five full-suite runs (`vitest run`, default
// 5000ms) measured that same single call at 5.3ms in one run and 2972.7ms in
// another, a 560x spread. In the worst run the Subtitles case finished in
// 4205ms of its 5000ms budget with 2972.7ms of that — 71% — spent inside that
// one import, before its first assertion.
//
// REFUTED IN REVIEW, wording kept: this used to end "The assertion work itself
// never exceeded 630ms (render 17-161ms, flush 125-889ms) in any run." That
// sentence contradicts its own parenthetical — it counts flush as assertion work
// and then caps assertion work below the flush maximum it just quoted. 889 > 630.
// The Subtitles case settles TWICE (once for `.subtitles-panel`, once for
// `.track-meta`), so on those same numbers its worst case is ~1.8s, roughly 3x the
// figure claimed. An isolated verbose run of the shipped file independently puts
// that case at 652ms — already over 630ms — with the others at 502/263/151/51ms.
//
// CORRECTLY SCOPED: per-test assertion work measured 17-161ms of render plus
// 125-889ms per settling call; the Subtitles case settles twice, so its worst
// measured case is ~1.8s. That is still ~3x under the 5000ms budget, versus the
// 4205ms the cold import made it — which is the whole point of moving the import
// out of the per-test budget and into a hook with its own explicit bound.
//
// The import itself is QUEUED WORK, not a hang: nothing here waits on an unbounded
// condition (a bounded import, one render, a bounded count of macrotask turns —
// see flushUntil), and the file passes at --testTimeout=30000. The hook carries
// its own explicit budget because the cost it absorbs is real.
beforeAll(async () => {
  await Promise.all([
    import('../features/Subtitles'),
    import('../features/Gaze'),
    import('../features/Dub'),
    import('../features/BrollPanel'),
    import('../features/Speed'),
  ]);
  // 60s, not the 10000ms default hookTimeout: instrumenting this hook measured
  // the five imports at 5015ms cold on this box — already half the default — and
  // 89-493ms once sibling suites had warmed the same graph. The budget has to
  // cover the cold case with room, and nothing under test happens in here, so a
  // wide bound costs no guard strength (unlike widening a per-test timeout).
}, 60_000);

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  rpcMock.mockReset();
  onProxyStateMock.mockReset();
  onProxyStateMock.mockReturnValue(() => undefined);
  // The real panel reads the frozen bridge through getApi() (features/_api.ts:99)
  // inside effects/callbacks only; install a fake so any later interaction has one.
  (globalThis as { api?: unknown }).api = {
    rpc: vi.fn(async () => ({})),
    onProgress: () => () => {},
    onJobDone: () => () => {},
  };
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  delete (globalThis as { api?: unknown }).api;
});

// Real macrotask turns (not just microtasks): the lazy chunk is a genuine dynamic
// import, so a microtask-only drain can leave the Suspense fallback mounted.
//
// ─── REFUTED IN REVIEW — read this before citing anything about "the flake" ───
//
// The change that introduced this helper claimed it "removes the `expected null
// not to be null` half of this file's reported flake", on the strength of 5/5
// post-fix green full runs. An adversarial re-run REFUTED that on this very tree:
// across four `npx vitest run --coverage` runs of this branch, one went RED at the
// exact assertion the change was meant to protect — Workspace.seam.test.tsx:241,
// `.track-meta`, `expected null not to be null` — i.e. this poll exhausted and the
// caller's expect failed. 1 red in 4 post-fix gate runs, against a summary that
// reported 5/5 green and called the symptom removed. The refuted wording is kept
// here on purpose; it must not be quietly deleted.
//
// CORRECTLY SCOPED: the settling scaffolding was made cheaper and the per-test
// budget headroom improved (the warming block above IS measured and stands). The
// flake is NOT demonstrated gone. Nothing in this file may claim that it is.
//
// The attributed CAUSE was wrong too, in two mechanically independent ways:
//
//   (a) Turn starvation is not the mechanism. Instrumenting the shipped helper
//       across all six call sites in this file measured every one settling after
//       exactly 1 turn. A 1-turn measured need does not starve at 10, let alone at
//       the 50 this shipped with — and the red run above exhausted all 50, which
//       is a never-settles signature, not a slow-settles one. So the sentence this
//       block used to carry — "too few turns and the assertion reads a DOM that
//       has not settled (the `expected null not to be null` half of this file's
//       reported flake)" — is REFUTED as an attribution. Load stretches the
//       wall-clock cost of a turn, not the NUMBER of turns needed.
//
//   (b) The transform-cost root cause does not reach the symptom. In that same red
//       run, features/Subtitles.test.tsx:148 failed with the IDENTICAL assertion
//       on the IDENTICAL product behaviour (late `initialTrack` adoption,
//       Subtitles.tsx:133-135). That file is not in this branch's diff, has no
//       lazy import, no Suspense, and no poll at all — its `mount()` is a single
//       `await act(async () => root.render(...))` — so neither transform cost nor
//       any settling window explains it. Two files failing on the same adoption is
//       a pattern, not resource noise.
//
// UNVERIFIED: whether that adoption failure predates this branch, and what its
// mechanism is. It is NOT the missing act-environment flag — in React 18.3.1 that
// global is read only by two warning helpers, never by the scheduler (see the note
// at the top of this file). SETTLING EXPERIMENT: run `npx vitest run --coverage`
// N>=8 times on origin/main and count reds at Subtitles.test.tsx:148. A red there
// on main makes this a pre-existing product/act race in the adoption path, with
// this file merely a second witness; no red in N=8 pushes suspicion back onto this
// branch and this file.
//
// ─── what the helper is, and why the bound is 10 ─────────────────────────────
//
// CONDITION-DRIVEN rather than a fixed turn count. This was `flush(turns = 10)`:
// ten unconditional turns per call — twenty in the Subtitles case, which calls it
// twice — burnt whether or not the DOM had already settled, and MEASURED at
// 125-889ms per call under full-suite load. Polling stops at the turn the
// precondition becomes true (measured: turn 1), which removes that cost without
// touching a single assertion.
//
// The bound is back to 10. Shipping it at 50 was a REFUTED 5x widening of the
// guard, and review proved the lost detection executably rather than arguing it:
// injecting a 15-macrotask-turn latency regression into the project.open->adopt
// path made the pre-lane `flush(10)` go RED with precisely `expected null not to
// be null`, while `flushUntil(present('.track-meta'), 50)` PASSED the same mutated
// system. Polling fixes the "guessing the turn count" problem in the WASTEFUL
// direction only; it is not a licence to widen in the DETECTING direction. At 10
// this helper keeps the pre-lane detection strength (an 11+-turn adoption-latency
// regression still goes red) AND the post-lane cost (it stops at turn 1) — better
// than either predecessor rather than a trade between them.
//
// Exhaustion THROWS rather than returning quietly. Returning quietly is what
// reduced the red run above to a bare `expected null not to be null` naming
// neither the selector, the turn budget, nor the fact that settling had been
// attempted — the same message-less-failure defect this branch fixed on the
// sidecar side, left live on the renderer side. Every call site is immediately
// followed by an assertion that the selector IS present, so throwing is
// semantically identical and strictly better labelled.
type SettlePredicate = { (): boolean; label: string };

async function flushUntil(settled: SettlePredicate, maxTurns = 10): Promise<void> {
  for (let i = 0; i < maxTurns; i++) {
    // eslint-disable-next-line no-await-in-loop
    await act(async () => {
      await new Promise((resolve) => {
        setTimeout(resolve, 0);
      });
    });
    if (settled()) return;
  }
  throw new Error(
    `flushUntil: ${settled.label} still false after ${maxTurns} macrotask turns.` +
      " The measured need across this file's call sites is 1 turn, so this is a" +
      ' never-settles signature rather than a slow box. Report it as a settling' +
      ' exhaustion, NOT as a bare assertion failure.',
  );
}

function present(selector: string): SettlePredicate {
  return Object.assign(() => container.querySelector(selector) !== null, {
    label: `present(${selector})`,
  });
}

describe('Workspace ↔ Subtitles seam', () => {
  it('adopts project.tracks[0] when project.open resolves AFTER the panel mounts', async () => {
    // The chunk is already warm (see the warming beforeAll above), so the
    // losing-race ordering — panel mounts BEFORE project.open resolves — is
    // pinned deterministically instead of left to transform timing.
    let resolveOpen: (value: { project: Project }) => void = () => undefined;
    rpcMock.mockImplementation((method: string) => {
      if (method === 'project.open') {
        return new Promise<{ project: Project }>((resolve) => {
          resolveOpen = resolve;
        });
      }
      return Promise.resolve({});
    });

    // L5: the workspace no longer LANDS on Subtitles. Its default selection is
    // "nothing selected" → project tools; Subtitles is a CUE-scoped tool, opened
    // by selecting the caption lane or, as here, by the deep-link the Task Hub
    // already sends (`taskHub.ts:109` → `{kind:'workspace', tab:'subtitles'}`).
    // The seam under test — the panel adopting `project.tracks[0]` when
    // `project.open` resolves after the mount — is unchanged.
    await act(async () => {
      root.render(<Workspace video={video} onBack={() => {}} initialTab="subtitles" />);
    });
    await flushUntil(present('.subtitles-panel'));

    // Preconditions — these are what make the assertion below a genuine red for
    // the DEFECT rather than a setup error: the REAL panel is mounted (not the
    // Suspense fallback) and it currently has no track.
    expect(container.querySelector('.subtitles-panel')).not.toBeNull();
    expect(container.querySelector('.track-meta')).toBeNull();

    await act(async () => {
      resolveOpen({ project: { ...project, tracks: [wireTrack] } });
    });
    await flushUntil(present('.track-meta'));

    expect(container.querySelector('.track-meta')).not.toBeNull();
    expect(container.querySelector('.track-meta')?.textContent).toContain('English');
    expect([...container.querySelectorAll('.cue-text')]).toHaveLength(2);
  });
});

// ─── W19 / W20: the seam tests the lane's reachability claim actually needs ──
// REFUTED IN REVIEW, twice and correctly: the lane offered
// `Workspace.test.tsx`'s "renders the gaze panel for its tab" as "the actual
// reachability test", but that file does `vi.mock('../features/Gaze', () =>
// stubPanel('Gaze'))` — it mounts a STUB. It proves the TabBar + `renderPanel()`
// switch and the props handed down; it cannot prove that
// `lazy(() => import('../features/Gaze'))` resolves or that the real panel mounts.
// That was resting on `tsc --noEmit`. These two cases close it in the file whose
// whole purpose is real lazy panel mounts, so the claim is now executable rather
// than narrowed away.
describe('Workspace ↔ Gaze seam (W19)', () => {
  it('mounts the REAL Gaze panel on the eye-contact tab', async () => {
    rpcMock.mockResolvedValue({ project }); // chunk warmed in beforeAll

    await act(async () => {
      root.render(<Workspace video={video} onBack={() => {}} initialTab="gaze" />);
    });
    await flushUntil(present('.gaze-panel'));

    // The real panel, not the Suspense fallback and not a marker div: its own
    // section class plus the ethics gate that only the real component renders.
    expect(container.querySelector('.gaze-panel')).not.toBeNull();
    expect(container.querySelector('[data-testid="gaze-consent"]')).not.toBeNull();
    expect(container.querySelector('[data-input="likeness-attest"]')).not.toBeNull();
    // Fail-closed on this scaffold: the fake bridge answers `gaze.probe` with `{}`,
    // so the panel treats the model as unavailable and the Run button stays shut.
    // That IS the shipped behaviour for a machine without the YuNet asset.
    expect((container.querySelector('[data-action="run"]') as HTMLButtonElement).disabled).toBe(
      true,
    );
  });
});

describe('Workspace ↔ Dub/LipSync seam (W20)', () => {
  it('mounts the REAL lip-sync section inside the Dub tab, disabled by default', async () => {
    // Dub hosts the LipSync section; its chunk is warmed in beforeAll.
    rpcMock.mockResolvedValue({ project });

    await act(async () => {
      root.render(<Workspace video={video} onBack={() => {}} initialTab="dub" />);
    });
    await flushUntil(present('.lipsync-section'));

    // The reachability half that IS true for W20: the control exists on a surface a
    // user can open. It is DISABLED here — the fake bridge answers `settings.get`
    // with `{}`, so `lipSyncEnabled` is not the literal true, exactly as every stock
    // build behaves. See the LipSync header: this is a call site, not a runnable
    // feature, and this test pins that distinction rather than papering over it.
    expect(container.querySelector('.lipsync-section')).not.toBeNull();
    const start = container.querySelector('[data-action="start-lipsync"]') as HTMLButtonElement;
    expect(start).not.toBeNull();
    expect(start.disabled).toBe(true);
    expect(container.querySelector('[data-section="disabled"]')?.textContent).toContain(
      'lipSyncEnabled',
    );
  });
});

// W16-UI. Same reason the Gaze block above exists, and the reachability claim here
// is the whole point of the lane: `Workspace.test.tsx` mocks
// `../features/BrollPanel` to a marker div, so it proves the TabBar + the
// `renderPanel()` switch and nothing about whether
// `lazy(() => import('../features/BrollPanel'))` resolves. Only a REAL mount can
// show that a user clicking "Auto B-roll" actually reaches the seven `broll.*`
// RPCs — the claim this lane is making — so it is asserted here, executably,
// rather than narrowed away or rested on `tsc --noEmit`.
describe('Workspace ↔ BrollPanel seam (W16-UI)', () => {
  it('mounts the REAL b-roll panel on its tab, with its honesty surfaces present', async () => {
    rpcMock.mockResolvedValue({ project }); // chunk warmed in beforeAll

    await act(async () => {
      root.render(<Workspace video={video} onBack={() => {}} initialTab="broll" />);
    });
    await flushUntil(present('.broll-panel'));

    // The real panel, not the Suspense fallback and not a marker div: its own
    // section class plus the two disclosures only the real component renders.
    expect(container.querySelector('.broll-panel')).not.toBeNull();
    expect(container.querySelector('[data-section="threshold-disclosure"]')?.textContent).toContain(
      'UNCALIBRATED',
    );
    expect(container.querySelector('[data-section="limits"]')).not.toBeNull();
    // The threshold really is a control the user can move, not a fixed constant.
    expect(container.querySelector('[data-input="threshold"]')).not.toBeNull();
    // Fail-closed on this scaffold: the fake bridge answers `broll.assets` with
    // `{}`, so the library reads EMPTY and the register control stays shut until a
    // path is typed. That IS the shipped first-run behaviour.
    expect(container.querySelector('[data-section="grid"]')).toBeNull();
    expect((container.querySelector('[data-action="add"]') as HTMLButtonElement).disabled).toBe(
      true,
    );
    // …and the same `{}` must NOT paint a freshness snapshot. A reviewer caught
    // this scaffold doing exactly that: `readBrollStatus` only rejected NON-objects,
    // so `{}` returned a full row of zeros and THIS test — the one offered as proof
    // of reachability — rendered "In library 0" as though it were a measurement.
    // Fixed in the panel; pinned here so the scaffold can never fabricate again.
    expect(container.querySelector('[data-section="status"]')).toBeNull();
    // The prerequisites are the first thing a user on a fresh video needs, so they
    // must survive the real lazy mount, not just the unit harness.
    //
    // THIS ASSERTION WAS CHANGED, and the reason matters: it used to pin the phrase
    // 'transcribe THIS video first'. That wording was itself the defect. The sidecar
    // enforces `require_model` (broll_ops.py:403) BEFORE the transcript raise (:408),
    // so transcribing is the THIRD prerequisite, not the first — and the omitted one
    // is a 4.5 GB SigLIP-2 download that no copy mentioned. Pinning "first" therefore
    // locked in a false ordering. The replacement is STRICTER, not looser: it keeps
    // the transcript pin and adds the matcher pin, so the seam now proves both halves
    // survive the real lazy mount.
    const prereq = container.querySelector('[data-section="prerequisites"]')?.textContent;
    expect(prereq).toContain('transcribe THIS video');
    expect(prereq).toContain('Assets tab');
  });
});

describe('Workspace ↔ Speed seam', () => {
  it('mounts the REAL Speed panel on the speed tab, threaded with the video duration', async () => {
    // The point of this test: before v1.5 the re-time engine had no control in
    // ANY panel. Asserting the real panel (not the Suspense fallback) is what
    // proves the door is genuinely reachable from the Workspace.
    rpcMock.mockResolvedValue({ project }); // chunk warmed in beforeAll

    await act(async () => {
      root.render(<Workspace video={video} onBack={() => {}} initialTab="speed" />);
    });
    await flushUntil(present('.speed-panel'));

    const panel = container.querySelector('.speed-panel');
    expect(panel).not.toBeNull();
    // `video.durationSec` is threaded through, so the before/after prediction is
    // real rather than a dash: 2x on this source halves it.
    expect(container.querySelector('[data-field="sourceDuration"]')?.textContent).not.toBe('—');
    expect(container.querySelector('[data-field="newDuration"]')?.textContent).not.toBe('—');
  });
});
