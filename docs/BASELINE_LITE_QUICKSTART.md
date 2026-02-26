# Baseline-Lite Quick Start Guide

## What is Baseline-Lite?

Baseline-Lite is a governance and infrastructure bundle extracted from the Reframe project. It provides battle-tested patterns for:
- ✅ Code quality enforcement
- ✅ Automated CI/CD pipelines
- ✅ Development metrics tracking
- ✅ Branch protection policies
- ✅ Agent-assisted development workflows

## 5-Minute Quick Start

### For New Repository Setup

```bash
# 1. Clone this repository as a template
git clone https://github.com/Prekzursil/Reframe baseline-lite-template
cd baseline-lite-template

# 2. Copy baseline components to your new repo
NEW_REPO="/path/to/your/new/repo"

# Copy core governance
cp AGENTS.md ARCHITECTURE.md "$NEW_REPO/"
cp Makefile "$NEW_REPO/"
cp .pre-commit-config.yaml "$NEW_REPO/"

# Copy GitHub workflows
cp -r .github/workflows/* "$NEW_REPO/.github/workflows/"
cp -r .github/ISSUE_TEMPLATE "$NEW_REPO/.github/"
cp .github/pull_request_template.md "$NEW_REPO/.github/"

# Copy documentation
mkdir -p "$NEW_REPO/docs"
cp -r docs/* "$NEW_REPO/docs/"

# 3. Customize for your project
cd "$NEW_REPO"

# Edit AGENTS.md: Update verification command
sed -i 's/make verify/your-verify-command/' AGENTS.md

# Edit Makefile: Add your project targets
# (Edit manually based on your tech stack)

# 4. Set up GitHub settings
gh repo view --web  # Opens GitHub settings page

# Navigate to Settings → Branches → Add rule
# - Branch name pattern: main
# - Enable: Require pull request reviews (1 approval)
# - Enable: Require status checks (add your CI job names)
# - Enable: Require conversation resolution
# - Enable: Require linear history

# 5. Initialize labels
gh workflow run agent-label-sync.yml

# 6. Test the setup
# Create a test PR to verify CI runs and protection works
```

### For Existing Repository

```bash
# 1. Create governance branch
cd /path/to/your/repo
git checkout -b add-baseline-lite

# 2. Copy selected components
# (Use the same cp commands as above)

# 3. Commit and create PR
git add .
git commit -m "Add Baseline-Lite governance"
git push -u origin add-baseline-lite
gh pr create --title "Add Baseline-Lite governance" --body "Adds governance, CI/CD, and quality patterns from Reframe"

# 4. After merge, configure branch protection
# (Follow step 4 from above)
```

## Component Selection Guide

Not all projects need all components. Choose what fits your needs:

### Minimal Setup (All Projects)
- ✅ `AGENTS.md` - Operating model
- ✅ `.github/workflows/ci.yml` - Basic CI
- ✅ `docs/BRANCH_PROTECTION.md` - Protection policy
- ✅ `.github/pull_request_template.md` - PR template

### Standard Setup (Most Projects)
- ✅ Everything from Minimal
- ✅ `docs/KPI_METRICS.md` - Development metrics
- ✅ `.github/workflows/kpi-digest.yml` - Metric tracking
- ✅ `.pre-commit-config.yaml` - Code quality hooks
- ✅ `Makefile` - Task automation

### Full Setup (Monorepos & Large Teams)
- ✅ Everything from Standard
- ✅ `ARCHITECTURE.md` - Slice ownership
- ✅ `docs/regressions/` - Regression tracking
- ✅ `.github/workflows/agent-task-queue.yml` - Agent automation
- ✅ `docs/BASELINE_LITE_PACKAGE.md` - Full documentation

## Customization Checklist

After copying files, customize these items:

### AGENTS.md
- [ ] Update `make verify` command to match your project
- [ ] Adjust slice definitions if not using monorepo
- [ ] Modify risk policy if needed

### ARCHITECTURE.md
- [ ] Replace directory structure with your layout
- [ ] Define your project's slices
- [ ] Document dependencies between components

### Makefile
- [ ] Add install targets for your dependencies
- [ ] Add dev server targets
- [ ] Configure test runners
- [ ] Update verify target

### .github/workflows/ci.yml
- [ ] Adjust language versions (Python, Node, etc.)
- [ ] Add or remove language-specific jobs
- [ ] Configure required checks
- [ ] Set up caching strategies

