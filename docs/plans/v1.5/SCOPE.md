# v1.5 — Scope and open items

> **Status:** ACTIVE
> The one place the v1.5 scope and its section numbering are FIXED. Every `v1.5 §N`
> comment in tracked source resolves here. Per-wave STATUS lives in
> [`PROGRAM.md`](PROGRAM.md); this file fixes WHAT is in scope and carries the open
> items inherited from archived plans.

## Why this file exists

Three items were tracked ONLY inside plan documents that phase 3 archived. An
archived doc is not authority (see [the anti-drift rule](../../INDEX.md#anti-drift)),
so anything still open had to land somewhere live first or it would have been
silently dropped. They are below, each with the probe that establishes it is still
open.

## Inherited open items

### O-1 — `providers.editKey` is not registered

The Provider Hub exposes `providers.testKey` and `providers.revealKey` but there is
no `providers.editKey`, so an index-targeted key edit has no RPC method behind it.

- Verified: `sidecar/media_studio/handlers/composition.py:233` registers
  `providers.testKey`, `:238` registers `providers.revealKey`; a tree-wide
  `git grep editKey` over `sidecar/` returns nothing.
- Was tracked in: `~/.reframe-review/reframe-reconcile-audit.md`, archived at
  `docs/_archive/2026-07/reframe-reconcile-audit.md`. That file's headline (no
  keystore) and its YuNet "CORRECTION" are both false; this one line is its only
  live residue.

### O-2 — `ReframeOverridePanel`: mounted 2026-08-09, correction loop still OPEN

> **RECONCILED 2026-08-10.** The paragraphs below were written before the panel
> was mounted and they now disagree with the tree in two places. Read this note
> first; the body is kept because its measurements are still the record of how
> the item got here.
>
> 1. **"the panel must stay unmounted for now" is SUPERSEDED, not satisfied.**
>    Owner ruling 2026-08-09 was *mount, do not delete*, and W17 mounted it on the
>    `reframeFix` tab via `app/renderer/src/features/ReframeCorrect.tsx`. This
>    file's own warning — that mounting first "would ship a surface that looks
>    functional and silently does nothing" — was the right worry and is answered
>    by CONSTRUCTION, not by ignoring it: the container states inline that the
>    corrections are not applied, refuses to offer re-export (which would discard
>    them), and hands them back as the exact `reframeOverrides` entry.
> 2. **"nothing in `app/renderer` calls either RPC" is now FALSE.**
>    `ReframeCorrect` calls `client.reframe.shotPlanFor`, so `client.reframe.*`
>    is reached by production code, not only by `client.ce.test.ts`.
>
> **What is still genuinely missing** — three renderer-side gaps, one closed:
>
> - CLOSED. `ReframeOverridePanel.onRerender` used to hand back shot INDICES
>   only, so the `ShotOverride` objects never escaped the component and no host
>   could send them anywhere. It now hands out the corrections too.
> - OPEN. `client.shortmaker.export` (`app/renderer/src/lib/rpc/client.ts:296-309`)
>   exposes no `reframeOverrides` option, so no renderer call can carry the map.
> - OPEN. A produced clip cannot re-drive its own export. `shortmaker.export`
>   resolves candidates by id from the select cache
>   (`sidecar/media_studio/features/shortmaker.py:1525-1549`) and a produced clip
>   records no candidate id, no `rank` and no source `start`/`end`
>   (`shorts.py:64-72` `META_FIELDS`; `shorts.py:457-477` `reexport` returns a
>   hook/template/virality/duration skeleton). `_assert_overrides_matched`
>   (`shortmaker.py:1358-1367`) additionally keys the map on the NEW export's
>   final path, so a re-export must reproduce the same rank-ordered stem.
>   **Conclusion: the correction loop belongs on the Short-maker export surface,
>   which still holds the live candidates — not on the produced-clip corrector.**
>   Anyone reading the old text below as "build `reframe.render` sidecar-side"
>   is being sent the wrong way; that method is not needed and never was.

`app/renderer/src/panels/ReframeOverridePanel.tsx` is complete and 100% covered in
isolation, and no production code imports it. It is WU-3a3 of the v1.4 plan; its
siblings WU-3a1/3a2/3a4 shipped.

- Verified: `git grep -l ReframeOverridePanel -- app` returns exactly two paths, the
  component and its own test. The other two production `panels/` mounts are
  `DirectorPanel` and `ModelsSystemPanel`.
- Not a mount-only fix. `docs/validation/v15-audit-ledger.md:1904` records why: no
  per-shot trace is produced for the renderer and no engine path re-renders the
  affected shot set, so the prerequisite work is a trace producer surfaced over RPC
  plus a per-shot re-render parameter in the export path.
- Was tracked in: `docs/plans/_archive/v1.4-experience-overhaul.md:46,:76-78`.

**Status: both prerequisites are now BUILT; the mount is NOT.** The item stays
open. What landed, sidecar-side only:

1. *Trace producer surfaced over RPC.* `MultiSpeakerReframeEngine` writes a
   decision sidecar (`<clip>.reframe.json`) after a successful render, and
   `reframe.shotPlanFor {clip}` turns it into the editable plan the panel takes.
   A clip the engine never rendered has no sidecar and answers `{"plan": null}` —
   the honest empty state, so a caller can explain rather than invent data.
2. *Per-shot re-render.* `MultiSpeakerReframeEngine.rerender_with_overrides`
   replays the corrections onto the persisted plan and re-encodes the timeline
   **without re-running the ML analysis**. `shortmaker.export` accepts
   `reframeOverrides: {clipPath: [ShotOverride]}` and threads each clip's entry
   into its own reframe stage; an engine that cannot honour a correction, and a
   correction that matches no exported clip, both fail LOUD.

Scope of (2), stated precisely so it is not read as more than it is: shots the
user did not touch keep byte-identical geometry but are re-encoded, and the
caption / zoom / brand stages re-run as part of the normal export. The saving is
the analysis pass, not the encode.

Still missing — and the reason the panel must stay unmounted for now: nothing in
`app/renderer` calls either RPC (`client.reframe.*` is still reached only by
`client.ce.test.ts`), so the remaining work is the renderer surface — obtain the
plan for a produced clip, mount the panel behind a "Fix the framing" disclosure,
and send `onRerender`'s affected set back through `shortmaker.export` with
`reframeOverrides` for that clip. Mounting the panel before that would ship a
surface that looks functional and silently does nothing, which is worse than the
current state.

### O-3 — the fuller prompt-driven Director surface

v1.4 promoted a Director rail with plan/apply/undo and a cost preview. The fuller
prompt-driven surface the `prompt-driven-editing` bundle designed is explicitly
deferred to 1.5.

- Verified: `CHANGELOG.md:255-257` — *"A dedicated Reframe Director panel is a v1.5
  item … the fuller prompt-driven Reframe Director surface is planned for 1.5."*
- Was designed in: `docs/plans/_archive/prompt-driven-editing/{DESIGN,PLAN,FEATURE}.md`.
  What shipped is `sidecar/media_studio/features/director.py`,
  `director_op_engines.py`, `director_eval.py` and
  `app/renderer/src/panels/DirectorPanel.tsx`.

## Section numbering

`§1..§P5` are reserved for the wave sections in [`PROGRAM.md`](PROGRAM.md). A source
comment citing `v1.5 §N` means that section number in `PROGRAM.md`; a comment citing
`v1.5 O-N` means an open item in this file.

## What is NOT in v1.5 scope

Items an archived plan proposed and the shipped code did not take are closed, not
deferred. The archived bundles under `docs/plans/_archive/` each name the module
that superseded them in their status header; read that header before reviving
anything from one.
