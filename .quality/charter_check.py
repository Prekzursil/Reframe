#!/usr/bin/env python3
"""Charter <-> workflow consistency gate.

Parses the closed gate list from QUALITY-CHARTER.md and the gate steps declared in
.github/workflows/quality.yml, and exits non-zero if the two sets diverge. This keeps
the documented gate model and the actual CI job from drifting apart (one-in/one-out).

Mapping: each charter gate has a stable slug (the "Gate" column). Every gate slug MUST
be covered by at least one step in quality.yml whose name contains the marker
`gate-<slug>` (the lint-format and secrets gates are both covered by the single
`gate-lint-format` pre-commit step, which also runs gitleaks).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CHARTER = REPO_ROOT / "QUALITY-CHARTER.md"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "quality.yml"

# Gates that are intentionally co-located in one workflow step.
# key: gate slug that has no own `gate-<slug>` step; value: the step slug that covers it.
COVERED_BY = {
    "secrets": "lint-format",  # gitleaks runs inside the pre-commit (gate-lint-format) step
}


def parse_charter_gates(text: str) -> list[str]:
    """Extract gate slugs from the table between the BEGIN/END GATES markers."""
    block = re.search(r"BEGIN GATES(.*?)END GATES", text, re.DOTALL)
    if not block:
        raise SystemExit("charter_check: BEGIN/END GATES markers not found in QUALITY-CHARTER.md")
    slugs: list[str] = []
    for line in block.group(1).splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 2:
            continue
        num, gate = cells[0], cells[1]
        if not num.isdigit():  # skip header + separator rows
            continue
        slugs.append(gate)
    return slugs


def parse_workflow_gate_steps(text: str) -> set[str]:
    """Collect gate slugs from step names of the form `gate-<slug>...`."""
    found: set[str] = set()
    for match in re.finditer(r"gate-([a-z0-9-]+?)(?=[\s(]|$)", text, re.MULTILINE):
        found.add(match.group(1))
    return found


def main() -> int:
    if not CHARTER.exists():
        raise SystemExit(f"charter_check: missing {CHARTER}")
    if not WORKFLOW.exists():
        raise SystemExit(f"charter_check: missing {WORKFLOW}")

    charter_gates = parse_charter_gates(CHARTER.read_text(encoding="utf-8"))
    workflow_steps = parse_workflow_gate_steps(WORKFLOW.read_text(encoding="utf-8"))

    if not charter_gates:
        raise SystemExit("charter_check: no gates parsed from QUALITY-CHARTER.md")

    problems: list[str] = []
    for gate in charter_gates:
        covering = COVERED_BY.get(gate, gate)
        if covering not in workflow_steps:
            problems.append(f"  - charter gate '{gate}' has no matching 'gate-{covering}' step in quality.yml")

    # Reverse direction: every workflow gate step must map to a charter gate.
    known = set(charter_gates) | {COVERED_BY[g] for g in COVERED_BY}
    for step in sorted(workflow_steps):
        if step not in known:
            problems.append(f"  - quality.yml has 'gate-{step}' step with no matching charter gate")

    if problems:
        print("charter_check: FAILED — charter and quality.yml diverge:")
        print("\n".join(problems))
        print(f"\n  charter gates : {charter_gates}")
        print(f"  workflow gates: {sorted(workflow_steps)}")
        return 1

    print(f"charter_check: OK — {len(charter_gates)} gates consistent: {charter_gates}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
