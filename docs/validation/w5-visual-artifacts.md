# Lane VISUAL — make a visual regression diagnosable + diagnose `workspace-preview`

> **Status:** ACTIVE

**Branch:** `ci/v15-w5-visual-artifacts` · **Base:** `origin/main` @ `81a04965`
Both deliverables measured.

> **⚠ The base is NOT the merge target, and three claims below were refuted because of
> it.** `origin/main` moved `81a04965 → 60f1a43e → 5c80c79b (PR #408) → 739ff6ed → a75ba50a`
> while this branch was in review. Everything measured against `81a04965` still holds *at
> 81a04965*; every statement about **which CI steps run after a red visual gate** is
> merge-target dependent and was re-measured at `739ff6ed`. Where the two disagree, the
> refuted wording is kept and marked, per the corrections-are-recorded rule.
>
> **Pin the BLOB, not the commit** — that is the lesson this section cost. `origin/main`
> advanced twice more during the remediation, but `e2e.yml` at `a75ba50a` is blob
> `986f1d1b`, byte-identical to `739ff6ed`, so the measurements below still hold. Before
> citing any of them, re-run the two-line check rather than comparing commit SHAs:
> `git rev-parse origin/main:.github/workflows/e2e.yml` — if it is still `986f1d1b`, nothing
> here has drifted.

> Write-as-you-go marker, kept deliberately: "If it still reads this way, the unit died before
> measuring anything and no verdict here may be cited." It does **not** still read that way —
> every section below carries a measurement.

---

## Deliverable 1 — make a visual failure diagnosable

### The briefed premise is REFUTED (recorded, not deleted)

Briefed: *"the `-actual.png` and `-diff.png` Playwright wrote under `test-results/` are never
uploaded."*

**REFUTED.** They **are** uploaded. `.github/workflows/e2e.yml:701-710` uploads
`app/playwright-report/` **and `app/test-results/`** with `if: always()`, `retention-days: 7`.
The artifact was empty for a different, sharper reason.

### Correctly-scoped root cause (CONFIRMED)

`app/test-results/` is uploaded but **clobbered before the upload runs**. Neither Playwright
config set `outputDir`, so both resolved to the *same* `app/test-results/`, and Playwright
**deletes `outputDir` at the start of every run**.

- `app/playwright.config.ts:9-31` — no `outputDir` → `app/test-results/`
- `app/playwright.visual.config.ts` (pre-change) — no `outputDir` → **the same directory**

Step order on Actions run **31445248586**, job `e2e-gui (windows-latest)` (measured with
`gh run view 31445248586 --json jobs`):

| # | conclusion | step |
|---|---|---|
| 22 | success | Playwright Electron (Windows packaged .exe + dev-build pipeline) |
| 23 | **failure** | **E2E GUI — VISUAL screenshot-diff + A11Y (axe)** |
| 25 | skipped | speech → transcript → caption |
| 26 | skipped | native "Add videos" dialog |
| 27 | success | Install the built package SILENTLY (NSIS /S) |
| 28 | **failure** | **INSTALLED build cold first-run + data pipeline** |
| 31 | success | Upload Playwright report |

Step 28 runs `npx playwright test --config playwright.config.ts installed-app` and carries
`!cancelled()` (`e2e.yml:646`), so the red at step 23 does not skip it. It ran **after** the
visual failure and wiped `app/test-results/`.

**Independent corroboration** — I downloaded the artifact myself. Its complete contents:

```
test-results\installed-app-INSTALLED-bu-82efa-lists-the-seeded-video-W41-\error-context.md
test-results\installed-app-INSTALLED-bu-dd800-rough-the-packaged-runtime-\error-context.md
```

Both from **`installed-app`** (step 28) — not from the visual suite. That is the clobber, on the
wire, in the shipped artifact.

**Mechanism proven executably** (not from docs). Detector control first: two marker files planted
under `app/test-results/`, confirmed present. Then a second Playwright invocation whose
`outputDir` pointed at that directory (`1 passed`, exit 0):

```
marker BEFORE: True
marker AFTER : False
dir AFTER    : .last-run.json
```

