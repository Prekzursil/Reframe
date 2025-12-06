from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable, List, Optional


class Translator(ABC):
    @abstractmethod
    def translate_batch(self, texts: List[str], src: str, tgt: str) -> List[str]:
        """Translate a batch of strings from src to tgt."""
        raise NotImplementedError


class NoOpTranslator(Translator):
    """Local fallback translator that returns the input unchanged."""

    def translate_batch(self, texts: List[str], src: str, tgt: str) -> List[str]:  # pragma: no cover - trivial
        return texts


class CloudTranslator(Translator):
    """Simple cloud-backed translator using an LLM-style chat client.

    The client is expected to expose `chat.completions.create(model=..., messages=[...])`
    similar to OpenAI or Groq SDKs. Provide a pre-configured client instance to avoid
    importing optional dependencies directly from this package.
    """

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
        results: List[str] = []
        for text in texts:
            messages = [
                {"role": "system", "content": self.system_prompt.format(src=src, tgt=tgt)},
                {
                    "role": "user",
                    "content": f"Translate this from {src} to {tgt}. Reply with translation only: {text}",
                },
            ]

            try:
                resp = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=self.temperature,
                )
                content = getattr(resp.choices[0].message, "content", "")  # type: ignore[attr-defined]
                cleaned = content.strip() if content else text
                if self.postprocess:
                    cleaned = self.postprocess(cleaned)
                results.append(cleaned or text)
            except Exception:
                # Fallback to original text if the provider fails
                results.append(text)
        return results


class LocalTranslator(Translator):
    """Offline translator using argostranslate if available."""

    def __init__(self, src: str, tgt: str):
        try:
            from argostranslate import translate  # type: ignore
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("argostranslate is not installed; install extras 'translate-local'") from exc

        languages = translate.get_installed_languages()
        self._src_lang = next((l for l in languages if l.code == src), None)
        self._tgt_lang = next((l for l in languages if l.code == tgt), None)
        if not self._src_lang or not self._tgt_lang:
            raise RuntimeError(f"argostranslate missing language pack for {src}->{tgt}")
        self._translator = self._src_lang.get_translation(self._tgt_lang)

    def translate_batch(self, texts: List[str], src: str, tgt: str) -> List[str]:
        return [self._translator.translate(text) for text in texts]
