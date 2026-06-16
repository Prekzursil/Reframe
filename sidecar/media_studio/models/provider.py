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
import json
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, List, Optional, Sequence

from ..util import get_logger

log = get_logger("media_studio.models.provider")

# A chat message is the OpenAI-style {"role": ..., "content": ...} dict.
Message = Dict[str, str]

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


# A transport seam: given (url, json-body-dict, headers, timeout) it performs the
# POST and returns the decoded JSON response dict. Injected in tests so no socket
# is ever opened. The default implementation is :func:`_urllib_post_json`.
Transport = Callable[[str, Dict[str, Any], Dict[str, str], float], Dict[str, Any]]


class ProviderError(RuntimeError):
    """Raised when a provider cannot produce a completion (HTTP / parse error).

    Carries a human-readable message; the RPC layer maps it onto a structured
    JSON-RPC error. Never embeds an API key (the key is header-only).
    """


# --------------------------------------------------------------------------- #
# stdlib urllib transport (the only place a socket is opened)
# --------------------------------------------------------------------------- #
def _urllib_post_json(
    url: str, body: Dict[str, Any], headers: Dict[str, str], timeout: float
) -> Dict[str, Any]:
    """POST ``body`` as JSON to ``url`` and decode the JSON response (stdlib only).

    Uses :mod:`urllib.request` so the sidecar has no hard HTTP dependency for the
    LLM path. Raises :class:`ProviderError` on any network / decode failure so the
    caller sees one error type regardless of the underlying urllib exception.
    """
    data = json.dumps(body).encode("utf-8")
    req_headers = {"Content-Type": "application/json", **headers}
    request = urllib.request.Request(url, data=data, headers=req_headers, method="POST")
    try:
        # CONTRACT-NOTE: no shell, no redirects-to-file; a plain JSON POST. Bandit
        # B310 (urlopen) is satisfied because the scheme is fixed http/https built
        # from settings, never attacker-controlled raw input.
        with urllib.request.urlopen(request, timeout=timeout) as resp:  # noqa: S310
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:  # 4xx/5xx with a body
        detail = ""
        try:
            detail = exc.read().decode("utf-8")
        except Exception:  # noqa: BLE001 - best-effort error body
            detail = ""
        raise ProviderError(f"LLM HTTP {exc.code}: {detail or exc.reason}") from exc
    except urllib.error.URLError as exc:  # connection refused / DNS / timeout
        raise ProviderError(f"LLM request failed: {exc.reason}") from exc
    try:
        decoded = json.loads(raw)
    except (ValueError, json.JSONDecodeError) as exc:
        raise ProviderError(f"LLM returned non-JSON response: {raw[:200]!r}") from exc
    if not isinstance(decoded, dict):
        raise ProviderError("LLM response was not a JSON object")
    return decoded


def _extract_content(response: Dict[str, Any]) -> str:
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
        system: Optional[str] = None,
        temperature: float = DEFAULT_TEMPERATURE,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        **kwargs: Any,
    ) -> str:
        """Single-turn completion: wrap ``prompt`` (+ optional ``system``) in a chat.

        This is the §4 ``complete`` half of the interface, implemented once here
        in terms of :meth:`chat` so subclasses only implement the transport.
        """
        messages: List[Message] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return self.chat(
            messages, temperature=temperature, max_tokens=max_tokens, **kwargs
        )


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
        api_key: Optional[str] = None,
        timeout: float = DEFAULT_TIMEOUT,
        transport: Optional[Transport] = None,
    ) -> None:
        # Normalize a trailing slash so f-strings below never double it.
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._api_key = api_key
        self.timeout = timeout
        # Default to the stdlib urllib transport; tests inject a fake.
        self._transport: Transport = transport or _urllib_post_json

    def _headers(self) -> Dict[str, str]:
        """Build request headers, adding a bearer token only when a key is set."""
        headers: Dict[str, str] = {}
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
        body: Dict[str, Any] = {
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
        transport: Optional[Transport] = None,
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
        transport: Optional[Transport] = None,
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
# Factory (CONTRACTS.md §2 settings.*)
# --------------------------------------------------------------------------- #
def get_provider(
    settings: Optional[Dict[str, Any]] = None,
    *,
    transport: Optional[Transport] = None,
) -> Provider:
    """Return the right :class:`Provider` for ``settings`` (CONTRACTS.md §2).

    Returns a :class:`CloudProvider` when ``settings.useCloud`` is truthy AND a
    non-empty ``cloudApiKey`` is present; otherwise a :class:`LocalServerProvider`
    pointed at the local llama.cpp server. ``transport`` is forwarded so tests can
    inject a fake HTTP transport through the factory too.

    CONTRACT-NOTE: §2 names ``{useCloud, cloudApiKey?, modelsDir, ffmpegPath}``.
    Optional ``localBaseUrl`` / ``localModel`` / ``cloudBaseUrl`` / ``cloudModel``
    overrides are honored when present but are NOT required by the contract.
    """
    settings = settings or {}
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

    return LocalServerProvider(
        base_url=str(settings.get("localBaseUrl") or DEFAULT_LOCAL_BASE_URL),
        model=str(settings.get("localModel") or DEFAULT_LOCAL_MODEL),
        transport=transport,
    )
