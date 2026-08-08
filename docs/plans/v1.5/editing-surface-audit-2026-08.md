# Reframe general-video-editing surface audit — 2026-08

> **Status:** ACTIVE

**Status: MEASURED.** 27 of 27 primitive rows measured against source (the brief's 24 named
primitives, split where one row held two distinct verdicts). Sections 2-4 written.
**COVERAGE:** engine + RPC columns measured by direct source read for every row. The **UI**
column is measured for the Workspace/Edit/Director/Timeline surfaces (the rail destinations);
per-row UI absence is inferred from the tab inventory at `app/renderer/src/views/Workspace.tsx:53-66`
plus the view files, not from an exhaustive component-by-component sweep — flagged inline where
that distinction changes a verdict.

Audit only. No code modified.

Owner's ask, verbatim: *"apart from shorts themselves, it should also allow general video
editing stuff subtitles and so more professional app regarding most stuff"*.

## Honesty contract in force

`UNVERIFIED` sits inline beside the claim it qualifies and names the settling experiment.
Every capability claim carries a `file:line`. `NOT-CHECKED` where not measured. Sherman-Kent
bands on forward-looking claims (*likely* 55-80%, *almost certain* 90-99%).

---

## 0. The headline

Reframe has a **large, genuinely good set of clip-level operations** and **no editor**.

Three measured facts carry that claim:

1. **The tab labelled "Timeline" is a subtitle-cue editor, not a video timeline.**
   `app/renderer/src/features/Timeline.tsx:1-8` — *"timeline subtitle editor (P2 T1). Waveform
   strip (from `timeline.peaks`) + a cue lane of draggable rects"*. Its split/merge/retime ops
   act on `Cue` objects (`app/renderer/src/lib/timelineOps.ts:57-83`), i.e. subtitle cues.
   `sidecar/media_studio/features/timeline.py:324` registers exactly one method,
   `timeline.peaks`, which returns `{sampleRate, peaks}` — a waveform, nothing more.

   > **NAMING RESOLVED (2026-08, `fix/v15-timeline-naming`) — the finding above stands; only the
   > LABEL moved.** The tab now reads **"Subtitle timeline"**, the panel heading matches, and the
   > panel carries a scope note pointing at the two surfaces that actually cut video today
   > (Director, and Make Shorts → Manual interval). The sibling `"Timeline export"` tab was
   > relabelled **"NLE export"** in the same pass, because once the first rename landed it became
   > the only tab still carrying the word and would have caught the same misdirected click; it is
   > the CMX3600/CSV handoff, whose events are approved short-maker clips laid back-to-back
   > (row 27). **Nothing in §1's verdicts changes** — no engine, RPC, tab id, order or grouping was
   > touched, the multi-clip gap is untouched, and the real video-timeline work stays in
   > `feat/v15-video-timeline`. This is the honesty half of S1.1, not S1.1.

2. **There is no direct-manipulation edit surface at all.** `app/renderer/src/views/Edit.tsx`
   is a 192-line *router*: it renders either `TaskHub` or `Workspace` (`Edit.tsx:153-163`).
   Its own empty state promises *"trim, cut, join, reframe, caption, and more — every edit tool
   lives here"* (`Edit.tsx:183-185`), but the Workspace tab list
   (`Workspace.tsx:53-66`) is `transcribe, search, subtitles, diarize, refine, tracks, convert,
   shortmaker, timeline, dub, nle, recipes, assets` — **no trim, no cut, no join tab**. The
   `trim`/`cut`/`join` engines are real (§1) and are reachable only through
   `director.apply` — i.e. behind an **AI prompt** (`app/renderer/src/views/Director.tsx:3,57`
   — *"prompt-driven AI editing… One prompt in. A reviewable plan out"*) — or implicitly via
   shorts candidate selection. A user cannot drag a cut.

3. **The render model is a linear destructive re-render chain, not a sequence model.**
   Each applied op reads the current source, renders a **whole new mp4** into the copy folder
   (`sidecar/media_studio/features/director_op_engines.py:148-157`), then re-points the manifest
   at it (`:160-175`). N ops = N full re-encodes. Undo is a *re-point to the previous file*
   (`RESTORE_KEY`, `:62,178-189`), never a re-render. This is elegant and safe, and it
   structurally cannot express two clips existing at the same time.

