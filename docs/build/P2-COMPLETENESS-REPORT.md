# P2 COMPLETENESS REPORT — media-studio (2026-06-12)

Completeness critic sweep of the whole tree against **CONTRACTS.md (base + P2 addendum)** and
**docs/PLAN-P2.md v2.1**. Both suites were RUN (not just read): sidecar `1089 passed / 2 failed`,
UI `299 passed / 3 failed`. The assembled composition root was BOOTED and the live method registry
dumped (42 methods) — registration claims below are verified at runtime, not from source reading.

**Headline: ~85% complete.** All 14 A2 methods registered and answering; A3 schemas match
field-for-field on both sides; all 8 panels wired to real RPC in dev. The misses cluster in five
places: (a) the Remotion caption engine is built but **never called by the export pipeline**;
(b) `shortmaker.export`'s frozen optional `audioTrackId` is unimplemented end-to-end; (c) the
production renderer bundle contains **zero feature panels** (runtime-variable dynamic import);
(d) WIRING-T5's packaged-mode supervisor block was never written into `app/main`; (e) T6 (thumbnails,
keyboard review, job-queue panel) has no code. Plus 5 failing tests (4 are test-side bugs).

> Supersedes `docs/build/COMPLETENESS-REPORT.md` and the integration framing of
> `docs/build/INTEGRATION-REPORT.md` — both describe the pre-`handlers.py` P1 world and are now
> historical. `docs/build/RUN-CHECKLIST.md` has been rewritten to match current reality.

---

## 1. A2 method registry — implemented & registered?

Verified live: `handlers.register_all()` boots clean in the dev venv and registers **42 methods**
(every §2 base method + every A2 addendum method + built-ins). Per A2 line:

| A2 method | Sidecar impl | Registered | TS client | UI surface |
|---|---|---|---|---|
| `media.playable` | `features/media_compat.py` | ✅ | ✅ `client.media.playable` | ✅ Workspace proxy kick + mstream resolver (main.ts) |
| `media.proxy.start` | `features/media_compat.py` | ✅ | ✅ | ✅ Workspace (auto on unplayable verdict) |
| `timeline.peaks` | `features/timeline.py` (disk-cached, mtime/path-invalidated, temp-file PCM) | ✅ | ✅ | ✅ Timeline.tsx |
| `tts.voices` | `features/tts/voices.py` | ✅ | ✅ | ✅ Dub.tsx |
| `tts.sample.add` | `features/tts/voices.py` (validates, copies to voices dir) | ✅ | ✅ | ✅ Dub.tsx |
| `tts.dub.start` | `features/tts/dub.py` (batched: translate-all → free MT → synth-all → align ±15% → concat → mux) | ✅ | ✅ | ✅ Dub.tsx |
| `tracks.audio.list/mux/replace/strip` | `features/tracks_audio.py` | ✅ ×4 | ✅ ×4 | ✅ Dub.tsx lists; Tracks panel does NOT show audio tracks (PLAN T2 said "Tracks panel lists audio tracks") — minor gap |
| `shortmaker.export` + **`audioTrackId`** | ❌ **param never read** (shortmaker.py reads only `reframeEngine`/`captionStyle`) | n/a | type-only in rpc.ts | ❌ ShortMaker.tsx has no audio-track selector and never sends it |
| `job.list` | `protocol.py` built-in + `jobs.list_info()` (bounded 100, newest-first) | ✅ | ✅ | ⚠️ no panel consumes it (see §6 T6) |
| `job.retry` | `protocol.py` built-in (stored-request re-dispatch, first-write-wins) | ✅ | ✅ | ✅ toast Retry button (`registerJobRetry` in App.tsx) |
| `assets.list` / `assets.ensure` | `assets/manager.py` + `assets/rpc.py` (resume, sha, disk preflight) | ✅ | ✅ | ✅ Assets.tsx |

Extra non-contract method: `assets.cancel` (documented CONTRACT-NOTE alias of `job.cancel`) — harmless.

**The ONE A2 miss: `shortmaker.export({…, audioTrackId})`.** Frozen in the addendum, typed in
`lib/rpc.ts`, absent everywhere else. T2's Done-when ("muxed as a selectable audio track that
**survives export**") is unreachable until the export pipeline maps the chosen audio stream
(or muxes the dub WAV) onto each cut clip and ShortMaker.tsx grows the selector.

## 2. A3 schema parity — Python vs TS

**No field mismatches found.** Checked construction sites against `lib/rpc.ts`:

