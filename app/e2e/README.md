# Reframe GUI / preview E2E harness

Real end-to-end verification that a user sees a **working preview**, launched
against the actual built Electron app and the live Python sidecar — no stubs.

## What it proves

| Spec | What runs | Verification level |
| --- | --- | --- |
| `preview.spec.ts` | Launches the real app via `playwright._electron.launch`, opens an imported sample video, asserts the preview `<video>` gets an `mstream://` src, reaches `readyState >= 2`, and `currentTime` **advances** after `play()` (real decode). Also asserts no console errors across the whole session; Library / Workspace / Shorts panels and the SemanticSearch + NleExport tab panels mount (panel-specific selectors); clicking the real **Export timeline** button writes a real `.edl` file to disk. The exported timeline is a valid CMX3600 EDL with **0 clips** (no shortmaker clips exist without ML candidate generation) — a real file, not edited video. | **GUI-VERIFIED** (live app + live sidecar) |
| `caption.dom.test.tsx` | Renders the real `CaptionOverlay` component over a real `<video>` with word-level cues in the exact shape `captions.cues` returns, and asserts the active caption word is painted in the DOM over the frame. | **DATA-PATH-VERIFIED** — the *live* caption overlay (`CandidateReview`) sits behind ML candidate generation (whisper transcript + LLM clip selection), which is not reachable without the model stack, so caption-over-video is proven at the component+DOM level. |
| `packaged.spec.ts` | Launches the **shipped electron-builder package** (the real `.exe`, resolved via `electron-playwright-helpers` `findLatestBuild`/`parseElectronApp`) and asserts `app.isPackaged === true`, that it runs out of `resources/app.asar`, that the packaged renderer boots with no console errors, and that the packaged main process inherits the seeded env + fires its first-run bootstrap. **WINDOWS-ONLY** (self-skips elsewhere — only the Windows CI leg builds a package). | **PACKAGED-SHELL-VERIFIED** (the shipped binary boots & is correctly wired). |
| `confirm-scrim.hittest.spec.ts` | Loads the REAL `renderer/src/components/confirmDialog.css` (+ `styles/tokens.css`) into a plain Chromium page and asks `document.elementFromPoint` whether a click behind the themed confirm gate reaches the page — the pointer half of its `aria-modal="true"`, which jsdom cannot observe because it does no layout and no hit-testing. Carries a **detector control** (the oracle must see the background when nothing covers it) and a **both-states control** that mounts the pre-fix `::before`-on-a-transformed-card stylesheet and REQUIRES the click to get through, so a green run cannot come from a probe that is silent everywhere. No Electron app or sidecar needed — the question is a property of one stylesheet. | **HIT-TEST-VERIFIED** (real Chromium, real stylesheet). |
| `nasty_captions.dom.test.tsx` | Feeds the real `CaptionOverlay` hostile caption data (unicode/RTL/emoji, empty/out-of-window cues, zero-duration/overlapping cues, a 10k-word timeline) and asserts graceful DOM output, never a crash. | **NASTY-INPUT-VERIFIED** (GUI leg). |
| `transcribe-journey.spec.ts` | Synthesises **real speech** with Windows SAPI, muxes it over the same `testsrc` video, seeds it through the real `library.add`, pins whisper `tiny`/`cpu` through the real `settings.set`, then drives the GUI: the Transcribe panel's **empty** state → the real **Start transcription** → the rendered `.transcript-segments` must carry the spoken content words → the Subtitles panel's real **Generate subtitles** → a rendered cue must carry one of the same words. **WINDOWS-ONLY** (SAPI; self-skips loudly elsewhere). | **GUI-VERIFIED** (live app + live sidecar + real faster-whisper). |

`DirectorPanel` is NOT mounted anywhere in the running renderer (only its own
file + unit test exist), so it is covered by its existing
`panels/DirectorPanel.test.tsx`, not by a GUI assertion.

### Speech → transcript → caption: what `transcribe-journey.spec.ts` does and does NOT prove

