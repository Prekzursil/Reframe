# Governance Overview

This document provides an overview of all governance components in the Reframe repository and how they work together.

## Core Governance Documents

### 1. [AGENTS.md](../AGENTS.md)
**Purpose**: Defines the operating model for AI-assisted development.

**Key Topics**:
- Evidence-first workflow
- Monorepo execution rules
- Risk policy and merge strategy
- Canonical verification command
- Scope guardrails
- Agent queue contract

**When to Reference**: 
- Setting up agent-assisted workflows
- Understanding merge policies
- Before starting any development work

### 2. [ARCHITECTURE.md](../ARCHITECTURE.md)
**Purpose**: Documents system architecture and ownership.

**Key Topics**:
- High-level system overview
- Directory layout and organization
- Monorepo slice definitions
- Slice ownership guidelines
- Cross-slice coordination

**When to Reference**:
- Planning new features
- Understanding code organization
- Determining which slice to modify
- Coordinating multi-slice changes

### 3. [docs/BRANCH_PROTECTION.md](./BRANCH_PROTECTION.md)
**Purpose**: Defines branch protection requirements and enforcement.

**Key Topics**:
- Protected branch rules
- Required CI checks
- Human approval requirements
- Review checklist
- Enforcement procedures
- Bypass process for emergencies

**When to Reference**:
- Setting up repository protection
- Understanding merge requirements
- Reviewing pull requests
- Dealing with blocked PRs

### 4. [docs/KPI_METRICS.md](./KPI_METRICS.md)
**Purpose**: Defines development metrics and targets.

**Key Topics**:
- Cycle time metrics
- Lead time tracking
- Rework and failure rates
- Evidence metrics
- Slice-specific metrics
- Regression tracking methodology

**When to Reference**:
- Reviewing team performance
- Setting improvement goals
- Analyzing trends
- Planning capacity

## Operational Workflows

### 5. [.github/workflows/kpi-digest.yml](../.github/workflows/kpi-digest.yml)
**Purpose**: Automated weekly KPI collection and reporting.

**Runs**: Every Monday at 9:00 AM UTC (scheduled)

**Outputs**: 
- Weekly KPI report JSON (`.github/kpi-reports/YYYY-WWW.json`)
- Markdown summary in workflow logs

**Testing**: See [KPI_DIGEST_TESTING.md](./KPI_DIGEST_TESTING.md)

### 6. [.github/workflows/ci.yml](../.github/workflows/ci.yml)
**Purpose**: Continuous integration for quality assurance.

**Runs**: On every push and pull request to main

**Jobs**:
- Python compilation and tests
- Web application tests and build

**Required For**: Merging to main branch

### 7. [.github/workflows/agent-task-queue.yml](../.github/workflows/agent-task-queue.yml)
**Purpose**: Agent task intake and routing.

**Triggers**: When `agent:ready` label is added to an issue

**Actions**:
- Updates issue status labels
- Posts execution packet
- Notifies @copilot

### 8. [.github/workflows/agent-label-sync.yml](../.github/workflows/agent-label-sync.yml)
**Purpose**: Standardize repository labels.

**Triggers**: Manual workflow dispatch

**Actions**: Creates or updates standard labels for agents, risk, and areas

## Support Documentation

### 9. [docs/KPI_DIGEST_TESTING.md](./KPI_DIGEST_TESTING.md)
**Purpose**: Testing guide for KPI digest workflow.

**Covers**:
- Test scenarios
- Validation procedures
- Edge cases
- Troubleshooting

### 10. [docs/regressions/](./regressions/)
**Purpose**: Regression tracking logs by slice.

**Structure**:
- `README.md` - Tracking process and guidelines
- `api-regressions.md` - API slice regressions
- `web-regressions.md` - Web slice regressions
- `worker-regressions.md` - Worker slice regressions
- `media-core-regressions.md` - Core library regressions
- `infra-regressions.md` - Infrastructure regressions

**Usage**: Log regressions as they occur, track resolution

## Baseline-Lite Package

### 11. [docs/BASELINE_LITE_PACKAGE.md](./BASELINE_LITE_PACKAGE.md)
**Purpose**: Reusable governance bundle for new repositories.

**Contains**:
- Package component inventory
- Deployment checklist
- Customization guide
- Monorepo overlays
- Exception handling patterns

### 12. [docs/BASELINE_LITE_QUICKSTART.md](./BASELINE_LITE_QUICKSTART.md)
**Purpose**: Quick start guide for deploying Baseline-Lite.

**Contains**:
- 5-minute setup instructions
- Component selection guide
- Customization checklist
- Testing procedures
- Common troubleshooting

## Templates

### 13. [.github/pull_request_template.md](../.github/pull_request_template.md)
**Purpose**: Standardized PR structure.

**Sections**:
- Summary
- Risk assessment
- Evidence of testing
- Rollback plan
- Scope guard

