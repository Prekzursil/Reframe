"""Stdio JSON-RPC 2.0 server (newline-delimited).

Reads one JSON object per line from **stdin**, dispatches via the
:data:`protocol.METHODS` registry, and writes one JSON object per line to
**stdout** — responses plus ``job.progress`` / ``job.done`` notifications. ALL
logs go to **stderr** (CONTRACTS.md §2). stdout is sacred: only framed JSON-RPC.

The server is transport-only; feature modules register their handlers on the
shared registry before ``serve()`` runs. Long jobs return ``{"jobId"}``
immediately and stream progress; this server relays the registry's progress/done
sinks to stdout notifications.
"""

from __future__ import annotations

import json
import sys
import threading
from typing import Any, TextIO

from . import protocol
from .job_store import JobStore
from .jobs import JobRegistry
from .protocol import (
    ErrorCode,
    RpcContext,
    RpcError,
    make_done,
    make_error,
    make_progress,
    make_response,
    parse_request,
)
from .util import get_logger

log = get_logger("media_studio.rpc")

#: F3b: the production per-job wall-clock deadline. A handler that outruns this is
#: force-finished ERROR by the registry watchdog so the bounded (2-slot) pool can
#: never be permanently starved by a wedged job. 30 min comfortably clears a long
#: real transcription/render while still bounding a true hang.
DEFAULT_JOB_TIMEOUT_SEC = 30.0 * 60.0


class RpcServer:
    """Newline-delimited JSON-RPC server over a pair of text streams.

    Defaults to ``sys.stdin`` / ``sys.stdout`` but accepts injected streams so
    tests can drive it with in-memory buffers (no real stdio, no subprocess).
    Writes to stdout are serialized behind a lock so concurrent job
    notifications never interleave a half-written line.
    """

    def __init__(
        self,
        instream: TextIO | None = None,
        outstream: TextIO | None = None,
        *,
        store: JobStore | None = None,
        job_timeout_sec: float | None = DEFAULT_JOB_TIMEOUT_SEC,
    ) -> None:
        self._in: TextIO = instream if instream is not None else sys.stdin
        self._out: TextIO = outstream if outstream is not None else sys.stdout
        self._write_lock = threading.Lock()
        # WU-6: the registry is RpcServer-owned, so the persistence store is
        # injected here (default None = today's in-memory behavior, back-compat)
        # and threaded down from the composition root via build_server/main.
        # F3b: the production registry arms the per-job watchdog (a wedged handler
        # is force-finished ERROR so the 2-slot pool can't starve); the real timer
        # seam is the registry default (a daemon ``threading.Timer``).
        self.jobs = JobRegistry(
            emit_progress=self._emit_progress,
            emit_done=self._emit_done,
            store=store,
            job_timeout_sec=job_timeout_sec,
        )
        self.ctx = RpcContext(emit_notification=self._write_obj, jobs=self.jobs)

    # -- output ------------------------------------------------------------

    def _write_obj(self, obj: dict[str, Any]) -> None:
        """Serialize ``obj`` as one compact JSON line to stdout (thread-safe)."""
        line = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
        with self._write_lock:
            self._out.write(line + "\n")
            self._out.flush()

    def _emit_progress(self, job_id: str, pct: int, message: str) -> None:
        self._write_obj(make_progress(job_id, pct, message))

    def _emit_done(self, job_id: str, result: Any) -> None:
        self._write_obj(make_done(job_id, result))

    # -- per-line handling -------------------------------------------------

    def handle_line(self, line: str) -> None:
        """Parse + dispatch one input line, writing the response to stdout.

        Notifications (no ``id``) produce no response. Parse failures yield a
        JSON-RPC error response with a null id. Any handler exception other than
        :class:`RpcError` becomes an INTERNAL_ERROR response so a single bad call
        never tears down the stdin loop.
        """
        stripped = line.strip()
        if not stripped:
            return  # blank/keepalive line — ignore

        try:
            obj = json.loads(stripped)
        except json.JSONDecodeError as exc:
            log.warning("parse error: %s", exc)
            self._write_obj(make_error(None, RpcError(f"parse error: {exc}", ErrorCode.PARSE_ERROR)))
            return

        try:
            req = parse_request(obj)
        except RpcError as exc:
            # An envelope may still carry an id even if otherwise invalid.
            req_id = obj.get("id") if isinstance(obj, dict) else None
            self._write_obj(make_error(req_id, exc))
            return

        try:
            result = protocol.dispatch(req, self.ctx)
        except RpcError as exc:
            if not req.is_notification:
                self._write_obj(make_error(req.id, exc))
            else:
                log.warning("notification %s failed: %s", req.method, exc)
            return
        except Exception as exc:  # noqa: BLE001 - never let one call kill the loop
            log.error("handler %s crashed: %s", req.method, exc, exc_info=True)
            if not req.is_notification:
                wrapped = RpcError(f"internal error in {req.method}: {exc}", ErrorCode.INTERNAL_ERROR)
                self._write_obj(make_error(req.id, wrapped))
            return

        if not req.is_notification:
            self._write_obj(make_response(req.id, result))

    # -- main loop ---------------------------------------------------------

    def serve(self) -> None:
        """Block reading newline-delimited requests from stdin until EOF."""
        log.info("sidecar rpc server: ready (stdio)")
        for line in self._in:
            self.handle_line(line)
        log.info("sidecar rpc server: stdin closed, exiting")


def build_server(
    instream: TextIO | None = None,
    outstream: TextIO | None = None,
    *,
    store: JobStore | None = None,
) -> RpcServer:
    """Construct an :class:`RpcServer`. Feature modules register handlers on
    :data:`protocol.METHODS` at import time before this is called.

    WU-6: ``store`` (default ``None`` = in-memory) is forwarded to the
    registry the server constructs so the composition root can supply disk
    persistence."""
    return RpcServer(instream=instream, outstream=outstream, store=store)


def main(argv: list[str] | None = None, *, store: JobStore | None = None) -> int:
    """Entry point: serve JSON-RPC over real stdio until stdin closes.

    CONTRACT-NOTE: feature handlers register themselves via import side effects.
    This core module imports none of them (to stay heavy-ML-free); the assembled
    sidecar entry point is expected to import the feature packages before calling
    ``main`` so their @method registrations land in METHODS.

    WU-6: when a ``store`` is supplied, the server's registry persists through
    it and is rehydrated once at startup (mid-flight jobs become INTERRUPTED;
    nothing is auto-spawned — the §5 no-silent-spend invariant).
    """
    server = build_server(store=store)
    if store is not None:
        server.jobs.rehydrate()
    try:
        server.serve()
    except KeyboardInterrupt:  # pragma: no cover - interactive only
        log.info("interrupted")
        return 130
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
