# Editing-Refinement Bundle — DESIGN

**Status:** DESIGN (docs only; no feature code). Must pass design-review + plan gates before BUILD.
**Branch:** `feat/editing-refine-design` (off `origin/main`).
**Scope:** (A) filler-word + silence detection/removal as a *tightenable, reversible* edit (Descript-style "tighten the edit"); (B) speaker diarization labels surfaced into the *transcript + captions*.
**Date:** 2026-06-18.

> RAILS: every claim below cites real code in this repo. Where a capability does
> not exist, it is named explicitly as a GAP. All paths are relative to repo root;
> sidecar paths are under `sidecar/media_studio/`.

---

## 0. Headline finding (ground truth, read before anything else)

**Most of the heavy lifting for this bundle is already shipped.** The engines exist
and are tested; the bundle's real work is a thin **editability + surfacing layer**,
plus closing two concrete seam gaps. Do NOT re-build the engines.

Already shipped (cited):

| Capability | Module | Wire surface today |
|---|---|---|
| Filler-word cut-list math + frame-accurate concat argv + cue remap | `features/fillers.py` (`build_cutlist_with_stats` L201, `build_segment_cut_argv` L351, `remap_cues` L324) | **None standalone** — only consumed inside the batch shortmaker (`features/shortmaker.py:225-236`, gated by `settings["removeFillers"]` at `shortmaker.py:908`) |
| Silence / dead-air detection + invert-to-keeps + re-cut | `features/silencetrim.py` (`detect_silence_spans` L159, `keep_spans` L107, `trim_clip` L199) | `silence.trim` RPC (`silencetrim.py:360`; registered `handlers.py:2176`) + shortmaker pre-step (`shortmaker.py:882`) |
| Speaker diarization (token-free local: SpeechBrain VAD→ECAPA→greedy cosine cluster) | `features/diarize.py` (`diarize_transcript` L179, `greedy_cluster` L92, `assign_speakers_to_segments` L134) + backend `diarize_backend.py`; pyannote alt backend `pyannote_backend.py` | `diarize.start` RPC (`diarize.py:399`; registered `handlers.py:2219`, backend selectable via `settings["diarizeBackend"]` per `handlers.py:1080-1108`). Renderer panel exists: `app/renderer/src/features/Diarize.tsx` |

The **two real gaps** this bundle must close:

1. **Filler removal has no standalone, previewable, reversible RPC.** It only runs
   buried in the shortmaker batch pipeline as a boolean flag. There is no way to
   *see the proposed filler cuts*, tune them, or apply them to an arbitrary clip —
   the Descript "tighten the edit" experience.
2. **Diarization output never reaches captions.** `diarize.start` stamps a
   `speaker` field on every transcript segment (`diarize.py:170`), but
   `subtitles.cues_from_transcript` (`subtitles.py:125-149`) **never reads
   `seg["speaker"]`**, and `subtitles.reindex` (`subtitles.py:107-119`) copies
   ONLY `index/start/end/text` — so the speaker label is silently dropped on the
   way to cues/SRT/ASS/VTT. Speakers are diarized but invisible in the output.

This DESIGN therefore is mostly **wiring + UX + gap-closing**, riding the shipped
substrate, not net-new engines.

---

## 1. User value & MVP cut

### User value
- **Tighten the edit (Descript-style):** one action removes "um/uh/like" fillers
  and long dead-air from a clip, shows you *what it will cut and how many seconds
  it saves before committing*, and keeps captions in sync. Reversible.
- **Know who's talking:** the transcript and the burned/soft captions show speaker
  labels ("SPEAKER_00:" or a renamed "Alex:") so multi-speaker footage reads
  clearly.

### MVP cut (smallest shippable slice that delivers the value)
- **A1. `refine.preview`** — a *dry-run* RPC: given a `videoId|path` + the project
  transcript's word timings, return the proposed **keep-spans + per-category
  stats** (`fillersRemoved`, `fillerSeconds`, `silenceRemovedSec`) WITHOUT
  re-encoding. Pure reuse of `fillers.build_cutlist_with_stats` +
  `silencetrim.detect_silence_spans`/`keep_spans`. This is the "see it before you
  cut" half.
- **A2. `refine.apply`** — apply the (possibly user-tuned) keep-spans to a clip via
  `fillers.build_segment_cut_argv` → a job → `{path, removedSec, stats}`. Writes a
  NEW output file (original untouched). Re-times any caption cues via
  `fillers.remap_cues`.
