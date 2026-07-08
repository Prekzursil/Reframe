"""LLM Provider seam: ABC + a llama.cpp LocalServerProvider + an optional CloudProvider.

The short-maker selection (``features/select.py``) and subtitle translation
(``features/subtitles.py``) both reach the LLM only through a tiny duck-typed
seam. This module is the concrete home of that seam (CONTRACTS.md §1/§4:
``Provider interface (complete/chat)``). It is import-light: the HTTP call uses
**urllib from the stdlib** and is wrapped behind an injectable transport so tests
NEVER touch the network.

What the consumers actually call (the interface this module must match EXACTLY):
  * ``features/select.py``  -> ``provider.chat(messages, *, temperature=..., max_tokens=...)`` -> ``str``
  * ``features/subtitles.py`` -> ``provider.chat(messages)`` (no kwargs) -> ``str``
So :meth:`Provider.chat` takes positional ``messages`` (a list of
``{"role","content"}`` dicts), accepts ``temperature`` / ``max_tokens`` keywords,
swallows any extra ``**kwargs``, and returns the assistant message **content**
string. ``complete(prompt, ...)`` is the single-turn convenience the §4 interface
names; it wraps the prompt in one user message and delegates to ``chat``.

CONTRACT-NOTE: §7 names a "managed llama.cpp server (OpenAI-compatible /v1)"; the
default model is Qwen3-4B. The endpoint is ``POST {base_url}/v1/chat/completions``.
CONTRACT-NOTE: pyproject declares ``httpx`` as a runtime dep, but this unit is
explicitly built on **stdlib urllib** (the task's hard rule) so the sidecar has
zero hard import dependency on httpx for the LLM path; the transport is injectable
so a future httpx-based transport can drop in without changing callers.
CONTRACT-NOTE: §0 is explicit there is NO auth/keystore. ``CloudProvider`` is the
ONLY place an API key is read, and only when ``settings.useCloud`` is true AND a
key is present; the key is passed as a bearer header and never logged.
"""

from __future__ import annotations

import abc
import functools
import json
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from ..util import get_logger
from .secrets import redact, scrub_error_body

log = get_logger("media_studio.models.provider")

# A chat message is the OpenAI-style {"role": ..., "content": ...} dict.
Message = dict[str, str]

# --------------------------------------------------------------------------- #
# Defaults (CONTRACTS.md §2 settings.* / §7 stack choices)
# --------------------------------------------------------------------------- #
#: Default base URL of the local llama.cpp OpenAI-compatible server (§7). Port
#: 8088 matches the runner's launch argv (``models/runner.py``).
DEFAULT_LOCAL_BASE_URL: str = "http://127.0.0.1:8088/v1"
#: Default cloud base URL (OpenAI-compatible). Only used when useCloud + a key.
DEFAULT_CLOUD_BASE_URL: str = "https://api.openai.com/v1"
#: §7 default local model id (the llama.cpp server reports its own; this is the
#: ``model`` field we send — llama.cpp ignores it for a single-model server).
DEFAULT_LOCAL_MODEL: str = "qwen3-4b"
#: A conservative default cloud model id (overridable via settings.cloudModel).
DEFAULT_CLOUD_MODEL: str = "gpt-4o-mini"
#: Recipe defaults mirrored from features/select.py so a bare ``chat`` still has
#: sane sampling. Callers that pass explicit kwargs override these.
DEFAULT_TEMPERATURE: float = 0.4
DEFAULT_MAX_TOKENS: int = 4096
#: HTTP timeout (seconds) for a single completion request.
DEFAULT_TIMEOUT: float = 600.0


# A transport seam: given (url, json-body-dict, headers, timeout) it performs an
# HTTP call and returns the decoded JSON response dict. Injected in tests so no
# socket is ever opened. The default POST implementation is
# :func:`_urllib_post_json`; the default GET implementation (used by local-server
# detection, which probes ``GET /models``) is :func:`urllib_get_json`. A GET
# transport ignores the body dict (a GET carries no body) so the SAME injectable
# ``Transport`` shape serves both the chat POST path and the detection GET path.
Transport = Callable[[str, dict[str, Any], dict[str, str], float], dict[str, Any]]


class ProviderError(RuntimeError):
    """Raised when a provider cannot produce a completion (HTTP / parse error).

    Carries a human-readable message; the RPC layer maps it onto a structured
    JSON-RPC error. Never embeds an API key (the key is header-only).

    ``status_code`` is the originating HTTP status when the failure was an
    ``HTTPError`` (e.g. ``402``/``429`` for the OpenRouter key-pool cooldown
    triggers, M4), and ``None`` for connection/parse failures. It lets a caller
    classify a cooldown-worthy failure WITHOUT re-parsing the message string.
    """

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


