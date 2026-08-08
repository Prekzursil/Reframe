"""The egress guard's own both-states matrix (ci-hygiene.md 2: hermetic CI).

The get-pip incident took ``main`` red twice in eight days: 14 tests pre-staged a
dummy cache, the manager re-verified it, discarded it, and SILENTLY REFETCHED the
real rolling artifact from the network. Nothing in the blocking gate noticed the
suite was non-hermetic. :mod:`tests._hermetic` is the detector that would have.

A detector is only trustworthy in BOTH states, so this file is deliberately two
halves that pull in opposite directions:

* FALSE-POSITIVE direction -- purely-local work (``socketpair``, ``asyncio.run``,
  a ``127.0.0.1`` bind + round-trip) MUST be left alone. A guard that replaces
  ``socket.socket`` wholesale fails every one of these while proving nothing: the
  Windows Proactor / POSIX Selector event loop builds its self-pipe through that
  constructor, and so does every loopback server.
* ANTI-GUTTING direction -- real off-box destinations MUST still raise. These are
  the cases that stop a future reader from "fixing" a false positive by loosening
  the destination check until the guard blocks nothing at all. All the addresses
  used are reserved-and-unroutable (RFC 5737 TEST-NET, RFC 6761 ``.invalid``), so
  even an unguarded run cannot actually leak.
"""

from __future__ import annotations

import asyncio
import socket
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest

from tests import _hermetic

# RFC 5737 TEST-NET-1/2/3 and RFC 6761 .invalid: reserved, globally unroutable,
# guaranteed never to resolve. Safe to name in an assertion.
_OFF_BOX_TCP = ("192.0.2.1", 80)
_OFF_BOX_UDP = ("198.51.100.1", 9)
_OFF_BOX_RAW = ("203.0.113.1", 80)
_OFF_BOX_HOST = "example.invalid"


@pytest.fixture(autouse=True)
def _guard():
    """Arm the guard for every case here, and leave the attempt log CLEAN.

    The anti-gutting cases below deliberately trip the guard. Without the
    teardown their synthetic destinations survive in the process-wide log, and
    any reporter that prints ``_hermetic.attempts()`` at the end of a run (e.g.
    ``docs/validation/tools/hermetic_probe.py``) then announces an off-box attempt
    that no production code ever made -- a detector reporting its own negative
    controls as findings. Measured: a full-suite probe run reported
    ``OFF-BOX EGRESS ATTEMPTS RECORDED: 1 -> example.invalid`` for exactly this
    reason.

    ``env={}`` is deliberate: this file TESTS the guard, it is not protected by
    it, so it must arm regardless of the ``REFRAME_ALLOW_EGRESS`` opt-out that
    .github/workflows/e2e.yml sets for the heavy suite. Without that, a run with
    the opt-out exported would leave the guard down and send
    ``test_guard_blocks_non_local_dns`` at a REAL resolver.

    The teardown restores whatever state the session was in, so forcing the
    guard on HERE cannot silently re-arm it for every module that runs after
    this one -- which would defeat the opt-out for whoever set it.

    It SNAPSHOTS-and-restores the log rather than clearing it. ``_ATTEMPTS`` is
    process-wide, so a bare ``clear_attempts()`` here would also discard a
    genuine off-box attempt recorded by a test module that ran earlier in the
    same session -- this file would be silently destroying the very evidence the
    guard exists to collect. Restoring the snapshot removes exactly the synthetic
    entries these cases create and nothing else.
    """
    was_installed = _hermetic.is_installed()
    prior_attempts = _hermetic.attempts()
    _hermetic.install(env={})
    yield
    _hermetic.restore_attempts(prior_attempts)
    if not was_installed:
        _hermetic.uninstall()


# --------------------------------------------------------------------------- #
# FALSE-POSITIVE direction: local-only work must survive untouched
# --------------------------------------------------------------------------- #
def test_guard_allows_socketpair():
    left, right = socket.socketpair()
    try:
        left.sendall(b"ping")
        assert right.recv(4) == b"ping"
    finally:
        left.close()
        right.close()


def test_guard_allows_asyncio_run():
    async def _answer() -> int:
        await asyncio.sleep(0)
        return 42

    assert asyncio.run(_answer()) == 42


def test_guard_allows_loopback_http_roundtrip():
    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler's required spelling
            body = b"loopback-ok"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            """Silence the per-request stderr line."""

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        # No-proxy opener: a configured http_proxy would turn a loopback GET into
        # a genuine off-box hop, which the guard is right to block.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f"http://127.0.0.1:{port}/", timeout=5) as resp:
            assert resp.status == 200
            assert resp.read() == b"loopback-ok"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1", "", None])
