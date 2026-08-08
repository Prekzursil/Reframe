"""Destination-aware network-egress guard for the sidecar test suite.

WHY THIS EXISTS
---------------
``main`` went red twice in eight days for a reason unrelated to any code change:
14 tests pre-staged a dummy cached ``get-pip.py``, the runtime-setup manager
re-verified it, discarded it, and SILENTLY REFETCHED the real rolling artifact
from ``https://bootstrap.pypa.io/get-pip.py``. When pypa rotated that file the
blocking gate failed. Nothing in the gate could see that the suite was reaching
the network at all -- and a suite whose green depends on a third party's CDN is
not a gate, it is a coin flip (``ci-hygiene.md`` 2: "Hermetic CI = block egress +
verify a committed snapshot store").

This module is the missing detector. It rides inside the existing
``gate-tests-coverage`` pytest step (installed from ``tests/conftest.py``), so it
costs no extra CI minutes, needs no new charter gate slug, and cannot drift out
of step with the suite it guards.

WHY IT IS DESTINATION-AWARE, NOT A BLANKET BLOCK
------------------------------------------------
The obvious implementation -- replace ``socket.socket`` wholesale -- is WRONG.
``socket.socketpair()`` goes through that constructor, and it is how *every*
asyncio event loop builds its self-pipe (Proactor on Windows, Selector on POSIX);
so does every ``("127.0.0.1", 0)`` bind. A blanket block therefore breaks
``asyncio.run(...)`` and every loopback test server while detecting nothing that
actually leaves the machine. That is not hypothetical: an earlier constructor-
replacing probe reported 8 sidecar tests as "network-reaching", and a follow-up
with four independent instruments measured ZERO off-box attempts from any of
them. All 8 were artifacts of the detector's shape.

So the predicate here is the DESTINATION, not the syscall: loopback and
unspecified addresses (and the ``localhost`` family of names) pass through
untouched; anything else raises :class:`HermeticEgressError` naming where it was
going, before a single byte is sent.

WHAT IS AND IS NOT COVERED (measured 2026-08-08 on win32 / CPython 3.14.6)
--------------------------------------------------------------------------
Guarded: ``socket.getaddrinfo``, ``socket.gethostbyname``,
``socket.gethostbyname_ex``, ``socket.create_connection``,
``socket.socket.connect``, ``socket.socket.connect_ex``, ``socket.socket.sendto``,
``socket.socket.sendmsg`` (POSIX only -- Windows has no such method) and
``asyncio.proactor_events.BaseProactorEventLoop.sock_connect``.

``sendto``/``sendmsg`` matter because UDP to a hardcoded IP needs neither a
``connect`` nor a DNS lookup. The asyncio Proactor entry matters for the same
reason one level up, and it is NOT redundant with the ``socket.socket.connect``
patch: on Windows, ``asyncio.open_connection("203.0.113.1", 9)`` skips
``getaddrinfo`` (the host is already numeric) and connects via
``_overlapped.ConnectEx``, never touching ``socket.socket.connect``. Measured
before the patch existed: that call was neither logged nor raised -- it simply
timed out after 3s. The POSIX Selector loop needs no equivalent patch because
its ``sock_connect`` calls ``sock.connect(address)``, which is already guarded.

Two honest limits, stated here so nobody has to rediscover them:

* **A subprocess is out of scope.** This patches this interpreter's ``socket``
  module. A test that shells out to ``curl``/``pip``/``git`` reaches the network
  in a process that never imported this module. Egress from a child process is
  the job of a sandbox or a network namespace, not of this guard.
* **``HermeticEgressError`` subclasses ``OSError``, so callers can swallow it.**
  Measured: ``urllib.request.urlopen("http://example.invalid/")`` IS caught (the
  attempt is logged and the raise happens), but urllib catches ``OSError`` and
  re-raises it as ``URLError`` -- so an assertion on the exception TYPE will miss
  it while the attempt log still shows it. That is why :func:`attempts` exists and
  why any report should read the log, not the traceback. Subclassing ``OSError``
  is nevertheless deliberate: a test that legitimately handles "the network is
  down" should keep working.

NOT under ``--cov=media_studio``: this is test support, so it carries no coverage
burden. Opt out for a deliberately-live run with ``REFRAME_ALLOW_EGRESS=1``.
"""

from __future__ import annotations

import ipaddress
import os
import socket
from typing import Any, NamedTuple

__all__ = [
    "Attempt",
    "HermeticEgressError",
    "attempts",
    "clear_attempts",
    "install",
    "is_installed",
    "is_local_destination",
    "real_getaddrinfo",
    "restore_attempts",
    "uninstall",
]

#: Hostnames that resolve to this machine without leaving it. ``""``/``None`` are
#: the "any/unspecified" spellings ``getaddrinfo`` accepts when binding.
_LOCAL_NAMES = frozenset(
    {
        "",
        "localhost",
        "localhost.localdomain",
        "ip6-localhost",
        "ip6-loopback",
        "broadcasthost",
    }
)

