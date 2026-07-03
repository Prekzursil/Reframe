# Reframe — Roadmap

> What the shipping app deliberately does and does not do, and what is deferred.
> Authoritative scope decisions live in [`V1-GRILL-DECISIONS.md`](V1-GRILL-DECISIONS.md)
> (see G-21/G-22 and section (e) "Speaker framing"). This file is the honest,
> user-facing summary of the capability boundary.

## Release status

- **v1.0.0 / 0.1.0** — shipped: first plug-and-play local Windows studio (see
  [`CHANGELOG.md`](../CHANGELOG.md)).
- **v1.1.0** — shipped: the **HYBRID multi-speaker reframe engine** (below) plus
  tiered subtitles, model management, and media lineage.
- **v1.2.0** — **shipped**: the native **YuNet** face detector (replacing the
  MediaPipe/haar path), the **virality highlight badge**, the **EdgeTAM** opt-in
  tracker, no-silent-fallback hardening, the SpeechBrain-pinned multi-speaker
  diarizer, and CodeQL 72 → 0. See `V1.2-FEATURES.md`.

## Default capability — speaker framing (single speaker)

The **default** `auto` reframe frames a **single speaker**. It locates the
**dominant / active** subject (via the native YuNet face detector, then motion
saliency) and keeps the vertical crop on them, smoothly tracked:

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

## Multi-speaker switching — shipped in v1.1.0 (explicit opt-in)

Automatic **multi-speaker switching** — detecting *who is talking now* across
multiple people and **cutting between them** (e.g. an interview where the crop
follows the conversation back and forth) — was the V1 slice's deferred item (per
[`V1-GRILL-DECISIONS.md`](V1-GRILL-DECISIONS.md) G-21) and **shipped in v1.1.0**
as the **HYBRID multi-speaker reframe engine** (`reframe_multispeaker`). It fuses
active-speaker diarization with face tracking and a shot-change policy to decide a
per-segment **cut / 50-50 split / 3-up composite** vertical layout. It is an
**explicit opt-in** engine (the `auto` default still tracks a single speaker); its
GPU tier is provisioned on the host and, as of v1.2.0, its SpeechBrain audio
dependency is declared + pinned (`speechbrain==1.0.3`). See
[`WU-R1-MULTISPEAKER-ENGINE.md`](WU-R1-MULTISPEAKER-ENGINE.md) and
[`V1.1-BUILD-NOTES.md`](V1.1-BUILD-NOTES.md) for the engine + validation record.

## Still deferred

Items deferred from V1 (per G-22) that have **not** yet shipped: B-roll, emoji /
keyword SFX triggers, AI avatars, and a publishing scheduler.
