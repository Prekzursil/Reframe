# Prompt-Driven AI Video Editing ("Director") — Feature Spec

**Status:** CAPTURED for the roadmap (LATER phase) — will go through the full metaswarm gates (design → design-review → plan → plan-review) before build.
**Date:** 2026-06-16
**Requested by:** user (2026-06-16): a new top-level functionality alongside Shorts/captions/etc.

---

## 1. Vision (user's words, paraphrased)

A **Descript-type** ability to **edit a video by prompting the AI**, then **confirm + evaluate** the proposed edits before they're applied. The user describes the desired outcome in natural language; the AI plans a concrete, reviewable edit sequence; the user approves (or iterates); the app renders it. This is an *editing agent* over the existing NLE engine — not another fixed pipeline like Shorts.

### Motivating examples (from the user)
1. **Smooth a chaotic scroll** — a screen recording where a list is scrolled erratically → the AI re-times/re-paces it so it reads as a smooth, easy-to-follow glide.
2. **Q&A showcase** — a recording of the user answering ~50 questions → the AI stitches it into a seamless flow from one question to the next, with **the answer/question text already written on screen**, presented as a polished showcase of the answers.

## 2. What it is

A **prompt → plan → preview → confirm → evaluate** loop:
1. **Prompt:** user states the goal ("make the scrolling smooth", "turn this into a Q&A showcase with on-screen text").
2. **Understand:** the AI analyzes the source (transcript via ASR, scene/motion via the Phase-8 signals, on-screen content via vision) to build a structured understanding of the timeline.
3. **Plan:** the LLM produces a **concrete, typed edit plan** — an ordered list of operations expressed in terms the existing engine already supports (cut, trim, re-time/speed-ramp, reorder, transition, overlay text/lower-third, zoom/pan/reframe, silence-removal, b-roll/caption insert).
4. **Preview + Confirm:** the plan is shown as a human-reviewable diff/storyboard over the timeline; the user approves, edits individual steps, or re-prompts. **Nothing is applied without confirmation** (the user's "confirming" requirement).
5. **Apply + Evaluate:** the engine renders the approved plan; an **evaluation pass** scores the result against the prompt (did it actually get smoother / seamless?) and surfaces a before/after so the user can accept or iterate (the user's "evaluation" requirement).

## 3. How it builds on what already exists (reuse, not net-new pipelines)

- **Transcript / alignment:** `features/transcribe.py` + `ctc_align` (word timing) — the spine for content-aware cuts and on-screen text.
- **Moment/structure signals (Phase 8):** `scorer.py` unified tri-modal scoring, `motion`/`saliency`/`scene_transnet`/`audio_saliency` — to detect scroll motion, scene boundaries, dead air, question/answer segments.
- **LLM seam:** `models/provider.py` (and the upcoming **Provider Hub** with cloud offload + rotation) — to turn the prompt + timeline understanding into the typed edit plan and to write on-screen text.
- **Vision seam:** `vlm_backbone` / `smolvlm2` (+ planned cloud multimodal) — to read on-screen content (lists, question text) for the showcase/scroll cases.
- **NLE / render engine:** `features/timeline.py`, `nle_export`, `caption_remotion` (Remotion captions/overlays), reframe — the operations the plan compiles down to.
- **The Director is an ORCHESTRATOR** over these; the edit "plan" is a typed, validated document (like the existing select/shorts results), so it's testable to 100% without rendering.

## 4. Key design principles (to resolve at the gate)

- **Typed, reversible edit plan** — every AI proposal is a structured op list applied to a copy of the timeline; original is never destroyed; full undo.
- **Confirm-before-apply** — mandatory human gate between plan and render (matches the user's "confirming").
- **Self-evaluation loop** — an automatic before/after scoring against the stated goal (matches "evaluation"); the user can iterate the prompt.
- **Determinism/testability** — the planner is a pure function (prompt + timeline-understanding → plan) behind the provider seam; tests inject fake providers + fixtures; 100% line+branch (standing policy).
- **Cost-awareness** — long sources (e.g. 50 Q&A) mean many LLM/vision calls → leans on the Provider Hub's rotation + usage budgeting so a big edit job doesn't stall or blow a free-tier cap.

## 5. Open questions (for the design gate)

- Q1 Plan representation: extend the existing timeline op schema, or a new "edit-plan" DSL?
- Q2 Scope of v1 op set: which operations ship first (cut/trim/re-time/text-overlay are the examples' core) vs later (b-roll, multicam, music)?
- Q3 Evaluation metric: how is "smoother" / "seamless" scored objectively (motion-jerk reduction, cut-rhythm, silence ratio) vs an LLM judge?
- Q4 Preview UX: storyboard diff vs inline timeline annotations vs side-by-side player.
- Q5 Dependency: does this require the Provider Hub (cloud offload) first, given the call volume on long sources? (Likely yes for the 50-Q&A case on weak hardware.)

## 6. Roadmap placement

- **Depends on:** Phase 8 moment-finding (done), the Provider Hub (LLM+vision offload + rotation — in design), and the NLE/caption engine (exists).
- **Sequencing:** after the Provider Hub lands (it supplies the cost-resilient AI calls this feature needs at scale). Will get its own design doc → Design Review Gate (5) → plan → Plan Review Gate (3) → execution-method choice → build, per project workflow.
- **Working title:** "Director" (prompt-driven editing). Final name TBD.