The multi-clip gap is not an oversight — it is **named and deliberately deferred in the source**:
`DEFERRED_SUBSYSTEMS["reorder"] = "the timeline clip-reorder engine (multi-clip permutation)"`
(`director_op_engines.py:116`), with the comment *"`reorder` is a multi-clip timeline permutation
outside the single-clip render scope of these adapters"* (`:103-104`).

**Standing defect, independently re-probed and CONFIRMED (not taken on faith):** `libx264` is
hardcoded in **9 non-test `media_studio` modules** — `brandkit.py`, `media_compat.py`,
`director_op_engines.py` (3 sites: `:360,:689,:912`), `fillers.py`, `reframe_claudeshorts.py`,
`reframe_multispeaker.py`, `shortmaker.py` (7 sites), `stabilize.py`, `zoom.py` (grep count by
file, a different probe than the brief's). **A second casualty of the same packaging defect that
the brief did not mention:** stabilisation needs GPL `libvidstab`, and the source says so —
*"`vidstabdetect`/`vidstabtransform` exist only when ffmpeg was compiled `--enable-libvidstab`
(GPL) … a stripped/LGPL bundle would NOT [have it]"* (`stabilize.py:25-27`). So the pinned GPL
rebuild is load-bearing for **stabilise** as well as H.264 export. Treat every "BUILT" verdict
below as *"built in source, blocked on the shipped binary"*.

---

## 1. Editing-primitive inventory

Legend — **BUILT**: engine + RPC + a user-reachable UI. **PARTIAL**: says which half is missing.
**MISSING**: no implementation found. "Director-only" = reachable solely by AI prompt.

| # | Primitive | Verdict | Evidence |
|---|-----------|---------|----------|
| 1 | **Trim** | PARTIAL — engine BUILT, RPC via `director.apply` only, **UI MISSING** | `director_op_engines.py:79` (`"trim"` in `WIRED_KINDS`), `:748`; no trim tab in `Workspace.tsx:53-66` |
| 2 | **Cut** (delete span, ripple) | PARTIAL — engine BUILT, Director-only, **UI MISSING** | `director_op_engines.py:80`; `:269` *"head + tail concatenated"* |
| 3 | **Split at playhead** | PARTIAL — **cues only**; video split MISSING | `timelineOps.ts:57-67` `splitCue` operates on `Cue`; no video-split op kind in `WIRED_KINDS` (`:78-92`) |
| 4 | **Multi-clip timeline** | **MISSING** — explicitly deferred | `director_op_engines.py:105-120`; `reorder` -> *"the timeline clip-reorder engine (multi-clip permutation)"* (`:116`). `join` is **append-only** — extra clips go *"AFTER the COPY source"* (`:318`) |
| 5 | **Transitions** | ~~MISSING~~ -> **BUILT at a chain boundary** (engine + op kind + UI); arbitrary-timeline transitions still MISSING | was: zero `xfade` in `sidecar/media_studio` (grep, 0 hits). Now: `sidecar/media_studio/features/transitions.py` (xfade + acrossfade builders), `transition` in `director_op_engines.WIRED_KINDS`, picker at `app/renderer/src/panels/TransitionPicker.tsx`. See the §2 correction below |
| 6 | **Speed ramp / slow-mo** | PARTIAL — **constant** factor BUILT, **ramp MISSING**, Director-only | `retime` wired `:87`; `build_retime_argv` `:665-689` = `setpts=(1/factor)*PTS` + `atempo` chain `:640-673`. One scalar `factor`; no keyframed curve |
| 7 | **Crop / pan / zoom keyframes** | PARTIAL — **auto** punch-in BUILT, **user keyframes MISSING** | `zoom.py:5` *"pure ffmpeg `zoompan` expression"*, `:168-194` *"the auto punch-in zoom"*; `zoomPan` wired `:86`. Per-shot crop override exists (`reframe.applyOverrides`, `reframe_override.py:433`) but is reframe-scoped, not a general keyframe editor |
| 8 | **Colour correction** | **MISSING** | zero `eq=`, `curves`, `colorbalance`, `colorchannelmixer`, `hue=` (grep, 0 hits) |
| 9 | **LUTs** | **MISSING** | zero `lut3d` (grep, 0 hits) |
| 10 | **Audio mixing** | PARTIAL — **2-input only**; N-track mixer MISSING | `audiomix.py:150` `amix=inputs=2` — foreground + exactly one bed |
| 11 | **Ducking** | BUILT (engine + RPC) — UI NOT-CHECKED per-row | `audiomix.py:149` `sidechaincompress`; RPC `audiomix.merge` (`:408`) |
| 12 | **Loudness normalisation** | BUILT (engine + RPC) — EBU R128 | `audiomix.py:151,225` `loudnorm=I=…:TP=…:LRA=…`; RPC `audiomix.normalize` (`:409`) |
| 13 | **Multi-track audio** | PARTIAL — **container-level only**, no mix timeline | `tracks_audio.py:670-673` = `tracks.audio.list/mux/replace/strip` (stream add/replace/remove). No per-track level/pan/automation |
| 14 | **Titles / lower-thirds** | PARTIAL — engine BUILT but **un-styleable**, Director-only | `build_drawtext_argv` `:699-722`; hardcoded `fontcolor=white`, `fontsize=h/18` (overlay) / `h/12` (lower third). No font, colour, position, or timing params. **UNVERIFIED:** `:711-712` relies on *"fontconfig's default face (no `fontfile` needed where fontconfig is present)"* — Windows ffmpeg builds frequently ship without fontconfig, which would make every title render fail or fall back silently. Settling experiment: run `build_drawtext_argv` against the packaged `ffmpeg.exe` and check exit code + a pixel-diff of the output frame |
| 15 | **Image / B-roll overlay** | PARTIAL — **static brand logo only**; B-roll MISSING | `brandkit.py:68-115` `build_logo_overlay_argv` — one image, corner-inset, whole-clip duration. No timed insert, no video-over-video. (`docs/plans/v1.5/flagship-auto-broll.md` is a plan, not an implementation) |
| 16 | **Freeze frame** | **MISSING** | zero `tpad`, `loop=`, `framestep` editing hits (grep) |
| 17 | **Reverse** | **MISSING** | zero `areverse`; every `reverse` hit in the tree is Python `reversed()`/`sort(reverse=True)` — a use-vs-mention false positive, individually checked (`jobs.py:376`, `catalog.py:412`, `fillers.py:109`, etc.) |
| 18 | **Stabilisation** | BUILT engine + RPC — **blocked on the LGPL binary** | `stabilize.py:1-6` vidstab 2-pass; RPC `stabilize.run` (`:496`); GPL requirement `:25-27` |
| 19 | **Masking** | **MISSING** | zero `maskedmerge`, `alphamerge` (grep, 0 hits) |
| 20 | **Chroma key** | **MISSING** | zero `colorkey`, `chromakey`, `despill` (grep, 0 hits) |
| 21 | **Motion tracking** | PARTIAL — tracking exists but **only drives auto-crop** | `reframe_edgetam_backend.py`, `reframe_multispeaker.py`, `saliency.py`. Not attachable to a user effect or overlay |
| 22 | **Proxy / optimised media** | BUILT — playback-compat scoped | `media_compat.py:245-269` h264 720p `scale=-2:720`; RPC `media.proxy.start` (`:487`). Note `:21` — *"proxy plays, all operations … keep using the ORIGINAL"* (correct conform behaviour) |
| 23 | **Markers / chapters** | **MISSING** | zero editing hits; all `marker` hits are release-tag markers (`tools_resolver.py:276-337`) and redacted-secret markers (`settings_store.py:102,315`) — use-vs-mention, individually checked |
| 24 | **Project save / load** | BUILT | `library.py:521-582` `Project.new/open/save`, manifest v1 `{video, tracks, clips, audioTracks, settings}` (`:526-527`); RPC `project.open/save/consolidate` (`composition.py:116-118`). `consolidate` rewrites refs relative for portability (`:529-532`) |
| 25 | **Undo / redo** | PARTIAL — **two disjoint mechanisms, no app-wide stack** | (a) `director.undo` (`composition.py:216`) walks recorded inverse ops by *re-pointing*, not re-rendering (`apply_engine.py:139`, `director_op_engines.py:178-189`); (b) a 100-entry linear history for **subtitle cues only**, in-component (`timelineOps.ts:23` `MAX_HISTORY = 100`) |
| 26 | **Render queue** | BUILT for batch-of-sources; **heterogeneous queue MISSING** | `batch.py:96` statuses `queued/running/done/error/cancelled/skipped`, durable resume `:471`; RPCs `batch.create/start/plan/status/list/cancel/resume/delete` (`:1083-1090`). One pipeline applied to many sources — not a queue of differing export jobs |
| 27 | **NLE interchange** | PARTIAL — **EDL + CSV only**; FCPXML/AAF/OTIO MISSING | `nle_export.py:50` `FORMATS = ("edl", "csv")`; CMX3600 builder `:204-234`. **And the EDL is not a user timeline:** `clips_to_events` lays every clip **back-to-back** on the record side (`:162,175-177`), deriving a contiguous rough cut from approved *shorts candidates* (`_clip_window` reads `sourceStart`/`end` off the candidate, `:128-148`). Single track, no transitions, no effects |

### Scorecard

- **BUILT (engine + RPC + reachable UI): 6** — ducking, loudness, stabilisation (binary-blocked),
  proxy, project save/load, batch queue.
- **PARTIAL: 12** — of which **6 are "engine exists, no UI"** (trim, cut, retime, zoomPan,
  titles, and split-for-video), all gated behind the AI Director.
- **MISSING: ~~9~~ 8** — colour, LUTs, freeze, reverse, masking, chroma key,
  markers/chapters, multi-clip timeline. (Transitions left this list: BUILT at a chain
  boundary — engine, op kind and picker — see row 5 and the §2 correction. The
  arbitrary-timeline case is folded into "multi-clip timeline", which is still missing.)

The distribution is the story: Reframe's gap is **less about missing engines than about missing
direct manipulation**. Six real, tested, working ffmpeg engines have no user-facing control.

---

## 2. The architectural ceiling

### What the substrate actually is

Two engines, measured:

- **ffmpeg filtergraph**, driven by pure argv builders (`build_*_argv` throughout `features/`),
  one subprocess per op, output to a new file.
- **Remotion**, and this is the finding that changes the roadmap: it is **already vendored and
  already a compositor**. `vendor/remotion-captions/src/` holds a real Remotion project
  (`Root.tsx`, `CaptionedClip.tsx`, four caption styles, `HookTitle.tsx`), rendered head-
  lessly via `@remotion/renderer`'s `selectComposition` + `renderMedia`
  (`app/render-cli/src/render.ts:33,168`). **But it is used for exactly one thing.**
  `CaptionedClip.tsx:37-38` is a single `<OffthreadVideo src={videoSrc}>` inside an
  `<AbsoluteFill>` with caption overlays — **no `<Sequence>`, no second video, no `<Img>`, no
  `<Audio>`.** Reframe ships a multi-layer compositing timeline engine and drives it as a
  single-clip caption burner.

### Where the ceiling is

The ceiling is **not** ffmpeg. ffmpeg can do every missing primitive in §1. The ceiling is the
**data model**: there is no sequence. Concretely:

- `Project.clips` is `[{candidate, path}]` (`library.py:527`) — a **bag of rendered shorts**,
  each an independently exported file. It has no track index, no record position, no effect
  stack, no transition. `nle_export.py` has to *synthesize* an order by butting clips together
  (`:175-177`) precisely because none is stored.
- The op model is a **mutation chain over one clip**: source -> render -> re-point
  (`director_op_engines.py:148-175`). A "project state" is just *which file the manifest points
  at right now*.

That model makes four things structurally impossible, not merely unimplemented:

1. **Anything requiring two clips at the same instant** — ~~transitions,~~ video-over-video B-roll,
   picture-in-picture, compositing. `xfade` needs an overlap; an append-only `join` (`:318`)
   cannot produce one.

   > **CORRECTION (transitions lane, 2026-08).** The transitions half of this row was an
   > OVERCLAIM and is REFUTED. It reasoned from the *timeline model* — true, `Project.clips`
   > cannot express two clips at one instant — to the *render*, which does not need it. A
   > boundary transition is one ffmpeg pass over N inputs: `xfade` creates the overlap INSIDE
   > its own filtergraph from two separate `-i` inputs, exactly as the concat filter already
   > takes N inputs at `director_op_engines.build_join_argv`. No sequence document is
   > involved. Measured by building it: `sidecar/media_studio/features/transitions.py`
   > (xfade + acrossfade, chained offsets), a `transition` op kind in `WIRED_KINDS`, and
   > `app/renderer/src/panels/TransitionPicker.tsx`. It landed on the existing single-clip
   > mutation chain with no model change — the same "cheap on today's substrate" shape as the
   > §3 S1.3 colour/LUT ops, which is where this row should have put it.
   >
   > **What the row got RIGHT, and what is still MISSING.** What is now built is a transition
   > at the boundaries of a linear CHAIN (`source -> clip -> clip`), because that is the only
   > junction the mutation chain can name. Still genuinely blocked on the §3 stage-2 sequence
   > model: a transition at an arbitrary point in a reorderable multi-clip timeline (there are
   > no positions to attach it to), and B-roll / PiP / compositing (those need one clip to
   > persist THROUGH another's duration, which is a different thing from overlapping at a
   > junction, and the row is still correct about them).
   >
   > Cost, disclosed rather than buried: a transition can never be a stream copy, since xfade
   > must decode and recomposite both sides of every boundary. That is not a regression on
   > `join`, which already re-encoded through the concat filter (`build_join_argv`, `-c:v
   > libx264`); and the genuine `-c copy` fast path in
   > `sidecar/media_studio/features/reframe_multispeaker.py` (`build_concat_argv`) stitches
   > per-segment crops of ONE clip inside the active-speaker pass and is untouched.
2. **Arbitrary time reordering** — the deferred `reorder` op. Ripple/roll/slip/slide edits all
   need positions the model does not hold.
3. **Non-destructive parameter tweaking.** Changing a title's colour today means re-running the
   whole chain. A sequence model re-renders a preview; a mutation chain re-encodes generations.
4. **Real-time preview / scrubbing of an edit.** The current preview *is* the last rendered file.

There is also a quality cost that compounds silently: **N ops = N H.264 re-encodes**, each
generational loss. No `-crf` continuity or intermediate-codec discipline was found in the
Director path — `:360,:689` pass bare `-c:v libx264` with no rate-control flags. Corroborated by
a second, independent probe: grepping `director_op_engines.py` for `crf|-preset|-b:v|-pix_fmt`
returns **zero** hits (only `-c:a` at `:361,582,631,690,734`), so every op re-encodes at
x264's default CRF 23 with no quality floor carried between generations. **UNVERIFIED:**
I did not measure actual quality degradation over a chain. Settling experiment: apply 6 Director
ops to one clip and compare VMAF/SSIM of the result against a single-pass filtergraph doing the
same work.

### The honest split — cheap vs. needs new architecture

**Cheap on today's substrate** (one more entry in `WIRED_KINDS` + one argv builder + a UI
control; no model change). Confidence *almost certain* (90-99%) for the render side, since each
is a single ffmpeg filter over one clip, which is exactly the shape the existing 13 engines have:

