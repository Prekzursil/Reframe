# Reframe Next Big Phase Release Notes (Draft) - 2026-03-01

## Highlights

- Enterprise access and org security surfaces expanded:
  - organization membership management
  - API key lifecycle endpoints
  - audit-event feed endpoint

- Creator workflow expansion shipped:
  - workflow template creation/listing
  - workflow run creation/status/cancel APIs
  - worker-side orchestrated pipeline dispatch

- Performance and cost visibility improvements:
  - usage ledger model integration
  - usage-cost summary endpoint
  - dedicated perf/cost smoke gate

- Operational quality improvements:
  - deterministic branch-protection audit workflow with policy source file
  - consolidated weekly ops digest workflow with rolling issue updates
  - release-readiness reporting hardened for stamp drift in updater evidence

## Validation Snapshot

- Required PR check contexts are green for PR `#87` head `72a158f`.
- SonarCloud is green.
- Diarization benchmark workflow is green (`cpu ok`, `gpu skipped`).
- Release Readiness workflow rerun is green after report fallback fix.

## Known Non-Blocking Items

- Codacy check remains `ACTION_REQUIRED` (currently not in required branch-protection contexts).
- PR merge requires one external approving review due branch protection policy.

## Recommended Merge Steps

1. Obtain one approving review from a writer/admin.
2. Merge PR `#87` into `main`.
3. Dispatch post-merge `release-readiness.yml` on `main` and archive artifact links.
4. Close/triage follow-up issues (`#83`, `#64`, `#66`) using merged evidence.

