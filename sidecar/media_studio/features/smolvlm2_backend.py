"""Real SmolVLM2-2.2B video-LLM backend (LAZY-imported only — heavy stack).

Imported ONLY inside ``smolvlm2._default_backend_factory`` at runtime — never at
package import, never by the tests (which inject a fake
:class:`~media_studio.features.smolvlm2.SmolVlmBackend`). It is therefore the one
place allowed to import ``transformers`` / ``torch``, and those imports live
inside the methods so even importing THIS module stays light.

The pinned model is ``HuggingFaceTB/SmolVLM2-2.2B-Instruct`` (Apache-2.0,
~5.2 GB BF16 runtime VRAM; PHASE8-SOTA-MANIFEST.md component #13). This is the
heaviest single model in the stack and is **6 GB-tight**: it CANNOT co-run with
any other GPU model. The orchestrator unloads everything else first; this backend
loads the model ALONE, scores the clips, and **unloads** it (``free()``) before
returning control. ``bitsandbytes`` int8/4-bit is BROKEN for SmolVLM2 (transformers
issue #41453) — the route here is **BF16 + sequential unload**.

Coverage of this module is excluded (it requires the heavy native stack + real
model weights); the pure prompt-build / reply-parse / reorder logic it feeds is
covered exhaustively in ``test_smolvlm2.py``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ..util import get_logger
from .smolvlm2 import MODEL_ID

log = get_logger("media_studio.features.smolvlm2_backend")


class RealSmolVlmBackend:  # pragma: no cover - requires the heavy native stack
    """SmolVLM2-2.2B loaded ALONE in BF16; scores each clip then unloads.

    Constructed lazily per job (``settings`` selects the device). The model is
    loaded on first :meth:`rank_clips` so construction stays cheap and an import
    failure surfaces as the job's error. After scoring it is explicitly freed so
    the ~5.2 GB BF16 weights do not linger and block the next sequential model.
    """

    def __init__(self, settings: Mapping[str, Any] | None = None) -> None:
        self._settings = dict(settings or {})
        self._model: Any = None
        self._processor: Any = None

    def _device(self) -> str:
        try:
            import torch  # noqa: PLC0415 - heavy seam, runtime only

            return "cuda" if torch.cuda.is_available() else "cpu"
        except Exception:  # noqa: BLE001 - no torch -> CPU path (impractical, but honest)
            return "cpu"

    def _ensure_model(self) -> None:
        if self._model is not None:
            return
        import torch  # noqa: PLC0415
        from transformers import AutoModelForImageTextToText, AutoProcessor  # noqa: PLC0415

        device = self._device()
        # BF16 + sequential unload — bnb int8/4-bit is broken (issue #41453).
        # `from_pretrained` returns a union basedpyright misreads as a bare
        # `_BaseModelWithGenerate` whose `.to()` overload rejects a device string;
        # binding through the `Any`-typed attribute first sidesteps that false call.
        model: Any = AutoModelForImageTextToText.from_pretrained(MODEL_ID, torch_dtype=torch.bfloat16)
        self._model = model.to(device).eval()
        self._processor = AutoProcessor.from_pretrained(MODEL_ID)
        log.info("smolvlm2 ready on %s (bf16, runs alone)", device)

    def _score_one(self, frames: Any, prompt: str) -> float:
        """Score a single clip's frame stack against the prompt (0..1)."""
        import re  # noqa: PLC0415

        import torch  # noqa: PLC0415

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "video", "video": frames},
                    {
                        "type": "text",
                        "text": (f"{prompt}\nRate THIS clip's engagement from 0 to 100. Reply with just the number."),
                    },
                ],
            }
        ]
        inputs = self._processor.apply_chat_template(
            messages,
            add_generation_prompt=True,
            tokenize=True,
            return_dict=True,
            return_tensors="pt",
        ).to(self._device())
        with torch.no_grad():
            generated = self._model.generate(**inputs, max_new_tokens=8, do_sample=False)
        reply = self._processor.batch_decode(generated, skip_special_tokens=True)[0]
        match = re.search(r"\d{1,3}", reply)
        value = float(match.group(0)) if match else 0.0
        return max(0.0, min(1.0, value / 100.0))

    def rank_clips(self, frames_per_clip: Sequence[Any], prompt: str) -> list[float]:
        """Score each clip (a frame stack) for the prompt — higher = more relevant."""
        self._ensure_model()
        try:
            return [self._score_one(frames, prompt) for frames in frames_per_clip]
        finally:
            self._free()

    def _free(self) -> None:
        """Unload the model so the next sequential stage gets the VRAM back."""
        self._model = None
        self._processor = None
        try:
            import torch  # noqa: PLC0415

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:  # noqa: BLE001 - best-effort cleanup, never fatal
            log.debug("smolvlm2 cuda cache clear skipped", exc_info=True)


__all__ = ["RealSmolVlmBackend"]