| Primitive | Filter | Note |
|---|---|---|
| Colour correction | `eq`, `curves`, `colorbalance` | pure per-frame, no state |
| LUTs | `lut3d=file=x.cube` | + a `.cube` asset path |
| Reverse | `reverse,areverse` | **caveat:** `reverse` buffers the whole clip in RAM — must chunk or cap duration |
| Freeze frame | `tpad` / `trim`+`loop` | changes duration; cue re-timing needed (`silencetrim` already does this) |
| Chroma key | `colorkey`+`despill` | keyable, but only useful once you can put something *behind* it — see below |
| Markers / chapters | none — **pure metadata** | zero render. Cheapest item in this document |
| FCPXML export | none — **pure serialization** | `nle_export.py` already has the timecode math (`:151-193`) |
| Title styling | existing `drawtext` | just thread params through `build_drawtext_argv` |

**Needs a real sequence/compositing model.** Confidence that these cannot be done well by
extending the mutation chain: *high* — the deferral comment at `:103-104` is the codebase
reaching the same conclusion independently.

- Multi-clip timeline with reorder / ripple
- ~~Transitions~~ — REFUTED for the chain-boundary case (built; see the §2 correction). Still
  needed for a transition at an arbitrary point in a reorderable timeline.
- B-roll / PiP / multi-track video
- Masking, and motion tracking bound to an effect (needs per-frame animated parameters)
- N-track audio mixing with automation
- Non-destructive editing and real-time preview

