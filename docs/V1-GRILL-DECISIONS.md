# Reframe V1 — GRILL DECISION QUEUE

> Audit-trail synthesis of the 6 grill-lens reports (ux-simplicity · model-device-tiering ·
> poly-processing · reliability-no-silent-fallback · packaging-provisioning-wsl · competitive-redteam).
> Deduped across lenses. Each decision carries a recommended answer + one-line trade-off.
> This is the working queue for the live grill — walk it one item at a time.
>
> Date: 2026-06-27 · Status: DRAFT FOR GRILL · Decision count: **24** (F-1, F-2 + G-1..G-22)

---

## (a) FOUNDATION FRAMING QUESTIONS

These two reframe everything below. Answer them first; several G-decisions collapse depending on the answer.

### F-1 — Audience + ambition
**Q (verbatim):** "Who is the primary V1 user — a novice creator who wants *paste a video → get shorts* with near-zero configuration — or a power user who wants the full local media studio? And how ambitious is V1: a *ship-now*, reliable, narrow vertical slice, or a feature-parity-with-OpusClip push?"

**Recommended answer:** **Primary user = novice creator; ambition = ship-now reliable narrow slice.** The repo is currently built as a power-user "media studio" (5 top tabs, Short-maker is the 8th of 13 sub-tabs, a 15-control wall) — but the headline V1 promise is "mostly dropdowns, almost no typing, all quality ON." Those are in direct conflict. Pick the novice + ship-now framing for V1; keep the studio surface as an "Advanced" mode, not the front door. Competitive parity (B-roll, avatars, scheduler) is explicitly a V2 ambition, not V1.

**Why this matters:** Every UX, scope, and cut-for-V1 decision below resolves cleanly under "novice + ship-now" and becomes contentious under "power user + parity."

### F-2 — Scope of "works on the user's machine"
**Q (verbatim):** "Is V1 a self-contained native app that must install and run cleanly on an ordinary Windows box (including odd install locations and a cold first-run) with **no WSL dependency on the default path** — or is a WSL/GPU power path an accepted V1 requirement?"

**Recommended answer:** **Self-contained native, no WSL on the default path.** The default reframe engine is already in-sidecar OpenCV/MediaPipe (P3 flipped the default away from the WSL `verthor` path; `verthor` now raises explicitly instead of silently falling back). The real-world first-run failure was a **packaging** bug (write to a non-writable install dir), not a WSL gap. So V1's "runs on the machine" promise is achievable native-only; keep `verthor`/WSL as explicit opt-in for GPU users. This makes the packaging fix (G-16/G-17) the true unblocker, not a WSL investment.

---

## (b) CATEGORIZED DECISION LIST

Format: **G-N** — Question · *Rec:* recommendation · *Trade-off:* one line.

### SCOPE
- **G-1** — Promote Short-maker from the 8th-of-13 buried sub-tab to a top-level primary flow (ideally the default landing)? · *Rec:* **Yes — make it the front door.** · *Trade-off:* Demotes the "media studio" identity; power users lose the studio-first IA they may expect.
- **G-2** — Collapse the 15-control flat wall (`ShortMakerControls.tsx`) into a one-screen "smart defaults + Advanced disclosure"? · *Rec:* **Yes — one screen, ~3 visible choices, rest behind Advanced.** · *Trade-off:* Hides power; advanced users do one extra click to reach knobs.
- **G-3** — Cut/hide the studio sub-tabs (Diarize / Refine / Tracks / Convert) from the V1 primary surface? · *Rec:* **Hide behind Advanced for V1, do not delete.** · *Trade-off:* Less discoverable for the few who want them; smaller surface to support/QA.

### UX
- **G-4** — Flip `DEFAULT_CONTROLS` so quality features are ON by default (stabilize / silenceTrim / autoZoom / removeFillers, emphasis)? · *Rec:* **Yes — defaults ON, matching the stated "all quality ON" promise.** · *Trade-off:* Slower per-clip processing and more chances for a quality step to degrade (couple tightly with G-13).
- **G-5** — Reduce typing — presets-first, dropdowns over free-text where possible? · *Rec:* **Yes — preset row leads; free-text prompt optional/secondary.** · *Trade-off:* Less expressive for users who want prompt-driven moment selection.
- **G-6** — Add competitor table-stakes that are cheap wins (hook-title generation, sane caption-style default)? · *Rec:* **Add hook-title default + one good caption preset; skip the rest.** · *Trade-off:* Small scope add now vs. clean cut; risk of feature creep if not bounded.

