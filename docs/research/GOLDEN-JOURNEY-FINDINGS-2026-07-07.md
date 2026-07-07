# Golden-Journey Findings — "shorts don't generate" root-caused + fixed (2026-07-07)

A held-out end-to-end acceptance test (`app/e2e/golden-journey.spec.ts`) was added as the single
external **done-signal** for Make Shorts, then run against the real Electron GUI + live Python
sidecar. It red-repro'd "shorts don't generate" and, iterating red→fix→red, uncovered **four**
layered blockers — three real Windows-only code bugs (now fixed) and one provisioning requirement.
With the three fixes, the full pipeline **produces a real vertical short end-to-end** (proven).

## Why the whole test suite was green while the app was broken
- `features/reframe.py:27`: the module is deliberately *"unit-testable with no WSL, no mediapipe,
  and no real verthor"* — the tests mock the verthor seam.
- `features/stabilize.py`: the ffmpeg runner is an injected seam, so unit tests never spawn real
  ffmpeg; and CI runs on **Linux**, where paths are `/tmp/...` (no drive colon), so the
  Windows-path bug can't manifest.
Result: **100% coverage, green units — and a Make Shorts flow that never produced a file on
Windows.** Textbook coverage-theater: the done-signal (coverage/green units) is a proxy the tests
control; the real A→B→C journey was never executed. The golden-journey executes it.

## The Make Shorts pipeline (per candidate)
CUT → SILENCE-TRIM → STABILIZE → (REMOVE-FILLERS, skipped when silence-trim on) → REFRAME
(1080×1920) → AUTO-ZOOM → CAPTION (libass) → EXPORT. The red-repro produced only `sample-1.cut.mp4`
(640×360) at `pct:0` — dying entering the first post-cut stage.

## Bug 1 — CRLF in the WSL scripts  *(FIXED — commit 789300d)*
`sidecar/media_studio/scripts/verthor_reframe.sh` + `build/wsl-verthor-bootstrap.sh` had stale CRLF
in the working tree (`core.autocrlf=true`, predating `.gitattributes eol=lf`; blobs already LF).
WSL bash aborts on `set -euo pipefail\r` ("set: pipefail: invalid option name"). **Fix:** normalize
working copies to LF + explicit `*.sh text eol=lf` guard.

## Bug 2 — verthor teardown SIGSEGV  *(FIXED — commit 789300d)*
verthor renders a valid 1080×1920 h264 short and flushes it (verified: ffprobe h264·1080·1920·60f),
then SIGSEGVs (exit 139) at interpreter teardown (mediapipe/tflite/torch atexit, CPU-only). The
wrapper's `set -e` aborted before its output check. **Fix:** disable errexit around the call and gate
success on an EXTERNAL signal — a genuinely valid video at `$OUT` (exists + ffprobe dims + duration).
Missing/short/undecodable output still hard-fails; only a post-render teardown crash is tolerated.

## Bug 3 — vidstab .trf path breaks the ffmpeg filtergraph on Windows  *(FIXED — commit b2deba8)*
STABILIZE runs `vidstabdetect=...:result=<trf>`; the `.trf` path is embedded in the `-vf` filtergraph
where `:` separates options, so an absolute Windows path (`C:\...`) makes ffmpeg read `result=C` then
reject the rest → EINVAL. **No escaping form works** (verified against ffmpeg 8: `C\:/`, `C\\:/`,
quoting, native backslashes all fail as clean argv). **Fix:** reference the `.trf` by BARE basename
and run both ffmpeg passes with `cwd=<trf dir>` (adds an optional `cwd` to `ffmpeg.run`); in/out paths
stay absolute. Regression test added.

## Blocker 4 — claudeshorts needs the YuNet model provisioned  *(SETUP, not a code bug → handoff)*
Past stabilize, the default `reframeEngine:"auto"` resolves to the **claudeshorts** engine, which
raises `ClaudeShortsBackendUnavailableError: the YuNet face-detection model is not provisioned — run
first-run setup (or assets.ensure)`. This is a provisioning/setup step (a real install downloads the
sha256-pinned ONNX at first-run); the E2E's fresh data root doesn't. Not a code defect.

## END-TO-END VERDICT — the pipeline WORKS
Forcing `reframeEngine:"verthor"` (the fixed engine; the WSL verthor install is present), the full
export **completes and returns a real short**:
`job.done → {"clips":[{"path":".../01-sample.mp4"}], "items":[...]}`. So the three code fixes genuinely
unblock Make Shorts. The `auto`/claudeshorts default additionally needs the YuNet model provisioned.

## Golden-journey status (2026-07-07)
- **Primary test GREEN** — `Make Shorts produces a real vertical short file on disk` PASSES on the
  DEFAULT `auto`→claudeshorts path after the E2E provisions YuNet in `beforeAll` (`provisionAssets`
  in `fixtures.ts`, mirroring a real first-run). A real user's Make Shorts genuinely works.
- **Secondary `no console errors` test — one known FAIL (cosmetic).** It surfaces a single 404, now
  precisely captured (the spec logs the failing URL): `mstream://media/thumb:<dataRoot>\thumbnails\
  <videoId>.jpg` — the Library card's SOURCE-video poster frame for the freshly-seeded sample. The
  poster `.jpg` is never generated for an out-of-band-seeded video (a real import generates it on
  demand via `useVideoThumbnail`→`library.thumbnail`). It is **cosmetic** (the card degrades to the
  ▶ glyph) and **tangential to Make Shorts**. Fix options for the finishing session: (a) seed the
  poster in the E2E — `library.thumbnail` is an ASYNC job, so it needs a job-wait like
  `provisionAssets` (a one-shot RPC returns before the `.jpg` is written); or (b) have the renderer
  suppress/guard the `thumb:` request until the poster exists. Keep `golden-journey.spec.ts` as the
  Make Shorts merge gate: coverage is necessary, never sufficient.

## The reusable lesson
A held-out golden-journey that drives the **real** app and asserts a **real artifact on disk** is the
only signal that catches this class of bug. All three code bugs were Windows-only and lived exactly at
the seams the unit tests mock and CI (Linux) can't reach.
