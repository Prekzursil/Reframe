"""W26 — the reachability gate, and the RPC half of it that needs the LIVE registry.

Two halves, split by what each can measure exactly:

* ``.quality/reachability_check.py`` walks the TS import graph (stdlib only, no
  ``media_studio`` import), so it rides in gate:1 as a ``pre-commit`` local hook next
  to ``docs_check.py``. Its rules are exercised below against synthetic trees, and
  the REQUIRED proof — that it goes red on a component this repo really does leave
  unreachable — is a MUTATION (drop the waiver), not an assertion about a fixture.
* the sidecar RPC surface is enumerated by RUNNING ``register_all`` with a collecting
  registrar (the composition-CE pattern ``test_contract_parity.py`` uses), because a
  static scan of 14 handler modules and their nested ``register()`` calls would be a
  guess. That is why this half lives in pytest (gate:3) rather than in the script.

Neither half adds a gate: gate:1 and gate:3 both already exist, and QUALITY-CHARTER.md
rule 2 declares the 6-gate list closed.

Why any of this exists: five defects this programme fixed (W16-W20) were built,
tested and 100%-covered while mounted NOWHERE, and coverage cannot see that — an
unreachable module still executes under its own test. Coverage measures execution;
this measures reachability.
"""

from __future__ import annotations

import importlib.util
import json
import tempfile
from pathlib import Path
from types import ModuleType

import pytest
from media_studio import protocol
from media_studio.handlers import Services, register_all

REPO_ROOT = Path(__file__).resolve().parents[2]
GATE_PY = REPO_ROOT / ".quality" / "reachability_check.py"
ALLOWLIST_PATH = REPO_ROOT / ".quality" / "reachability_allowlist.json"
RENDERER_SRC = REPO_ROOT / "app" / "renderer" / "src"


@pytest.fixture()
def gate() -> ModuleType:
    """Import `.quality/reachability_check.py` by path (it is not a package)."""
    spec = importlib.util.spec_from_file_location("_reachability_under_test", GATE_PY)
    assert spec is not None and spec.loader is not None, f"cannot load {GATE_PY}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def allowlist() -> dict[str, list[dict[str, str]]]:
    return json.loads(ALLOWLIST_PATH.read_text(encoding="utf-8"))


def _real_inputs(gate: ModuleType) -> tuple[list[str], object, dict[str, str]]:
    files = gate.tracked_files()

    def read(rel: str) -> str:
        return (REPO_ROOT / rel).read_text(encoding="utf-8", errors="replace")

    allowed, _methods, shape = gate.load_allowlist(ALLOWLIST_PATH.read_text(encoding="utf-8"))
    assert not shape, f"the committed allowlist is malformed: {shape}"
    return files, read, allowed


# --------------------------------------------------------------------------- #
# 1. Controls — the real configuration must PASS, and the detector must be alive.
# --------------------------------------------------------------------------- #


def test_real_tree_passes(gate: ModuleType, capsys) -> None:
    assert gate.main() == 0
    out = capsys.readouterr().out
    assert "SUCCESS:reachability" in out
    assert "u1=0 u2=0 u3=0 u4=0" in out


def test_the_graph_really_has_edges(gate: ModuleType) -> None:
    """Detector control. If the import regex or the resolver broke, every non-entry
    module would read as unreachable and the allowlist would look catastrophically
    short — a flood of findings that is really one instrument failure."""
    files, read, _allowed = _real_inputs(gate)
    graph, unresolved = gate.build_graph(files, read)
    reached = gate.reachable_from(graph, [p for p, _why in gate.ENTRY_POINTS])
    assert not unresolved, f"unresolved specifiers: {unresolved[:5]}"
    assert len(reached) > 100, f"only {len(reached)} modules reachable — the walker is broken"
    assert sum(len(v) for v in graph.values()) > 400, "implausibly few edges"


def test_every_declared_entry_point_is_a_tracked_module(gate: ModuleType) -> None:
    files, _read, _allowed = _real_inputs(gate)
    tracked = set(files)
    for path, why in gate.ENTRY_POINTS:
        assert path in tracked, f"declared entry point {path} is not tracked"
        assert why.strip(), f"entry point {path} has no written justification"


def test_alias_matches_the_two_vite_configs(gate: ModuleType) -> None:
    """`@` -> renderer/src is declared in two configs; hardcoding it here can drift."""
    for config in ("electron.vite.config.ts", "vitest.config.ts"):
        text = (REPO_ROOT / "app" / config).read_text(encoding="utf-8")
        assert "'@': resolve(__dirname, 'renderer/src')" in text, f"{config} no longer declares the @ alias"
    assert gate.ALIAS_PREFIX == "@/"
    assert gate.ALIAS_TARGET == "app/renderer/src/"


