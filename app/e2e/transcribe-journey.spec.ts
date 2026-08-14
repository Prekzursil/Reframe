// transcribe-journey.spec.ts — the held-out proof that SPEECH becomes TEXT, and
// then becomes CAPTIONS, through the real GUI against the real Python sidecar.
//
// ── THE HOLE THIS CLOSES ─────────────────────────────────────────────────────
// Reframe's core purpose is: import landscape video → TRANSCRIBE → CAPTION →
// reframe → export. Steps 2 and 3 had never been proven on speech ANYWHERE in the
// repository, in either direction. Measured at origin/main 775a97ea:
//   * `fixtures.ts` generateSample — the only media fixture — is `testsrc` +
//     `sine=frequency=440`. No speech.
//   * `golden-journey.spec.ts:18-19` deliberately drives the MANUAL-range path
//     because "AI moment-pick would emit 'no candidates' on a 3s no-speech
//     sample", so the GUI keystone bypasses transcription BY DESIGN.
//   * `sidecar/tests/e2e/real_pipeline_smoke.py:294` runs a real tiny whisper and
//     prints "sine-only audio has no speech, so 0 segments is the honest result"
//     — it ASSERTS AN EMPTY TRANSCRIPT.
//   * `sidecar/tests/e2e/test_whisper_offline_e2e.py` proves model RESOLUTION with
//     fake weights (`write_bytes(b"ct2-weights")`); it never transcribes audio.
//   * the repo tracks ZERO audio/video binaries.
// So: no test proved a spoken word becomes text or a caption. That is a
// VERIFICATION hole, not necessarily a product defect — this spec settles it.
//
// ── THE JOURNEY (nothing stubbed) ────────────────────────────────────────────
//   synthesise real speech with Windows SAPI → mux it over the same `testsrc`
//   video the silent fixture uses → seed it through the real `library.add`
//   → PIN the ASR target via the real `settings.set`
//   → launch the built app (with the HF model fetch forced ANONYMOUS — see
//     HF_ANONYMOUS_ENV; an ambient HF_TOKEN that 401s otherwise reads as
//     "the model does not exist") → open the video → Workspace
//   → Transcribe tab: assert the panel's EMPTY state first (detector control),
//     click the real "Start transcription", and assert the rendered
//     `.transcript-segments` carries the spoken content words
//   → Subtitles tab: click the real "Generate subtitles" and assert a rendered
//     CUE carries one of those same words.
//
// Every assertion about the TRANSCRIPT and the CUES reads the UI: the point is
// that the USER can see the transcript, not that an RPC returned one.
//
// SCOPE CORRECTION — the earlier wording here ("every assertion reads the UI,
// never the sidecar's return value") was REFUTED and is wrong. There is exactly
// ONE assertion on an RPC return value: the `settings.set` pin in `beforeAll`
// below, which checks the MERGED settings document it returns. That is a setup
// PRECONDITION that no UI surface exposes, and it is deliberate — without it a
// param-shape mistake becomes a mysterious 1.5 GB download instead of a named
// setup failure. Every done-signal (transcript text, cue text) is still read
// from the rendered DOM.
//
// ── WHAT THIS DOES *NOT* DO ──────────────────────────────────────────────────
// It does NOT gate a PR. `e2e.yml` is `workflow_dispatch` + nightly `cron` only,
// so this proves the capability NIGHTLY AND ON DEMAND; it cannot stop a
// transcription regression from merging. Wiring it into `quality.yml` is not on
// the table — that gate list is CLOSED at 6 by QUALITY-CHARTER.md rule 2. See the
// PR body for the recommendation + its cost.

import { test, expect, _electron as electron, type ElectronApplication } from '@playwright/test';
import {
  SPEECH_KEYWORDS,
  SPEECH_KEYWORD_MIN_HITS,
  SPEECH_PHRASE,
  applySettings,
  findBuiltApp,
  generateSpeechSample,
  matchedSpeechKeywords,
  seedEnvironment,
  type SeededEnv,
  type SpeechFixture,
} from './fixtures';

