# Reframe GUI / preview E2E harness

Real end-to-end verification that a user sees a **working preview**, launched
against the actual built Electron app and the live Python sidecar — no stubs.

## What it proves

| Spec | What runs | Verification level |
| --- | --- | --- |
| `preview.spec.ts` | Launches the real app via `playwright._electron.launch`, opens an imported sample video, asserts the preview `<video>` gets an `mstream://` src, reaches `readyState >= 2`, and `currentTime` **advances** after `play()` (real decode). Also asserts no console errors across the whole session; Library / Workspace / Shorts panels and the SemanticSearch + NleExport tab panels mount (panel-specific selectors); clicking the real **Export timeline** button writes a real `.edl` file to disk. The exported timeline is a valid CMX3600 EDL with **0 clips** (no shortmaker clips exist without ML candidate generation) — a real file, not edited video. | **GUI-VERIFIED** (live app + live sidecar) |
| `caption.dom.test.tsx` | Renders the real `CaptionOverlay` component over a real `<video>` with word-level cues in the exact shape `captions.cues` returns, and asserts the active caption word is painted in the DOM over the frame. | **DATA-PATH-VERIFIED** — the *live* caption overlay (`CandidateReview`) sits behind ML candidate generation (whisper transcript + LLM clip selection), which is not reachable without the model stack, so caption-over-video is proven at the component+DOM level. |
| `packaged.spec.ts` | Launches the **shipped electron-builder package** (the real `.exe`, resolved via `electron-playwright-helpers` `findLatestBuild`/`parseElectronApp`) and asserts `app.isPackaged === true`, that it runs out of `resources/app.asar`, that the packaged renderer boots with no console errors, and that the packaged main process inherits the seeded env + fires its first-run bootstrap. **WINDOWS-ONLY** (self-skips elsewhere — only the Windows CI leg builds a package). | **PACKAGED-SHELL-VERIFIED** (the shipped binary boots & is correctly wired). |
| `nasty_captions.dom.test.tsx` | Feeds the real `CaptionOverlay` hostile caption data (unicode/RTL/emoji, empty/out-of-window cues, zero-duration/overlapping cues, a 10k-word timeline) and asserts graceful DOM output, never a crash. | **NASTY-INPUT-VERIFIED** (GUI leg). |

`DirectorPanel` is NOT mounted anywhere in the running renderer (only its own
file + unit test exist), so it is covered by its existing
`panels/DirectorPanel.test.tsx`, not by a GUI assertion.

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

## Prerequisites

- `npm run build` (or `npx electron-vite build` for the preview-only path) so
  `app/out/main/main.js` exists.
- `ffmpeg` on PATH (or `RF_FFMPEG`) — generates the real H.264/AAC sample.
- Python 3.12 reachable as `py -3.12` (or set `RF_PY` to the interpreter path).
  The sidecar runs on the **standard library only** — no ML deps needed for the
  preview path (`library.add` / `library.list` / `media.playable` / `nle.export`).

## Run

```sh
npm run test:e2e        # Playwright Electron GUI E2E (preview.spec.ts)
npm run test:e2e:dom    # vitest DOM proof (caption.dom.test.tsx)
npm run typecheck:e2e   # type-check the harness
```

The harness seeds a fresh per-run `MEDIA_STUDIO_CONFIG_DIR` and registers the
sample through the real `library.add` JSON-RPC (the native "Add videos" dialog
cannot be driven headlessly; seeding the data root the sidecar reads is
equivalent — the app lists, opens, and plays the same library record).