### docs/KPI_METRICS.md
- [ ] Adjust target values for your team
- [ ] Add project-specific metrics
- [ ] Remove irrelevant metrics

### docs/BRANCH_PROTECTION.md
- [ ] Verify required checks match your CI jobs
- [ ] Adjust approval count if needed
- [ ] Customize review checklist

## Testing Your Setup

### 1. Test CI Pipeline
```bash
# Create a test branch with a dummy change
git checkout -b test-ci
echo "# Test" >> README.md
git add README.md
git commit -m "test: verify CI runs"
git push -u origin test-ci

# Create PR and verify CI runs
gh pr create --title "Test CI" --body "Testing CI setup"

# Check that required checks appear
gh pr checks
```

### 2. Test Branch Protection
```bash
# Try to push directly to main (should fail)
git checkout main
git pull
echo "direct push test" >> test.txt
git add test.txt
git commit -m "test: direct push"
git push  # Should be rejected

# Verify rejection message mentions protection
```

### 3. Test Pre-commit Hooks
```bash
# Install pre-commit
pip install pre-commit
pre-commit install

# Make a change and commit
echo "test" >> file.py
git add file.py
git commit -m "test"  # Hooks should run
```

### 4. Test KPI Digest (Manual Run)
```bash
# Trigger workflow manually
gh workflow run kpi-digest.yml

# Wait a moment, then check run
gh run list --workflow=kpi-digest.yml

# View output
gh run view --log
```

## Common Customizations

### Python-Only Project
Remove Node.js job from `ci.yml`:
```yaml
jobs:
  python:
    # ... keep this
  
  # web:
  #   # ... delete this job
```

### JavaScript-Only Project
Remove Python job from `ci.yml`:
```yaml
jobs:
  # python:
  #   # ... delete this job
  
  web:
    # ... keep this
```

### Microservices (Multiple Repos)
For each service repo:
1. Copy Minimal Setup components
2. Skip `ARCHITECTURE.md` (not needed for single service)
3. Simplify `Makefile` (no cross-slice targets needed)
4. Use same branch protection and KPI setup

### Monorepo
Use Full Setup:
1. Document all slices in `ARCHITECTURE.md`
2. Add path-based workflow triggers in `ci.yml`
3. Track regressions per slice
4. Consider CODEOWNERS file for slice owners

## Verification

After setup, verify these work:

- [ ] CI runs on pull requests
- [ ] Branch protection blocks direct pushes to main
- [ ] Required checks must pass before merge
- [ ] Pre-commit hooks run locally
- [ ] KPI digest generates reports
- [ ] Agent task queue responds to labels (if using agents)
- [ ] Pull request template appears on new PRs
- [ ] Issue templates available when creating issues

## Troubleshooting

### CI doesn't run on PRs
**Solution**: Check workflow trigger in `.github/workflows/ci.yml`:
```yaml
on:
  pull_request:
    branches: [main]
```

### Can still push to main despite protection
**Solution**: 
1. Verify branch protection is saved in GitHub settings
2. Check "Include administrators" is enabled
3. Confirm branch name exactly matches "main"

### Pre-commit hooks not running
**Solution**:
```bash
pre-commit install  # Re-install hooks
pre-commit run --all-files  # Test manually
```

### KPI digest fails
**Solution**:
1. Check workflow has required permissions
2. Verify GitHub token has access
3. Ensure `.github/kpi-reports/` directory exists

## Next Steps

Once baseline-lite is set up:

1. **Train the team**
   - Review governance documents together
   - Walk through PR process
   - Explain KPI metrics and goals

2. **Establish cadence**
   - Weekly KPI review meetings
   - Monthly retrospectives
   - Quarterly policy updates

3. **Customize over time**
   - Add project-specific checks
   - Adjust thresholds based on data
   - Evolve as team grows

4. **Share improvements**
   - Document what works well
   - Contribute back to Reframe if valuable
   - Help other teams adopt

## Support

- 📖 Full documentation: `docs/BASELINE_LITE_PACKAGE.md`
- 🐛 Issues: Open issue in Reframe repository
- 💬 Questions: Use GitHub Discussions

## License

Baseline-Lite components are provided under the same license as Reframe. Free to use, modify, and redistribute with attribution.
