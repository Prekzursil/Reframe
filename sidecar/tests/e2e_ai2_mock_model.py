"""A local, OpenAI-compatible MOCK model server for the E2E-AI2 integration run.

This is the ONLY fake in the E2E-AI2 suite: a real HTTP server (stdlib
``http.server``, zero extra deps) that speaks the OpenAI ``/v1`` wire protocol so
the sidecar's REAL provider/embedder code (``models/provider.py`` /
``models/embedder.py``) reaches it over a REAL socket with NO injected transport
and NO cloud key. Everything else in the suite is genuine: real ffmpeg, real
handler dispatch, real consent/budget gates.

Endpoints:
  * ``POST /v1/chat/completions`` — a valid OpenAI chat completion. When the
    system prompt is the Director planner (it carries the EditPlan SECURITY RULE),
    the assistant content is a valid EditPlan JSON object so ``parse_edit_plan`` +
    ``validate_and_reject`` accept it. Otherwise a generic completion. Always
    carries a ``usage`` block.
  * ``POST /v1/embeddings`` — one deterministic dense vector per input
    (``{"data":[{"embedding":[...]}]}``), so cosine ranking is well-defined.
  * The vision path reuses ``/v1/chat/completions`` (the frame scorer issues a
    chat with image content); the mock returns a frame-index reply so the
    best-frame picker has a real model verdict.

Every request is COUNTED per endpoint (``hits``) so a test can PROVE egress
happened — guarding against the silent local-fallback trap where a flow looks
green but never touched the model.
"""

from __future__ import annotations

import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

_EMBED_DIM = 16


def _deterministic_vector(text: str, dim: int = _EMBED_DIM) -> list[float]:
    """A stable, unit-norm bag-of-words vector for ``text`` (cosine-friendly)."""
    vec = [0.0] * dim
    for token in text.split():
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        bucket = int.from_bytes(digest[:4], "big") % dim
        sign = 1.0 if digest[4] & 1 else -1.0
        vec[bucket] += sign
    norm = sum(x * x for x in vec) ** 0.5
    if norm == 0.0:
        return vec
    return [x / norm for x in vec]


def _is_director_request(body: dict[str, Any]) -> bool:
    """True when the chat request is the Director planner (EditPlan expected)."""
    for msg in body.get("messages") or []:
        if msg.get("role") == "system" and "EditPlan" in str(msg.get("content", "")):
            return True
    return False


def _is_vision_request(body: dict[str, Any]) -> bool:
    """True when any message content is multimodal (a list of parts w/ an image)."""
    for msg in body.get("messages") or []:
        content = msg.get("content")
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") in ("image_url", "image", "input_image"):
                    return True
    return False


def _edit_plan_json() -> str:
    """A valid EditPlan object (kinds from edit_plan.OP_KINDS; spans in ms)."""
    plan = {
        "ops": [
            {
                "id": "op-1",
                "kind": "removeSilence",
                "span": [0, 2000],
                "params": {},
                "reversible": True,
                "rationale": "tighten the opening dead air",
            },
            {
                "id": "op-2",
                "kind": "trim",
                "span": [2000, 8000],
                "params": {},
                "reversible": True,
                "rationale": "keep the strongest middle beat",
            },
            {
                "id": "op-3",
                "kind": "caption",
                "span": None,
                "params": {"style": "bold"},
                "reversible": True,
                "rationale": "burn captions for silent viewing",
            },
        ]
    }
    # A <think> block exercises the strip_think parse path on the real parser.
    return "<think>plan the cuts</think>\n" + json.dumps(plan)


class MockModelServer:
    """A running OpenAI-compatible mock with per-endpoint hit counters.

    Use as a context manager. ``base_url`` is the ``http://127.0.0.1:<port>/v1``
    string to drop into a provider settings entry's ``baseUrl``.
    """

    def __init__(self) -> None:
        self.hits: dict[str, int] = {"chat": 0, "embeddings": 0, "vision": 0}
        self.last_bodies: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:  # silence stderr noise
                return

            def _read(self) -> dict[str, Any]:
                length = int(self.headers.get("Content-Length", 0) or 0)
                raw = self.rfile.read(length) if length else b"{}"
                try:
                    return json.loads(raw or b"{}")
                except (ValueError, json.JSONDecodeError):
                    return {}

            def _send(self, payload: dict[str, Any], code: int = 200) -> None:
                out = json.dumps(payload).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(out)))
                # de-facto usage headers the rotation pool may parse
                self.send_header("X-RateLimit-Limit", "1000")
                self.send_header("X-RateLimit-Remaining", "999")
                self.end_headers()
                self.wfile.write(out)

            def do_POST(self) -> None:  # noqa: N802 - http.server API
                body = self._read()
                path = self.path.split("?", 1)[0]
                if path.endswith("/embeddings"):
                    outer._on_embeddings(self, body)
                elif path.endswith("/chat/completions"):
                    outer._on_chat(self, body)
                else:
                    self._send({"error": f"unknown path: {path}"}, code=404)

        self._handler_cls = Handler
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    # -- request handlers ---------------------------------------------------
    def _on_embeddings(self, handler: Any, body: dict[str, Any]) -> None:
        inputs = body.get("input") or []
        if isinstance(inputs, str):
            inputs = [inputs]
        with self._lock:
            self.hits["embeddings"] += 1
            self.last_bodies["embeddings"] = body
        data = [
            {"object": "embedding", "index": i, "embedding": _deterministic_vector(str(t))}
            for i, t in enumerate(inputs)
        ]
        handler._send(
            {
                "object": "list",
                "data": data,
                "model": body.get("model", "mock-embed"),
                "usage": {"prompt_tokens": 5, "total_tokens": 5},
            }
        )

    def _on_chat(self, handler: Any, body: dict[str, Any]) -> None:
        vision = _is_vision_request(body)
        with self._lock:
            self.hits["chat"] += 1
            if vision:
                self.hits["vision"] += 1
            self.last_bodies["chat"] = body
        if _is_director_request(body):
            content = _edit_plan_json()
        elif vision:
            # Best-frame picker asks for the best 1-based frame index; "2" -> idx 1.
            content = "Frame 2 is the most eye-catching and in-focus."
        else:
            content = "This is a mock completion."
        handler._send(
            {
                "id": "chatcmpl-mock",
                "object": "chat.completion",
                "model": body.get("model", "mock-chat"),
                "choices": [
                    {"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}
                ],
                "usage": {"prompt_tokens": 42, "completion_tokens": 12, "total_tokens": 54},
            }
        )

    # -- lifecycle ----------------------------------------------------------
    def __enter__(self) -> MockModelServer:
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler_cls)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)

    @property
    def port(self) -> int:
        assert self._server is not None, "server not started"
        return self._server.server_address[1]

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1"
