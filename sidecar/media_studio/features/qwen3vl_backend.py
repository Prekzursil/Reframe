"""Real Qwen3-VL-4B/8B video-LLM backend (LAZY-imported only — heavy stack).

The gem-hunt E.3 "backbone swap": an OPT-IN alternative to SmolVLM2 for the
Tier-2 re-rank seam. Imported ONLY inside
``smolvlm2._default_qwen3vl_backend_factory`` at runtime — never at package
import, never by the tests (which inject a fake
:class:`~media_studio.features.smolvlm2.SmolVlmBackend`). It is therefore the one
place allowed to import ``transformers`` / ``torch``, and those imports live
inside the methods so even importing THIS module stays light.

Model (chosen from settings by :func:`smolvlm2.resolve_backbone`):

* ``Qwen/Qwen3-VL-4B-Instruct`` (Apache-2.0, ~9 GB bf16 resident) — the cheaper
  "large quality jump" over SmolVLM2-2.2B (default when ``vlmBackbone=qwen3vl``);
* ``Qwen/Qwen3-VL-8B-Instruct`` (Apache-2.0, ~18 GB bf16 resident) — the
  higher-quality tier.

Qwen3-VL adds native temporal grounding (text ↔ timestamp alignment) and stronger
video understanding than SmolVLM2 — the reason it is the "cheapest large quality
jump" for the re-rank. Like SmolVLM2 it is loaded ALONE (the orchestrator unloads
every other GPU model first), scores each clip, and is **unloaded** (``_free``)
before returning control. It is HEAVIER than SmolVLM2, so it stays OPT-IN — a
6 GB-tight box keeps the SmolVLM2 default.

This backend satisfies the SAME :class:`~media_studio.features.smolvlm2.SmolVlmBackend`
Protocol (``rank_clips(frames_per_clip, prompt) -> list[float]``), so nothing
downstream changes when it is swapped in.

Coverage of this module is excluded (it requires the heavy native stack + real
model weights); the pure backbone-resolution / factory-selection logic it feeds
is covered exhaustively in ``test_qwen3vl_backbone_swap.py``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ..util import get_logger
from .smolvlm2 import (
    BACKBONE_QWEN3VL_8B,
    QWEN3VL_4B_MODEL_ID,
    QWEN3VL_4B_REVISION,
    QWEN3VL_8B_MODEL_ID,
    QWEN3VL_8B_REVISION,
    resolve_backbone,
)

log = get_logger("media_studio.features.qwen3vl_backend")


class RealQwen3VlBackend:  # pragma: no cover - requires the heavy native stack
    """Qwen3-VL (4B or 8B) loaded ALONE in BF16; scores each clip then unloads.

    Constructed lazily per job. The concrete model + pinned revision are chosen
    from ``settings`` (via :func:`smolvlm2.resolve_backbone`) at construction, but
    the weights load on first :meth:`rank_clips` so construction stays cheap and
    an import failure surfaces as the job's error. After scoring the model is
    explicitly freed so the multi-GB BF16 weights do not linger and block the next
    sequential model.
    """

    def __init__(self, settings: Mapping[str, Any] | None = None) -> None:
        self._settings = dict(settings or {})
        backbone = resolve_backbone(self._settings)
        if backbone == BACKBONE_QWEN3VL_8B:
            self._model_id = QWEN3VL_8B_MODEL_ID
            self._revision = QWEN3VL_8B_REVISION
        else:  # 4B is the default Qwen tier (also the bare "qwen3vl" alias)
            self._model_id = QWEN3VL_4B_MODEL_ID
            self._revision = QWEN3VL_4B_REVISION
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
        from transformers import AutoProcessor  # noqa: PLC0415

        # Prefer the concrete Qwen3-VL class; fall back to the generic
        # image-text-to-text auto-class on older/newer transformers layouts.
        try:
            from transformers import Qwen3VLForConditionalGeneration as _ModelCls  # noqa: PLC0415
        except Exception:  # noqa: BLE001 - class name varies across transformers versions
            from transformers import AutoModelForImageTextToText as _ModelCls  # noqa: PLC0415

        device = self._device()
        # BF16 + sequential unload (same route as SmolVLM2). `from_pretrained`
        # returns a union basedpyright misreads as a bare model whose `.to()`
        # overload rejects a device string; binding through an `Any` attribute
        # first sidesteps that false call.
        model: Any = _ModelCls.from_pretrained(self._model_id, revision=self._revision, torch_dtype=torch.bfloat16)
        self._model = model.to(device).eval()
        self._processor = AutoProcessor.from_pretrained(self._model_id, revision=self._revision)
        log.info("qwen3-vl ready on %s (bf16, runs alone): %s", device, self._model_id)

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
            log.debug("qwen3-vl cuda cache clear skipped", exc_info=True)


__all__ = ["RealQwen3VlBackend"]
