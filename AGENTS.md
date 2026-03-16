# AGENTS.md

## Operating Model
This repository follows an evidence-first, zero-external-API-cost workflow.
Use GitHub Copilot coding agent and Codex app/IDE/CLI for implementation and review.

## Monorepo Execution Rules
- Decompose non-trivial work into independent slices (API, worker, web, docs).
- Assign explicit slice ownership in issue intake.
- Integrate through one human-reviewed PR after deterministic verification.
- See `ARCHITECTURE.md` section 3 for detailed slice definitions and ownership guidelines.

## Risk Policy
- Default merge policy: human-reviewed only.
- Use explicit risk labels: `risk:low`, `risk:medium`, `risk:high`.
- High-risk changes require rollback notes.

## Canonical Verification Command
Run this before completion claims **from the repository root**:

```bash
make verify
```

See `README.md` for details on what this command does.

## Scope Guardrails
- Keep changes minimal and scoped to one slice unless explicitly requested.
- Avoid broad refactors without a dedicated task packet.
- Preserve local-first behavior and deterministic tests.

## Strict-Zero Platform Contract
- This repository is governed by `quality-zero-platform`.
- Wrapper workflows under `.github/workflows/quality-zero-*.yml` delegate to platform-managed reusable workflows.
- Keep live rulesets and required-status enforcement deferred until repository contexts are observed and verified.
- Do not push directly to the default branch from automation.
- Platform-driven remediation and backlog branches must preserve monorepo slice ownership, evidence-first reporting, and explicit risk labels.