- **B1. Speaker→cue plumbing** — make `subtitles.cues_from_transcript` carry the
  segment's `speaker` onto each cue (additive field), and have `reindex` preserve
  it. Optional speaker *prefix* in rendered text (`"SPEAKER_00: …"`), gated by a
  setting.
- **B2. `diarize.rename`** — map raw `SPEAKER_NN` → friendly names on the persisted
  transcript (e.g. `{ "SPEAKER_00": "Alex" }`), so labels are human.
- **UI:** one **Refine** renderer panel (preview list + per-category toggles +
  Apply) and a speaker-rename affordance on the existing `Diarize.tsx` panel.

**Explicitly OUT of MVP (deferred):** waveform/transcript scrubbing UI, click-to-delete
individual words on a timeline, per-speaker color theming in burned captions,
multi-clip batch refine UI (the shortmaker already does batch). These are listed
in §7.

---

## 2. Architecture — reuse vs NEW

### Reuse (no change to engine logic)
- `features/fillers.py` — `build_cutlist_with_stats`, `build_segment_cut_argv`,
  `remap_cues`, `remap_time`. Already the exact "tighten" math. (L201/L351/L324/L305)
- `features/silencetrim.py` — `detect_silence_spans`, `keep_spans`,
  `removed_seconds`, `trim_clip`. (L159/L107/L150/L199)
- `features/diarize.py` — `diarize_transcript`, `roster`, `speaker_label`,
  `assign_speakers_to_segments`. (L179/L174/L129/L134)
- `ffmpeg.py` resolver + drained `run` seam (used by `build_segment_cut_argv` at
  `fillers.py:367` and `silencetrim.trim_clip:244-245`).
- `jobs.py` `JobContext` (progress/cancel) — diarize/silence already use it; refine
  jobs follow the identical pattern (`silencetrim.py:309-330`).
- Project/transcript store seams: `_load_or_create_project` / `project.save()` as in
  `handlers.subtitles_generate` (`handlers.py:730-744`) and diarize's
  `load_project`/`save_project` seams (`diarize.py:311-313`).
- **AI-Job envelope** (`models/ai_job.py`) — used ONLY for the optional AI-assisted
  parts (see §5); the core filler/silence/diarize paths are 100% local and need NO
  envelope.

### NEW components (small, all behind seams, all unit-testable to 100%)
- **`features/refine.py`** (NEW, pure + a service) — the unifying "tighten the
  edit" feature:
  - `plan_refine(words, lang, total_sec, silences, *, remove_fillers, remove_silence, merge_gap_ms, pad_sec) -> RefinePlan` — **pure**: intersect/union the filler keep-spans (`fillers.build_cutlist`) with the silence keep-spans (`silencetrim.keep_spans`) into ONE keep-list + a typed stats block. No subprocess, no model. Fully testable with hand-built words + fake silence spans.
  - `RefineService.preview(params, ctx)` — resolve clip + transcript, run
    `silencetrim.detect_silence_spans` (injected `run` seam) + `plan_refine`,
    return the plan (NO encode). Reuses the silencetrim detection seam verbatim.
  - `RefineService.apply(params, ctx)` — take a plan (or recompute), run
    `fillers.build_segment_cut_argv` through `ffmpeg.run` as a job, remap caption
    cues, return `{path, removedSec, stats}`. New output file; original kept.
  - `register(...)` mirroring `silencetrim.register` (`silencetrim.py:336-362`).
- **Subtitles speaker carry** — *edit existing* `subtitles.py`:
  `cues_from_transcript` reads `seg.get("speaker")` and sets it on each cue;
  `make_cue`/`reindex` preserve an optional `speaker` key; a new
  `format_speaker_prefix(cues, *, on)` helper prefixes text when the setting is on.
  Additive — the frozen §3 Cue keeps `index/start/end/text`; `speaker` is an
  optional extra field (mirrors how `DiarizedSegment` extends `Segment` in
  `Diarize.tsx:19`).
- **`diarize.rename`** — small pure mapping helper in `diarize.py`
  (`rename_speakers(transcript, mapping) -> transcript`, immutable like
  `assign_speakers_to_segments`) + a direct-return RPC handler.
- **Renderer:** `app/renderer/src/features/Refine.tsx` (NEW) + a speaker-rename
  block added to `Diarize.tsx`. Both consume the FROZEN `window.api` bridge via the
  shared `./_api` helpers (same pattern as `Diarize.tsx:14`).