// ── LOAD-BEARING SETUP VALUES ────────────────────────────────────────────────
// The whisper model this journey pins, and WHY it is not the shipped default.
//
// `resolve_transcribe_target` (sidecar features/transcribe.py:353-392) would pick
// `cpu_auto_model()` on a GPU-less runner, which today returns `large-v3-turbo`
// (the only whisper snapshot the Default install profile registers). MEASURED on
// this box, that snapshot is **1546.5 MB** across 11 files
// (`mobiuslabsgmbh--faster-whisper-large-v3-turbo`, the exact commit
// `manifest.WHISPER_HF_REVISION` pins) versus **74.6 MB** for
// `Systran--faster-whisper-tiny`. Pulling 1.5 GB into a nightly leg to prove
// "speech becomes text" buys nothing over 75 MB, so we pin `tiny` explicitly —
// the SAME model `sidecar/tests/e2e/real_pipeline_smoke.py` already runs in this
// very workflow, so no new CI contract is introduced.
//
// DISCLOSED RESIDUAL (inline, per the honesty rule): `tiny` is NOT a registered
// manifest asset, so `transcribe.resolve_model_source('tiny')` logs
// "no pinned local snapshot" and hands faster-whisper the bare id — a NETWORK
// resolve. This leg therefore depends on huggingface.co being reachable, exactly
// as `real_pipeline_smoke.py` already does. It is NOT an offline proof and must
// not be described as one. Registering a pinned `tiny` asset would remove that
// dependency but adds a user-visible component to `assets.list` / the Models &
// System UI for the sole benefit of a nightly test, so it was deliberately NOT
// done here; the settling experiment for the offline claim is a run with
// HF_HUB_OFFLINE=1 after `assets.ensure(['whisper-tiny'])`, which needs that
// registration first.
const PIN_MODEL = 'tiny';
// Force CPU too: `detect_device` probes `torch.cuda.is_available()`, and torch is
// absent from the E2E runtime install — so the probe would ImportError-degrade to
// CPU anyway. Pinning it makes the resolved target deterministic instead of a
// side effect of which packages happen to be installed.
const PIN_DEVICE = 'cpu';

// ── THE ONE ENV OVERRIDE, AND THE DEFECT IT CLOSES ───────────────────────────
// `fixtures.definedEnv` copies the WHOLE ambient environment into the app env, so
// the sidecar inherits any `HF_TOKEN` the developer has exported. huggingface_hub
// sends that token IMPLICITLY on every request — including requests for a PUBLIC
// repo — and a token that no longer authenticates turns a public fetch into
// `RepositoryNotFoundError: 401`, which reads as "the model does not exist", not
// "your token is bad". MEASURED on this box, four arms, each on a FRESH empty
// HF_HOME against the public `Systran/faster-whisper-tiny`:
//   huggingface_hub 1.27.0, ambient token -> RepositoryNotFoundError 401, cache 5,698 B
//   huggingface_hub 1.27.0, this override -> OK, 6 blobs / 78,207,087 B (74.6 MB)
//   huggingface_hub 1.26.0 (the lock pin), ambient token -> RepositoryNotFoundError 401
//   huggingface_hub 1.26.0 (the lock pin), this override -> OK, the same 6 blobs
// and END-TO-END through this spec: WITHOUT the override, a cold-HF_HOME run goes
// red in 41 s at the panel-error arm below, carrying the sidecar's
// `User Access Token "Reframe" is expired`.
//
// The credential itself is NOT touched — AGENTS.md §9 reserves credential
// lifecycle to the owner — so the CONSUMER is fixed instead, which is also the
// durable half: ANY HF_TOKEN that 401s (revoked, wrong org, insufficient scope)
// breaks the cold-cache path identically. A GitHub runner carries no HF_TOKEN and
// was therefore already anonymous, so this changes nothing in CI and only makes a
// developer's cold-cache run deterministic. It does NOT make the leg offline (see
// PIN_MODEL's disclosed residual) — it makes the network fetch unauthenticated.
const HF_ANONYMOUS_ENV: Record<string, string> = { HF_HUB_DISABLE_IMPLICIT_TOKEN: '1' };

