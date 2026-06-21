# Reframe GUI / preview E2E harness

Real end-to-end verification that a user sees a **working preview**, launched
against the actual built Electron app and the live Python sidecar — no stubs.

## What it proves

| Spec | What runs | Verification level |
| --- | --- | --- |
| `preview.spec.ts` | Launches the real app via `playwright._electron.launch`, opens an imported sample video, asserts the preview `<video>` gets an `mstream://` src, reaches `readyState >= 2`, and `currentTime` **advances** after `play()` (real decode). Also asserts no console errors across the whole session; Library / Workspace / Shorts panels and the SemanticSearch + NleExport tab panels mount (panel-specific selectors); clicking the real **Export timeline** button writes a real `.edl` file to disk. The exported timeline is a valid CMX3600 EDL with **0 clips** (no shortmaker clips exist without ML candidate generation) — a real file, not edited video. | **GUI-VERIFIED** (live app + live sidecar) |
| `caption.dom.test.tsx` | Renders the real `CaptionOverlay` component over a real `<video>` with word-level cues in the exact shape `captions.cues` returns, and asserts the active caption word is painted in the DOM over the frame. | **DATA-PATH-VERIFIED** — the *live* caption overlay (`CandidateReview`) sits behind ML candidate generation (whisper transcript + LLM clip selection), which is not reachable without the model stack, so caption-over-video is proven at the component+DOM level. |

`DirectorPanel` is NOT mounted anywhere in the running renderer (only its own
file + unit test exist), so it is covered by its existing
`panels/DirectorPanel.test.tsx`, not by a GUI assertion.

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
