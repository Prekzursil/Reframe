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
| `add-videos-dialog.spec.ts` | Drives the **"Add videos" button a real user clicks**, end to end: `.library__add-btn` → `Library.handlePick` → the preload `window.api.openVideos` → `ipcMain.handle('dialog.openVideos')` → `dialog.showOpenDialog` → `library.add`. Only the OS widget is substituted (`electron-playwright-helpers` `stubDialog` replaces `dialog.showOpenDialog` inside the RUNNING main process), so every other link is real and **no production seam was added**. Both-states by construction — the CANCEL case and the PICK case are the identical click on identical wiring, differing only in the injected dialog result; a third case injects a nonexistent path and requires the **sidecar's own** wording ("video not found") to reach the toast, text the renderer cannot author. A fourth signal is mechanically independent of the DOM: `fixtures.listLibraryVideos()` re-reads the data root through the real `library.list`, so an optimistically-painted card cannot pass. | **GUI-VERIFIED** (live app + live sidecar; the OS dialog window itself is out of reach by construction). |
| `installed-app.spec.ts` | The **INSTALLED** app (not `dist/win-unpacked`), resolved via `RF_E2E_APP_EXE`: asserts the running binary is a PACKAGED one from **outside** both `dist/` and the repo checkout (the `process.execPath == built.executablePath` comparison alone was **REFUTED as a tautology** — see below — so the out-of-repo check is what discriminates), that the **install directory's** `resources/bin/ffmpeg` carries every encoder the pipeline hardcodes (the NSIS-layout parity measurement), that the **cold first-run bootstrap COMPLETES** and the app's own bundled runtime then answers `library.list`, and that the seeded video really decodes. Self-skips **loudly** when `RF_E2E_APP_EXE` is unset. | **UNVERIFIED — never yet observed green.** Producing an installed app needs the full staging pipeline plus a silent NSIS install, which its author did not run. Settling experiment: the `drive_installed_build` dispatch input in `.github/workflows/e2e.yml`. The escape hatch's *resolution* contract IS measured, deterministically, by `findBuiltApp.test.ts`. |
| `findBuiltApp.test.ts` | vitest, every OS leg. Pins `RF_E2E_APP_EXE` resolution against a **synthetic** installed tree — no Electron, no package, no installer, no GUI: the variable wins over `RF_E2E_DEV`, satisfies `RF_E2E_REQUIRE_PACKAGED`, fails **loud** on a path that does not exist AND on one that exists but is not an app tree (never a silent dev-build fallback), returns the executable the caller *named* rather than one re-derived by `readdirSync` — for **both** shapes, `.exe` and `.app` — and pins `bundledFfmpegPath`'s layout per target. | **RESOLUTION-VERIFIED for the cases listed** (15/15; the sibling-decoy and `bundledFfmpegPath` arms are RED-first-verified). Previously read "7/7; mutation-checked", which was **REFUTED**: the `.app` branch was delegated to `parseElectronApp` and returned a SIBLING bundle, the macOS fixture had no decoy to catch it, and the fail-loud case survived deleting its own `existsSync` guard. See the `Refuted claims` section below. |
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
  `HF_HOME`: **6 model blobs / 78,207,087 B = 74.6 MB** (14 files in the repo dir
  once the snapshot symlinks and `refs/` are counted). **So this leg needs network;
  it is NOT an offline proof** (the same dependency the `e2e-sidecar` leg already
  carries). Making it offline would mean registering a pinned `tiny` asset, which
  adds a user-visible component to `assets.list` for the sole benefit of a nightly
  test — deliberately not done.
- **The fetch is forced ANONYMOUS** (`HF_HUB_DISABLE_IMPLICIT_TOKEN=1`, set on the
  app env in the spec). `fixtures.definedEnv` copies the whole ambient environment
  into the app env, so the sidecar inherits any `HF_TOKEN` the developer exported —
  and huggingface_hub sends it implicitly *even for a public repo*, so a token that
  no longer authenticates turns the public `tiny` fetch into
  `RepositoryNotFoundError: 401` ("the model does not exist"). MEASURED on this box
  end-to-end through the spec: **without** the override, a cold-`HF_HOME` run goes
  red in 41 s carrying `User Access Token "Reframe" is expired`; **with** it, the
  same cold cache and the same ambient token pass. Isolated four ways on a fresh
  empty `HF_HOME` — huggingface_hub 1.27.0 and 1.26.0 (the lock pin), each with and
  without the flag: ambient token → 401 (cache left at 5,698 B), flag → OK. The
  credential is not touched (AGENTS.md §9); the consumer is fixed, which also
  covers *any* `HF_TOKEN` that 401s (revoked / wrong org / insufficient scope).
  A GitHub runner has no `HF_TOKEN`, so CI was already anonymous and is unchanged.

**BOTH-STATES verified — for the TRANSCRIPT arm.** Same spec, same code, only the
fixture's audio changed:

