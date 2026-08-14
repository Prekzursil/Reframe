// Edit.tsx — the "Editor" mode of the REFINE destination (per-video editing) +
// the per-video TASK HUB (WU-3a1).
//
// LANDING — L5 G-7 INVARIANT 2, "the timeline is VISIBLE in Refine with ZERO
// navigation actions" (L5-NAVIGATION-DECISIONS.md G-7:214). Opening a video from
// the Library routes here, and here now mounts the Workspace — preview on top,
// timeline DOCKED at the bottom, selection-driven inspector — IMMEDIATELY.
//
// It did not before. `useState<'hub'|'workspace'>('hub')` opened on the Task Hub
// and reached the Workspace only after a card was picked (or when a remembered
// workspace-scoped choice resumed there), so the invariant held from the
// Workspace MOUNT and not from a first open of the destination: one click stood
// between "I opened my video" and "there is a timeline". That was the only one of
// the five locked invariants still failing, and it had no owner — the L5 lane
// deferred it as "Edit.tsx is outside its file scope and byte-unchanged on this
// branch", a premise PR #427 falsified when it adopted the shared EmptyState here
// (App.tsx carries that retraction). This lane owns and closes it.
//
// PROVEN BOTH-STATES, not asserted: checking the pre-branch Edit.tsx over this one
// (`git checkout 4c24700b -- app/renderer/src/views/Edit.tsx`) and re-running
// Edit.invariant.test.tsx gives `Tests  3 failed | 2 passed (5)`; restoring gives
// `Tests  5 passed (5)`. The verbatim per-case transcript, the two lines of it
// that PASS at the baseline and therefore do NOT discriminate, and the reason the
// `key` below exists are all recorded at the head of that file. An earlier
// revision of this paragraph quoted a "2 failed | 1 passed" run: that transcript
// was real but was taken when the file held three cases, and it was left standing
// when two more were added — cite a run you produced against the file as it
// stands, never one inherited from an earlier shape of it.
//
// TWO CLAIMS ELSEWHERE ARE NOW FALSE BECAUSE OF THIS FIX. Both are SCOPE-ESCAPES,
// reported to the orchestrator rather than edited here: App.tsx:21 and :43-48
// ("still opens on its Task Hub (Edit.tsx:69 `useState('hub')`, :163)" and "Until
// it is taken, G-7 invariant 2 does not hold"), and Workspace.tsx:610-615 ("the
// Refine DESTINATION still lands on views/Edit.tsx's Task Hub on a first open").
// Every line number those two cite is gone from this file.
//
// THE TASK HUB SURVIVES IN THE CODE AND IS UNREACHABLE IN THE SHIPPED APP ON THIS
// BRANCH. Stated plainly, because an earlier revision of this paragraph said the
// cards, the "Advanced / all tools" escape and the per-video choice persistence
// "keep working exactly as before", and that is false in the product. Trace it:
// `<TaskHub>` renders at exactly ONE place (:381) behind `mode !== 'workspace'`;
// `mode` is seeded `initialMode ?? 'workspace'` (:213-214), re-seeded at :236, and
// never set to 'hub' anywhere (:251 and :284 both set 'workspace'); the sole
// production mount, App.tsx:604, passes no `initialMode`. So no user reaches the
// four cards or the advanced escape, and `initialMode='hub'` is exercised by tests
// only. `lib/taskHub.ts resumeFor` genuinely does keep working — it is read on
// every open at :248 — but it is the only half of the hub that does.
//
// THE CONSEQUENCE NOTHING ELSE HERE DRAWS: `persist()` (:265) is the only writer of
// `taskHubChoiceByVideo`, and it is reachable only from `handleChoose` (:278),
// which only TaskHub's `onChoose` calls (:381). Hub unreachable ⇒ writer
// unreachable ⇒ NO FRESH INSTALL ON THIS BRANCH CAN EVER CREATE a remembered
// choice. Two things follow that are easy to miss. (1) The `key` at :373, whose
// price the comment there enumerates in full (a whole Workspace subtree remount, a
// duplicate `project.open`, a replaced `<video>` node, a dropped `onProxyState`
// window), can now fire ONLY for profiles that wrote a choice under v1.4.1 or
// earlier — a real but FROZEN population. It STAYS, because dropping it regresses
// exactly those installs; but from this commit it is a legacy-compatibility path,
// not a living one, and the Workspace-side fix named there retires it for good.
// (2) An upgraded user whose stored choice is 'subtitles' now lands on the caption
// lane on every open of that video with no surface anywhere in the app to change
// or clear it — the hub was the only writer, and this file already records that
// the choice is restart-durable with no clearing UI.
//
// SCOPE-ESCAPE, one line, App.tsx's to take: wire ONE production entry point that
// passes `initialMode='hub'` (a first-import "what do you want to do with it?"
// moment, or a per-video overflow action), or a designed v1.4.1 surface and its
// preference writer ship dead. Nothing was removed from the CODE, so that wiring
// is one prop away; but until it lands, every hub case in Edit.test.tsx and all of
// TaskHub.test.tsx covers a production-unreachable path. No user CAPABILITY is
// lost meanwhile — all four card destinations are top-level surfaces and the
// advanced escape's target is now the default — which is why this is a dead
// surface to re-wire, not a dropped feature.
//
// NINE TEST SITES PIN THE OLD LANDING AND MUST CHANGE IN THE SAME MERGE — not the
// TWO an earlier revision of this paragraph named. That undercount was not a
// judgement call, it was a blind instrument: the count came from `npx vitest run`,
// and app/vitest.config.ts `test.include` is `main/**`, `renderer/src/**`,
// `render-cli/src/**` — `app/e2e/**` is not in it, and app/package.json routes e2e
// to a different runner (`"test:e2e": "playwright test"`). So vitest structurally
// CANNOT see the layer this change breaks, and its "2 files / 4 tests" was a
// complete answer to the wrong question. All nine sites are OUTSIDE this lane's
// file scope and are reported as scope-escapes rather than edited here.
//
// VITEST — 2 files / 4 tests. `npx vitest run` from app/ is 2 files / 4 tests
// failed, 4921 passed (4925); the 4 are exactly the 3 + 1 below and this lane's own
// suites are green. (That count describes the branch BEFORE the merge that carries
// these edits; read it as the record of why these two files are named.)
//   1. App.quality.test.tsx:437 asserts `.task-hub__title` is 'Talk' after a video
//      is opened — that suite mocks ./views/Workspace but NOT ./views/Edit, so it
//      renders the real Edit and now reads `undefined`. Corrected assertion: the
//      `[data-testid="workspace"]` marker carries data-video-id 'v1'.
//   2. App.director-state.test.tsx mocks neither, so it mounts the REAL Workspace
//      for the first time (the hub used to stand in the way). Its `./lib/rpc` mock
//      has no `onProxyState`, which Workspace.tsx:412 subscribes to on mount, so 3
//      tests die with "No onProxyState export is defined". Fix: add
//      `onProxyState: () => () => undefined,` to that mock factory.
//
// PLAYWRIGHT — 7 specs, NOT run by this lane and NOT previously named. The hub
// never renders, so `button.task-hub__advanced` never exists and every site below
// waits on an unresolvable locator until the Playwright timeout:
//   3-6. FOUR literal call sites, ONE LINE TO DELETE at each — the
//      `.workspace__title` wait that follows then satisfies itself, because the
//      Workspace IS the landing: e2e/preview.spec.ts:143,
//      e2e/transcribe-journey.spec.ts:238, e2e/installed-app.spec.ts:397,
//      e2e/visual/_visualSetup.ts:128.
//   7-9. THREE specs that inherit the break through `_visualSetup.ts`'s shared
//      `openVideo()` helper and need NO edit of their own once it is fixed:
//      e2e/overlay-hittest.spec.ts:189, e2e/visual/a11y.a11y.spec.ts:100,
//      e2e/visual/surfaces.visual.spec.ts:96.
//   Plus TWO comments that this change inverts and that should be retired with it:
//      e2e/overlay-hittest.spec.ts:185-188 says `openVideo` is non-idempotent
//      because the Advanced escape is "a one-time step, so a second call would
//      hang" — after this change the FIRST call hangs; and e2e/preview.spec.ts:194
//      describes the open path as "library card -> task-hub Advanced / all tools".
// Both e2e legs of .github/workflows/e2e.yml collect them: playwright.config.ts
// (testDir './e2e', testIgnore visual/**, audit/**) takes preview,
// transcribe-journey, overlay-hittest and installed-app; playwright.visual.config.ts
// (testDir './e2e/visual', testMatch '**/*.{visual,a11y}.spec.ts') takes a11y.a11y
// and surfaces.visual. installed-app.spec.ts self-skips when RF_E2E_APP_EXE is
// unset (:118, :208), so it is inert in the ordinary legs and DOES run in the
// dedicated packaged-artifact job that sets it (e2e.yml:706) — the golden journey
// against the shipped .exe, which is the one leg that proves the built product.
// THE HONEST STATUS OF THIS BRANCH, therefore: green on the renderer unit suite
// apart from the two vitest files above, and RED on the e2e and visual gates until
// the four one-line deletions land. It is NOT independently mergeable.
// Neither edit weakens a test: (1) inverts an assertion onto the new locked
// behaviour, (2) completes a mock that was never exercised. A third suite,
// App.quality.test.tsx, is ALSO the only place the Library → open-video hop is
// driven, and it mocks Workspace — so "Library → open video → the dock is on
// screen" is still covered by two disjoint tests whose composition nothing pins.
// Edit.invariant.test.tsx proves the destination half against the real Workspace
// and does not reach the routing half; closing that needs one App-level case in
// a suite with no Edit mock, which is a scope-escape from here.
//
// ADDITIVE: the four cards route into existing surfaces, never reimplementations —
//   - Reframe to vertical → the single Make Shorts owner, PRE-SELECTED to this video
//                           (onMakeShortsForVideo). This used to route to
//                           `Workspace @ the Short-maker tab`, but WU-3a4 moved
//                           ShortMaker OUT of the Workspace, leaving that tab as a
//                           mount-time redirect — so the card detoured through a
//                           Workspace it was immediately bounced out of.
//   - Add subtitles       → Workspace @ the Subtitles tab,
//   - Make shorts         → the top-level Make Shorts section (onMakeShorts),
//   - Director            → the top-level AI Director section (onDirector).
// The last choice is remembered per video so a returning power user resumes the
// workspace-scoped tool in place rather than seeing the hub again. Choices that
// NAVIGATE AWAY (reframe / shorts / director) are only MARKED as last-used, never
// auto-resumed — auto-resuming one bounces the user straight back out of the video
// they just opened, which is unescapable and survives restart.
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { EmptyState } from '../components/EmptyState';
import { Workspace } from './Workspace';
import { TaskHub } from './TaskHub';
import { hasApi, rpc, type Video } from '../lib/rpc';
import {
  HUB_CHOICE_KEY,
  type HubChoice,
  mergeHubChoice,
  readHubChoice,
  resumeFor,
} from '../lib/taskHub';

