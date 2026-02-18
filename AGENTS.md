# AGENTS.md

## Operating Model
This repository follows an evidence-first, zero-external-API-cost workflow.
Use GitHub Copilot coding agent and Codex app/IDE/CLI for implementation and review.

## Monorepo Execution Rules
- Decompose non-trivial work into independent slices (API, worker, web, docs).
- Assign explicit slice ownership in issue intake.
- Integrate through one human-reviewed PR after deterministic verification.

## Risk Policy
- Default merge policy: human-reviewed only.
- Use explicit risk labels: `risk:low`, `risk:medium`, `risk:high`.
- High-risk changes require rollback notes.

## Canonical Verification Command
Run this before completion claims:

```bash
make verify
```

## Scope Guardrails
- Keep changes minimal and scoped to one slice unless explicitly requested.
- Avoid broad refactors without a dedicated task packet.
- Preserve local-first behavior and deterministic tests.

## Agent Queue Contract
- Intake work via `.github/ISSUE_TEMPLATE/agent_task.yml`.
- Queue with label `agent:ready`.
- Queue workflow posts execution packet and notifies `@copilot`.