_ENV_OPT_OUT = "REFRAME_ALLOW_EGRESS"


class HermeticEgressError(OSError):
    """Raised instead of letting a test reach a destination off this machine."""


class Attempt(NamedTuple):
    """One blocked egress attempt, kept so a failure says WHERE it was going."""

    api: str
    host: str
    address: str


_ATTEMPTS: list[Attempt] = []

# The pristine stdlib callables, captured at import time -- before anything in the
# suite has had a chance to shadow them.
real_getaddrinfo = socket.getaddrinfo
real_gethostbyname = socket.gethostbyname
real_gethostbyname_ex = socket.gethostbyname_ex
real_create_connection = socket.create_connection
real_connect = socket.socket.connect
real_connect_ex = socket.socket.connect_ex
real_sendto = socket.socket.sendto
real_sendmsg = getattr(socket.socket, "sendmsg", None)

try:
    import asyncio.proactor_events as _proactor_events
except ImportError:  # a stripped-down asyncio; nothing to patch
    _proactor_events = None  # type: ignore[assignment]

_proactor_loop_cls = getattr(_proactor_events, "BaseProactorEventLoop", None)

#: Present on every platform (``proactor_events`` is pure Python and imports
#: cleanly on POSIX), but only ever *instantiated* on Windows.
real_proactor_sock_connect = getattr(_proactor_loop_cls, "sock_connect", None)

_installed = False


def is_installed() -> bool:
    """Whether the guard is currently armed."""
    return _installed


def attempts() -> tuple[Attempt, ...]:
    """Every egress attempt blocked since the last :func:`clear_attempts`."""
    return tuple(_ATTEMPTS)


def clear_attempts() -> None:
    """Reset the recorded-attempt log.

    Process-wide. A test module that trips the guard on purpose should
    :func:`restore_attempts` to a snapshot instead, so it removes only its own
    synthetic entries and cannot discard a real finding recorded by a sibling.
    """
    _ATTEMPTS.clear()


def restore_attempts(snapshot: tuple[Attempt, ...]) -> None:
    """Roll the attempt log back to ``snapshot`` (see :func:`clear_attempts`)."""
    _ATTEMPTS[:] = list(snapshot)


def _as_text(host: object) -> str:
    if isinstance(host, (bytes, bytearray)):
        return host.decode("utf-8", "replace")
    return "" if host is None else str(host)


def is_local_destination(host: object) -> bool:
    """True when ``host`` cannot leave this machine.

    Accepts what the socket APIs accept: a name, an IPv4/IPv6 literal (with or
    without a ``%zone`` suffix), bytes, ``None``, or a non-string address
    component (AF_UNIX path, AF_PACKET tuple member) which is not IP egress.
    """
    if host is None:
        return True
    if isinstance(host, (bytes, bytearray)):
        host = _as_text(host)
    if not isinstance(host, str):
        # A non-string address component: AF_UNIX path object, AF_BLUETOOTH
        # channel, ... none of which is an IP destination.
        return True
    text = host.strip()
    if text.lower() in _LOCAL_NAMES:
        return True
    try:
        parsed = ipaddress.ip_address(text.split("%", 1)[0])
    except ValueError:
        # A real DNS name. Resolving it is itself a query that leaves the box.
        return False
    return bool(parsed.is_loopback or parsed.is_unspecified)


def _host_of(address: object) -> object:
    """The host component of a socket address, or ``None`` when there is none."""
    if isinstance(address, (tuple, list)) and address:
        return address[0]
    return None


def sendto_address(args: tuple[Any, ...]) -> object:
    """The ``address`` positional of ``sendto(data[, flags], address)``.

    ``data`` is a named parameter on the guard, so ``args`` is either
    ``(address,)`` or ``(flags, address)`` -- the address is LAST either way.
    Extracted as a pure function so the argument arithmetic is unit-testable on
    a platform basis, rather than only via a live socket.
    """
    return args[-1] if args else None


def sendmsg_address(args: tuple[Any, ...]) -> object:
    """The ``address`` positional of ``sendmsg(buffers[, ancdata[, flags[, address]]])``.

    ``buffers`` is a NAMED parameter on the guard, so ``args`` starts at
    ``ancdata`` and the address is ``args[2]``.

    This was ``args[3]`` in the first revision -- off by one, which made the arm
    UNREACHABLE: a real ``sock.sendmsg([b"x"], [], 0, (host, port))`` passes three
    positionals, ``len(args) > 3`` is False, and the guard checked ``None`` (which
    :func:`is_local_destination` calls local) and waved the packet through. It
    survived review because Windows has no ``sendmsg`` at all, so no test on the
    authoring machine could ever have executed this line. Hence the pure helper
    and :func:`test_sendmsg_address_is_the_third_positional`, which fails on every
    platform if the index regresses.
    """
    return args[2] if len(args) > 2 else None