A first attempt at this probe died at config load (`Cannot find module '@playwright/test'`) and
its "marker survived" reading was **void, not evidence** — recorded so the passing probe above is
not mistaken for a first-try result.

### Scope of the defect — REFUTED as written; it is UNIVERSAL on the Windows leg

> **REFUTED wording, kept verbatim (was true at `81a04965`, false at the merge target):**
>
> > - **Nightly / plain dispatch, visual red:** steps 25-28 all skip (implicit `success()` gate;
> >   27/28 are dispatch-only), nothing clobbers, PNGs upload. Diagnosable today.
> > - **Dispatch with `drive_installed_build=true`, visual red:** step 28 runs and clobbers.
> >   **Not** diagnosable. That is run 31445248586.
> >
> > This matters: a naive "move outputDir and let PR #408 add the upload later" would have been
> > a **regression** for the nightly case. It was avoided — see below.
>
> Why it is wrong: it is a **merge-target-dependent** claim about `e2e.yml`, asserted with no
> inline UNVERIFIED tag, about a file this lane knew was owned by open PR #408 **whose entire
> subject was those guards**. #408 merged as `5c80c79b` and flipped exactly the two post-visual
> steps that are Windows-only with no dispatch gate.

**Correctly-scoped version (measured at `origin/main` = `739ff6ed`):**

`yaml.safe_load` over `e2e.yml` at both revs, resolving `npm run` wrappers through
`app/package.json` (detector control: the matcher was first confirmed to find the two
known-present `test:e2e:visual` steps; a narrower first matcher keyed only on the literal
`playwright test` **missed step 20** and undercounted 4 as 3 — recorded):

| `e2e-gui` step | invokes | guard @ `81a04965` | guard @ `739ff6ed` |
|---|---|---|---|
| 20 Windows packaged suite | `playwright.config.ts` | `runner.os == 'Windows'` | `!cancelled() && Windows` |
| 21 VISUAL gate | `playwright.visual.config.ts` | `!cancelled() && Windows && inputs != 'true'` | unchanged |
| 22 VISUAL REGEN | `playwright.visual.config.ts` | `always() && Windows && inputs == 'true'` | unchanged |
| 23 transcribe-journey | `playwright.config.ts` | **bare — implicit `success()`** | **`!cancelled() && Windows`** |
| 24 add-videos-dialog | `playwright.config.ts` | **bare — implicit `success()`** | **`!cancelled() && Windows`** |
| 26 installed-app | `playwright.config.ts` | `!cancelled() && Windows && inputs == 'true'` | unchanged |

Neither 23 nor 24 carries a `github.event.inputs` condition, so both fire on the **cron**. So:

- **Before #408** — on the nightly a red visual gate skipped 23/24, and 26 was dispatch-only, so
  nothing clobbered and the PNGs uploaded. Independent corroboration that they used to skip:
  `gh run view 31445248586 --json jobs` reports `25 skipped … 26 skipped`.
- **Since #408 (`5c80c79b`)** — 23 and 24 run after a red visual gate on the nightly too, each
  deleting `app/test-results/` at start. **The clobber is universal on the Windows leg, not
  dispatch-only.**

This does not weaken the landed fix; it makes it strictly more necessary. What it does kill is
the *rationale* above: the "regression for the nightly case" that the html-reporter design was
chosen to avoid can no longer occur, so that design argument is moot (the design is still right
for the other reason — the report survives an outputDir wipe).

### What LANDED here

`app/playwright.visual.config.ts`:

- **`outputDir: './test-results-visual'`** — a sibling directory no **other** config cleans, so
  the raw `-actual` / `-diff` / `-expected` PNGs survive any later Playwright step **that uses a
  different config**.

  > **REFUTED wording, kept:** *"survive any later Playwright step."* Too wide. The REGEN step
  > (`e2e.yml`, "VISUAL baseline REGEN (`--update-snapshots`)") re-runs **this** config, so it
  > removes both `test-results-visual/` and `playwright-report/visual/`. **Measured cost: zero** —
  > the gate step requires `update_visual_baselines != 'true'` and REGEN requires `== 'true'`, so
  > the two are mutually exclusive and on a regen dispatch the gate never ran to produce a diff.
  > (This is narrower than the objection, which said the harm was merely "bounded".)