/** What Edit shows for an open video: the job chooser, or the editor itself. */
export type EditMode = 'hub' | 'workspace';

export interface EditProps {
  /** The video to edit, or null when none has been opened yet. */
  video: Video | null;
  /**
   * Which mode to SEED for an open video. Defaults to `'workspace'` so the
   * destination opens on the docked timeline with zero navigation actions
   * (L5 G-7 invariant 2). Pass `'hub'` to open the per-video Task Hub instead.
   * A remembered workspace-scoped choice still overrides the seed and resumes at
   * its own tab — which under this seed costs one keyed remount of the whole
   * Workspace subtree, `<Player>` included, because the Workspace is already
   * mounted by the time that choice is read. The `key` at the render below is
   * that remount; removing it silently drops the resumed tab, and its comment
   * enumerates the full cost and names the Workspace-side fix that retires it. A
   * remembered NAVIGATE-AWAY choice is still only marked last-used and never
   * auto-navigated to.
   */
  initialMode?: EditMode;
  /** Return to the Library home. */
  onBack: () => void;
  /** Route to the top-level Make Shorts section (the "Make shorts" job card). */
  onMakeShorts?: () => void;
  /**
   * WU-3a4: route to the top-level Make Shorts section PRE-SELECTED to a video —
   * the Workspace "Short-maker" tab deep-links here (the single ShortMaker owner)
   * rather than mounting a second copy in the Workspace.
   */
  onMakeShortsForVideo?: (videoId: string) => void;
  /** Route to the top-level AI Director section (the "Director" job card). */
  onDirector?: () => void;
}