# --------------------------------------------------------------------------- #
# 2. THE REQUIRED MUTATION: the gate must fail on a KNOWN-unreachable component.
# --------------------------------------------------------------------------- #

# Components this repo really does leave unmounted today (waived, with reasons, in
# .quality/reachability_allowlist.json). Dropping a waiver is the mutation: the gate
# must then name that exact file. Asserting against a synthetic fixture would prove
# only that the fixture works.
KNOWN_UNREACHABLE = (
    "app/renderer/src/panels/TransitionPicker.tsx",
    "app/main/socialAuth.ts",
    "app/renderer/src/components/useAutosave.ts",
)


@pytest.mark.parametrize("victim", KNOWN_UNREACHABLE)
def test_dropping_a_waiver_makes_the_gate_name_that_component(gate: ModuleType, victim: str) -> None:
    files, read, allowed = _real_inputs(gate)
    assert victim in allowed, f"{victim} is expected to be waived today"
    mutated = {k: v for k, v in allowed.items() if k != victim}
    violations, stats = gate.check_modules(files, read, mutated)
    assert any(v.startswith(f"u1 {victim} ") for v in violations), (
        f"the gate did NOT flag {victim}; violations={violations[:5]}"
    )
    assert stats["subjects"] > 100


def test_all_waivers_dropped_yields_exactly_the_waived_set(gate: ModuleType, allowlist) -> None:
    """The allowlist is EXACTLY the unreachable set — no more, no fewer.

    This is the no-dead-entries rule computed in both directions at once: an entry
    that became reachable shows up as a missing u1, and an unreachable module that is
    not waived shows up as an extra one.
    """
    files, read, _allowed = _real_inputs(gate)
    violations, _stats = gate.check_modules(files, read, {})
    flagged = {v.split(" ")[1] for v in violations if v.startswith("u1 ")}
    waived = {e["path"] for e in allowlist["modules"]}
    assert flagged == waived, f"only-flagged={sorted(flagged - waived)} only-waived={sorted(waived - flagged)}"


# --------------------------------------------------------------------------- #
# 3. Rule-by-rule mutations on synthetic trees.
# --------------------------------------------------------------------------- #

SYNTHETIC = {
    "app/main/main.ts": "import { boot } from './boot';\nboot();\n",
    "app/main/boot.ts": "export function boot() {}\n",
    "app/main/orphan.ts": "export function orphan() {}\n",
    "app/main/orphan.test.ts": "import { orphan } from './orphan';\n",
    "app/main/preload.ts": "export {};\n",
    "app/renderer/src/main.tsx": "export {};\n",
    "app/render-cli/src/render.ts": "export {};\n",
    "app/render-cli/src/bundle.ts": "export {};\n",
}


def _synthetic(gate: ModuleType, extra: dict[str, str] | None = None):
    tree = dict(SYNTHETIC) | (extra or {})
    return list(tree), (lambda rel: tree[rel])


def test_a_module_whose_only_importer_is_its_own_test_is_unreachable(gate: ModuleType) -> None:
    files, read = _synthetic(gate)
    violations, _stats = gate.check_modules(files, read, {})
    assert [v for v in violations if v.startswith("u1 ")] == [
        "u1 app/main/orphan.ts is not reachable from any entry point (imported by nothing)"
    ]


def test_a_comment_mentioning_a_real_module_creates_no_edge(gate: ModuleType) -> None:
    """The SILENT direction: prose must not confer reachability.

    The first draft of this gate scanned raw source, so `// see './orphan'` in a
    reachable file would have marked orphan.ts reachable and hidden it forever.
    """
    files, read = _synthetic(
        gate,
        {
            "app/main/boot.ts": "// mounting is tracked separately; see './orphan' and '../main/orphan'\nexport function boot() {}\n"
        },
    )
    violations, _stats = gate.check_modules(files, read, {})
    assert any(v.startswith("u1 app/main/orphan.ts ") for v in violations)


def test_a_block_comment_mention_creates_no_edge(gate: ModuleType) -> None:
    files, read = _synthetic(
        gate,
        {"app/main/boot.ts": "/*\n * import { orphan } from './orphan';\n */\nexport function boot() {}\n"},
    )
    violations, _stats = gate.check_modules(files, read, {})
    assert any(v.startswith("u1 app/main/orphan.ts ") for v in violations)