- **`reporter: [['list'], ['html', { outputFolder: 'playwright-report/visual', open: 'never' }]]`**
  — written *inside* `app/playwright-report/`, which the existing "Upload Playwright report" step
  **already** uploads with `always()`. A reporter only cleans its own `outputFolder`, so nothing
  else wipes it **today**.

  > **Trap flagged for the next editor** (now also in the source comment): Playwright's html
  > reporter **defaults** `outputFolder` to `playwright-report` — the *parent*. A future bare
  > `['html']` on `playwright.config.ts` would therefore clean `app/playwright-report/` wholesale
  > and take `visual/` with it, on steps that run *after* the visual gate. Measured: a second
  > config with the parent as its outputFolder left `report/visual/index.html` absent and `data/`
  > empty. A GUI report may only sit beside this one as an explicit
  > `['html', { outputFolder: 'playwright-report/gui' }]`.

`.github/workflows/e2e.yml` — **now editable: PR #408 MERGED as `5c80c79b`** (`gh pr view 408`
→ `state: MERGED`, and `castfix`'s `e2e.yml` blob is byte-identical to `origin/main`'s
`986f1d1b`, so no live branch competes for the file):

- **A dedicated `e2e-gui-visual-diff-${{ matrix.os }}` upload** (`!cancelled() && Windows`,
  `retention-days: 14`) carrying `app/test-results-visual/` + `app/playwright-report/visual/`.
  This is a **prerequisite, not an enhancement**, for raw-image access: no other step uploads
  `app/test-results-visual/`, so without it the named triples never leave the runner. The html
  report *is* reachable via the existing upload, but it stores the images as content-hashed
  copies under `data/`, not as `<name>-actual.png`.

  > **REFUTED wording, kept:** *"This patch is an **enhancement, not a prerequisite** — the landed
  > config change already makes the failure diagnosable through the existing
  > `app/playwright-report/` upload."* Correctly scoped: diagnosable **through the html report**,
  > yes; the **raw named triples** were unreachable from CI on every path until this step landed.

- **Per-invocation `--output` on the four Windows-leg `playwright.config.ts` steps** (20 packaged
  suite, 23 transcribe-journey, 24 add-videos-dialog, 26 installed-app) →
  `test-results/gui-<name>`. See the next section.

`.gitignore`: added `app/test-results-visual/` (the new `test-results/gui-*` subdirectories are
already covered by the existing `app/test-results/` entry).

**The load-bearing claim was verified executably, not assumed.** After the local run,
`app/playwright-report/visual/data/` holds 6 PNGs whose byte sizes match the two failures'
expected/actual/diff triples exactly (`133872 / 110707 / 112741` and `46754 / 58813 / 55539`).
The HTML reporter really does copy the diff triple into its own folder, so the report stays
complete even if `outputDir` is removed afterwards.

### The other half of the same defect: the GUI config (CONFIRMED, now fixed)

The root-cause sentence was *"neither Playwright config set `outputDir`, so both resolved to the
same `app/test-results/`"* — but the invariant actually violated is **"N Playwright invocations in
one job share one `outputDir`"**, and the first version of this lane fixed only the visual config.
`app/playwright.config.ts` still set none, and at `739ff6ed` **four** steps on the Windows leg
invoke it, all surviving a red (table above). Concrete live defect: on every nightly, if step 20 —
the largest suite (`confirm-scrim golden-journey overlay-hittest packaged preview installed-app`)
— goes red, steps 23 and 24 run afterwards and destroy its traces and `error-context.md` before
the `always()` upload. Pre-#408 the implicit `success()` chain masked this; #408 widened it from
dispatch-only to universal on the same day.

**The obvious one-liner does not fix it.** Giving `playwright.config.ts` a single different
`outputDir` (e.g. `./test-results-gui`) only *renames* the shared directory — all four invocations
would still clobber each other. Isolation has to be **per invocation**, which means the CLI, which
means `e2e.yml`.