Until it existed, **no test in the repository proved that a spoken word becomes
text or a caption.** The only media fixture was `testsrc` + a 440 Hz `sine`, so
`golden-journey.spec.ts` deliberately takes the manual-range path (AI moment-pick
emits "no candidates" on no-speech audio), `sidecar/tests/e2e/real_pipeline_smoke.py`
*asserts an empty transcript* and says so in its own output, and
`sidecar/tests/e2e/test_whisper_offline_e2e.py` proves model *resolution* with fake
weights without ever transcribing audio. That was a **verification** hole, not
necessarily a product defect — the new spec settles it in the affirmative.

It **does** prove, through the live GUI: real audio → real faster-whisper →
a transcript the user can SEE in the Transcribe panel → real `subtitles.generate`
→ cues the user can SEE and edit in the Subtitles panel.

It does **not** prove the *live `CaptionOverlay` painted over the video frame* —
that surface (`CandidateReview`) still sits behind LLM clip selection, so the
`caption.dom.test.tsx` row above remains the honest level for caption-over-video.

Three deliberate design choices, each with its reason in the source:

- **Keyword + threshold, never an exact phrase.** Measured with the shipped stack
  (faster-whisper 1.2.1, `tiny`, cpu/int8) the word "Reframe" comes back as
  "Refrain". An exact-sentence or product-name assertion would be flaky *by
  construction*. The spec requires ≥ 2 of `fox` / `dog` / `landscape` / `vertical`
  (`fixtures.SPEECH_KEYWORD_MIN_HITS`); do not "tighten" it to 4 — which specific
  words survive depends on the machine's installed voice.
- **No committed audio binary.** The repo tracks zero media binaries; Windows SAPI
  synthesises the speech offline at test time. The cost is that the spec is
  Windows-only, so it `test.skip()`s with a named reason *and prints it*.
- **`tiny` pinned via `settings.set`.** Measured: the Default-profile whisper asset
  (`whisper-large-v3-turbo`) is **1546.5 MB**; `Systran/faster-whisper-tiny` is
  **74.6 MB**, and `tiny` is already what `real_pipeline_smoke.py` runs in the same
  workflow. Because `tiny` is *not* a registered manifest asset,
  `transcribe.resolve_model_source` hands faster-whisper the bare id and the
  snapshot is fetched from huggingface.co at run time — measured on a cold, empty
  `HF_HOME`: 13 files / 74.6 MB. **So this leg needs network; it is NOT an offline
  proof** (the same dependency the `e2e-sidecar` leg already carries). Making it
  offline would mean registering a pinned `tiny` asset, which adds a user-visible
  component to `assets.list` for the sole benefit of a nightly test — deliberately
  not done.

**BOTH-STATES verified** (a test that passes in both states measures nothing).
Same spec, same code, only the fixture's audio changed:

| fixture audio | result |
| --- | --- |
| SAPI speech | **PASS** — keyword hits 4/4, 2 cues both carrying keywords |
| speechless `sine` (the pre-existing fixture) | **FAIL** — "the transcription completed but produced ZERO segments" |

**It gates nothing.** `e2e.yml` is `workflow_dispatch` + nightly `cron` only, so
this proves the capability nightly and on demand; it cannot prevent a
transcription regression from merging.

### Packaged data-pipeline: a documented CI limitation

`preview.spec.ts` resolves the app via `fixtures.findBuiltApp()`, which PREFERS
the shipped package and asserts `app.isPackaged` matches what it launched. Its
**data-pipeline** assertions (seeded library item, real `<video>` playback, NLE
export) need the sidecar to answer RPCs. A **cold** packaged launch first runs the
documented first-run bootstrap — it `pip install`s the heavy sidecar runtime into
`<configDir>/envs/sidecar` (electron-builder ships only the sidecar SOURCE + the
embeds; the wheels install on first run). That install is multi-minute and
network-bound, so a cold packaged pipeline cannot answer RPCs inside a CI test
window. `packaged.spec.ts` reads the packaged main-process log and proves that
bootstrap fires from the `.exe`. So in CI the **shell** is verified against the
real `.exe` (`packaged.spec`) while the **data-pipeline** runs against the dev
build (`preview.spec` with `RF_E2E_DEV=1`) on every OS leg. Set `RF_E2E_DEV=1`
locally to force the dev build; omit it (with a warm first-run env) to drive a
real package end-to-end.

## Wave-2b: VISUAL screenshot-diff + A11Y (`e2e/visual/`)

