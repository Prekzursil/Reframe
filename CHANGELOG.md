# Changelog

All notable changes to Reframe — Media Studio are documented here.
This project adheres to [Semantic Versioning](https://semver.org/).

## [1.4.0] — 2026-07-07

**Reframe v1.4 — the experience overhaul.** One big release that turns the raw
first-run into a plug-and-play experience: it kills the three errors that greeted
new installs, makes setup visible and choosable, surfaces where every clip came
from, and re-skins the whole app in a calm cool blue-gray. Almost all of it is
wiring + making existing machinery visible, not new capability. Ships **in place**
over the existing GitHub-Releases auto-update feed (the bump to **1.4.0** is what
lets that feed report an update at all — 1.3.0 reports "no update" to itself).
Both coverage gates stay at **strict 100% line + branch** (renderer vitest **and**
sidecar pytest) under the single `quality` CI gate.

### Fixed — the three first-launch errors are gone

- **"Sidecar is not running" on first launch** — the app no longer drops you into
  a dead Library while Python and the models are still installing. A full-screen
  **"Setting up Reframe"** first-run screen now stands in for the tabbed shell
  while provisioning, driven by the real `bootstrap.progress` stream (phase +
  progress bar), and auto-transitions into the app the moment the sidecar reports
  **running**. Setup failures / offline / partial states are first-class in that
  view with a **Retry** (no dead-end, no raw crash banner).
- **Player preview "code 4" / clipped-at-the-top** — the preview is now
  sidecar-state-aware: while the playback proxy is still building it shows
  **"Building preview…"** (not a raw exit-code), reloads when `proxy.state` goes
  ready, and reports a real error loudly with its actual reason. The
  fixed-height/overflow CSS that cut the frame "in half at the top" is fixed.
- **Settings / first-run confusion** — the local-vs-cloud **FirstRunChooser** that
  was buried in Settings is surfaced into the first-run flow, so the choice is made
  up front instead of failing later.

### Added — in-app install profiles (Min / Default / Full / Custom)

- **Choose what gets installed, in the app, on first run.** A first-run profile
  picker (**Minimum · Default · Full · Custom**) shows what each level includes,
  why, and its approximate download size, then routes the choice into first-run
  bootstrap (which previously spawned with no arguments and always fetched the same
  set). The profile→asset map is a **single source of truth** with a conformance
  test asserting it stays a superset of the CORE model floor (YuNet / S3FD / LR-ASD)
  and matches the sidecar — every level keeps that floor so the app never silently
  falls back to a plain center crop.

### Added — Library provenance, relink & keep-a-copy

- **See where every clip came from.** Each library item now shows its **source
  path**, an **on-disk / MISSING** badge, and **open-in-folder**; a moved or
  renamed source can be **relinked** with a content-hash verify so you re-point to
  the right file, not just any file. Existing videos get their `content_hash`
  back-filled lazily (pin-on-view) so relink works for the clips you already have,
  not only new adds; a source that is already gone surfaces "relink unavailable"
  honestly.
- **Keep a managed copy of originals (opt-in).** An opt-in keep-a-copy imports a
  managed duplicate of source files with a **free-space preflight**, content-hash
  dedup, a cumulative size cap + meter, and an **atomic** copy (temp + replace with
  rollback) so it never half-writes or silently doubles your disk use.

### Added — API keys: reveal & live usage

- **Providers & Keys** lets you **reveal** a stored key on demand and shows
  **per-key live usage**, so you can confirm the right key is set and watch spend —
  while the key stays redacted over the RPC/IPC bridge by default and is never
  logged.

### Changed — cool blue-gray visual overhaul

- **A calm, cool blue-gray re-skin, token-first.** Design tokens v2 lift the base
  off near-black toward a faint cool blue-gray and **widen the surface ladder** so
  cards, panels, and wells stratify with real elevation and a top-lit atmosphere;
  every component inherits it. A humanized header replaces the QUALITY/ROUTING
  jargon with plain-language iconed toggles ("Runs on: This computer / Cloud",
  "Where jobs run: …") plus an egress dot and a Jobs status pill (same values and
  handlers — relabel only, **local stays default, cloud strictly opt-in**). A
  designed state system lands skeleton-shimmer loading, ghost-poster empties, a
  calm-amber **"Reconnecting…"** (hard-red reserved for true failure), and a framed
  player error card; cards, buttons, tabs, and inputs get signature hover / focus /
  active states. **AA contrast is re-verified and the `tokens.conformance` test
  stays green.**

### Added — in-place auto-update (safe by construction)

- **Updates land in place over GitHub Releases** — a packaged build checks the feed
  on launch and drives an in-app update banner (electron-updater;
  download-then-quit-and-install). Because a working install can be bricked by a bad
  update, v1.4 lands its safety net **first**: a **single-instance lock** (plus a
  data-root-scoped lock so two distinct copies pointed at one relocatable data
  folder also mutually exclude) prevents two bootstraps racing into the same env /
  `library.db`, and a **version-aware re-bootstrap** gates first-run on a persisted
  shipped-requirements **fingerprint** (not just marker existence) so an update that
  adds Python deps re-provisions the env instead of starting the sidecar against a
  stale one ("No module X"). A version-triggered re-bootstrap is **silent** and
  reuses the saved profile — it never re-prompts.

### Changed — display name & icon unified to "Reframe"

- **One user-facing name and a real app icon.** The window title, in-app header,
  Electron About panel, and installer / Start-menu shortcut all read **"Reframe"**,
  and the app ships its production multi-size icon. The About panel reads the
  version **dynamically** via `app.getVersion()`, so it tracks the package version
  with no hardcoded string. The internal id **`media-studio`** is deliberately
  unchanged — the package `name`, the `local.media-studio` appId, the `${name}`
  installer-artifact filename, and every appData/path literal keep it so **first-run
  state, the data root, proxy/peak/dub caches, and the sidecar-env sentinel survive
  the upgrade untouched**. A brand guard test asserts no user-facing surface leaks
  "media-studio" / "Media Studio".

### Legal — NON-COMMERCIAL while ViNet-S is bundled

- **Reframe v1.4 still bundles the ViNet-S saliency model under CC-BY-NC-SA-4.0.**
  ViNet-S (the no-face crop-tracking video-saliency network, ICASSP 2025,
  arXiv:2502.00397) is licensed **Attribution-NonCommercial-ShareAlike 4.0**, so
  **the app as shipped is NON-COMMERCIAL while that model is bundled**. A future
  paid tier MUST remove or replace ViNet-S. Its required attribution — © 2025
  Rohit Girmaji, Siddharth Jain, Bhav Beri, Sarthak Bansal, Vineet Gandhi (IIIT
  Hyderabad) — plus the other bundled model licenses (YuNet MIT, EdgeTAM
  Apache-2.0, TransNetV2 MIT, LR-ASD MIT) are surfaced **in-app** at
  **Settings → Licenses** and in the repo-root **`NOTICE`** file; the vendored
  full CC-BY-NC-SA-4.0 text ships at
  `sidecar/media_studio/features/_vinet_s/LICENSE`.

### Rolling back to 1.3.0

- **If a 1.4 update ever misbehaves, you can go back.** Download and re-run the
  **1.3.0** installer from the
  [Releases page](https://github.com/Prekzursil/Reframe/releases) — it installs
  over the top and, because the internal id, appId, and every appData/path literal
  are unchanged across the upgrade, your **userData and the data root (library,
  keys, proxies, caches, installed models) are preserved**. Nothing is migrated
  destructively, so a downgrade re-uses the same data folder.

### Roadmap

- **A dedicated Reframe Director panel is a v1.5 item.** v1.4 promotes
  reframe-to-vertical to a first-class action and wires the existing override
  controls; the fuller prompt-driven Reframe Director surface is planned for **1.5**.

## [1.2.0] — 2026-07-03

**Reframe v1.2.0 — detector, virality, tracking + fail-loud hardening.** A single
native **YuNet** face detector replaces the old MediaPipe/haar + HOG path in the
default reframer; the candidate list gains a **virality highlight badge**; an
**EdgeTAM** opt-in tracker lands behind an explicit setting; the multi-speaker
diarizer's **SpeechBrain** dependency is declared and pinned with a typed
fail-loud; and the no-silent-fallback posture is hardened across the reframe and
provisioning paths. All open **CodeQL** alerts are driven to **zero** (72 → 0,
including the render-CLI `js/path-injection` fix in this release). Both coverage
gates remain at **strict 100% line + branch** (sidecar **and** renderer) under the
single `quality` CI gate.

### Added — YuNet face detector (WU1)

- **YuNet replaces the MediaPipe/haar detector** — the default in-sidecar
  `claudeshorts` reframer now finds faces with **`cv2.FaceDetectorYN`** (a tiny
  **sha256-pinned ONNX CNN** run through OpenCV's bundled ONNX runtime), replacing
  the old haar-cascade face + HOG person/body detectors and dropping the
  `mediapipe` dependency entirely. YuNet holds turned / profile faces far better
  (making the objdetect-dependent HOG body fallback redundant), leaving exactly
  **one native detector surface** to provision. The detection chain is now
  **YuNet face → motion saliency → center** — and a truly face-less, motion-less
  clip still degrades to a plain center crop **with a loud notice**, never
  silently.

### Added — virality highlight badge (WU3)

- **Highlight-score badge (display-only)** — the candidate review list now
  surfaces the unified scorer's `signalScore` (a 0..1 fusion of the legacy LLM
  score with the present-weighted multimodal signal boost, stamped by
  `select_unified`) as a distinct **0-100 "highlight" badge** next to the
  existing within-batch **virality percentile** badge — the two are now labelled
  distinctly (percentile vs highlight), each with its own tooltip. `signalScore`
  is carried through `_coerce_candidate` so it reaches the renderer over the RPC,
  added to both `Candidate` schema copies, and normalized by a pure
  `displaySignalScore` helper. Pure surfacing — selection/ranking is unchanged;
  the badge simply does not render on the frozen path where `signalScore` is
  absent. Both coverage gates stay at strict 100% line + branch.

### Added — EdgeTAM opt-in tracker (WU2)

- **EdgeTAM is an explicit opt-in subject tracker** — setting
  `reframeTracker = "edgetam"` opts IN to the torch-based EdgeTAM tracker; the
  default (`yunet`, or any blank / unknown value) stays on the zero-dependency
  per-frame YuNet face detector. Opting in on a host without the EdgeTAM stack
  (`torch` + `opencv-python`) raises a **loud provisioning error** naming the real
  cause — it never silently falls back to the YuNet default the user did not ask
  for.

### Added — multi-speaker diarizer: SpeechBrain declared + pinned (via #255)

- **SpeechBrain is now a declared, pinned dependency of the `reframe-gpu` extra**
  (`speechbrain==1.0.3`, with `huggingface-hub<1.0`), so the multi-speaker
  diarizer's audio-side model load is reproducible on the GPU host and **fails
  loud with a typed error** when the backend is unavailable rather than degrading
  silently. See `docs/WU-R1-MULTISPEAKER-ENGINE.md` for the pin rationale and the
  Windows `k2_fsa` gotcha. (Landed via PR #255, shipped as part of v1.2.0.)

### Changed — no-silent-fallback hardening (fail loud)

- **Never a silent center-crop or silent model swap.** Every reframe / tracker /
  provisioning path that cannot run raises a **typed, actionable error** (or, on
  the `auto` degrade path, emits a loud `reframe.degraded` notice) instead of
  quietly producing a degraded result. First-run **provisioning** is explicit
  about what it downloads and self-tests, and reports a missing native detector or
  model as a loud failure — no quiet degradation anywhere in the default path.

### Security — CodeQL remediation 72 → 0

- **All open CodeQL alerts driven to zero (72 → 0).** Includes the render-CLI
  **`js/path-injection`** (HIGH) fix: `render.ts` `readJob` now canonicalises the
  argv-supplied job path and **proves it stays inside `os.tmpdir()`** (a
  `path.resolve` + `startsWith` confine-to-base barrier — the TS analog of the
  sidecar's `pathsafe.ensure_within`) before the `readFileSync` sink, on top of
  the existing NUL / `..` guard. Covered by new `jobPath` unit tests.

### Fixed — first-run + Windows stability

- **First-run provisioning** hardened (loud, resumable, checksummed setup of the
  native detector + chosen models).
- **Windows E2E hang** fixed — the opt-in end-to-end suite no longer hangs on
  Windows.
- **Settings crash** fixed — the Settings surface no longer crashes.

## [1.1.0] — 2026-06-29

**Reframe v1.1.0 — the multi-speaker release.** The flagship is a HYBRID
multi-speaker reframe engine that decides per-segment between **cut** (lock onto
the single active speaker), **50-50 split**, and **3-up composite**, driven by a
vendored, GPU-validated **LR-ASD** active-speaker model. Ships alongside tiered
subtitles, model management, media lineage, OpusClip-parity polish, and
foundation hardening. Both coverage gates remain at **strict 100% line + branch**
(sidecar **and** renderer) under the single `quality` CI gate.

### Added — HYBRID multi-speaker reframe engine (the flagship)

- **Per-segment layout decision** — `MultiSpeakerReframeEngine.reframe` analyses
  the active speaker over time and renders each segment as the right layout:
  **cut** (one active speaker, static centered crop), **50-50 vertical split**
  (two concurrently-active speakers, two independently captioned regions), or
  **3-up composite** (host top + two guests bottom). Per-segment
  `build_filter_complex` + ffmpeg concat; pure, unit-tested multi-region
  geometry.
- **LR-ASD active-speaker oracle (vendored, GPU-validated)** — vendored
  numpy-2-clean LR-ASD (Junhua-Liao/LR-ASD, IJCV 2025, MIT) — S3FD detect → IoU
  track → 112-crop → MFCC → windowed ASD score. Proven **bit-identical**
  (max-abs-diff `0.000e+00`) to the reference, so it inherits LR-ASD's published
  **Columbia ASD F1 96.4%** (TalkSet-ft) / **AVA val mAP ~94%**. Audio fusion
  (SpeechBrain VAD + ECAPA diarization) contributes via a diarize→visual-track
  namespace map.
- **R0 evaluation harness** — speaker-attribution, crop-IoU, switch-latency,
  layout-match, and within-segment static-jitter metrics; GPU-validated on real
  footage (within-segment jitter 0.19 / 0.37 / 0.47 ≪ 3.17 baseline).

### Added — Tiered subtitles, model management, media lineage, OpusClip parity

- **Tiered subtitle styles** and delivery options building on the v1.0 caption
  editor.
- **Model management** surface for the local/bundled model catalog.
- **Media lineage** tracking across the produce/edit pipeline.
- **OpusClip-parity** improvements to the short-maker output.

### Changed — Foundation hardening

- Foundation hardening across the sidecar and renderer, with both coverage gates
  held at strict 100% line + branch under the deterministic `quality` CI gate.

### Validation (honest)

- Multi-speaker engine end-to-end re-validated on real `razvan_gandu` content on
  a local RTX 4050: single + split rendered and **frame-confirmed**, all R0
  metric axes pass, composite render-path proven via the shared compositor (its
  natural 3-concurrent-speaker trigger does not occur in this footage). LR-ASD
  faithfulness is a numerical-equivalence proof, not an 87-minute re-measure.
  Full record in `docs/V1.1-BUILD-NOTES.md`.

## [1.0.0] — 2026-06-28

**Reframe v1.0.0 — the first stable release.** A plug-and-play, local-first Windows desktop
video studio that turns long videos into shorts: download one file, run it, and the app does
its own first-run setup (Python, ffmpeg, and the render engine are bundled). Both gates are at
**strict 100% line + branch coverage** (sidecar **and** renderer) and `main` CI is green.

### Added — Five-section information architecture (V1 IA)

- **A clean five-section top-level IA** replaces the old tab set. The app is now organised into
  **Library · Make Shorts · Edit · Director · Settings** (an ARIA tablist whose active section
  is *derived from the route*, so the strip can never desync):
  - **Library** — the video library home; opening a video routes into **Edit** for it.
  - **Make Shorts** — the novice front door / short-maker: **AI moment-pick *and* manual-interval**
    shorts, the single produced-Shorts gallery, and batch / template repurposing (it carries the
    interrupted-batch resume badge).
  - **Edit** — the per-video manual surface (trim / cut / join, reframe, caption editor, audio,
    stabilize, transcribe, export) hosted in the per-video Workspace.
  - **Director** — the prompt-driven AI video-editing panel (storyboard / diff + cost preview →
    real ffmpeg op-engines).
  - **Settings** — Models & System / Providers & Keys / Storage / System Health.

### Added — Caption position & style editor + output options

- **Caption position editor** — a draggable / resizable caption box with a live preview on a
  real video frame, so the caption lands exactly where you place it on the export. The box is
  stored normalised (resolution-independent) and converted to ASS alignment + margins by the
  sidecar; quick Top / Center / Bottom band buttons re-seat it.
- **Subtitle style templates** — a previewable swatch picker (karaoke + the OpusClip-style
  premium looks), each rendered with its real palette / font / box / outline, previewed both
  as swatches and live on the video before processing.
- **Output options in the Output Tray** — subtitle delivery is now a real choice (burn-in /
  soft track / separate file / none) honoured by the export pipeline (burn is no longer
  hard-coded), alongside save cut / save short / save SRT for every combination.
- **Preferences** — a Settings → Caption defaults area persists the default caption style,
  position, subtitle delivery, and language; Make Shorts seeds new clips from it.

### Changed — Framing: native, no-WSL by default + no silent fallback

- **9:16 reframe now runs natively with no WSL required.** The `auto` selector resolves to the
  in-sidecar **claudeshorts** (OpenCV / MediaPipe) engine, so the short-maker needs no WSL by
  default; **verthor** (WSL2 / MediaPipe) is now an *explicit opt-in* for higher quality.
- **No silent fallback.** An explicit `verthor` request fails **loudly** when WSL is absent
  (raising rather than being silently swapped); the `auto` path that does substitute surfaces a
  typed notice in job progress. First-run setup is loud about what it is doing — no quiet
  degradation. The packaging root-cause + a `dataRoot` fallback and a startup self-test landed
  alongside.
- **Single-speaker framing (V1).** Even in a wide / two-shot the crop locks onto the dominant /
  active speaker and tracks them smoothly — never an empty studio or the gap between two people.
  Automatic multi-speaker *switching* remains a V2 roadmap item.

### Security

- **`cloudApiKey` is redacted over the RPC / IPC bridge** — the only RPC-facing settings
  accessor now redacts provider keys so a key can never leak unredacted to the renderer.
- Stopped a silent-caption-erasure path so caption edits are never quietly dropped.

### Coverage / CI

- Strict **100% line + branch coverage** enforced on both the Python sidecar and the
  TypeScript renderer under the single deterministic `quality` CI gate; `main` is green and has
  **0 open issues**.

## [0.1.0] — 2026-06-25

First public release: a plug-and-play, local-first Windows desktop video studio that turns
long videos into shorts. Download the NSIS installer or portable zip from the
[Releases page](https://github.com/Prekzursil/Reframe/releases) — Python, ffmpeg, and the
render engine are bundled, and first run sets up the rest automatically (offline thereafter).

### Highlights

- **AI Provider Hub** — one shared AI substrate for the whole app: a curated, capability-aware
  model catalog; provider / API-key management; **multi-key auto-rotation** so jobs don't
  stall on a free-tier `429`; live per-key usage bars; and a single **AI-Job envelope** that
  gates every cloud call behind explicit consent and a budget. Local models are always the
  always-available fallback; keys stay on your machine and are never logged.
- **Five feature bundles** built on the Hub:
  - **Prompt-driven editing (Director)** — describe an edit, review the storyboard / diff and
    its cost, then apply real ffmpeg op-engines (reframe, zoom/pan, retime, overlay,
    lower-third, remove fillers, translate captions, export).
  - **Repurpose** — batch many sources through one aggregate job, save reusable templates +
    per-platform export presets (TikTok / Reels / Shorts), and resume after an app restart.
  - **Intelligence** — clip recommendations, best-frame thumbnails, and local-first semantic
    search over your library (cloud only with per-data-type consent).
  - **Editing-refine** — caption-cue remapping after silence-trim and related editing
    refinements.
  - **UX quality-of-life** — readiness rollups, onboarding, job-queue and consent affordances.
- **UI redesign + tabbed navigation** — top-level ARIA tablist:
  **Library · Create · Director · Repurpose · Settings**, with the per-video Workspace nested
  under Library (#231).
- **Providers & Keys panel** — add / redact API keys, capability + cost badges, per-key live
  usage bars, and per-data-type consent toggles, all in one place (#231).
- **Monthly cumulative spend cap** — a persisted, month-keyed (UTC) cumulative cost ledger in
  integer cents under the data root; soft/hard caps wired into every cloud-AI egress path so
  many small approved runs can't quietly add up. The hard cap refuses egress past the limit
  (#232).
- **8 audit bug fixes** shipped with the redesign and follow-ups, including: caption-cue
  remap after silence-trim, enforced offline on cloud-AI egress, sidecar exit/error listener
  race guard, race-safe job-store writes, embedder raw-key fix (was redacted → cloud 401),
  reframe auto-engine WSL-absent fallback to claudeshorts, transcribe device/model auto-detect
  + CPU fallback, and Director text-consent gating of the edit plan (no transcript leak).
- **Test harness** — strict 100% line+branch coverage everywhere (sidecar and renderer) under
  one deterministic `quality` CI gate, plus a permanent **opt-in** E2E suite
  (real-pipeline + AI + GUI) that runs nightly / on demand without gating PRs.

### Packaging

- Two Windows x64 artifacts: an **NSIS installer** (`.exe`) and a **portable zip**.
- Slim download (Electron app + bundled CPython 3.12 / 3.14 + ffmpeg + the Remotion render
  engine); heavy ML wheels and chosen models install on first run into `%APPDATA%\media-studio`
  (resumable + checksummed). No external prerequisites.

### Known caveats (honest)

- **First run downloads a few GB** of ML wheels + the models you enable; budget time and disk.
  The app is fully offline only **after** that first-run setup.
- **GPU is optional** — an NVIDIA GPU + CUDA accelerates transcription, the vision stack, and
  Chatterbox voice-clone TTS; without one, everything still runs on CPU (slower).
- **9:16 reframe** uses WSL2 / MediaPipe (verthor) for best quality and auto-falls back to the
  in-process claudeshorts reframer when WSL2 is absent.
- Windows x64 only in this release.