Landed fix, and the both-states probe that chose it (`npx playwright test` ×2, planted markers,
Playwright 1.62.1):

| state | shape | marker after 2nd run |
|---|---|---|
| **X — control** | both runs share `outputDir=_probe_tr` | **False** — clobbered, so the probe measures something |
| **Y — proposed** | `_probe_tr/gui-a` and `_probe_tr/gui-b` | **True**, and the `_probe_tr/parent-level` marker also **True** |

`_probe_tr` afterwards held `['.last-run.json', 'gui-a', 'gui-b', 'parent-level']`. Playwright
removes **only** its own `outputDir` subtree, so per-invocation subdirectories *under*
`test-results/` isolate the four steps **and** need no change to the existing `app/test-results/`
upload path. Arg forwarding was verified in both shapes the workflow uses — `npx playwright test
--config <cfg> --output=<dir> <filter>` and `npm run <script> -- --output=<dir> <filter>` — each
against a control run with no `--output` that correctly landed in the config's own directory.

**UNVERIFIED — that these five `e2e.yml` changes behave as intended on a real runner.** `e2e.yml`
is `workflow_dispatch` + nightly cron only and gates no PR, so nothing in the `quality` gate
exercises it; the evidence above is local Playwright behaviour plus a YAML parse, not a CI run.
Settling experiment: dispatch `e2e.yml` on Windows and confirm the job produces an
`e2e-gui-visual-diff-windows-latest` artifact and that `app/test-results/` contains all four
`gui-*` subdirectories.

### The `e2e.yml` patch: it was MALFORMED, and it is now LANDED instead

> **REFUTED, kept:** this section previously shipped the upload step as a *"prepared unified
> diff"* under the heading `BLOCKED-ON-PR-408`, with residual #2's settling experiment reading
> *"after #408 merges, **apply the diff** and dispatch `e2e.yml`."* `docs/INDEX.md` advertised it
> as *"Carries the prepared `e2e.yml` upload patch."*
>
> **The diff would never have applied, at any base.** Measured against the committed blob
> (`git cat-file -p HEAD:docs/validation/w5-visual-artifacts.md`, so a later edit cannot change
> what is audited):
>
> ```text
> declared header : '@@ -699,6 +699,29 @@'
> measured body   : context=6 added=31 removed=0
>   => old-side must be 6   (declared 6)   OK      <- control: the counter is sound
>   => new-side must be 37  (declared 29)  MISMATCH
> file-headers present (--- a/ , +++ b/): False / False
> ```
>
> `git apply --check` therefore returns `error: corrupt patch at line 41`, exit 128, at **both**
> `81a04965` and `origin/main`; correcting only the count to `37` makes it apply cleanly at both.
> The old-side count being right is the control that isolates the defect to the new-side number.
> This was base-independent — not staleness. Three independent refuters reached the same
> arithmetic.

**Resolution: the step is no longer a patch.** PR #408 is `MERGED` (`5c80c79b`), so `e2e.yml` is
not owned by an open PR and the step is applied directly on this branch — see *What LANDED here*
above. There is no prepared diff to mis-apply, and the settling experiment is now a dispatch, not
a `git apply`.

---

## Deliverable 2 — why `workspace-preview-win32.png` drifted

### VERDICT: legitimate ACCUMULATED baseline drift, **not** a regression. Band: **almost certain (90-99%)**.

### Local reproduction is faithful to CI (this is the detector control)

`npm run test:e2e:visual` locally, `RF_E2E_DEV=1`, dev build. Playwright's stabilise loop prints
the diff at each attempt, giving three independent comparison points:

| attempt | CI (run 31445248586) | local (this box) | agreement |
|---|---|---|---|
| 1 | 132 573 px (0.13) | 132 557 px (0.13) | 0.01% |
| 2 | 135 064 px (0.13) | 135 051 px (0.13) | 0.01% |
| **stable** | **11 187 px (0.02)** | **11 060 px (0.02)** | 1.1% |

Threshold is `maxDiffPixelRatio: 0.01` over 1280×820 = **10 496 px**. CI is **691 px over** — a
6.6% overshoot. The reproduction is the same failure, not a lookalike.