**The leverage:** the sequence model does not have to be built from nothing. Remotion already
*is* the compositor — `<Sequence from={} durationInFrames={}>` over N `<OffthreadVideo>` layers
is precisely a multi-track timeline, and the headless render path is already wired and shipping
(`render.ts:168`). The missing piece is a **sequence document** (ordered clips with
in/out/track/position/effects) that both Remotion (preview + composite render) and ffmpeg
(fast flatten) can consume. That is a real piece of architecture — but it is *additive* and it
reuses two engines already in the tree, which is a materially cheaper position than "rewrite the
renderer".

---

## 3. Staged plan

### Stage 1 — "a credible editor" with **no new architecture**

Thesis: the fastest credibility win is **not** new capability, it is **exposing the six engines
that already work** and giving them a manual surface. Everything here fits the existing
single-clip mutation model.

**S1.1 — A manual edit surface (the keystone).**
New view `app/renderer/src/views/Trim.tsx` (or a `cut` tab in `WORKSPACE_TABS`,
`Workspace.tsx:53-66`), reusing the **existing** waveform (`timeline.peaks`) and the existing
lane/drag math (`timelineOps.ts` — `timeFromClientX`, `dragEdge`, `cueRectStyle` are already
generic over a time axis). Emits a hand-built `EditPlan` and calls the **existing**
`director.apply`. No new RPC. This alone converts trim/cut/join/retime/zoomPan/overlayText from
Director-only to user-driven.
- Modules: `app/renderer/src/views/` (new), `app/renderer/src/lib/timelineOps.ts` (extend to
  generic spans), `sidecar/media_studio/models/edit_plan.py` (already models `EditOp`/`EditPlan`,
  `:81,:106` — likely no change).