# --------------------------------------------------------------------------- #
# stdlib urllib transport (the only place a socket is opened)
# --------------------------------------------------------------------------- #
def _urllib_request_json(
    url: str,
    *,
    method: str,
    data: bytes | None,
    headers: dict[str, str],
    timeout: float,
    secrets: Sequence[str] = (),
) -> dict[str, Any]:
    """Issue one ``method`` request to ``url`` and decode the JSON response (stdlib).

    Shared core for both the chat POST (:func:`_urllib_post_json`) and the
    detection GET (:func:`urllib_get_json`). Raises :class:`ProviderError` on any
    network / decode failure so the caller sees one error type regardless of the
    underlying urllib exception. The error body is scrubbed ENFORCEABLY (PLAN
    §WU-keys): every live key in ``secrets`` AND any leaked ``Authorization:
    Bearer`` token is stripped at THIS construction site, so "no live key in any
    :class:`ProviderError`" is an invariant, not a hope.
    """
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        # CONTRACT-NOTE: no shell, no redirects-to-file; a plain JSON call. Bandit
        # B310 (urlopen) is satisfied because the scheme is fixed http/https built
        # from settings, never attacker-controlled raw input.
        with urllib.request.urlopen(request, timeout=timeout) as resp:  # noqa: S310
            raw = resp.read().decode("utf-8")
            raw_headers = getattr(resp, "headers", None)
            resp_headers = {str(k): str(v) for k, v in raw_headers.items()} if raw_headers is not None else {}
    except urllib.error.HTTPError as exc:  # 4xx/5xx with a body
        detail = ""
        try:
            detail = exc.read().decode("utf-8")
        except Exception:  # noqa: BLE001 - best-effort error body
            detail = ""
        # ENFORCEABLE SCRUB (PLAN §WU-keys): strip every live key threaded in via
        # ``secrets`` AND any echoed ``Authorization: Bearer`` token from the
        # server's error body BEFORE it ever reaches a ProviderError / a log line.
        safe_detail = scrub_error_body(detail, secrets) if detail else ""
        reason = scrub_error_body(str(exc.reason), secrets)
        raise ProviderError(f"LLM HTTP {exc.code}: {safe_detail or reason}", status_code=exc.code) from exc
    except urllib.error.URLError as exc:  # connection refused / DNS / timeout
        # ENFORCEABLE SCRUB (WU-F1 symmetry): ``exc.reason`` can echo a leaked
        # bearer/key (e.g. a proxy error page carrying the URL), so it goes through
        # the SAME guard as the HTTPError branch before reaching a ProviderError.
        reason = scrub_error_body(str(exc.reason), secrets)
        raise ProviderError(f"LLM request failed: {reason}") from exc
    try:
        decoded = json.loads(raw)
    except (ValueError, json.JSONDecodeError) as exc:
        # ENFORCEABLE SCRUB (WU-F1 symmetry): a non-JSON body (HTML proxy/error
        # page) can echo the key too; scrub the slice BEFORE the ``!r`` repr so no
        # live key survives in the surfaced/loggable error at this site either.
        safe_raw = scrub_error_body(raw[:200], secrets)
        raise ProviderError(f"LLM returned non-JSON response: {safe_raw!r}") from exc
    if not isinstance(decoded, dict):
        raise ProviderError("LLM response was not a JSON object")
    # Surface response headers under a reserved ``_headers`` key so the rotation
    # pool can parse ``X-RateLimit-*`` usage metadata; ``_extract_content`` and
    # the detection probe ignore it (it is not part of the OpenAI envelope).
    decoded.setdefault("_headers", resp_headers)
    return decoded


def _urllib_post_json(
    url: str,
    body: dict[str, Any],
    headers: dict[str, str],
    timeout: float,
    secrets: Sequence[str] = (),
) -> dict[str, Any]:
    """POST ``body`` as JSON to ``url`` and decode the JSON response (stdlib only).

    Uses :mod:`urllib.request` so the sidecar has no hard HTTP dependency for the
    LLM path. The :class:`Transport` shape's ``body`` dict is serialized to JSON.
    ``secrets`` is the provider's own key-set, threaded down so the error body is
    scrubbed of every live key at the construction site (PLAN §WU-keys). It is a
    keyword-only-in-practice extra arg — the 4-positional :data:`Transport` shape
    a test injects is unaffected (those fakes never reach the scrub branch).
    """
    data = json.dumps(body).encode("utf-8")
    req_headers = {"Content-Type": "application/json", **headers}
    return _urllib_request_json(url, method="POST", data=data, headers=req_headers, timeout=timeout, secrets=secrets)


def urllib_get_json(url: str, body: dict[str, Any], headers: dict[str, str], timeout: float) -> dict[str, Any]:
    """GET ``url`` and decode the JSON response (the local-server detection probe).

    Matches the :data:`Transport` shape so it is interchangeable with
    :func:`_urllib_post_json` wherever a transport is injected. A GET carries no
    request body, so the ``body`` dict is intentionally ignored (it exists only to
    keep the four-argument transport signature uniform across POST and GET).
    """
    _ = body  # a GET has no body; the arg exists for transport-shape uniformity.
    return _urllib_request_json(url, method="GET", data=None, headers=dict(headers), timeout=timeout)