### Why a unifying `refine.py` instead of two RPCs
Filler removal and silence removal both compile to the SAME `build_segment_cut_argv`
keep-list concat. Doing them in one pass (one re-encode, one cue-remap) avoids a
double-encode and a double cue-remap mismatch. `silence.trim` stays as-is for
back-compat; `refine.*` is the new previewable/combined surface. The shortmaker
keeps its existing inlined path (`shortmaker.py:882-913`) unchanged.

---

## 3. RPC surface (new `*.*` handlers in `register_all`)

Registered in `handlers.register_all` (`handlers.py:1982`) following the exact
module-owns-its-`register()` idiom used at `handlers.py:2176` (silencetrim) and
`handlers.py:2219` (diarize). Naming follows CONTRACTS.md §2 dotted convention
(`subtitles.generate`, `silence.trim`, `diarize.start`).

| New RPC | Shape | Kind | Reuses |
|---|---|---|---|
| `refine.preview` | `{videoId|path, removeFillers?, removeSilence?, lang?, mergeGapMs?, noiseDb?, minSilenceSec?, padSec?}` → `{plan:{keeps,stats:{fillersRemoved,fillerSeconds,silenceRemovedSec,keptSec}}}` | direct (detection only; no encode) | `silencetrim.detect_silence_spans`, `fillers.build_cutlist_with_stats`, NEW `refine.plan_refine` |
| `refine.apply` | `{videoId|path, keeps?|(removeFillers,removeSilence...), cues?}` → `{jobId}` → `{path, removedSec, stats, cues?}` | job | `fillers.build_segment_cut_argv`, `ffmpeg.run`, `fillers.remap_cues` |
| `diarize.rename` | `{videoId, mapping:{SPEAKER_NN: name}}` → `{transcript}` | direct | NEW `diarize.rename_speakers` (pure, immutable) + project store |

Edited existing RPCs (behavior additive, contract-safe):
- `subtitles.generate` (`handlers.py:722`) — cues now carry `speaker` when the
  transcript was diarized; rendered prefix gated by `settings["captionSpeakerLabels"]`.
  No change to the `{track}` return shape.

`silence.trim` (`silence.trim`, `silencetrim.py:360`) and `diarize.start`
(`diarize.py:399`) are unchanged.

### Renderer surface
- `Refine.tsx` (NEW feature panel): "Tighten the edit" — calls `refine.preview`,
  renders the keep/cut list + saved-seconds, exposes **Remove fillers** /
  **Remove silence** toggles + the tunables (noiseDb, minSilenceSec, mergeGapMs),
  then **Apply** → `refine.apply` job with progress (same job-progress pattern as
  `Diarize.tsx:62-101`). Original-vs-result both surfaced.
- `Diarize.tsx`: add a per-speaker rename row (text input per `SPEAKER_NN`) →
  `diarize.rename` → refresh roster. Existing run/cancel/progress untouched.
- Both wire through `getApi()`/`bridge.rpc`/`waitForJobDone` from `features/_api.ts`
  (the frozen bridge, `Diarize.tsx:14`). New strings localize via existing i18n if
  present; otherwise inline (match current panels).

---

## 4. Data / storage & settings keys

### Data shapes (all additive to CONTRACTS.md §3)
- **Cue** gains an OPTIONAL `speaker?: string`. Frozen `index/start/end/text` stay.
  Mirrors `DiarizedSegment = Segment & { speaker?: string }` already shipped in
  `Diarize.tsx:19`.
- **RefinePlan** (NEW, internal+wire): `{ keeps: [[start,end],...],
  stats: { fillersRemoved:int, fillerSeconds:float, silenceRemovedSec:float,
  keptSec:float } }`. Mirrors the existing per-clip stats
  `{fillersRemoved, fillerSeconds}` (`shortmaker.py:1032-1034`) + the silence
  `removedSec` (`silencetrim.py:327`).
- **Transcript** already carries `speaker` per segment + a `speakers` roster
  (`diarize.py:194-198`). `diarize.rename` rewrites both, persisted via the
  project store.

### Storage
- Refine outputs go to the same per-job out_dir convention as silencetrim
  (`silencetrim.py:312-314`: `out_dir / f"{stem}.trimmed.mp4"`) — refine uses e.g.
  `{stem}.refined.mp4`. **Original is never overwritten** (reversibility).