### MODELS / DEVICE
- **G-7** — Extend (NOT rebuild) `system_advisor.py` to drive auto-preset selection surfaced in the UI? · *Rec:* **Extend — the probe/advisor/recommender + tiers 0/1/2 already exist and produce `recommended_preset`.** · *Trade-off:* Inherits the existing VRAM-budget heuristics (TIGHT_FRACTION=0.85) rather than designing fresh.
- **G-8** — Keep ASR model auto-selection by device (large-v3-turbo GPU / small CPU)? · *Rec:* **Keep auto; expose as a one-line "using model X because device Y."** · *Trade-off:* CPU-tier users get `small` quality silently unless we surface it.
- **G-9** — Surface the advisor's `recommended_preset` + proposed model downloads at first run? · *Rec:* **Yes — reuse the existing loud reason strings ("needs ~X MB VRAM, over Y MB budget").** · *Trade-off:* Adds a first-run step; mitigated because the strings already exist.

### POLY-PROCESSING (local/cloud split)
- **G-10** — Keep cloud opt-in / local-only default for V1 (consent default-deny per data-type)? · *Rec:* **Yes — default local-only; the `AiJob` degradeChain already terminates in local.** · *Trade-off:* Lower out-of-box quality for moment-selection vs. a cloud model; but zero egress surprises.
- **G-11** — Add a cloud ASR provider, or keep ASR local-only for V1? · *Rec:* **Local-only for V1** (both engines are already local; no cloud ASR seam exists). · *Trade-off:* CPU-tier transcription is slow/lower-quality; cloud ASR would be a clean future poly-processing win.
- **G-12** — Surface `willEgress` / cost-estimate / degrade notices in the UI? · *Rec:* **Yes — show the "degraded: fell back to local" notice and a pre-run egress badge.** · *Trade-off:* Slightly busier UI; essential for trust if cloud is ever enabled.

### RELIABILITY (no silent fallback)
- **G-13** — Fix D1: speaker-tracking silently degrading to a dumb center crop (the marquee feature)? · *Rec:* **Yes — top priority. Surface per-clip ("tracking unavailable, used center crop"), never swallow.** `compute_plan` currently catches ALL detection exceptions + trust-gate miss with only a `log.warning`. · *Trade-off:* Some clips will visibly say "degraded" instead of looking fine-but-wrong — that's the point.
- **G-14** — Make `detect_backend()` return an explicit signal (not silent `"center"`) when cv2 is absent? · *Rec:* **Yes — fail loud at setup; cv2-absent is a provisioning bug, not a per-clip event.** · *Trade-off:* Turns a "works, badly" path into a "blocked until fixed" path — correct for a marquee feature.
- **G-15** — Audit the remaining quieter degrades introduced by turning all quality steps ON (G-4)? · *Rec:* **Yes — one sweep over stabilize/silence/autoZoom/fillers for swallowed failures.** · *Trade-off:* Extra audit time before V1; prevents a "ships ON but silently no-ops" embarrassment.

### PACKAGING / WSL
- **G-16** — Fix the first-run root cause: `bootstrap.py` writes `python3XX._pth` into the (non-writable) install dir, unguarded? · *Rec:* **Yes — guard the write, and/or relocate it so the install dir is never written. This is THE unblocker.** · *Trade-off:* Touches the bootstrap path that every install depends on — needs careful testing across install locations.
- **G-17** — Make first-run fail LOUD + actionable instead of leaving an empty data dir? · *Rec:* **Yes — wrap the bootstrap top-level so PermissionError surfaces as a real error, not exit-1 silence.** · *Trade-off:* None meaningful; strictly better than the current silent empty-dir symptom.
- **G-18** — Avoid Program-Files-class install dirs being load-bearing for writes (or document/guard)? · *Rec:* **Make the runtime never depend on writing the install dir; data/runtime writes go to the data dir.** · *Trade-off:* Some refactor of where `_pth`/env live; cleaner long-term.
- **G-19** — Keep `verthor`/WSL as explicit opt-in and ship in-sidecar as the only default path? · *Rec:* **Yes — already the P3 default; do not regress.** · *Trade-off:* GPU power users must opt in; acceptable per F-2.

### SEQUENCING
- **G-20** — What is the fix-first order for V1? · *Rec:* **(1) Packaging root cause G-16/G-17 → (2) Reliability D1 G-13/G-14 → (3) UX promotion + defaults G-1/G-2/G-4 → (4) cheap competitive wins G-6.** · *Trade-off:* Front-loads invisible plumbing before visible UX; but a beautiful UI on a crashing install or a silently-degrading marquee feature is worthless.