A deterministic, no-cloud visual-regression + accessibility suite over the
renderer surfaces, run via its OWN config (`playwright.visual.config.ts`) so its
platform-specific screenshot baselines never burden the 4-OS `e2e-gui` matrix.

| Spec | What runs | Surfaces |
| --- | --- | --- |
| `library.visual.spec.ts` | The visual spike: `toHaveScreenshot` against the seeded Library tab; proves a pixel-stable diff against a real `_electron.launch` window. | Library |
| `surfaces.visual.spec.ts` | `toHaveScreenshot` baselines for the rest of the tabs/panels. | Create, Director, Repurpose, Settings → Models & System, Settings → Providers & Keys, the Spend-cap card, and the Workspace preview (`<video>` masked) |
| `a11y.a11y.spec.ts` | `axe-core` scan asserting **zero serious/critical** WCAG 2.0/2.1 A+AA violations on every panel, plus keyboard-nav reaches interactive controls, `:focus-visible` paints the focus ring, and `prefers-reduced-motion: reduce` collapses animations. | all of the above + global chrome |

**Determinism** (see `e2e/visual/_visualSetup.ts`): the BrowserWindow is pinned
to 1280×820, reduced-motion is emulated + `animations: 'disabled'`, and the
non-deterministic live regions (the moving `testsrc` `<video>` frame, the CPU/RAM
`ResourceBar`, provider usage numbers, month-to-date spend) are **masked**, never
asserted. A small `maxDiffPixelRatio` absorbs sub-pixel AA/font-hinting noise.

**axe under Electron** (`runAxe` in `_visualSetup.ts`): `@axe-core/playwright`'s
`AxeBuilder.analyze()` calls `browserContext.newPage()`, which the Electron
embedder rejects; and the renderer ships a strict CSP (`script-src 'self'`) that
blocks inline `addScriptTag`. So axe is injected via `page.evaluate` (the CDP
`Runtime.evaluate` channel, which bypasses the page CSP) and run with `axe.run()`
in-page — no new page, CSP-safe.

This suite found (and this branch FIXED) real serious violations: low-contrast
faint text (`--text-faint` failed WCAG 1.4.3), a "Recommended" badge using an
undefined `--on-accent` token (~1.02:1 on amber), and the Library row using a
`role="button"` `<li>` that both broke list semantics and nested the focusable
Remove button (`only-listitems` / `nested-interactive`).

**Baselines are Windows-only** (`*-win32.png`). The CI step runs only on the
Windows `e2e-gui` leg (a11y is OS-independent but rides the same leg). Regenerate
after an intentional UI change:

```sh
npm run test:e2e:visual         # check against committed baselines
npm run test:e2e:visual:update  # regenerate the `*-win32.png` baselines
```

## Prerequisites

- `npm run build` (or `npx electron-vite build` for the preview-only path) so
  `app/out/main/main.js` exists.
- `ffmpeg` on PATH (or `RF_FFMPEG`) — generates the real H.264/AAC sample.
- Python 3.12 reachable as `py -3.12` (or set `RF_PY` to the interpreter path).
  The sidecar runs on the **standard library only** — no ML deps needed for the
  preview path (`library.add` / `library.list` / `media.playable` / `nle.export`).
- `transcribe-journey.spec.ts` ONLY: `faster-whisper==1.2.1` in that interpreter
  (`e2e.yml` installs it on the Windows leg), plus network access to
  huggingface.co for the 74.6 MB `tiny` snapshot on the first run. Windows only —
  the speech fixture needs SAPI. It needs no `assets.ensure` and no GPU (it pins
  `transcribeDevice: 'cpu'`).

## Run

```sh
npm run test:e2e        # every Playwright Electron GUI spec
npm run test:e2e:dom    # vitest DOM proof (caption.dom.test.tsx)
npm run typecheck:e2e   # type-check the harness

# one spec at a time (the arg is a regex over spec paths)
npx playwright test --config playwright.config.ts preview
npx playwright test --config playwright.config.ts transcribe-journey
```

The harness seeds a fresh per-run `MEDIA_STUDIO_CONFIG_DIR` and registers the
sample through the real `library.add` JSON-RPC (the native "Add videos" dialog
cannot be driven headlessly; seeding the data root the sidecar reads is
equivalent — the app lists, opens, and plays the same library record).
