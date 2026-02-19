# KPI Digest Testing Guide

## Overview

This guide provides instructions for testing the KPI digest automation to ensure it correctly collects metrics, generates reports, and stores historical data.

## Prerequisites

- Repository with at least some merged PRs and closed issues
- GitHub Actions enabled
- Write access to the repository

## Test Scenarios

### 1. Manual Workflow Trigger

**Purpose**: Verify the workflow runs successfully on demand.

**Steps**:
1. Navigate to Actions tab in GitHub
2. Select "Weekly KPI Digest" workflow
3. Click "Run workflow" dropdown
4. Select branch (usually `main`)
5. Click "Run workflow" button

**Expected Results**:
- Workflow starts within 30 seconds
- All steps complete successfully (green checkmarks)
- New file created in `.github/kpi-reports/YYYY-WWW.json`
- Summary printed in workflow output

**Validation**:
```bash
# Check if report file was created
ls -la .github/kpi-reports/

# View the report content
cat .github/kpi-reports/2026-W08.json
```

### 2. Metric Calculation Accuracy

**Purpose**: Verify metrics are calculated correctly.

**Test Data Setup**:
Create test data with known values:
- Merge 2 PRs with different cycle times
- Close 1 issue with known lead time
- Run CI workflow and note pass/fail status

**Steps**:
1. Record expected values:
   - Average PR cycle time = (time1 + time2) / 2
   - Average issue lead time = time3
   - CI failure rate = failed_runs / total_runs * 100
2. Run KPI digest workflow
3. Compare calculated values with expected

**Validation**:
```bash
# Extract metrics from report
cat .github/kpi-reports/2026-W08.json | jq '.cycle_time.average_hours'
cat .github/kpi-reports/2026-W08.json | jq '.lead_time.average_days'
cat .github/kpi-reports/2026-W08.json | jq '.failure_rate.ci_failure_percent'
```

**Expected Results**:
- Metrics match manual calculations (±1% for rounding)
- Status indicators correct (green/yellow/red)

### 3. Report Storage

**Purpose**: Verify reports are stored and committed correctly.

**Steps**:
1. Run workflow multiple times on different days
2. Check `.github/kpi-reports/` directory

**Expected Results**:
- One JSON file per week (YYYY-WWW.json format)
- Files are committed to the repository
- Git history shows automated commits by `github-actions[bot]`

**Validation**:
```bash
# List all KPI reports
ls -l .github/kpi-reports/

# Check git log for automated commits
git log --author="github-actions[bot]" --grep="KPI report" --oneline
```

### 4. Summary Generation

**Purpose**: Verify human-readable summary is generated.

**Steps**:
1. Run workflow
2. Check workflow output logs
3. Look for summary section

**Expected Results**:
- Summary includes all metric categories
- Status emojis display correctly (✅, ⚠️, ❌)
- Targets and actual values shown
- Health status assessment included

**Validation**:
- Review "Generate Digest Summary" step output in Actions UI
- Verify markdown formatting is correct
- Check that status emojis match metric status

### 5. Time Window Filtering

**Purpose**: Verify metrics only include data from the specified week.

**Test Setup**:
- Create PRs and issues with known timestamps
- Some within last week, some older

**Steps**:
1. Run workflow
2. Check which items were included in counts

**Expected Results**:
- Only items from last 7 days included in metrics
- Older items correctly excluded

**Validation**:
```bash
# Check activity count in report
cat .github/kpi-reports/2026-W08.json | jq '.summary'

# Compare with actual merged PRs in last week
gh pr list --state merged --search "merged:>=$(date -d '7 days ago' +%Y-%m-%d)" --json number --jq 'length'
```

### 6. Edge Cases

#### 6a. No Activity Week

**Setup**: Test on a repository with no recent activity

**Expected Results**:
- Workflow completes successfully
- Metrics show 0 counts
- Averages show 0 or N/A
- No errors in workflow logs

#### 6b. High Activity Week

**Setup**: Week with 50+ PRs (if available)

**Expected Results**:
- Workflow handles pagination correctly
- All PRs counted (not just first 100)
- Performance acceptable (<5 minutes)

#### 6c. Failed CI Runs Only

**Setup**: Week where all CI runs on main failed

**Expected Results**:
- Failure rate = 100%
- Status = Red
- No division by zero errors

### 7. Schedule Trigger

**Purpose**: Verify workflow runs automatically on schedule.

**Note**: This test requires waiting for the scheduled time (Monday 9 AM UTC).

**Steps**:
1. Ensure workflow file is on main branch
2. Wait for next Monday 9:00 AM UTC
3. Check Actions tab for automatic run

