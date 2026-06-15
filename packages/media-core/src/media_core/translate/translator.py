"""Translator interface and built-in implementations.

Provides an abstract :class:`Translator` plus a no-op fallback, a cloud-backed
LLM translator, and an offline ``argostranslate`` implementation. Each concrete
class intentionally exposes a single public ``translate_batch`` method as part
of a strategy-style interface.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import Callable, List, Optional


class Translator(ABC):
    """Abstract base for translators that convert batches of strings."""

    # pylint: disable=too-few-public-methods

    @abstractmethod
    def translate_batch(self, texts: List[str], src: str, tgt: str) -> List[str]:
        """Translate a batch of strings from src to tgt."""
        raise NotImplementedError


class NoOpTranslator(Translator):
    """Local fallback translator that returns the input unchanged."""

    # pylint: disable=too-few-public-methods

    def translate_batch(
        self, texts: List[str], src: str, tgt: str
    ) -> List[str]:  # pragma: no cover - trivial
        return texts


class CloudTranslator(Translator):
    """Simple cloud-backed translator using an LLM-style chat client.

    The client is expected to expose `chat.completions.create(model=..., messages=[...])`
    similar to OpenAI or Groq SDKs. Provide a pre-configured client instance to avoid
    importing optional dependencies directly from this package.
    """

    # pylint: disable=too-few-public-methods

    def __init__(
        self,
        client: object,
        model: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.0,
        postprocess: Optional[Callable[[str], str]] = None,
    ) -> None:
        if client is None:
            raise ValueError("CloudTranslator requires a chat client instance")
        self.client = client
        self.model = model
        self.system_prompt = system_prompt or (
            "You are a translation engine. Translate user text from {src} to {tgt}. "
            "Reply with the translated text only."
        )
        self.temperature = temperature
        self.postprocess = postprocess

    def translate_batch(self, texts: List[str], src: str, tgt: str) -> List[str]:
        if os.getenv("REFRAME_OFFLINE_MODE", "").strip().lower() in {"1", "true", "yes", "on"}:
            raise RuntimeError("REFRAME_OFFLINE_MODE is enabled; refusing to use cloud translator.")
        results: List[str] = []
        for text in texts:
            messages = [
                {"role": "system", "content": self.system_prompt.format(src=src, tgt=tgt)},
                {
                    "role": "user",
                    "content": (
                        f"Translate this from {src} to {tgt}. "
                        f"Reply with translation only: {text}"
                    ),
                },
            ]

            try:
                resp = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=self.temperature,
                )
                content = getattr(
                    resp.choices[0].message, "content", ""
                )  # type: ignore[attr-defined]
                cleaned = content.strip() if content else text
                if self.postprocess:
                    cleaned = self.postprocess(cleaned)
                results.append(cleaned or text)
            except Exception:  # pylint: disable=broad-exception-caught
                # Fallback to original text if the provider fails for any reason.
                results.append(text)
        return results


class LocalTranslator(Translator):
    """Offline translator using argostranslate if available."""

    # pylint: disable=too-few-public-methods

    def __init__(self, src: str, tgt: str):
        try:
            # Imported lazily so the optional dependency is only required at runtime.
            from argostranslate import translate  # type: ignore  # pylint: disable=import-outside-toplevel
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "argostranslate is not installed; install extras 'translate-local'"
            ) from exc

        languages = translate.get_installed_languages()
        self._src_lang = next((l for l in languages if l.code == src), None)  # noqa: E741
        self._tgt_lang = next((l for l in languages if l.code == tgt), None)  # noqa: E741
        if not self._src_lang or not self._tgt_lang:
            raise RuntimeError(f"argostranslate missing language pack for {src}->{tgt}")
        self._translator = self._src_lang.get_translation(self._tgt_lang)

    def translate_batch(self, texts: List[str], src: str, tgt: str) -> List[str]:
        return [self._translator.translate(text) for text in texts]
