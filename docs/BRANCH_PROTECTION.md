# Branch Protection Policy

## Overview
This document defines the branch protection requirements for the Reframe repository to ensure code quality, prevent accidental commits, and enforce proper review processes.

## Protected Branches

### `main` Branch

The `main` branch is the primary production branch and has the strictest protection rules.

#### Required Protections

1. **Require Pull Request Reviews Before Merging**
   - **Required approving reviews**: 1
   - **Dismiss stale pull request approvals when new commits are pushed**: Yes
   - **Require review from Code Owners**: No (optional, can be enabled when CODEOWNERS file is added)
   - **Restrict who can dismiss pull request reviews**: Maintainers only

2. **Require Status Checks Before Merging**
   - **Require branches to be up to date before merging**: Yes
   - **Required status checks**:
     - `python / Python API & worker checks` - Validates Python code compilation and tests
     - `web / Web build` - Ensures frontend builds successfully

3. **Require Conversation Resolution Before Merging**
   - All review comments must be resolved before merge
   - Ensures all feedback is addressed

4. **Require Signed Commits**
   - Optional but recommended for enhanced security
   - Can be enabled in later phases

5. **Require Linear History**
   - **Enabled**: Yes
   - Prevents merge commits, enforces squash or rebase
   - Keeps history clean and easy to navigate

6. **Include Administrators**
   - Administrators must also follow these rules
   - No exceptions for protection bypassing

7. **Restrict Pushes**
   - **No direct pushes to main**
   - All changes must go through pull requests
   - Only allows merges via approved PRs

8. **Allow Force Pushes**
   - **Disabled**: Force pushes not allowed
   - Protects against accidental history rewriting

9. **Allow Deletions**
   - **Disabled**: Branch cannot be deleted
   - Permanent protection of main branch

### Feature Branches

Feature branches follow a naming convention and have lighter protections:

#### Naming Convention
- `feature/*` - New features
- `fix/*` - Bug fixes
- `chore/*` - Maintenance tasks
- `docs/*` - Documentation changes
- `copilot/*` - Agent-generated changes

#### Protections
- No direct protection rules
- Expected to have passing CI before merge to main
- Should be deleted after merge to keep repository clean

## Required Checks in Detail

### 1. Python API & Worker Checks

**Job Name**: `python`  
**Workflow**: `.github/workflows/ci.yml`

**Steps**:
1. Checkout code
2. Set up Python 3.11
3. Install dependencies from:
   - `apps/api/requirements.txt`
   - `services/worker/requirements.txt`
4. Run syntax check:
   ```bash
   python -m compileall apps/api services/worker packages/media-core
   ```
5. Run tests:
   ```bash
   PYTHONPATH=.:apps/api:packages/media-core/src python -m pytest apps/api/tests services/worker packages/media-core/tests
   ```

**Success Criteria**:
- All Python files compile without syntax errors
- All tests pass
- Exit code 0

**Failure Handling**:
- PR cannot be merged if this check fails
- Must fix Python errors before approval

### 2. Web Build

**Job Name**: `web`  
**Workflow**: `.github/workflows/ci.yml`

**Steps**:
1. Checkout code
2. Set up Node.js 20
3. Install dependencies:
   ```bash
   cd apps/web && npm ci
   ```
4. Run tests:
   ```bash
   cd apps/web && npm test
   ```
5. Build application:
   ```bash
   cd apps/web && npm run build
   ```

**Success Criteria**:
- Dependencies install successfully
- All tests pass
- Build completes without errors
- Exit code 0

**Failure Handling**:
- PR cannot be merged if this check fails
- Must fix build or test errors before approval

## Human Approval Requirements

### Review Requirements

All PRs to `main` require at least **1 approving review** from:
- Repository maintainers
- Users with write access
- Designated reviewers (if CODEOWNERS is configured)

### Review Checklist

Reviewers should verify:

