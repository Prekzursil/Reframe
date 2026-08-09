#!/usr/bin/env python3
"""Charter <-> workflow consistency gate.

Parses the closed gate list from QUALITY-CHARTER.md and the gate steps declared in
.github/workflows/quality.yml, and exits non-zero if the two sets diverge. This keeps
the documented gate model and the actual CI job from drifting apart (one-in/one-out).

Mapping: each charter gate has a stable slug (the "Gate" column). Every gate slug MUST
be covered by at least one step in quality.yml whose name contains the marker
`gate-<slug>` (the lint-format and secrets gates are both covered by the single
`gate-lint-format` pre-commit step, which also runs gitleaks).

"whose name" is enforced structurally — only the value of a SEQUENCE-ITEM `- name:` key is
scanned (that is the shape of a step name; a job-level or `with:`-block `name:` is a
mapping key and is skipped), any trailing comment is stripped, and the body of a `|`/`>`
block scalar is skipped in full. So a slug mentioned in a YAML comment, used as an
upload-artifact/job name, or echoed inside a `run:` body does not satisfy the check.

Scope of that claim, measured (`sidecar/tests/test_charter_check_gate.py` asserts all four,
and each goes RED against the pre-fix parser): whole-line comment · trailing comment ·
`with:`/job-level `name:` · `- name:` inside a `run: |` body. NOT covered, and MEASURED so
rather than assumed (this is a line walker, not a YAML parser): a quoted scalar containing
` #` loses the text after the `#`, and a flow-style `- {name: gate-x}` step is not seen at
all. Both DROP a slug, which fails the charter -> workflow direction loudly; neither can add
a phantom one. An explicit block-scalar indent indicator (`|2`) is not parsed but needs no
special case — body lines are always deeper than the key column, so they are skipped anyway.
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


# A step name: `name:` as the FIRST key of a sequence item. The `- ` is REQUIRED — that is
# what separates a step from a job-level `name:` or a `with: {name: ...}` artifact name,
# both of which are plain mapping keys and neither of which is a gate step.
NAME_KEY = re.compile(r"^\s*-\s+name:\s*(?P<value>\S.*)$")
GATE_SLUG = re.compile(r"gate-([a-z0-9-]+?)(?=[\s(]|$)")

# `<key>: |` / `<key>: >` (with any chomping/`+`/`-` indicator) opens a block scalar whose
# body is opaque text, not YAML. Captured so the body can be skipped: a `run: |` body may
# legitimately contain a line that looks exactly like `- name: gate-x`.
BLOCK_SCALAR_START = re.compile(r"^(?P<lead>\s*)(?P<dash>(?:-\s+)*)(?P<key>[A-Za-z_][\w.-]*):\s*[|>][+-]?\d*\s*$")


def strip_trailing_comment(value: str) -> str:
    """Drop a ` #...` trailing comment from a plain (unquoted) YAML scalar.

    YAML only starts a comment at a `#` preceded by whitespace, so `gate-a#b` is left
    intact. Quoted scalars are NOT parsed: a `#` inside quotes is treated as a comment
    here too. That direction is deliberate — over-stripping can only DROP a slug, which
    makes the forward charter -> workflow check fail loudly; under-stripping is what
    lets a phantom slug silently satisfy it.
    """
    cut = re.search(r"(?:^|\s)#", value)
    return value[: cut.start()] if cut else value


def parse_workflow_gate_steps(text: str) -> set[str]:
    """Collect gate slugs from real step NAMES of the form `- name: gate-<slug>...`.

    Structural on purpose. This used to regex the raw workflow text, so a slug written in
    a YAML comment (or echoed in a `run:` body) counted as a live step — and because the
    resulting set is used in both directions below, a gate whose step had been renamed or
    commented out still satisfied the charter -> workflow check. The parity gate then
    certified an SSOT it was no longer measuring.

    Only two things can add a slug: the line is a sequence-item `name:` key, and it is not
    inside a block scalar. Anything this walker cannot classify is skipped, i.e. it errs
    toward reporting FEWER gates, which fails loudly rather than passing silently.
    """
    found: set[str] = set()
    block_key_col: int | None = None
    for line in text.splitlines():
        if block_key_col is not None:
            # A block scalar continues through blank lines and any line indented deeper
            # than its key; the first non-blank line at or left of the key closes it.
            if not line.strip() or (len(line) - len(line.lstrip())) > block_key_col:
                continue
            block_key_col = None
        opener = BLOCK_SCALAR_START.match(line)
        if opener:
            block_key_col = len(opener.group("lead")) + len(opener.group("dash"))
            continue
        key = NAME_KEY.match(line)
        if not key:
            continue
        for match in GATE_SLUG.finditer(strip_trailing_comment(key.group("value"))):
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
