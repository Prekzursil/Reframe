// Gaze.test.tsx — tests for the "Eye contact" panel (W19).
//
// MEASURED GAP. `gaze.probe` + `gaze.run` are both registered
// (`sidecar/media_studio/features/gaze.py:699-700`) and both are frozen into the
// authoritative RPC surface (`sidecar/tests/test_handlers_rpc_surface.py`), yet
// before this panel the string `gaze` appeared ZERO times, case-insensitively,
// anywhere under `app/renderer`. The detector was controlled against a
// known-present item first: the same case-insensitive scan finds `gaze` in 9
// files under `sidecar/`, so the zero was real and not a broken matcher.
// `docs/wiring/WIRING-gaze.md:172` already presupposed "so the UI can disable the
// control" — the control did not exist.
//
// TWO RPCs:
//   gaze.probe()                      -> {available}            (direct return)
//   gaze.run({videoId, strength, likenessSubject, likenessAttested?})
//        -> {jobId} -> job.done {path, strength, report, likeness}
//
// THE ETHICS GATE IS THE POINT OF THIS PANEL, NOT A DECORATION.
// `gaze.run` alters a real person's face. `models/likeness.resolve_attestation`
// (`likeness.py:137-160`) accepts an EXPLICIT per-job attestation in the request,
// else a persisted grant, else it RAISES. This panel drives the EXPLICIT per-job
// route deliberately (see the Gaze.tsx header for why), so these tests pin two
// properties that a passing feature test alone would not:
//   * the attestation is NEVER minted by the UI — an untidied checkbox means the
//     param is ABSENT, not `false`-but-present and not `true`;
//   * the tick does not carry over to the next run after a success.
// A Tier-0 defect earlier in this programme (W02) was exactly a consent value the
// code minted on the user's behalf.

// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import Gaze, { buildGazeParams, gazeOutcome, DEFAULT_GAZE_STRENGTH } from './Gaze';
import type { DoneEvent, MediaStudioApi, ProgressEvent } from './_api';

interface FakeApi {
  api: MediaStudioApi;
  calls: Array<{ method: string; params?: Record<string, unknown> }>;
  fireProgress: (ev: ProgressEvent) => void;
  fireDone: (ev: DoneEvent) => void;
}

const REPORT = {
  framesTotal: 300,
  framesCorrected: 288,
  eyesCorrected: 570,
  skipped: { 'low-confidence': 12 },
};
const AUDIT = { subject: 'Marius (self)', scope: 'gaze', source: 'request' };

function makeFakeApi(
  overrides: { available?: boolean; probeError?: Error; runError?: Error } = {},
): FakeApi {
  const calls: FakeApi['calls'] = [];
  let progressCbs: Array<(ev: ProgressEvent) => void> = [];
  let doneCbs: Array<(ev: DoneEvent) => void> = [];
  const api: MediaStudioApi = {
    rpc: vi.fn(async <T,>(method: string, params?: Record<string, unknown>) => {
      calls.push({ method, params });
      if (method === 'gaze.probe') {
        if (overrides.probeError) throw overrides.probeError;
        return { available: overrides.available ?? true } as T;
      }
      if (method === 'gaze.run') {
        if (overrides.runError) throw overrides.runError;
        return { jobId: 'job-g' } as T;
      }
      return {} as T;
    }) as MediaStudioApi['rpc'],
    onProgress: (cb) => {
      progressCbs.push(cb);
      return () => {
        progressCbs = progressCbs.filter((c) => c !== cb);
      };
    },
    onJobDone: (cb) => {
      doneCbs.push(cb);
      return () => {
        doneCbs = doneCbs.filter((c) => c !== cb);
      };
    },
  };
  return {
    api,
    calls,
    fireProgress: (ev) => progressCbs.slice().forEach((cb) => cb(ev)),
    fireDone: (ev) => doneCbs.slice().forEach((cb) => cb(ev)),
  };
}