### CUT-FOR-V1
- **G-21** — Cut true multi-speaker / wide-shot reframe handling (RISK-3, genuinely absent today)? · *Rec:* **Cut to V2 — but be explicit in UI that V1 tracks a single subject.** · *Trade-off:* Competitive gap vs. OpusClip; honesty avoids "it broke on my 2-person clip" reports.
- **G-22** — Cut B-roll / emoji-triggers / keyword-SFX / AI-avatar / scheduler (Submagic/Captions.ai parity)? · *Rec:* **Cut all to V2.** · *Trade-off:* Feature-list looks thinner than competitors; but each is a multi-week build and a reliability surface.

---

## (c) BETTER IDEAS (surfaced beyond the ask)

- **First-run self-diagnostic / smoke test** that validates the install end-to-end (writes to data dir, probes device, confirms cv2/ASR present) and reports loudly. *Cross-lens convergence: packaging + reliability both independently point here — a single "did the install actually work" gate kills both the empty-data-dir symptom and the cv2-absent silent center-crop at the same place.*
- **Reuse the advisor's existing loud reason strings in the UX layer.** *Convergence: device lens ("needs ~X MB VRAM, over Y MB budget" strings already exist) + ux lens (novices need to know *why* a preset was chosen).* Near-zero build cost, high trust payoff.
- **One-click device→quality preset mapping**: advisor tier (0/1/2) auto-sets which quality toggles are ON. *Convergence: device + ux — solves G-4 (defaults ON) and G-7 (auto-preset) jointly without the user touching the 15 controls.*
- **Per-clip "real / degraded" badge** in the output list (local, telemetry-free). *From reliability lens — makes G-13/G-15 visible without modal-spam.*
- **"Honest capability" copy** ("V1 follows a single speaker") instead of hiding the multi-speaker gap. *Red-team lens — converts RISK-3 from a bug report into an expectation.*
- **Pin the planning baseline to merged reality:** `feat/reframe-quality` is already merged as #236; the "unmerged wide-shot fixes" framing is stale. *Red-team lens — prevents re-planning against a wrong baseline.*

---

## (d) RISKS / RED-TEAM — TOP 10

1. **Marquee speaker-tracking silently degrades to center crop** (reliability D1). Users conclude the product is cheap/broken; no signal it degraded. → G-13/G-14.
2. **First-run crash on non-writable install dir → empty data dir** (packaging root cause, `bootstrap.py` unguarded `_pth` write). Exact match for the reported real-machine failure. → G-16/G-17.
3. **Buried IA** — Short-maker is the 8th of 13 sub-tabs, ~3 levels deep; novices never find the headline feature. → G-1.
4. **Defaults OFF contradict the "all quality ON" promise** (stabilize/silence/autoZoom/fillers all `false`). The product undersells itself out of the box. → G-4.
5. **Multi-speaker / wide-shot handling genuinely absent** — fails on the common 2-person interview clip vs. OpusClip/Submagic. → G-21 (cut + disclose).
6. **15-control flat wall** is the opposite of "mostly dropdowns, almost no typing" — scares the target novice. → G-2/G-5.
7. **Cloud egress / consent confusion** if cloud is ever surfaced without the `willEgress`/degrade notices wired into UI. → G-12.
8. **Scope creep toward OpusClip/Submagic parity** (B-roll, avatars, SFX, scheduler) sinks the ship-now timeline. → G-22.
9. **CPU-tier ASR is slow/low-quality and silent** (`small` model auto-picked, no cloud ASR option) → bad first impression on weak machines. → G-8/G-11.
10. **Stale baseline assumption** — planning around "unmerged wide-shot fixes" when #236 is already merged wastes effort and misjudges remaining work. → pin baseline (Better Ideas).

---

## (e) LIVE GRILL ANSWERS (2026-06-27)