**Honest scoping of the local run:** it failed **2** tests, not 1 — `settings-models-system` also
went red locally (14 711 px, 0.02) while it **passed** in CI. That one is this box's font/AA noise
and must not be reported as a CI finding. The three-stage numeric agreement above is what
licenses citing the `workspace-preview` local diff as CI-representative; no such agreement exists
for `settings-models-system`.

### What the diff image actually shows (inspected, not inferred)

Expected baseline tab strip: `SPEECH & TEXT · TRANSCRIBE · SEARCH · SUBTITLES · DIARIZE · REFINE ‖
FRAME & CUT · SHORT-MAKER · TIMELINE ‖ AUDIO · DUB ‖ DELIVER · CONV…` — running off the right
edge, **no Advanced toggle, no Export button**.

Actual, five structural deltas, all additive and coherent:

1. a new **`TRANSCRIPT EDIT`** tab between SUBTITLES and DIARIZE (label wraps to two lines, so the
   strip gets taller);
2. an **`ADVANCED ▸` disclosure + `Export` button** pinned at the strip's right edge;
3. a **horizontal scrollbar** under the tab clusters (they now scroll inside an inner tablist);
4. panel content shifted **down ~14 px** (`Subtitles` heading y=504 → y=518);
5. a new **`IMPORT SUBTITLE FILE`** + `Choose File` row in the Subtitles panel.

Nothing is clipped, overlapped, garbled or missing; the `Workspace preview — zero
serious/critical axe violations` a11y test passes in the same run.

### Which commits caused it (pinned with `git log -S`, each with a detector control)

Baseline last regenerated at **`27e7189b`** (2026-07-29). `WORKSPACE_TABS` held **13** entries
then; it holds **21** now (`Workspace.test.tsx:884`).

