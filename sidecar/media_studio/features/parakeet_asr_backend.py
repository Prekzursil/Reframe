"""Real NeMo Parakeet-TDT-0.6b-v3 loader (LAZY-imported only).

Imported ONLY inside ``parakeet_asr._default_loader`` at run-time — never at
package import, never by the tests (which inject a fake
:class:`~media_studio.features.parakeet_asr.ParakeetLoader`). It is therefore
the one place allowed to import ``nemo_toolkit`` / ``torch`` and pull the model
weights, and those imports live inside the methods so even importing THIS module
stays light.

Coverage of the HEAVY halves is excluded (they require the native stack + real
model weights); the pure ASR plumbing they feed — chunking, merge, normalizers,
CPU fallback, the offline degrade — is covered exhaustively in
``test_parakeet_asr.py`` via an injected fake loader, and the pure
revision-resolution logic below is covered in ``test_runtime_revision_pin.py``.

WU-S5 (revision pinning). NeMo's ``ASRModel.from_pretrained(model_name=...)`` has
**no revision parameter at all** (checked against NVIDIA/NeMo v2.4.0
``nemo/core/classes/common.py``; its own docstring says *"Use restore_from() to
instantiate from a local .nemo file"*), so it resolves whatever the Hub currently
serves and can silently download 2.4 GB mid-job. A ``.nemo`` archive is unpacked
and deserialized at load time, so an upstream change is a code-execution vector.
This module therefore:

  1. resolves ``(repo, revision)`` from the ASSET REGISTRY — the same 40-hex
     commit ``assets.ensure`` snapshot-downloaded — via the shared
     :func:`~media_studio.features.diarize_backend.resolve_pinned_hf_source`;
  2. materializes that EXACT revision **local-only** (``local_files_only=True``),
     so a runtime load never reaches the network — fetching weights stays
     ``assets.ensure``'s job (pinned, progress-reported, user-initiated);
  3. restores the model from the single ``.nemo`` file inside that pinned
     snapshot with ``ASRModel.restore_from``, so NeMo never resolves a ref itself.

BEHAVIOUR CHANGE (deliberate, disclosed): with Parakeet selected but its asset not
installed, the load now fails closed with an actionable message instead of
silently downloading. Offline already degraded to the whisper fallback
(``parakeet_asr.transcribe_file``); online now surfaces "install the asset" rather
than an unpinned background download.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..util import get_logger
from .diarize_backend import UnpinnedModelRevisionError, resolve_pinned_hf_source
from .parakeet_asr import ASSET_NAME, DEFAULT_MODEL

log = get_logger("media_studio.features.parakeet_asr_backend")

#: A pinned HF snapshot materializer: ``(repo_id, revision, local_files_only) ->
#: local snapshot dir``. Injectable so the pinning logic is testable without
#: huggingface_hub, a network, or 2.4 GB of weights.
SnapshotFetch = Callable[..., str]

#: The NeMo checkpoint extension inside the pinned HF snapshot.
NEMO_SUFFIX = ".nemo"


def find_nemo_checkpoint(snapshot_dir: str) -> str:
    """The single ``*.nemo`` archive inside a pinned snapshot dir, or fail closed.

    ``ASRModel.restore_from`` needs a concrete ``.nemo`` path. The pinned
    ``nvidia/parakeet-tdt-0.6b-v3`` snapshot contains exactly one
    (``parakeet-tdt-0.6b-v3.nemo``, verified via the HF revision API at
    :data:`~media_studio.features.parakeet_asr.ASSET_REVISION`). Zero or several
    is refused rather than guessed: silently picking one would reintroduce exactly
    the "load whatever is there" ambiguity the pin exists to remove.
    """
    candidates = sorted(Path(snapshot_dir).glob(f"*{NEMO_SUFFIX}"))
    if not candidates:
        raise UnpinnedModelRevisionError(
            f"pinned snapshot {snapshot_dir!r} contains no {NEMO_SUFFIX} checkpoint; "
            f"re-run assets.ensure for {ASSET_NAME!r} to materialize the pinned revision"
        )
    if len(candidates) > 1:
        names = ", ".join(p.name for p in candidates)
        raise UnpinnedModelRevisionError(
            f"pinned snapshot {snapshot_dir!r} is ambiguous: {len(candidates)} {NEMO_SUFFIX} "
            f"checkpoints ({names}); refusing to guess which one to deserialize"
        )
    return str(candidates[0])


def _default_snapshot_fetch(  # pragma: no cover - prod seam (huggingface_hub + the real cache)
    *, repo_id: str, revision: str, local_files_only: bool
) -> str:
    """Resolve a pinned HF snapshot dir (lazy ``huggingface_hub`` import).

    Mirrors ``assets.manager._default_hf_fetch`` but adds ``local_files_only`` so a
    RUNTIME load can be confined to what ``assets.ensure`` already downloaded.
    """
    from huggingface_hub import snapshot_download  # noqa: PLC0415 - lazy seam

    return str(snapshot_download(repo_id=repo_id, revision=revision, local_files_only=local_files_only))


def resolve_pinned_checkpoint(
    *,
    model: str = DEFAULT_MODEL,
    snapshot_fetch: SnapshotFetch = _default_snapshot_fetch,
) -> str:
    """Local path of the ``.nemo`` checkpoint at the REGISTERED commit for ``model``.

    ``model`` is the repo the caller wants to load; it is checked against the
    registry entry, so a model the registry never pinned is refused instead of
    downloaded. The snapshot is materialized ``local_files_only=True`` — the load
    path never fetches from the network.
    """
    repo, revision = resolve_pinned_hf_source(ASSET_NAME, model)
    snapshot_dir = snapshot_fetch(repo_id=repo, revision=revision, local_files_only=True)
    return find_nemo_checkpoint(snapshot_dir)


class _RealParakeetModel:  # pragma: no cover - requires the heavy native stack
    """Adapts NeMo's ``EncDecRNNTBPEModel`` to the ``ParakeetModel`` Protocol.

    Wraps NeMo's ``transcribe`` output (a hypotheses list carrying
    word-level timestamps when ``timestamps=True``) into the segment-like shape
    the pure normalizers in ``parakeet_asr`` expect.
    """

    def __init__(self, model: Any) -> None:
        self._model = model

    def transcribe(self, audio: str, **kwargs: Any) -> Any:
        language = kwargs.get("language")
        # NeMo decodes the whole file; the chunking caller passes offset/duration
        # for bookkeeping but NeMo's CLI-level path transcribes per-file. A real
        # 6 GB build would pre-slice the audio to ``[offset, offset+duration)``
        # before calling this; here we forward the path + request timestamps.
        hyps = self._model.transcribe([audio], timestamps=True)
        hyp = hyps[0] if hyps else None
        segments = _hyp_to_segments(hyp)
        return {
            "segments": segments,
            "info": {"language": language or ""},
        }


def _hyp_to_segments(hyp: Any) -> list[dict[str, Any]]:  # pragma: no cover - heavy seam
    """Convert a NeMo hypothesis with word timestamps into segment dicts."""
    if hyp is None:
        return []
    timestamp = getattr(hyp, "timestamp", None) or {}
    seg_stamps = timestamp.get("segment") if isinstance(timestamp, dict) else None
    word_stamps = timestamp.get("word") if isinstance(timestamp, dict) else None
    words = [
        {"text": w.get("word", ""), "start": w.get("start", 0.0), "end": w.get("end", 0.0)} for w in (word_stamps or [])
    ]
    if seg_stamps:
        return [
            {
                "start": s.get("start", 0.0),
                "end": s.get("end", 0.0),
                "text": s.get("segment", ""),
                "words": [w for w in words if s.get("start", 0.0) <= w["start"] < s.get("end", 0.0)],
            }
            for s in seg_stamps
        ]
    text = getattr(hyp, "text", "") or ""
    end = words[-1]["end"] if words else 0.0
    return [{"start": 0.0, "end": end, "text": text, "words": words}]


class RealParakeetLoader:  # pragma: no cover - requires the heavy native stack
    """Default loader: lazily imports ``nemo_toolkit`` and builds a model.

    The import lives inside :meth:`load` (not at module scope) so importing this
    module never pulls in NeMo / its native deps. Models are cached per
    (model, device, compute_type) so a job that transcribes after a device
    fallback does not rebuild needlessly (mirrors ``FasterWhisperLoader``).

    WU-S5: ``load`` restores from the REGISTRY-PINNED local ``.nemo`` snapshot
    (:func:`resolve_pinned_checkpoint`) instead of calling the unpinnable
    ``ASRModel.from_pretrained``. ``snapshot_fetch`` is the injectable
    pinned-materializer seam (tests pass a fake; prod uses huggingface_hub).
    """

    def __init__(self, *, snapshot_fetch: SnapshotFetch = _default_snapshot_fetch) -> None:
        self._cache: dict[tuple[str, str, str], _RealParakeetModel] = {}
        self._snapshot_fetch = snapshot_fetch

    def load(self, model: str, device: str, compute_type: str) -> _RealParakeetModel:
        key = (model, device, compute_type)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        import torch  # noqa: PLC0415 - heavy seam, runtime only
        from nemo.collections.asr.models import ASRModel  # noqa: PLC0415  # pyright: ignore[reportMissingImports]

        # WU-S5: from_pretrained CANNOT be revision-pinned (no such parameter), so
        # restore the pinned local snapshot's .nemo directly — NeMo never resolves
        # a Hub ref, and nothing outside the registered commit is deserialized.
        checkpoint = resolve_pinned_checkpoint(model=model, snapshot_fetch=self._snapshot_fetch)
        asr = ASRModel.restore_from(restore_path=checkpoint)
        target = device if (device != "cuda" or torch.cuda.is_available()) else "cpu"
        asr = asr.to(target)
        asr.eval()
        built = _RealParakeetModel(asr)
        self._cache[key] = built
        log.info("parakeet ready on %s (%s) from pinned %s", target, compute_type, checkpoint)
        return built

    def release(self) -> None:
        """Drop cached models so the single-heavy-model budget is freed (§7)."""
        self._cache.clear()


__all__ = [
    "NEMO_SUFFIX",
    "RealParakeetLoader",
    "SnapshotFetch",
    # Re-exported so a caller can catch the pin refusal without reaching into
    # diarize_backend (WU-S5: the shared resolver lives there).
    "UnpinnedModelRevisionError",
    "find_nemo_checkpoint",
    "resolve_pinned_checkpoint",
]
