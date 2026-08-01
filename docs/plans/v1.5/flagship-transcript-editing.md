# Reframe v1.5 Flagship — Transcript-Native Editing: Implementation Plan + Go/No-Go

**Status:** RESEARCH + DESIGN + PLAN (no repo modified).
**Grounding:** read from `origin/main` @ `7502e3a` (#288 Caption pilot) — local checkout is stale, every seam below was read via `git show origin/main:<path>`.
**Licenses:** independently re-verified on HuggingFace 2026-07-12 (not taken from the design on faith).
**Verdict:** **GO WITH CAVEATS.** The feature is an architecture/method build; ~85-90% of the backend already ships behind clean lazy seams. The ONLY non-permissive model in the stack is an OPTIONAL 2nd-pass aligner that degrades to a permissive baseline, and the codebase already has the permissive-override switch. The single blocking action is a packaged-default config flip (WU-T0).

---

## 1. Go / No-Go verdict

**`go-with-caveats`.**

A fresh reviewer must agree on two things; both hold:

1. **The models are permissive + local.** The feature ships 100% commercial-clean on **openai/whisper-large-v3-turbo (MIT)** word timestamps ALONE — that model is the always-installed default ASR (`transcribe.py:74 DEFAULT_MODEL = "large-v3-turbo"`, `word_timestamps=True` at line 351). Every accuracy upgrade is also permissive: Parakeet-TDT-0.6b-v3 (CC-BY-4.0, attribution), wav2vec2-large-960h-lv60-self / gigant/romanian-wav2vec2 / XLSR-53 family / hubert-large-ls960-ft (all Apache-2.0). The one CC-BY-NC model (MMS forced-aligner) is an **optional precision 2nd pass** that `ctc_align.align_words` degrades away from (returns the input transcript unchanged) whenever it is absent/offline/fails.
2. **The plan is real-functional-verifiable.** Every net-new unit is pure timeline math over shipped, already-100%-covered engines, PLUS a distinct real-functional integration tier (WU-T7) that re-transcribes the rendered output and asserts deleted tokens are absent — a gate a green-mocked cut-list cannot fake.

**Caveats (all addressable, none a fundamental no-go):**
- **C1 (blocking, small):** the packaged CTC-aligner default is CC-BY-NC (MMS). Must be flipped to a permissive default before commercial ship — WU-T0. This is a **config-default flip, not a missing-model problem**: the permissive alternatives already exist in the same module (`MIT_MODEL_IDS`, `RO_MODEL_IDS`).
- **C2:** Parakeet CC-BY-4.0 requires an attribution NOTICE line when it is the active engine.
- **C3 (scope):** REORDER-by-text (the Descript/Premiere differentiator) is the ONE real backend gap. DELETE + FILLER + SILENCE ship in v1.5; REORDER is a time-boxed fast-follow (WU-T6).
- **C4 (hygiene):** `ctc_align.py` mislabels wav2vec2-large-960h-lv60-self as "MIT" — HF says Apache-2.0. Correct the label (both permissive; no functional block).

Why NOT `no-go-licensing`: the only viable models are NOT non-permissive — the reverse is true. The permissive stack (MIT Whisper baseline + Apache aligners + CC-BY Parakeet) is fully sufficient; the NC model is opt-in only.

---

## 2. Exact models to adopt — with licenses (HF-verified 2026-07-12)

| Model (HF id) | Role | License | Local/offline | Commercial | Notes |
|---|---|---|---|---|---|
| `openai/whisper-large-v3-turbo` (via faster-whisper) | **Default ASR + native word timestamps** | **MIT** (weights) + faster-whisper **MIT** (code) | Yes, CPU-viable/GPU-opt | ✅ clean | 99 langs incl. `ro`; `word_timestamps=True`; **feature ships on this alone** |
| `nvidia/parakeet-tdt-0.6b-v3` | High-accuracy EN/EU ASR opt-in + native word timing | **CC-BY-4.0** | Yes (NeMo, 6GB via chunking) | ✅ with attribution | 25 EU langs incl. `ro`; needs NOTICE (C2) |
| `facebook/wav2vec2-large-960h-lv60-self` | **Commercial default CTC aligner (EN)** | **Apache-2.0** | Yes | ✅ clean | replaces MMS as packaged default; code mislabels "MIT" (C4) |
| `gigant/romanian-wav2vec2` | CTC aligner (RO) | **Apache-2.0** | Yes | ✅ clean | base facebook/wav2vec2-xls-r-300m |
| `jonatasgrosman/wav2vec2-large-xlsr-53-*` (family) | Per-language permissive aligner map | **Apache-2.0** | Yes | ✅ clean | fills the language→permissive-CTC map |
| `facebook/hubert-large-ls960-ft` | Alt EN CTC aligner | **Apache-2.0** | Yes | ✅ clean | already in `MIT_MODEL_IDS` |
| `MahmoudAshraf/mms-300m-1130-forced-aligner` | 158-lang forced aligner | **CC-BY-NC-4.0** | Yes | ⛔ **NON-COMMERCIAL** | **opt-in ONLY — must NOT be the packaged default** |

**Word-timing strategy (licensing-first):** PREFER native ASR word timestamps — Whisper (MIT) always, Parakeet (CC-BY) when selected — which sidesteps the aligner licensing trap entirely (zero extra model). CTC forced alignment is a **precision UPGRADE** (~20-120 ms vs Whisper DTW ~100-500 ms), gated per-language to a permissive aligner, degrading to Whisper-native where no permissive aligner exists.

---

## 3. Commercial blockers + mitigations

| # | Blocker | Severity | Mitigation | WU |
|---|---|---|---|---|
| B1 | `ctc_align.DEFAULT_MODEL_ID = MahmoudAshraf/mms-300m-1130-forced-aligner` is CC-BY-NC-4.0 and is the packaged default via `_resolve_model_id` fallback | **HIGH (blocking)** | Flip packaged default to `wav2vec2-960h-lv60` (Apache, EN) + a language→permissive-CTC map (gigant RO, XLSR-53 family); degrade to Whisper MIT native word timestamps where none exists; gate MMS behind an explicit `allowNonCommercialAligner` opt-in | T0 |
| B2 | `nvidia/parakeet-tdt-0.6b-v3` is CC-BY-4.0 (attribution obligation) | LOW | Ship an About/licenses NOTICE line shown when Parakeet (or any CC-BY aligner) is the active engine | T0 / T5 |
| B3 | `ctc_align.py` labels wav2vec2-large-960h-lv60-self as "MIT"; HF = Apache-2.0 | LOW (hygiene) | Correct the comment + asset label (both permissive) | T0 |
| B4 | Copying third-party editors: transcribee is **AGPL-3.0**; WhisperX code is BSD-2 but its non-EN default align map bundles **CC-BY-NC** models | MEDIUM (avoid re-introducing NC) | Do NOT port transcribee code at all; may reference WhisperX BSD-2 patterns but do NOT copy its non-EN CC-BY-NC align-model map | T0 / T6 |
| B5 | Future Overdub-style word **regeneration** (TTS/voice-clone) re-enters the NC-weight minefield + triggers a hard consent gate | N/A (scope guard) | Explicitly OUT OF SCOPE for v1.5; DELETE/REORDER/TRIM/FILLER/SILENCE only (no synthesis) | — |

---

## 4. Architecture (grounded in real origin/main seams)

The feature = a non-destructive **ordered keep-list (EDL)** binding every transcript word to an ms timecode, a pure transcript-diff→EditPlan translator, a new Transcript inspector pane over the #288 `EditorContext` shared stage, and the B1 default flip. Verified seams:

- **ASR** — `features/transcribe.py` (faster-whisper `large-v3-turbo`, `word_timestamps=True`) or `features/parakeet_asr.py` (`settings["asrEngine"]="parakeet"`) → the §3 `Transcript {language, segments:[{start,end,text,words:[{text,start,end}]}], durationSec}`.
- **Optional refine** — `features/ctc_align.py::align_words` → tightens word timing; **degrade-never-raise** (`ALIGN_SKIPPED_NOTICE`), returns input unchanged when the model is missing/offline/fails. Commercial default = permissive aligner (post-T0).
- **Persist** — `library.py` (`Project = {id, video, transcript?, tracks, clips, settings}`, `Video.hasTranscript`, `set_has_transcript(...)`). NEW: stamp a stable `wordId` (or `segmentIndex+wordIndex`) at persist so text↔timeline is bidirectional and edits survive re-transcription (additive backfill mirroring the optional `transcript` handling).
- **Compose** — `features/refine.py::plan_refine` composes filler cut-lists + silence keep-spans into ONE union keep-list + stats (the "see before you cut" planner). **`refine._union_spans` SORTS + merges** → reorder MUST bypass it (verified: `refine.py:94`).
- **Cut** — `features/fillers.py::build_segment_cut_argv` builds a frame-accurate `filter_complex` trim/atrim + `concat=n=N` **in list order, no sort** (verified `fillers.py:364` preserves order) → **reorder + repeat already work at the ffmpeg layer** once an engine + cue remap exist. Cue re-timing = `fillers.remap_cues`/`remap_time` — but these **assume MONOTONIC keeps** (verified `fillers.py:305`), so reorder needs a NEW segment-aware remap.
- **Apply (reversible)** — `features/apply_engine.py::apply_plan(plan, *, project_copy, engines, inverse_engines, allow_irreversible)` walks `EditPlan.ops` over a project COPY (source never touched), dispatches each op to `engines[kind]`, records an inverse op → one-shot `director.undo`. `models/edit_plan.py::OpKind` already includes `cut/reorder/removeFillers/removeSilence` (verified). `features/director_op_engines.py::DEFERRED_KINDS = ("reorder", ...)` — reorder is the deferred single-clip permutation (verified line 105).
- **Integrity** — `features/edit_validate.py::validate_and_reject` (PURE, never raises; drops impossible/injected spans with a typed reason; `reorder/cut/removeSilence/removeFillers` in `_SPAN_REQUIRED_KINDS`).
- **Export** — `features/nle_export.py` (FCPXML/EDL) consumes the ordered EDL directly.
- **Contract** — `sidecar/contract/spec.py` (NOTE: **not** `sidecar/media_studio/contract/…`). `MethodSpec{name, ts_path, params, binding, result_ts, result_imports, needs_key, kind}` — the design omitted the **required `result_imports`** field; JobHandle imports from `_HAND = "../schemas"`. Only ~6 methods are migrated to MethodSpec generation; the rest are runtime-only via `protocol.register` → **dual registration is mandatory**.
- **UI** — `features/EditorContext.tsx` (#288 shared stage), `features/Timeline.tsx` (+ `timeline.peaks` waveform), `features/caption/CaptionInspector.tsx` (pane to mirror), `lib/editorState.ts` (reducer to extend), `lib/directorTypes.ts` (TS-type-from-contract pattern), `lib/rpc/client.ts`.

### 4.1 The single-render vs apply_engine resolution (a real design tension)

`refine.apply` does **ONE** render via `build_segment_cut_argv` (union keep-list) and does **NOT** route through `apply_engine`. `apply_engine` walks ops one-at-a-time — each op is a potential separate encode. Resolution the plan adopts:

- **v1 (DELETE + FILLER + SILENCE — all monotonic):** mirror `refine.apply` exactly — `plan_refine` union keep-list → `build_segment_cut_argv` → `*.edited.mp4` (original untouched) → `remap_cues` (monotonic, existing). **ONE encode.** Undo is trivially available (original untouched → re-point). LOW risk, reuses shipped+tested code.
- **v1.5 fast-follow (REORDER):** the ordered-EDL path. A single ordered keep-list expresses delete+filler+silence+reorder+repeat at once (build_segment_cut_argv concats in list order) → still ONE encode, but the keep-list is **non-monotonic** so it needs the NEW segment-aware cue remap. Route through `apply_engine` (emit `reorder`/`cut` ops) so `director.undo` records the inverse and the Director agent stays consistent. If a workflow chains a monotonic cut AND a reorder as separate ops, that is 2 encodes — documented, acceptable, optimizable later by baking cuts into the single ordered EDL.

---

## 5. RPC additions (dual registration — verified against spec.py)

Three methods, all `needs_key=False` (100% local, no provider egress → off the keyBridge allowlist):

- **`transcript.get`** — DIRECT reader. `MethodSpec(name="transcript.get", ts_path=("transcript","get"), params=TranscriptGetParams, binding=NAMED, result_ts="{ transcript: Transcript }", result_imports=(("Transcript", _OWN),), needs_key=False, kind="direct")`.
- **`transcript.previewEdit`** — DIRECT planner (mirror `refine.preview`). `result_ts="{ plan: TranscriptEditPlan }"`, `result_imports=(("TranscriptEditPlan", _OWN),)`, `kind="direct"`. No encode, no write.
- **`transcript.applyEdit`** — JOB (mirror `refine.apply`). `result_ts="JobHandle & { editId?: string }"`, `result_imports=(("JobHandle", _HAND),)`, `kind="job"`. `job.done.result = {path, removedSec, cues, editId, plan}`; writes `*.edited.mp4` (original untouched).

**New param dataclasses** (spec.py): `TranscriptGetParams{videoId}`; `EditSpan{op:'delete'|'reorder'|'trim'|'restore', wordId?:str | segmentIndex:int+wordIndex:int, startMs?:int, endMs?:int, toIndex?:int}`; `TranscriptEditParams{videoId, edits:list[EditSpan], removeFillers?:bool, removeSilence?:bool}`.

**New DATA_MODELS** (emit to `schemas.generated.ts` + Python validators): `Word{text,start,end,score?}`, `Segment{start,end,text,words}`, `Transcript{language,segments,durationSec}`, `TranscriptEditPlan{keeps,stats,cues}`. `Video.hasTranscript` already exists.

**Typed Settings keys** (the #282 stringly-typed fix — add to the `Settings` dataclass; note `ctcModelId` is currently read by `ctc_align` but is NOT declared): add `ctcModelId: str | None = None`, `asrEngine: str | None = None`, `allowNonCommercialAligner: bool | None = None`. A typo becomes a compile error, not a silent `None`.

**Dual registration (mandatory):** (a) add the 3 MethodSpec entries + new DATA_MODELS to `spec.py` and run `contract.generate` — the drift gate `test_generated_artifacts_are_current` must stay green; (b) register the SAME methods at runtime via a NEW `features/transcript_edit.py::register()` using `protocol.register` (register_fn default), wired into `handlers/composition.py::register_all` immediately after `_refine.register(...)` (verified line 503), passing the same seams (resolver, out_dir, load_project, save_project, settings_provider, run, duration). Add a parity test asserting both sides agree.

**No new undo RPC** — `director.apply`/`director.undo` already provide the reversible walk; `applyEdit` emits an EditPlan (`cut`/`reorder`/`removeFillers`/`removeSilence` — all present in `OpKind`) and hands it to `apply_engine`.

---

## 6. Work units (build order: keystone-first, pure-before-heavy, TDD)

| ID | Title | Scope |
|---|---|---|
| **T0** | Commercial licensing flip + typed settings + NOTICE (KEYSTONE / go-no-go pivot) | Add typed `ctcModelId`/`asrEngine`/`allowNonCommercialAligner` to `spec.py` Settings; flip `ctc_align` packaged default so `_resolve_model_id` no longer falls back to CC-BY-NC MMS (default `wav2vec2-960h-lv60` Apache; language→permissive-CTC map: gigant RO, XLSR-53 family; degrade to Whisper-native elsewhere); gate MMS behind `allowNonCommercialAligner`; correct the "MIT"→Apache-2.0 mislabel; add Parakeet CC-BY NOTICE entry. Regenerate contract; drift gate green. TDD: assert default never resolves to MMS unless opt-in true; per-language map picks Apache models; degrade path returns Whisper-native word timings. |
| **T1** | EDL data model + `wordId` addressing + contract data models | Add `Word/Segment/Transcript/TranscriptEditPlan` + `TranscriptGetParams/EditSpan/TranscriptEditParams` to `spec.py` DATA_MODELS/params. Stamp a stable `wordId` (or `segmentIndex+wordIndex` fallback) at persist in `library.py` (additive backfill mirroring optional `transcript` handling; old projects round-trip). Pure, TDD 100% branch. |
| **T2** | Pure transcript-diff→EditOps translator (renderer) | New `app/renderer/src/lib/transcriptEdit.ts` — PURE edited-vs-original token order → EditOps keyed to word `[startMs,endMs]` (delete=omitted, reorder=permutation, trim=boundary nudge). Extend `editorState.ts` reducer. Generate `transcriptEditTypes.ts` from the contract. Renderer 100% (vitest). No RPC, no render. |
| **T3** | Python `transcript_edit` translator + service (preview/applyEdit) — DELETE+FILLER+SILENCE (v1 SHIP slice) | New `features/transcript_edit.py::TranscriptEditService` mirroring RefineService seams. `previewEdit` (direct): translate EditSpans → union keep-list via shipped `plan_refine` + `fillers.build_cutlist`; return `{plan:{keeps,stats,cues}}` (monotonic `remap_cues`). `applyEdit` (job): compose union keep-list, render ONCE via `build_segment_cut_argv` → `*.edited.mp4` (original untouched), remap cues, return `{path,removedSec,cues,editId,plan}`. Pure `translate_edits(edits, transcript)` 100% branch; service branches via fake `run`/`duration`. **100% commercial-clean on Whisper-native alone.** |
| **T4** | Dual contract registration + drift parity | Add 3 MethodSpec entries (with `result_imports`) + DATA_MODELS to `spec.py`; run `contract.generate`; keep `test_generated_artifacts_are_current` green. Wire `transcript_edit.register()` into `composition.register_all` after `_refine.register` (line ~503). Parity test both sides. `needs_key=False` ×3. |
| **T5** | Transcript inspector pane (renderer UI) | Mirror `caption/CaptionInspector.tsx`, mounted in `EditorContext` `key={videoId}`, thin `useEditor()` over shared `Timeline.tsx` + `timeline.peaks` waveform (no new provider). Word token list (strike-delete, filler underline, click-to-seek, karaoke playhead), one-click removeFillers/removeSilence toggles, "see before you cut" preview panel (removedSec/stats/cues + re-synced overlay), word-boundary nudge escape hatch, undo/redo→`director.undo`, EDL/NLE handoff via `nle_export.py`, Parakeet/CC-BY attribution surface (B2). Renderer 100%. |
| **T6** | REORDER fast-follow: segment-aware cue remap + single-clip reorder OpEngine (the ONE backend gap) | New segment-index-aware cue remap (positions each cue by cumulative duration of segments preceding its instance in OUTPUT order — replaces monotonic `remap_time` for reordered/repeated spans). Single-clip word-REORDER OpEngine in `director_op_engines.py` (build keeps in output order → `build_segment_cut_argv`; record inverse); remove `"reorder"` from `DEFERRED_KINDS`. Route ordered edit through `apply_engine.apply_plan` (director.undo inverse). Explicit ordering rules: reorder MUST bypass `refine._union_spans` (it sorts+merges). One-time "reordering can change meaning" notice + `validate_and_reject` + reversible undo. Time-boxed. |
| **T7** | Real functional verification harness (anti-green-mock gate) | Integration tier proving the edit WORKS. Golden round-trip: ASR → delete known words → RE-transcribe output → assert deleted tokens absent + neighbors intact. ffmpeg: output duration == sum(kept spans) ±1 frame (ffprobe). Reorder A/B: 2-clip swap frame + audio-sync + SAR/timebase. Undo: byte/duration-equal to pre-edit copy. Runs REAL ffmpeg + a tiny real ASR pass on a fixture clip (pinned model revision for determinism; longrun-wrapped). Distinct from the 100%-branch pure-unit tier. |

**Ship gate for v1.5:** T0–T5 + T7 (DELETE+FILLER+SILENCE, commercial-clean, functionally verified). **T6 (REORDER)** is the time-boxed differentiator fast-follow. T0 is the keystone — nothing ships commercial without it.

---

## 7. 100%-coverage testing strategy for ML-boundary code (deterministic, not mock-sandwich)

The repo already MANDATES 100% (`.coverage-thresholds.json`: sidecar `pytest --cov-fail-under=100 --cov-branch`; renderer vitest 100% lines/branches/functions/statements — a BLOCKING `quality.yml` gate). The strategy inherits the shipped **pure/heavy-seam split** (seen in `ctc_align`/`transcribe`/`parakeet_asr`/`refine`) and adds a distinct functional tier:

1. **Pure half = 100% branch, deterministic, no I/O.** The translator (`translate_edits`: EditSpans→keep-list/EditOps), `plan_refine` composition, cue remap (monotonic AND segment-aware), and the reorder OpEngine's keep-ordering are PURE. Tested with hand-built transcripts + canned edits, asserting on **VALUES** — the exact keep-list, exact cue times, the exact inverse op — computed by the real functions. No torch, no ffmpeg, no model.

2. **Heavy half behind lazy seams, exercised with INJECTED fakes.** ASR (`WhisperLoader`/`ParakeetLoader`), the aligner (`CtcAlignBackend` Protocol), ffmpeg (`run`/`duration`), and the project store (`load_project`/`save_project`) are all injectable. Prod-only lines (the real HF/NeMo import, the ffmpeg subprocess) carry `# pragma: no cover`; every branch around them is covered by injecting a fake that returns canned spans / exit code 0 / a fake duration — exactly how `refine`/`ctc_align` tests already reach 100%.

3. **Deterministic ≠ mock-sandwich.** A mock-sandwich test asserts "`build_segment_cut_argv` was called with X" — green even if X is wrong. Instead: the unit tier asserts on the **produced values** (the argv's trim start/end times, the keep-list, the remapped cue seconds) that the REAL pure functions compute over REAL fixtures — deterministic without I/O. The argv is verified by structure+values, not by "was it called".

4. **Real functional tier (WU-T7) = the falsification gate.** A SEPARATE integration suite runs the ACTUAL ffmpeg on a tiny fixture and asserts on OBSERVABLE OUTPUT: (a) **re-transcribe** the rendered `*.edited.mp4` and assert the deleted word's tokens are ABSENT and neighbors intact — a real ASR model output, deterministic against a KNOWN transcript with a pinned model revision (`hf_revision` commit hashes already pin this); (b) ffprobe duration == sum(kept spans) ±1 frame; (c) reorder A/B frame + audio-sync + SAR/timebase; (d) undo byte/duration-equal to the pre-edit copy. This tier CANNOT be satisfied by a green pure-unit suite over fake cut-lists — it is what separates "green-mocked" from "works".

5. **Degrade/licensing-safety branches are covered.** The Whisper-native fallback (aligner absent/offline/failed → transcript unchanged), the empty-transcript pass-through, and the `allowNonCommercialAligner` gate are covered by injecting a failing/absent seam and asserting pass-through — these are the branches that keep the build commercial-clean, so they are non-negotiable coverage.

---

## 8. Ethics / consent gate

For the in-scope feature (delete/reorder/trim/filler/silence of ALREADY-RECORDED words) there is **NO consent gate at any competitor** — it is normal NLE editing; no biometric/voiceprint/faceprint is created (ASR text over existing media, not voice/face ID or synthesis). Do NOT bolt a heavyweight consent gate onto transcript editing — no peer precedent, pure friction. The only industry consent gate (Descript Overdub: read-a-statement + ~10 min audio + verbal consent) is for **voice-cloning / word regeneration**, which is explicitly OUT OF SCOPE (B5) and would trigger a HARD gate if ever added.

**The relevant ethics surface is LOCAL-FIRST:** transcript + media never leave the machine → zero egress → no gate fires. The shipped per-data-type `models/consent.py` (default-deny) already governs the only case that could ever need one (an OPTIONAL cloud-LLM "suggest cuts" assist), unchanged. **Proportionate integrity guardrails (above the industry bar, cheap, non-blocking):** a one-time "reordering can change meaning / may misrepresent what was said" notice on the FIRST reorder-by-text (splicing words out of order can fabricate a quote), backed by `edit_validate.validate_and_reject` (drops impossible/injected spans, never raises) + reversible `director.undo` + rationale/statusReason text that is shown but NEVER trusted as an instruction.

---

## 9. Risks (verified) + mitigations

- **LICENSE (highest, same class as the no-license S3FD catch):** MMS aligner default is CC-BY-NC → WU-T0 flip + opt-in gate. **Verified:** `ctc_align.py:101` + docstring §Decision-#1.
- **REORDER cue-remap desync:** `remap_time`/`remap_cues` assume MONOTONIC keeps → wrong times for reordered/repeated spans. New segment-aware remap; verify on a real 2-clip swap (frame + audio-sync) + concat SAR/timebase. **Verified:** `fillers.py:305`.
- **REORDER must bypass the union:** `refine._union_spans` SORTS + merges (would destroy order + collapse repeats). Keep reorder an ordered EDL straight to `build_segment_cut_argv`; only delete/filler/silence go through the sorted union. **Verified:** `refine.py:94,166`.
- **Word-timing precision:** Whisper DTW drifts ~100-500 ms → cuts can clip a phoneme/proper noun. Mitigate with the permissive CTC/Parakeet ~20-120 ms refine + manual word-boundary nudge; prove with the re-transcribe golden gate.
- **Green-mocked ≠ works:** enforced by the WU-T7 functional tier (§7.4).
- **Word-address stability:** word dicts are positional today → stamp `wordId` at persist, additive backfill (WU-T1).
- **Dual-contract drift:** register BOTH the runtime `protocol.register` AND the `spec.py` MethodSpec (with `result_imports`); add the parity test (WU-T4).
- **Perf/cost:** long videos → large token lists (render perf) + a re-encode per apply (compose into ONE ordered EDL → one encode). Parakeet covers 25 EU langs, Whisper 99 (coarser timing) — set per-language expectations; Whisper stays the multilingual fallback.

---

## 10. Fresh-reviewer checklist

- [x] Models permissive + local: Whisper MIT baseline ships the whole feature; Parakeet CC-BY + wav2vec2/gigant/XLSR/hubert Apache are upgrades. HF-verified 2026-07-12.
- [x] The one NC model (MMS) is optional 2nd-pass, degrades to Whisper-native, has a permissive override switch already in-module.
- [x] Blocker is a config-default flip (WU-T0), not a missing-model problem.
- [x] Plan is real-functional-verifiable: pure 100%-branch tier + a re-transcribe/ffprobe/undo functional tier that a mock cannot fake (WU-T7).
- [x] Every seam cited was read from `origin/main` (paths + line numbers verified; contract path corrected to `sidecar/contract/spec.py`; `result_imports` field noted).
- [x] Reorder is honestly scoped as the one backend gap + fast-follow, with the exact non-monotonic-remap correctness risk called out.
