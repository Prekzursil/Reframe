"""W30 — the charter/workflow gate-parity check must count REAL step names only.

``.quality/charter_check.py`` regexed the RAW ``quality.yml`` TEXT for ``gate-<slug>``,
so a slug written in a YAML COMMENT counted as a live workflow step. That set is then
used in BOTH directions by ``main()`` (charter -> workflow, then the reverse-direction
loop), so a gate whose step was renamed, commented out, or deleted still satisfied
the forward check for as long as its slug survived anywhere in the file — including in a
comment written to explain why the step exists. At that point the charter/quality.yml
SSOT silently stops meaning anything, which is the one thing this gate exists to prevent.

The fix is scoped deliberately: the gate list in ``QUALITY-CHARTER.md`` is a CLOSED set of
6 with a one-in/one-out rule (charter §15, §40), so this adds no 7th gate and does not
relax the charter — it only makes the existing parser structural.

The first shipped fix only required a ``name:`` KEY, which an adversarial review then showed
was still a silent pass for three other phantom shapes -- a ``with:`` block ``name:`` (an
upload-artifact name), a JOB-level ``name:``, and a ``name:`` line inside a ``run: |`` block
scalar. Each of those made ``main()`` return 0 with every real ``gate-tests-coverage`` step
renamed away. ``PHANTOM_VECTORS`` below pins all of them; they go RED against the pre-fix
parser and are the reason a step name must now be a SEQUENCE ITEM (``- name:``) outside any
block scalar.

Four states are asserted here:

1. the REAL 6-gate configuration still PASSES (control — the fix must not over-tighten);
2. a gate that exists ONLY in a comment FAILS end to end (the original defect, now caught);
3. no phantom shape in ``PHANTOM_VECTORS`` can satisfy a gate, end to end;
4. the block-scalar skip TERMINATES — a real step after a ``run: |`` body is still counted
   (the over-tightening direction, which would fail loudly rather than silently);
5. every shape the module docstring DISCLOSES as unparsed only ever DROPS a slug
   (``RESIDUAL_SHAPES``) — the disclosure's direction is asserted, not just asserted-in-prose.

This module rides inside the existing ``gate-tests-coverage`` pytest step; it is not a new
gate. ``.quality/`` is outside ``--cov=media_studio``, so importing it here changes no
coverage number.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CHARTER_CHECK_PY = REPO_ROOT / ".quality" / "charter_check.py"
PRECOMMIT_CONFIG = REPO_ROOT / ".pre-commit-config.yaml"

# The slugs that quality.yml really declares as step names today. `secrets` is absent on
# purpose: it rides inside the gate-lint-format pre-commit step (charter_check.COVERED_BY).
REAL_STEP_SLUGS = {"lint-format", "types", "tests-coverage", "sast", "deps"}


@pytest.fixture()
def charter_check() -> ModuleType:
    """Import `.quality/charter_check.py` by path (it is not an installed package)."""
    spec = importlib.util.spec_from_file_location("_charter_check_under_test", CHARTER_CHECK_PY)
    assert spec is not None and spec.loader is not None, f"cannot load {CHARTER_CHECK_PY}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --- state 1: the real configuration must still pass -------------------------------


def test_real_configuration_still_passes(charter_check: ModuleType, capsys) -> None:
    assert charter_check.main() == 0
    assert "charter_check: OK" in capsys.readouterr().out


def test_real_step_names_are_all_found(charter_check: ModuleType) -> None:
    text = charter_check.WORKFLOW.read_text(encoding="utf-8")
    assert charter_check.parse_workflow_gate_steps(text) == REAL_STEP_SLUGS


# --- state 2: a mention must NOT satisfy the check ----------------------------------


def test_slug_in_a_whole_line_comment_is_not_a_step(charter_check: ModuleType) -> None:
    text = "\n".join(
        [
            "jobs:",
            "  quality:",
            "    steps:",
            "      # gate-ghost is covered inside the pre-commit step below",
            "      - name: gate-lint-format (pre-commit run --all-files)",
            "        run: pre-commit run --all-files",
        ]
    )
    assert charter_check.parse_workflow_gate_steps(text) == {"lint-format"}


def test_trailing_comment_cannot_inject_a_slug(charter_check: ModuleType) -> None:
    text = "      - name: gate-types tsc app  # gate-ghost is covered elsewhere\n"
    assert charter_check.parse_workflow_gate_steps(text) == {"types"}


def test_run_body_mention_is_not_a_step(charter_check: ModuleType) -> None:
    text = "      - name: gate-sast opengrep\n        run: echo gate-ghost && opengrep scan\n"
    assert charter_check.parse_workflow_gate_steps(text) == {"sast"}


# --- state 3: no phantom `name:` SHAPE may satisfy a gate ---------------------------
#
# Each entry is YAML appended to a quality.yml whose real `gate-tests-coverage` steps have
# been renamed away. Against the pre-fix parser every one of these returned 0.
PHANTOM_VECTORS: dict[str, str] = {
    "with-block artifact name": (
        "      - name: upload the coverage report\n"
        "        uses: actions/upload-artifact@v4\n"
        "        with:\n"
        "          name: gate-tests-coverage\n"
        "          path: coverage/\n"
    ),
    "job-level name": ("  other:\n    name: gate-tests-coverage\n    runs-on: ubuntu-latest\n"),
    "plain name: in a run body": (
        "      - name: echo a workflow template\n"
        "        run: |\n"
        "          cat <<'YAML'\n"
        "          name: gate-tests-coverage\n"
        "          YAML\n"
    ),
    "sequence-item name: in a run body": (
        "      - name: echo a workflow template\n"
        "        run: |\n"
        "          cat <<'YAML'\n"
        "          - name: gate-tests-coverage\n"
        "          YAML\n"
    ),
}


@pytest.mark.parametrize("vector", sorted(PHANTOM_VECTORS), ids=sorted(PHANTOM_VECTORS))
def test_phantom_name_shape_cannot_satisfy_a_gate(
    vector: str,
    charter_check: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    """Rename every real `gate-tests-coverage` STEP, then inject the phantom shape.

    The gate must still go RED. This is the direct refutation of the earlier residual
    wording ("loud in both directions, never a silent pass") — it was measurably false for
    all four shapes.
    """
    real = charter_check.WORKFLOW.read_text(encoding="utf-8")
    mutated = real.replace("- name: gate-tests-coverage", "- name: tests-coverage")
    assert "gate-tests-coverage" not in mutated, "a real step name survived the rename"
    mutated += PHANTOM_VECTORS[vector]

    workflow = tmp_path / "quality.yml"
    workflow.write_text(mutated, encoding="utf-8")
    monkeypatch.setattr(charter_check, "WORKFLOW", workflow)

    assert charter_check.main() == 1
    assert "charter gate 'tests-coverage' has no matching" in capsys.readouterr().out


# --- state 4: the block-scalar skip must TERMINATE ----------------------------------


def test_block_scalar_skip_ends_at_the_next_step(charter_check: ModuleType) -> None:
    """A real step following a `run: |` body is still a step (no over-skipping)."""
    text = "\n".join(
        [
            "      - name: gate-sast opengrep",
            "        run: |",
            "          opengrep scan \\",
            "            --config .quality/opengrep",
            "",
            "      - name: gate-deps osv-scanner",
            "        run: osv-scanner scan source",
        ]
    )
    assert charter_check.parse_workflow_gate_steps(text) == {"sast", "deps"}


# --- the DISCLOSED residuals must only ever DROP, never ADD -------------------------
#
# The module docstring names three shapes this line walker does not parse. That
# disclosure is only worth anything if its DIRECTION holds: a shape may cost us a real
# slug (loud — the charter -> workflow check then fails) but must never manufacture one
# (silent — the failure mode this whole lane exists to remove). `expected` is what the
# walker really returns; `truth` is what a YAML parser would say.
RESIDUAL_SHAPES: dict[str, tuple[str, set[str], set[str]]] = {
    # yaml, walker result, real-YAML truth
    "quoted scalar containing ' #'": (
        '      - name: "gate-types # and gate-ghost"\n',
        {"types"},
        {"types", "ghost"},
    ),
    "flow-style step mapping": (
        "      - {name: gate-ghost, run: 'true'}\n",
        set(),
        {"ghost"},
    ),
    "explicit block-scalar indent indicator": (
        "      - name: gate-sast opengrep\n"
        "        run: |2\n"
        "            - name: gate-ghost\n"
        "      - name: gate-deps osv\n",
        {"sast", "deps"},
        {"sast", "deps"},
    ),
}


@pytest.mark.parametrize("shape", sorted(RESIDUAL_SHAPES), ids=sorted(RESIDUAL_SHAPES))
def test_disclosed_residual_never_adds_a_phantom_slug(shape: str, charter_check: ModuleType) -> None:
    text, expected, truth = RESIDUAL_SHAPES[shape]
    got = charter_check.parse_workflow_gate_steps(text)
    assert got == expected
    assert not (got - truth), f"{shape} ADDED a phantom slug: {sorted(got - truth)}"


# --- the gate-1 local hooks must be DECLARED, not just described ---------------------
#
# `charter_check.py` reads QUALITY-CHARTER.md and quality.yml only. The three stdlib
# checkers the gate-1 charter row names ride INSIDE the pre-commit step, so nothing —
# not charter_check, not either gate's own test module — asserted that
# `.pre-commit-config.yaml` still declares them. Deleting a `- id:` block was therefore
# invisible: the charter would keep advertising a checker that no longer runs, which is
# the same charter-stops-meaning-anything failure the rest of this module exists to catch.
#
# Parsed with `yaml.safe_load` — the loader pre-commit itself uses — for the same reason
# the W30 fix went structural.
#
# REFUTED wording, kept so it is not re-derived: this comment first read "a substring search
# would be satisfied by the several COMMENTS in that file that name these hooks by id".
# Measured over the real file: exactly ONE comment line names exactly ONE of the three ids
# (`.pre-commit-config.yaml:79`, "Same reasoning as docs-check above"), and
# `reachability-check` / `electron-hardening-check` appear in NO comment at all — so "the
# several COMMENTS", plural both ways, is false. The decision to parse structurally is still
# right, for a reason that sentence did not give: every hook's own `name:` value repeats its
# id verbatim (`:72`, `:89`, `:101`), so a substring search for an id is satisfied by the
# hook's LABEL rather than by its declaration.
#
# REFUTED implementation, likewise recorded: the first structural version was a pair of
# line-positional regexes, and an adversarial review measured it wrong in BOTH directions.
#   * `entry:` captured the raw remainder of the line INCLUDING a trailing ` #` comment,
#     while the assertion below is a containment test — so `entry: true  # python
#     .quality/docs_check.py` was GREEN while pre-commit executed `true`. That is the W30
#     use-vs-mention defect in the ENTRY position, committed by the fix written to close it
#     in the ID position (`.quality/docs_check.py:33-37` records the same class).
#   * `id:` was read positionally, so a hook whose keys were reordered (legal — YAML mapping
#     keys are unordered) reported as MISSING, a folded `entry: >-` reported its entry as
#     `">-"`, and a `- id: ghost-check` nested under `args:` registered as a declared hook.
# `ENTRY_HOLE_VECTORS` (3), `PARSER_FALSE_RED_VECTORS` (2) and the `nested args:` mention
# vector (1) pin six vectors between them. Measured by swapping this loader back out for
# the retired regex and re-running: all six go RED against the regex and GREEN against the
# loader, so they discriminate. The `entry: key` mention vector does NOT — it behaves
# identically under both — and says so where it is declared.

# hook id -> the script its `entry:` must invoke.
GATE1_LOCAL_HOOKS = {
    "docs-check": ".quality/docs_check.py",
    "reachability-check": ".quality/reachability_check.py",
    "electron-hardening-check": ".quality/electron_hardening_check.py",
}


def parse_precommit_hooks(text: str) -> dict[str, str]:
    """id -> entry, for every hook really declared under ``repos[].hooks[]``.

    Scope, so this is not read as more: it proves the hook is DECLARED with an entry that
    names the expected script. It does NOT prove pre-commit executes it — `stages:`,
    `always_run`, and the top-level `exclude:` are not modelled here, and no pre-commit
    process is spawned (this suite is hermetic and offline). A non-string `entry:` (`true`,
    a list, absent) normalises to `""`, which FAILS the containment assertion below rather
    than passing it; that is the direction a neutered hook must fall in.
    """
    document = yaml.safe_load(text)
    hooks: dict[str, str] = {}
    if not isinstance(document, dict):
        return hooks
    repos = document.get("repos")
    if not isinstance(repos, list):
        return hooks
    for repo in repos:
        if not isinstance(repo, dict):
            continue
        declared = repo.get("hooks")
        if not isinstance(declared, list):
            continue
        for hook in declared:
            if not isinstance(hook, dict):
                continue
            hook_id = hook.get("id")
            if not isinstance(hook_id, str):
                continue
            entry = hook.get("entry")
            hooks[hook_id] = entry if isinstance(entry, str) else ""
    return hooks


def gate1_hook_violations(text: str) -> list[str]:
    """Exactly the failures the assertion below reports, as data.

    Shared so the both-states controls pin the REAL verdict instead of re-implementing it —
    a control that drifts from the assertion it guards proves nothing about the assertion.
    """
    hooks = parse_precommit_hooks(text)
    problems = [f"missing hook {hook_id}" for hook_id in sorted(set(GATE1_LOCAL_HOOKS) - set(hooks))]
    problems += [
        f"hook {hook_id!r} no longer runs {script} (entry is {hooks[hook_id]!r})"
        for hook_id, script in sorted(GATE1_LOCAL_HOOKS.items())
        if hook_id in hooks and script not in hooks[hook_id]
    ]
    return problems


def test_gate1_local_hook_ids_are_declared_in_precommit_config() -> None:
    """The three stdlib checkers the gate-1 charter row names are really wired."""
    problems = gate1_hook_violations(PRECOMMIT_CONFIG.read_text(encoding="utf-8"))
    assert not problems, f"QUALITY-CHARTER.md gate 1 names checkers .pre-commit-config.yaml does not run: {problems}"


def test_the_hook_id_parser_finds_known_present_ids() -> None:
    """Detector control: the parser must find ids it is known to be pointed at.

    A parser that found nothing would fail the assertion above as "missing hook" — a
    loud but WRONG diagnosis, pointing at the config when the probe is what broke. Pin the
    positive case on five unrelated hooks so a parser regression is named as such.
    """
    hooks = parse_precommit_hooks(PRECOMMIT_CONFIG.read_text(encoding="utf-8"))
    assert {"ruff", "ruff-format", "oxlint", "biome-format", "gitleaks"} <= set(hooks), sorted(hooks)
    assert hooks["docs-check"] == "python .quality/docs_check.py", hooks["docs-check"]


# The real `docs-check` entry, and the shapes that neuter the hook while leaving the real
# command visible in a trailing YAML comment. pre-commit runs the value BEFORE the ` #`;
# the retired regex captured the whole line, so all three were GREEN.
REAL_DOCS_ENTRY = "entry: python .quality/docs_check.py"
ENTRY_HOLE_VECTORS = {
    "disabled to echo, real command in the comment": (
        "entry: echo  # python .quality/docs_check.py (disabled, see the tracking issue)"
    ),
    "neutered to a no-op, real command in the comment": "entry: true  # python .quality/docs_check.py",
    "renamed, OLD name left in the comment": "entry: python .quality/docs_check_v2.py  # was .quality/docs_check.py",
}


@pytest.mark.parametrize("shape", sorted(ENTRY_HOLE_VECTORS), ids=sorted(ENTRY_HOLE_VECTORS))
def test_a_script_named_only_in_a_trailing_comment_is_caught(shape: str) -> None:
    """Both-states control for the ENTRY half: a MENTION must not satisfy the entry.

    The hook id survives in every shape, so the id half of the assertion stays green; only
    the command changes. This is the realistic way a gate-1 checker stops running — a rename
    that leaves the old path in a comment, or a temporary `true`/`echo` that outlives its
    tracking issue — and it is the shape the retired line-positional parser could not see.
    """
    real = PRECOMMIT_CONFIG.read_text(encoding="utf-8")
    mutated = real.replace(REAL_DOCS_ENTRY, ENTRY_HOLE_VECTORS[shape])
    assert mutated != real, f"anchor {REAL_DOCS_ENTRY!r} no longer exists in .pre-commit-config.yaml"
    assert "docs-check" in parse_precommit_hooks(mutated), "the mutation must neuter the entry, not the id"
    assert gate1_hook_violations(mutated), f"{shape} left the gate GREEN"


# Legal rewrites that are the SAME configuration to pre-commit. anchor -> replacement.
PARSER_FALSE_RED_VECTORS = {
    "folded block scalar entry": (
        "entry: python .quality/reachability_check.py",
        "entry: >-\n          python .quality/reachability_check.py",
    ),
    "id: written after entry: in the same hook": (
        "      - id: docs-check\n"
        "        name: docs-check (SSOT anti-drift R1-R5)\n"
        "        entry: python .quality/docs_check.py\n",
        "      - name: docs-check (SSOT anti-drift R1-R5)\n"
        "        entry: python .quality/docs_check.py\n"
        "        id: docs-check\n",
    ),
}


@pytest.mark.parametrize("shape", sorted(PARSER_FALSE_RED_VECTORS), ids=sorted(PARSER_FALSE_RED_VECTORS))
def test_semantically_identical_yaml_does_not_go_red(shape: str) -> None:
    """The over-tightening direction: a legal rewrite must not be reported as a broken hook.

    YAML mapping keys are unordered and a folded scalar is just a wrapped string, so both
    shapes below run exactly what the real file runs. The retired regex reported the first as
    ``reachability-check no longer runs ... (entry is '>-')`` and the second as ``missing hook
    docs-check`` — loud, and pointing at the config when the probe was what broke.
    """
    anchor, rewrite = PARSER_FALSE_RED_VECTORS[shape]
    real = PRECOMMIT_CONFIG.read_text(encoding="utf-8")
    assert anchor in real, f"anchor for {shape} no longer exists in .pre-commit-config.yaml"
    problems = gate1_hook_violations(real.replace(anchor, rewrite))
    assert not problems, f"{shape} is the same config to pre-commit, but the parser reports: {problems}"


@pytest.mark.parametrize(
    ("mention", "entry_owner_mutated"),
    [
        ("      # - id: ghost-check\n", False),
        ("  # the ghost-check hook was removed, see the tracking issue\n", False),
        ("        name: ghost-check (a hook NAME is not an id)\n", False),
        ("        entry: python .quality/ghost_check.py\n", True),
        ("        args:\n          - --config\n          - id: ghost-check\n", False),
    ],
    ids=["commented sequence item", "prose comment", "name: key", "entry: key", "nested args: sequence item"],
)
def test_a_mentioned_hook_id_is_not_a_declared_hook(mention: str, entry_owner_mutated: bool) -> None:
    """Both-states control: a MENTION must not satisfy the assertion above.

    This is the W30 defect in its pre-commit form. Each vector is appended to the real
    config; none may make `ghost-check` appear as a declared hook.

    The second column exists because the `entry:` vector passed for the WRONG reason: an
    `entry:` appended at hook-key indentation cannot create a hook, it silently gives the
    LAST declared hook (`gitleaks`, which declares no `entry:` of its own) that command. So
    "ghost-check is absent" was a tautology there; asserting the side effect makes it a
    measurement. Scope of that row, measured and stated so it is not read as more: BOTH the
    retired regex and this loader reassign `gitleaks` identically, so it pins behaviour and
    does NOT discriminate between the two parsers. The `args:` vector is the one that does —
    it is the shape a line-positional parser got wrong in the other direction, registering
    `ghost-check` as a declared hook.
    """
    real = PRECOMMIT_CONFIG.read_text(encoding="utf-8")
    before = parse_precommit_hooks(real)
    after = parse_precommit_hooks(real + mention)
    assert "ghost-check" not in after
    assert sorted(after) == sorted(before), "a mention must not change the DECLARED hook set"
    mutated = {key for key in after if before[key] != after[key]}
    assert mutated == ({"gitleaks"} if entry_owner_mutated else set()), mutated


def test_removing_a_hook_id_block_is_caught() -> None:
    """Both-states control: the KNOWN-BROKEN state must go red.

    Delete the `- id: electron-hardening-check` line from the real config and the parser
    must stop reporting it — otherwise the assertion above could never fail.
    """
    real = PRECOMMIT_CONFIG.read_text(encoding="utf-8")
    anchor = "      - id: electron-hardening-check\n"
    assert anchor in real, "anchor no longer exists in .pre-commit-config.yaml"
    hooks = parse_precommit_hooks(real.replace(anchor, ""))
    assert "electron-hardening-check" not in hooks
    assert "docs-check" in hooks, "the mutation must be surgical, not destroy the whole parse"


def test_comment_only_gate_fails_end_to_end(
    charter_check: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    """Rename every real `gate-tests-coverage` STEP but leave the slug in a comment.

    Before the fix this returned 0: the commented mention alone satisfied the forward
    charter -> workflow direction, so deleting the coverage gate from CI would have been
    invisible to the very check that exists to notice it.
    """
    real = charter_check.WORKFLOW.read_text(encoding="utf-8")
    mutated = real.replace("- name: gate-tests-coverage", "- name: tests-coverage")
    assert mutated != real, "anchor '- name: gate-tests-coverage' no longer exists in quality.yml"
    assert "gate-tests-coverage" not in mutated, "a real step name survived the rename"
    mutated += "      # gate-tests-coverage is temporarily disabled, see the tracking issue\n"

    workflow = tmp_path / "quality.yml"
    workflow.write_text(mutated, encoding="utf-8")
    monkeypatch.setattr(charter_check, "WORKFLOW", workflow)

    assert charter_check.main() == 1
    out = capsys.readouterr().out
    assert "charter gate 'tests-coverage' has no matching 'gate-tests-coverage' step" in out
