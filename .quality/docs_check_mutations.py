"""Both-states proof for `.quality/docs_check.py` (single-signal-verification §3b).

A gate that has never been seen red is indistinguishable from a no-op, and this one
sits outside pytest --cov, outside basedpyright's include, and outside pre-commit's
ruff `files:` filter — so this harness is its ONLY protection against silently
becoming a no-op.

For each mutation: apply it, run the gate, require exit 1 AND require the named rule's
counter to be non-zero, then revert and require exit 0 again.

NOT wired into CI — it mutates tracked files in place, which a shared runner must not
do. Run it by hand after any change to `docs_check.py`:

    python .quality/docs_check_mutations.py

It is fail-safe on interrupt only to the extent that each mutation reverts in a
`finally`; if it is killed mid-run, `git checkout -- <file>` restores the tree.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

def _find_root() -> Path:
    """Same anchor as `docs_check.py`. `parent.parent` would be wrong the moment this
    file moves — which it already did once, from the repo root into `.quality/`, and the
    harness caught its own relocation by failing its precondition instead of passing."""
    here = Path(__file__).resolve()
    for cand in (here.parent, *here.parents):
        if (cand / ".git").exists() and (cand / "app/package.json").is_file():
            return cand
    raise SystemExit(f"FAILED:mutate cannot locate the repo root from {here}")


ROOT = _find_root()
GATE = ["python", ".quality/docs_check.py"]


def run() -> tuple[int, str]:
    r = subprocess.run(GATE, cwd=ROOT, capture_output=True, text=True, timeout=300)
    return r.returncode, r.stdout + r.stderr


def counter(out: str, rule: str) -> int:
    m = re.search(rf"\b{rule}=(\d+)", out)
    return int(m.group(1)) if m else -1


# (name, file, mutate(text) -> text, rule expected to fire)
MUTATIONS = [
    (
        "m1 unlink a doc from INDEX.md",
        "docs/INDEX.md",
        lambda t: t.replace("[`WU-R0-EVAL-HARNESS.md`](WU-R0-EVAL-HARNESS.md)", "WU-R0 (unlinked)"),
        "r3",
    ),
    (
        "m2 cite a docs/ path that does not exist",
        "docs/ROADMAP.md",
        lambda t: t + "\n\nSee docs/nope-does-not-exist.md for details.\n",
        "r2",
    ),
    (
        "m2b broken SIBLING-RELATIVE markdown link",
        "docs/ROADMAP.md",
        lambda t: t + "\n\nSee [gone](./gone-sibling.md).\n",
        "r2",
    ),
    (
        "m3 cite a gitignored path from tracked source",
        "sidecar/media_studio/features/zoom.py",
        lambda t: t.replace(
            '"""', '"""Derived by .audit/anything.py.\n\n', 1
        ),
        "r4",
    ),
    (
        "m4 remove a doc status line",
        "docs/design-system.md",
        lambda t: re.sub(r"(?m)^> \*\*Status:\*\*.*\n", "", t, count=1),
        "r1",
    ),
]


def main() -> int:
    code, out = run()
    if code != 0:
        print(f"PRECONDITION FAILED: gate is not green before mutating (exit {code})")
        print(out[-1500:])
        return 1
    print(f"baseline: exit=0 :: {out.strip().splitlines()[-2]}")

    failures = 0
    for name, rel, mutate, rule in MUTATIONS:
        p = ROOT / rel
        original = p.read_text(encoding="utf-8")
        mutated = mutate(original)
        if mutated == original:
            print(f"  BROKEN-HARNESS {name}: mutation was a no-op on {rel}")
            failures += 1
            continue
        p.write_text(mutated, encoding="utf-8")
        try:
            code, out = run()
            n = counter(out, rule)
            ok = code == 1 and n > 0
            print(f"  {'RED-OK  ' if ok else 'MISS    '} {name}: exit={code} {rule}={n}")
            if not ok:
                failures += 1
        finally:
            p.write_text(original, encoding="utf-8")
        code, out = run()
        if code != 0:
            print(f"  REVERT-FAILED after {name}: gate still red (exit {code})")
            failures += 1

    code, out = run()
    print(f"final: exit={code} :: {out.strip().splitlines()[-1]}")
    if code != 0 or failures:
        print(f"FAILED:mutate {failures} mutation(s) did not behave")
        return 1
    print(f"SUCCESS:mutate {len(MUTATIONS)}/{len(MUTATIONS)} mutations went red and reverted clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
