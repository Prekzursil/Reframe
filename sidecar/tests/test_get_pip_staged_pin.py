"""The VENDORED get-pip.py must hash to the pin the runtime enforces.

WHY THIS EXISTS. `build/python-embed-setup.ps1:127` says "Keep the three in sync" — the runtime
constant (`assets/manager.py::GET_PIP_SHA256`), the build script's `$ExpectedGetPipSha256`, and
the vendored artifact `build/python-embed/get-pip.py`. On 2026-07-30 pypa rotated the rolling
URL and TWO of the three were updated; the vendored file was not. Nothing compared them, so it
shipped.

The consequence was not cosmetic. `runtime_setup/bootstrap.py::resolve_get_pip` prefers the
STAGED copy and verifies it against the pin, failing CLOSED on a mismatch — correctly, since
get-pip.py is downloaded-then-EXECUTED. Failing closed on the staged copy means it never falls
through to the download, so EVERY fresh install died in first-run bootstrap with
`FAILED:bootstrap get-pip.py sha256 mismatch`, showing the user "Setup couldn't finish" and a
Retry button that could only fail identically. Measured on GitHub Actions run 31445248586,
step 28 (INSTALLED build cold first-run), with a real NSIS install.

This test is the missing comparison. It is hermetic — it hashes a file on disk and reads a
constant; no network, no subprocess.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from media_studio.assets.manager import GET_PIP_SHA256

#: `sidecar/tests/<this file>` -> repo root. Same idiom as test_charter_check_gate.py:46.
REPO_ROOT = Path(__file__).resolve().parents[2]
VENDORED = REPO_ROOT / "build" / "python-embed" / "get-pip.py"
EMBED_SETUP = REPO_ROOT / "build" / "python-embed-setup.ps1"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_the_vendored_get_pip_is_present() -> None:
    """A missing file would make the hash assertion below vacuous rather than red."""
    assert VENDORED.is_file(), f"the staged get-pip.py is missing at {VENDORED}"


def test_the_vendored_get_pip_matches_the_runtime_pin() -> None:
    """The staged copy bootstrap.py prefers must satisfy the pin bootstrap.py enforces.

    If this fails, a fresh install cannot bootstrap. Fix by re-staging the artifact whose
    sha256 equals GET_PIP_SHA256 — NOT by relaxing the pin to match whatever is on disk,
    which would defeat a pin on a downloaded-then-executed script.
    """
    assert _sha256(VENDORED) == GET_PIP_SHA256


def test_the_build_script_pin_matches_the_runtime_pin() -> None:
    """The third of the "three in sync": the PowerShell default must not drift either.

    Drift here is silent in a different way — the build script would stage an artifact the
    runtime then rejects, which is exactly the failure this module exists to prevent.
    """
    text = EMBED_SETUP.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"\$ExpectedGetPipSha256\s*=\s*'([0-9a-f]{64})'", text)
    assert m is not None, "could not find $ExpectedGetPipSha256 in build/python-embed-setup.ps1"
    assert m.group(1) == GET_PIP_SHA256


def test_the_vendored_get_pip_is_lf_only() -> None:
    """A CRLF byte would change the sha256 and re-open this bug in a new form.

    `.gitattributes` sets `* text=auto eol=lf`, so git normalises on commit: a CRLF working
    copy would hash differently from its blob, and the pin would match one and not the other.
    Asserting LF-only keeps the on-disk bytes and the committed bytes identical.
    """
    assert b"\r\n" not in VENDORED.read_bytes()
