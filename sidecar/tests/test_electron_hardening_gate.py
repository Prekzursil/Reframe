"""W66 — both-states proof for `.quality/electron_hardening_check.py`.

The gate reads two files that decide whether the SHIPPED binary is hardened, so a
silent no-op here is worse than no gate: `docs/plans/v1.5/PROGRAM.md` already recorded
"ASAR-integrity fuses + Electronegativity CI ... SHIPPED" while
`electron-builder.yml` declared no `electronFuses` block at all.

Rides the existing gate:3 pytest step; `.quality/` is outside `--cov=media_studio`, so
importing it here changes no coverage number (same arrangement as
`test_charter_check_gate.py`).

The `refuses` trap is pinned explicitly: the programme has a RECORDED detector failure
where a search for `fuses` matched the substring in "re​fuses", and this repo is
full of the word. `test_the_naive_substring_probe_is_the_trap_and_the_anchor_avoids_it`
demonstrates both halves rather than asserting that the anchor is fine.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GATE_PY = REPO_ROOT / ".quality" / "electron_hardening_check.py"
BUILDER_YML = REPO_ROOT / "electron-builder.yml"
MAIN_TS = REPO_ROOT / "app" / "main" / "main.ts"


@pytest.fixture()
def gate() -> ModuleType:
    spec = importlib.util.spec_from_file_location("_electron_hardening_under_test", GATE_PY)
    assert spec is not None and spec.loader is not None, f"cannot load {GATE_PY}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def yml() -> str:
    return BUILDER_YML.read_text(encoding="utf-8")


@pytest.fixture()
def main_ts() -> str:
    return MAIN_TS.read_text(encoding="utf-8")


# --- controls ---------------------------------------------------------------------


def test_real_configuration_passes(gate: ModuleType, capsys) -> None:
    assert gate.main() == 0
    out = capsys.readouterr().out
    assert "SUCCESS:electronhardening" in out
    assert "e1=0 e2=0" in out


def test_every_required_fuse_is_actually_found(gate: ModuleType, yml: str) -> None:
    """Detector control: prove each anchored pattern finds a KNOWN-PRESENT item."""
    for key, (want, why) in gate.REQUIRED_FUSES.items():
        match = gate.fuse_line_re(key).search(yml)
        assert match is not None, f"the pattern for {key} finds nothing — the detector is broken ({why})"
        assert match.group("value") == want


def test_the_webprefs_triple_is_actually_found(gate: ModuleType, main_ts: str) -> None:
    for key, want in gate.REQUIRED_WEBPREFS.items():
        match = gate.webpref_line_re(key).search(main_ts)
        assert match is not None, f"the pattern for {key} finds nothing in main.ts"
        assert match.group("value") == want


def test_run_as_node_is_pinned_true_on_purpose(gate: ModuleType) -> None:
    """The one fuse whose correct value is the insecure-looking one.

    `false` is the usual hardening default and would break every animated caption
    render: the sidecar spawns the ELECTRON EXE as plain Node
    (CONTRACTS.md:187, docs/wiring/WIRING-T4A.md:51, app/main/sidecar.ts:154).
    """
    want, why = gate.REQUIRED_FUSES["runAsNode"]
    assert want == "true"
    assert "ELECTRON_RUN_AS_NODE" in why


def test_the_naive_substring_probe_is_the_trap_and_the_anchor_avoids_it(gate: ModuleType) -> None:
    """The recorded detector failure, demonstrated in both directions."""
    decoy = "  # the updater refuses a downgrade\n  runAsNode: true\n"
    assert "fuses" in "refuses", "control: the substring trap is real"
    assert decoy.count("fuses") == 1, "the decoy really does contain the trap substring"
    assert gate._FUSES_BLOCK_RE.search(decoy) is None, "the anchored block probe matched a prose line"
    assert gate.fuse_line_re("runAsNode").search(decoy) is not None, "the anchor lost the real line"


# --- e1 mutations: every one must go RED ------------------------------------------


def test_a_missing_fuses_block_is_caught(gate: ModuleType, yml: str) -> None:
    problems = gate.check_fuses(yml.replace("electronFuses:", "# electronFuses:"))
    assert len(problems) == 1
    assert "declares no `electronFuses:` block" in problems[0]


@pytest.mark.parametrize("key", ["enableEmbeddedAsarIntegrityValidation", "onlyLoadAppFromAsar", "runAsNode"])
def test_flipping_a_required_fuse_is_caught(gate: ModuleType, yml: str, key: str) -> None:
    want, _why = gate.REQUIRED_FUSES[key]
    flipped = "false" if want == "true" else "true"
    mutated = gate.fuse_line_re(key).sub(f"  {key}: {flipped}", yml, count=1)
    assert mutated != yml, f"the mutation anchor for {key} did not apply"
    problems = gate.check_fuses(mutated)
    assert any(key in p and f"is {flipped}" in p for p in problems), problems


@pytest.mark.parametrize("key", ["enableNodeOptionsEnvironmentVariable", "enableNodeCliInspectArguments"])
def test_deleting_a_required_fuse_is_caught(gate: ModuleType, yml: str, key: str) -> None:
    mutated = gate.fuse_line_re(key).sub("  # removed", yml, count=1)
    assert mutated != yml
    problems = gate.check_fuses(mutated)
    assert any(f"does not declare fuse `{key}`" in p for p in problems), problems


def test_losing_asar_true_is_caught(gate: ModuleType, yml: str) -> None:
    """Integrity validation with no asar to validate is decoration."""
    mutated = gate._ASAR_TRUE_RE.sub("asar: false", yml, count=1)
    assert mutated != yml
    problems = gate.check_fuses(mutated)
    assert any("does not set `asar: true`" in p for p in problems), problems


def test_a_trailing_comment_on_a_fuse_line_still_parses(gate: ModuleType, yml: str) -> None:
    """Over-tightening direction: the anchor must tolerate a normal YAML comment."""
    mutated = gate.fuse_line_re("runAsNode").sub("  runAsNode: true  # keep, see the note above", yml, count=1)
    assert mutated != yml
    assert not gate.check_fuses(mutated)


# --- e2 mutations -----------------------------------------------------------------


@pytest.mark.parametrize("key", ["contextIsolation", "nodeIntegration", "sandbox"])
def test_flipping_the_renderer_sandbox_is_caught(gate: ModuleType, main_ts: str, key: str) -> None:
    want = gate.REQUIRED_WEBPREFS[key]
    flipped = "false" if want == "true" else "true"
    mutated = gate.webpref_line_re(key).sub(f"      {key}: {flipped},", main_ts, count=1)
    assert mutated != main_ts, f"the mutation anchor for {key} did not apply"
    problems = gate.check_webprefs(mutated, {"app/main/main.ts": mutated})
    assert any(key in p and f"declares `{key}: {flipped}`" in p for p in problems), problems


def test_deleting_a_webpref_is_caught(gate: ModuleType, main_ts: str) -> None:
    mutated = gate.webpref_line_re("sandbox").sub("      // sandbox removed", main_ts, count=1)
    assert mutated != main_ts
    problems = gate.check_webprefs(mutated, {"app/main/main.ts": mutated})
    assert any("no longer declares `sandbox: true`" in p for p in problems), problems


@pytest.mark.parametrize(
    ("key", "value"),
    [("webSecurity", "false"), ("allowRunningInsecureContent", "true")],
)
def test_a_banned_webpref_anywhere_under_app_main_is_caught(
    gate: ModuleType, main_ts: str, key: str, value: str
) -> None:
    rogue = (
        "export function openHelp() {\n  return {\n    webPreferences: {\n      "
        + f"{key}: {value},\n"
        + "    },\n  };\n}\n"
    )
    problems = gate.check_webprefs(main_ts, {"app/main/main.ts": main_ts, "app/main/rogue.ts": rogue})
    assert any("app/main/rogue.ts" in p and key in p for p in problems), problems


def test_the_safe_direction_of_a_banned_webpref_is_not_flagged(gate: ModuleType, main_ts: str) -> None:
    """`webSecurity: true` is the hardened value and must NOT be reported."""
    fine = "const wp = {\n      webSecurity: true,\n};\n"
    problems = gate.check_webprefs(main_ts, {"app/main/main.ts": main_ts, "app/main/fine.ts": fine})
    assert not problems, problems
