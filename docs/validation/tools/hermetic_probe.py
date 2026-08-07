"""Run the DEFAULT (non-e2e) sidecar suite with network egress BLOCKED.

ci-hygiene.md 2: "Hermetic CI = block egress + verify a committed snapshot store."
The get-pip.py incident showed the suite silently reaching the network: 14 tests
pre-staged a dummy cache, the manager re-verified it, discarded it, and REFETCHED
the real 2.2 MB rolling artifact -- so an upstream rotation turned the blocking
gate red. Nothing detected that the suite was non-hermetic.

This blocks socket creation at the stdlib seam and runs the suite. Every failure it
reports is a test that reaches the network and would break the gate the next time
that endpoint moves, rate-limits, or goes down.

Usage:  python .audit/hermetic_probe.py [extra pytest args...]
"""

from __future__ import annotations

import socket
import sys
from pathlib import Path


def _find_root() -> Path:
    """Walk up to the repo root rather than assuming a fixed depth.

    Authored at `.audit/` where `parent.parent` IS the root; it now lives at
    `docs/validation/tools/`, where that same expression resolves to
    `docs/validation/`. This is the SECOND tool in this directory to hit that, so it
    is anchored on markers that exist only at the root instead.
    """
    here = Path(__file__).resolve()
    for cand in (here.parent, *here.parents):
        if (cand / ".git").exists() and (cand / "sidecar/pyproject.toml").is_file():
            return cand
    raise SystemExit(f"FAILED:hermetic-probe cannot locate the repo root from {here}")


SIDECAR = _find_root() / "sidecar"


class _BlockedSocket(socket.socket):
    def __init__(self, *a: object, **k: object) -> None:  # noqa: D107
        raise OSError("EGRESS BLOCKED (hermetic_probe): this test reaches the network")


def _blocked(*_a: object, **_k: object) -> object:
    raise OSError("EGRESS BLOCKED (hermetic_probe): this test reaches the network")


def main() -> int:
    sys.path.insert(0, str(SIDECAR))
    socket.socket = _BlockedSocket  # type: ignore[misc,assignment]
    socket.create_connection = _blocked  # type: ignore[assignment]
    socket.getaddrinfo = _blocked  # type: ignore[assignment]

    import pytest

    args = sys.argv[1:] or ["tests", "-q", "--no-header", "-p", "no:cacheprovider"]
    return int(pytest.main(args))


if __name__ == "__main__":
    raise SystemExit(main())