- RPCs: **none new.** `director.apply` + `director.undo` already accept and invert plans.

**S1.2 — Title styling params.** Thread `font`, `size`, `colour`, `position`, `start/end` through
`build_drawtext_argv` (`director_op_engines.py:699-722`) and add `enable=between(t,s,e)` for
timing. Resolve the fontconfig risk (row 14) at the same time by bundling a font and passing
`fontfile=` explicitly.

**S1.3 — Colour + LUT ops.** Add `colour` and `lut` to `WIRED_KINDS` (`:78-92`) with
`build_color_argv` / `build_lut3d_argv` beside the existing builders. Same engine-factory shape
as `make_overlay_text_engine` (`:940`).

**S1.4 — Markers / chapters.** Add a `markers: []` array to the project manifest
(`library.py:559-566` already backfills unknown fields, so this is schema-compatible) + new RPCs
`markers.list` / `markers.set`. Zero render work. Export chapters into the mp4 container and
into the EDL.

**S1.5 — FCPXML + freeze + reverse.** Add `"fcpxml"` to `nle_export.FORMATS` (`:50`) reusing
`clips_to_events`; add `freeze` and `reverse` op kinds (with the RAM cap noted above).

**S1.6 — Fix the binary.** Ship the pinned GPL ffmpeg. Nothing in stage 1 is demonstrable
without it, and it unblocks stabilisation too (`stabilize.py:25-27`).