/**
 * The per-video body: the Task Hub landing, or (on a card / advanced pick, or a
 * remembered workspace choice) the full Workspace. Split out so `video` is always
 * non-null here — the null case is the empty state in `Edit` below.
 */
function EditVideo({
  video,
  onBack,
  onMakeShorts,
  onMakeShortsForVideo,
  onDirector,
  initialMode,
}: EditProps & { video: Video }): React.ReactElement {
  // A video IS open in this component (the null case never reaches here), so the
  // seed is the editor unless a caller explicitly asked for the job chooser.
  const seed: EditMode = initialMode ?? 'workspace';
  const [mode, setMode] = useState<EditMode>(seed);
  // The Workspace tab to land on (null = its own default first tab).
  const [tab, setTab] = useState<string | null>(null);
  const [lastChoice, setLastChoice] = useState<string | null>(null);
  // The last-read settings blob, kept so a persist is a read-modify-write that
  // preserves OTHER videos' remembered choices without a second settings.get.
  const settingsRef = useRef<Record<string, unknown> | null>(null);
  const videoId = video.id;

  // On (re)open of a video: reset to the seeded mode, then best-effort read the
  // remembered choice — a workspace-scoped one resumes IN PLACE at its own tab; a
  // section choice only marks "last used" and never navigates (auto-resuming one
  // bounces the user out of the video they just opened, restart-durably, with no
  // UI to clear it). Neither branch can now put an interstitial in front of the
  // timeline: the seed is already the editor.
  //
  // ORDERING, because it is load-bearing and not obvious: under the 'workspace'
  // seed this `setTab` lands AFTER the Workspace has mounted, so "resumes at its
  // tab" is true only because the render below keys on `tab`. `setMode` is then a
  // no-op on that path — it still matters under an explicit 'hub' seed, where the
  // Workspace has not mounted yet and receives the tab as a first-mount prop.
  useEffect(() => {
    setMode(seed);
    setTab(null);
    setLastChoice(null);
    settingsRef.current = null;
    if (!hasApi()) return;
    let cancelled = false;
    void rpc<Record<string, unknown>>('settings.get')
      .then((settings) => {
        if (cancelled) return;
        settingsRef.current = settings ?? null;
        const choice = readHubChoice(settings, videoId);
        setLastChoice(choice);
        const resume = resumeFor(choice);
        if (resume.kind === 'workspace') {
          setTab(resume.tab);
          setMode('workspace');
        }
      })
      .catch(() => {
        // Best-effort: a failed read simply keeps the hub landing.
      });
    return () => {
      cancelled = true;
    };
  }, [videoId, seed]);

  // Persist the picked choice for this video (best-effort, in-memory reflected
  // immediately). Read-modify-write against the cached settings so sibling videos'
  // choices survive.
  const persist = useCallback(
    (choice: string) => {
      setLastChoice(choice);
      const map = mergeHubChoice(settingsRef.current?.[HUB_CHOICE_KEY], videoId, choice);
      settingsRef.current = { ...(settingsRef.current ?? {}), [HUB_CHOICE_KEY]: map };
      if (!hasApi()) return;
      void rpc('settings.set', { [HUB_CHOICE_KEY]: map }).catch(() => {
        // Persisting is best-effort; the in-memory choice already reflects intent.
      });
    },
    [videoId],
  );

  const handleChoose = useCallback(
    (choice: HubChoice) => {
      persist(choice);
      const resume = resumeFor(choice);
      if (resume.kind === 'workspace') {
        setTab(resume.tab);
        setMode('workspace');
        return;
      }
      // Section choices route to a top-level surface (kept in App shell state).
      // 'reframe' deep-links to the SINGLE Make Shorts owner PRE-SELECTED to this
      // video. It must NOT go via `Workspace initialTab='shortmaker'`: WU-3a4 moved
      // ShortMaker out of the Workspace, so that tab only redirects away on mount —
      // mounting Workspace just to be bounced out of it made Edit unreachable for
      // this video for good (restart-durable, no UI to clear the persisted choice).
      // Routing straight to the owner reaches the same destination without the detour.
      if (choice === 'reframe') {
        onMakeShortsForVideo?.(videoId);
        return;
      }
      if (choice === 'shorts') {
        onMakeShorts?.();
        return;
      }
      onDirector?.();
    },
    [persist, onMakeShorts, onMakeShortsForVideo, onDirector, videoId],
  );

  if (mode === 'workspace') {
    return (
      // `key` IS THE RESUME PATH — do not remove it as noise. Workspace consumes
      // `initialTab` ONLY in two `useState` lazy initializers (Workspace.tsx:254-260
      // `lane`, :270-274 `sectionPref`); no effect there depends on it. React runs an
      // initializer once per component INSTANCE, so a prop that arrives after mount
      // cannot reach them. Seeding 'workspace' means this element mounts on render 1,
      // BEFORE the async `settings.get` above resolves — so without a key change the
      // remembered `{kind:'workspace', tab}` would be read, set, and silently dropped,
      // and the user who picked "Add subtitles" would land on the video lane with
      // project tools instead of the caption lane with Subtitles.
      //
      // Keying on the tab remounts ONCE PER OPEN and ONLY in that case: `tab` is null
      // on first render and is only ever set from `resumeFor` / `handleChoose`, and a
      // resume that yields a null tab ('advanced', or any section choice) leaves the
      // key at 'default' and does not remount. "Per open" is the honest scope — the
      // effect above also `setTab(null)` on a [videoId, seed] change, so an Edit
      // instance that survived a video SWITCH would flip the key again. Unreachable
      // today: App's `openVideo` (App.tsx:429) has exactly one caller, `<Library
      // onOpen>` (:633), which changes route and unmounts Edit.
      //
      // THE COST, ENUMERATED. It is a full subtree REMOUNT, not one cheap RPC — an
      // earlier revision of this comment priced it as "one extra `project.get`", an
      // RPC that exists nowhere in this app. Measured by the seam probe in
      // Edit.invariant.test.tsx (hold the settings read pending → snapshot → release),
      // resume against the no-resume control:
      //   * `project.open` — Workspace's ONLY rpc call (Workspace.tsx:380) — fires
      //     1 → 2. The handler resolves the id to the per-video manifest and creates
      //     one on first open (sidecar/media_studio/handlers/library_ops.py:527-533),
      //     so the duplicate is wasted work, not a second project record.
      //   * the <video> element afterwards is a DIFFERENT NODE (control: the same
      //     node). `<Player key={video.id} reloadToken={playerEpoch}>` lives inside
      //     this subtree (Workspace.tsx:591-597) and its own key cannot save it: a
      //     parent key change unmounts every descendant. That reintroduces one level
      //     up the restart `reloadToken` exists to avoid — Workspace.tsx:360-363,
      //     "NOT a key-remount, which would visibly restart the element mid-load (the
      //     'shakiness' bug)", and :588-590 "key is the videoId ONLY". It fires about
      //     one IPC round trip after mount, so the element being restarted is
      //     milliseconds old; whether that is PERCEPTIBLE in the packaged app is
      //     UNVERIFIED — settle it by opening a profile whose settings hold
      //     `taskHubChoiceByVideo: {<id>: 'subtitles'}` and recording the first 500 ms.
      //   * `onProxyState` is re-subscribed with `proxyPhaseRef` reset to 'initial'
      //     (Workspace.tsx:407-412), so a 'ready'/'error' push landing in that
      //     one-commit window reaches the doomed instance and is dropped.
      //
      // WHY IT IS STILL THE RIGHT TRADE, and what retires it:
      //   * NOT paying it means silently ignoring the remembered lane, which is a
      //     REGRESSION and not a declined new feature. Measured: with the pre-branch
      //     Edit.tsx checked out, Edit.invariant.test.tsx's resume case PASSES — under
      //     the hub seed the choice arrived as a first-mount prop — and the hub plus
      //     its `taskHubChoiceByVideo` writer shipped in v1.4.1 (`git show
      //     v1.4.1:app/renderer/src/lib/taskHub.ts`), so upgraded installs already
      //     hold choices that land on the caption lane with zero clicks today.
      //   * withholding the first mount until the settings read settles swaps a
      //     bounded restart for an unbounded one: the timeline's appearance would
      //     depend on an unrelated RPC's latency, and on a hang it never appears.
      //   * the durable fix is Workspace consuming `initialTab` AFTER mount — its two
      //     lazy `useState` initializers are the whole reason a post-mount prop cannot
      //     land. That is a Workspace.tsx edit, outside this lane's file scope, so it
      //     is reported as a scope-escape rather than taken here. When it lands,
      //     delete this key: the invariant suite bounds the resume at `<= 2` mounts
      //     precisely so that fix makes it greener, never red.
      // Pinned by Edit.invariant.test.tsx ("resumes a remembered workspace-scoped
      // choice at its own tab, from the production seed", plus the two seam cases)
      // against the REAL Workspace.
      <Workspace
        key={tab ?? 'default'}
        video={video}
        onBack={onBack}
        initialTab={tab ?? undefined}
        onOpenMakeShorts={onMakeShortsForVideo}
      />
    );
  }
  return <TaskHub video={video} lastChoice={lastChoice} onChoose={handleChoose} />;
}

