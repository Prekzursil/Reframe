---
name: feature-or-bugfix-with-tdd-and-coverage
description: Workflow command scaffold for feature-or-bugfix-with-tdd-and-coverage in Reframe.
allowed_tools: ["Bash", "Read", "Write", "Grep", "Glob"]
---

# /feature-or-bugfix-with-tdd-and-coverage

Use this workflow when working on **feature-or-bugfix-with-tdd-and-coverage** in `Reframe`.

## Goal

Implements a feature or bugfix with immediate test coverage, aiming for 100% coverage and explicit TDD (test-driven development). Each change modifies implementation files and corresponding test files together.

## Common Files

- `sidecar/media_studio/features/reframe_claudeshorts.py`
- `sidecar/tests/test_reframe_claudeshorts.py`
- `sidecar/tests/e2e/_tiny_sidecar.py`
- `sidecar/tests/test_tiny_sidecar_launcher.py`
- `app/renderer/src/panels/ModelsSystemPanel.tsx`
- `app/renderer/src/panels/ModelsSystemPanel.test.tsx`

## Suggested Sequence

1. Understand the current state and failure mode before editing.
2. Make the smallest coherent change that satisfies the workflow goal.
3. Run the most relevant verification for touched files.
4. Summarize what changed and what still needs review.

## Typical Commit Signals

- Modify or add implementation logic in the relevant source file(s)
- Add or update corresponding test files to cover new or changed logic
- Ensure tests assert both expected behavior and error/failure conditions (including fail-loud, no-silent-fallback cases)
- Run the test suite to confirm 100% coverage (lines, branches, functions, statements)
- Commit both implementation and test changes together

## Notes

- Treat this as a scaffold, not a hard-coded script.
- Update the command if the workflow evolves materially.