def test_guard_allows_local_name_resolution(host):
    assert _hermetic.is_local_destination(host) is True


# --------------------------------------------------------------------------- #
# ANTI-GUTTING direction: off-box destinations must still raise, and say where
# --------------------------------------------------------------------------- #
def test_guard_blocks_off_box_create_connection():
    with pytest.raises(_hermetic.HermeticEgressError) as excinfo:
        socket.create_connection(_OFF_BOX_TCP, timeout=0.05)
    assert _OFF_BOX_TCP[0] in str(excinfo.value)


def test_guard_blocks_off_box_socket_connect():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(_hermetic.HermeticEgressError) as excinfo:
            sock.connect(_OFF_BOX_RAW)
    finally:
        sock.close()
    assert _OFF_BOX_RAW[0] in str(excinfo.value)


def test_guard_blocks_off_box_connect_ex():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(_hermetic.HermeticEgressError):
            sock.connect_ex(_OFF_BOX_RAW)
    finally:
        sock.close()


def test_guard_blocks_off_box_sendto():
    """UDP to a hardcoded IP needs neither connect() nor DNS -- guard it too."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        with pytest.raises(_hermetic.HermeticEgressError) as excinfo:
            sock.sendto(b"x", _OFF_BOX_UDP)
    finally:
        sock.close()
    assert _OFF_BOX_UDP[0] in str(excinfo.value)


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        ((_OFF_BOX_UDP,), _OFF_BOX_UDP),  # sendto(data, address)
        ((0, _OFF_BOX_UDP), _OFF_BOX_UDP),  # sendto(data, flags, address)
        ((), None),  # malformed; must not IndexError
    ],
)
def test_sendto_address_is_the_last_positional(args, expected):
    assert _hermetic.sendto_address(args) is expected


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (([], 0, _OFF_BOX_UDP), _OFF_BOX_UDP),  # sendmsg(buffers, ancdata, flags, address)
        (([], 0), None),  # no address supplied -- a connected socket
        ((), None),  # malformed; must not IndexError
    ],
)
def test_sendmsg_address_is_the_third_positional(args, expected):
    """The index arithmetic, provable on EVERY platform including Windows.

    ``sendmsg`` does not exist on Windows, so the live-socket case below skips
    there -- which is exactly how this shipped wrong the first time, as
    ``args[3]``. That index makes the guard's ``sendmsg`` arm unreachable: a real
    four-arg call passes three positionals after the named ``buffers``, so
    ``len(args) > 3`` is False and the destination read as ``None`` (which counts
    as local) while the packet went out. This parametrisation fails on any
    platform if the index regresses.
    """
    assert _hermetic.sendmsg_address(args) is expected


@pytest.mark.skipif(_hermetic.real_sendmsg is None, reason="socket.socket.sendmsg is POSIX-only")
def test_guard_blocks_off_box_sendmsg():
    """The live-socket half of the arm above -- runs on the Linux CI leg."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        with pytest.raises(_hermetic.HermeticEgressError) as excinfo:
            sock.sendmsg([b"x"], [], 0, _OFF_BOX_UDP)
    finally:
        sock.close()
    assert _OFF_BOX_UDP[0] in str(excinfo.value)


def test_guard_blocks_non_local_dns():
    with pytest.raises(_hermetic.HermeticEgressError) as excinfo:
        socket.getaddrinfo(_OFF_BOX_HOST, 443)
    assert _OFF_BOX_HOST in str(excinfo.value)


def test_guard_blocks_asyncio_connect_to_a_numeric_off_box_ip():
    """asyncio + a NUMERIC host is the one shape the socket-level patches miss.

    A numeric host skips ``getaddrinfo`` entirely, and on Windows the Proactor
    loop then reaches ``_overlapped.ConnectEx`` without ever calling
    ``socket.socket.connect``. Measured before the ``sock_connect`` patch existed:
    this call was neither logged nor raised -- it just timed out after 3s, so the
    guard would have waved through any hardcoded-IP asyncio egress. On POSIX the
    Selector loop routes through ``sock.connect``, so this passes there via a
    different patch; asserting the OUTCOME keeps one test honest on both.
    """

    async def _reach() -> None:
        await asyncio.wait_for(asyncio.open_connection(*_OFF_BOX_RAW), timeout=5)

    with pytest.raises(_hermetic.HermeticEgressError) as excinfo:
        asyncio.run(_reach())
    assert _OFF_BOX_RAW[0] in str(excinfo.value)