// Cold whisper: a ~75 MB model fetch on a fresh runner, then CPU/int8 inference
// over ~7 s of audio. Measured locally (warm HF cache, 8-core): first transcript
// in well under 30 s. 300 s is fetch-plus-slow-runner headroom, deliberately
// generous — this is a nightly leg, not a PR gate.
const TRANSCRIBE_WAIT_MS = 300_000;

let seeded: SeededEnv;
let speech: SpeechFixture;
let app: ElectronApplication;
const consoleErrors: string[] = [];
// The sidecar's own stderr arrives on the MAIN process's pipes, not in
// Playwright's error context. A failed transcribe job (no faster_whisper, a
// blocked model download, a ctranslate2 load error) is only diagnosable from
// here, so buffer it and fold the tail into any red repro.
const mainLog: string[] = [];

/** Loud, named reason for the platform gate — never a silent pass. */
const SKIP_REASON =
  'Windows-only: the speech fixture synthesises its audio with Windows SAPI ' +
  '(System.Speech.Synthesis.SpeechSynthesizer). There is no committed speech ' +
  'binary to fall back to, so this journey cannot run off-Windows — it is SKIPPED, ' +
  'not silently satisfied.';

test.beforeAll(async () => {
  // Same reasoning as golden-journey.spec.ts:129-145: a beforeAll hook does NOT
  // inherit a test's setTimeout and gets its own from the config (120 s). Speech
  // synthesis + ffmpeg mux + library.add + thumbnail + app launch all live here.
  test.setTimeout(240_000);

  if (process.platform !== 'win32') {
    // Print it as well as skipping: a `-` in the list reporter is easy to miss,
    // and a gate that cannot fail must at least say so out loud.
    console.log(`[transcribe-journey] SKIPPED — ${SKIP_REASON}`);
  }
  test.skip(process.platform !== 'win32', SKIP_REASON);

  const built = findBuiltApp();
  // The ONLY difference from every other spec's seeding: the sample carries real
  // speech. Same data root, same `library.add`, same thumbnail, same app env.
  seeded = seedEnvironment((samplePath, workDir) => {
    speech = generateSpeechSample(samplePath, workDir);
  });
  console.log(
    `[transcribe-journey] speech fixture: voice=${speech.voice} ` +
      `speechDurationSec=${speech.speechDurationSec.toFixed(3)} phrase=${JSON.stringify(SPEECH_PHRASE)}`,
  );

  // PIN the ASR target before the app boots (see PIN_MODEL/PIN_DEVICE above), and
  // VERIFY the write landed. `settings.set` returns the merged document, so an
  // unabsorbed key (a param-shape mistake, a rejected write) fails HERE with a
  // named error instead of surfacing as a mysterious 1.5 GB download later.
  const merged = applySettings(seeded.python, seeded.dataRoot, {
    transcribeModel: PIN_MODEL,
    transcribeDevice: PIN_DEVICE,
  });
  if (merged.transcribeModel !== PIN_MODEL || merged.transcribeDevice !== PIN_DEVICE) {
    throw new Error(
      `settings.set did not persist the ASR pin — got transcribeModel=${JSON.stringify(merged.transcribeModel)} ` +
        `transcribeDevice=${JSON.stringify(merged.transcribeDevice)}`,
    );
  }

  app = await electron.launch({
    args: [built.main, '--autoplay-policy=no-user-gesture-required', '--no-sandbox'],
    ...(built.executablePath ? { executablePath: built.executablePath } : {}),
    // HF_ANONYMOUS_ENV last so it wins over anything the ambient env carried.
    env: { ...seeded.appEnv, ...HF_ANONYMOUS_ENV },
  });

  const proc = app.process();
  proc.stdout?.on('data', (d: Buffer) => mainLog.push(d.toString()));
  proc.stderr?.on('data', (d: Buffer) => mainLog.push(d.toString()));

  const win = await app.firstWindow();
  win.on('console', (m) => {
    if (m.type() === 'error') consoleErrors.push(m.text());
  });
  win.on('pageerror', (e) => consoleErrors.push(`PAGEERROR: ${e.message}`));
  await win.waitForLoadState('domcontentloaded');
});

