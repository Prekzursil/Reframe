# Quality Gates Baseline (2026-03-03)

## Source
- Baseline commit: `origin/main@8c7f5f1`
- Captured before quality-gate expansion changes.

## Branch protection contexts on main
- `Python API & worker checks`
- `Web build`
- `Analyze (actions)`
- `Analyze (javascript-typescript)`
- `Analyze (python)`
- `CodeQL`
- `CodeRabbit`

## SonarCloud main signal
- Context: `SonarCloud Code Analysis`
- Conclusion: `failure`
- Summary: quality gate failed due `C Reliability Rating on New Code` (required >= A).

## Codacy PR signal format
- Context: `Codacy Static Code Analysis`
- Summary shape observed on PR: `39 new issues (0 max.)`.
- Current signal is issue-delta oriented; total-open zero enforcement is added by repository-owned gate scripts.

## DeepScan signal pattern
- Context: `DeepScan` (status context)
- Description shape observed: `0 new and 0 fixed issues`.
- Repository-owned strict gate now requires total-open evidence (`DEEPSCAN_OPEN_ISSUES_URL`) and fails closed if unavailable.
