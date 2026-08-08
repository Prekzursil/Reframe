"""Documentation anti-drift gate — rules R1-R4.

The rules were drafted in the SSOT plan, which lives in the disposable `.audit/` scratch
tree and is deliberately not tracked; they are restated in full and kept current in
`docs/INDEX.md § Anti-drift`, which is the tracked authority.  ssot-allow: the sentence
above names the scratch origin only, and nothing here is decided by that file.


Four mechanical checks over the TRACKED tree. Stdlib only, no network, so it rides
inside gate:1 as a `pre-commit` local hook rather than opening a 7th gate — the
charter's rule 2 declares the gate list closed, and `.quality/charter_check.py`
requires every `gate-<slug>` step in `quality.yml` to map to a charter row.

  r1  Every doc in the authority set carries an R2 status line as line 3.
      Template: `docs/V1.2-FEATURES.md:3`.
  r2  Every `docs/**` / `reports/**` path cited by tracked source resolves on disk.
  r3  Every LIVE tracked `.md` in the authority set is linked from `docs/INDEX.md`.
  r4  No `.gitignore`-matched path is cited by tracked source (R1: scratch that is
      cited is a defect).
  r5  No tracked doc that lives in a SUBDIRECTORY is cited by bare basename.

r5 exists because r1-r4 could not see the drift this gate's own commit created. Moving
`WIRING-*.md` from the repo root to `docs/wiring/` orphaned 24 citations across 17 shipped
`.ts`/`.tsx`/`.py` files, every one a bare `WIRING-<unit>.md` with no directory in front
of it — so `DOC_PATH_RE` never matched, and being outside a markdown link `MD_LINK_RE`
never matched either. The gate printed `r1=0 r2=0 r3=0 r4=0 SUCCESS` over a tree it had
just broken. A rename is exactly the event this gate is for, so blindness to the
bare-name form made it blind to its own highest-value case. Sweeping r5 across the whole
tree then found 66, not 24: earlier archive moves had already left the same drift behind
for `CATALOG-SEED.md` and `PHASE8-SOTA-MANIFEST.md`.  ssot-allow: those two names are
NAMED here as examples of the defect, not cited as sources.

NOTE FOR ANYONE EDITING THIS DOCSTRING: do not write a real cited-doc basename here as
an EXAMPLE of the broken form. The mechanical fixer that closed those 66 rewrote this
very paragraph, turning "the broken form looks like X" into "the broken form looks like
<the correct path>" and destroying the sentence — use-vs-mention, committed by the tool
built to fix it. Use `<unit>`-style placeholders that match no tracked file.

Waiver idiom (charter rule 4 — reasoned and greppable): put `ssot-allow: <reason>`
on the SAME LINE as the citation. r2, r4 and r5 honour it; r1 and r3 do not (there is
no legitimate reason for a tracked authority doc to be unheaded or unlinked).

FAIL CLOSED (rules/common/ci-hygiene.md §1): if the walk yields zero subjects, or
`docs/INDEX.md` is missing, the gate returns non-zero. "Found nothing, therefore
pass" is a no-op gate.

Usage:  python .quality/docs_check.py
Exit 0 when clean, 1 on any violation.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


def _find_root() -> Path:
    """Anchor on markers that exist only at the repo root.

    Deliberately NOT `parent.parent` — `docs/validation/tools/verify_ssot_claims.py`
    records what that cost when the file moved: every relative read missed and the
    detector blamed the repo for its own relocation.

    Intentionally a second copy of that file's `_find_root`, not an import: this
    module runs as a `pre-commit` `language: system` hook with no guaranteed
    `sys.path` into `docs/validation/tools/` (which is not a package), and a gate
    that cannot import is a gate that does not run.
    """
    here = Path(__file__).resolve()
    for cand in (here.parent, *here.parents):
        if (cand / ".git").exists() and (cand / "app/package.json").is_file():
            return cand
    raise SystemExit(f"FAILED:docscheck cannot locate the repo root from {here}")


ROOT = _find_root()
INDEX = "docs/INDEX.md"

# --- what r1/r3 govern -------------------------------------------------------
# The authority set: docs the repo decides things with. Deliberately NOT "every
# tracked .md" — `.claude/commands/*.md` open with YAML `---` at line 1 and carry
# `description:` at line 3, so inserting a status line there breaks the command
# definition. vendor/ is third-party. A README that documents how to run one test
# directory is not an authority doc.
ROOT_AUTHORITY = frozenset(
    {
        "README.md",
        "CHANGELOG.md",
        "CONTRACTS.md",
        "QUALITY-CHARTER.md",
        "SECURITY.md",
    }
)
ARCHIVE_MARKERS = ("docs/_archive/", "docs/plans/_archive/")

STATUS_RE = re.compile(r"^>\s*\*\*Status:\*\*\s*(?:DRAFT|ACTIVE|SHIPPED|SUPERSEDED BY|ARCHIVED)\b")
# Closed extension set. A loose `\S+` suffix reports `docs/v1.1` dangling when the
# text is naming the git BRANCH `docs/v1.1-feature-spec`.
DOC_PATH_RE = re.compile(
    r"(?<![\w./-])((?:docs|reports)/[A-Za-z0-9_][A-Za-z0-9_./-]*"
    r"\.(?:md|html|json|py|ts|tsx|css|gz|txt))"
)
IGNORED_PATH_RE = re.compile(r"(?<![\w./-])((?:\.audit|\.reframe-review)/[A-Za-z0-9_./-]+)")
# A markdown link whose target is a SIBLING-RELATIVE path — `[x](V1-GRILL-DECISIONS.md)`
# from inside docs/. DOC_PATH_RE cannot see these (no `docs/` prefix) and an archive
# move silently breaks them; `docs/ROADMAP.md` carried exactly that after phase 3.
MD_LINK_RE = re.compile(r"\]\(([^)\s#]+?\.(?:md|html|json|py|ts|tsx|css|gz|txt))(?:#[^)]*)?\)")
# r5: a `.md` basename with NO path separator in front of it — `see SOME-DOC.md`. The
# lookbehind excludes an already-qualified path and a `](...)` link target, both of
# which r2 already owns. The example basename is deliberately one no tracked file
# uses; see the docstring note about the fixer rewriting its own explanation.
BARE_DOC_RE = re.compile(r"(?<![\w./\-(])([A-Za-z0-9_][A-Za-z0-9_.\-]*\.md)(?![\w/])")
WAIVER_RE = re.compile(r"ssot-allow:")
# `.ps1` is here because the worktree-hygiene scripts cite repo docs in their comments and
# were invisible to every rule without it. Measured on the combined tree: adding it scans 10
# more files and finds nothing, so it is pure coverage rather than a new debt.
CITING_SUFFIXES = frozenset({".md", ".py", ".ts", ".tsx", ".ps1"})


def tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "--no-optional-locks", "ls-files"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    ).stdout
    return [line for line in out.splitlines() if line]


def is_authority_doc(rel: str) -> bool:
    if not rel.endswith(".md"):
        return False
    if rel in ROOT_AUTHORITY:
        return True
    if rel.startswith("docs/") or rel.startswith("reports/"):
        return True
    return "/" not in rel and rel.startswith("WIRING-")


def read_lines(rel: str) -> list[str] | None:
    try:
        return (ROOT / rel).read_text(encoding="utf-8", errors="replace").splitlines()
    except (OSError, UnicodeDecodeError):
        return None


def resolves(cand: str) -> bool:
    """A cited doc path resolves if it is on disk, or its `.gz` form is.

    `docs/validation/v15-audit-ledger-unverified.md` is tracked as `.md.gz`; a
    citation of the logical name is correct, not dangling.
    """
    p = ROOT / cand
    return p.exists() or (ROOT / (cand + ".gz")).exists()


def check_r1(docs: list[str]) -> list[str]:
    bad = []
    for rel in docs:
        lines = read_lines(rel)
        if lines is None:
            bad.append(f"r1 {rel}:0 unreadable")
            continue
        line3 = lines[2] if len(lines) >= 3 else ""
        if not STATUS_RE.match(line3):
            bad.append(f"r1 {rel}:3 missing R2 status line (got {line3.strip()[:60]!r})")
    return bad


def check_r2_r4(files: list[str]) -> tuple[list[str], list[str], int, int]:
    """Returns (r2 violations, r4 violations, files scanned, waivers APPLIED).

    "Applied" is the load-bearing word in the fourth value. A waiver counts only when
    it actually suppressed a finding on its own line — so the regex literal at
    `WAIVER_RE` and the docstring sentence that explains the idiom, both of which
    contain the token, are excluded mechanically rather than by a filename blocklist.
    That is the use-vs-mention distinction, computed instead of asserted.
    """
    dangling, ignored, scanned, waivers_applied = [], [], 0, 0
    ignore_cache: dict[str, bool] = {}
    for rel in files:
        if Path(rel).suffix not in CITING_SUFFIXES:
            continue
        lines = read_lines(rel)
        if lines is None:
            continue
        scanned += 1
        for n, line in enumerate(lines, 1):
            waived = bool(WAIVER_RE.search(line))
            suppressed = 0
            for m in DOC_PATH_RE.finditer(line):
                cand = m.group(1)
                if not resolves(cand):
                    if waived:
                        suppressed += 1
                    else:
                        dangling.append(f"r2 {rel}:{n} cites {cand} — does not resolve")
            if rel.endswith(".md") and not waived:
                here = Path(rel).parent
                for m in MD_LINK_RE.finditer(line):
                    target = m.group(1)
                    if "://" in target:
                        continue
                    cand = (here / target).as_posix()
                    cand = str(Path(cand)).replace("\\", "/")
                    # Path() normalises `docs/../README.md` -> `README.md`; a link that
                    # escapes the repo root is a defect in its own right.
                    if cand.startswith("..") or not resolves(cand):
                        dangling.append(f"r2 {rel}:{n} links {target} — resolves to {cand}, which does not exist")
            for m in IGNORED_PATH_RE.finditer(line):
                cand = m.group(1)
                if cand not in ignore_cache:
                    ignore_cache[cand] = (
                        subprocess.run(
                            ["git", "--no-optional-locks", "check-ignore", "-q", cand],
                            cwd=ROOT,
                            capture_output=True,
                            timeout=60,
                        ).returncode
                        == 0
                    )
                if ignore_cache[cand]:
                    if waived:
                        suppressed += 1
                    else:
                        ignored.append(f"r4 {rel}:{n} cites gitignored {cand}")
            # Counted once per LINE, after both rule bodies have had their say: a
            # waiver comment waives its whole line, so two suppressed candidates on
            # one line are still one waiver in force.
            if waived and suppressed:
                waivers_applied += 1
    return dangling, ignored, scanned, waivers_applied


def subdir_docs_by_basename(files: list[str]) -> dict[str, str]:
    """`basename -> path` for AUTHORITY `.md` docs that live BELOW the repo root.

    Two filters, both load-bearing, both added after measuring the unfiltered version:

    * **Authority set only.** Unfiltered, r5 reported 7 hits of the form "cites bare
      AGENTS.md — it lives at .codex/AGENTS.md". `.codex/AGENTS.md` is Codex's own
      config; a source comment saying "per AGENTS.md" means the cross-tool behaviour
      contract, which is not in this repo at all. Rewriting those to `.codex/AGENTS.md`
      would have replaced a vague reference with a confidently WRONG one. The gate
      governs the authority set, so r5 resolves against the authority set.
    * **Unambiguous basenames only, and never one that a ROOT file already owns.**
      Exactly one authority `README.md` lives in a subdirectory
      (`docs/plans/v1.5/README.md`), so the naive version resolved all 14 bare
      `README.md` mentions — which plainly mean the repo's own README — to the v1.5
      plan index. Same failure shape as the `AGENTS.md` case above: unique-in-subdirs
      is not the same as unambiguous. A basename that also exists at the root belongs
      to the root.
    """
    root_names = {f for f in files if "/" not in f}
    seen: dict[str, list[str]] = {}
    for rel in files:
        if not rel.endswith(".md") or "/" not in rel or not is_authority_doc(rel):
            continue
        name = Path(rel).name
        if name in root_names:
            continue
        seen.setdefault(name, []).append(rel)
    return {name: paths[0] for name, paths in seen.items() if len(paths) == 1}


def check_r5(files: list[str], subdir_docs: dict[str, str]) -> list[str]:
    """Flag `see FOO.md` when FOO.md actually lives at `some/dir/FOO.md`."""
    bad = []
    for rel in files:
        if Path(rel).suffix not in CITING_SUFFIXES:
            continue
        lines = read_lines(rel)
        if lines is None:
            continue
        here = Path(rel).parent.as_posix()
        for n, line in enumerate(lines, 1):
            if WAIVER_RE.search(line):
                continue
            for m in BARE_DOC_RE.finditer(line):
                name = m.group(1)
                target = subdir_docs.get(name)
                if target is None:
                    continue
                # A sibling reference is the correct spelling from inside the same
                # directory, and `docs/INDEX.md` legitimately names its neighbours.
                if Path(target).parent.as_posix() == here:
                    continue
                # Already written in full somewhere on this line — r2 owns that form.
                if target in line:
                    continue
                bad.append(f"r5 {rel}:{n} cites bare {name} — it lives at {target}")
    return bad


def index_forms(rel: str) -> tuple[str, ...]:
    """Every spelling a link to `rel` may legitimately take inside `docs/INDEX.md`.

    docs/INDEX.md lives in `docs/`, so a relative link is the CORRECT form and the gate
    must read it the way a markdown renderer would — matching only the repo-relative
    path would force every entry to be written in a form that does not resolve when
    clicked.
    """
    if rel.startswith("docs/"):
        return (rel, rel[len("docs/") :])
    return (rel, "../" + rel)


def check_r3(docs: list[str]) -> list[str]:
    index = read_lines(INDEX)
    if index is None:
        return [f"r3 {INDEX} is missing — the doc map is the entry point (R4)"]
    body = "\n".join(index)
    missing = []
    for rel in docs:
        if rel == INDEX or any(rel.startswith(a) for a in ARCHIVE_MARKERS):
            continue
        if not any(form in body for form in index_forms(rel)):
            missing.append(f"r3 {rel} is not linked from {INDEX}")
    return missing


def main() -> int:
    files = tracked_files()
    docs = sorted(f for f in files if is_authority_doc(f))

    if not files or not docs:
        print(f"FAILED:docscheck empty walk (tracked={len(files)} authority-docs={len(docs)})")
        return 1

    violations: list[str] = []
    violations += check_r1(docs)
    dangling, ignored, scanned, waivers = check_r2_r4(files)
    if scanned == 0:
        print("FAILED:docscheck zero citing files scanned — the extractor is broken")
        return 1
    violations += dangling
    violations += ignored
    violations += check_r3(docs)
    violations += check_r5(files, subdir_docs_by_basename(files))

    counts = {"r1": 0, "r2": 0, "r3": 0, "r4": 0, "r5": 0}
    for v in violations:
        counts[v.split(" ", 1)[0]] += 1

    for v in violations:
        print(v)
    # `waivers=` is REPORTED, not hand-counted. Three separate prose claims about how
    # many waivers this repo carries were wrong at review time, each in a different
    # direction, because `git grep -c ssot-allow:` also counts the regex literal and
    # the docstring that explains the idiom — use-vs-mention. A generated number
    # cannot drift from the thing it counts.
    print(
        f"docscheck: authority-docs={len(docs)} citing-files-scanned={scanned} "
        f"waivers-applied={waivers} "
        f"r1={counts['r1']} r2={counts['r2']} r3={counts['r3']} r4={counts['r4']} "
        f"r5={counts['r5']}"
    )
    if violations:
        print(f"FAILED:docscheck {len(violations)} violation(s)")
        return 1
    print("SUCCESS:docscheck")
    return 0


if __name__ == "__main__":
    sys.exit(main())