test.afterAll(async () => {
  await app?.close();
});

/** The lines of the sidecar's log that explain a failed ASR job. */
function asrErrorTail(): string {
  return mainLog
    .join('')
    .split(/\r?\n/)
    .filter((l) =>
      /error|traceback|whisper|ctranslate|faster_whisper|transcribe|huggingface|offline|snapshot|tokenizer/i.test(l),
    )
    .slice(-30)
    .join('\n');
}

test('spoken words become a visible transcript and then a caption cue (real GUI + real sidecar)', async () => {
  // Whisper cold-start dominates; give the whole journey room above the 120 s
  // config default. Kept as ONE test on purpose: a caption assertion is
  // meaningless without the transcript that feeds it, so splitting them would
  // create a silent inter-test ordering dependency instead of a visible one.
  test.setTimeout(TRANSCRIBE_WAIT_MS + 120_000);
  const win = await app.firstWindow();

  // A — the shell is up and the speech-bearing sample is imported + listed.
  await expect(win.locator('.app__brand')).toHaveText('Reframe');
  await expect(win.locator('.library__item-title').first()).toHaveText('sample');

  // B — open it and take the "Advanced / all tools" escape into the full
  // Workspace (opening a video lands on the per-video Task Hub first; the same
  // route preview.spec.ts:142-144 drives).
  await win.locator('.library__item-title', { hasText: 'sample' }).click();
  await win.locator('button.task-hub__advanced').click();
  await expect(win.locator('.workspace__title')).toHaveText('sample');

  // C — Transcribe tab. The Workspace lands on Subtitles by default
  // (`DEFAULT_WORKSPACE_TAB`, Workspace.tsx:158), so select Transcribe explicitly.
  // Both tabs live in the VISIBLE "Speech & Text" cluster, so no Advanced
  // disclosure is involved.
  await win.locator('[role="tab"][data-tab-id="transcribe"]').click();
  const panel = win.locator('section.transcribe-panel');
  await expect(panel).toBeVisible();

  // DETECTOR CONTROL — assert the ABSENCE first. A fresh data root has no
  // transcript, so the panel must render its empty state and offer "Start
  // transcription". This is what makes the post-run assertion meaningful: it
  // proves the selectors resolve, that nothing pre-seeded a transcript, and that
  // the keyword-bearing text below genuinely arrived from THIS run. Without it a
  // green could come from a stale fixture and would measure nothing.
  await expect(panel.locator('[data-state="empty"]')).toBeVisible();
  await expect(panel.locator('.transcript-segments')).toHaveCount(0);
  const startButton = panel.locator('button', { hasText: 'Start transcription' });
  await expect(startButton).toBeEnabled();

  // D — run the REAL transcription (transcribe.start → live faster-whisper).
  await startButton.click();

  // Wait for the JOB to land, not for the segments — the two are different states
  // and conflating them costs five minutes on the most interesting failure.
  // `.transcript-summary` renders as soon as a Transcript object arrives
  // (Transcribe.tsx:318), INCLUDING one with zero segments. Waiting on
  // `.transcript-segments li` instead means an honest empty transcript (what the
  // speechless `sine` sample produces) burns the whole TRANSCRIBE_WAIT_MS budget
  // before reporting an anonymous "element not found" — measured at 5.1 minutes
  // on the PRE-SHARPENING shape of this block against a ~6.7 s speechless sine
  // (i.e. a sine stretched to the speech fixture's length, NOT the repo's own
  // 3 s `sine=frequency=440:duration=3`). UNVERIFIED here: that 5.1-minute figure
  // has not been re-measured, because the shape it describes no longer exists;
  // the settling experiment is to revert to `segments.first().waitFor(...)` and
  // re-run the sine arm. What IS re-measured is the sharpened shape below.
  //
  // Racing the summary and the panel error gives three distinct, fast verdicts —
  // and all THREE are now measured, not two:
  //   ASR blew up            -> panel error, 41 s wall clock: a cold HF_HOME plus
  //                             an ambient HF_TOKEN that 401s (see HF_ANONYMOUS_ENV)
  //                             lands here carrying the sidecar's own reason.
  //   ASR finished EMPTY     -> the zero-segments arm below, RE-MEASURED against
  //                             the repo's OWN 3 s speechless `sine` fixture:
  //                             failing test 12.6 s, whole invocation 56.3 s
  //                             (it includes Playwright's worker restart). Seconds,
  //                             not the pre-sharpening minutes — worth stating
  //                             because the cost of the red state is the only
  //                             argument against keeping this arm strict.
  //   ASR finished with content -> the green path.
  const segments = panel.locator('.transcript-segments li');
  const summaryLoc = panel.locator('.transcript-summary');
  const panelError = panel.locator('p.error[role="alert"]');
  await Promise.race([
    summaryLoc.waitFor({ state: 'visible', timeout: TRANSCRIBE_WAIT_MS }),
    panelError.waitFor({ state: 'visible', timeout: TRANSCRIBE_WAIT_MS }),
  ]).catch(() => undefined);
  if (await panelError.isVisible()) {
    throw new Error(
      `transcription failed in the UI: ${(await panelError.textContent())?.trim()}\n` +
        `--- sidecar log tail ---\n${asrErrorTail()}`,
    );
  }
  await expect(
    summaryLoc,
    `the transcription never completed within ${TRANSCRIBE_WAIT_MS}ms (no transcript reached the UI)\n` +
      `--- sidecar log tail ---\n${asrErrorTail()}`,
  ).toBeVisible({ timeout: 5_000 });
  // A transcript OBJECT arrived. An EMPTY one is the signature of "the audio
  // carried no recognisable speech" — precisely the pre-existing state this spec
  // exists to distinguish from working transcription, so name it.
  await expect(
    segments,
    'the transcription completed but produced ZERO segments — the audio reaching whisper ' +
      'carried no recognisable speech (this is exactly what the speechless `sine` fixture does)',
    // Short timeout on purpose: the summary above proves the job is TERMINAL, and
    // Transcribe.tsx renders every segment in the same commit as the summary — so
    // the count cannot change. Polling it for the config's 30 s only lengthens the
    // red repro. MEASURED against the sine fixture: this arm fires.
  ).not.toHaveCount(0, { timeout: 5_000 });

  // E — THE PRIMARY DONE-SIGNAL: the words the user can SEE.
  const transcriptText = ((await panel.locator('.transcript-segments').textContent()) ?? '').trim();
  const summary = ((await panel.locator('.transcript-summary p').textContent()) ?? '').trim();
  const hits = matchedSpeechKeywords(transcriptText);
  // Self-document on green AND red — an oracle nobody can read is an oracle
  // nobody trusts, and this line is the evidence for the whole lane.
  console.log(`[transcribe-journey] summary: ${summary}`);
  console.log(`[transcribe-journey] transcript-as-rendered: ${JSON.stringify(transcriptText)}`);
  console.log(`[transcribe-journey] keyword hits: ${hits.length}/${SPEECH_KEYWORDS.length} -> ${JSON.stringify(hits)}`);

  expect(
    hits.length,
    `the rendered transcript must carry at least ${SPEECH_KEYWORD_MIN_HITS} of ` +
      `${JSON.stringify(SPEECH_KEYWORDS)} (NOT an exact-phrase match — see ` +
      `fixtures.SPEECH_KEYWORD_MIN_HITS for why). rendered: ${JSON.stringify(transcriptText)}\n` +
      `--- sidecar log tail ---\n${asrErrorTail()}`,
  ).toBeGreaterThanOrEqual(SPEECH_KEYWORD_MIN_HITS);

  // F — CAPTIONS. `subtitles.generate` reads the transcript the run above just
  // persisted onto the project manifest, so this is the second half of the chain:
  // transcript → cues the user can see and edit.
  // The inspector is SELECTION-DRIVEN (L5 G-5): it renders only the sections of the
  // current context, `WORKSPACE_INSPECTOR_SECTIONS[context]`. `transcribe` (clicked
  // at C above) is in the `project` context — the default when nothing is selected —
  // but `subtitles` is in the `cue` context, so its tab does not exist until the
  // caption-cue lane is selected. Clicking it directly waited 30 s for a locator that
  // could never resolve; this spec predates the selection-driven rebuild and still
  // assumed one flat strip carrying every panel.
  //
  // Selecting the dock lane IS the selection the inspector follows (the dock's lane
  // heads are `WORKSPACE_DOCK_LANES`; ids are disjoint from the inspector section ids,
  // so this `data-tab-id` cannot collide).
  await win.locator('[role="tab"][data-tab-id="captions"]').click();
  await win.locator('[role="tab"][data-tab-id="subtitles"]').click();
  const subs = win.locator('section.subtitles-panel');
  await expect(subs).toBeVisible();
  // Detector control again: no track yet ⇒ no cue rows.
  await expect(subs.locator('.cue-list .cue-row')).toHaveCount(0);

  await subs.locator('button', { hasText: 'Generate subtitles' }).click();
  const subsError = subs.locator('p.error[role="alert"]');
  await Promise.race([
    subs.locator('.cue-list .cue-row').first().waitFor({ state: 'visible', timeout: 60_000 }),
    subsError.waitFor({ state: 'visible', timeout: 60_000 }),
  ]).catch(() => undefined);
  if (await subsError.isVisible()) {
    throw new Error(
      `subtitles.generate failed in the UI: ${(await subsError.textContent())?.trim()}\n` +
        `--- sidecar log tail ---\n${asrErrorTail()}`,
    );
  }
  await expect(subs.locator('.cue-list .cue-row').first()).toBeVisible({ timeout: 5_000 });

  // A cue's TEXT lives in its editable input's value, not in textContent.
  const cueTexts = await subs.locator('.cue-list .cue-row input.cue-text').evaluateAll((els) =>
    els.map((el) => (el as HTMLInputElement).value),
  );
  const cueHits = matchedSpeechKeywords(cueTexts.join(' '));
  console.log(`[transcribe-journey] cues: ${JSON.stringify(cueTexts)}`);
  console.log(`[transcribe-journey] cue keyword hits: ${cueHits.length} -> ${JSON.stringify(cueHits)}`);

  expect(cueTexts.length, 'at least one caption cue was generated from the transcript').toBeGreaterThan(0);
  expect(
    cueHits.length,
    `a generated CUE must carry at least one of ${JSON.stringify(SPEECH_KEYWORDS)} — ` +
      `otherwise captions are not carrying the spoken words. cues: ${JSON.stringify(cueTexts)}`,
  ).toBeGreaterThan(0);
});

test('no console errors across the transcribe-journey session', async () => {
  // Bound in beforeAll. Kept SEPARATE from — and after — the speech-to-text
  // done-signal so a renderer console error never masks the primary verdict
  // (same split as golden-journey.spec.ts:318).
  //
  // SCOPE — this covers load, navigation, the transcription run and the caption
  // generation ONLY WHEN THE PRIMARY TEST PASSES. After a primary failure
  // Playwright restarts the worker, `beforeAll` re-runs, and this test then
  // observes a FRESH app that never transcribed. MEASURED both states in one
  // spec: the red run prints the `[transcribe-journey] speech fixture: …` line
  // TWICE (once per beforeAll) and this test finishes in tens of ms against that
  // fresh launch, while the green run prints it ONCE. So on a red run this is a
  // launch-only console check, not session coverage. Not lane-introduced —
  // golden-journey.spec.ts:318 has the identical split — and left as-is
  // deliberately: merging it into the primary test would let a console error mask
  // the speech verdict, which is the worse failure.
  expect(consoleErrors, `console errors across session: ${JSON.stringify(consoleErrors)}`).toEqual([]);
});
