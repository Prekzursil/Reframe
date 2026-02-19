# Baseline-Lite Package

## Overview

The Baseline-Lite Package is a reusable governance and infrastructure bundle designed to bootstrap new repositories with proven patterns from the Reframe project. It provides essential tooling, workflows, and documentation templates that enforce code quality, security, and operational excellence from day one.

## Package Components

### 1. Core Governance Documents

#### AGENTS.md
Defines the operating model for AI-assisted development:
- Evidence-first workflow principles
- Monorepo execution rules
- Risk policy and merge strategy
- Canonical verification commands
- Scope guardrails

**Customization Points**:
- Adjust verification command to match project tech stack
- Modify risk thresholds based on project criticality
- Add project-specific slice definitions

#### ARCHITECTURE.md
Documents system architecture and slice ownership:
- High-level system overview
- Directory layout conventions
- Slice ownership guidelines
- Cross-slice coordination patterns

**Customization Points**:
- Replace monorepo structure with project-specific layout
- Define project-specific slices (frontend, backend, etc.)
- Add architecture diagrams and decision records

### 2. CI/CD Workflows

#### `.github/workflows/ci.yml`
Primary continuous integration pipeline:
- Language-specific compilation checks
- Test execution with coverage
- Build verification
- Parallel job execution

**Customization Points**:
- Add or remove language-specific jobs
- Adjust Node.js/Python versions
- Configure additional linters or security scanners
- Modify cache strategies

#### `.github/workflows/kpi-digest.yml`
Weekly KPI reporting automation:
- Collects development metrics
- Generates health summaries
- Stores historical data
- Posts digest reports

**Customization Points**:
- Adjust schedule frequency
- Modify metric thresholds
- Add project-specific metrics
- Configure notification channels

#### `.github/workflows/agent-task-queue.yml`
Agent task intake and routing:
- Label-based task triggering
- Execution packet generation
- Copilot notification
- Progress tracking

**Customization Points**:
- Modify label names
- Adjust execution contract terms
- Add project-specific task templates

#### `.github/workflows/agent-label-sync.yml`
Label management and standardization:
- Creates standard labels
- Syncs label metadata
- Ensures consistency

**Customization Points**:
- Add project-specific labels
- Modify color schemes
- Adjust descriptions

### 3. Documentation Templates

#### docs/KPI_METRICS.md
Defines development KPIs:
- Cycle time metrics
- Lead time tracking
- Failure rates
- Evidence metrics
- Regression tracking

**Customization Points**:
- Set targets based on team size and velocity
- Add domain-specific metrics
- Define slice-specific tracking

#### docs/BRANCH_PROTECTION.md
Branch protection policy:
- Protected branch rules
- Required checks definition
- Approval requirements
- Enforcement procedures

**Customization Points**:
- Adjust approval count requirements
- Add or remove required status checks
- Define project-specific review checklists
- Set review timeframes

#### docs/BASELINE_LITE_PACKAGE.md (this document)
Package documentation and rollout guide

### 4. Issue Templates

#### `.github/ISSUE_TEMPLATE/agent_task.yml`
Structured task intake for agent execution:
- Captures objective and acceptance criteria
- Defines slice ownership
- Sets risk level
- Includes verification commands

**Customization Points**:
- Modify field names and descriptions
- Add project-specific fields
- Adjust validation rules

### 5. Development Tooling

#### Makefile
Task automation and verification:
- Install targets per slice
- Dev server targets
- Test runners
- Verification command

**Customization Points**:
- Add language-specific targets
- Configure tool paths
- Set default options

#### .pre-commit-config.yaml
Pre-commit hook configuration:
- Code formatting (black, prettier)
- Linting (ruff, eslint)
- Security checks
- Commit message validation

**Customization Points**:
- Add or remove hooks
- Configure tool options
- Set file patterns

#### .gitignore
Standard exclusion patterns:
- Build artifacts
- Dependencies
- IDE files
- Environment files

**Customization Points**:
- Add project-specific patterns
- Configure for additional languages

### 6. Pull Request Template

#### `.github/pull_request_template.md`
Standardized PR structure:
- Summary section
- Risk assessment
- Evidence of testing
- Rollback plan
- Scope guard

**Customization Points**:
- Add project-specific sections
- Modify checklist items
- Include deployment steps

## Deployment Checklist

Use this checklist when rolling out Baseline-Lite to a new repository:

### Phase 1: Core Setup (Day 1)
- [ ] Create repository with appropriate visibility
- [ ] Initialize with README and basic .gitignore
- [ ] Copy AGENTS.md and customize verification command
- [ ] Copy Makefile and adjust for project languages
- [ ] Set up branch protection for main branch
- [ ] Create initial ARCHITECTURE.md documenting planned structure

### Phase 2: CI/CD Foundation (Days 2-3)
- [ ] Copy .github/workflows/ci.yml
- [ ] Customize CI workflow for project tech stack
- [ ] Add required secrets (if needed)
- [ ] Test CI workflow with a dummy PR
- [ ] Copy agent workflows (agent-task-queue.yml, agent-label-sync.yml)
- [ ] Run agent-label-sync workflow to create standard labels