1. **Code Quality**
   - [ ] Code follows repository style and conventions
   - [ ] No obvious bugs or security issues
   - [ ] Appropriate error handling

2. **Testing**
   - [ ] Tests are included for new functionality
   - [ ] Tests are comprehensive and meaningful
   - [ ] Edge cases are covered

3. **Documentation**
   - [ ] Code is well-commented where necessary
   - [ ] README or relevant docs are updated
   - [ ] API changes are documented

4. **PR Description**
   - [ ] Clear summary of changes
   - [ ] Risk assessment included
   - [ ] Evidence of testing provided
   - [ ] Rollback plan documented (for medium/high-risk)
   - [ ] Scope guard confirms minimal changes

5. **Scope**
   - [ ] Changes are minimal and focused
   - [ ] No unnecessary refactoring
   - [ ] Follows slice ownership guidelines

### Review Timeframes

- **Low-risk changes**: Review within 24 hours
- **Medium-risk changes**: Review within 48 hours
- **High-risk changes**: Review within 72 hours, may require multiple approvers

## Enforcement

### Automated Enforcement

GitHub branch protection rules are enforced automatically:
- PRs without required checks cannot merge
- PRs without approval cannot merge
- Status badges on PRs show check status

### Manual Enforcement

1. **PR Template**
   - Use `.github/pull_request_template.md` to prompt for required information
   - Ensures consistent PR structure

2. **Label Requirements**
   - Apply risk labels (`risk:low`, `risk:medium`, `risk:high`)
   - Apply area labels (`area:frontend`, `area:backend`, etc.)

3. **Review Process**
   - Maintainers review for completeness
   - Request changes if requirements not met
   - Approve only when all criteria satisfied

## Bypassing Protections

### When Bypass is Allowed

In **emergency situations only**:
- Critical security vulnerability hotfix
- Production outage requiring immediate fix
- Broken main branch blocking all development

### Bypass Process

1. Document the emergency in an issue
2. Get verbal/written approval from repository owner
3. Use administrator override to merge
4. Create follow-up PR to add missing tests/docs
5. Conduct post-incident review

### Bypass Logging

All bypasses are logged:
- GitHub audit log tracks protection bypasses
- Emergency issue documents the reason
- Follow-up issue tracks remediation

## Configuration Steps

To apply these protections to the repository:

1. Navigate to repository **Settings** → **Branches**
2. Click **Add rule** for branch name pattern: `main`
3. Enable the following:
   - ✅ Require a pull request before merging
     - ✅ Require approvals: 1
     - ✅ Dismiss stale pull request approvals when new commits are pushed
   - ✅ Require status checks to pass before merging
     - ✅ Require branches to be up to date before merging
     - Add required checks: `python`, `web`
   - ✅ Require conversation resolution before merging
   - ✅ Require linear history
   - ✅ Do not allow bypassing the above settings
   - ✅ Restrict who can push to matching branches (none)
4. Click **Create** or **Save changes**

## Monitoring and Compliance

### Weekly Reviews

As part of the weekly KPI digest:
- Track PRs merged without full review
- Monitor branch protection bypass events
- Review failed CI runs on main branch

### Quarterly Audits

Every quarter:
- Review branch protection settings
- Verify required checks are still relevant
- Update policy based on team feedback

## Policy Updates

This policy is reviewed and updated:
- When new CI checks are added
- When repository structure changes significantly
- When team processes evolve
- At least once per quarter

Changes to this policy require:
- Discussion in repository issues or discussions
- Approval from repository maintainers
- Documentation update before enforcement

## References

- [AGENTS.md](../AGENTS.md) - Agent operating model and guardrails
- [ARCHITECTURE.md](../ARCHITECTURE.md) - Monorepo slice ownership
- [docs/KPI_METRICS.md](./KPI_METRICS.md) - KPI tracking and targets
- [GitHub Branch Protection Documentation](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches)
