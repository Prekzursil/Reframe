from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List


class Translator(ABC):
    @abstractmethod
    def translate_batch(self, texts: List[str], src: str, tgt: str) -> List[str]:
        """Translate a batch of strings from src to tgt."""
        raise NotImplementedError


class NoOpTranslator(Translator):
    """Local fallback translator that returns the input unchanged."""

    def translate_batch(self, texts: List[str], src: str, tgt: str) -> List[str]:  # pragma: no cover - trivial
        return texts
