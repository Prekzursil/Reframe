# Regression Tracking Log

This directory contains regression logs for each monorepo slice. Regressions are tracked separately by slice to enable focused accountability and faster resolution.

## Structure

Each slice maintains its own regression log:
- `api-regressions.md` - Backend API slice
- `web-regressions.md` - Frontend slice
- `worker-regressions.md` - Background worker slice
- `media-core-regressions.md` - Core library slice
- `infra-regressions.md` - Infrastructure/CI/tooling slice

## Regression Entry Format

```markdown
### [YYYY-MM-DD] Regression Title
- **Severity**: P0 | P1 | P2 | P3
- **Introduced in**: PR #123, commit abc1234
- **Detected by**: CI | Manual | User report
- **Impact**: Brief description of the regression
- **Root cause**: Brief explanation
- **Resolution**: PR #456, commit def5678
- **Time to resolve**: X hours/days
- **Status**: Open | Resolved | Wont-Fix
```

## Severity Levels

- **P0 (Critical)**: System down, data loss, security breach
  - Target resolution: 2 hours
  - Requires immediate revert or hotfix

- **P1 (High)**: Major feature broken, significant performance degradation
  - Target resolution: 24 hours
  - May require revert if fix not ready

- **P2 (Medium)**: Minor feature broken, moderate performance impact
  - Target resolution: 1 week
  - Scheduled in next sprint

- **P3 (Low)**: Cosmetic issue, edge case
  - Target resolution: Next sprint or backlog
  - May be deferred

## Tracking Process

1. When a regression is detected:
   - Create entry in appropriate slice log
   - Set severity and status
   - Link to detection issue/PR

2. During resolution:
   - Update status with progress notes
   - Link to resolution PR

3. After resolution:
   - Update with resolution details
   - Calculate time to resolve
   - Mark status as Resolved

4. Weekly review:
   - Review open regressions
   - Escalate overdue items
   - Report in KPI digest

## Prevention

Lessons learned from regressions should be:
- Added to test suite
- Documented in architecture decisions
- Shared in team retrospectives
- Used to improve CI/CD coverage
