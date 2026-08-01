# v1.5 plan corpus

Everything in this directory was authored during the v1.5 planning work and lived
**untracked** on one machine (`~/.reframe-review/`) until this commit. It is landed
here **verbatim**, so that the corrections in the follow-up passes are reviewable as
diffs rather than arriving pre-applied.

## R1 — Authority lives in the repo, or it is not authority

A document that is not in this tree cannot be reviewed, cannot be diffed, cannot be
found by the next person, and is one disk failure from gone. If a decision matters,
it is committed. If it is not committed, it is a draft, no matter how carefully it
was written.

Corollary: **when a doc and the code disagree, the code wins and the doc is a bug.**
Every contradiction resolved in this pass was a doc asserting something the code had
already changed — never the reverse.

## What each file is authoritative for

| file | authoritative for | status |
|---|---|---|
| `PROGRAM.md` | the owner-locked v1.5 scope + decision list | **current** — newest, and it supersedes older plans on conflict |
| `GRILL-DECISION-QUEUE.md` | binding owner decisions taken during the grill (version 1.4.2, baseline REGEN, a11y critical-only) | **current** |
| `DESIGN-DIRECTION.md` | the v1.5 re-skin direction | current for *direction*; **`app/renderer/src/styles/tokens.css` is authoritative for values** |
| `redesign.html` | the validated redesign prototype | reference artifact |
| `shell-audit/` | 8 screenshots + `capture-report.json` of the built shell as of the audit | evidence, point-in-time |
| `flagship-active-speaker.md` | flagship #1 plan | proposed, not executed |
| `flagship-transcript-editing.md` | flagship #2 plan | proposed, not executed |
| `flagship-auto-broll.md` | flagship #3 plan | proposed, not executed |
| `flagship-lip-sync-dub.md` | flagship #4 plan | proposed, not executed |
| `signed-release-ci.md` | the signed-release CI design | proposed |
| `signed-release-trust-options.md` | **why** Ed25519 beat cosign / SLSA / Authenticode | the only record of the rationale behind `app/main/updateVerify.ts` — do not delete |
| `model-rehosting.md` | the CC-BY-NC-SA re-hosting dossier | **SUPERSEDED** by `PROGRAM.md` — see below |
| `techprep-dossier.md` | technology-prep survey | reference |
| `competitor-research.md` | competitor landscape | reference, point-in-time |

## Known supersessions inside this corpus

- **ViNet-S.** `model-rehosting.md` (2026-07-04) plans to permanently re-host the
  CC-BY-NC-SA checkpoint. `PROGRAM.md` (2026-07-11) instead locks
  *"ViNet-S (CC-BY-NC-SA) → UNISAL (Apache-2.0)"* as a mandatory NC→permissive swap.
  **`PROGRAM.md` wins** — it is newer and it is the owner's locked decision, and
  `flagship-lip-sync-dub.md` independently rules the re-hosting dossier stale.
  Neither has executed: `features/_vinet_s/` is still on disk and there are zero
  UNISAL references in implementation code (the single textual hit is one alternative
  inside a model-name regex in `advisorMeta.test.ts`, i.e. a mention, not a swap).

- **B-roll is not deferred.** `docs/ROADMAP.md` lists B-roll, emoji/SFX triggers and
  publishing as "deferred from V1"; `PROGRAM.md` makes local auto-B-roll flagship #3
  and puts emoji-burst + SFX-on-emphasis in the caption engine. ROADMAP.md is stale
  at v1.2.0 while `app/package.json` is 1.4.2.

## Two documents were archived, not promoted

They are at `docs/_archive/2026-07/` because they are superseded, and one is
**actively wrong** in a way worth remembering:

- `reframe-visual-audit.md` — its P0 ("16+ horizontal top-level tabs") is refuted by
  `App.tsx`, which renders 8 vertical rails.
- `reframe-reconcile-audit.md` — asserts *"there is NO 'YuNet' anywhere in the repo
  (zero matches)"*. There are 369 occurrences across 44 files, and the detector it
  contradicts had landed roughly 24 hours before that file's mtime. Its headline gap
  (no keystore) was likewise already closed by `app/main/keystore.ts`.

  The lesson is the reason it is kept: **a confident "zero matches" from a stale
  working copy reads exactly like a finding.** Corroborate a claimed absence against
  the tree at HEAD before acting on it.

## Verifying this corpus has not drifted

`docs/validation/tools/verify_ssot_claims.py` re-checks every load-bearing factual
claim behind this reconciliation — file existence, version literals, palette values,
the RPC registration site, the rail/sub-tab counts — mechanically, against the tree.
Run it after any change here:

```
python docs/validation/tools/verify_ssot_claims.py
```

It exits non-zero and names each claim that no longer resolves as recorded.
