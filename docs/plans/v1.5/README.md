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

- **B-roll is not deferred.** `PROGRAM.md` makes local auto-B-roll flagship #3 and puts
  emoji-burst + SFX-on-emphasis in the caption engine.

  > **CORRECTED (2026-08-12).** This bullet used to open by asserting, in the present
  > tense, that the `## Still deferred` sentence in `docs/ROADMAP.md` *lists* B-roll
  > alongside emoji/SFX triggers and publishing. That was true at `1fa9a69f` and is now
  > **REFUTED**: the same branch that wrote this correction removed B-roll from that
  > sentence (commit `cddc178a`), which now names only emoji / keyword SFX triggers, AI
  > avatars and a publishing scheduler and carries its own retraction beneath it. So the
  > contradiction this bullet reported is closed at the source, and the *report* of it had
  > gone stale — a doc asserting something another doc in the same commit series
  > contradicts, which is the exact defect class this corpus exists to remove, created by
  > the pass that was removing it. Marked rather than deleted so the next reader inherits
  > the correction instead of re-deriving it.
  >
  > `C11a`/`C11b` pin the code and the ROADMAP sentence and BOTH reported green over this
  > line, being scoped to files that do not include it — a guard that cannot see a
  > contradiction reports its absence. `C11c` now scans every other doc for the same
  > assertion. Known limit, stated rather than hidden: `C11c` skips blockquote lines, so
  > this paragraph is invisible to it — the price of not punishing a retraction for
  > quoting what it retires. A live wrong claim parked in a `>` block would be missed.
  > Settling experiment: unindent this block and confirm `C11c` goes red.

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
  `App.tsx`, which renders 8 vertical rails.
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

> **CORRECTED (2026-08-13) — that promise was false off ONE machine, and is true now.** The
> `P1-shell` INVARIANT counted PNGs under the UNTRACKED scratch directory
> `~/.reframe-review/shell-audit` — a path this README mentions once, at the top, as the corpus's
> historical *origin*, never as a prerequisite of the command above. So a reviewer, a CI runner or
> any later reader got exit 1 naming `P1-shell`, a claim that had not drifted at all, while its
> OPEN sibling `P1-corpus` flipped to `NOW-FIXED (retire it from OPEN_ITEMS)` on 0/12 files found —
> inviting a stranger to retire a check on a measurement that never ran, which is verbatim the
> failure the verifier condemns in its own comment above `P1_SCRATCH`. MEASURED both states with
> `$HOME`/`$USERPROFILE` pointed at an empty directory. `P1-shell` now asserts the **TRACKED**
> captures at [`shell-audit/`](shell-audit) (8 PNGs — the promote-then-assert shape `P1-promoted`
> already used), and `P1-corpus` prints `NOT-MEASURED` where the scratch corpus is absent instead
> of guessing. Held by [`test_verify_ssot_claims.py`](../../validation/tools/test_verify_ssot_claims.py),
> which runs the documented command in a hermetic HOME and carries a control proving the
> redirection took effect — without that control the test would pass for the wrong reason on the
> author's box. **Residual, stated not hidden:** `P1-corpus` still reads that scratch directory, so
> elsewhere it reports rather than measures. It is an OPEN item and never gates the exit code, and
> re-pointing it is not available — `git ls-files` matches none of its 12 basenames anywhere in the
> tree (0 of 12 promoted, measured 2026-08-13), unlike the 8 captures above.

> **SCOPE, corrected — it does NOT check this file.** The earlier wording ("re-checks every
> load-bearing factual claim behind this reconciliation") was wider than the tool, and the proof
> was sitting in its own output: it exited 0 (`total=40 as-predicted=40 mismatched=0`, the count at
> `1fa9a69f` — re-derive with the command above, which prints its own current total) in a tree
> where the B-roll bullet above still asserted `app/package.json` is 1.4.2 — twenty lines from
> the tool's own `P2.11a ... app/package.json version=1.5.0`. The instrument was right; nothing
> compared the prose against it. (That bullet has since been re-measured and now carries the
> dated 1.2.0-vs-1.5.0 gap, so the example is historical — the SCOPE limit it demonstrates is
> not.) A green run here means every REGISTERED claim holds — how many that is, is printed by the
> run itself and deliberately not retyped here; the sentence used to name a count, and that count
> had already drifted, which is this paragraph's own point committed one line below where it is
> made. It still says nothing about a literal written in this README. **The follow-up this
> paragraph deferred is now partly done (2026-08-12, `1fa9a69f`):** `P3-readme-count` in the
> verifier fails if this file ever hand-writes that count again. Partly, not fully — it pins THIS
> literal, not every literal in the corpus, and the general case remains open.
