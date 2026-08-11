"""Reachability gate (W26) — code that is built, tested and mounted NOWHERE.

Five defects this programme fixed (W16/W17/W18/W19/W20) were "built, tested,
100%-covered, and mounted nowhere", and the coverage gate caught **none** of them:
coverage proves a line EXECUTED under some test, which is exactly what an
unreachable module still does. Coverage cannot see unreachability. This can.

What it measures
----------------
``u1``  Every tracked production ``.ts``/``.tsx`` module under the scope roots must be
        reachable, through the import graph, from a DECLARED entry point — the four
        real process entries plus the one build script (see ``ENTRY_POINTS``). A
        module whose only importer is its own test is NOT reachable.
``u2``  No allowlist entry may name a module that IS reachable. This is the
        "allowlist tracks the tree, not history" rule: once something gets mounted,
        its waiver has to go, or the next unreachable module inherits a stale pass.
``u3``  No allowlist entry may name a path that is not a tracked in-scope module
        (a renamed/deleted file must not keep a live waiver).
``u4``  Every allowlist entry — in BOTH sections — must carry a non-empty ``reason``.
        The ``rpcMethods`` section is SHAPE-checked here and ENFORCED in
        ``sidecar/tests/test_reachability_gate.py``, which needs the live sidecar
        registry (an exact set) rather than a static guess at what is registered.

Why an allowlist at all
-----------------------
A naive "every export must be imported" rule would fail code this repo ships
unreachable ON PURPOSE — the generated RPC-contract POC artifacts, and (RPC side)
``reframe.analyze`` / ``reframe.render``, registered backend-only while the renderer
wave is unstarted. So the waiver is explicit, per-entry, and carries a written
reason; the gate's value is that the set is FROZEN and reasoned, not that it is
empty. Same guard-first shape as the W15 contrast guard.

Scope of the u1 measurement, stated so it is not read as more than it is
-----------------------------------------------------------------------
This is MODULE reachability, not per-EXPORT reachability: a module that is imported
for one symbol while three others are dead passes u1. Per-export deadness needs a TS
type-aware pass (`ts-prune`/`knip`), which is a network-fetched tool this charter's
determinism rule (rule 3) does not admit today. UNVERIFIED whether per-export
deadness exists in this tree — the settling experiment is a pinned in-repo `knip`
run, deliberately not taken here.

Direction of the residual errors, MEASURED rather than asserted: an import specifier
this walker cannot resolve is DROPPED from the graph, which can only make a module
look LESS reachable — i.e. it fails loudly (a false u1) and can never manufacture a
false pass. ``u4`` reports the count so the blind spot is a number, not a hope.
Non-TS specifiers (``.css`` side-effect imports — 109 of them in this tree) are
skipped by suffix, not by silence.

FAIL CLOSED (rules/common/ci-hygiene.md §1): a missing entry point, an empty module
walk, or a reachable set no bigger than the entry set all return non-zero. "Found
nothing, therefore pass" is a no-op gate.

Usage:  python .quality/reachability_check.py
Exit 0 when clean, 1 on any violation.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path


def _find_root() -> Path:
    """Anchor on markers that exist only at the repo root.

    Deliberately NOT ``parents[1]`` — the same third copy of this helper as
    ``docs_check.py`` and ``docs_check_mutations.py`` carry, for the same reason
    recorded there: this runs as a ``pre-commit`` ``language: system`` hook with no
    guaranteed ``sys.path``, and a gate that cannot import is a gate that does not run.
    """
    here = Path(__file__).resolve()
    for cand in (here.parent, *here.parents):
        if (cand / ".git").exists() and (cand / "app/package.json").is_file():
            return cand
    raise SystemExit(f"FAILED:reachability cannot locate the repo root from {here}")


ROOT = _find_root()
ALLOWLIST = ".quality/reachability_allowlist.json"

# --- the declared entry points ----------------------------------------------
# Each one is a REAL process/build entry, verified against the config that names it.
# Adding an entry here is how a new process gets a root; it is not a waiver.
ENTRY_POINTS: tuple[tuple[str, str], ...] = (
    (
        "app/main/main.ts",
        "electron-vite `main` build entry (app/electron.vite.config.ts:27) -> out/main/main.js = package.json `main`",
    ),
    (
        "app/main/preload.ts",
        "electron-vite `preload` build entry (app/electron.vite.config.ts:42) -> out/preload/preload.js",
    ),
    ("app/renderer/src/main.tsx", "renderer entry: app/renderer/index.html loads `/src/main.tsx` as the module script"),
    (
        "app/render-cli/src/render.ts",
        "render-cli `main`: dist/render.js, spawned by the sidecar under ELECTRON_RUN_AS_NODE=1",
    ),
    (
        "app/render-cli/src/bundle.ts",
        "render-cli `bundle` npm script (`npm run build && node dist/bundle.js`) — an app-BUILD-time entry, not dead code",
    ),
)

# Roots whose production modules must be reachable.
SCOPE_ROOTS = ("app/main/", "app/renderer/src/", "app/render-cli/src/")
TS_SUFFIXES = (".ts", ".tsx")
# Relative-import suffixes that are legitimately NOT TypeScript modules; skipped by
# suffix so their absence from the graph is a decision, not an accident.
NON_MODULE_SUFFIXES = (".css", ".scss", ".json", ".svg", ".png", ".jpg", ".webp", ".woff", ".woff2", ".html")

# `@` -> app/renderer/src, the alias declared in BOTH app/electron.vite.config.ts:60
# and app/vitest.config.ts:24. Hardcoding it here would drift from those two; it is
# asserted against them by test_reachability_gate.test_alias_matches_the_vite_configs.
ALIAS_PREFIX = "@/"
ALIAS_TARGET = "app/renderer/src/"

# Only static/dynamic ESM + CJS forms. `vi.mock()` is deliberately absent: a test
# mocking a module is not production reachability, and counting it would re-open the
# exact hole this gate closes.
#
# This regex is applied to COMMENT-STRIPPED text (see `strip_comments`), and that is
# load-bearing in the SILENT direction. The first draft scanned raw source and read
# three prose mentions of `from '../lib/rpc'` in line comments as real imports
# (client.ts:145, index.ts:2, schemas.ts:5) — use-vs-mention, the defect class this
# repo has paid for repeatedly. Those three happened to be unresolvable and so failed
# loudly, but a comment naming a REAL sibling would have manufactured a phantom edge
# and marked a dead module reachable: a silent pass, the one outcome this gate must
# not produce. `test_a_comment_mentioning_a_real_module_creates_no_edge` pins it.
IMPORT_RE = re.compile(
    r"""(?:
        \bfrom\s*['"](?P<a>[^'"]+)['"]
      | \bimport\s*\(\s*['"](?P<b>[^'"]+)['"]\s*\)
      | \bimport\s+['"](?P<c>[^'"]+)['"]
      | \brequire\s*\(\s*['"](?P<d>[^'"]+)['"]\s*\)
    )""",
    re.VERBOSE,
)


def strip_comments(text: str) -> tuple[str, bool, list[tuple[int, int]]]:
    """Blank `//` and `/* */` comments. Returns (text, desynced, string_spans).

    A character walker rather than a regex, because the two shapes that matter here
    defeat the regex forms: a `//` inside a string literal (`'https://x'`, and every
    `import ... from './x'` line contains quotes) and a `/* */` spanning lines. Each
    removed character is replaced by a space so byte offsets — and therefore any line
    numbering built on them — do not shift.

    TWO HOLES CLOSED 2026-08-11, both of which could MANUFACTURE a phantom import edge and
    thereby SILENCE a genuinely dead module (u1 going quiet is the failure that matters —
    this gate exists because W16-W20 shipped mounted nowhere):

    1. String CONTENTS are preserved verbatim — they must be, because an import specifier IS a
       string literal — and `IMPORT_RE` then ran over them, so
       `const DOC = "import { d } from './dead';"` in ANY analysed module created the edge.
       Blanking the contents is NOT the fix: it deletes every specifier and the walker's own
       no-edges sanity check fires (measured: `reachable=5`). Instead the walk now also returns
       the SPANS of every string literal, and the caller drops any `IMPORT_RE` match whose
       `import`/`require` KEYWORD begins inside one. A real import keeps its keyword in code and
       only its specifier in a string, so it is unaffected.

    2. The walker treats `'` as a string opener wherever it appears, including in JSX TEXT.
       `Checking what's ready…` therefore opened a string that never closed, and every
       comment after it in that file stopped being stripped — so a prose comment naming a
       real sibling module minted an edge. That is not fixable by a character walker without
       a JSX parser, and this hook is deliberately stdlib-only with no network, so instead it
       is now DETECTED: a file whose walk ends inside a string is reported as unanalysable
       and fails the gate loudly. Fail closed, never silently vouch.
    """
    out: list[str] = []
    spans: list[tuple[int, int]] = []
    start = -1
    i, n = 0, len(text)
    quote: str | None = None
    while i < n:
        ch = text[i]
        if quote is not None:
            out.append(ch)
            if ch == "\\" and i + 1 < n:  # an escape consumes the next char verbatim
                out.append(text[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = None
                spans.append((start, i))
            i += 1
            continue
        if ch in "'\"`":
            quote = ch
            start = i
            out.append(ch)
            i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                out.append(" ")
                i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "*":
            while i < n and not (text[i] == "*" and i + 1 < n and text[i + 1] == "/"):
                out.append("\n" if text[i] == "\n" else " ")
                i += 1
            out.append("  ")
            i += 2
            continue
        out.append(ch)
        i += 1
    if quote is not None:  # unterminated at EOF — record the open span so callers see it
        spans.append((start, n))
    return "".join(out), quote is not None, spans


def tracked_files(root: Path | None = None) -> list[str]:
    out = subprocess.run(
        ["git", "--no-optional-locks", "ls-files"],
        cwd=root or ROOT,
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    ).stdout
    return [line for line in out.splitlines() if line]


def is_test_module(rel: str) -> bool:
    """A test/type-only module: never a reachability root and never a subject."""
    name = Path(rel).name
    return ".test." in name or name.endswith(".d.ts")


def in_scope(rel: str) -> bool:
    return rel.startswith(SCOPE_ROOTS) and rel.endswith(TS_SUFFIXES) and not is_test_module(rel)


def resolve_specifier(spec: str, importer: str, modules: frozenset[str]) -> str | None:
    """Resolve a relative/aliased specifier to a tracked module path, or ``None``.

    Resolution is against the KNOWN MODULE SET rather than the filesystem, so the
    gate behaves identically on a synthetic tree in a test and on the real checkout —
    the property that lets the mutation tests plant a module without touching disk.
    """
    if spec.startswith(ALIAS_PREFIX):
        base = ALIAS_TARGET + spec[len(ALIAS_PREFIX) :]
    elif spec.startswith("."):
        base = (Path(importer).parent / spec).as_posix()
        # `Path` keeps `..` segments as-is on join; normalise them away.
        parts: list[str] = []
        for part in base.split("/"):
            if part in ("", "."):
                continue
            if part == "..":
                if parts:
                    parts.pop()
                continue
            parts.append(part)
        base = "/".join(parts)
    else:
        return None  # a bare package specifier — not our tree
    candidates = [base] if base.endswith(TS_SUFFIXES) else []
    # An ESM-style `./x.js` specifier compiles from `./x.ts`.
    if base.endswith(".js"):
        candidates += [base[: -len(".js")] + s for s in TS_SUFFIXES]
    candidates += [base + s for s in TS_SUFFIXES]
    candidates += [f"{base}/index{s}" for s in TS_SUFFIXES]
    for cand in candidates:
        if cand in modules:
            return cand
    return None


def build_graph(files: list[str], read) -> tuple[dict[str, set[str]], list[str]]:
    """``{module: {imported modules}}`` plus the unresolved relative specifiers."""
    modules = frozenset(f for f in files if f.startswith(SCOPE_ROOTS) and f.endswith(TS_SUFFIXES))
    graph: dict[str, set[str]] = {}
    unresolved: list[str] = []
    for rel in sorted(m for m in modules if not is_test_module(m)):
        text, desynced, spans = strip_comments(read(rel))
        if desynced:
            # The walk ended inside a string, so every comment after that point was NOT
            # stripped and this file's import set cannot be trusted — in the direction that
            # SILENCES a dead module. Refuse to vouch for it rather than analyse it anyway.
            unresolved.append(
                f"u4 {rel} ends inside an unterminated string literal — the scanner desynced, "
                f"so its imports cannot be trusted (a bare apostrophe in JSX text does this; "
                f"use the typographic ’)"
            )
        deps: set[str] = set()
        for match in IMPORT_RE.finditer(text):
            # Hole 1 (see strip_comments): the KEYWORD must be code, not string content.
            # `const DOC = "import { d } from './dead';"` otherwise minted a real edge and
            # silenced a genuinely dead module. A true import has its keyword outside any
            # string and only its specifier inside one, so this never drops a real edge.
            if any(lo < match.start() < hi for lo, hi in spans):
                continue
            spec = next(g for g in match.groups() if g)
            if not (spec.startswith(".") or spec.startswith(ALIAS_PREFIX)):
                continue
            if spec.endswith(NON_MODULE_SUFFIXES):
                continue
            target = resolve_specifier(spec, rel, modules)
            if target is None:
                unresolved.append(f"u4 {rel} imports {spec} — cannot be resolved to a tracked module")
            elif not is_test_module(target):
                deps.add(target)
        graph[rel] = deps
    return graph, unresolved


def reachable_from(graph: dict[str, set[str]], entries: list[str]) -> set[str]:
    seen: set[str] = set()
    stack = list(entries)
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        stack.extend(graph.get(cur, ()))
    return seen


def load_allowlist(text: str) -> tuple[dict[str, str], dict[str, str], list[str]]:
    """``(modules, rpcMethods, shape problems)`` — each mapping key -> reason."""
    problems: list[str] = []
    data = json.loads(text)
    modules: dict[str, str] = {}
    methods: dict[str, str] = {}
    for section, key, sink in (("modules", "path", modules), ("rpcMethods", "method", methods)):
        for i, entry in enumerate(data.get(section, [])):
            name = entry.get(key, "")
            reason = str(entry.get("reason", "")).strip()
            if not name:
                problems.append(f"u4 {ALLOWLIST} {section}[{i}] has no {key!r}")
                continue
            if not reason:
                problems.append(f"u4 {ALLOWLIST} {section} entry {name!r} has no written reason")
            if name in sink:
                problems.append(f"u4 {ALLOWLIST} {section} entry {name!r} is duplicated")
            sink[name] = reason
    return modules, methods, problems


def check_modules(
    files: list[str], read, allowed: dict[str, str], entries: tuple[tuple[str, str], ...] = ENTRY_POINTS
) -> tuple[list[str], dict[str, object]]:
    """Run u1/u2/u3/u4 over a module set. Returns (violations, stats)."""
    violations: list[str] = []
    subjects = sorted(f for f in files if in_scope(f))
    entry_paths = [p for p, _why in entries]

    missing_entries = [p for p in entry_paths if p not in subjects]
    if missing_entries:
        # An entry point that vanished silently orphans its whole subtree, which would
        # read as a flood of u1s pointing at innocent files. Fail on the CAUSE instead.
        violations.append(f"u1 declared entry point(s) are not tracked in-scope modules: {missing_entries}")
        return violations, {"subjects": len(subjects), "reachable": 0, "unresolved": 0}

    graph, unresolved = build_graph(files, read)
    reached = reachable_from(graph, entry_paths)

    for rel in subjects:
        if rel in reached or rel in allowed:
            continue
        importers = sorted(k for k, v in graph.items() if rel in v)
        detail = f" (imported only by {importers})" if importers else " (imported by nothing)"
        violations.append(f"u1 {rel} is not reachable from any entry point{detail}")

    for rel in sorted(allowed):
        if rel not in subjects:
            violations.append(f"u3 {ALLOWLIST} waives {rel}, which is not a tracked in-scope module")
        elif rel in reached:
            violations.append(f"u2 {ALLOWLIST} waives {rel}, which IS now reachable — delete the entry")

    violations += unresolved
    return violations, {"subjects": len(subjects), "reachable": len(reached), "unresolved": len(unresolved)}


def main() -> int:
    files = tracked_files()
    allowlist_path = ROOT / ALLOWLIST
    if not allowlist_path.is_file():
        print(f"FAILED:reachability missing {ALLOWLIST}")
        return 1

    def read(rel: str) -> str:
        return (ROOT / rel).read_text(encoding="utf-8", errors="replace")

    allowed, methods, shape = load_allowlist(allowlist_path.read_text(encoding="utf-8"))
    subjects = [f for f in files if in_scope(f)]
    if not subjects:
        print(f"FAILED:reachability empty module walk (tracked={len(files)})")
        return 1

    violations, stats = check_modules(files, read, allowed)
    violations = shape + violations

    if stats["reachable"] <= len(ENTRY_POINTS):
        # The walker found no edges at all: the import regex or the resolver is broken,
        # so every non-entry module would read as unreachable. That is a DETECTOR
        # failure, not a finding (single-signal-verification: a self-contradicting
        # output means fix the instrument before reading either number).
        print(f"FAILED:reachability the graph has no edges (reachable={stats['reachable']}) — the walker is broken")
        return 1

    counts = {"u1": 0, "u2": 0, "u3": 0, "u4": 0}
    for v in violations:
        counts[v.split(" ", 1)[0]] += 1
    for v in violations:
        print(v)
    print(
        f"reachability: modules={stats['subjects']} reachable={stats['reachable']} "
        f"entry-points={len(ENTRY_POINTS)} waived-modules={len(allowed)} waived-rpc-methods={len(methods)} "
        f"u1={counts['u1']} u2={counts['u2']} u3={counts['u3']} u4={counts['u4']}"
    )
    if violations:
        print(f"FAILED:reachability {len(violations)} violation(s)")
        return 1
    print("SUCCESS:reachability")
    return 0


if __name__ == "__main__":
    sys.exit(main())