### 14. [.github/ISSUE_TEMPLATE/agent_task.yml](../.github/ISSUE_TEMPLATE/agent_task.yml)
**Purpose**: Structured task intake for agents.

**Fields**:
- Objective
- Acceptance criteria
- Slice ownership
- Risk level
- Verification command

## Development Tools

### 15. [Makefile](../Makefile)
**Purpose**: Task automation for common development operations.

**Key Targets**:
- `make verify` - Run all quality checks (required before merge)
- `make *-install` - Install dependencies per slice
- `make *-dev` - Run development servers
- `make *-test` - Run tests per slice

### 16. [.pre-commit-config.yaml](../.pre-commit-config.yaml)
**Purpose**: Git pre-commit hooks for code quality.

**Checks**:
- Code formatting (black, prettier)
- Linting (ruff, eslint)
- File size limits
- Merge conflict markers

## How Components Work Together

### Development Lifecycle

```
1. Issue Created
   ↓
2. Label with 'agent:ready' (optional)
   ↓
3. Agent Task Queue Triggered (if using agents)
   ↓
4. Development Work
   - Follow AGENTS.md guidelines
   - Reference ARCHITECTURE.md for slice ownership
   - Run pre-commit hooks locally
   ↓
5. Create Pull Request
   - Use PR template
   - Include risk assessment
   ↓
6. CI Runs (ci.yml)
   - Compile checks
   - Tests
   - Build
   ↓
7. Review Process
   - Follow BRANCH_PROTECTION.md checklist
   - Resolve all comments
   ↓
8. Approval + Merge
   - Requires 1 approval
   - All CI checks pass
   ↓
9. Weekly KPI Digest (kpi-digest.yml)
   - Tracks PR cycle time
   - Monitors failure rates
   - Reports metrics
   ↓
10. Regression Tracking (if issues arise)
    - Log in appropriate slice regression file
    - Track resolution time
    - Update KPI metrics
```

### Quality Gates

Multiple layers ensure code quality:

1. **Pre-commit hooks** (.pre-commit-config.yaml)
   - Local, immediate feedback
   - Prevents obviously bad commits

2. **CI pipeline** (ci.yml)
   - Automated, consistent checks
   - Runs on every PR

3. **Required checks** (BRANCH_PROTECTION.md)
   - Enforced by GitHub
   - Must pass before merge

4. **Human review** (BRANCH_PROTECTION.md)
   - Critical thinking and context
   - Ensures appropriate changes

5. **KPI monitoring** (kpi-digest.yml + KPI_METRICS.md)
   - Long-term trends
   - Continuous improvement signals

### Metrics and Improvement Loop

```
Weekly KPI Digest
   ↓
Review Metrics vs Targets
   ↓
Identify Issues
   ↓
Update Processes/Documentation
   ↓
Implement Changes
   ↓
Monitor Impact (next week)
   ↓
(repeat)
```

## Getting Started Checklist

For new team members or contributors:

- [ ] Read [AGENTS.md](../AGENTS.md) for operating model
- [ ] Read [ARCHITECTURE.md](../ARCHITECTURE.md) to understand structure
- [ ] Install pre-commit hooks: `pre-commit install`
- [ ] Verify setup: `make verify`
- [ ] Review [BRANCH_PROTECTION.md](./BRANCH_PROTECTION.md) for merge process
- [ ] Browse existing PRs for examples
- [ ] Check [KPI_METRICS.md](./KPI_METRICS.md) for quality targets

## Admin Setup Checklist

For repository administrators setting up governance:

- [ ] Copy governance documents (AGENTS.md, ARCHITECTURE.md)
- [ ] Set up CI workflow (ci.yml)
- [ ] Configure branch protection in GitHub settings
- [ ] Run agent label sync workflow
- [ ] Set up KPI digest workflow
- [ ] Test with a sample PR
- [ ] Document any customizations
- [ ] Train team on new processes

## Maintenance

### Weekly
- Review KPI digest output
- Check for open regressions
- Monitor CI failure trends

### Monthly
- Review branch protection effectiveness
- Audit bypassed merges (if any)
- Update documentation as needed

### Quarterly
- Comprehensive governance review
- Update KPI targets based on data
- Retrospective on what's working/not working
- Plan improvements for next quarter

## Questions and Support

- **Process questions**: Open a discussion or issue
- **Technical issues**: Check troubleshooting sections in specific documents
- **Improvements**: Propose changes via PR with rationale
- **Urgent issues**: Contact repository maintainers directly

## Related Documentation

- [README.md](../README.md) - Project overview and getting started
- [TODO.md](../TODO.md) - Development roadmap
- [GOAL.md](../GOAL.md) - Project goals and vision

## Version History

- **2026-02-18**: Initial governance framework (Phase 3/4)
  - KPI metrics and digest automation
  - Branch protection policy
  - Regression tracking
  - Baseline-lite package
