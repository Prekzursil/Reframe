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
        # Anchored on the ROW, by regex, not on one exact link spelling. The literal
        # string this used to search for did not exist in the tree it shipped with, so
        # every run reported BROKEN-HARNESS and the accompanying "5/5 mutations go red"
        # claim was false. A mutation keyed to a formatting detail of the file it mutates
        # decays the first time anyone reflows that file.
        "m1 unlink a doc from docs/INDEX.md",
        "docs/INDEX.md",
        lambda t: re.sub(r"(?m)^\|.*WU-R0-EVAL-HARNESS\.md.*\n", "", t, count=1),
        "r3",
    ),
    (
        # The payloads below are deliberately-broken FIXTURES, not citations. Without
        # the waivers this harness fails the very gate it proves — a detector
        # self-conflict, and the tell that a probe is reading the document instead of
        # the field.
        "m2 cite a docs/ path that does not exist",
        "docs/ROADMAP.md",
        lambda t: t + "\n\nSee docs/nope-does-not-exist.md for details.\n",  # ssot-allow: fixture
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
        lambda t: t.replace('"""', '"""Derived by .audit/anything.py.\n\n', 1),  # ssot-allow: fixture
        "r4",
    ),
    (
        "m4 remove a doc status line",
        "docs/design-system.md",
        lambda t: re.sub(r"(?m)^> \*\*Status:\*\*.*\n", "", t, count=1),
        "r1",
    ),
    (
        # PLANTED-CITATION CONTROL for r5. The rename that motivated r5 was invisible to
        # r1-r4, so "the gate is green" was not evidence the bare-name form is covered.
        # This plants exactly that form and requires r5 to name it.
        "m5 cite a subdirectory doc by BARE basename",
        "sidecar/media_studio/features/zoom.py",
        lambda t: t.replace('"""', '"""Wiring notes live in WIRING-T2.md.\n\n', 1),  # ssot-allow: fixture
        "r5",
    ),
    (
        # NEGATIVE control for the same rule: the QUALIFIED spelling of the identical
        # citation must NOT fire. Without this, r5 could be "flag every .md basename"
        # and still pass m5 — a rule that cannot be satisfied is as useless as one that
        # cannot fire. Expected rule count is 0, so it is checked separately below.
        "m5b cite the SAME doc by its full path (must stay green)",
        "sidecar/media_studio/features/zoom.py",
        lambda t: t.replace('"""', '"""Wiring notes live in docs/wiring/WIRING-T2.md.\n\n', 1),
        None,
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
        # Byte-exact round-trip. `read_text`/`write_text` normalise CRLF -> LF on the
        # way out, so a "revert" would silently rewrite the line endings of every file
        # this harness touches (windows-shell.md §8b). git happens to normalise those
        # away here; on a repo that does not, it would leave a whole-file phantom diff.
        raw = p.read_bytes()
        eol = b"\r\n" if b"\r\n" in raw else b"\n"
        original = raw.decode("utf-8").replace("\r\n", "\n")
        mutated = mutate(original)
        if mutated == original:
            print(f"  BROKEN-HARNESS {name}: mutation was a no-op on {rel}")
            failures += 1
            continue
        p.write_bytes(mutated.replace("\n", eol.decode()).encode("utf-8"))
        try:
            code, out = run()
            if rule is None:
                # A NEGATIVE control: this edit is legitimate and the gate must stay
                # green. `MISS` here means the rule over-fires, which is just as much a
                # broken gate as one that never fires.
                ok = code == 0
                print(f"  {'GREEN-OK' if ok else 'MISS    '} {name}: exit={code} (expected 0)")
            else:
                n = counter(out, rule)
                ok = code == 1 and n > 0
                print(f"  {'RED-OK  ' if ok else 'MISS    '} {name}: exit={code} {rule}={n}")
            if not ok:
                failures += 1
        finally:
            p.write_bytes(raw)
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