def _reject(api: str, address: object, host: object) -> None:
    attempt = Attempt(api=api, host=_as_text(host), address=repr(address))
    _ATTEMPTS.append(attempt)
    raise HermeticEgressError(
        f"HERMETIC GUARD: {api} -> {attempt.host!r} is OFF-BOX network egress. "
        "The default sidecar suite must be hermetic: a test that fetches a "
        "remote artifact goes red when that artifact rotates, rate-limits, or "
        "goes down (this is exactly how get-pip.py took main red twice). Inject "
        "the seam and assert against a committed fixture instead. For a "
        f"deliberately live run, set {_ENV_OPT_OUT}=1. Destination: {attempt.address}"
    )


def _check(api: str, address: object) -> None:
    host = _host_of(address)
    if not is_local_destination(host):
        _reject(api, address, host)


def _guarded_getaddrinfo(host: Any, port: Any, *args: Any, **kwargs: Any) -> Any:
    if not is_local_destination(host):
        _reject("socket.getaddrinfo", (host, port), host)
    return real_getaddrinfo(host, port, *args, **kwargs)


def _guarded_gethostbyname(hostname: Any) -> Any:
    if not is_local_destination(hostname):
        _reject("socket.gethostbyname", hostname, hostname)
    return real_gethostbyname(hostname)


def _guarded_gethostbyname_ex(hostname: Any) -> Any:
    if not is_local_destination(hostname):
        _reject("socket.gethostbyname_ex", hostname, hostname)
    return real_gethostbyname_ex(hostname)


def _guarded_create_connection(address: Any, *args: Any, **kwargs: Any) -> Any:
    _check("socket.create_connection", address)
    return real_create_connection(address, *args, **kwargs)


def _guarded_connect(self: socket.socket, address: Any) -> Any:
    _check("socket.socket.connect", address)
    return real_connect(self, address)


def _guarded_connect_ex(self: socket.socket, address: Any) -> Any:
    _check("socket.socket.connect_ex", address)
    return real_connect_ex(self, address)


def _guarded_sendto(self: socket.socket, data: Any, *args: Any) -> Any:
    _check("socket.socket.sendto", sendto_address(args))
    return real_sendto(self, data, *args)


def _guarded_sendmsg(self: socket.socket, buffers: Any, *args: Any) -> Any:
    _check("socket.socket.sendmsg", sendmsg_address(args))
    return real_sendmsg(self, buffers, *args)  # type: ignore[misc]


async def _guarded_proactor_sock_connect(self: Any, sock: Any, address: Any) -> Any:
    # Windows' Proactor loop reaches ConnectEx without going through
    # socket.socket.connect; see the module docstring's measurement.
    _check("asyncio.BaseProactorEventLoop.sock_connect", address)
    return await real_proactor_sock_connect(self, sock, address)  # type: ignore[misc]


#: ``(owner, attribute name, guarded callable, pristine callable)``. Everything
#: patched here lives on the ``socket`` module, the ``socket.socket`` class, or
#: asyncio's Proactor loop -- no filesystem, subprocess or os-level behaviour is
#: touched.
_PATCHES: tuple[tuple[Any, str, Any, Any], ...] = (
    (socket, "getaddrinfo", _guarded_getaddrinfo, real_getaddrinfo),
    (socket, "gethostbyname", _guarded_gethostbyname, real_gethostbyname),
    (socket, "gethostbyname_ex", _guarded_gethostbyname_ex, real_gethostbyname_ex),
    (socket, "create_connection", _guarded_create_connection, real_create_connection),
    (socket.socket, "connect", _guarded_connect, real_connect),
    (socket.socket, "connect_ex", _guarded_connect_ex, real_connect_ex),
    (socket.socket, "sendto", _guarded_sendto, real_sendto),
    # sendmsg is POSIX-only; the Proactor loop only exists where asyncio ships it.
    *(((socket.socket, "sendmsg", _guarded_sendmsg, real_sendmsg),) if real_sendmsg is not None else ()),
    *(
        (
            (
                _proactor_loop_cls,
                "sock_connect",
                _guarded_proactor_sock_connect,
                real_proactor_sock_connect,
            ),
        )
        if real_proactor_sock_connect is not None
        else ()
    ),
)


def install(env: dict[str, str] | None = None) -> str:
    """Arm the guard. Returns ``installed`` / ``already-installed`` / ``disabled``.

    ``env`` defaults to :data:`os.environ`; it is injectable so the opt-out path
    is testable without mutating the process environment.
    """
    global _installed
    environ = os.environ if env is None else env
    if environ.get(_ENV_OPT_OUT):
        return "disabled"
    if _installed:
        return "already-installed"
    for owner, name, guarded, _original in _PATCHES:
        setattr(owner, name, guarded)
    _installed = True
    return "installed"


def uninstall() -> str:
    """Disarm the guard. Returns ``uninstalled`` / ``not-installed``."""
    global _installed
    if not _installed:
        return "not-installed"
    for owner, name, _guarded, original in _PATCHES:
        setattr(owner, name, original)
    _installed = False
    return "uninstalled"