- `AudioTrack {id, lang, name, kind:"original"|"dub", voice?, path}` — `tracks_audio.normalize` ⟷ rpc.ts/Dub.tsx. ✅ (`voice` omitted-when-absent both sides.)
- `JobInfo {jobId, feature, label, videoId?, status, pct}` — `Job.info()` ⟷ rpc.ts. ✅ Internal `pending` correctly mapped to wire `"queued"`; `videoId` omitted (not null); metadata backfilled from the recorded request so every dispatched job gets meaningful feature/label.
- `AssetInfo {name, kind, sizeMB, installed, dest}` — `manager.info()` ⟷ rpc.ts/Assets.tsx. ✅
- `VoiceSample {id, name, path, durationSec}` — `voices.normalize_sample` ⟷ rpc.ts/Dub.tsx. ✅
- `media.playable {playable, reason?, proxyPath?}`, `timeline.peaks {sampleRate, peaks}` ✅.
- `Project.audioTracks` ✅ (optional in TS for old manifests).
- job.done error payload `{error:{message,type}}` — `jobs._finish_error` ⟷ `useJob.extractJobError`. ✅

**Drift risk (not a mismatch):** three parallel TS schema layers exist — canonical `lib/rpc.ts`,
legacy `components/api.ts` + `features/_api.ts` (P1, lack all P2 types), and local re-declarations
in `Dub.tsx`/`Assets.tsx`/`ShortMaker.tsx`. Currently consistent; consolidate onto `lib/rpc.ts`
when convenient.

## 3. A6 violations (anywhere)

1. **Pre-import natives (A6.1):** `__main__._preimport_native_modules` covers numpy, ctranslate2,
   cv2, mediapipe, onnxruntime, kokoro_onnx, aiohttp. **GAP: `av` (PyAV) is missing.** It is a
   native C-extension pulled in by `faster_whisper` and first imported inside the transcribe job
   thread — exactly the deadlock class the lesson froze. One-line add.
2. **Undrained Popen pipes (A6.2):** clean everywhere it matters — `ffmpeg.run` (stderr drain
   thread), `caption_remotion.run_render` (drain thread + RENDER_PROGRESS parse), timeline peaks
   (PCM via temp file, by design), chatterbox/assets/media_compat/reframe* (`subprocess.run`).
   **Adjacent violation: `models/runner.py:347` spawns llama-server as `Popen(argv)` with
   INHERITED stdio.** The child shares the sidecar's stdout — the JSON-RPC protocol channel — so
   any llama-server stdout chatter can interleave with protocol frames (Electron tolerates whole
   junk lines but not mid-line interleaving). Not a freeze (inherit ≠ PIPE), but redirect to
   `DEVNULL` (or a drain thread to stderr) is the correct fix.
3. **Swallowed job failures (A6.3):** none found. `_finish_error` emits the job.done error payload
   (the Phase-0 fix); translation tier failures, asset failures, dub failures all raise through it.
   The two intentional best-effort swallows (`set_has_transcript` bookkeeping, mediaProtocol
   resolver → 404) are logged and non-protocol.
4. **argv/WSL/ASS escaping (A6.4):** clean. No `shell=True` anywhere; verthor runs `wsl bash
   <script-file>`; ASS text escaped in `caption.py`.
5. **Pinned manifest entries (A6.5):** the manifest **rejects** loose env requirement specifiers at
   registration; all 12 registered assets (whisper-hf, qwen, kokoro ×2, chatterbox-env,
   chrome-headless-shell, translategemma ×2, llama-server ×3) carry pinned URLs/`pkg==ver`.
   sha256 left blank where allowed ("sha-optional" — human fills on first verified download).
   **Pin inconsistencies found:** `pyproject.toml` pins `onnxruntime==1.20.1` while
   `runtime_setup/requirements-sidecar.txt` (and the live venv) have `1.26.0` — `pip install -e .`
   would downgrade and diverge from the runtime env. **`mediapipe` is in no requirements file at
   all** (PLAN T4.0: "mediapipe/opencv added to the runtime-setup manifest" — opencv is there,
   mediapipe is not), and is absent from the dev venv.

## 4. UI surfaces vs real RPC

All 8 Workspace tabs mount and all panels call the real bridge: Transcribe/Subtitles/Tracks/
Convert/ShortMaker (P1) + Timeline (`timeline.peaks`, `tracks.list`, `subtitles.edit`, undo stack,
drag/split/merge/retime), Dub (`tts.voices`, `tts.sample.add`, `tts.dub.start`, `tracks.audio.list`,
WAV audition via `mstream://media/dub:<path>` with the dubs-root jail in main.ts), Assets
(`assets.list/ensure/cancel` with live job progress). Library has both U2 paths (native picker via
`dialog.openVideos` IPC + drag-drop via `webUtils.getPathForFile`). Player streams over the
privileged `mstream://` protocol with Range support; Workspace kicks `media.proxy.start` on an
unplayable verdict and remounts the player on job.done. Toasts: `useJob` extracts the A3 error
payload, every panel goes through it, retry wired to `job.retry`.

