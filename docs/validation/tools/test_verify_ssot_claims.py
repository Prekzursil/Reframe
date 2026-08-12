"""Machine-independence regression for ``verify_ssot_claims.py``.

WHY THIS FILE EXISTS. ``docs/plans/v1.5/README.md`` hands every reader the command
``python docs/validation/tools/verify_ssot_claims.py`` and asserts that it "exits
non-zero and names each **registered** claim that no longer resolves as recorded".
That promise was false off ONE machine: the ``P1-shell`` INVARIANT counted PNGs under
``Path.home() / ".reframe-review" / "shell-audit"`` — an UNTRACKED scratch directory
that exists only on the author's box — so a reviewer, a CI runner, or any future
reader got exit 1 naming a claim that had not drifted at all. Its OPEN sibling
``P1-corpus`` was worse than useless off-box: it flipped to
``NOW-FIXED (retire it from OPEN_ITEMS)``, i.e. it instructed a stranger to retire a
check on the strength of a measurement that never ran — verbatim the failure the tool
itself names in the comment above its own ``P1_SCRATCH`` list.

WHAT IS ASSERTED. The verifier is run in a hermetic HOME (an empty temp dir) and must
exit 0, ``P1-shell`` must hold, and ``P1-corpus`` must not claim a fix. The scratch
corpus is genuinely untracked and cannot be re-pointed, so it must say NOT-MEASURED
rather than pretend a measurement.

DETECTOR CONTROL (this is not optional — the test is worthless without it). A test
that failed to redirect ``Path.home()`` would pass for the wrong reason, silently, on
the author's box: the real HOME does hold the scratch dir, so every assertion below
would go green while measuring nothing. ``test_home_redirection_control`` therefore
proves, through a mechanically different route (a child that prints ``Path.home()``),
that the redirection this module relies on actually takes effect. Delete it and the
rest of this file stops being evidence.

Run:  python -m pytest docs/validation/tools/test_verify_ssot_claims.py -q --no-cov
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

TOOL = Path(__file__).resolve().with_name("verify_ssot_claims.py")


def _root() -> Path:
    """Repo root, found by the same marker pair the tool under test uses."""
    for cand in (TOOL.parent, *TOOL.parents):
        if (cand / ".git").exists() and (cand / "app/package.json").is_file():
            return cand
    raise AssertionError(f"cannot locate the repo root from {TOOL}")


def _hermetic_env(home: Path) -> dict[str, str]:
    """A copy of the environment whose ONLY home is ``home``.

    ``USERPROFILE`` is what ``ntpath.expanduser`` reads first on Windows and ``HOME``
    is what ``posixpath.expanduser`` reads on Linux/macOS, so both are set; the
    ``HOMEDRIVE``/``HOMEPATH`` pair is dropped so nothing can fall back to the real
    profile behind our backs.
    """
    env = dict(os.environ)
    for var in ("HOMEDRIVE", "HOMEPATH", "XDG_CONFIG_HOME"):
        env.pop(var, None)
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    return env


def _run_verifier(home: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 — fixed argv, no shell, repo-local script
        [sys.executable, str(TOOL)],
        capture_output=True,
        text=True,
        env=_hermetic_env(home),
        cwd=str(_root()),
        check=False,
    )


def _line(stdout: str, cid: str) -> str:
    for raw in stdout.splitlines():
        if f" {cid} " in raw or raw.strip().split(" ")[1:2] == [cid]:
            return raw
    raise AssertionError(f"{cid} never printed; stdout was:\n{stdout}")


def test_home_redirection_control(tmp_path: Path) -> None:
    """CONTROL: prove the hermetic HOME really moves ``Path.home()``."""
    probe = subprocess.run(  # noqa: S603 — fixed argv, no shell
        [sys.executable, "-c", "from pathlib import Path; print(Path.home())"],
        capture_output=True,
        text=True,
        env=_hermetic_env(tmp_path),
        check=True,
    )
    assert Path(probe.stdout.strip()) == tmp_path
    assert not (tmp_path / ".reframe-review").exists()


def test_verifier_is_green_without_the_authors_scratch_dir(tmp_path: Path) -> None:
    """The documented command must reproduce for a reviewer, CI, or a later reader."""
    done = _run_verifier(tmp_path)
    assert done.returncode == 0, (
        "verify_ssot_claims.py is not reproducible off the author's machine.\n"
        f"stdout:\n{done.stdout}\nstderr:\n{done.stderr}"
    )
    assert "mismatched=0" in done.stdout, done.stdout


def test_p1_shell_asserts_a_tracked_property(tmp_path: Path) -> None:
    """``P1-shell`` must measure the tree, not one machine's scratch directory."""
    line = _line(_run_verifier(tmp_path).stdout, "P1-shell")
    assert "holds" in line, line
    assert "BROKEN" not in line, line


def test_p1_corpus_does_not_claim_a_fix_it_did_not_measure(tmp_path: Path) -> None:
    """An unmeasurable OPEN item must say so, not invite its own retirement."""
    line = _line(_run_verifier(tmp_path).stdout, "P1-corpus")
    assert "NOW-FIXED" not in line, line
    assert "NOT-MEASURED" in line, line