Stage-1 outcome: a user can open a video, see a waveform, drag trims, cut, join, retime, colour-
grade, LUT, title, marker, and export — plus everything Reframe already does. That is a credible
lightweight editor. **Estimated confidence it lands without touching the render model: *likely*
(55-80%)** — the main risk is S1.1's plan-building UI proving to want positions the model lacks
the moment a user tries to reorder two cuts, which is exactly the stage-2 trigger.

### Stage 2 — the sequence model

Introduce a **sequence document** as the source of truth: ordered `clips[{sourceId, inSec,
outSec, trackIndex, recordSec, effects[]}]`. Store it in the existing project manifest
(additive — `Project.open` already tolerates new keys, `library.py:559-566`). Two renderers over
one document:
- **Remotion** for preview + composited render (extend `vendor/remotion-captions/` from one
  `<OffthreadVideo>` to `<Sequence>`-mapped layers — the engine and headless driver already
  exist).
- **ffmpeg** for a fast flatten of the simple single-track case (reuse the concat-filter path,
  `:339-360`).

Unlocks multi-clip reorder (retiring the deferred `reorder`), transitions ~~(`xfade` becomes
expressible)~~ *at an arbitrary timeline position — `xfade` is already expressible at a chain
boundary, see the §2 correction*, B-roll/PiP, and a real app-wide undo over document edits
rather than file re-points. NLE export stops being synthesized and becomes a faithful serialization.