**Two real holes:**

- **Production build ships ZERO panels.** `Workspace.lazyPanel` uses a runtime-variable
  `import(/* @vite-ignore */ modulePath)` — Rollup cannot bundle it. Verified in the existing
  `app/out/renderer` bundle: the *"panel is not available"* placeholder string is present, the
  panels' code (e.g. ShortMaker's "Caption style") is **absent**. Works in dev (vite serves
  modules over HTTP); in any packaged/preview build every tab renders the placeholder. Fix:
  static `lazy(() => import('../features/X'))` per panel (the absence-tolerance hack is obsolete —
  all panels exist now) or `import.meta.glob`.
- **ShortMaker candidate preview is still a placeholder** (`ShortMaker.tsx:764` "Preview
  placeholder"). U1's Done-when — "candidate preview plays its exact window
  (sourceStart→end, in/out markers)" — has no code; the Player component + mstream exist, the
  seek-window wiring was never done.

Minor: Tracks panel doesn't list audio tracks (PLAN T2 bullet); no panel consumes `job.list` (§6).

## 5. Stubs / TODO / NotImplementedError

Production tree is clean: **no** TODO/FIXME/XXX/NotImplementedError/pass-only bodies in
`sidecar/media_studio` or `app/{main,renderer/src}` (the P1-era `boundary.detect_*`
NotImplementedErrors are gone — real ffmpeg-silencedetect + PySceneDetect seams now exist and are
fed by `handlers._detect_boundaries`). Remaining stub-like items:

- `ShortMaker.tsx:764` — preview placeholder (see §4).
- `Workspace.lazyPanel` MissingPanel fallback — now effectively dead code in dev and a trap in prod.
- Stale docs: `docs/build/RUN-CHECKLIST.md` (rewritten now), `docs/build/COMPLETENESS-REPORT.md`,
  `docs/build/INTEGRATION-REPORT.md` — all describe the "no composition root" P1 world.

## 6. PLAN-P2 Done-when items with NO code

| Item | Status |
|---|---|
| **T4a** "karaoke render completes **from `shortmaker.export`** with the Remotion style selected" | ❌ **Engine never invoked by the pipeline.** `RemotionCaptionEngine` is complete (resolution chains, drained subprocess, job-file argv, tests; supervisor injects `MEDIA_STUDIO_NODE_EXE`/`RENDER_JS`/`REMOTION_BUNDLE`; render-cli + vendored compositions exist; Chrome registered in U4) — but `shortmaker._lazy_caption` constructs **libass `CaptionEngine` unconditionally**. `captionStyle` reaches the export settings and dies there. Also: style `none` doesn't skip the caption stage. |
| **T2** "muxed as a selectable audio track that **survives export**" | ❌ `audioTrackId` unimplemented (§1). Dub→mux→list works; the export carry does not exist. |
| **T6 thumbnails** (posters + duration badges in Library) | ❌ no code. |
| **T6 keyboard review** (J/K/Space/A/X/←→) | ❌ no code (no key handlers in ShortMaker). |
| **T6 global job queue panel** | ❌ no UI. The hard protocol half (bounded worker pool, gpu lane serialization, queued state, metadata, `job.list`/`job.retry`) is DONE in U5 — only the panel is missing. |
| **U1** "candidate preview plays its exact window" | ❌ placeholder (§4). |
| **T5** "installer → first-run setup → Sinek smoke on a clean machine" | ⚠️ sidecar half done (`runtime_setup/bootstrap.py`, `tools_resolver`, embeddable-python + ffmpeg staging scripts, electron-builder.yml, make-portable assertions) — but **WIRING-T5 §2 was never applied to `app/main`**: no packaged-mode env injection (`MEDIA_STUDIO_PYTHON`/`SIDECAR_DIR`/`FFMPEG`/`FFPROBE`) and no first-run `bootstrap.py` spawn before `sidecar.start()`. Packaged app would launch `py -3.12` against an absent venv and never find the bundled ffmpeg (ffmpeg.py's bundled probe looks inside the package dir, not `resources/bin`). Plus the §4 production-bundle hole. |
| **Phase Z** (integration acceptance, design pass, packaged-build exercise) | ⏳ runtime/orchestrator legs — expected pending, listed for completeness. |
| Everything else (U1 fallback tree, U2, U3, U4 resume+preflight+registration, T1 round-trip/undo/peaks-cache, T2 engines+sample UX+batched pipeline, T3 tiers+router+model-identity-aware runner, T4b A/B + auto-fallback + typed notice) | ✅ code + tests exist and pass. |

## 7. Suite state (RUN 2026-06-12)

**Sidecar: 1089 passed, 2 failed.**

1. `test_assets.py::TestEnsureJob::test_ensure_job_progress_and_done_payload` — fixture declares
   `size_mb=0.001` (→ plausibility floor 524 B via `file_size_ok`'s `MIN_SIZE_FRACTION=0.5`) but the
   fake download writes 10 bytes → freshly-installed asset reads `installed:false`. Test-vs-impl
   disagreement about whether a just-completed verified download counts. Cheapest fix: fixture
   `size_mb=0.00001`; better fix: `ensure()` trusts its own just-verified install.
2. `test_tts_align.py::TestAlignCueWav::test_resynth_asked_when_off_target` — **pure test bug**:
   `fake_duration` substring-matches `"resynth"` against the FULL path, and pytest's tmp dir is
   named `test_resynth_asked_when_off_ta0` → `raw.wav` reads 10.4 s instead of 13.0 → rate 1.04.
   Fix: match `Path(path).name`.

**UI: 299 passed, 3 failed.**

3. `timelineOps.test.ts > splitAt renumbers` — the test self-contradicts (asserts sequential
   renumbering AND "later cues untouched" with their old index). Impl renumbers sequentially
   (correct subtitle semantics). Fix the assertion.
4–5. `Workspace.test.tsx` ×2 — stale P1 expectations: "five contract tabs" / `toBe(5)` vs the 8
   P2 tabs. Update to the 8-tab list.

## 8. PRIORITIZED punch list → green suites + runnable app

| # | P | Fix | Size |
|---|---|---|---|
| 1 | P0 | **Green the suites:** fix the 4 test-side bugs (§7 items 2–5) + decide item 1 (fixture vs `ensure()` trust). | S |
| 2 | P0 | **Wire Remotion into export:** `shortmaker._lazy_caption` (or a `Stages` swap in `handlers._shortmaker`) routes `settings["captionStyle"]` → `RemotionCaptionEngine.render` for `bold/bounce/clean/karaoke`, skips captioning for `none`, keeps libass default. Add the pipeline test. | M |
| 3 | P0 | **Production panel bundling:** replace `lazyPanel`'s runtime-variable import with static `React.lazy` imports (all 8 panels exist — the absence shim is obsolete). Without this every packaged/preview build is an empty shell. | S |
| 4 | P1 | **`shortmaker.export` audioTrackId:** sidecar — resolve the AudioTrack, map/mux its stream onto each cut clip (reuse `tracks_audio` ffmpeg patterns); UI — audio-track `<select>` in ShortMaker fed by `tracks.audio.list`. Closes the frozen A2 line + T2's Done-when. | M |
| 5 | P1 | **Dev-env deps (runnable app):** `pip install kokoro-onnx==0.4.9 edge-tts==7.0.0` (+ a pinned `mediapipe` for T4b) into `sidecar/.venv`; reconcile the `onnxruntime` pin (pyproject 1.20.1 vs requirements/venv 1.26.0); add mediapipe to `requirements-sidecar.txt`; `cd app && npm run render-cli:install && npm run render-cli:bundle` (T4a is dead in dev until render-cli/dist + out/remotion-bundle exist). See RUN-CHECKLIST. | S |
| 6 | P1 | **WIRING-T5 §2 supervisor block:** packaged-mode env injection (PYTHON/SIDECAR_DIR/FFMPEG/FFPROBE) + first-run `bootstrap.py` spawn in `app/main` (`buildSidecarEnv` is the one place). Blocks only the packaged path. | M |
| 7 | P2 | `runner.py`: spawn llama-server with `stdout=stderr=DEVNULL` (protocol-pollution guard, §3.2). | S |
| 8 | P2 | Add `"av"` to `_preimport_native_modules` (§3.1). | S |
| 9 | P2 | ShortMaker candidate preview: Player + `sourceStart→end` window seek + in/out markers (U1 Done-when). | M |
| 10 | P3 | T6 trio: Library thumbnails; keyboard review; job-queue panel over `job.list`/`job.retry`/cancel. | M–L |
| 11 | P3 | Doc hygiene: archive the two stale P1 build reports; consolidate the 3 TS schema layers onto `lib/rpc.ts`; Tracks panel lists audio tracks. | S |

**Completeness: ~85%** (A2 surface 13/14 lines fully live; A3 100%; suites 99.6% green;
U1–U5 + T1–T4b code-complete except the two export-pipeline integrations; T5 ~70%; T6 ~25% —
backend done, UI absent; Phase Z pending by design). Items 1–5 get green suites + a fully
runnable **dev** app including premium captions; +6 makes the packaged story real.