### Phase 3: Quality Gates (Days 4-5)
- [ ] Copy .pre-commit-config.yaml
- [ ] Install pre-commit hooks for local dev
- [ ] Copy pull_request_template.md
- [ ] Copy issue templates
- [ ] Test issue creation and PR flow
- [ ] Verify required checks appear in PR status

### Phase 4: Governance Documentation (Week 2)
- [ ] Copy docs/BRANCH_PROTECTION.md
- [ ] Apply branch protection settings via GitHub UI
- [ ] Copy docs/KPI_METRICS.md
- [ ] Customize KPI targets for project
- [ ] Copy .github/workflows/kpi-digest.yml
- [ ] Test KPI digest generation manually

### Phase 5: Validation (Week 2-3)
- [ ] Create test PR touching multiple slices
- [ ] Verify all required checks run
- [ ] Verify approval requirements enforced
- [ ] Verify pre-commit hooks work locally
- [ ] Review first KPI digest output
- [ ] Adjust thresholds and targets based on baseline

### Phase 6: Team Onboarding (Week 3-4)
- [ ] Document rollout in project README
- [ ] Add CONTRIBUTING.md with local setup
- [ ] Create onboarding issue template
- [ ] Run team walkthrough of governance model
- [ ] Address questions and friction points
- [ ] Update documentation based on feedback

## Monorepo-Specific Overlays

When deploying to a monorepo structure, apply these overlays:

### Slice-Specific Workflows

For projects with clear slice boundaries (e.g., frontend, backend, worker):

#### Add slice-specific CI jobs
```yaml
jobs:
  frontend:
    name: Frontend checks
    runs-on: ubuntu-latest
    # ... steps specific to frontend slice
  
  backend:
    name: Backend checks
    runs-on: ubuntu-latest
    # ... steps specific to backend slice
```

#### Add path-based triggering
```yaml
on:
  pull_request:
    paths:
      - 'apps/web/**'
      - 'packages/shared/**'
```

#### Create slice-specific test targets
```makefile
frontend-test:
	cd apps/web && npm test

backend-test:
	PYTHONPATH=.:apps/api python -m pytest apps/api/tests

verify: frontend-test backend-test
```

### Exception Handling

Some repositories may need exceptions to standard policies:

#### Public/Open-Source Overlay
- Relax approval requirements for maintainers
- Add community contribution guidelines
- Include DCO or CLA requirements
- Add security disclosure policy

#### High-Security Overlay
- Require signed commits
- Add CODEOWNERS file with mandatory reviews
- Require 2+ approvals for sensitive areas
- Add additional security scanning (SAST, dependency check)

#### Rapid-Iteration Overlay
- Reduce approval count to 0 for bot PRs
- Allow merge queue with auto-merge
- Reduce required check time with parallel execution
- Use draft PRs for WIP, strict rules for ready

## Maintenance and Updates

### Version Tracking

Baseline-Lite versions follow semantic versioning:
- **Major**: Breaking changes to governance model
- **Minor**: New components or workflows added
- **Patch**: Bug fixes, documentation updates

Current version: **1.0.0**

### Update Process

When updating Baseline-Lite in an existing repo:

1. Review changelog for breaking changes
2. Backup current configurations
3. Apply updates file by file
4. Test each component after update
5. Update customizations to new format
6. Communicate changes to team
7. Monitor for issues in first week

### Feedback Loop

Improvements to Baseline-Lite should be:
- Tested in Reframe repository first
- Documented with rationale and examples
- Rolled out to dependent repos incrementally
- Validated with team feedback

## Success Metrics

Track these metrics to measure Baseline-Lite effectiveness:

### Adoption Metrics
- Time to first PR (from repo creation)
- Time to production deploy
- Number of governance violations (should trend down)

### Quality Metrics
- PR cycle time (should stay within targets)
- CI failure rate (should stay below 10%)
- Revert rate (should stay below 5%)

### Developer Experience
- Survey: "Governance feels helpful vs. bureaucratic"
- Time spent on non-coding tasks (should be minimal)
- Friction points reported (should be addressed)

## Support and Resources

### Documentation
- Full governance model: See AGENTS.md in this repo
- Architecture patterns: See ARCHITECTURE.md
- KPI definitions: See docs/KPI_METRICS.md

### Community
- Discussions: Repository discussions for questions
- Issues: Bug reports or improvement suggestions
- Wiki: Extended examples and case studies (optional)

### Contact
- Maintainers: Listed in repository settings
- Security: See SECURITY.md (if exists)

## License

Baseline-Lite governance components are provided under the same license as the Reframe project. Organizations are free to:
- Use in any project (commercial or non-commercial)
- Modify to fit organizational needs
- Redistribute with attribution

## Changelog

### 1.0.0 (2026-02-18)
- Initial release
- Core governance documents
- CI/CD workflows
- KPI tracking
- Branch protection policy
- Documentation templates