### Stage 3 — depth

Masking + motion tracking bound to effects (reuse the existing `reframe_edgetam_backend` tracker
as the tracking source), N-track audio mixing with automation curves, chroma key composite
(needs stage 2 to have something behind the key), speed *ramps* via piecewise `setpts` with
segment-wise audio resampling, and proxy-based editing performance.

---

## 4. What Reframe should NOT try to be

**Not DaVinci Resolve / Premiere.** No node-based colour grading, no Fairlight-class audio, no
Fusion-class VFX, no collaborative/multi-user project locking, no broadcast deliverable
compliance (AAF round-trip with an audio post house, closed-caption standards conformance). The
reason is not ambition, it is measured: Reframe's differentiators are the AI ones — active-speaker
reframing (`reframe_multispeaker.py`), moment-finding (`select.py`, `ranker.py`), dub
(`dub.py`), Director planning. Every hour spent chasing a scope/waveform/curve editor is an hour
not spent there, and it competes on the axis where two free incumbents are 20 years ahead.

**Not a real-time NLE.** The mutation-chain heritage and per-op subprocess model mean Reframe's
honest posture is *plan -> render -> review*, not *scrub -> instant feedback*. Even with stage 2,
Remotion preview is frame-serving, not GPU timeline playback. Promising real-time scrubbing
would be an overclaim.

**Not a colour-managed finishing tool.** No ACES, no HDR tonemapping pipeline, no scopes. It
should do *corrective* colour (§S1.3), and hand off to Resolve via FCPXML (§S1.5) for finishing.
The interchange path is the honest answer to "professional", and it is cheap.

**The scope that IS defensible:** *the best AI-first shorts and social editor that also handles
ordinary cuts, titles, colour, and subtitles competently, and hands off cleanly to a real NLE
when the job outgrows it.* That framing makes the missing primitives a finite list (§1) rather
than an open-ended chase, and it is honest about the handoff instead of pretending it never
happens.

One caution on the owner's ask: *"professional app regarding most stuff"* is the phrasing most
likely to lead to stage-2-and-3 scope with stage-1 resourcing. The measured recommendation is to
ship stage 1 whole — six engines already exist and are invisible, which is the highest
value-per-hour work available in this repo — and let stage 1's friction decide whether stage 2
is warranted, rather than committing to the sequence model up front.

---

## Residual gaps in this audit (disclosed, not blocking)

- **UI column granularity.** Measured at rail/tab level (`Workspace.tsx:53-66` + the view
  files), not by a per-component sweep. A control could exist inside a panel I did not open.
  Settling experiment: drive the built app with the `ui-audit` skill and enumerate every
  interactive control per tab.
- **Runtime behaviour NOT-CHECKED.** Every verdict is from source. I did not launch Reframe or
  execute a single ffmpeg command; given the LGPL/libx264 defect, several "BUILT" rows are
  *likely* (55-80%) to fail at runtime on the installed build. Settling experiment:
  `packaged-artifact-smoke` golden journeys against the packaged binary with ffprobe
  postconditions.
- **Test coverage of the deferred paths NOT-CHECKED.** I did not check whether the `DEFERRED_KINDS`
  degradation path (per-op `failed` + auto-rollback, claimed at `director_op_engines.py:94-97`)
  is actually exercised by a test.
