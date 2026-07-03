---
name: fail-loud-no-silent-fallback-hardening
description: Workflow command scaffold for fail-loud-no-silent-fallback-hardening in Reframe.
allowed_tools: ["Bash", "Read", "Write", "Grep", "Glob"]
---

# /fail-loud-no-silent-fallback-hardening

Use this workflow when working on **fail-loud-no-silent-fallback-hardening** in `Reframe`.

## Goal

Hardens error handling so that any provisioning, data, or dependency failure is surfaced loudly to the user/developer, never silently degraded. This includes surfacing missing models, broken payloads, or partial installs, and always adding explicit error messages and test assertions for these cases.

## Common Files

- `sidecar/media_studio/features/reframe_claudeshorts.py`
- `sidecar/tests/test_reframe_claudeshorts.py`
- `sidecar/runtime_setup/bootstrap.py`
- `sidecar/tests/test_runtime_setup.py`
- `app/renderer/src/panels/ModelsSystemPanel.tsx`
- `app/renderer/src/panels/ModelsSystemPanel.test.tsx`

## Suggested Sequence

1. Understand the current state and failure mode before editing.
2. Make the smallest coherent change that satisfies the workflow goal.
3. Run the most relevant verification for touched files.
4. Summarize what changed and what still needs review.

## Typical Commit Signals

- Identify a code path where a failure could be silently ignored or degraded
- Modify implementation to raise explicit errors or surface actionable messages (fail loud)
- Update or add tests to assert that these errors are raised and never silently degrade
- Document the fail-loud behavior inline or in test descriptions
- Commit both implementation and test changes together

## Notes

- Treat this as a scaffold, not a hard-coded script.
- Update the command if the workflow evolves materially.