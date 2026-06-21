# Media Studio — P2 Mega-Phase Plan (v2.1, 2026-06-12)

> **Plan-review gate: PASSED 3/3** (Scope round-1; Feasibility + Completeness round-2 after the v2
> fixes). v2.1 folds the reviewers' final wording-level catches: kokoro-onnx (not torch-Kokoro);
> codec-driven (not container-driven) U1 fallback tree; the Python→Node spawn shape pinned to
> `ELECTRON_RUN_AS_NODE=1` + a render-CLI resolution chain; embeddable-CPython pip mechanics named
> (get-pip + `pip --target` + `._pth` — no ensurepip/venv in the embeddable distro); pinned wheel
> versions in the manifest; retry-params ownership = T6 (U3 consumes); audio RPC names added to the §2
> delta; mediapipe wheel check in T4.0; dub audition via WAV playback (Chromium audioTracks is
> flag-gated); T2 cross-language dub leg proven at Phase Z.

**Source of truth for scope:** the 2026-06-12 grill (all branches user-resolved). Supersedes PLAN-P1's
"Later" list — those items ENTER scope. Lean-local rules hold: no auth/keystore/signing/SaaS; ordinary
correctness; engines stay behind interfaces.

> **v2 changelog (plan-gate round 1: scope PASS, feasibility+completeness FAIL → fixed):** two-stage
> install (slim installer + first-run runtime setup) replaces bundle-everything (NSIS 2 GB limit, torch);
> Chatterbox isolated in its own downloaded env (torch↔ctranslate2 DLL conflict); U1 gains the custom
> protocol + remux/proxy fallback (Chromium can't demux MKV / HEVC flaky); download manager promoted to
> owned shared infra (U4) with a model-registration manifest; T4a's Remotion-in-Electron shape spelled out
> (utilityProcess, build-time pre-bundle, Chrome Headless Shell download, sidecar↔Node bridge defined);
> T2 gains the AudioTrack data model + audio-mux items; T6 queue gains the job.list/metadata/queue/retry
> protocol work; per-item **Done when** criteria added; CONTRACTS amendment item added (§3/§4/§7); shared-
> file ownership rule added; verthor third-party GPU lane named; design pass moved to Phase Z-adjacent.

**Shape:** Phase 0 (spine, interactive) → Phase 1 (usability core + shared infra) → Tracks T1–T6
(parallel) → Phase Z (integration + design pass + acceptance). Pragmatic TDD (P1 style). Baseline: P1
green (587 sidecar + 93 UI tests; sidecar auto-detects `.venv`, 01581a1).

**Track↔grill mapping:** T1=timeline editor · T2=TTS/dub incl. Chatterbox clone · T3=translation full
chain + survey-first · T4=FULL claude-shorts (Remotion captions **and** crop engine) · T5=Windows
installer+portable · T6=polish extras. Phase 1 (U1–U4) = prerequisite insertion (player/picker/toasts/
downloads) — U1–U3 close P1's never-built "preview/approve" commitment; U4 is shared infra three tracks
need. Acknowledged as added-by-necessity, not grill-scoped.

---

## Phase 0 — Spine validation (BLOCKS ALL; interactive, orchestrator-driven)
- Relaunch llama server (Qwen3-4B :8088) + app; verify sidecar (27 methods). Acquire yt-dlp if absent.
- Fetch Sinek talk video → `library.add` → transcribe (first whisper download ~1.5 GB) → short-maker
  (select → snap → cut → verthor/WSL reframe → libass caption → export).
- Fix seams live. Known-likely: whisper download UX; **Win→WSL path translation** for verthor; caption
  escape on real ASR text; **GPU eviction order — the sidecar's LaneLock covers only {llama, whisper};
  verthor's YOLO runs in WSL on the same 6 GB GPU outside any lane → add a third-party lane: evict/stop
  llama before every reframe** (extends `runner.py`).
- **Done when:** 5 captioned 9:16 clips exported from the Sinek video through the app's own RPC.

## Phase 1 — Usability core + shared infra (gates T1, T6-review; U4 gates T2/T3/T4a/T5)
- **U1 Real video player.** Privileged **custom protocol with Range support** (dev renderer is
  http://localhost — raw file:// is blocked) + workspace player + ShortMaker candidate preview seeking
  `sourceStart→end` with in/out markers. **Compatibility fallback (codec-driven, not container-driven):**
  ffprobe sniff on open → if ALL streams are Chromium-playable but the container isn't (e.g. h264-in-MKV)
  → remux `-c copy` to mp4; if any stream isn't playable (HEVC/WMV/MPEG-TS/AVI — including HEVC inside
  MKV) → proxy transcode h264 720p, cached per video; play the proxy while operations use the original. *Done when:* an mp4, an
  MKV, and an HEVC file all play + scrub in the workspace; candidate preview plays its exact window.
- **U2 Import UX.** Native file picker (`dialog.showOpenDialog` over IPC) + drag-drop onto Library;
  multi-add. *Done when:* both paths add videos; bad files surface a typed error.
- **U3 Error/notify surface.** App-wide toast system; every typed job failure surfaces with reason +
  retry where sane (retry consumes the stored request params that **T6 owns** — U3 lands without retry,
  gains it when T6 merges). *Done when:* a forced failure in each feature
  shows a toast; no silent failures remain.
- **U4 Download & runtime-setup manager (shared infra, ONE owner).** A sidecar `assets.*` subsystem +
  panel: **manifest-driven** — every track REGISTERS its artifacts (name, kind: model|env|tool, size,
  source, dest, checksum?) in `sidecar/media_studio/assets_manifest.py`; the manager downloads with
  resume + disk preflight + progress. **Entries carry PINNED versions / exact wheel URLs** (first-run pip
  must not resolve loose from PyPI — Chatterbox pins torch tightly). **Day-1 scope stays minimal**
  (download + resume + preflight + registration API; runtime-setup polish lands with T5, since U4 gates
  four tracks). Covers from day 1: whisper, Qwen3-4B GGUF; later registrations: MT
  GGUFs (T3), Kokoro weights + the **Chatterbox isolated env** (T2), Remotion **Chrome Headless Shell**
  (T4a), **llama-server binaries (CUDA+CPU)** (T5), verthor YOLO weights (T5). Also owns the **first-run
  runtime setup** step (pip-install of heavy wheels into `%APPDATA%` envs — see T5 two-stage design).
  **Mechanics (embeddable CPython has NO ensurepip/venv):** bootstrap pip via get-pip.py, install with
  `pip --target` into per-env dirs activated via `python312._pth`/`PYTHONPATH`; the isolated Chatterbox
  env may instead download a full standalone CPython if `--target` proves insufficient for torch.
  *Done when:* a fresh `%APPDATA%` gets whisper+Qwen via the panel with resume + preflight exercised;
  registration API documented for tracks.

## Tracks (parallel after Phase 0; U4 gates the marked ones)

**Shared-file ownership (anti-contamination, from the parallel-worktree lesson):** `runner.py`,
`handlers.py`, `protocol.py`, `Workspace.tsx`, `lib/rpc.ts`, `assets_manifest.py` are APPEND-POINTS many
tracks touch. Rule: tracks develop in isolated worktrees; the orchestrator serializes merges of these six
files (one merge at a time, suite green between merges).

### T1 — Timeline subtitle editor (needs U1)
Cue list + waveform strip (`timeline.peaks` RPC: ffmpeg-extracted peaks, cached per video, invalidated by
source mtime/path change), click-to-seek via U1 player, split/merge/retime, drag-sync cue edges, thin
undo/redo, save via `subtitles.edit`. *Done when:* round-trip = edit/split/merge/retime/drag a real
track and the saved file reflects it; peaks render for a 1-hour file < 5 s from cache; undo restores
pre-edit state. (Undo = single linear stack — keep thin.)

### T2 — TTS voiceover/dub (needs U4 for weights/env)
- **Engines behind ONE `TtsEngine`:** Kokoro-82M local default — **the `kokoro-onnx` build
  (onnxruntime), NOT the torch pip package** (the main sidecar env stays torch-free per §7) (Apache,
  8 langs, CPU-OK, in-sidecar);
  edge-tts hosted fallback (100+ langs; labeled ONLINE); **Chatterbox 0.5B voice-clone in its own
  downloaded venv subprocess** (MIT; FP16; isolated env dodges the torch↔ctranslate2 cuDNN DLL conflict
  AND keeps the main sidecar torch-free per contract; argv+JSON subprocess seam like verthor). Chatterbox
  joins the VRAM lanes as sole-resident; **T2.0 = a 10-minute on-4050 smoke (load FP16 + synth one cue)
  BEFORE building the dub pipeline on it.**
- **Voice-sample UX:** record/upload a 10–30 s sample (validated format/length), stored under
  `%APPDATA%/media-studio/voices/`.
- **Dub pipeline (batched, not interleaved):** translate ALL cues (T3 seam; skipped if same-language) →
  free MT model → synth ALL cues → align per cue (target duration → rate re-synth → `atempo` clamp ±15%
  → pad) → concat to a dub audio file. **Audition:** the Dub panel plays the dub WAV directly (Chromium's
  `audioTracks` switching is flag-gated — don't promise in-player track switching). **The cross-language
  dub leg depends on T3 and is first PROVEN at Phase Z** (T2's own Done-when is satisfiable
  same-language); Phase Z budgets for first-contact failures there.
- **AudioTrack data model (new):** §3 gains `AudioTrack {id, lang, name, kind:"original"|"dub", voice}`;
  `Project.audioTracks:[AudioTrack]`; `tracks.py` gains audio-stream mux/replace/strip (it is subtitle-
  only today); Tracks panel lists audio tracks; `shortmaker.export` carries the chosen audio track.
- *Done when:* a real clip gets a Kokoro dub and a Chatterbox-cloned dub, each cue within ±15% of its
  window (asserted), muxed as a selectable audio track that survives export; edge-tts path works online.

### T3 — Tiered translation (needs U4 for GGUFs)
- **T3.0 survey FIRST:** current open-model MT landscape (LM Studio catalog + HF, mid-2026); verify
  TranslateGemma-4B/Aya-Expanse-8B GGUF availability; swap picks if something better fits ≤6 GB. Output:
  a short decision doc; the survey may replace the default chain below.
- **T3.1:** chain = TranslateGemma-4B Q4 local (major langs) → Aya-8B offloaded (low-resource; UI labels
  SLOW) → hosted (labeled ONLINE). Language-aware router on the provider seam. **`runner.py` becomes
  model-identity-aware** (today `start_server` returns the existing process even if it serves a different
  GGUF — restart on model switch; shared-file rule applies). *Done when:* three languages route to three
  tiers (asserted via a routing table test) and a real subtitle track translates through each tier.

### T4 — Second engines (FULL claude-shorts: both halves; needs U4 for Chromium)
- **T4.0 vendor:** acquire claude-shorts source (AgriciDaniel/claude-shorts) → `vendor/claude-shorts/`;
  confirm repo availability/license at vendoring time and **that mediapipe publishes win_amd64 wheels
  for the pinned 3.12** (else T4b's engine joins Chatterbox in an isolated env);
  port its Remotion compositions + MediaPipe crop math; mediapipe/opencv added to the runtime-setup
  manifest (NOT the slim installer).
- **T4a Remotion CaptionEngine.** Shape (the only workable one): compositions **pre-bundled at app-build
  time** (`@remotion/bundler` runs in CI/dev, ships as a static bundle — never bundles at runtime);
  rendering runs in a **separate Node process** (Electron `utilityProcess` / `ELECTRON_RUN_AS_NODE`),
  with `@remotion/renderer`'s native compositor shipped `asar.unpacked` (electron-builder config — T5
  coupling, single owner = T5); **Chrome Headless Shell (~150 MB) registers in U4**. **Sidecar↔Node
  bridge:** the Python `RemotionCaptionEngine` impl spawns the render CLI as a subprocess — concretely
  **the Electron executable with `ELECTRON_RUN_AS_NODE=1`** (`utilityProcess` is main-process-only,
  unreachable from Python); the exe path is **injected into the sidecar's env by the supervisor at spawn**
  with a resolution chain like llama-server's (settings/env → packaged app exe → dev `node_modules`) —
  (argv + JSON
  job file → renders → returns the output path), mirroring the verthor adapter pattern — the engine stays
  inside the Python pipeline, identical export contract. Expect slow renders (SwiftShader, often <5 fps —
  the style picker labels Remotion styles "premium, slower"). Remotion free for individuals (license OK).
  *Done when:* a karaoke-style caption render of a real clip completes from `shortmaker.export` with the
  Remotion style selected, byte-playable mp4, and libass styles still pass their suite.
- **T4b claude-shorts ReframeEngine.** The MediaPipe-crop engine as the second `ReframeEngine` impl
  (in-sidecar, mediapipe via runtime setup); ShortMaker gains an A/B engine override (default verthor).
  **Also the no-WSL fallback:** when WSL/verthor is absent, reframe auto-falls-back to claude-shorts
  (typed notice). *Done when:* same clip reframed by both engines side-by-side via the override; fallback
  fires on a simulated missing-WSL.

### T5 — Packaging (Windows, validated; two-stage)
- **Slim installer + portable zip** (electron-builder NSIS + zip, both < ~700 MB): Electron app +
  **embeddable CPython 3.12** + the LIGHT sidecar deps + bundled ffmpeg/ffprobe + the pre-bundled
  Remotion bundle + render CLI. **NO torch, NO heavy wheels, NO models in the artifact** (NSIS ~2 GB
  format limit + contract §7).
- **First-run runtime setup (owned by U4's manager, packaged here):** pip-installs heavy wheels
  (faster-whisper/ctranslate2, scenedetect, opencv, mediapipe; the Chatterbox env separately) into
  `%APPDATA%/media-studio/envs/` + downloads all registered models/tools — **including llama-server
  (CUDA + CPU builds) so a fresh machine needs no `D:\tools` path**; `runner.py` resolves llama-server
  from settings/env → `%APPDATA%` tool dir → the dev path.
- **WSL/verthor provisioning:** detect WSL + verthor; offer a scripted bootstrap (distro check + venv +
  script install) OR rely on the T4b fallback with a clear notice. Mac/Linux scripts present, unvalidated.
- Pin dev to `py -3.12` (a 3.14 `__pycache__` exists — purge; CI asserts 3.12).
- *Done when:* on a machine-state without `D:\tools` (clean `%APPDATA%`, PATH-less ffmpeg), the installer
  → first-run setup → Sinek smoke (transcribe + 1 clip) succeeds; portable zip boots the same.

### T6 — Polish extras
- **Thumbnails:** ffmpeg poster frames + duration badges in Library, cached in the project dir. *Done
  when:* library shows posters for all formats U1 supports (incl. proxy-only files).
- **Keyboard review** (needs U1): J/K prev-next, Space play/pause, A approve, X discard, ←/→ nudge.
  *Done when:* full 5-candidate review possible mouse-free (component test + manual).
- **Global job queue panel:** requires protocol work — `job.list` RPC; `Job` metadata enrichment
  (feature, label, videoId); **real queue semantics** (today `JobRegistry.start()` spawns immediately —
  add a bounded worker pool + queued state); stored request params enabling **retry** (also powers U3).
  *Done when:* three concurrent feature jobs appear in one panel with live states; cancel + retry work;
  GPU-lane jobs queue instead of colliding.
- **Visual design pass → moved to Phase Z-adjacent** (after integration, before acceptance): deliberate
  direction per the web design rules, styling the REAL surfaces. *Done when:* all panels pass the
  anti-template checklist; both grilled reviewers of the pass agree it looks intentional.

## Phase Z — Integration + design pass + acceptance
- Serialized merges of the six shared files (ownership rule); both suites green; CONTRACTS amended.
- **Design pass** (T6's last item) on the integrated app.
- **Packaged-build exercise:** acceptance runs on the dev tree AND the packaged build's first-run path
  (install → runtime setup → at least the Sinek transcribe+export leg) so download-on-first-run is
  exercised against reality, not just unit tests.
- **Acceptance:** Sinek (controlled) + ONE user wild video; full flow incl. a timeline cue edit, a dub,
  a translated track, a Remotion caption style, both reframe engines tried. **Pass = ≥3/5 share-worthy
  clips without manual re-editing on BOTH videos, judged by the user.**

## Cross-cutting
- **CONTRACTS.md amendment (single PR-of-truth, early):** §2 += `tts.*`, `timeline.peaks`, `job.list`,
  **the audio-track methods** (`tracks.audio.list/mux/replace/strip` or equivalent — existing
  `tracks.burn/strip` are subtitle-typed) **and the `shortmaker.export` audioTrack param**,
  `assets.*`; §3 += AudioTrack, peaks, voice descriptors; **§4 rewritten** (ReframeEngine ×2 impls,
  CaptionEngine ×2 impls, new TtsEngine ×3 impls — still exactly three interfaces, no fourth); **§7
  amended** (heavy wheels live in `%APPDATA%` envs; Chatterbox env isolated; torch never in the slim
  bundle or main sidecar env).
- VRAM lanes: every heavy model one-resident on 6 GB incl. the WSL third-party lane; CPU fallback +
  ONLINE/SLOW labels in UI.
- Models/tools all download-on-first-run via U4; nothing heavy in repo (.gitignore enforces).
- Pragmatic TDD; adversarial review per track; no platform creep (no signing/keystore/consent/SaaS).

## Execution
User-selected: **ultracode**, spine-first then parallel tracks; orchestrator drives Phase 0 + every
runtime smoke (GPU/display/WSL can't run inside workflow agents) + the serialized shared-file merges.

---

## P3 WAVE (user-approved 2026-06-13): OpusClip catch-ups + the local flywheel
- **P3-A Hook-title overlay:** render the candidate's `hook` as the big bold headline at the clip top —
  both engines (libass layer + a Remotion title slot); ShortMaker toggle (default ON); auto-shorten via
  the existing hook text. UI control rides the existing style picker row.
- **P3-B Filler-word removal:** word timings already exist — build a cut-list (configurable filler set per
  language + gap-merge ≥120ms, never cut mid-sentence), apply as an ffmpeg segment-concat in the cut stage
  (frame-accurate); ShortMaker toggle (default OFF until proven); per-clip "removed N fillers (X.Xs)".
- **P3-C Virality % v2:** select schema gains 4 factors {hookStrength, emotionalFlow, perceivedValue,
  shareability} 0-100 + one-line rationale each + overall; batch-percentile normalization within a video's
  candidate set -> displayed %; optional self-consistency x2 averaging (variance = confidence). UI: factor
  bars in the candidate card.
- **P3-D Feedback flywheel:** (1) capture approve/discard/nudge/export to %APPDATA%/media-studio/feedback/
  feedback.jsonl (implicit labels; candidate payload + factors + action + ts); (2) taste exemplars — the
  select prompt embeds top-approved/bottom-rejected hooks once >=20 labels (compact, capped tokens);
  (3) score calibration — binned mapping LLM%->empirical approval% once >=50 labels, displayed as the
  calibrated %. LoRA tier explicitly deferred. Research basis: OpusClip's 4-factor 0-99 score is an
  unvalidated heuristic (no published spec; low-scored clips regularly outperform) — ours adds batch
  percentile + personal calibration it cannot do.