- Renamed speakers persist onto the project transcript (same `save_project` seam
  diarize already uses, `diarize.py:311-313`).

### Settings keys (read via `settings_store` / `self.settings.get()`)
| Key | Type | Meaning | Existing precedent |
|---|---|---|---|
| `captionSpeakerLabels` | bool | prefix cue text with the speaker label on generate/burn | new (mirrors `captionPolish` flag, `handlers.py:738`) |
| `refine.noiseDb` / `refine.minSilenceSec` / `refine.padSec` | float | silence tunables | reuse `silencetrim` defaults (`silencetrim.py:57-60`) |
| `refine.mergeGapMs` | int | filler merge window | `fillers.DEFAULT_MERGE_GAP_MS` (`fillers.py:44`) |
| `refine.fillerSets` | dict | per-language filler sets override (incl. `ro`) | `fillers.DEFAULT_SETS` (`fillers.py:60`) |

Existing `removeFillers` / `silenceTrim` / `diarizeBackend` settings keep their
shortmaker meaning unchanged.

---

## 5. Reversibility / safety + (AI parts) consent/budget via the Hub envelope

### Reversibility & safety (core paths are local + non-destructive)
- **No in-place destruction:** `refine.apply` always writes a NEW file; original
  preserved (matches `silencetrim.trim_clip` pass-through when nothing to cut,
  `silencetrim.py:240-242`).
- **Pure preview:** `refine.preview` runs detection only — zero encode, zero file
  write — so the user always reviews before committing (the Descript "confirm"
  requirement).
- **Word-boundary safety:** filler cuts already land exactly on word
  start/end and never splice sentence boundaries (`fillers.py:14-17`, `_SENTENCE_END`
  guard L168-171). Silence keeps leave `pad_sec` so speech isn't clipped
  (`silencetrim.py:130-135`). Reused verbatim — no new cut math.
- **Caption sync preserved:** `fillers.remap_cues` re-times cues onto the
  compressed timeline and drops cues that collapsed into a cut (`fillers.py:324-345`).
- **Diarize rename is immutable:** new transcript dict, never mutates input
  (matches `assign_speakers_to_segments`, `diarize.py:170`).
- **Detection failures fail-soft:** a probe miss returns "keep everything"
  (`silencetrim.py:189-193`, `225-227`) — refine inherits this; a detection miss
  never deletes content.

### AI parts (and their Hub envelope)
The **MVP filler/silence/diarize paths use NO cloud AI** — diarization is
token-free local (`diarize.py:1-13`), filler/silence are pure ffmpeg math. So the
core bundle needs **no budget/consent gate** (no egress).

The ONE optional AI touchpoint is the **deferred (post-MVP)** "smart filler/refine"
that asks an LLM to judge borderline disfluencies or to clean caption text after a
tighten. IF/when built, it MUST ride the shipped Hub substrate exactly:
- Build `AiInputs` and call `plan_ai_job` (`models/ai_job.py:204`) to get the
  envelope `{route, costEst, cacheKey, willEgress}` (`ai_job.py:95-108`) — surfaced
  to the user via `ai.planJob` for cost-preview + consent BEFORE any egress.
- Run via `run_ai_job` (`ai_job.py:264`) which checks the **cache first**
  (`ai_job.py:19-20`), enforces the **budget degrade chain**, and only egresses
  when `willEgress` is true (`ai_job.py:57-58`). Rotation/provider selection comes
  from `models/provider.py` (the rotation pool) — never a hand-rolled provider call.
- This mirrors how `handlers._run_ai_job` (`handlers.py:1617-1650`) already gates
  AI jobs behind `plan_ai_job_envelope` (`handlers.py:1601-1610`).

No new consent/budget machinery is invented; the Hub envelope is the single AI
gate, used only if/when the optional AI assist lands.

---

## 6. Explicit capability gaps (named, not hidden)

1. **No standalone filler RPC today** — filler removal is locked inside the
   shortmaker batch (`shortmaker.py:908-913`). GAP closed by `refine.*` (§3).
2. **Speaker label is dropped before captions** — `cues_from_transcript`
   (`subtitles.py:125`) ignores `seg["speaker"]` and `reindex` (`subtitles.py:107`)
   strips it. GAP closed by §2 "Subtitles speaker carry".