# --------------------------------------------------------------------------- #
# Local-server readiness probe (WU-B2: fixes "LLM 10061" refused-connection)
# --------------------------------------------------------------------------- #
#: Path (relative to the server ROOT) of the llama.cpp health endpoint. The chat
#: base URL ends in ``/v1`` but ``/health`` is served at the root.
LOCAL_HEALTH_PATH: str = "/health"
#: HTTP status the ``/health`` endpoint returns once the model is fully loaded.
_HEALTH_OK: int = 200
#: Default bounded wall-clock deadline (seconds) for the readiness poll. Bounded
#: so a slow/failed start becomes an exhausted slot rather than a hang.
DEFAULT_READINESS_TIMEOUT: float = 60.0
#: Default seconds between readiness polls.
DEFAULT_READINESS_POLL_INTERVAL: float = 0.25
#: Default per-request timeout (seconds) for one health GET.
DEFAULT_READINESS_REQUEST_TIMEOUT: float = 5.0


def health_url_from_base(base_url: str) -> str:
    """Derive the llama.cpp ``/health`` URL from an OpenAI-style base URL.

    The chat base URL ends in ``/v1`` (e.g. ``.../8088/v1``) but llama.cpp serves
    ``/health`` at the SERVER ROOT (``.../8088/health``); strip a trailing ``/v1``
    before appending the health path so the readiness probe hits the right route.
    """
    base = base_url.rstrip("/")
    if base.endswith("/v1"):
        base = base[: -len("/v1")].rstrip("/")
    return f"{base}{LOCAL_HEALTH_PATH}"


def _probe_health_status(transport: Transport, url: str, timeout: float) -> int:
    """One health GET -> HTTP status (200 ready, 503 loading, 0 refused/unreachable).

    Reuses the existing GET :data:`Transport` seam (default
    :func:`urllib_get_json`): a 200 returns a JSON body (mapped to ``200``); an
    ``HTTPError`` surfaces as a :class:`ProviderError` carrying ``status_code``
    (``503`` while the model loads); a refused/unreachable connection has
    ``status_code is None`` and maps to ``0`` so the caller keeps waiting.
    """
    try:
        transport(url, {}, {}, timeout)
    except ProviderError as exc:
        return exc.status_code or 0
    return _HEALTH_OK


def readiness_probe(
    health_url: str,
    *,
    transport: Transport,
    now: Callable[[], float],
    sleep: Callable[[float], None],
    child_exited: Callable[[], bool],
    timeout_s: float = DEFAULT_READINESS_TIMEOUT,
    poll_interval_s: float = DEFAULT_READINESS_POLL_INTERVAL,
    request_timeout_s: float = DEFAULT_READINESS_REQUEST_TIMEOUT,
) -> None:
    """Poll ``health_url`` until the local model server is ready or time runs out.

    A bounded wall-clock loop that NEVER hangs (WU-B2). Each iteration first fails
    fast if the child process has exited (``child_exited()`` -> a
    :class:`ProviderError`), then GETs the health endpoint: HTTP ``200`` means the
    model is loaded (return); ``503`` (loading) or a refused/unreachable
    connection keep waiting; once ``now()`` passes the ``timeout_s`` deadline a
    :class:`ProviderError` is RAISED so :class:`RotatingProvider` treats a slow
    start as an exhausted slot instead of blocking forever. Every side-effecting
    collaborator (``transport`` / ``now`` / ``sleep`` / ``child_exited``) is
    injected so the probe is fully unit-testable with no socket and no real wait.
    """
    deadline = now() + timeout_s
    while True:
        if child_exited():
            raise ProviderError("local model server exited before becoming ready")
        if _probe_health_status(transport, health_url, request_timeout_s) == _HEALTH_OK:
            return
        if now() >= deadline:
            raise ProviderError(f"local model server not ready within {timeout_s:g}s")
        sleep(poll_interval_s)


def _extract_content(response: dict[str, Any]) -> str:
    """Pull the assistant message content from an OpenAI-style chat response.

    Shape: ``{"choices":[{"message":{"role":"assistant","content":"..."}}]}``.
    Raises :class:`ProviderError` when the expected path is absent so a malformed
    response is a hard error rather than a silent empty string.
    """
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ProviderError("LLM response had no choices")
    first = choices[0]
    if not isinstance(first, dict):
        raise ProviderError("LLM choice was not an object")
    message = first.get("message")
    if isinstance(message, dict) and isinstance(message.get("content"), str):
        return message["content"]
    # Some llama.cpp builds echo a bare ``text`` field on the choice.
    if isinstance(first.get("text"), str):
        return first["text"]
    raise ProviderError("LLM response had no message content")


