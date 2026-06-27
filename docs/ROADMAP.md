# Reframe — Roadmap

> What V1 deliberately does and does not do, and what is deferred to V2.
> Authoritative scope decisions live in [`V1-GRILL-DECISIONS.md`](V1-GRILL-DECISIONS.md)
> (see G-21/G-22 and section (e) "Speaker framing"). This file is the honest,
> user-facing summary of the capability boundary.

## V1 capability — speaker framing (single speaker)

V1 frames a **single speaker**. The 9:16 auto-reframe locates the **dominant /
active** subject and keeps the vertical crop on them, smoothly tracked:

- **Wide / two-shot:** the crop locks onto the **largest, most-active** face or
  person (the featured speaker) — it **never** shows an empty studio, an
  edge-cut, or the gap between two people.
- **Two people, different sizes:** the **larger / closer** person (the one the
  shot features) is framed.
- **Symmetric two-shot (similar sizes):** the **active speaker** wins the tie —
  the person with the most mouth / gesture **motion** between frames.
- **No detectable face/body:** motion saliency locks onto the **single dominant
  motion cluster** (one speaker), not the average of everything that moved.
- **Tracking:** zero-phase EMA smoothing (no jitter, no drift back to frame
  center); when tracking genuinely cannot run, the clip degrades to a center
  crop **and says so** (a per-clip "degraded" notice — no silent fallback).

Implementation: `sidecar/media_studio/features/reframe_claudeshorts.py`
(`select_dominant`, the face → person → motion finder chain, and the
`_dominant_cluster_centroid` motion fallback). Honest copy:
`SINGLE_SPEAKER_CAPABILITY_NOTE` in that module.

## V2 — multi-speaker switching (deferred)

Automatic **multi-speaker switching** — detecting *who is talking now* across
multiple people and **cutting between them** (e.g. an interview where the crop
follows the conversation back and forth) — is a **V2** feature. It needs
active-speaker diarization fused with face tracking and a shot-change policy, and
is intentionally out of scope for the ship-now V1 slice (per
[`V1-GRILL-DECISIONS.md`](V1-GRILL-DECISIONS.md) G-21: "cut multi-speaker /
wide-shot *switching* to V2 — but be explicit in the UI that V1 tracks a single
subject").

Other V2 items deferred from V1 (per G-22): B-roll, emoji / keyword SFX
triggers, AI avatars, and a publishing scheduler.