def test_restore_attempts_rolls_back_only_the_new_entries():
    """UNIT scope: the semantics of :func:`restore_attempts` itself.

    This does NOT prove the autouse fixture uses it correctly -- measured: with
    the teardown mutated back to ``clear_attempts()`` this test still passed,
    because its own assertions run before any teardown. The fixture's behaviour
    is covered by the module-scoped sentinel at the bottom of this file, which
    that mutation does kill. Two different claims, two different tests.
    """
    sibling = _hermetic.Attempt(api="socket.getaddrinfo", host="sibling.invalid", address="()")
    _hermetic.restore_attempts((sibling,))
    with pytest.raises(_hermetic.HermeticEgressError):
        socket.getaddrinfo(_OFF_BOX_HOST, 443)
    assert len(_hermetic.attempts()) == 2

    _hermetic.restore_attempts((sibling,))
    assert _hermetic.attempts() == (sibling,)


def test_blocked_attempt_is_recorded_with_its_destination():
    # Measure the DELTA rather than calling clear_attempts(): the log is
    # process-wide, so clearing it here would destroy an off-box attempt
    # recorded by an earlier test module -- the same defect the module-scoped
    # sentinel at the bottom of this file guards against.
    before = len(_hermetic.attempts())
    with pytest.raises(_hermetic.HermeticEgressError):
        socket.getaddrinfo(_OFF_BOX_HOST, 443)
    recorded = _hermetic.attempts()[before:]
    assert len(recorded) == 1
    assert recorded[0].host == _OFF_BOX_HOST
    assert recorded[0].api == "socket.getaddrinfo"


def test_error_is_an_oserror_so_callers_see_a_network_failure():
    assert issubclass(_hermetic.HermeticEgressError, OSError)


# --------------------------------------------------------------------------- #
# The guard itself: idempotent, reversible, and demonstrably load-bearing
# --------------------------------------------------------------------------- #
def test_install_is_idempotent():
    first = socket.getaddrinfo
    assert _hermetic.install(env={}) == "already-installed"
    assert socket.getaddrinfo is first


def test_uninstall_restores_the_stdlib_and_is_what_blocks():
    """Both-states: with the guard OFF the same call is NOT a HermeticEgressError."""
    assert _hermetic.uninstall() == "uninstalled"
    try:
        assert socket.getaddrinfo is _hermetic.real_getaddrinfo
        with pytest.raises(OSError) as excinfo:
            socket.create_connection(_OFF_BOX_TCP, timeout=0.05)
        assert not isinstance(excinfo.value, _hermetic.HermeticEgressError)
    finally:
        assert _hermetic.install(env={}) == "installed"
    assert socket.getaddrinfo is not _hermetic.real_getaddrinfo


def test_install_is_a_no_op_when_the_opt_out_env_is_set():
    assert _hermetic.uninstall() == "uninstalled"
    try:
        assert _hermetic.install(env={"REFRAME_ALLOW_EGRESS": "1"}) == "disabled"
        assert socket.getaddrinfo is _hermetic.real_getaddrinfo
    finally:
        assert _hermetic.install(env={}) == "installed"


def test_uninstall_is_idempotent():
    assert _hermetic.uninstall() == "uninstalled"
    try:
        assert _hermetic.uninstall() == "not-installed"
    finally:
        _hermetic.install(env={})


# --------------------------------------------------------------------------- #
# The teardown's OWN both-states case -- must stay LAST in this file
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module", autouse=True)
def _sibling_finding():
    """A stand-in for an off-box attempt recorded by an EARLIER test module.

    ``_ATTEMPTS`` is process-wide and this file trips the guard a dozen times on
    purpose, so its per-test teardown has to remove ONLY its own synthetic
    entries. Seeding a sentinel before the first case and asserting it is still
    there after the last one is the only way to measure that: a unit test of
    :func:`_hermetic.restore_attempts` cannot see a teardown, and measurably did
    not -- mutating the teardown to ``clear_attempts()`` left that test green.
    """
    sentinel = _hermetic.Attempt(api="socket.getaddrinfo", host="earlier-module.invalid", address="()")
    before = _hermetic.attempts()
    _hermetic.restore_attempts((*before, sentinel))
    yield sentinel
    _hermetic.restore_attempts(before)


def test_zz_an_earlier_modules_finding_survives_every_teardown_in_this_file(
    _sibling_finding,
):
    """Defined LAST on purpose: pytest runs a module in definition order, so by
    here every guard-tripping case above has set up and torn down at least once.
    If the teardown clears instead of restoring, the sentinel is gone and this
    goes red -- which is exactly what a mutation run confirms.
    """
    assert _sibling_finding in _hermetic.attempts(), (
        "a teardown in this file destroyed an attempt it did not create; the "
        "guard's log is process-wide, so that would discard a real finding"
    )