# --------------------------------------------------------------------------- #
# Provider ABC (the §4 interface: complete / chat)
# --------------------------------------------------------------------------- #
class Provider(abc.ABC):
    """Abstract LLM provider (CONTRACTS.md §4 ``Provider interface (complete/chat)``).

    Subclasses implement :meth:`chat`. :meth:`complete` is provided concretely as
    a single-turn convenience built on top of ``chat`` so every provider exposes
    both methods named in the contract without re-implementing the wrapper.
    """

    @abc.abstractmethod
    def chat(
        self,
        messages: Sequence[Message],
        *,
        temperature: float = DEFAULT_TEMPERATURE,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        **kwargs: Any,
    ) -> str:
        """Send a chat ``messages`` list, return the assistant content string.

        ``messages`` is a sequence of ``{"role","content"}`` dicts. ``temperature``
        / ``max_tokens`` map to the sampling params; any extra ``**kwargs`` are
        accepted (and may be forwarded) so callers that pass nothing
        (subtitles.py) and callers that pass both (select.py) both work.
        """
        raise NotImplementedError

    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = DEFAULT_TEMPERATURE,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        **kwargs: Any,
    ) -> str:
        """Single-turn completion: wrap ``prompt`` (+ optional ``system``) in a chat.

        This is the §4 ``complete`` half of the interface, implemented once here
        in terms of :meth:`chat` so subclasses only implement the transport.
        """
        messages: list[Message] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return self.chat(messages, temperature=temperature, max_tokens=max_tokens, **kwargs)


