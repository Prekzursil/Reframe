"""Import-hygiene guard helper — checks a module pulls no heavy native backend.

The "no heavy import at load" guards must measure what importing a SPECIFIC
module pulls in, NOT the state of the shared pytest ``sys.modules`` (which other
tests legitimately pollute — e.g. the real GPU device probe imports ``torch`` at
runtime on a machine where torch is installed). Asserting ``"torch" not in
sys.modules`` in-process therefore passes only when torch happens to be
uninstalled (CI) and flakes locally.

Running the import in a CLEAN subprocess (a fresh interpreter that imports ONLY
the module under test) makes the guard a true, environment-independent statement
about the module's import graph.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Iterable


def assert_module_import_is_light(modules: str | Iterable[str], banned: Iterable[str]) -> None:
    """Assert importing ``modules`` in a fresh interpreter pulls no ``banned`` module.

    ``modules`` is one dotted module path or an iterable of them; ``banned`` is the
    set of heavy backends that must NOT appear in the child's ``sys.modules`` after
    the import. Raises ``AssertionError`` (with the leaked names) on violation, or
    surfaces the child's stderr if the import itself fails.
    """
    targets = [modules] if isinstance(modules, str) else list(modules)
    banned_tuple = tuple(banned)
    import_lines = "\n".join(f"import {m}" for m in targets)
    code = (
        f"{import_lines}\n"
        "import sys\n"
        f"_banned = {banned_tuple!r}\n"
        "_leaked = sorted(m for m in _banned if m in sys.modules)\n"
        "sys.exit('LEAKED ' + ','.join(_leaked) if _leaked else 0)"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, (
        f"import of {targets} leaked a heavy backend or failed:\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}"
    )