describe('buildGazeParams', () => {
  it('carries the explicit per-job attestation when the user ticked it', () => {
    expect(
      buildGazeParams({
        videoId: 'v1',
        likenessSubject: 'Marius (self)',
        likenessAttested: true,
        strength: 0.7,
      }),
    ).toEqual({
      videoId: 'v1',
      likenessSubject: 'Marius (self)',
      likenessAttested: true,
      strength: 0.7,
    });
  });

  it('OMITS likenessAttested entirely when the box is unticked — never mints consent', () => {
    const params = buildGazeParams({
      videoId: 'v1',
      likenessSubject: 'Someone',
      likenessAttested: false,
      strength: 0.5,
    });
    expect('likenessAttested' in params).toBe(false);
    // The subject still travels: the sidecar needs it to name the refusal.
    expect(params).toEqual({ videoId: 'v1', likenessSubject: 'Someone', strength: 0.5 });
  });

  it('trims the subject label so a whitespace-only subject cannot pose as one', () => {
    expect(
      buildGazeParams({
        videoId: 'v1',
        likenessSubject: '  Ana  ',
        likenessAttested: true,
        strength: 1,
      }).likenessSubject,
    ).toBe('Ana');
  });
});

describe('gazeOutcome', () => {
  it('reads a completed run including the likeness audit trail', () => {
    expect(
      gazeOutcome({
        path: '/out/gaze/clip.gaze.mp4',
        strength: 0.7,
        report: REPORT,
        likeness: AUDIT,
      }),
    ).toEqual({
      path: '/out/gaze/clip.gaze.mp4',
      strength: 0.7,
      report: REPORT,
      likeness: AUDIT,
    });
  });

  it('null when there is no usable path', () => {
    expect(gazeOutcome({})).toBeNull();
    expect(gazeOutcome(null)).toBeNull();
    expect(gazeOutcome({ path: '' })).toBeNull();
    expect(gazeOutcome({ path: 42 })).toBeNull();
  });

  it('defaults a missing/malformed report to explicit zeros rather than inventing a tally', () => {
    expect(gazeOutcome({ path: '/p.mp4' })?.report).toEqual({
      framesTotal: 0,
      framesCorrected: 0,
      eyesCorrected: 0,
      skipped: {},
    });
    expect(
      gazeOutcome({ path: '/p.mp4', report: { framesTotal: 'lots', skipped: 'nope' } })?.report,
    ).toEqual({ framesTotal: 0, framesCorrected: 0, eyesCorrected: 0, skipped: {} });
    // `typeof null === 'object'`, so an explicit null must be rejected by the
    // null-check arm rather than indexed into.
    expect(gazeOutcome({ path: '/p.mp4', report: null })?.report).toEqual({
      framesTotal: 0,
      framesCorrected: 0,
      eyesCorrected: 0,
      skipped: {},
    });
  });

  it('drops non-numeric skip counts instead of rendering junk', () => {
    expect(
      gazeOutcome({
        path: '/p.mp4',
        report: { ...REPORT, skipped: { 'extreme-roll': 3, bogus: 'x' } },
      })?.report.skipped,
    ).toEqual({ 'extreme-roll': 3 });
  });

  it('null strength and null likeness when the sidecar sent neither', () => {
    const out = gazeOutcome({ path: '/p.mp4' });
    expect(out?.strength).toBeNull();
    expect(out?.likeness).toBeNull();
  });

  it('drops a shapeless likeness block — an audit trail is all-or-nothing', () => {
    expect(gazeOutcome({ path: '/p.mp4', likeness: { subject: 'a' } })?.likeness).toBeNull();
    expect(gazeOutcome({ path: '/p.mp4', likeness: 'attested' })?.likeness).toBeNull();
  });
});

