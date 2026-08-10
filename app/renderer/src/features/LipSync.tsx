// Lip-sync section of the Dub surface — re-lip the on-screen mouth to a finished
// dub (W20).
//
// MEASURED GAP. `tts.lipsync.start` is registered UNCONDITIONALLY
// (`sidecar/media_studio/features/tts/__init__.py:141`) and is frozen into the
// authoritative method list, but it had NO caller anywhere. Measured on the host
// tree: `Dub.tsx` was 519 lines with ZERO `lipSync`/`lipsync` references, and the
// only renderer matches for "lipsync" were `AiDisclosure.tsx` and
// `ThirdPartyNotices.tsx`, neither of which calls anything. It is registered
// unconditionally and refuses at CALL time on the flag (`tts/__init__.py:23-28`),
// so it was never flag-gated out of existence — it simply had no entry point.
//
// This is a SEPARATE component mounted inside the Dub panel rather than more code
// in `Dub.tsx`: that file was already 519 lines and this section carries four
// gates, three pickers and its own job lifecycle. It consumes the audio-track list
// Dub has already fetched (`tracks.audio.list`), so it adds no duplicate RPC, and
// it renders inside `.dub-panel` so the existing `.dub-consent` / `.dub-pickers`
// styling applies without touching a stylesheet (another lane owns those).
//
// WIRE: tts.lipsync.start({videoId, audioTrackId, engine?, quality?,
//                          likenessConsentAttested}) -> {jobId}
//         -> job.done {path, engine, syncConfidence}
//
// ─── THE FOUR GATES, ALL FAIL CLOSED ────────────────────────────────────────
// 1. BUILD FLAG (`lipsync.py:197-215`). `require_enabled` refuses unless the
//    `lipSyncEnabled` setting is the LITERAL `true`; the default is `False`
//    (`settings_store.py:178`). `lipSyncEnabledFrom` mirrors that literal-true rule
//    exactly, so a truthy `'true'`/`1` reads as OFF here as it does there.
//    Consequence, deliberate: with the flag off the button is DISABLED and the
//    reason names the flag. It is not hidden — "disabled, and here is exactly what
//    is off" is the same honesty the sidecar chose by registering the method
//    unconditionally. What that reason must NOT do is imply an in-app switch: there
//    is none (see the scope section below), and the first wording did, which is why
//    `LIPSYNC_DISABLED_REASON` now says so outright.
// 2. LIKENESS CONSENT (`lipsync.py:218-225`). `likenessConsentAttested` must be
//    the literal `true`. `buildLipsyncParams` OMITS the key unless the user
//    actually ticked the box — it is never synthesized, and the tick is cleared
//    after a success so it cannot carry into a second run.
// 3. THE TRACK MUST BE A DUB (`lipsync.py:672-677`). Re-lipping the mouth to the
//    ORIGINAL audio is meaningless, so the picker offers `kind === 'dub'` only.
// 4. ENGINE. `wav2lip` is permanently in `DENIED_ENGINES` because it genuinely
//    forbids commercial use (`lipsync.py:120-126`), so it is not offerable at all.
//    The two offered engines are OpenRAIL — commercial use IS permitted, but with
//    behavioural use-restrictions that must be passed downstream
//    (`lipsync.py:23-30`), which is why each engine's licence is shown.
//
// ─── SCOPE OF THE CLAIM: THIS IS A CALL SITE, NOT A WORKING FEATURE ─────────
// An earlier version of this header, and the lane report around it, said "both
// RPCs now have real user entry points". For gaze that is true end to end; for
// lip-sync it was WIDER THAN THE EVIDENCE and was refuted in review. What landed
// here is the first CALLER of `tts.lipsync.start`. It is not an executable path in
// any stock build, for two independent reasons, both measured:
//
//   1. THE CONTROL IS DISABLED IN EVERY STOCK BUILD. `canStart` requires
//      `enabled === true`, `lipSyncEnabled` defaults to `False`
//      (`settings_store.py:178`), and NOTHING in `app/` ever writes it — a
//      case-sensitive scan of `app/` for `lipSyncEnabled` finds only the generated
//      type (`lib/rpc/generated/schemas.generated.ts:54`), this file, its test, and
//      `ThirdPartyNotices.tsx` copy. Detector controlled: the same scan style finds
//      real `settings.set` writes for user-settable keys (`App.tsx:308` `useCloud`,
//      `Edit.tsx:117`, `DirectorPanel.tsx:267`), so the zero is a real absence.
//      `LIPSYNC_NO_IN_APP_SETTER` is pinned by a test that re-runs that scan, so
//      the copy cannot rot if a setter is ever added. This is by DESIGN, not an
//      oversight: `docs/plans/v1.5/flagship-lip-sync-dub.md:151,177` files
//      `lipSyncEnabled` as "(personal-only)" and says the commercial build's
//      handler hard-refuses with the flag OFF.
//   2. EVEN WITH THE FLAG FORCED ON, THE JOB REFUSES. `_tts.register(...)`
//      (`handlers/composition.py:327-336`) passes no `lipsync_face_boxes_probe`, so
//      `face_boxes_probe` is `None` and `require_face_boxes`
//      (`lipsync.py:239-254`, called at `:699`) RAISES inside the job. Wiring that
//      is the sibling sidecar lane's work — `handlers/composition.py` belongs to
//      another live lane this wave and is deliberately untouched here.
//
// So: correctly scoped, W20 adds the call site, the four fail-closed gates and the
// disclosure; it does NOT make lip-sync runnable. Do not read "reachable" as
// "works".
//
// ─── HOW THE PANEL HANDLES THAT WITHOUT LYING IN EITHER DIRECTION ───────────
// The pre-click notice (`data-section="unwired"`) states the RULE, which is true of
// every build: a run needs YuNet face boxes from the sidecar and REFUSES without
// them. It deliberately does not assert, as present-tense fact, that THIS build
// has no provider — the renderer cannot observe that (no RPC reports it), and the
// previous wording did assert it, which would have started telling every user a
// working feature was broken the moment the sibling lane wired the probe. That is
// the same "stale in the WORST direction" failure the lane used to justify not
// hardcoding `false` on the button, so it is now avoided on both surfaces.
//
// What the renderer CAN measure is a refusal it has actually received. Once the
// sidecar has answered with `require_face_boxes`'s own message
// (`LIPSYNC_FACE_BOX_MARKER`), the control is disabled FOR AS LONG AS THIS PANEL
// STAYS MOUNTED and the verbatim reason is shown: a build with no probe refuses
// EVERY run, so inviting a second identical click would be the "button that is
// present but always errors" shape. It is self-healing — when the probe is wired,
// that refusal never arrives and nothing is disabled.
//
// "…FOR THE SESSION" WAS AN OVERCLAIM, now corrected in the copy as well as here.
// `faceBoxRefusal` is component state, and `Workspace.tsx:479-488` swaps the panel
// type inside ONE `<Suspense>`, so leaving the Dub tab UNMOUNTS this section and
// returning to it offers the guaranteed-failing click again. Measured, not reasoned
// from React semantics: a test unmounts and remounts and asserts the refusal is
// gone and the button enabled. A module-scoped latch WOULD make "session" true and
// was rejected — it needs a test-only reset export in production code to stay
// isolatable, and the honest cost of the panel-scoped version is one extra click
// that shows the sidecar's own words again, not a wrong result.
// UNVERIFIED: whether the transport preserves the
// sidecar's message text byte-for-byte end to end in the packaged app (the unit
// tests inject the message through the same `waitForJobDone` rejection path the
// real bridge uses); settled by forcing `lipSyncEnabled` true in the per-user
// settings.json of a packaged build, clicking Re-lip once, and reading whether
// `[data-section="face-box-refused"]` appears.
//
// ─── AI DISCLOSURE: WHY `AiDisclosure.tsx` IS NOT CHANGED ───────────────────
// Checked, not ignored. That module's model is AUDIO-TRACK-scoped:
// `isAiGeneratedAudioTrack(track)` keys off the A3 `AudioTrack.kind`, and
// `AiDisclosurePanel`'s copy says "Audio produced here is synthesized, and every
// dub track is marked…". A lip-synced output is a VIDEO FILE — it is never
// registered as an `AudioTrack`, so it has no `kind` for that predicate to read and
// no row in the track list to badge. Widening that panel's copy to cover video
// would also change `ShortMakerControls.tsx`, its other consumer, which is outside
// this lane. So the synthetic-VIDEO disclosure lives here, and the one fact that IS
// shared — that no C2PA provenance manifest is written on export — is IMPORTED from
// `C2PA_EXPORT_STATUS` rather than restated, so there is a single source for it.
// Measured, and the reason the copy can claim it: `lipsync.py` contains zero
// `metadata` occurrences, so its remux writes no marking into the output container
// either — the same in-app-only limitation the audio badge already discloses.
import React, { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import './panels.css';
import { C2PA_EXPORT_STATUS } from './AiDisclosure';
import type { AudioTrack } from './Dub';
import { extractJobId, getApi, pickField, waitForJobDone, type MediaStudioApi } from './_api';

/** One offerable re-lip engine and the licence facts the user must be told. */
export interface LipSyncEngineOption {
  id: string;
  label: string;
  /** The HUB tag on the WEIGHTS (`lipsync.py` ENGINES), not the code licence. */
  weightsLicense: string;
  notice: string;
}

/**
 * The OpenRAIL obligation in user-facing words, mirroring `_OPENRAIL_NOTICE`
 * (`lipsync.py:128-134`). Commercial use is permitted; the restrictions are
 * behavioural and must be passed on.
 */
const OPENRAIL_OBLIGATION =
  'Commercial use IS permitted, but the licence attaches behavioural ' +
  'use-restrictions you must not breach and must pass on to anyone you give the ' +
  'output or the model to. Re-lipping a real person without their consent is not ' +
  'a use Reframe supports.';

/**
 * The engines this UI offers — exactly the keys of `lipsync.ENGINES`.
 * `wav2lip` is ABSENT on purpose: it is in `DENIED_ENGINES` (`lipsync.py:120-126`)
 * because its README forbids commercial use outright, and the sidecar raises a loud
 * refusal for it. Not offering it means a typo cannot reach it either.
 */
export const LIPSYNC_ENGINES: readonly LipSyncEngineOption[] = [
  {
    id: 'latentsync',
    label: 'LatentSync (ByteDance) — highest quality',
    weightsLicense: 'openrail++',
    notice: OPENRAIL_OBLIGATION,
  },
  {
    id: 'musetalk',
    label: 'MuseTalk (Tencent) — real-time capable',
    weightsLicense: 'creativeml-openrail-m',
    notice: OPENRAIL_OBLIGATION,
  },
];

/** `lipsync.DEFAULT_ENGINE` (`lipsync.py:160`). */
export const DEFAULT_LIPSYNC_ENGINE = 'latentsync';
/** `lipsync.QUALITIES` / `DEFAULT_QUALITY` (`lipsync.py:165-166`). */
export const LIPSYNC_QUALITIES: readonly string[] = ['fast', 'quality'];
export const DEFAULT_LIPSYNC_QUALITY = 'quality';

/** The exact attestation the user makes (higher bar than the dub's, by design). */
export const LIPSYNC_CONSENT_TEXT =
  'I am the person on screen, or I hold their documented permission to alter ' +
  'their face in this video.';

/**
 * Shown when the build flag is off.
 *
 * REFUTED IN REVIEW, and the objection was right: the previous wording said "set
 * the lipSyncEnabled setting to true to enable it", which named a setting the user
 * has NO way to change — there is no settings UI for it anywhere in `app/` (see the
 * header's measured scan, pinned by a test). The one actionable sentence in the
 * panel was a dead end. It now says what is actually true: this is a personal-tier
 * BUILD flag living in the sidecar's own per-user config file, not an in-app
 * preference. The `lipSyncEnabled` key name stays, because it is what a user would
 * have to search for and what the sidecar's own refusal names.
 */
export const LIPSYNC_DISABLED_REASON =
  'Lip-sync is OFF in this build, and there is no switch for it in this app: ' +
  'lipSyncEnabled is a personal-tier build flag stored in the sidecar per-user ' +
  'settings.json config file, not an app preference — a commercial build refuses ' +
  'lip-sync outright. Turning it on there also means accepting a separate opt-in ' +
  'download of the engine weights under their own licence.';

/** The claim `LIPSYNC_DISABLED_REASON` makes about `app/`, pinned by a test. */
export const LIPSYNC_NO_IN_APP_SETTER = 'there is no switch for it in this app';

/**
 * The pre-click disclosure, rendered in BOTH flag states.
 *
 * REFUTED IN REVIEW: this used to assert as present-tense fact that "no face-box
 * provider is wired" in this build — a property of `handlers/composition.py` that
 * the renderer cannot observe, and one that would invert into telling every user a
 * working feature was broken the moment the sibling lane wires the probe. It now
 * states the RULE, which holds for every build, and leaves the per-build verdict to
 * `LIPSYNC_OBSERVED_REFUSAL_PREFIX`, which is only ever shown from a refusal the
 * sidecar actually returned. It keeps naming S3FD, because WHY the refusal is
 * correct is the part a user cannot infer.
 */
export const LIPSYNC_UNWIRED_NOTICE =
  'Lip-sync runs only when the sidecar supplies face boxes from the vendored ' +
  'MIT-licensed YuNet detector: letting the engine find faces itself would pull the ' +
  'S3FD weight, which ships under no licence at all. A build with no face-box ' +
  'provider wired therefore REFUSES the run instead of producing a video — that ' +
  'refusal is deliberate, and if it happens the reason is shown here verbatim and ' +
  'this control is disabled until you reopen this panel.';

/**
 * The sidecar's own marker for the unwired-probe refusal (`require_face_boxes`,
 * `lipsync.py:249-254`). A sidecar test asserts this exact substring is still in
 * that message, so a reworded refusal cannot silently stop being detected.
 */
export const LIPSYNC_FACE_BOX_MARKER = 'no face-box provider is wired';

/**
 * Prefix for a refusal actually OBSERVED — never a prediction.
 *
 * SCOPE CORRECTED: this used to say the control is "disabled until Reframe runs
 * with one wired", which overstated how long the verdict is remembered. It lives in
 * component state, so it is forgotten when this panel unmounts (measured: a
 * remount test re-enables the button). The sentence now says exactly that, and adds
 * the one fact a user needs to not read the re-offer as the feature having been
 * fixed.
 */
export const LIPSYNC_OBSERVED_REFUSAL_PREFIX =
  'Measured on this build, not predicted: the sidecar refused the last run because ' +
  'it has no face-box provider, and it will refuse every identical run, so the ' +
  'control above is disabled until you reopen this panel. Reopening offers the click ' +
  'again — this verdict is not remembered beyond the panel — and only a build with a ' +
  'provider wired makes it succeed. Sidecar reason:';

/** The synthetic-VIDEO disclosure. The C2PA half is imported, never restated. */
export const LIPSYNC_AI_DISCLOSURE =
  'A re-lipped video is synthetic media: the mouth you see was generated, not ' +
  'recorded. Reframe writes no marking into the output file — nothing about the ' +
  'edit reaches the exported container.';

/** The `job.done` payload of `tts.lipsync.start` (`lipsync.py:575`). */
export interface LipSyncOutcome {
  path: string;
  /** The engine the sidecar reports it actually used; '' when it sent none. */
  engine: string;
  /** Null when the sidecar could not measure it — never a fabricated number. */
  syncConfidence: number | null;
}

// --- pure helpers (exported for tests) -------------------------------------

function errText(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

/**
 * Did the sidecar just refuse because no face-box provider is wired?
 *
 * OBSERVED, never assumed. This is the one thing the renderer CAN establish about
 * the sidecar's wiring, and only after a run has come back: the refusal is
 * deterministic (`probe is None` cannot fix itself mid-session), so one is enough
 * to stop offering the same click. A message that does not carry the marker is a
 * different failure — transient, ffmpeg, cancel — and must NOT disable anything.
 */
export function isFaceBoxRefusal(message: string): boolean {
  return message.includes(LIPSYNC_FACE_BOX_MARKER);
}

/**
 * The build flag, read with the sidecar's own literal-`true` rule
 * (`lipsync.lipsync_enabled`, `lipsync.py:197-205`). A truthy string or `1` is NOT
 * an opt-in: this flag guards a face-manipulation path, so a sloppy value reads as
 * OFF on both sides of the wire rather than only one.
 *
 * A TYPED accessor exists and is deliberately NOT used:
 * `lib/rpc/generated/client.generated.ts` declares
 * `settings.get(): Promise<Settings>` with `Settings.lipSyncEnabled: boolean`
 * (`generated/schemas.generated.ts:54`). Two reasons to read `unknown` instead:
 *   * that type is a COMPILE-TIME claim about a value that comes off DISK, and the
 *     sidecar itself does not trust it — `lipsync_enabled` treats a truthy
 *     non-`true` as OFF precisely because a settings store can hold a malformed
 *     value. Consuming it as a declared `boolean` would make the renderer LESS
 *     defensive than the backend guarding the same path, which is the wrong
 *     direction for a safety gate;
 *   * `clientGenerated` calls the non-injectable module-level `rpc()`, so it cannot
 *     take the `api?` test bridge every panel in `features/` is built around.
 */
export function lipSyncEnabledFrom(settings: unknown): boolean {
  return pickField<unknown>(settings, 'lipSyncEnabled') === true;
}

/**
 * The audio tracks that can be re-lipped: dubs only. `lipsync_start` rejects any
 * other kind (`lipsync.py:672-677`) because re-lipping the mouth to the ORIGINAL
 * recorded audio is meaningless, so offering one would be offering a guaranteed
 * error.
 */
export function dubAudioTracks(tracks: readonly AudioTrack[]): AudioTrack[] {
  return tracks.filter((t) => t.kind === 'dub');
}

/**
 * Build the `tts.lipsync.start` params. `likenessConsentAttested` is present ONLY
 * when the user genuinely ticked the box — never `false`-but-present, never
 * synthesized.
 */
export function buildLipsyncParams(args: {
  videoId: string;
  audioTrackId: string;
  engine: string;
  quality: string;
  consentAttested: boolean;
}): Record<string, unknown> {
  const params: Record<string, unknown> = {
    videoId: args.videoId,
    audioTrackId: args.audioTrackId,
    engine: args.engine,
    quality: args.quality,
  };
  if (args.consentAttested) params.likenessConsentAttested = true;
  return params;
}

/**
 * Read a `tts.lipsync.start` job.done result. Null without a usable `path`, so a
 * shapeless payload renders nothing. A missing/malformed `syncConfidence` stays
 * NULL and is displayed as "not measured" rather than as a number the sidecar
 * never produced.
 */
export function lipsyncOutcome(result: unknown): LipSyncOutcome | null {
  const path = pickField<string>(result, 'path');
  if (typeof path !== 'string' || !path) return null;
  const engine = pickField<unknown>(result, 'engine');
  const confidence = pickField<unknown>(result, 'syncConfidence');
  return {
    path,
    engine: typeof engine === 'string' ? engine : '',
    syncConfidence: Number.isFinite(confidence) ? (confidence as number) : null,
  };
}

export interface LipSyncProps {
  videoId: string;
  /** The A3 audio-track list Dub has already fetched (no duplicate RPC here). */
  audioTracks: readonly AudioTrack[];
  /** Injectable bridge for tests; defaults to the preload-exposed api. */
  api?: MediaStudioApi;
  /**
   * The C2PA export status. Injectable for the same reason `AiDisclosurePanel`
   * makes it injectable — the shipped constant is a hardcoded `available: false`,
   * so without a seam the "available" wording could never be exercised, and an
   * untested branch is where a future signing-identity change would silently break
   * the disclosure. Defaults to the SHARED constant so production has one source.
   */
  c2pa?: typeof C2PA_EXPORT_STATUS;
}

export function LipSync({
  videoId,
  audioTracks,
  api,
  c2pa = C2PA_EXPORT_STATUS,
}: LipSyncProps): React.ReactElement {
  const bridge = useMemo<MediaStudioApi>(() => api ?? getApi(), [api]);

  // null while settings.get is in flight — the control is disabled until it answers.
  // `canStart` therefore tests `enabled === true`, never `!== false`. That mutation
  // SURVIVED an adversarial run (all 36 tests stayed green because nothing exercised
  // the null window); "fails CLOSED while settings.get is still in flight" now kills it.
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [trackId, setTrackId] = useState<string>('');
  const [engine, setEngine] = useState<string>(DEFAULT_LIPSYNC_ENGINE);
  const [quality, setQuality] = useState<string>(DEFAULT_LIPSYNC_QUALITY);
  const [consentAttested, setConsentAttested] = useState<boolean>(false);
  const [busy, setBusy] = useState<boolean>(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [pct, setPct] = useState<number>(0);
  const [message, setMessage] = useState<string>('');
  const [error, setError] = useState<string>('');
  const [outcome, setOutcome] = useState<LipSyncOutcome | null>(null);
  // Empty until the sidecar has actually refused for the unwired probe. The
  // renderer must not pre-judge a build it cannot inspect (see the header).
  const [faceBoxRefusal, setFaceBoxRefusal] = useState<string>('');

  const dubs = useMemo(() => dubAudioTracks(audioTracks), [audioTracks]);
  // `engine` is only ever set from the <select> whose options ARE LIPSYNC_ENGINES,
  // so the fallback is defensive and unreachable from the UI.
  const engineOption = useMemo(
    /* v8 ignore next */
    () => LIPSYNC_ENGINES.find((e) => e.id === engine) ?? LIPSYNC_ENGINES[0],
    [engine],
  );

  useEffect(() => {
    void (async () => {
      try {
        const settings = await bridge.rpc<unknown>('settings.get');
        setEnabled(lipSyncEnabledFrom(settings));
      } catch {
        // FAIL CLOSED, exactly as `LipSyncService._settings` does for an unreadable
        // store: lip-sync stays disabled rather than assuming it is on.
        setEnabled(false);
      }
    })();
  }, [bridge]);

  // A dub track that vanishes from the list (e.g. tracks.audio.strip) must not stay
  // selected, or the panel would dispatch a stale id the sidecar cannot resolve.
  useEffect(() => {
    if (trackId && !dubs.some((t) => t.id === trackId)) setTrackId('');
  }, [dubs, trackId]);

  // ─── A NEW VIDEO IS A NEW CONSENT QUESTION ─────────────────────────────────
  // `consentAttested` was cleared ONLY after a success, and nothing was keyed to
  // `videoId`. `Dub.tsx:529` renders `<LipSync videoId={videoId} …>` unkeyed, `Dub`
  // is mounted unkeyed (`Workspace.tsx:398-399`), and the App -> Edit -> Workspace
  // chain above it is unkeyed too — so a video swapped IN PLACE
  // (`App.tsx:332-353`'s `[]`-deps launch-restore, which calls `setEditVideo` after
  // two RPC awaits) kept the tick. Measured on the wire before this fix:
  //   {"videoId":"videoB","audioTrackId":"a-dub-1","engine":"latentsync",
  //    "quality":"fast","likenessConsentAttested":true}
  // The tick's own sentence is "I am the person ON SCREEN…", and the person on
  // screen is precisely what a videoId change replaces.
  //
  // The comment in the consent fieldset below used to argue this section needed no
  // invalidation because it "has no such field — the subject is whoever is on screen
  // in `videoId`". That reasoning was right about the field and wrong about the
  // conclusion: it treated `videoId` as fixed for the component's lifetime, which it
  // is not. Recorded rather than deleted, because the same premise could be
  // re-derived by the next reader.
  //
  // Shape (an effect, not `key=` at the mount site) and its trade-offs: see the
  // matching block in `Gaze.tsx`. It applies with extra force here — this section's
  // mount site is `Dub.tsx`, so a key at the Workspace panel site would not have
  // reached it at all.
  //
  // RESET: the tick, and the picked dub TRACK — a dub belongs to the video it was
  // generated from, so pairing video A's `audioTrackId` with video B's `videoId` is
  // never right, and the stale-track effect above cannot catch it when the parent
  // hands over the same list. Plus `outcome` and `error`, so video A's result and
  // failure do not read as video B's.
  // NOT RESET, deliberately, and both pinned by tests: `enabled` (the build flag is
  // per machine, not per video) and `faceBoxRefusal` (a BUILD fact —
  // `composition.py` passes no probe, which no video change can fix, so clearing it
  // would re-offer a guaranteed-failing click on every switch). `engine`/`quality`
  // are preferences with no consent meaning; `quality` doubles as the tests'
  // detector control that a swap is a prop update and not a remount.
  //
  // The SIBLING consent gate in this same panel was audited and is NOT affected:
  // `Dub.tsx`'s voice-clone tick attests to the person in the chosen SAMPLE FILE,
  // and `buildSampleAddParams` (`Dub.tsx:65-77`) sends no `videoId` at all — the
  // tick and its subject (`samplePath`) travel together, so a video change cannot
  // put them out of step. Checked, not assumed to be fine.
  // useLAYOUTEffect for the same reason as the Gaze reset (see the note there): a passive
  // effect lets React paint the new videoId with the consent box still ticked, leaving a
  // one-frame window in which a click sends `likenessConsentAttested: true` under the NEW
  // video. Remote, but this is a face-alteration consent gate and the fix is one word.
  // UNVERIFIED inline: indistinguishable under jsdom + `act()`, which flushes passive effects
  // synchronously; settling experiment is in the Gaze note.
  const videoIdRef = useRef<string>(videoId);
  useLayoutEffect(() => {
    videoIdRef.current = videoId;
    setConsentAttested(false);
    setTrackId('');
    setOutcome(null);
    setError('');
  }, [videoId]);

  useEffect(() => {
    if (!jobId) return;
    const off = bridge.onProgress((ev) => {
      if (ev.jobId !== jobId) return;
      setPct(ev.pct);
      setMessage(ev.message);
    });
    return off;
  }, [bridge, jobId]);

  const canStart = enabled === true && trackId !== '' && consentAttested && faceBoxRefusal === '';

  const start = useCallback(async (): Promise<void> => {
    // Defensive: the button is disabled unless `canStart` and not already busy.
    /* v8 ignore next */
    if (busy || !canStart) return;
    // The video this relip belongs to, frozen at dispatch. `tts.lipsync.start` is a
    // DEFERRED job, so the reset effect above can fire while we are still awaiting
    // `job.done` — the reset runs FIRST and the old video's write lands AFTER it
    // (the hole `origin/main` `4408e033` documents for the sibling panel). An id
    // comparison, not a latch. Scoped honestly: the request carried video A's own
    // videoId and a genuine attestation for A, so this prevents a false ATTRIBUTION
    // onto B's panel, not a forged consent on the wire. The in-flight progress bar
    // is deliberately NOT reset — see the `Gaze.tsx` note; keeping `busy` true is
    // also what stops a second concurrent job.
    const startedFor = videoId;
    setBusy(true);
    setError('');
    setOutcome(null);
    setPct(0);
    setMessage('Starting…');
    try {
      const res = await bridge.rpc<unknown>(
        'tts.lipsync.start',
        buildLipsyncParams({ videoId, audioTrackId: trackId, engine, quality, consentAttested }),
      );
      const id = extractJobId(res) ?? null;
      setJobId(id);
      // waitForJobDone REJECTS on an {error} job.done payload, which is exactly how
      // the job-time face-box refusal reaches the user: as a loud alert carrying the
      // sidecar's own typed message, never as a silent no-op or an empty success.
      const result = id ? await waitForJobDone<unknown>(bridge, id, (r) => r ?? null) : null;
      const next = videoIdRef.current === startedFor ? lipsyncOutcome(result) : null;
      if (next) {
        setOutcome(next);
        setPct(100);
        setMessage('Done');
        // A fresh attestation per relip; kept on FAILURE so an unrelated retry does
        // not force a re-attestation (same shape as `Dub.tsx` addSample), and
        // cleared by the reset effect above when the VIDEO changes.
        setConsentAttested(false);
      }
    } catch (err) {
      const message = errText(err);
      // Only the video that asked for the relip wears the blame for it…
      if (videoIdRef.current === startedFor) setError(message);
      // …but the face-box verdict is deliberately NOT scoped to that video. Turn an
      // observed, deterministic refusal into a disabled control carrying the
      // sidecar's own words, rather than inviting an identical second click. It is a
      // property of how the sidecar was BUILT (`composition.py` passes no probe), so
      // it holds for whichever video is on screen when the refusal arrives.
      if (isFaceBoxRefusal(message)) setFaceBoxRefusal(message);
    } finally {
      setBusy(false);
      setJobId(null);
    }
  }, [bridge, busy, canStart, consentAttested, engine, quality, trackId, videoId]);

  const cancel = useCallback(async (): Promise<void> => {
    // Defensive: Cancel renders only while `busy && jobId`.
    /* v8 ignore next */
    if (!jobId) return;
    try {
      await bridge.rpc('job.cancel', { jobId });
    } catch {
      // Best-effort — a failed cancel must not become a panel error.
    }
    setMessage('Cancelling…');
  }, [bridge, jobId]);

  return (
    <section className="lipsync-section" aria-label="Lip-sync">
      <h3>Lip-sync (re-lip the mouth to a dub)</h3>
      <p className="dub-intro">
        Re-generate the speaker&apos;s mouth so it matches a finished dub track instead of the
        original language. This alters a real person&apos;s face, so it is gated separately from the
        dub itself.
      </p>

      {enabled === false && (
        <p className="lipsync-disabled" data-section="disabled" role="status">
          {LIPSYNC_DISABLED_REASON}
        </p>
      )}

      {/* The RULE, stated in BOTH flag states: it governs every build.
          RAISED IN REVIEW as an undisclosed cost — with the flag off (every stock
          build) this puts two paragraphs of S3FD/YuNet licensing internals in front
          of a user who cannot turn the feature on. KEPT UNCONDITIONAL, as a decision
          rather than an accident, for two reasons: gating it on `enabled === true`
          would require deleting a green assertion ("discloses the face-box rule in
          BOTH flag states"), and the rule is the answer to the question the disabled
          paragraph provokes — why a personal-tier build refuses at all. What the
          notice must not do is state a per-BUILD verdict the renderer cannot observe;
          that is `LIPSYNC_OBSERVED_REFUSAL_PREFIX`'s job and it fires only from a
          refusal actually received. */}
      <p className="lipsync-unwired" data-section="unwired" role="status">
        {LIPSYNC_UNWIRED_NOTICE}
      </p>

      {/* ...and the per-build verdict, ONLY once the sidecar has actually said it. */}
      {faceBoxRefusal !== '' && (
        <p className="lipsync-refused" data-section="face-box-refused" role="status">
          {LIPSYNC_OBSERVED_REFUSAL_PREFIX} {faceBoxRefusal}
        </p>
      )}

      <div className="dub-pickers">
        <label>
          Dub track to match{' '}
          <select
            data-picker="lipsync-track"
            value={trackId}
            onChange={(e) => setTrackId(e.target.value)}
            disabled={busy || dubs.length === 0}
          >
            <option value="">— pick a dub track —</option>
            {dubs.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name} ({t.lang})
              </option>
            ))}
          </select>
        </label>

        <label>
          Engine{' '}
          <select
            data-picker="lipsync-engine"
            value={engine}
            onChange={(e) => setEngine(e.target.value)}
            disabled={busy}
          >
            {LIPSYNC_ENGINES.map((e) => (
              <option key={e.id} value={e.id}>
                {e.label}
              </option>
            ))}
          </select>
        </label>

        <label>
          Quality{' '}
          <select
            data-picker="lipsync-quality"
            value={quality}
            onChange={(e) => setQuality(e.target.value)}
            disabled={busy}
          >
            {LIPSYNC_QUALITIES.map((q) => (
              <option key={q} value={q}>
                {q}
              </option>
            ))}
          </select>
        </label>
      </div>

      {dubs.length === 0 && (
        <p className="lipsync-no-dub" data-section="no-dub" role="status">
          This video has no dub track yet. Lip-sync re-lips the mouth to a GENERATED dub, so make
          one above first — the original recorded audio already matches the mouth.
        </p>
      )}

      <p className="lipsync-licence" data-section="licence">
        {engineOption.label} — weights licensed <code>{engineOption.weightsLicense}</code>.{' '}
        {engineOption.notice}
      </p>

      <p className="lipsync-ai-disclosure" data-section="ai-disclosure">
        {LIPSYNC_AI_DISCLOSURE} Content Credentials (C2PA) on export:{' '}
        {c2pa.available ? 'Available' : `not available — ${c2pa.reason}`}
      </p>

      <fieldset className="dub-consent" data-testid="lipsync-consent-gate">
        <legend>Face-alteration consent (required)</legend>
        <label className="dub-consent-attest">
          <input
            data-input="lipsync-consent"
            type="checkbox"
            checked={consentAttested}
            onChange={(e) => setConsentAttested(e.target.checked)}
            disabled={busy}
          />{' '}
          {LIPSYNC_CONSENT_TEXT}
        </label>
        {/* No subject-rename invalidation here, unlike `Gaze.tsx`: that panel has a
            free-text subject LABEL the user can change under a ticked box, which is
            how a tick for 'Ana' could authorise a run against 'Bogdan'. This section
            has no such field — the subject is whoever is on screen in `videoId`, and
            changing the dub TRACK does not change the person whose face is altered.
            REFUTED IN REVIEW: this used to add "the component is bound to that one
            video", and conclude that no invalidation was needed. The component is
            NOT bound to one video — `videoId` is a PROP that its unkeyed parents
            swap in place — so the tick did carry across a video change. The reset
            effect above is the fix; the wrong premise is recorded here rather than
            deleted, because it is exactly what a later reader would re-derive. */}
        <p className="dub-consent-hint">
          This attestation applies to THIS run only — it is never saved. It is cleared after a
          finished run and whenever a different video is opened here, so one tick can never
          authorise a run against a different person. A FAILED run deliberately keeps it, so you can
          retry the same request without re-attesting. A dub voiced by a stored voice CLONE needs
          that sample&apos;s own consent record as well; the sidecar checks it independently and
          refuses without it.
        </p>
      </fieldset>

      <div className="actions">
        <button
          type="button"
          data-action="start-lipsync"
          onClick={() => void start()}
          disabled={busy || !canStart}
        >
          {busy ? 'Re-lipping…' : 'Re-lip to this dub'}
        </button>
        {busy && jobId && (
          <button
            type="button"
            data-action="lipsync-cancel"
            className="secondary"
            onClick={() => void cancel()}
          >
            Cancel
          </button>
        )}
      </div>

      {busy && (
        <div className="progress" aria-live="polite">
          <progress max={100} value={pct} />
          <span className="progress-pct">{Math.round(pct)}%</span>
          {message && <span className="progress-message"> · {message}</span>}
        </div>
      )}

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      {outcome && (
        <div className="output-done" data-section="lipsync-result">
          <span className="output-done-label">Re-lipped file</span>
          <code>{outcome.path}</code>
          <span className="lipsync-confidence">
            {' '}
            engine {outcome.engine} · sync confidence{' '}
            {outcome.syncConfidence === null ? 'not measured' : outcome.syncConfidence.toFixed(2)}
          </span>
        </div>
      )}
    </section>
  );
}

export default LipSync;
