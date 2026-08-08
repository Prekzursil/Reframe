# Reframe — live visual audit (v1.5 input)

> **Status:** ARCHIVED 2026-08-08

Read from the committed Playwright win32 baselines (the driven-app captures): Library,
Create/Shorts, Edit/workspace, Director. These are visual-truth findings to fuse into the
v1.5 roadmap.

## P0 — Information architecture is the #1 problem
- **Editor tab overload:** the Edit surface has **16+ horizontal top-level tabs** (Speech&Text,
  Transcribe, Search, Subtitles, Diarize, Refine, Frame&Cut, Short-Maker, Timeline, Audio, Dub,
  Deliver, Convert, Timeline-Export, Recipes, Assets…). Severe cognitive overload; loosely grouped
  but a wall of tabs. Needs a real IA: group into ~4-6 phases (e.g. Transcribe → Edit → Reframe →
  Caption → Export) with progressive disclosure. **Biggest single UX lever for v1.5.**
- **Nav + chrome inconsistency across screens:** Library/Edit show nav "Make Shorts / Edit" with
  "AI MODEL: Local/Cloud" + "WHERE JOBS RUN: Local/Cloud/Auto" toggles and brand "REFRAME";
  Create/Director/Repurpose show nav "Create / Repurpose" with a single "QUALITY: Local/Cloud"
  toggle and brand "REFRAME — MEDIA STUDIO". Same app, two different navbars/top-bars/brandings.
  Unify to ONE nav + ONE top-bar model + ONE brand string.

## P1 — Library foregrounds plumbing over content
- The Library screen leads with a dense two-column **"READY ON THIS COMPUTER"** model-readiness
  list (Instant numeric, Multimodal, Video-LLM re-rank, AI: editPlan, Reframe tracking/saliency,
  Scene-cut…) that dominates the viewport; the user's actual **video** is a small card at bottom-
  left with lots of dead space to its right. Invert it: **content first** (video grid), readiness
  demoted to a collapsible "Capabilities" panel or a per-action just-in-time "needs download" nudge.
- **Jargon labels:** "Instant numeric (no downloads)", "Multimodal (visual + audio + transcript)",
  "Video-LLM re-rank (heavy, opt-in)", "AI: editPlan" are internal/engineer language. Rewrite in
  user terms (what it *does*, not how it's built).

## P1 — Sparse content under dense chrome
- Edit (Subtitles tab = one "Generate subtitles" button) and Director (a form top-left) leave the
  bottom ~60% of the viewport empty. Poor content-to-chrome ratio; layouts read unbalanced.
  Center/rebalance, add context (preview, recent results, tips).

## P2 / cosmetic
- **Mojibake `�`** on the two Reframe rows in the Library baseline ("Reframe � vertical subject
  tracking" / "Reframe � saliency") — the #265 issue; the baseline predates the hyphen fix (#278).
  Regenerate the win32 baselines after #278 to clear it. (Confirms per-context font: the top-bar
  em-dash "REFRAME — MEDIA STUDIO" renders fine.)
- Magenta flat placeholder for the video preview (test fixture) — real app needs a proper
  poster/loading treatment, not a raw fill.
- 16:9 preview dominates a tool whose *output* is 9:16 — consider emphasizing the vertical target.

## What's GOOD (keep / build on)
- **Director** is a highlight: clean natural-language editing prompt + excellent trust microcopy
  ("The Director plans a reviewable, reversible edit — nothing is applied until you confirm").
  This is a differentiator — make it more central in v1.5.
- **Create/Shorts empty state** is well-done: icon + heading ("No shorts yet") + clear CTA copy.
- Status colors (green "Ready" / amber "Needs download") read clearly; dark theme + amber accent
  is a coherent base to refine (not replace).

## Design-direction seeds (for the figma/artifact pass)
- Keep dark-first + amber accent, but tighten the type scale + spacing rhythm (spacing reads ad-hoc).
- Move to a content-first Library (video grid), a phase-based editor IA, one unified top-bar.
- Lean into "AI Director / reviewable-reversible edits" as the brand's signature interaction.