class _OpenAICompatProvider(Provider):
    """Shared implementation for any OpenAI-compatible ``/v1/chat/completions`` API.

    Both :class:`LocalServerProvider` (llama.cpp) and :class:`CloudProvider` are
    this same wire protocol differing only in base URL, model id, and an optional
    bearer header — so the request-building + parsing lives here once.
    """

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        transport: Transport | None = None,
    ) -> None:
        # Normalize a trailing slash so f-strings below never double it.
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._api_key = api_key
        self.timeout = timeout
        # Default to the stdlib urllib transport; tests inject a fake. The default
        # transport is bound to THIS provider's key-set so its error body is
        # scrubbed of the live key at the construction site (PLAN §WU-keys
        # ENFORCEABLE SCRUB); an injected fake keeps the plain 4-arg Transport
        # shape (it never reaches the real scrub branch).
        if transport is not None:
            self._transport: Transport = transport
        else:
            secrets = (api_key,) if api_key else ()
            self._transport = functools.partial(_urllib_post_json, secrets=secrets)

    def _headers(self) -> dict[str, str]:
        """Build request headers, adding a bearer token only when a key is set."""
        headers: dict[str, str] = {}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    def chat(
        self,
        messages: Sequence[Message],
        *,
        temperature: float = DEFAULT_TEMPERATURE,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        **kwargs: Any,
    ) -> str:
        url = f"{self.base_url}/chat/completions"
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [dict(m) for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        # Forward whitelisted extra sampling knobs if a caller passes them; unknown
        # kwargs are ignored so the seam stays forgiving (subtitles passes none).
        for key in ("top_p", "stop", "presence_penalty", "frequency_penalty", "seed"):
            if key in kwargs and kwargs[key] is not None:
                body[key] = kwargs[key]
        log.debug("LLM chat -> %s (model=%s, %d msgs)", url, self.model, len(body["messages"]))
        response = self._transport(url, body, self._headers(), self.timeout)
        return _extract_content(response)

    def chat_full(
        self,
        messages: Sequence[Message],
        *,
        temperature: float = DEFAULT_TEMPERATURE,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        **kwargs: Any,
    ) -> tuple[str, dict[str, Any]]:
        """Like :meth:`chat` but also returns the raw response dict.

        The rotation pool uses this so it can read ``X-RateLimit-*`` usage
        metadata (surfaced under the response's ``_headers`` key) alongside the
        assistant content. Re-uses :meth:`chat`'s body shaping by re-issuing the
        request once — kept tiny so the single-provider :meth:`chat` path is
        unaffected for the legacy callers that do not need the response.
        """
        url = f"{self.base_url}/chat/completions"
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [dict(m) for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        for key in ("top_p", "stop", "presence_penalty", "frequency_penalty", "seed"):
            if key in kwargs and kwargs[key] is not None:
                body[key] = kwargs[key]
        response = self._transport(url, body, self._headers(), self.timeout)
        return _extract_content(response), response


class LocalServerProvider(_OpenAICompatProvider):
    """Talks to the local llama.cpp OpenAI-compatible server (CONTRACTS.md §7).

    The server itself is started/stopped by ``models/runner.py``; this provider
    only issues HTTP requests to it. No API key is needed for the local server.
    """

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_LOCAL_BASE_URL,
        model: str = DEFAULT_LOCAL_MODEL,
        timeout: float = DEFAULT_TIMEOUT,
        transport: Transport | None = None,
    ) -> None:
        super().__init__(
            base_url=base_url,
            model=model,
            api_key=None,
            timeout=timeout,
            transport=transport,
        )


class CloudProvider(_OpenAICompatProvider):
    """Optional cloud LLM, used ONLY when ``settings.useCloud`` + a key (§2).

    Identical wire protocol to the local server but with a base URL pointing at a
    hosted OpenAI-compatible endpoint and a bearer ``api_key``. Lean by design: no
    keystore, no rotation — the key comes straight from settings (§0/§6).
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = DEFAULT_CLOUD_BASE_URL,
        model: str = DEFAULT_CLOUD_MODEL,
        timeout: float = DEFAULT_TIMEOUT,
        transport: Transport | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("CloudProvider requires a non-empty api_key")
        super().__init__(
            base_url=base_url,
            model=model,
            api_key=api_key,
            timeout=timeout,
            transport=transport,
        )


# --------------------------------------------------------------------------- #
# RotatingProvider (WU-pool): multi-PROVIDER rotation over an ordered key pool
# --------------------------------------------------------------------------- #
#: Default per-window cooldown (seconds) a key is skipped after a 429/5xx before
#: it becomes eligible again. Computed purely from ``now()`` deltas — the module
#: imports NEITHER ``time`` NOR ``asyncio`` and the hot path never sleeps.
DEFAULT_COOLDOWN_SECONDS: float = 60.0

#: The default capability a chat request needs of a pool entry.
DEFAULT_CAPABILITY: str = "text"

#: The sentinel provider id meaning "the local backstop only" (matches
#: ``presets.LOCAL``). When a per-function routing slot prefers this, the factory
#: builds a local-only pool so the privacy/all-local route never egresses cloud.
LOCAL_PROVIDER_ID: str = "local"


def _default_now() -> float:
    """The default wall-clock source (replaced by a fake clock in tests).

    Imported lazily so the MODULE itself never imports ``time`` at top level (the
    no-sleep / deterministic-clock rule, PLAN §WU-pool): ``time`` is reached only
    when the real default clock is actually called, and tests inject their own
    ``now`` so this line is never executed under the gate.
    """
    import time as _time  # noqa: PLC0415 - lazy so the module has no top-level time import

    return _time.monotonic()  # pragma: no cover -- real wall-clock; tests inject a fake now()


@dataclass(frozen=True)
class PoolEntrySpec:
    """The static description of one pool entry (a provider + its key list).

    Same-provider extra ``keys`` are FAILOVER only — never advertised as N×quota
    (PLAN SE2). ``local`` flags the always-available llama.cpp/Ollama/LM-Studio
    backstop, which is sorted last and carries no key.
    """

    provider: str
    kind: str
    base_url: str
    model: str
    keys: tuple[str, ...]
    capabilities: tuple[str, ...] = (DEFAULT_CAPABILITY,)
    unit: str = "req"
    local: bool = False


@dataclass(frozen=True)
class RotationEvent:
    """Emitted once per failover so the envelope/UI can show what rotated.

    ``from_key`` / ``to_key`` are REDACTED (last-4 only); the live key is never
    carried. ``reason`` is the (already-scrubbed) failure summary.
    """

    provider: str
    from_key: str
    to_key: str
    reason: str


class _LiveKey:
    """One concrete (entry, key) slot: its provider + a mutable usage/cooldown.

    ``cooled_until`` is an absolute ``now()`` value: the slot is skipped while
    ``now() < cooled_until``. ``used`` is an optimistic counter; ``max`` /
    ``reset_at`` are filled from parsed ``X-RateLimit-*`` headers when present.
    """

    def __init__(self, *, spec: PoolEntrySpec, key: str | None, transport: Transport | None) -> None:
        self.spec = spec
        self.key = key
        self.provider = _OpenAICompatProvider(
            base_url=spec.base_url,
            model=spec.model,
            api_key=key,
            transport=transport,
        )
        self.used: int = 0
        self.max: int | None = None
        self.reset_at: float | None = None
        self.cooled_until: float = 0.0

    @property
    def redacted_key(self) -> str:
        """The display-safe last-4 redaction of this slot's key (``"local"`` keyless)."""
        return redact(self.key) if self.key else "local"

    def eligible(self, *, now: float, capability: str) -> bool:
        """True iff this slot can serve ``capability`` and its cooldown has lapsed."""
        if capability not in self.spec.capabilities:
            return False
        return now >= self.cooled_until


def _parse_rate_limit_headers(response: dict[str, Any]) -> tuple[int | None, int | None]:
    """Parse ``(limit, remaining)`` from a response's ``_headers`` (or ``(None, None)``).

    Reads the de-facto ``X-RateLimit-Limit`` / ``X-RateLimit-Remaining`` headers
    (case-insensitively); a missing/garbage header yields ``None`` for that field.
    """
    headers = response.get("_headers")
    if not isinstance(headers, dict):
        return None, None
    lowered = {str(k).lower(): v for k, v in headers.items()}

    def _as_int(name: str) -> int | None:
        raw = lowered.get(name)
        try:
            return int(str(raw)) if raw is not None else None
        except (TypeError, ValueError):
            return None

    return _as_int("x-ratelimit-limit"), _as_int("x-ratelimit-remaining")


def _retry_after_seconds(message: str) -> float | None:
    """Best-effort parse of a ``retry-after=<n>`` hint from a 429 error message."""
    marker = "retry-after="
    idx = message.lower().find(marker)
    if idx < 0:
        return None
    tail = message[idx + len(marker) :]
    digits = ""
    for ch in tail:
        if ch.isdigit() or (ch == "." and "." not in digits):
            digits += ch
        else:
            break
    try:
        return float(digits) if digits else None
    except ValueError:  # pragma: no cover -- guarded by the digit-only accumulation above
        return None


class RotatingProvider(Provider):
    """A :class:`Provider` fronting an ordered pool of OpenAI-compatible keys.

    Reactive failover: a 429/5xx (or any transient provider error) on the active
    key advances to the next ELIGIBLE key and emits exactly one ``rotation``
    event. A throttled key is put on a per-window cooldown and SKIPPED (never
    awaited) until ``now()`` passes its window — the hot path NEVER sleeps. The
    local backstop is always last, so an offline run still works once every cloud
    key is exhausted. Per-key usage ``{used, max, unit, resetAt}`` is tracked from
    optimistic decrement + parsed ``X-RateLimit-*`` headers (for the usage UI).
    """

    def __init__(
        self,
        *,
        pool: Sequence[PoolEntrySpec],
        now: Callable[[], float] = _default_now,
        transport: Transport | None = None,
        cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS,
        ensure: Callable[[], None] | None = None,
    ) -> None:
        specs = list(pool)
        if not specs:
            raise ValueError("RotatingProvider requires a non-empty pool")
        self._now = now
        self._cooldown = float(cooldown_seconds)
        # WU-B2: the injected opaque llama-backstop ensure() callback. Invoked
        # lazily ONLY before the ``local`` backstop slot is tried (see ``chat``),
        # so an all-local run auto-starts the llama.cpp server; a slow/failed
        # start RAISES a ProviderError and is treated as an exhausted slot. The
        # provider module stays runner-free — the engine layer that owns the
        # ModelRunner builds and injects this callback.
        self._ensure = ensure
        # Sort the local backstop(s) to the very end; cloud keys keep pool order.
        ordered = sorted(specs, key=lambda s: 1 if s.local else 0)
        self._slots: list[_LiveKey] = []
        for spec in ordered:
            keys: Sequence[str | None] = spec.keys or (None,) if spec.local else spec.keys
            for key in keys:
                self._slots.append(_LiveKey(spec=spec, key=key, transport=transport))
        self._rotation_cbs: list[Callable[[RotationEvent], None]] = []

    # -- public hooks --------------------------------------------------------
    def on_rotation(self, callback: Callable[[RotationEvent], None]) -> None:
        """Register a ``rotation`` callback (one call per failover)."""
        self._rotation_cbs.append(callback)

    @property
    def entries(self) -> tuple[PoolEntrySpec, ...]:
        """The distinct entry specs in pool order (for budget/degrade-chain)."""
        seen: set[int] = set()
        out: list[PoolEntrySpec] = []
        for slot in self._slots:
            ident = id(slot.spec)
            if ident not in seen:
                seen.add(ident)
                out.append(slot.spec)
        return tuple(out)

    def provider_groups(self) -> tuple[str, ...]:
        """Distinct CLOUD provider names (same-provider keys collapse to one)."""
        seen: set[str] = set()
        out: list[str] = []
        for slot in self._slots:
            if slot.spec.local:
                continue
            if slot.spec.provider not in seen:
                seen.add(slot.spec.provider)
                out.append(slot.spec.provider)
        return tuple(out)

    def usage(self) -> list[dict[str, Any]]:
        """Per-key usage rows ``{provider, key(redacted), used, max, unit, resetAt}``."""
        return [
            {
                "provider": slot.spec.provider,
                "key": slot.redacted_key,
                "used": slot.used,
                "max": slot.max,
                "unit": slot.spec.unit,
                "resetAt": slot.reset_at,
            }
            for slot in self._slots
        ]

    # -- the Provider.chat seam ---------------------------------------------
    def chat(
        self,
        messages: Sequence[Message],
        *,
        temperature: float = DEFAULT_TEMPERATURE,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        capability: str = DEFAULT_CAPABILITY,
        **kwargs: Any,
    ) -> str:
        """Try eligible keys in pool order until one succeeds; rotate on failure.

        Raises a single :class:`ProviderError` (never hangs) once every eligible
        key — including the local backstop — has failed. ``capability`` filters
        the pool to entries that can serve the request (e.g. ``"vision"``).
        """
        failures: list[str] = []
        active: _LiveKey | None = None
        for slot in self._slots:
            now = self._now()
            if not slot.eligible(now=now, capability=capability):
                continue
            # WU-B2: lazily ensure the llama backstop is up BEFORE its first chat
            # (never for a cloud key or a detected Ollama/LM-Studio slot). A slow
            # start raises ProviderError -> handled exactly like a chat failure
            # (cool + rotate), so the pool advances instead of hanging.
            if self._ensure is not None and slot.spec.provider == LOCAL_PROVIDER_ID:
                try:
                    self._ensure()
                except ProviderError as exc:
                    self._on_failure(slot, exc, failures)
                    if active is not None:
                        self._emit_rotation(active, slot, str(exc))
                    active = slot
                    continue
            try:
                content, response = slot.provider.chat_full(
                    messages, temperature=temperature, max_tokens=max_tokens, **kwargs
                )
            except ProviderError as exc:
                self._on_failure(slot, exc, failures)
                if active is not None:
                    self._emit_rotation(active, slot, str(exc))
                active = slot
                continue
            self._on_success(slot, response)
            if active is not None:
                # We advanced PAST a prior failed key to land on this one.
                self._emit_rotation(active, slot, "recovered")
            return content
        raise ProviderError(self._exhausted_message(capability, failures))

    # -- internals ----------------------------------------------------------
    def _on_success(self, slot: _LiveKey, response: dict[str, Any]) -> None:
        """Record an optimistic use + any authoritative ``X-RateLimit-*`` headers."""
        slot.used += 1
        limit, remaining = _parse_rate_limit_headers(response)
        if limit is not None:
            slot.max = limit
            if remaining is not None:
                slot.used = max(0, limit - remaining)

    def _on_failure(self, slot: _LiveKey, exc: ProviderError, failures: list[str]) -> None:
        """Cool the failed key for its window and record a SCRUBBED failure line."""
        message = scrub_error_body(str(exc), [slot.key] if slot.key else [])
        retry_after = _retry_after_seconds(message)
        window = retry_after if retry_after is not None else self._cooldown
        slot.cooled_until = self._now() + window
        slot.reset_at = slot.cooled_until
        failures.append(f"{slot.spec.provider} ({slot.redacted_key}): {message}")

    def _emit_rotation(self, from_slot: _LiveKey, to_slot: _LiveKey, reason: str) -> None:
        event = RotationEvent(
            provider=to_slot.spec.provider,
            from_key=from_slot.redacted_key,
            to_key=to_slot.redacted_key,
            reason=scrub_error_body(reason, [k for k in (from_slot.key, to_slot.key) if k]),
        )
        for cb in self._rotation_cbs:
            cb(event)

    def _exhausted_message(self, capability: str, failures: list[str]) -> str:
        detail = "; ".join(failures) if failures else "no eligible keys"
        return f"provider pool exhausted ({capability}): {detail}"


def build_pool_provider(
    settings: dict[str, Any] | None,
    *,
    transport: Transport | None = None,
    probe_transport: Transport | None = None,
    detect_local: bool = True,
    prefer: str | None = None,
    ensure: Callable[[], None] | None = None,
) -> RotatingProvider:
    """Build a :class:`RotatingProvider` from ``settings.providers`` + local detect.

    Folds in any locally-running Ollama / LM Studio servers (probed via
    ``probe_transport``, default :func:`urllib_get_json`) and ALWAYS appends the
    llama.cpp local backstop last so an offline run still works. ``transport`` is
    the chat transport; ``probe_transport`` the GET detection transport.

    ``detect_local=False`` SKIPS the live Ollama/LM-Studio ``GET /models`` probe
    entirely (no socket): the budget/route planner (``ai_job.plan_ai_job``) only
    needs the cloud providers + the llama backstop and must NOT open a socket, so
    it builds the pool with detection off. The runtime execution path keeps the
    default ``True`` so live local servers are still discovered when a call runs.

    ``prefer`` (WU-presets per-function routing): the configured provider ``id``
    the active function prefers. The matching provider spec is moved to the FRONT
    of the cloud pool (tried first), the rest kept as failover, the local backstop
    still last. ``prefer == LOCAL_PROVIDER_ID`` yields a local-only pool (the
    privacy/all-local route — NO cloud entry, so it never egresses). An unknown id
    is a no-op (configured order kept), so a stale routing choice never breaks the
    pool.
    """
    settings = settings or {}
    if prefer == LOCAL_PROVIDER_ID:
        # Privacy/all-local route: skip cloud specs entirely (zero cloud egress).
        return RotatingProvider(pool=[_llama_backstop_spec(settings)], transport=transport, ensure=ensure)
    specs = _cloud_specs_from_settings(_prefer_provider_first(settings, prefer))
    if detect_local:
        specs.extend(_detected_local_specs(settings, probe_transport=probe_transport))
    specs.append(_llama_backstop_spec(settings))
    return RotatingProvider(pool=specs, transport=transport, ensure=ensure)


def _prefer_provider_first(settings: dict[str, Any], prefer: str | None) -> dict[str, Any]:
    """Return ``settings`` with ``providers`` reordered so ``prefer`` (an id) is first.

    PURE: a new settings dict with a reordered ``providers`` list (the original is
    never mutated). ``prefer`` of ``None`` or an unknown id leaves the order
    unchanged — the matching entry (by ``id``) is simply hoisted to the front so
    the per-function preferred provider is tried before the rest of the pool.
    """
    if not prefer:
        return settings
    providers = settings.get("providers")
    if not isinstance(providers, list):
        return settings
    preferred = [p for p in providers if isinstance(p, dict) and p.get("id") == prefer]
    if not preferred:
        return settings
    rest = [p for p in providers if not (isinstance(p, dict) and p.get("id") == prefer)]
    return {**settings, "providers": [*preferred, *rest]}


def _cloud_specs_from_settings(settings: dict[str, Any]) -> list[PoolEntrySpec]:
    """Materialize enabled, keyed cloud providers from ``settings.providers``."""
    specs: list[PoolEntrySpec] = []
    for raw in settings.get("providers") or []:
        if not isinstance(raw, dict):
            continue
        if not raw.get("enabled", True):
            continue
        keys = tuple(str(k) for k in (raw.get("apiKeys") or []) if k)
        if not keys:
            continue
        specs.append(
            PoolEntrySpec(
                provider=str(raw.get("provider") or raw.get("id") or "cloud"),
                kind=str(raw.get("kind") or "cloud"),
                base_url=str(raw.get("baseUrl") or DEFAULT_CLOUD_BASE_URL),
                model=str(raw.get("model") or DEFAULT_CLOUD_MODEL),
                keys=keys,
                capabilities=tuple(str(c) for c in (raw.get("capabilities") or [DEFAULT_CAPABILITY])),
                unit=str(raw.get("unit") or "req"),
                local=False,
            )
        )
    return specs


def _detected_local_specs(settings: dict[str, Any], *, probe_transport: Transport | None) -> list[PoolEntrySpec]:
    """Probe Ollama/LM Studio (best-effort) and turn live ones into pool specs."""
    from . import local_detect  # local import: avoids an import cycle at module load

    probe = probe_transport or urllib_get_json
    detected = local_detect.detect_local_servers(settings, transport=probe)
    return [
        PoolEntrySpec(
            provider=entry["kind"],
            kind=entry["kind"],
            base_url=entry["base_url"],
            model=entry["model"],
            keys=(),
            capabilities=tuple(entry["capabilities"]),
            unit=entry["unit"],
            local=True,
        )
        for entry in detected
    ]


def _llama_backstop_spec(settings: dict[str, Any]) -> PoolEntrySpec:
    """The always-present llama.cpp local backstop entry (no key, sorted last)."""
    return PoolEntrySpec(
        provider="local",
        kind="local",
        base_url=str(settings.get("localBaseUrl") or DEFAULT_LOCAL_BASE_URL),
        model=str(settings.get("localModel") or DEFAULT_LOCAL_MODEL),
        keys=(),
        capabilities=(DEFAULT_CAPABILITY,),
        unit="req",
        local=True,
    )


# --------------------------------------------------------------------------- #
# Factory (CONTRACTS.md §2 settings.*)
# --------------------------------------------------------------------------- #
def get_provider(
    settings: dict[str, Any] | None = None,
    *,
    transport: Transport | None = None,
    prefer: str | None = None,
    ensure: Callable[[], None] | None = None,
) -> Provider:
    """Return the right :class:`Provider` for ``settings`` (CONTRACTS.md §2).

    When ``settings.providers`` lists at least one enabled, keyed cloud provider
    a pool-aware :class:`RotatingProvider` is returned (WU-pool); otherwise the
    existing fall-through is UNCHANGED — a :class:`CloudProvider` when
    ``settings.useCloud`` is truthy AND a non-empty ``cloudApiKey`` is present,
    else a :class:`LocalServerProvider` pointed at the local llama.cpp server.
    ``transport`` is forwarded so tests can inject a fake HTTP transport.

    ``prefer`` (WU-presets) is the configured provider ``id`` the active function
    prefers; it is threaded into :func:`build_pool_provider` so the per-function
    seam tries that provider first (``LOCAL_PROVIDER_ID`` -> local-only). It only
    applies on the pool path; the legacy single-provider fall-through ignores it.

    CONTRACT-NOTE: §2 names ``{useCloud, cloudApiKey?, modelsDir, ffmpegPath}``.
    Optional ``localBaseUrl`` / ``localModel`` / ``cloudBaseUrl`` / ``cloudModel``
    overrides are honored when present but are NOT required by the contract.
    """
    settings = settings or {}

    # WU-pool: a configured multi-provider pool takes precedence over the legacy
    # single-provider routing (which stays for back-compat when no pool is set).
    # A prefer==LOCAL route is honored even with cloud providers configured.
    if prefer == LOCAL_PROVIDER_ID or _cloud_specs_from_settings(settings):
        return build_pool_provider(settings, transport=transport, prefer=prefer, ensure=ensure)

    use_cloud = bool(settings.get("useCloud"))
    api_key = settings.get("cloudApiKey") or ""

    if use_cloud and api_key:
        return CloudProvider(
            api_key=str(api_key),
            base_url=str(settings.get("cloudBaseUrl") or DEFAULT_CLOUD_BASE_URL),
            model=str(settings.get("cloudModel") or DEFAULT_CLOUD_MODEL),
            transport=transport,
        )

    if use_cloud and not api_key:
        # CONTRACT-NOTE: useCloud requested but no key -> we do NOT raise; we fall
        # back to the local server so the app stays usable offline (lean, §0).
        log.warning("useCloud is set but cloudApiKey is empty; using local server")

    if ensure is not None:
        # WU-B2: the legacy bare-local fall-through has no llama-backstop slot to
        # auto-start. When an ensure() is injected, route through a local-only
        # pool so the injected callback can bring the llama.cpp server up first
        # (fixes "LLM 10061" for a fresh all-local config). No cloud spec exists
        # here, so a local-only pool is behaviourally identical for the call.
        return build_pool_provider(settings, transport=transport, prefer=LOCAL_PROVIDER_ID, ensure=ensure)

    return LocalServerProvider(
        base_url=str(settings.get("localBaseUrl") or DEFAULT_LOCAL_BASE_URL),
        model=str(settings.get("localModel") or DEFAULT_LOCAL_MODEL),
        transport=transport,
    )
