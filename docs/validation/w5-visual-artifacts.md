# Lane VISUAL — make a visual regression diagnosable + diagnose `workspace-preview`

> **Status:** ACTIVE

**Branch:** `ci/v15-w5-visual-artifacts` · **Base:** `origin/main` @ `81a04965`
Both deliverables measured.

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

### Scope of the defect — narrower than "always broken"

- **Nightly / plain dispatch, visual red:** steps 25-28 all skip (implicit `success()` gate; 27/28
  are dispatch-only), nothing clobbers, PNGs upload. Diagnosable today.
- **Dispatch with `drive_installed_build=true`, visual red:** step 28 runs and clobbers. **Not**
  diagnosable. That is run 31445248586.

This matters: a naive "move outputDir and let PR #408 add the upload later" would have been a
**regression** for the nightly case. It was avoided — see below.

### What LANDED here (no `e2e.yml` edit — PR #408 owns that file)

`app/playwright.visual.config.ts`:

- **`outputDir: './test-results-visual'`** — a sibling directory no other config cleans, so the
  raw `-actual` / `-diff` / `-expected` PNGs survive any later Playwright step.
- **`reporter: [['list'], ['html', { outputFolder: 'playwright-report/visual', open: 'never' }]]`**
  — written *inside* `app/playwright-report/`, which `e2e.yml:707` **already** uploads with
  `always()`. So this is diagnosable **with zero workflow change**, and it also survives the
  clobber (nothing else configures an html reporter, and a reporter only cleans its own
  `outputFolder`).

`.gitignore`: added `app/test-results-visual/`.

**The load-bearing claim was verified executably, not assumed.** After the local run,
`app/playwright-report/visual/data/` holds 6 PNGs whose byte sizes match the two failures'
expected/actual/diff triples exactly (`133872 / 110707 / 112741` and `46754 / 58813 / 55539`).
The HTML reporter really does copy the diff triple into its own folder, so the report stays
complete even if `outputDir` is removed afterwards.

Net effect vs today: **strictly better, no interim regression** — the images reach the artifact in
both the nightly and the clobber scenario, before PR #408 lands anything.

### BLOCKED-ON-PR-408 — the `e2e.yml` patch (prepared, NOT applied)

`.github/workflows/e2e.yml` is owned by open PR #408, so this is a patch, not an edit. It adds the
raw per-test directory and a self-describing artifact name. Insert between the existing
"Upload regenerated visual baselines" and "Upload Playwright report" steps (currently `:700`):

```diff
@@ -699,6 +699,29 @@
           if-no-files-found: warn
           retention-days: 7
 
+      # VISUAL diagnostics, SEPARATE from the general report upload below.
+      #
+      # A screenshot-diff failure is the one class that is useless without the
+      # images, and until now they never survived to the artifact: both Playwright
+      # configs left `outputDir` at the default `app/test-results/`, and Playwright
+      # DELETES outputDir at the start of every run — so the `installed-app` step
+      # above (which carries `!cancelled()` and therefore runs after a red visual
+      # gate) wiped them. MEASURED on run 31445248586: the uploaded
+      # `e2e-gui-playwright-report-windows-latest` artifact contained ZERO png
+      # files, only two `error-context.md`, both from `installed-app`.
+      #
+      # playwright.visual.config.ts now writes to its own `test-results-visual/`
+      # (clobber-proof) and emits an html report under `playwright-report/visual/`
+      # that embeds the expected/actual/diff triple as copied attachments.
+      #
+      # `!cancelled()` rather than `always()`, matching the visual gate step itself:
+      # it MUST upload when that gate goes red (the entire point), but a cancelled
+      # run has no diff worth keeping. Windows-only because the suite is.
+      - name: Upload VISUAL screenshot-diff diagnostics (actual + diff + html report)
+        if: ${{ !cancelled() && runner.os == 'Windows' }}
+        uses: actions/upload-artifact@330a01c490aca151604b8cf639adc76d48f6c5d4 # v5.0.0
+        with:
+          name: e2e-gui-visual-diff-${{ matrix.os }}
+          path: |
+            app/test-results-visual/
+            app/playwright-report/visual/
+          if-no-files-found: ignore
+          # Longer than the 7 days the other uploads use: deciding "drift or
+          # regression" on a nightly needs the images to outlive a weekend.
+          retention-days: 14
+
       - name: Upload Playwright report
         if: always()
         uses: actions/upload-artifact@330a01c490aca151604b8cf639adc76d48f6c5d4 # v5.0.0
```

This patch is an **enhancement, not a prerequisite** — the landed config change already makes the
failure diagnosable through the existing `app/playwright-report/` upload.

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
plus a CI↔local three-point numeric agreement, not on git history alone. The one open item is the
regen itself, tagged UNVERIFIED inline above with its settling experiment.
