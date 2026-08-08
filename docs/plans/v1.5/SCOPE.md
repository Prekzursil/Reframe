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

### O-2 — `ReframeOverridePanel` is built, tested, and mounted nowhere

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