- **F-1 = ANSWERED → Novice-first, advanced hidden.** Default = paste video → make shorts, near-zero config, all quality ON. Power features exist behind "Advanced". PLUS user model direction: **easiest = local model via Ollama / LM Studio** (advise install + pull best whisper + LLM), **and/or cloud via OpenRouter** with a **pool/stash of API keys + per-key usage/consumption shown** in the UI. Lean on existing local runners; don't hand-provision.
- **F-2 = ANSWERED → Native-default, WSL optional + advised.** Native Windows path always works (no WSL required); WSL/verthor = opt-in power path with a tooltip + optional guided setup when it'd genuinely be better.
- Implications locked: G-1/G-2/G-3 (promote Short-maker to front door + one-screen smart-defaults + Advanced disclosure) = YES. G-4 (quality defaults ON) = YES. G-7/G-8/G-9 (extend system_advisor for device-ranked model recommend + first-run download) = YES, extended to Ollama/LM Studio detect+pull + OpenRouter key-pool+usage. G-10/G-11/G-12 (local-only default, cloud opt-in w/ egress+usage badges) = YES. G-13..G-19 (no-silent-fallback + packaging root-cause) = YES (all). G-20 sequencing = packaging → reliability → UX → cheap wins.
- **GUI layout = ANSWERED → Single-screen one-shot (option A)** approved ("yeah that's it"). Drop video → dropdowns → Make Shorts → results grid w/ real/degraded badge; Advanced hidden; device+model+ETA status strip.
- **Caption/output richness = ADDED (user, must build for V1, per best-practice):**
  - **Language = DROPDOWN selectable (never free-typed)** to avoid wrong/nonexistent languages; Auto-detect also offered BUT if auto yields lower quality than picking upfront, show an ADVICE/warning to pick the language.
  - **Caption POSITION editor**: options + LIVE PREVIEW on the actual video; caption box draggable / resizable / movable (like CapCut/Submagic), reflecting final on-video position.
  - **Subtitle STYLE templates**: multiple presets (karaoke + others) — colors, fonts, styling — selectable + PREVIEWABLE on the video BEFORE processing.
  - **Output options**: save the SRT separately and/or the shorts (for later edits); BURN-IN on/off; all combinations (burn vs soft-mux vs sidecar SRT). A Preferences/Settings area for defaults.
  - User delegates the detail to best-practice ("you know how these programs are designed") — design per CapCut/Submagic/Descript norms; search/clarify only where genuinely unclear.
- **Speaker framing = ANSWERED → Fix wide-shot in V1 + multi-speaker-switching on V2 roadmap.** V1 frames the dominant/active single speaker (no empty studio, even in a 2-shot — the fix already asked for). True speaker-SWITCHING (auto-cut between people) deferred to V2 with honest "follows one speaker at a time" copy.

---

## (f) CONVERGED V1 BUILD PLAN (sequenced; ultracode + TDD 100% + visual-verify)

