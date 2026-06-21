# WU12 — Cross-cutting verification + PR readiness (gate WU)

**Status:** PASS — whole-bundle gate run green on `feat/repurpose-design`.
**Scope:** WU12 adds no feature source (PLAN §WU12: "No new source; CI/verification only").
This ledger records the falsifiable-acceptance results for the WU1–WU11 bundle.

## Falsifiable acceptance (PLAN §WU12)

1. **Sidecar `pytest --cov-branch --cov-fail-under=100` exits 0.** ✓
   `cd sidecar && python -m pytest --cov=media_studio --cov-branch --cov-fail-under=100`
   → `3256 passed`; `TOTAL 12071 0 3054 0 100%`; "Required test coverage of 100% reached."
   The three new modules at 100% line+branch: `batch.py` 370/120, `export_presets.py` 130/30,
   `templates.py` 123/46 (zero missed lines, zero missed branches).

2. **Renderer `vitest run --coverage` exits 0 (thresholds:100 met).** ✓
   `cd app && npx vitest run --coverage`
   → Statements 100% (8290/8290), Branches 100% (2836/2836), Functions 100% (514/514),
   Lines 100% (8290/8290). `Repurpose.tsx`, `BatchQueue.tsx`, `TemplateEditor.tsx`,
   `ExportPresetsPanel.tsx`, `BatchConsentCard.tsx`, `LiveStatusRegion.tsx`, `rpc.ts` all 100%.

3. **`git diff <main> -- sidecar/media_studio/handlers.py` shows ONLY additions inside
   `register_all` (no second registration site; no provider wiring).** ✓
   The only added blocks are the three module-owned `register()` calls
   (`_export_presets.register`, `_templates.register`, `_batch.register`) plus the
   `_video_title` title-seam helper the batch runner's progress line reuses. No provider,
   key, or `_run_ai_job` wiring is introduced — the single RPC composition root invariant holds.

4. **The three new feature modules contain no direct provider construction or key read.** ✓
   `grep -E "Provider|api_key|_run_ai_job\(|os\.environ|getenv"` over
   `export_presets.py`, `templates.py`, `batch.py` → zero matches. AI rides the envelope only
   by method name (`templates.apply` → recipe runner; consent via `ai.planJob` by name).

## Other standing gates (all green)

- `ruff check media_studio` → All checks passed; `ruff format --check media_studio tests` → all formatted.
- `basedpyright media_studio` → 0 errors (30 pre-existing torch/transformers missing-import
  warnings in unrelated ML-backend modules; not from this bundle; CI's bare `basedpyright` exits 0).
- `tsc --noEmit` (app) and `tsc -p . --noEmit` (render-cli) → clean.
- `biome 2.5.0 format` (format-only gate; `biome.json` has `linter.enabled:false`) over
  `app/{main,renderer/src,render-cli/src}` → "Checked 163 files. No fixes applied."
- `oxlint --config app/.oxlintrc.json --deny-warnings` → clean (exit 0).

> Note: a Windows checkout with `core.autocrlf=true` makes biome-format report CRLF diffs;
> the committed code is LF (verified against a pristine `core.autocrlf=false` clone, where
> biome-format applies zero fixes). CI runs on Ubuntu (LF), so the gate is green upstream.