**Expected Results**:
- Workflow triggers automatically at scheduled time
- Completes successfully
- New report generated

**Alternative Test** (without waiting):
Temporarily modify schedule to run in 5 minutes:
```yaml
schedule:
  - cron: '*/5 * * * *'  # Every 5 minutes for testing
```
Commit, push, wait, then revert.

### 8. Error Handling

**Purpose**: Verify graceful handling of errors.

#### 8a. GitHub API Rate Limit

**Simulation**: Run workflow many times in quick succession

**Expected Results**:
- Workflow shows rate limit error
- Does not corrupt existing reports
- Retries or fails gracefully

#### 8b. Missing Permissions

**Simulation**: Remove write permissions temporarily

**Expected Results**:
- Workflow logs clear error message
- No partial files committed

### 9. Historical Trends

**Purpose**: Verify multiple reports can be compared over time.

**Steps**:
1. Generate reports for multiple weeks
2. Compare metrics week-over-week

**Expected Results**:
- Each week's report is independent
- Trends can be identified manually or via script
- No data corruption between reports

**Validation Script**:
```bash
#!/bin/bash
# Compare last 4 weeks of cycle time
for report in .github/kpi-reports/*.json; do
  week=$(basename "$report" .json)
  cycle_time=$(cat "$report" | jq -r '.cycle_time.average_hours')
  echo "$week: $cycle_time hours"
done
```

## Integration Testing

### Full Workflow Integration

**Steps**:
1. Create a test PR
2. Merge the PR
3. Wait 1 hour (for indexing)
4. Run KPI digest workflow
5. Verify test PR appears in metrics

**Expected Results**:
- PR counted in merged PR total
- Cycle time includes test PR
- Status checks reflected in failure rate

## Performance Testing

**Metrics to Monitor**:
- Workflow execution time (target: <2 minutes)
- API calls made (should be efficient, not excessive)
- Memory usage (should be minimal)

**Test on Different Scales**:
- Small repo (10 PRs/week)
- Medium repo (50 PRs/week)
- Large repo (200+ PRs/week)

## Troubleshooting

### Common Issues

#### Issue: Workflow fails with "Resource not accessible by integration"
**Solution**: Check workflow permissions in workflow file:
```yaml
permissions:
  contents: write
  issues: read
  pull-requests: read
```

#### Issue: No reports generated
**Solution**: 
- Check workflow logs for errors
- Verify `.github/kpi-reports/` directory exists
- Ensure git config in workflow is correct

#### Issue: Metrics are 0 despite activity
**Solution**:
- Verify date filtering logic
- Check that PRs are actually merged (not just closed)
- Ensure issue query excludes PRs

#### Issue: Wrong week number in filename
**Solution**:
- ISO week calculation may differ from calendar week
- This is expected and correct per ISO 8601 standard

## Continuous Testing

### Recommended Testing Cadence

- **Daily**: Monitor scheduled runs (once deployed)
- **Weekly**: Review report accuracy
- **Monthly**: Audit historical data
- **Quarterly**: Performance and scalability review

### Automated Tests

Consider adding these automated checks:

1. **Schema Validation**
   ```bash
   # Validate JSON structure
   cat .github/kpi-reports/latest.json | jq . > /dev/null
   ```

2. **Threshold Alerts**
   ```bash
   # Alert if failure rate exceeds 20%
   failure_rate=$(cat report.json | jq -r '.failure_rate.ci_failure_percent')
   if (( $(echo "$failure_rate > 20" | bc -l) )); then
     echo "ALERT: High failure rate!"
   fi
   ```

3. **Report Completeness**
   ```bash
   # Ensure all expected fields present
   required_fields=("cycle_time" "lead_time" "failure_rate" "rework_rate")
   for field in "${required_fields[@]}"; do
     if ! jq -e ".$field" report.json > /dev/null; then
       echo "ERROR: Missing field $field"
     fi
   done
   ```

## Success Criteria

The KPI digest workflow is considered fully tested and ready for production when:

- ✅ Manual trigger works consistently
- ✅ Metrics calculated accurately (validated against known data)
- ✅ Reports stored correctly in git
- ✅ Summary generates readable output
- ✅ Scheduled trigger works (verified for 2+ weeks)
- ✅ Edge cases handled gracefully
- ✅ Performance acceptable for expected repository size
- ✅ Documentation complete and accurate

## References

- Workflow file: `.github/workflows/kpi-digest.yml`
- Metrics definitions: `docs/KPI_METRICS.md`
- GitHub Actions documentation: https://docs.github.com/en/actions