def test_a_real_import_still_confers_reachability(gate: ModuleType) -> None:
    """The over-tightening direction: comment stripping must not eat real imports."""
    files, read = _synthetic(
        gate, {"app/main/boot.ts": "import './orphan'; // wired here\nexport function boot() {}\n"}
    )
    violations, _stats = gate.check_modules(files, read, {})
    assert not [v for v in violations if v.startswith("u1 ")], violations


@pytest.mark.parametrize(
    ("spec_text", "label"),
    [
        ("import { orphan } from './orphan';\n", "static from"),
        ("const m = await import('./orphan');\n", "dynamic import"),
        ("const m = require('./orphan');\n", "require"),
        ("import './orphan';\n", "bare side-effect import"),
        ("import { orphan } from './orphan.js';\n", "ESM .js specifier"),
    ],
)
def test_each_import_form_confers_reachability(gate: ModuleType, spec_text: str, label: str) -> None:
    files, read = _synthetic(gate, {"app/main/boot.ts": spec_text + "export function boot() {}\n"})
    violations, _stats = gate.check_modules(files, read, {})
    assert not [v for v in violations if v.startswith("u1 ")], f"{label}: {violations}"


def test_the_at_alias_resolves(gate: ModuleType) -> None:
    files, read = _synthetic(
        gate,
        {
            "app/renderer/src/main.tsx": "import '@/panels/Deep';\n",
            "app/renderer/src/panels/Deep.tsx": "export {};\n",
        },
    )
    violations, _stats = gate.check_modules(files, read, {})
    assert not [v for v in violations if v.startswith("u1 app/renderer/src/panels/Deep.tsx")], violations


def test_a_waiver_for_a_reachable_module_is_a_dead_entry(gate: ModuleType) -> None:
    files, read = _synthetic(gate)
    violations, _stats = gate.check_modules(files, read, {"app/main/boot.ts": "stale"})
    assert any(v.startswith("u2 ") and "app/main/boot.ts" in v for v in violations), violations


def test_a_waiver_for_a_vanished_path_is_a_dead_entry(gate: ModuleType) -> None:
    files, read = _synthetic(gate)
    violations, _stats = gate.check_modules(files, read, {"app/main/deleted.ts": "stale"})
    assert any(v.startswith("u3 ") and "app/main/deleted.ts" in v for v in violations), violations


def test_a_waiver_without_a_reason_is_rejected(gate: ModuleType) -> None:
    _mods, _methods, problems = gate.load_allowlist(
        json.dumps({"modules": [{"path": "app/main/x.ts", "reason": "   "}], "rpcMethods": []})
    )
    assert any("has no written reason" in p for p in problems), problems


def test_a_duplicated_waiver_is_rejected(gate: ModuleType) -> None:
    _mods, _methods, problems = gate.load_allowlist(
        json.dumps({"modules": [{"path": "a.ts", "reason": "x"}, {"path": "a.ts", "reason": "y"}], "rpcMethods": []})
    )
    assert any("is duplicated" in p for p in problems), problems


def test_a_missing_entry_point_fails_on_the_cause_not_the_symptoms(gate: ModuleType) -> None:
    """Deleting an entry orphans its whole subtree; report the entry, not 200 files."""
    files, read = _synthetic(gate)
    files = [f for f in files if f != "app/main/main.ts"]
    violations, _stats = gate.check_modules(files, read, {})
    assert len(violations) == 1
    assert "declared entry point(s) are not tracked in-scope modules" in violations[0]
    assert "app/main/main.ts" in violations[0]


def test_strip_comments_keeps_string_literals(gate: ModuleType) -> None:
    src = "const u = 'https://example.test/x'; // drop me\nconst t = `a/*b*/c`;\n/* multi\nline */ const z = 1;\n"
    out = gate.strip_comments(src)
    assert "https://example.test/x" in out
    assert "a/*b*/c" in out
    assert "drop me" not in out
    assert "multi" not in out
    assert out.count("\n") == src.count("\n"), "line count must be preserved"


def test_non_module_suffixes_are_skipped_rather_than_unresolved(gate: ModuleType) -> None:
    files, read = _synthetic(gate, {"app/main/boot.ts": "import './boot.css';\nexport function boot() {}\n"})
    _graph, unresolved = gate.build_graph(files, read)
    assert not unresolved, unresolved


def test_an_unresolvable_relative_specifier_is_reported(gate: ModuleType) -> None:
    files, read = _synthetic(gate, {"app/main/boot.ts": "import './nope';\nexport function boot() {}\n"})
    _graph, unresolved = gate.build_graph(files, read)
    assert any("u4" in u and "./nope" in u for u in unresolved), unresolved