Baseline = merged main (#236), NOT the stale "unmerged wide-shot" framing. Branch: feat/reframe-v1.

- **Phase 1 — UNBLOCK (foundation, highest priority).** Packaging root-cause: guard bootstrap `_pth`/install-dir writes, dataRoot falls back to userData when install dir non-writable, first-run fails LOUD+actionable (no empty-dir silence) [G-16/17/18]. First-run self-diagnostic/smoke (writable data dir + device probe + cv2/ASR present) reported loudly [Better-Idea]. No-silent-fallback sweep: speaker-track degrade → per-clip loud badge [G-13], detect_backend explicit when cv2 absent [G-14], audit stabilize/silence/autoZoom/fillers swallowed failures [G-15].
- **Phase 2 — MODELS/DEVICE.** Extend system_advisor → device-ranked model recommend surfaced in UI [G-7/8/9]; detect+advise **Ollama / LM Studio** local runners (pull recommended whisper+LLM); **OpenRouter** cloud w/ **API-key pool + per-key usage/consumption** display; ETA + device details (disk/RAM/VRAM/GPU) strip.
- **Phase 3 — UX REDESIGN (single-screen one-shot).** Promote short-maker to the front door [G-1]; one screen, ~3 dropdowns + Make Shorts + results grid w/ real/degraded badge [G-2]; quality defaults ON [G-4]; Advanced disclosure hides studio tabs [G-3]; **language DROPDOWN** (+auto-detect with quality-advice); presets-first, least typing [G-5].
- **Phase 4 — CAPTION EDITOR + OUTPUT.** Draggable/resizable **caption position w/ LIVE PREVIEW** on the video; **subtitle STYLE templates** (color/font/styling) previewable before processing; **output options** (burn-in on/off, save SRT separately, save shorts, combinations); Preferences/Settings area. Per CapCut/Submagic/Descript best-practice.
- **Phase 5 — FRAMING.** Finish wide-shot dominant-speaker fix (no empty studio); add the "single speaker" honest copy; multi-speaker-switching → V2 roadmap doc.
- **Phase 6 — VERIFY + RELEASE.** Visual-verify samples (extract frames + LOOK); full gate (sidecar+renderer 100%, pre-commit); merge; rebuild installer; cut V1 release. Re-test first-run on a Program-Files-class path.

CUT to V2: multi-speaker switching, B-roll/avatars/SFX/scheduler [G-21/22].

## (g) IA / NAVIGATION REFINEMENT (user, 2026-06-27) — overrides G-3 "hide"

- **KEEP all functionality** (join, cut, trim, translate, diarize, refine, convert, etc.) — do NOT delete/remove. The earlier "hide studio tabs" must NOT eliminate capability.
- **CONSOLIDATE the 13 flat tabs into clean SECTIONS** + DEDUPLICATE: each function lives in ONE place. NO operation appears redundantly across multiple tabs (e.g. caption-translation must NOT be a standalone on 4 tabs).
- **Shared ops become CONTEXTUAL OPT-INS after a primary action**, not standalone tabs: after you join / cut / trim / make-shorts, you can opt in to caption it, translate it, burn-subs-or-not, save. Translation/captioning is offered in-context, once.
- **Primary flows to support** (examples user gave): (a) AI moment-pick shorts; (b) MANUAL time-interval shorts — give a video + specify ranges (e.g. 1:23 → 4:10) to clip; (c) edit ops join/cut/trim; each then offers the contextual caption/translate/save options.
- **Unified SAVE/OUTPUT**: save the cut, save the shorts, burn subtitles on/off, save SRT separately — all from one consistent output step (ties to (f) Phase 4 output options).
- **PRINCIPLE:** maximum capability + cohesion, minimum navigation complexity — "everything comes together" without being complex to use. Functional + each section specific (no dead/duplicate tabs).
- ACTION: Phase 3 becomes an IA redesign (sections + dedup + contextual shared-ops), NOT a hide-behind-Advanced. Scout current tabs→functions→duplication, propose consolidated IA, confirm with user before building.

## (h) IA CONVERGED (proposal a6ee4dad + user sign-off 2026-06-27)

**5 SECTIONS (each function in exactly ONE home; zero duplication):**
1. **Library** — sources & readiness (library/project/media/readiness/paths).
2. **Make Shorts** (novice front door, single-screen) — AI moment-pick (shortmaker.select/export, phase8, thumbnail, ranker/feedback) + **Manual interval** mode (ranges 1:23→4:10 via shortmaker.export inline candidates [E3=yes]) + Batch/"make N"/Templates absorbed here [E4=under Make Shorts] + the SINGLE produced-shorts Gallery (absorbs the misnamed "Create" tab + ShortMaker's ProducedShorts).
3. **Edit** — manual per-video: Trim/Cut/**Join**/Reorder/Reframe/Stabilize/Cleanup (refine silence+filler, stabilize.run) + Transcript&Captions (transcribe, semantic index as a search box, subtitles.generate/edit with the Timeline cue-editor MERGED IN [kills dup#1], diarize, tracks mgmt) + Audio (dub/tts, tracks.audio). **E2 = ADD a first-class join/concat op** (genuine gap in edit_plan.OpKind; user listed "join" as required) — backend op + UI.
4. **Director = OWN 5th SECTION** (user sign-off) — the only NL editor (director.plan/previewCost/apply/undo/evaluate), same op engines exposed as "describe it"; headline feature.
5. **Settings** — Models&System (system/asr/providers.catalog/assets) · Providers&Keys (providers/savePresets/spend + **OpenRouter key-pool + per-key usage**) · Storage&Branding (paths + ShortMaker's leaked data-folder/brand-kit MOVED here) · Health. **E6 = keep the global Local/Cloud quality toggle in the header + per-function routing override in Settings/Advanced** (enables poly-processing).

**KEYSTONE = "Output Tray"** (defined ONCE, rendered after any primary action in Make Shorts / Edit / Director): Caption? · Translate? · Reframe? · Burn-subs on/off · [Save clip][Save short][Save SRT separately] · Preset/Package/NLE-export. Kills the cross-surface dups (caption×6, translate×3, silence×4, subtitle-edit×2, gallery×2, export×7).

**E5 = Convert** → Output-step utility (still discoverable). Migration table (old 13 Workspace sub-tabs + 5 top tabs → these 5 sections) is in proposal a6ee4dad. NOTHING removed — all capability kept, just deduplicated + contextual.
