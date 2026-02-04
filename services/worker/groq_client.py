from __future__ import annotations

import json
import os
import urllib.request
from types import SimpleNamespace
from typing import Any, Optional


def _truthy_env(name: str) -> bool:
    value = os.getenv(name, "").strip().lower()
    return value in {"1", "true", "yes", "on"}


class GroqChatClient:
    """Minimal OpenAI-compatible chat client for Groq.

    Exposes `chat.completions.create(model=..., messages=[...])` so it can be used with
    `media_core.translate.CloudTranslator` and `media_core.segment.shorts.score_segments_llm`.
    """

    def __init__(self, *, api_key: str, base_url: str = "https://api.groq.com/openai/v1", timeout_seconds: float = 30.0) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

        # OpenAI SDK shape compatibility
        self.chat = self
        self.completions = self

    def create(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
        response_format: Optional[dict[str, Any]] = None,
    ):
        if _truthy_env("REFRAME_OFFLINE_MODE"):
            raise RuntimeError("REFRAME_OFFLINE_MODE is enabled; refusing to call Groq API.")

        payload: dict[str, Any] = {"model": model, "messages": messages, "temperature": temperature}
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if response_format is not None:
            payload["response_format"] = response_format

        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=body,
            method="POST",
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"},
        )
        with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:  # noqa: S310 - intended outbound request (gated)
            data = resp.read()

        parsed = json.loads(data.decode("utf-8"))
        content = ""
        try:
            content = parsed["choices"][0]["message"]["content"]
        except Exception:
            content = ""

        # Return a minimal object compatible with OpenAI SDK response shape used in this repo.
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def get_groq_chat_client_from_env() -> Optional[GroqChatClient]:
    if _truthy_env("REFRAME_OFFLINE_MODE"):
        return None
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        return None
    base_url = os.getenv("GROQ_BASE_URL", "").strip() or "https://api.groq.com/openai/v1"
    timeout_raw = os.getenv("GROQ_TIMEOUT_SECONDS", "").strip() or "30"
    try:
        timeout = float(timeout_raw)
    except ValueError:
        timeout = 30.0
    return GroqChatClient(api_key=api_key, base_url=base_url, timeout_seconds=timeout)