# --------------------------------------------------------------------------- #
# 4. The RPC half — registered methods with no renderer caller.
# --------------------------------------------------------------------------- #


def _registered_methods() -> set[str]:
    """Every live RPC method: feature handlers (collected) + protocol built-ins.

    Same ``register=`` seam as test_contract_parity._live_methods, so the global
    ``protocol.METHODS`` is never mutated.
    """
    with tempfile.TemporaryDirectory() as td:
        collected: dict[str, object] = {}
        register_all(Services(data_dir=Path(td)), register=lambda n, h: collected.__setitem__(n, h))
    return set(collected) | set(protocol.METHODS)


def _renderer_referenced(gate: ModuleType, candidates: set[str]) -> set[str]:
    """Which of ``candidates`` appear as a quoted literal in renderer PRODUCTION code.

    DELIBERATELY the loose form (any quoted occurrence), not `rpc('<name>')`. Measured:
    the strict form found 141 of the 169 registered methods and missed 21 that ARE
    called — through `bridge.rpc(...)`, a `start(method)` job helper, and per-feature
    client modules. Holding the tree to the strict form would have manufactured 21
    false "dead" findings and 21 bogus waivers.

    Direction of the residual, stated rather than hoped: loose can only UNDER-report
    deadness, so the computed dead set is a SUBSET of the truly-dead set — the gate
    can miss a dead method, never invent one. Comments are stripped first (a prose
    mention is not a call site), which closes the largest part of that gap. Still
    open, UNVERIFIED: a method name appearing as a quoted literal in some non-call
    position would read as reached. Settling experiment: a TS-aware call-graph pass
    over the `rpc()`/`bridge.rpc()` seams, which needs a pinned in-repo TS tool the
    charter's determinism rule does not admit today.
    """
    seen: set[str] = set()
    for path in RENDERER_SRC.rglob("*"):
        if path.suffix not in (".ts", ".tsx") or ".test." in path.name:
            continue
        text = gate.strip_comments(path.read_text(encoding="utf-8", errors="replace"))
        for name in candidates:
            if f"'{name}'" in text or f'"{name}"' in text or f"`{name}`" in text:
                seen.add(name)
    return seen


def test_the_rpc_detector_finds_known_present_call_sites(gate: ModuleType) -> None:
    """Control the detector before trusting any zero (single-signal-verification §3).

    Three shapes: a `client.ts` wrapper, a `bridge.rpc` feature call, and a built-in.
    """
    found = _renderer_referenced(gate, {"library.list", "assets.ensure", "ping"})
    assert found == {"library.list", "assets.ensure", "ping"}, found


def test_registered_methods_are_reached_from_the_renderer_or_waived(gate: ModuleType) -> None:
    registered = _registered_methods()
    assert len(registered) > 100, f"only {len(registered)} methods registered — the collector is broken"
    _mods, waived, problems = gate.load_allowlist(ALLOWLIST_PATH.read_text(encoding="utf-8"))
    assert not problems, problems
    unreached = registered - _renderer_referenced(gate, registered)
    unwaived = sorted(unreached - set(waived))
    assert not unwaived, (
        "registered RPC methods with no renderer call site and no waiver — mount them "
        f"or add a reasoned entry to .quality/reachability_allowlist.json: {unwaived}"
    )


def test_no_dead_rpc_waivers(gate: ModuleType) -> None:
    """Both directions, so the waiver list tracks the tree and not history."""
    registered = _registered_methods()
    _mods, waived, _problems = gate.load_allowlist(ALLOWLIST_PATH.read_text(encoding="utf-8"))
    unreached = registered - _renderer_referenced(gate, registered)
    not_registered = sorted(m for m in waived if m not in registered)
    now_reached = sorted(m for m in waived if m in registered and m not in unreached)
    assert not not_registered, f"waived methods that are not registered at all: {not_registered}"
    assert not now_reached, f"waived methods the renderer now calls — delete the entries: {now_reached}"


def test_the_rpc_rule_goes_red_when_a_waiver_is_dropped(gate: ModuleType) -> None:
    """MUTATION: without its waiver, a known backend-only method must be flagged."""
    registered = _registered_methods()
    _mods, waived, _problems = gate.load_allowlist(ALLOWLIST_PATH.read_text(encoding="utf-8"))
    victim = "reframe.analyze"
    assert victim in waived and victim in registered
    unreached = registered - _renderer_referenced(gate, registered)
    unwaived = unreached - (set(waived) - {victim})
    assert unwaived == {victim}, unwaived