describe('<Gaze />', () => {
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

  const flush = async (): Promise<void> => {
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
  };

  async function mount(api: MediaStudioApi): Promise<void> {
    await act(async () => {
      root.render(<Gaze videoId="v1" api={api} />);
    });
    await flush();
  }

  function pick(selector: string, value: string): void {
    const el = container.querySelector(selector) as HTMLInputElement;
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
    act(() => {
      setter.call(el, value);
      el.dispatchEvent(new Event('input', { bubbles: true }));
    });
  }

  function attest(): void {
    const box = container.querySelector('[data-input="likeness-attest"]') as HTMLInputElement;
    act(() => {
      box.click();
    });
  }

  const runButton = (): HTMLButtonElement =>
    container.querySelector('[data-action="run"]') as HTMLButtonElement;

  async function clickRun(): Promise<void> {
    await act(async () => {
      runButton().click();
      await Promise.resolve();
    });
    await flush();
  }

  /** Fill in a complete, attested request (the only state that can dispatch). */
  function fillAttested(subject = 'Marius (self)'): void {
    pick('[data-input="likeness-subject"]', subject);
    attest();
  }

  it('probes availability on mount', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    expect(fake.calls.some((c) => c.method === 'gaze.probe')).toBe(true);
  });

  // MUTATION NOTE — both availability tests below FILL IN a complete, attested
  // request before asserting `disabled`. The first drafts did not, and a mutation
  // (`setAvailable(false)` -> `setAvailable(true)` in the probe's catch) SURVIVED:
  // the button was disabled because nothing was attested, so the assertion never
  // measured availability at all. With the gate satisfied, availability is the only
  // remaining reason the button can be disabled, and the mutant dies.
  it('disables the control with a NAMED reason when the YuNet asset is missing', async () => {
    const fake = makeFakeApi({ available: false });
    await mount(fake.api);
    fillAttested();
    expect(runButton().disabled).toBe(true);
    const reason = container.querySelector('[data-section="unavailable"]');
    // The asset id is the actionable part of the sidecar's own UNAVAILABLE_MESSAGE
    // (`gaze.py` UNAVAILABLE_MESSAGE) — a bare "unavailable" is not actionable.
    expect(reason?.textContent).toContain('yunet-face-detection');
  });

  it('fails CLOSED when the probe itself throws', async () => {
    const fake = makeFakeApi({ probeError: new Error('sidecar down') });
    await mount(fake.api);
    fillAttested();
    expect(runButton().disabled).toBe(true);
    expect(container.querySelector('[data-section="unavailable"]')?.textContent).toContain(
      'sidecar down',
    );
  });

  it('keeps the run button disabled until BOTH a subject and an attestation exist', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    // available, but nothing attested yet
    expect(runButton().disabled).toBe(true);
    pick('[data-input="likeness-subject"]', 'Marius (self)');
    expect(runButton().disabled).toBe(true);
    attest();
    expect(runButton().disabled).toBe(false);
  });

  it('a whitespace-only subject does not satisfy the gate', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    pick('[data-input="likeness-subject"]', '   ');
    attest();
    expect(runButton().disabled).toBe(true);
  });

  it('sends gaze.run with the attested params and the chosen strength', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    fillAttested();
    pick('[data-input="strength"]', '0.4');
    await clickRun();
    expect(fake.calls.find((c) => c.method === 'gaze.run')?.params).toEqual({
      videoId: 'v1',
      likenessSubject: 'Marius (self)',
      likenessAttested: true,
      strength: 0.4,
    });
  });

  it('defaults the strength to the sidecar default', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    fillAttested();
    await clickRun();
    expect(fake.calls.find((c) => c.method === 'gaze.run')?.params?.strength).toBe(
      DEFAULT_GAZE_STRENGTH,
    );
  });

  it('streams progress for its own job and ignores another job', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    fillAttested();
    await act(async () => {
      runButton().click();
    });
    await act(async () => {
      fake.fireProgress({ jobId: 'job-g', pct: 55, message: 'warping eyes' });
      await Promise.resolve();
    });
    expect(container.querySelector('.progress-pct')?.textContent).toContain('55');
    expect(container.querySelector('.progress-message')?.textContent).toContain('warping eyes');
    await act(async () => {
      fake.fireProgress({ jobId: 'not-mine', pct: 99, message: 'other' });
      await Promise.resolve();
    });
    expect(container.querySelector('.progress-pct')?.textContent).not.toContain('99');
  });

  it('renders the output path, the honest tally AND the likeness audit trail', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    fillAttested();
    await act(async () => {
      runButton().click();
    });
    await act(async () => {
      fake.fireDone({
        jobId: 'job-g',
        result: { path: '/out/gaze/clip.gaze.mp4', strength: 0.7, report: REPORT, likeness: AUDIT },
      });
      await Promise.resolve();
    });
    await flush();
    expect(container.querySelector('[data-section="result"]')?.textContent).toContain(
      '/out/gaze/clip.gaze.mp4',
    );
    const report = container.querySelector('[data-section="report"]');
    expect(report?.textContent).toContain('288');
    expect(report?.textContent).toContain('300');
    // A skip is NOT a failure, but it must be visible — the engine leaves frames
    // pristine on purpose (gaze.py skip_reason) and hiding that would overstate
    // what the run did.
    expect(report?.textContent).toContain('low-confidence');
    const audit = container.querySelector('[data-section="audit"]');
    expect(audit?.textContent).toContain('Marius (self)');
    expect(audit?.textContent).toContain('request');
  });

  it('says so LOUDLY when a "successful" run corrected nothing', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    fillAttested();
    await act(async () => {
      runButton().click();
    });
    await act(async () => {
      fake.fireDone({
        jobId: 'job-g',
        result: {
          path: '/out/gaze/clip.gaze.mp4',
          strength: 0.7,
          report: {
            framesTotal: 300,
            framesCorrected: 0,
            eyesCorrected: 0,
            skipped: { 'eyes-too-small': 300 },
          },
          likeness: AUDIT,
        },
      });
      await Promise.resolve();
    });
    await flush();
    expect(container.querySelector('[data-section="nothing-corrected"]')).not.toBeNull();
  });

  it('surfaces the sidecar likeness refusal as an alert, never a silent no-op', async () => {
    const refusal = new Error(
      "gaze likeness alteration for subject 'Ana' refused: no attestation.",
    );
    const fake = makeFakeApi({ runError: refusal });
    await mount(fake.api);
    fillAttested('Ana');
    await clickRun();
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('no attestation');
  });

  it('surfaces a non-Error rejection as a string', async () => {
    const api: MediaStudioApi = {
      rpc: vi.fn(async (method: string) => {
        if (method === 'gaze.probe') return { available: true };
        throw 'plain string boom';
      }) as unknown as MediaStudioApi['rpc'],
      onProgress: () => () => {},
      onJobDone: () => () => {},
    };
    await mount(api);
    fillAttested();
    await clickRun();
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('plain string boom');
  });

  it('CLEARS the attestation after a successful run so one tick cannot authorise a second subject', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    fillAttested();
    await act(async () => {
      runButton().click();
    });
    await act(async () => {
      fake.fireDone({
        jobId: 'job-g',
        result: { path: '/out/gaze/clip.gaze.mp4', strength: 0.7, report: REPORT, likeness: AUDIT },
      });
      await Promise.resolve();
    });
    await flush();
    const box = container.querySelector('[data-input="likeness-attest"]') as HTMLInputElement;
    expect(box.checked).toBe(false);
    expect(runButton().disabled).toBe(true);
  });

  it('KEEPS the attestation after a failed run so a retry need not re-attest', async () => {
    const fake = makeFakeApi({ runError: new Error('ffmpeg exploded') });
    await mount(fake.api);
    fillAttested();
    await clickRun();
    const box = container.querySelector('[data-input="likeness-attest"]') as HTMLInputElement;
    expect(box.checked).toBe(true);
  });

  // ─── the SECOND half of "one tick, one subject" (W02 class) ────────────────
  // REFUTED IN REVIEW, and the refutation was correct: the first draft invalidated
  // the tick ONLY on a successful run, so a tick made while the field read 'Ana'
  // still satisfied `canRun` after the field was changed to 'Bogdan' — and
  // `likeness.py:156-157` stamps whatever subject arrives into the job's audit
  // trail, so the record would assert Bogdan was attested when the user never read
  // the sentence against Bogdan. The panel's own hint claims the tick "can never
  // authorise … a different person"; these three tests are what make that true.
  const attestBox = (): HTMLInputElement =>
    container.querySelector('[data-input="likeness-attest"]') as HTMLInputElement;

  it('CLEARS the attestation when the subject is RENAMED — one tick never covers a second person', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    fillAttested('Ana');
    expect(runButton().disabled).toBe(false);
    pick('[data-input="likeness-subject"]', 'Bogdan');
    expect(attestBox().checked).toBe(false);
    expect(runButton().disabled).toBe(true);
  });

  it('clears it on a rename AFTER a failed run too — the retry path keeps the tick only for the SAME person', async () => {
    const fake = makeFakeApi({ runError: new Error('ffmpeg exploded') });
    await mount(fake.api);
    fillAttested('Ana');
    await clickRun();
    expect(attestBox().checked).toBe(true); // same person, retry is fine
    pick('[data-input="likeness-subject"]', 'Bogdan');
    expect(attestBox().checked).toBe(false); // different person, re-attest
    expect(runButton().disabled).toBe(true);
  });

  it('a whitespace-only edit is NOT a new subject, so the tick survives', async () => {
    // `buildGazeParams` trims, so 'Ana' -> 'Ana ' sends the IDENTICAL subject.
    // Clearing there would be consent theatre — a re-tick that changes nothing.
    const fake = makeFakeApi();
    await mount(fake.api);
    fillAttested('Ana');
    pick('[data-input="likeness-subject"]', 'Ana ');
    expect(attestBox().checked).toBe(true);
    expect(runButton().disabled).toBe(false);
  });

  // ─── the THIRD carryover door: the VIDEO changes under a ticked box ────────
  // A fresh skeptic found this AFTER the rename fix above and its three refuters
  // all missed it: nothing was keyed to `videoId`, so re-rendering this panel in
  // place with a new video kept `attested` AND `subject`. Measured on the wire
  // before the fix: `{"videoId":"videoB","likenessSubject":"Ana","strength":0.7,
  // "likenessAttested":true}` — a tick taken against video A authorising face
  // alteration of video B, which `likeness.py:156-157` then stamps into the job
  // audit trail via `gaze.py:668-672` as if the operator had given it.
  //
  // The swap is REACHABLE, not a thought experiment: nothing on the App -> Edit ->
  // Workspace -> Gaze chain is keyed (`App.tsx:481-482`, `Edit.tsx:155-156`,
  // `Workspace.tsx:388-393`), and `App.tsx:332-353`'s launch-restore effect has
  // `[]` deps, no route guard, and calls `setEditVideo(match)` + `setRoute` after
  // two RPC awaits — so a video opened and ticked before those resolve is swapped
  // IN PLACE. `origin/main`'s `4408e033` is a merged fix for this exact structural
  // pattern in an unkeyed sibling panel, so the repo already treats it as live.

  /**
   * Re-render IN PLACE with a new videoId — the SAME component type at the SAME
   * position, so React updates it rather than remounting. Every test below then
   * asserts `strength` as its DETECTOR CONTROL: strength is deliberately NOT
   * reset, so a value back at the 0.70 default would mean the panel remounted and
   * the consent assertions were measuring a fresh mount instead of a prop swap.
   */
  async function swapVideo(api: MediaStudioApi, videoId: string): Promise<void> {
    await act(async () => {
      root.render(<Gaze videoId={videoId} api={api} />);
    });
    await flush();
  }

  const subjectInput = (): HTMLInputElement =>
    container.querySelector('[data-input="likeness-subject"]') as HTMLInputElement;

  // THE WIRE ASSERTION FIRST — it is the falsifiable one, and asserting on the
  // recorded params (not `some(...)`) makes the pre-fix failure print the leaked
  // payload verbatim instead of a bare `true !== false`.
  it('the WIRE carries no attestation for a video the tick was never read against', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    fillAttested('Ana');
    pick('[data-input="strength"]', '0.4');
    expect(runButton().disabled).toBe(false);

    await swapVideo(fake.api, 'videoB');

    // DETECTOR CONTROL: this was an in-place prop swap, not a remount.
    expect(container.querySelector('.gaze-strength-value')?.textContent).toBe('0.40');
    // No request can be dispatched at all, so none can carry `likenessAttested`
    // for a video whose face the sentence was never read against.
    await clickRun();
    expect(fake.calls.filter((c) => c.method === 'gaze.run').map((c) => c.params)).toEqual([]);
  });

  it('CLEARS the tick AND the subject label when the VIDEO changes under them', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    fillAttested('Ana');
    pick('[data-input="strength"]', '0.4');
    await swapVideo(fake.api, 'videoB');

    expect(container.querySelector('.gaze-strength-value')?.textContent).toBe('0.40'); // control
    // The label goes too: a new video is a new person question, and a prefilled
    // 'Ana' under a new face invites the wrong answer to it.
    expect(attestBox().checked).toBe(false);
    expect(subjectInput().value).toBe('');
    expect(runButton().disabled).toBe(true);
  });

  it('a fresh tick after a video change attests the NEW video, and the wire says so', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    fillAttested('Ana');
    await swapVideo(fake.api, 'videoB');
    fillAttested('Bogdan');
    await clickRun();
    expect(fake.calls.find((c) => c.method === 'gaze.run')?.params).toEqual({
      videoId: 'videoB',
      likenessSubject: 'Bogdan',
      likenessAttested: true,
      strength: DEFAULT_GAZE_STRENGTH,
    });
  });

  it('drops the finished result AND its likeness audit trail when the video changes', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    fillAttested('Ana');
    await act(async () => {
      runButton().click();
    });
    await act(async () => {
      fake.fireDone({
        jobId: 'job-g',
        result: { path: '/out/gaze/videoA.mp4', strength: 0.7, report: REPORT, likeness: AUDIT },
      });
      await Promise.resolve();
    });
    await flush();
    expect(container.querySelector('[data-section="audit"]')).not.toBeNull(); // control
    await swapVideo(fake.api, 'videoB');
    // Video A's "Authorised by: Marius (self)" must not stand under video B: the
    // audit block is a consent RECORD, and showing it here is a false attribution.
    expect(container.querySelector('[data-section="result"]')).toBeNull();
    expect(container.querySelector('[data-section="audit"]')).toBeNull();
  });

  it('drops the previous video failure banner when the video changes', async () => {
    const fake = makeFakeApi({ runError: new Error('ffmpeg exploded') });
    await mount(fake.api);
    fillAttested('Ana');
    await clickRun();
    expect(container.querySelector('[role="alert"]')).not.toBeNull(); // control
    await swapVideo(fake.api, 'videoB');
    expect(container.querySelector('[role="alert"]')).toBeNull();
  });

  // The over-reset control. `gaze.probe` takes NO videoId — the yunet asset is
  // installed or not, per machine — so a video change must neither re-probe nor
  // re-disable the control. Without this, "reset on videoId" could quietly become
  // "reset everything", and the panel would flicker back to unavailable.
  it('does NOT re-probe or re-disable availability on a video change', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    await swapVideo(fake.api, 'videoB');
    expect(fake.calls.filter((c) => c.method === 'gaze.probe')).toHaveLength(1);
    expect(container.querySelector('[data-section="unavailable"]')).toBeNull();
    fillAttested('Bogdan');
    expect(runButton().disabled).toBe(false);
  });

  // ─── the SAME defect through the in-flight door ────────────────────────────
  // The reset effect runs on the switch; a job that was ALREADY in flight settles
  // AFTER it, so without an ownership guard the old video's write lands anyway —
  // the exact hole `4408e033` describes for the sibling panel. Scoped honestly:
  // the request itself carried A's videoId and a valid attestation for A, so this
  // is a false ATTRIBUTION of A's consent record onto B's panel, not a forged
  // consent on the wire.
  it('drops a late job.done from the PREVIOUS video instead of stamping its audit under the new one', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    fillAttested('Ana');
    await act(async () => {
      runButton().click();
    });
    await swapVideo(fake.api, 'videoB');
    await act(async () => {
      fake.fireDone({
        jobId: 'job-g',
        result: { path: '/out/gaze/videoA.mp4', strength: 0.7, report: REPORT, likeness: AUDIT },
      });
      await Promise.resolve();
    });
    await flush();
    expect(container.querySelector('[data-section="result"]')).toBeNull();
    expect(container.querySelector('[data-section="audit"]')).toBeNull();
    // The lane is still freed, so the new video is not left permanently busy.
    expect(container.querySelector('.progress')).toBeNull();
  });

  it('surfaces a job.done ERROR payload as an alert (the no-switch control arm)', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    fillAttested('Ana');
    await act(async () => {
      runButton().click();
    });
    await act(async () => {
      fake.fireDone({
        jobId: 'job-g',
        result: { error: { message: 'gaze backend died', type: 'GazeError' } },
      });
      await Promise.resolve();
    });
    await flush();
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('gaze backend died');
  });

  it('drops a late FAILURE from the previous video instead of blaming the new one', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    fillAttested('Ana');
    await act(async () => {
      runButton().click();
    });
    await swapVideo(fake.api, 'videoB');
    await act(async () => {
      fake.fireDone({
        jobId: 'job-g',
        result: { error: { message: 'gaze backend died', type: 'GazeError' } },
      });
      await Promise.resolve();
    });
    await flush();
    expect(container.querySelector('[role="alert"]')).toBeNull();
  });

  // The copy the user reads BEFORE ticking is the strongest claim this panel
  // makes, so it is pinned to what the code actually guarantees — including the
  // deliberate carve-out (a FAILED run keeps the tick) that the previous absolute
  // wording hid. Each clause here has a behavioural test above or beside it.
  it('the consent hint names every trigger that really clears the tick, and the retry carve-out', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    const hint = container.querySelector('.gaze-consent-hint')?.textContent ?? '';
    expect(hint).toMatch(/finished run/i); // cleared on success
    expect(hint).toMatch(/name above/i); // cleared on rename
    expect(hint).toMatch(/different video/i); // cleared on a videoId change
    expect(hint).toMatch(/failed run/i); // …and NOT cleared on failure
  });

  it('cancels the in-flight job via job.cancel', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    fillAttested();
    await act(async () => {
      runButton().click();
    });
    await act(async () => {
      (container.querySelector('[data-action="cancel"]') as HTMLButtonElement).click();
      await Promise.resolve();
    });
    expect(fake.calls.some((c) => c.method === 'job.cancel')).toBe(true);
  });

  it('keeps the panel usable when job.cancel itself fails', async () => {
    let doneCbs: Array<(ev: DoneEvent) => void> = [];
    const api: MediaStudioApi = {
      rpc: vi.fn(async <T,>(method: string) => {
        if (method === 'gaze.probe') return { available: true } as T;
        if (method === 'job.cancel') throw new Error('cancel failed');
        return { jobId: 'job-g' } as T;
      }) as MediaStudioApi['rpc'],
      onProgress: () => () => {},
      onJobDone: (cb) => {
        doneCbs.push(cb);
        return () => {
          doneCbs = doneCbs.filter((c) => c !== cb);
        };
      },
    };
    await mount(api);
    fillAttested();
    await act(async () => {
      runButton().click();
    });
    await act(async () => {
      (container.querySelector('[data-action="cancel"]') as HTMLButtonElement).click();
      await Promise.resolve();
    });
    expect(container.querySelector('[role="alert"]')).toBeNull();
  });

  it('does not hang when the bridge exposes no job.done channel', async () => {
    const api: MediaStudioApi = {
      rpc: vi.fn(async (method: string) =>
        method === 'gaze.probe' ? { available: true } : { jobId: 'job-g' },
      ) as unknown as MediaStudioApi['rpc'],
      onProgress: () => () => {},
    };
    await mount(api);
    fillAttested();
    await clickRun();
    expect(container.querySelector('[data-section="result"]')).toBeNull();
    expect(container.querySelector('[role="alert"]')).toBeNull();
  });

  it('renders nothing when the rpc returns no jobId', async () => {
    const api: MediaStudioApi = {
      rpc: vi.fn(async (method: string) =>
        method === 'gaze.probe' ? { available: true } : {},
      ) as unknown as MediaStudioApi['rpc'],
      onProgress: () => () => {},
      onJobDone: () => () => {},
    };
    await mount(api);
    fillAttested();
    await clickRun();
    expect(container.querySelector('[data-section="result"]')).toBeNull();
  });

  it('settles cleanly on a job.done with no result field and on an unusable one', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    fillAttested();
    await act(async () => {
      runButton().click();
    });
    await act(async () => {
      fake.fireDone({ jobId: 'job-g' });
      await Promise.resolve();
    });
    await flush();
    expect(container.querySelector('[data-section="result"]')).toBeNull();
    expect(container.querySelector('[role="alert"]')).toBeNull();
  });

  // ─── AI disclosure parity with the lip-sync sibling (refuted in review) ────
  // The lane reasoned this interaction through for W20 and skipped it here; a
  // gaze-corrected clip is the same category of artifact (real irises warped, and
  // `gaze_backend.py:200-219` writes no `-metadata` either), so it is owed the same
  // disclosure. Asserted on the SHARED constant, not a restated string, so the two
  // panels cannot drift apart.
  it('discloses that the output is edited media carrying no embedded provenance', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    const note = container.querySelector('[data-section="ai-disclosure"]');
    expect(note?.textContent).toMatch(/re-drawn|edited media/i);
    expect(note?.textContent).toContain('C2PA');
    expect(note?.textContent).toContain('not available');
  });

  it('reports C2PA as available if a signing identity ever lands (the other state)', async () => {
    // The shipped constant is a hardcoded `available: false`, so without this seam
    // the "available" wording could never be exercised.
    const fake = makeFakeApi();
    await act(async () => {
      root.render(<Gaze videoId="v1" api={fake.api} c2pa={{ available: true, reason: '' }} />);
    });
    await flush();
    expect(container.querySelector('[data-section="ai-disclosure"]')?.textContent).toContain(
      'Available',
    );
  });

  it('falls back to the global window.api bridge when no api prop is given', async () => {
    const fake = makeFakeApi();
    (globalThis as { api?: unknown }).api = fake.api;
    try {
      await act(async () => {
        root.render(<Gaze videoId="v1" />);
      });
      await flush();
      fillAttested();
      await clickRun();
      expect(fake.calls.find((c) => c.method === 'gaze.run')?.params).toMatchObject({
        videoId: 'v1',
        likenessAttested: true,
      });
    } finally {
      delete (globalThis as { api?: unknown }).api;
    }
  });
});
