# Reframe v1.5 — competitor feature research (redo of the bugged workflow agent)

> **Status:** DRAFT

Base: ~16 web searches (WebSearch/Exa/Tavily) across OpusClip, Submagic, Descript, CapCut, Kapwing, Veed, Vizard, Klap, Riverside, HeyGen/Captions + local-first rivals (AetherCut, Diffusion Studio, Bitcut, Reelify). Effort grades calibrated vs what media_studio already ships.

## Top 5 to steal for v1.5
1. **Active-speaker detection + multi-speaker split/switch layouts** (L) — dynamic crop that cuts to whoever's talking, or 9:16 host/guest split. Highest-value reframe extension for podcast/interview clips (the market's dominant segment). Local-feasible: free NVIDIA Active-Speaker-Detection NIM (~5-10ms/frame RTX3080), Apple streaming ASD. Extends Reframe's core subject-tracking.
2. **Animated caption template GALLERY + auto-emphasis + auto-emoji** (M / S-M) — expand Reframe's existing karaoke preset (caption_karaoke.py) into a selectable gallery (Submagic has 35+) + brand kit; LLM tags power-words for color/scale-pop + context emoji. Captions are the #1 loved feature market-wide; highest virality-per-effort.
3. **Auto clip-finding → ranked candidate shorts + honest highlight score** (L + M) — long video → 10-20 pre-cut ranked segments (OpusClip ClipAnything/Vizard). Converts Reframe from "cropper" to "repurposing tool" (the category people buy). Local LLM scores transcript segments. CRITICAL: users distrust OpusClip's virality score (decorative, non-deterministic) — ship as an HONEST filter with visible reasons, not a fake crystal ball.
4. **Agentic AI Director expansion** (M) — one prompt → sequenced multi-step edit ("polish this for TikTok" = reframe+captions+zoom+trim+B-roll). Counters Descript Underlord; matches local rival AetherCut ("AI Director by Claude"). Builds on Reframe's existing reviewable/reversible Director.
5. **Auto-zoom / punch-in synced to emphasis** (S-M) — keyframed scale on the existing crop path, timed off caption cue timestamps. Kills "static talking head"; very high engagement-per-effort.

## Other ranked adoptable features
6. AI B-roll insertion from the user's OWN library (semantic match, local, on-brand) — M. Local edge vs generic cloud stock.
7. Filler-word/bad-take removal (transcript-driven cut+re-time, reuses silencetrim.py) — M.
8. AI dubbing: translated TTS voiceover (+ optional local lip-sync Wav2Lip/LatentSync on WSL2 GPU) — L. Reframe already translates audio; TTS is next step. Biggest reach multiplier.
9. Batch workflow + brand templates + aspect-ratio matrix (9:16/4:5/1:1/16:9 in one pass) — M. The "scale" story agencies pay for; local orchestration, no new ML.
10. Hook-title/hook-card LLM generation (Reframe already RENDERS hook cards in caption.py; add LLM text gen) — S.
11. Text-based/transcript editing (delete word → cut video; Reframe already owns word-aligned transcript) — L.
12. NLE handoff: FCPXML/EDL/Premiere-DaVinci export (privacy/pro crowd finishes locally) — M.
13. Caption-accuracy escape hatches: custom .SRT import + custom dictionary (fixes #1 caption complaint: proper nouns/jargon/accents) — S.
14/15. (Lower priority) social scheduler/publish (needs cloud/OAuth → at most "platform-ready export presets"); eye-contact gaze correction (niche L).

## Where Reframe ALREADY WINS (local/offline/privacy) — the marketed category
- **Privacy = decisive edge.** CapCut's Jun-2025 ToS grants ByteDance perpetual/irrevocable/sublicensable license to EVERYTHING uploaded incl. private drafts, deleted content, NDA client work; CapCut US-banned Jan-2025 (PAFACA) + live class-action. Descript/Kapwing/Clipchamp all upload to cloud. Reframe = 100% local, no perpetual license, no training on your footage, safe for NDA/HIPAA/unreleased. AetherCut/Bitcut/Reelify sell exactly this.
- No upload wait / render queue / outage exposure (cloud = 15-45min + early-2026 multi-hour outages; local = 2-10min, scales with your GPU).
- No watermark / no clip expiry / no metered credits (OpusClip free = watermark + 3-day expiry + credit-metering; CapCut paywalled captions at $20.84/mo).
- Own-media B-roll + full offline operation + reversible/inspectable AI Director (no prompts+footage to a vendor).
- **Net: Reframe doesn't need to WIN on privacy — it needs to CLOSE the feature gap (captions polish, active-speaker, clip-finding, B-roll, zoom) so privacy-conscious creators stop sacrificing capability to stay local.**

## Confidence + gaps
- HIGH: OpusClip virality-score+ClipAnything+active-speaker+B-roll (score distrusted); Submagic best captions+MagicZoom+B-roll+hook titles+brand kit; Descript Underlord agentic+text-editing; CapCut privacy/ToS/ban; real local-first rival wave (AetherCut "AI Director by Claude").
- MEDIUM: vendor caption-accuracy % (98-99% marketing vs ~95% real w/ proper-noun errors); local feasibility of active-speaker/lip-sync on Reframe's WSL2 GPU inferred from model specs, not benchmarked; effort grades from visible skills not a code audit.
- GAPS: did NOT read the repo (web-only) → some features may already be partially built (hook cards exist; auto-zoom/emoji status unknown) → the code-audit agents de-dup this; virality-score worth-building is contested (A/B as honest filter); no primary Reddit threads (complaint synthesis is second-hand via review aggregators).