3. **No speaker rename** — diarization only emits raw `SPEAKER_NN`
   (`diarize.speaker_label`, `diarize.py:129`); there is no human-name mapping.
   GAP closed by `diarize.rename` (§3).
4. **No interactive word/waveform editor** — there is no transcript-scrub or
   click-a-word-to-cut surface anywhere in `app/renderer/src` (only
   `CaptionOverlay.tsx`, `Diarize.tsx`, `Subtitles.tsx` exist). MVP delivers a
   *span/stat preview list*, NOT a word-level timeline editor. True Descript word
   editing is DEFERRED (§7) and is a large net-new UI.
5. **Diarization accuracy is heuristic** — greedy cosine clustering with a fixed
   threshold (`diarize.greedy_cluster`, `diarize.py:92`, `DEFAULT_THRESHOLD=0.5`
   L51); it does not handle overlapping speech or re-merge over-split speakers.
   pyannote backend (`pyannote_backend.py`) is the better-accuracy alt but is a
   gated heavy asset. No change in this bundle — documented limitation.
6. **Filler sets are language-limited** — only `en` + `ro` basics shipped
   (`fillers.DEFAULT_SETS`, `fillers.py:60-86`); other languages fall back to `en`
   (`fillers._lang_sets`, `fillers.py:94-103`). Overridable via `refine.fillerSets`
   but not auto-expanded.
7. **Silence detection is amplitude-only** — ffmpeg `silencedetect`
   (`silencetrim.detect_silence_spans:159`); it cannot distinguish "intentional
   dramatic pause" from "dead air" beyond the dB/duration thresholds. User-tunable,
   not semantic.
8. **No per-speaker caption styling** — even after B1, burned captions get a text
   prefix only; per-speaker color/position theming in `caption.py`/`caption_remotion.py`
   is NOT in scope (§7).

---

## 7. Deferred / future (out of this bundle)
- Word-level transcript-scrub editor (click word → cut), waveform UI.
- Per-speaker caption color/position theming.
- Auto language expansion for filler sets (LLM-suggested per-language disfluencies).
- "Smart refine" LLM judgement of borderline fillers / post-cut caption cleanup
  (would ride the §5 Hub envelope).
- Multi-clip batch refine UI (shortmaker already batches via settings flags).
- Overlapping-speaker diarization / speaker re-merge.

---

## 8. Test & quality plan (BUILD gates — for the PLAN doc to expand)
- **Sidecar:** `pytest --cov-branch --cov-fail-under=100`. New `refine.py` pure
  functions (`plan_refine`, span union, stats) tested with hand-built words + fake
  silence spans (no ffmpeg) — same style as `test_fillers`/`test_silencetrim`.
  Service `preview`/`apply` tested with injected `run`/`detect_run`/`duration` seams
  (mirror `silencetrim.SilenceTrim.__init__` seams, `silencetrim.py:257-272`).
  `diarize.rename_speakers` + subtitles speaker-carry tested purely.
- **Renderer:** vitest `thresholds: 100` (lines/branches/functions/statements —
  `app/vitest.config.ts:44-48`). `Refine.tsx` + `Diarize.tsx` rename block tested
  with an injected `api` bridge (the `api?` prop pattern, `Diarize.tsx:48`).
- **Lint/types:** ruff (sidecar), oxlint/biome + tsc/basedpyright (renderer). Never
  `--no-verify`; never `git add -A`.
- Reuse-first: NO new cut/detection/cluster math — all reused from shipped modules.

---

## 9. Reuse-vs-new summary (one glance)

**REUSE (unchanged engines):** `fillers.py`, `silencetrim.py`, `diarize.py`+backends,
`ffmpeg.run`, `jobs.JobContext`, project store seams, `ai_job` envelope (AI-only,
deferred), `models/provider.py` rotation pool.

**NEW:** `features/refine.py` (`refine.preview`/`refine.apply` + `plan_refine`);
`diarize.rename` + `rename_speakers`; subtitles speaker-carry edits in
`subtitles.py`; `Refine.tsx` panel + `Diarize.tsx` rename block; settings keys
`captionSpeakerLabels` + `refine.*`.

**GAPS NAMED:** standalone filler RPC (closed), speaker→caption plumbing (closed),
speaker rename (closed), word-level editor (deferred), diarization accuracy
(heuristic, documented), filler-language coverage (en+ro only), silence semantics
(amplitude-only), per-speaker styling (deferred).
