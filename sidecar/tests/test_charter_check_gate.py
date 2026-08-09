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

REPO_ROOT = Path(__file__).resolve().parents[2]
CHARTER_CHECK_PY = REPO_ROOT / ".quality" / "charter_check.py"

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
