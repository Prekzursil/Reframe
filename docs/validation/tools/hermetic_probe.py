"""Run the DEFAULT (non-e2e) sidecar suite and report OFF-BOX egress attempts.

ci-hygiene.md 2: "Hermetic CI = block egress + verify a committed snapshot store."
This exists because the suite was silently reaching the network: 14 tests pre-staged a
dummy get-pip.py cache, the manager re-verified it, discarded it, and REFETCHED the real
2.2 MB rolling artifact -- so an upstream rotation turned the blocking gate red. Nothing
detected that the suite was non-hermetic.

CORRECTED 2026-08-08 -- the first version of this probe was WRONG and its output was
believed. It did:

    class _BlockedSocket(socket.socket): ...      # raise in __init__
    socket.socket = _BlockedSocket
    socket.create_connection = _blocked
    socket.getaddrinfo = _blocked

Replacing the CONSTRUCTOR blocks every socket, not every egress -- including asyncio's
`socketpair` self-pipe and every `("127.0.0.1", 0)` loopback bind, neither of which
leaves the machine. On that basis it reported 8 "network-reaching" tests
(`TestEdgeTts` x4, `test_e2e_ai2_director_text_consent` x3,
`test_director_golden_plans` x1). Four independent instruments later showed NONE of
them egresses. The 8 were artifacts of this probe, and chasing them cost a full
review lane.

So: judge the DESTINATION, not the act of making a socket. Loopback, link-local,
private ranges and UNIX sockets are fine; anything else is an off-box attempt. The probe
RECORDS rather than raising, because raising changes control flow and a test that
handles the error tells you nothing -- a recorded attempt is evidence either way.

Usage:  python docs/validation/tools/hermetic_probe.py [extra pytest args...]
Exit 0 when zero off-box attempts were recorded, 1 otherwise (the attempts are printed).
"""

from __future__ import annotations

import ipaddress
import socket
import sys
from pathlib import Path


def _find_root() -> Path:
    """Walk up to the repo root rather than assuming a fixed depth.

    Authored at `.audit/` where `parent.parent` IS the root; it now lives at
    `docs/validation/tools/`, where that same expression resolves to `docs/validation/`.
    Anchored on markers that exist only at the root instead.
    """
    here = Path(__file__).resolve()
    for cand in (here.parent, *here.parents):
        if (cand / ".git").exists() and (cand / "sidecar/pyproject.toml").is_file():
            return cand
    raise SystemExit(f"FAILED:hermetic-probe cannot locate the repo root from {here}")


ATTEMPTS: list[str] = []


def _is_off_box(host: object) -> bool:
    """True only for a destination that would actually leave this machine."""
    if not isinstance(host, str) or not host:
        return False
    if host in ("localhost", "localhost.localdomain", "::1"):
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        # A NAME that is not a known-local alias: resolving it is itself egress.
        return True
    return not (ip.is_loopback or ip.is_link_local or ip.is_private or ip.is_unspecified)


def _record(where: str, host: object, port: object = None) -> None:
    ATTEMPTS.append(f"{where} -> {host}{'' if port is None else ':' + str(port)}")


def _install() -> None:
    real_getaddrinfo = socket.getaddrinfo
    real_create_connection = socket.create_connection
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_sendto = socket.socket.sendto

    def getaddrinfo(host, port, *a, **k):  # noqa: ANN001, ANN202
        if _is_off_box(host):
            _record("getaddrinfo", host, port)
        return real_getaddrinfo(host, port, *a, **k)

    def create_connection(address, *a, **k):  # noqa: ANN001, ANN202
        if isinstance(address, tuple) and address and _is_off_box(address[0]):
            _record("create_connection", address[0], address[1] if len(address) > 1 else None)
        return real_create_connection(address, *a, **k)

    def connect(self, address, *a, **k):  # noqa: ANN001, ANN202
        if isinstance(address, tuple) and address and _is_off_box(address[0]):
            _record("connect", address[0], address[1] if len(address) > 1 else None)
        return real_connect(self, address, *a, **k)

    def connect_ex(self, address, *a, **k):  # noqa: ANN001, ANN202
        if isinstance(address, tuple) and address and _is_off_box(address[0]):
            _record("connect_ex", address[0], address[1] if len(address) > 1 else None)
        return real_connect_ex(self, address, *a, **k)

    def sendto(self, data, *args):  # noqa: ANN001, ANN202
        # The address is the LAST positional arg (flags may or may not be present).
        addr = args[-1] if args else None
        if isinstance(addr, tuple) and addr and _is_off_box(addr[0]):
            _record("sendto", addr[0], addr[1] if len(addr) > 1 else None)
        return real_sendto(self, data, *args)

    socket.getaddrinfo = getaddrinfo  # type: ignore[assignment]
    socket.create_connection = create_connection  # type: ignore[assignment]
    socket.socket.connect = connect  # type: ignore[method-assign]
    socket.socket.connect_ex = connect_ex  # type: ignore[method-assign]
    socket.socket.sendto = sendto  # type: ignore[method-assign]


def main() -> int:
    root = _find_root()
    sidecar = root / "sidecar"
    sys.path.insert(0, str(sidecar))
    _install()

    import pytest

    args = sys.argv[1:] or ["tests", "-q", "--no-header", "-p", "no:cacheprovider"]
    rc = pytest.main([*args, f"--rootdir={sidecar}"] if "--rootdir" not in " ".join(args) else args)

    print()
    if ATTEMPTS:
        print(f"OFF-BOX EGRESS ATTEMPTS RECORDED: {len(ATTEMPTS)}")
        for a in dict.fromkeys(ATTEMPTS):
            print(f"  {a}")
        print("FAILED:hermetic-probe the default suite reaches the network")
        return 1
    print("OFF-BOX EGRESS ATTEMPTS RECORDED: 0")
    print(f"SUCCESS:hermetic-probe no off-box destination attempted (pytest rc={rc})")
    # pytest's own rc is reported but does NOT gate this probe: a test can fail for
    # reasons unrelated to egress, and conflating the two is what made the old version
    # unreadable.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
