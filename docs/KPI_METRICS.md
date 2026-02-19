# KPI Metrics for Reframe

## Overview
This document defines the Key Performance Indicators (KPIs) for tracking development velocity, quality, and operational health in the Reframe monorepo.

## Metric Categories

### 1. Cycle Time Metrics

**Definition**: Time from work start to production deployment.

- **PR Cycle Time**: Time from PR creation to merge
  - Target: < 24 hours for low-risk changes
  - Target: < 48 hours for medium-risk changes
  - Target: < 72 hours for high-risk changes
- **Issue Cycle Time**: Time from issue creation to closure
  - Target: < 7 days for bugs
  - Target: < 14 days for features

### 2. Lead Time Metrics

**Definition**: Time from issue creation to production deployment.

- **Feature Lead Time**: Issue creation → deployment
  - Target: < 21 days for standard features
- **Bug Lead Time**: Bug report → fix deployed
  - Target: < 3 days for critical bugs
  - Target: < 7 days for high-priority bugs
  - Target: < 14 days for normal bugs

### 3. Rework Rate

**Definition**: Percentage of changes requiring post-merge corrections.

- **Post-Merge Fixes**: PRs that fix issues introduced in the last 30 days
  - Target: < 10% of total merged PRs
- **Revert Rate**: PRs that are reverted
  - Target: < 2% of total merged PRs

### 4. Failure Rate

**Definition**: Frequency of CI/CD and deployment failures.

- **CI Failure Rate**: Failed CI runs / total CI runs
  - Target: < 5% for main branch
  - Target: < 15% for PRs (acceptable for WIP)
- **Build Failure Rate**: Failed builds / total builds
  - Target: < 3% for main branch
- **Deployment Failure Rate**: Failed deployments / total deployments
  - Target: < 2% (with automatic rollback)

### 5. Evidence Metrics

**Definition**: Quality and completeness of change documentation.

- **PR Description Completeness**: % of PRs with all required sections
  - Required: Summary, Risk, Evidence, Rollback, Scope Guard
  - Target: 100% for medium and high-risk changes
- **Test Coverage**: % of code covered by tests
  - Target: > 70% for packages/media-core
  - Target: > 60% for apps/api
  - Target: > 50% for apps/web
- **Documentation Coverage**: % of features with documentation
  - Target: 100% for public APIs
  - Target: > 80% for internal modules

## Slice-Specific Metrics

### API Slice (`apps/api`)
- API endpoint latency (p50, p95, p99)
- API error rate by endpoint
- Database query performance

### Web Slice (`apps/web`)
- Bundle size (target: < 500KB gzipped)
- First contentful paint (target: < 2s)
- JavaScript error rate

### Worker Slice (`services/worker`)
- Job processing time by job type
- Job failure rate by type
- Queue depth and wait time

### Core Library (`packages/media-core`)
- Function execution time for media operations
- Memory usage for large files
- Algorithm accuracy metrics (transcription WER, etc.)

## Regression Tracking

### Definition
A regression is any decrease in quality, performance, or functionality introduced in a change.

### Tracking Methodology

1. **Automated Detection**
   - Performance regression: > 10% increase in execution time
   - Quality regression: > 5% decrease in test pass rate
   - Coverage regression: > 2% decrease in test coverage

2. **Manual Detection**
   - User-reported bugs with "regression" label
   - CI failures on main branch
   - Reverted commits

3. **Slice-Specific Tracking**
   - Each slice maintains a regression log in `docs/regressions/{slice}-regressions.md`
   - Regressions are categorized by severity (P0-P3)
   - Resolution time is tracked per severity level

### Regression Response

- **P0 (Critical)**: Immediate revert or hotfix within 2 hours
- **P1 (High)**: Fix within 24 hours
- **P2 (Medium)**: Fix within 1 week
- **P3 (Low)**: Fix in next sprint

## Data Collection

### Automated Collection

KPI data is collected from:
- GitHub API (PR and issue metadata)
- GitHub Actions (CI/CD run data)
- Code coverage tools (pytest-cov, vitest coverage)
- Git history (commit metadata)

### Storage

- Weekly aggregated metrics stored in `.github/kpi-reports/YYYY-WW.json`
- Historical trends accessible via KPI dashboard

### Privacy

- No personally identifiable information stored
- Focus on aggregate team metrics, not individual performance

## Reporting

### Weekly KPI Digest

Generated every Monday via GitHub Actions workflow:
- Summary of key metrics vs. targets
- Trend analysis (week-over-week, month-over-month)
- Top 3 improvements and concerns
- Recommended actions

### Monthly Review

- Comprehensive report with all metrics
- Slice-specific deep dives
- Retrospective and action items

## Thresholds and Alerts

### Red Alerts (Immediate Action Required)
- CI failure rate on main > 10%
- Revert rate > 5%
- P0 regression unresolved > 2 hours

### Yellow Alerts (Monitor Closely)
- PR cycle time > 72 hours (3-day SLA breach)
- Test coverage drop > 5%
- Rework rate > 15%

### Green (Healthy)
- All metrics within target ranges
- Improving trends over last 4 weeks

## Continuous Improvement

This KPI framework is reviewed quarterly and updated based on:
- Team feedback and pain points
- Industry benchmarks
- Evolving project needs
- New slice additions or architecture changes