| delta | commit | detector control |
|---|---|---|
| `TRANSCRIPT EDIT` tab | **`fc5c3320`** feat(transcript-edit) … (#366) | needle present at `origin/main` ✓ |
| `IMPORT SUBTITLE FILE` row | **`2e715edd`** feat/v15 subtitle import (#359) | needle present at `origin/main` ✓ |
| tab strip → inner scrollport, `Export` pinned | **`8802e96d`** feat(workspace): mount ReframeOverridePanel + VideoTimeline (W17+W18) (#385) | needle present ✓ (`workspace.css:74-108`) |
| `ADVANCED ▸` becomes visible at all | **`3f981d17`** fix(workspace): scope the Advanced-cluster display rule (F17) | see below |
| select/fieldset token floor | `2380b160` fix(design-system) (H5) (#373) | needle present ✓ |

One probe was **void and is recorded as such**: the needle `ADVANCED` returned "needle is wrong"
from its own control (the label is uppercased by CSS, not in source), so that run proved nothing
and was re-done against `tabbar__advanced-toggle`.

### The decisive evidence: the baseline depicts a KNOWN-BROKEN state

`3f981d17`'s own commit message says the re-record was deliberately deferred:

> *"The visual baseline re-record is SKIPPED, not forgotten. The committed
> `workspace-preview-win32.png` **does depict the broken strip** (verified by eye:
> `... AUDIO | DUB | DELIVER | CONV`, no toggle, no Export), but the plan's premise that the
> visual gate 'WILL go red otherwise' is false: the fix moves ~7.4k px, under the
> `maxDiffPixelRatio: 0.01` tolerance (~10.5k px)…"*

That quoted strip — `AUDIO | DUB | DELIVER | CONV`, no toggle, no Export — is **exactly** what the
`-expected.png` I inspected shows. So:

- F17 knowingly parked ~7.4 k px of baseline debt because it fitted under the ~10.5 k px budget;
- `fc5c3320`, `2e715edd` and `8802e96d` then added more on top;
- cumulative drift reached **11 187 px**, crossing the budget by 691 px, and the gate finally
  went red.

The current render is **more correct than the baseline**, which still shows the F17 defect.

### Recommendation: REGEN via the workflow_dispatch — NOT a local `--update-snapshots`

Dispatch `e2e.yml` with `update_visual_baselines: true`, download the `updated-visual-baselines`
artifact, commit `workspace-preview-win32.png`.

This is not a style preference. `3f981d17` also measured that this exact baseline is **already
~50% flaky** — *"2 pass / 2 fail over 4 runs, delta 130,743 px = 13% of the image"* — because the
masked `<video>` box renders **280 px tall when its poster wins the load race and 150 px when it
loses**, and *"six consecutive re-records on this 16-agent-loaded box all captured the degraded
150px frame"*.

My run independently reproduces that race: attempts 1 and 2 measured ~132-135 k px (0.13 ≈ the
documented 130 743 px / 13%) before collapsing to 11 k px once the poster landed. **A regen taken
on a loaded box would bake in the 150 px frame and produce a reliably-red baseline** — which is
why it must be taken on the quiet CI visual runner, as F17 already concluded.

**UNVERIFIED:** that a dispatch regen on the GitHub Windows runner captures the 280 px frame
rather than the degraded 150 px one (F17 asserts the quiet runner is the right place but the
regen has not been run since). Settling experiment: dispatch `e2e.yml` with
`update_visual_baselines: true`, then diff the produced `workspace-preview-win32.png` against the
`-actual.png` in this run's artifacts — the masked magenta box must measure 280 px tall, and a
second dispatch must produce a byte-comparable PNG.

**Follow-up worth filing (not done here — out of lane):** the 0.13-vs-0.02 swing means this
baseline passes today only because Playwright's stabilise loop happens to retry until the poster
wins. Masking the whole `.workspace__player` rather than just the `video` element would remove the
race at its source.

---

## COVERAGE

Both deliverables measured. Deliverable 1's fix is landed and its key mechanism (html reporter
copies the diff triple) is executably verified. Deliverable 2's verdict rests on inspected pixels
plus a CI↔local three-point numeric agreement, not on git history alone.

**Corrections applied after adversarial review** (all recorded above, none deleted):

| # | what was wrong | status |
|---|---|---|
| 1 | *"Nightly … nothing clobbers … Diagnosable today"* and the *"regression … was avoided"* rationale | **REFUTED** — true at `81a04965`, false since #408 (`5c80c79b`). Re-measured at `739ff6ed`; clobber is universal on the Windows leg |
| 2 | *"neither config set `outputDir`"* fixed in only 1 of 2 configs | **DEFECT CONFIRMED and fixed** — four `playwright.config.ts` invocations shared one dir; each now has its own `test-results/gui-*`. The refuters' suggested single-`outputDir` one-liner is itself insufficient (it renames a shared dir) |
| 3 | *"a future GUI-suite report can sit beside it"* | **TRAP CONFIRMED** — the html reporter's default `outputFolder` is the *parent*; source comment now forbids a bare `['html']` |
| 4 | *"survive any later Playwright step"* | **REFUTED** — REGEN re-runs this config. Harm measured at **zero** (guards are mutually exclusive), narrower than the objection claimed |
| 5 | the *"prepared unified diff"* | **REFUTED** — hunk header declared 29 new-side lines against a measured 37, and had no file headers; never appliable at any base. Now landed as a real edit |
| 6 | *"enhancement, not a prerequisite"* | **REFUTED** — no step uploaded `app/test-results-visual/`, so the raw named triples were unreachable from CI on every path |

Two items remain open, each tagged UNVERIFIED inline above with its settling experiment: the
baseline **regen** itself, and whether the five `e2e.yml` changes behave as intended on a real
runner (`e2e.yml` gates no PR, so no gate here can exercise them).

One detector failure of my own, recorded: a first matcher keyed on the literal string
`playwright test` in a step's `run:` reported **3** `playwright.config.ts` invocations. It was
blind to `npm run test:e2e` wrappers and missed step 20 — the largest suite. The refuters' count
of **4** was right. The corrected matcher resolves `npm run <script>` through `app/package.json`;
it in turn over-matches (`test:e2e` is a prefix of `test:e2e:visual`), so steps 17/21/22 appear as
false hits in its raw output and were excluded by hand.