/** The Edit section: the per-video Task Hub / Workspace, or an empty state. */
export function Edit({
  video,
  onBack,
  onMakeShorts,
  onMakeShortsForVideo,
  onDirector,
  initialMode,
}: EditProps): React.ReactElement {
  if (!video) {
    // Q8: the anatomy (ghost poster -> title -> hint -> a way forward) now has ONE
    // definition, components/EmptyState.tsx. `block` keeps this screen's own
    // `edit__empty-*` skin (components/shell.css) class-for-class, so sharing
    // the structure costs zero pixels here — this screen IS the reference bar, and
    // Edit.empty.test.tsx pins both the delegation and the unchanged classes.
    //
    // ONE attribute is deliberately NOT byte-identical to what shipped: the root
    // now carries `role="region"` beside its `aria-label`. origin/main named a
    // role-less div, where ARIA 1.2 declares "Name from: prohibited"; measured on
    // this repo's own axe-core 4.12.1 that shape is a needs-review ("aria-label
    // attribute is not well supported on a div with no valid role attribute") and
    // this one PASSES — so the honest delta is unreliable -> dependable, not
    // "was broken" (see resolveA11y in EmptyState.tsx). Attribute-only,
    // zero CSS impact — the sole `[role=…]` selector in any renderer stylesheet is
    // shell.css's :focus-visible list (button/tab/input, never region) — so the
    // "zero visual regression" claim survives; it is the a11y tree that changed.
    //
    // HINT COPY — docs/plans/v1.5/editing-surface-audit-2026-08.md:52 — this used
    // to read "trim, cut, join, reframe, caption, and more — every edit tool lives
    // here". Three of those verbs are not reachable from this section, and the
    // "every tool lives here" clause was the widest part of the claim: Make Shorts
    // and the Director are top-level rail destinations, and WU-3a4 deliberately
    // moved ShortMaker OUT of the Workspace. The audit at :44 measures the tab list
    // as "no trim, no cut, no join tab"; :45-48 finds those engines reachable "only
    // through" the AI Director and concludes "a user cannot drag a cut"; rows 1-3
    // (:82-84) mark trim/cut/split "engine BUILT ... UI MISSING". So the copy names
    // only verbs this section actually reaches, and says where the missing one
    // lives instead of implying it is here. Pinned by Edit.test.tsx. If a manual
    // cut surface lands later, widen this sentence in the SAME commit that ships it.
    //
    // ACTION — M2: Edit was the only one of eight empty states with no way forward.
    // Same affordance and voice as the sibling views (Caption.tsx:102-104,
    // Export.tsx:251-253), which already shipped it.
    return (
      <EmptyState
        className="edit edit--empty"
        label="Edit"
        block="edit__empty"
        poster
        title="No video open"
        hint="Open a video from the Library to transcribe it, add subtitles, reframe it to vertical, dub it, or hand it to the AI Director. Shortening a clip goes through the Director for now."
        action={{ label: '← Library', onClick: onBack, className: 'edit__empty-back' }}
      />
    );
  }
  return (
    <EditVideo
      video={video}
      onBack={onBack}
      onMakeShorts={onMakeShorts}
      onMakeShortsForVideo={onMakeShortsForVideo}
      onDirector={onDirector}
      initialMode={initialMode}
    />
  );
}

export default Edit;