| fixture audio | result |
| --- | --- |
| SAPI speech | **PASS** — keyword hits 4/4; 2 cues, both carrying keywords |
| speechless `sine` (the repo's own 3 s fixture) | **FAIL** — "the transcription completed but produced ZERO segments" (failing test 12.6 s) |

Two honest limits on that table — because a both-states claim that overreaches is
worse than none — and one extra arm that IS measured:

- **The CAPTION arm is not both-states controlled.** The broken run aborts at the
  zero-segments assertion, so the caption half never executes with speechless
  audio. Those assertions are fail-closed *by construction* (they require
  `.cue-list .cue-row` to appear and then require cue text to be non-empty and to
  carry a keyword), but "fail-closed by construction" is a code-reading, not a
  measurement. The settling experiment is to seed a transcript with segments and
  break `subtitles.generate`.
- **The keyword THRESHOLD is controlled elsewhere.** With speechless audio there is
  no transcript at all, so the `SPEECH_KEYWORD_MIN_HITS` comparison is never
  evaluated in the broken state. `speechKeywords.test.ts` (vitest, every OS leg)
  covers its failing direction directly — a 1-hit transcript must be below the
  floor — and is mutation-checked: setting the floor to 1 turns that case red.
- A THIRD arm is measured too: **ASR error**. A cold `HF_HOME` plus an ambient
  `HF_TOKEN` that 401s lands on the panel's `p.error[role="alert"]` in 41 s with the
  sidecar's own reason, rather than timing out anonymously.

**It gates nothing.** `e2e.yml` is `workflow_dispatch` + nightly `cron` only, so
this proves the capability nightly and on demand; it cannot prevent a
transcription regression from merging.

**It runs as its OWN CI step, after the visual/a11y gate**, not inside the shared
`npm run test:e2e` invocation. A red Playwright step makes later steps inherit
GitHub's implicit `success()` gate, so folding the most environment-dependent spec
in the repo (an `en-*` SAPI voice on the image plus huggingface.co egress) into that
one invocation would let its first red silently drop visual + a11y coverage. This
repo has already measured that cascade on run 30612141716. Everything after this
step carries `always()` or `!cancelled()`, so its own red suppresses no artifact.

**The cascade is now closed at the ROOT as well** (2026-08-11). Every mitigation
until then was per-spec, which meant each newly added spec had to re-derive the
reasoning — and the v1.5 lane got it wrong for `add-videos-dialog.spec.ts`, placing
it in the shared invocation on an argument (*"a spec that cannot fail cannot start
the cascade"*) that only holds for `installed-app.spec.ts`, which self-skips.
`add-videos-dialog` **can** fail, and `--list` showed it sorting FIRST of the eight
spec files, ahead of `packaged`, `preview` and the proven `golden-journey`. So the
blocking visual/a11y step now carries `!cancelled()`: it still diffs the committed
baselines and still fails the leg on a mismatch, it simply can no longer be SKIPPED
because something unrelated went red. `always()` is still withheld, so a cancelled
run cannot start a screenshot suite.

`add-videos-dialog` also moved to its own step (after `transcribe-journey`), because
it launches its own Electron app plus a cold sidecar and needs a 60 s `beforeAll`
wait. **The shared Windows step now names the files it runs** rather than excluding
by pattern: a second name cannot be added to `--grep-invert` on Windows —
`"a|b"` has its `|` eaten by the shell npm spawns (*exit 255*), and two
`--grep-invert` flags leave only the last one in effect (measured: `--list` still
enumerated the transcribe-journey tests). Current counts, re-measured:
`--list` alone **37 in 8 files**; the shared step's positive list **30 in 6**;
`--list add-videos-dialog` **5 in 1**.

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

**PARTLY ADDRESSED, and only on demand.** `installed-app.spec.ts` +
`RF_E2E_APP_EXE` exist precisely to observe the case the paragraph above declares
out of reach: it waits for the cold bootstrap to **finish** (default 15 min,
`RF_E2E_COLD_TIMEOUT_MS`) and then drives the pipeline through the app's own
bundled runtime, with `MEDIA_STUDIO_PYTHON` / `MEDIA_STUDIO_SIDECAR_DIR` stripped
from the launch env so the repo's sidecar and the host interpreter cannot stand in
for the packaged ones. It runs ONLY when the `drive_installed_build` dispatch input
is checked, and — restating the row in the table above rather than letting the
reader infer it — **it has never been observed green**, so nothing in it may be
cited as evidence yet.

Two facts that narrow the *shape* of the remaining risk without closing it:
`bundledFfmpegPath()` is derived from the executable's own path, and an installed
tree was verified BY HAND to contain that exact path — so NSIS is believed to lay
resources out identically to `win-unpacked` (*likely*, 80%; one hand inspection, no
automated check). `installed-app.spec.ts`'s encoder test is what would turn that
belief into a measurement, because it probes the **install directory's** binary.

### Refuted claims (2026-08-11 adversarial round) — recorded, not deleted

Four sentences in this harness were wider than their evidence. Each is corrected at
its source; they are collected here so a reader who remembers the old wording knows
it was withdrawn rather than quietly edited away.

1. **"a macOS `.app` argument is a bundle DIRECTORY, so the derived `info.executable`
   is the right answer"** (`fixtures.ts`) — REFUTED BY EXECUTION. `parseElectronApp`
   strips a `.app` to its PARENT and picks `readdirSync(parent).find(f =>
   f.endsWith('.app'))`, so with a sibling `Aardvark.app` present, asking for
   `Reframe.app` returned `Aardvark.app/Contents/MacOS/Aardvark` for the executable
   AND `Aardvark`'s entry for `main` — silently. `/Applications` is the documented
   install location and holds every other app on the machine, so this was the
   canonical input, not an edge case. Fixed by deriving from inside the named bundle.
2. **`RESOLUTION-VERIFIED (7/7; mutation-checked)`** — REFUTED. The macOS fixture
   built a fresh `mkdtemp` holding exactly ONE bundle while the Windows arm got an
   explicit decoy, so the suite could not observe (1). Separately the fail-loud case
   was a SURVIVING MUTANT: deleting the `existsSync` pre-check left all seven green,
   because the fall-through error also contains `RF_E2E_APP_EXE` and the path.
3. **"the running process IS the installed executable"** (`installed-app.spec.ts`) —
   REFUTED as a tautology: `resolveInstalledApp` returns the caller's `.exe` verbatim
   and Playwright launches exactly that, so the comparison reduces to
   `resolve($RF_E2E_APP_EXE) === resolve($RF_E2E_APP_EXE)`. `isPackaged` and an
   appPath containing `resources` are both satisfied by `dist/win-unpacked` too — the
   very target the spec's skip message warns against. An out-of-repo check was added.
4. **"Only `MEDIA_STUDIO_CONFIG_DIR` travels"** (`installed-app.spec.ts`) — the code
   deleted two keys while `definedEnv` copies the whole ambient environment, and
   `buildSidecarEnv` resolves each packaged default as `env.X ?? <resources>` (its own
   header: "Pre-set env vars always win"). So an ambient `MEDIA_STUDIO_FFMPEG` would
   have beaten the shipped binary. Resolved by widening the CODE to match the claim
   (every ambient `MEDIA_STUDIO_*` except `CONFIG_DIR` is now deleted, asserted), not
   by narrowing the sentence.
5. **"two independent signals that this is a real install"** (`e2e.yml`) — only one
   was asserted; the NSIS uninstaller was passed to `Write-Host`. Now a `throw`.

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
- `transcribe-journey.spec.ts` ONLY: `faster-whisper==1.2.1` in that interpreter,
  plus network access to huggingface.co for the 74.6 MB `tiny` snapshot on the
  first run. Windows only — the speech fixture needs SAPI. It needs no
  `assets.ensure` and no GPU (it pins `transcribeDevice: 'cpu'`). Install it the
  way `e2e.yml` does, so the transitives match the shipped stack instead of
  floating (measured: unconstrained gives `av 18.0.0` against lock `av==17.1.0`):

  ```sh
  pip install "faster-whisper==1.2.1" --constraint sidecar/requirements.lock.txt
  ```

  A stale or mis-scoped `HF_TOKEN` in your environment does **not** break this —
  the spec forces the HF fetch anonymous. You do not need to unset anything.

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
sample through the real `library.add` JSON-RPC.

**Corrected scope of that shortcut.** This paragraph used to justify it with "the
native 'Add videos' dialog cannot be driven headlessly; seeding the data root the
sidecar reads is equivalent". Both halves need narrowing:

- Seeding is equivalent for everything **downstream** of the add — the app lists,
  opens and plays the same library record either way — and it is **not** equivalent
  for the add itself, which is a five-hop chain (button → renderer handler →
  preload bridge → ipc handler → dialog → RPC) that no spec exercised. A broken
  preload wiring would have shipped green with a "Native file picker unavailable"
  toast and nothing watching.
- Only the **OS widget** is undrivable, not the chain. `add-videos-dialog.spec.ts`
  drives the chain by replacing `dialog.showOpenDialog` inside the running main
  process, so seeding remains the right default for the other specs (it is faster
  and it is not what they are testing) rather than the only option.

```sh
npx playwright test --config playwright.config.ts add-videos-dialog

# the INSTALLED build (Windows): needs a real silent install first, and self-skips
# loudly without the variable. Point it at the INSTALLED exe, never at dist/.
RF_E2E_APP_EXE="C:/Program Files/Reframe/Reframe.exe" \
  npx playwright test --config playwright.config.ts installed-app
```
