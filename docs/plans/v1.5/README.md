# v1.5 plan corpus

> **Status:** ACTIVE

Everything in this directory was authored during the v1.5 planning work and lived
**untracked** on one machine (`~/.reframe-review/`) until this commit. It is landed
here **verbatim**, so that the corrections in the follow-up passes are reviewable as
diffs rather than arriving pre-applied.

## The anti-drift rule

R1 ("Authority lives in the repo, or it is not authority") used to be restated in full
here. It is now tree-wide, stated once with R2-R4 alongside it, and mechanically
enforced: see [`docs/INDEX.md` § Anti-drift](../../INDEX.md#anti-drift) and
`.quality/docs_check.py`. Duplicating it here is exactly the failure the rule exists
to stop.

What is worth keeping local to this corpus is the corollary it was landed under:
**when a doc and the code disagree, the code wins and the doc is a bug.** Every
contradiction resolved in this pass was a doc asserting something the code had already
changed — never the reverse.

## What each file is authoritative for

| file | authoritative for | status |
|---|---|---|
| `PROGRAM.md` | the owner-locked v1.5 scope + decision list | **current** — newest, and it supersedes older plans on conflict |
| `GRILL-DECISION-QUEUE.md` | binding owner decisions taken during the grill (versioning — B-1 chose 1.4.2 and is now marked SUPERSEDED by the 1.5.0 bump in #402; baseline REGEN; a11y critical-only) | **current** |
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
  **That quoted pairing conflates two different KINDS of licence — annotation added
  2026-08-11 (W24 remediation); the quote is left verbatim because it is the locked
  decision.** ViNet-S's CC-BY-NC-SA is a **weights** licence (live code:
  `sidecar/media_studio/features/saliency.py:421`, the `AssetEntry.label` on the
  `installer="download"` entry, and the registering docstring at `:408`) — which the
  line above already implies by calling it "the CC-BY-NC-SA **checkpoint**" — whereas
  UNISAL's Apache-2.0 is its **repository/code** licence, and the UNISAL *weights*
  licence is UNVERIFIED: a recursive scan of the pinned `rdroste/unisal@0440df77`
  tree (41 entries, `truncated: false`) finds exactly one licence artifact, the root
  `LICENSE`, and none beside either weight. So the swap is a licence improvement of
  *unmeasured size* until the UNISAL weights terms are read. Full adjudication and
  the settling experiment: `PROGRAM.md:37` and its licence sub-bullet at `:40`.
  **`PROGRAM.md` wins** — it is newer and it is the owner's locked decision, and
  `flagship-lip-sync-dub.md` independently rules the re-hosting dossier stale.
  Neither has executed: `features/_vinet_s/` is still on disk and there are zero
  UNISAL references in implementation code (the single textual hit is one alternative
  inside a model-name regex in `advisorMeta.test.ts`, i.e. a mention, not a swap).

- **B-roll is not deferred.** `docs/ROADMAP.md` lists B-roll, emoji/SFX triggers and
  publishing as "deferred from V1" (`docs/ROADMAP.md:66`); `PROGRAM.md` makes local
  auto-B-roll flagship #3 and puts emoji-burst + SFX-on-emphasis in the caption engine.
  Re-measured 2026-08-11: `docs/ROADMAP.md`'s Release-status list still stops at **v1.2.0**
  while `app/package.json` is **1.5.0** — so the gap is three minors wide (1.2 -> 1.3 -> 1.4
  -> 1.5), not the two it was when this line was written.
  (An earlier revision of this line asserted `app/package.json` is 1.4.2. That was true when
  written and is now REFUTED; the version is a moving figure, so treat the dated measurement
  as the claim and re-run it rather than reading the number as a standing fact. A first
  attempt at this correction closed with "not one", which is also REFUTED: the superseded
  figure 1.4.2 against v1.2.0 is a TWO-minor gap, and no revision of this line ever claimed
  one.)

## Two documents were archived, not promoted

They are at `docs/_archive/2026-07/` because they are superseded, and one is
**actively wrong** in a way worth remembering:

- `docs/_archive/2026-07/reframe-visual-audit.md` — its P0 ("16+ horizontal top-level tabs") is refuted by
  `App.tsx`, which renders a vertical rail. **Re-measured 2026-08-13: the rail is FIVE destinations**
  (Library / Produce / Refine / Deliver / Settings), derived from the `tabs` array `App.tsx` declares to be
  its SSOT. This line previously said "8 vertical rails", which was true when written and was invalidated by
  the L5 navigation rebuild (`69665321`, PR #431) that cut the rail from eight destinations to four +
  Settings. The refutation of the archived P0 still stands — vertical, not 16 horizontal tabs — only the
  count moved. Do not re-pin a raw count here: `P2.10a` in `docs/validation/tools/verify_ssot_claims.py`
  now DERIVES the rail from that array and is the machine-checked authority.
- `docs/_archive/2026-07/reframe-reconcile-audit.md` — asserts *"there is NO 'YuNet' anywhere in the repo
  (zero matches)"*. YuNet is referenced throughout the tree — hundreds of occurrences across
  dozens of files, and the detector it
  contradicts had landed roughly 24 hours before that file's mtime. Its headline gap
  (no keystore) was likewise already closed by `app/main/keystore.ts`.

  The lesson is the reason it is kept: **a confident "zero matches" from a stale
  working copy reads exactly like a finding.** Corroborate a claimed absence against
  the tree at HEAD before acting on it.

## Verifying this corpus has not drifted

`docs/validation/tools/verify_ssot_claims.py` re-checks **its own registered list** of claims —
file existence, the live version literal, palette values, the RPC registration site, the
rail/sub-tab counts — mechanically, against the tree. Run it after any change here:

```
python docs/validation/tools/verify_ssot_claims.py
```

It exits non-zero and names each **registered** claim that no longer resolves as recorded.

> **SCOPE, corrected — it does NOT check this file.** The earlier wording ("re-checks every
> load-bearing factual claim behind this reconciliation") was wider than the tool, and the proof
> was sitting in its own output: it exited 0 (`total=40 as-predicted=40 mismatched=0`) in a tree
> where the B-roll bullet above still asserted `app/package.json` is 1.4.2 — twenty lines from
> the tool's own `P2.11a ... app/package.json version=1.5.0`. The instrument was right; nothing
> compared the prose against it. (That bullet has since been re-measured and now carries the
> dated 1.2.0-vs-1.5.0 gap, so the example is historical — the SCOPE limit it demonstrates is
> not.) A green run here means the 40 REGISTERED claims hold; it says nothing about a literal
> written in this README. Closing that properly means adding checks that pin this corpus's own
> literals, which is a follow-up, not a wording change.
