"""Tier-2 SmolVLM2-2.2B multimodal re-rank — OPT-IN, off by default (WU8).

The final, *optional* stage of the Phase-8 selection pipeline: a small on-device
video-LLM (``HuggingFaceTB/SmolVLM2-2.2B-Instruct``, Apache-2.0 — commercial OK;
PHASE8-SOTA-MANIFEST.md component #13) that **reorders only the top-K candidates**
the cheaper Tier-0/Tier-1 stages already ranked. It is the heaviest single model
in the stack (~5.2 GB BF16 runtime VRAM) and is **6 GB-tight**: it CANNOT co-run
with any other GPU model, so the orchestrator unloads everything else first, this
module loads it ALONE, infers, and unloads. ``bitsandbytes`` int8/4-bit is BROKEN
for SmolVLM2 under transformers (issue #41453) — the sub-6 GB route is **BF16 +
sequential unload** (a GGUF/llama.cpp provider is a future note, NOT used here).

It is wired into the unified scorer as the ``vlm_reranker`` seam (design-spec
``scorer.VlmReranker`` Protocol: ``rerank_top_k(cands, *, top_k) -> list``).
``tier < 2`` or a ``None`` seam skips it entirely, so the default pipeline never
loads it.

Design follows the canonical Phase-8 seam pattern (see ``vlm_backbone`` /
``scene_transnet`` / ``ranker``):

* **Pure half** (fully covered, no heavy import): :func:`build_rerank_prompt`
  renders the candidate set into a numbered instruction; :func:`parse_rerank_order`
  parses the model's reply into a 0-based index permutation (defensively — a
  malformed / partial reply degrades to the identity order, never raises);
  :func:`reorder_by_indices` applies a permutation to the candidate list.
* **Heavy half behind a Protocol seam** (:class:`SmolVlmBackend`): the real
  transformers/torch SmolVLM2 is built lazily by :func:`_default_backend_factory`
  (which imports the sibling ``smolvlm2_backend.py`` *inside* the function — that
  module is the only place allowed to import ``transformers`` / ``torch``, and is
  coverage-excluded). Tests inject a FAKE backend returning canned per-clip
  scores, so no model, no weights, no network is ever touched.
* **Graceful no-op**: an empty candidate set, a ``top_k`` of 0/negative, a backend
  that returns the wrong score count, or any backend failure all leave the input
  order unchanged — the re-rank can only ever *improve* the order, never break it.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol

from ..util import clamp, get_logger

log = get_logger("media_studio.features.smolvlm2")

# --------------------------------------------------------------------------- #
# pinned model (PHASE8-SOTA-MANIFEST.md component #13 — SmolVLM2-2.2B-Instruct)
# --------------------------------------------------------------------------- #
#: the on-demand asset name (Wave-2 registers the manifest entry).
ASSET_NAME = "smolvlm2-2.2b"
#: HF model id of the video-LLM (rev 482adb5; transformers ==4.49.0).
MODEL_ID = "HuggingFaceTB/SmolVLM2-2.2B-Instruct"
#: how many top candidates the video-LLM re-ranks by default (settings override).
TOP_K_DEFAULT = 10
#: resident VRAM at bf16 video inference (manifest VRAM table) — diagnostics only.
SMOLVLM_VRAM_MB = 5200
#: number of frames sampled per clip and handed to the backend (kept small for the
#: 6 GB budget — the backend down-samples each clip to this many evenly-spaced
#: frames before the video-LLM forward pass).
FRAMES_PER_CLIP = 8

#: the candidate field the re-rank score is stamped onto (parallel to ranker's).
SCORE_FIELD = "vlmScore"


# --------------------------------------------------------------------------- #
# the VlmReranker contract (design-spec scorer.VlmReranker) — what select_unified
# step 6 calls. Declared here so the module is self-describing; the scorer's own
# Protocol is structurally identical (duck-typed), so this class satisfies it.
# --------------------------------------------------------------------------- #
class VlmReranker(Protocol):
    """The Tier-2 re-rank seam the unified scorer consumes.

    ``select_unified`` step 6 calls ``rerank_top_k(cands, top_k=...)`` only when
    ``tier >= 2`` AND a reranker is injected; otherwise the step is skipped, so
    the default pipeline never loads the video-LLM.
    """

    def rerank_top_k(self, cands: Sequence[Mapping[str, Any]], *, top_k: int) -> list[dict[str, Any]]:
        """Reorder the top ``top_k`` candidates; the tail is left untouched."""
        ...  # pragma: no cover - Protocol stub


# --------------------------------------------------------------------------- #
# the heavy backend seam (SmolVLM2) — never imported at module load
# --------------------------------------------------------------------------- #
class SmolVlmBackend(Protocol):
    """The slice of SmolVLM2 the pure re-ranker needs.

    A real impl is built lazily by :func:`_default_backend_factory` (never at
    import). Tests inject a FAKE whose :meth:`rank_clips` returns a canned list
    of per-clip relevance scores — no model, no weights, no torch/transformers.
    The backend owns the load -> infer -> unload lifecycle (it runs ALONE).
    """

    def rank_clips(self, frames_per_clip: Sequence[Any], prompt: str) -> list[float]:
        """Score each clip (a frame stack) for the prompt — higher = more relevant."""
        ...  # pragma: no cover - Protocol stub


#: Factory seam: ``settings -> SmolVlmBackend`` (default = lazy real impl).
BackendFactory = Callable[[Mapping[str, Any]], SmolVlmBackend]
#: path, [(start, end), ...] -> per-clip frame stacks. cv2 lives inside the
#: default loader; tests inject synthetic stacks so cv2 is never imported.
ClipFrameLoader = Callable[[str, Sequence[tuple[float, float]]], "list[Any]"]
#: are the SmolVLM2 weights installed? (drives the offline / opt-in degrade).
ModelsPresent = Callable[[Mapping[str, Any]], bool]


# --------------------------------------------------------------------------- #
# pure: prompt build + reply parse + reorder (fully covered with plain strings)
# --------------------------------------------------------------------------- #
def _clip_label(candidate: Mapping[str, Any], index: int) -> str:
    """One numbered prompt line describing a candidate clip.

    Uses the candidate's ``hook`` (falling back to ``why``, then a generic
    label) so the video-LLM has a textual anchor alongside the sampled frames.
    The leading ``[i]`` index is what the model echoes back in its ranking.
    """
    hook = str(candidate.get("hook") or "").strip()
    why = str(candidate.get("why") or "").strip()
    text = hook or why or "(clip)"
    return f"[{index}] {text}"


def build_rerank_prompt(cands: Sequence[Mapping[str, Any]], *, instruction: str | None = None) -> str:
    """Render the candidate set into a numbered re-rank instruction.

    The prompt lists each clip as ``[i] <hook>`` (0-based) and asks the
    video-LLM to return the indices ordered best-first. The exact wording is a
    constant so tests can assert it; ``instruction`` overrides the lead-in for
    callers who want a different framing (e.g. a topical prompt). An empty
    candidate set yields just the instruction (the runner never calls the model
    in that case, but the helper stays total).
    """
    lead = (instruction or "").strip() or (
        "You are ranking short video clips by how engaging and share-worthy they are. "
        "Below are the candidate clips with their hooks. Return the clip indices ordered "
        "from BEST to worst, most engaging first, as a comma-separated list (e.g. 2,0,1)."
    )
    lines = [_clip_label(c, i) for i, c in enumerate(cands)]
    return lead + "\n" + "\n".join(lines) if lines else lead


def parse_rerank_order(text: str, n: int) -> list[int]:
    """Parse the model's reply into a full 0-based permutation of ``0..n-1``.

    Walks the reply left-to-right, picking out integer tokens; the first
    occurrence of each in-range, not-yet-seen index is kept in order. Any index
    the model omitted (or that was out of range / duplicated) is appended in
    ascending order at the end, so the result is ALWAYS a complete permutation
    of ``range(n)`` (the n-mismatch guard). A reply with no parseable indices
    therefore degrades to the identity order ``[0, 1, ..., n-1]`` — the re-rank
    becomes a no-op rather than dropping or duplicating a clip. ``n <= 0`` -> ``[]``.
    """
    if n <= 0:
        return []
    order: list[int] = []
    seen: set[int] = set()
    token = ""
    for ch in f"{text} ":  # trailing space flushes the last token
        if ch.isdigit():
            token += ch
            continue
        if token:
            idx = int(token)
            token = ""
            if 0 <= idx < n and idx not in seen:
                order.append(idx)
                seen.add(idx)
    order.extend(i for i in range(n) if i not in seen)
    return order


def reorder_by_indices(
    cands: Sequence[Mapping[str, Any]],
    order: Sequence[int],
    *,
    scores: Sequence[float] | None = None,
) -> list[dict[str, Any]]:
    """Apply an index permutation to ``cands``, returning immutable copies.

    ``order`` is a permutation of ``range(len(cands))`` (as produced by
    :func:`parse_rerank_order`). Each returned candidate is a fresh copy (inputs
    are never mutated); when ``scores`` is given (aligned to the ORIGINAL index)
    each copy carries its :data:`SCORE_FIELD`. Indices out of range are skipped
    defensively so a hand-built ``order`` can never raise.
    """
    out: list[dict[str, Any]] = []
    for idx in order:
        if not 0 <= idx < len(cands):
            continue
        copy = dict(cands[idx])
        if scores is not None and idx < len(scores):
            copy[SCORE_FIELD] = clamp(float(scores[idx]), 0.0, 1.0)
        out.append(copy)
    return out


def _order_from_scores(scores: Sequence[float]) -> list[int]:
    """Stable best-first index order from a per-clip score list (ties keep input)."""
    return [i for i, _s in sorted(enumerate(scores), key=lambda iv: (-float(iv[1]), iv[0]))]


def _scores_from_order(order: Sequence[int], n: int) -> list[float]:
    """Turn a best-first index ``order`` (length ``n``) into per-clip scores in [0,1].

    The inverse of :func:`_order_from_scores`: the clip ranked first gets the
    highest score, the last the lowest, so feeding the result back through the
    re-ranker reproduces ``order``. ``order`` is a full permutation of
    ``range(n)`` (as :func:`parse_rerank_order` guarantees). With one clip the
    single score is ``1.0``; ``n <= 0`` -> ``[]``.
    """
    if n <= 0:
        return []
    scores = [0.0] * n
    last = max(1, n - 1)
    for position, idx in enumerate(order):
        if 0 <= idx < n:
            # rank 0 -> 1.0, rank n-1 -> 0.0 (descending by reply position).
            scores[idx] = (last - position) / last
    return scores


# --------------------------------------------------------------------------- #
# Cloud (multi-provider) Tier-2 backend (WU-vision) — offloads the re-rank to a
# vision-capable rotation pool. The pool arrives via a CLOSURE the handler builds
# (the ``BackendFactory`` signature stays ``settings -> SmolVlmBackend``), so this
# class satisfies the SAME :class:`SmolVlmBackend` Protocol as the local model.
# --------------------------------------------------------------------------- #
#: A frame -> base64 string encoder seam. The default (PNG via cv2) is runtime-only
#: and coverage-excluded; tests inject a trivial encoder so no native image lib is
#: imported under the gate.
FrameEncoder = Callable[[Any], str]
#: Default vision sampling cap (kept small for the free-tier per-request limits).
VISION_MAX_TOKENS_DEFAULT = 64


def _default_frame_encoder(frame: Any) -> str:  # pragma: no cover - prod seam (PNG-encodes a numpy frame with cv2)
    """Encode one RGB frame array to a base64 PNG string (LAZY native import).

    ``cv2`` / ``base64`` are imported INSIDE the function so importing this module
    never drags in OpenCV; tests inject a fake encoder, so this body is runtime-only
    and coverage-excluded (mirrors :func:`_default_clip_frame_loader`).
    """
    import base64  # noqa: PLC0415

    import cv2  # noqa: PLC0415 - job-time native

    bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
    ok, buf = cv2.imencode(".png", bgr)
    if not ok:
        raise RuntimeError("frame PNG encode failed")
    return base64.b64encode(buf.tobytes()).decode("ascii")


class CloudVlmBackend:
    """A :class:`SmolVlmBackend` that scores clips via a vision rotation pool.

    Implements ``rank_clips(frames_per_clip, prompt) -> list[float]`` by
    base64-encoding the sampled frame stacks into an OpenAI-style multimodal
    message and sending it through the injected ``pool`` filtered to
    ``capability="vision"`` (so only vision-capable providers are tried, and the
    pool rotates across them on a 429). The model's reply is parsed into a 0-based
    order (the pure :func:`parse_rerank_order`) and turned back into per-clip
    scores, so the surrounding :class:`SmolVlmReranker` reorders identically to
    the local path — and its n-mismatch / failure guards still degrade cleanly.

    The pool arrives via a CLOSURE the handler builds (the ``BackendFactory``
    signature is UNCHANGED: ``settings -> SmolVlmBackend``). This backend never
    swallows a pool failure — that is the reranker's job (so a cloud outage leaves
    the input order unchanged), keeping a single degrade point.
    """

    def __init__(
        self,
        *,
        pool: Any,
        settings: Mapping[str, Any] | None = None,
        frame_encoder: FrameEncoder | None = None,
        capability: str = "vision",
    ) -> None:
        self._pool = pool
        self._settings = dict(settings or {})
        self._encode = frame_encoder or _default_frame_encoder
        self._capability = capability

    def _image_part(self, frame: Any) -> dict[str, Any]:
        """One OpenAI ``image_url`` content part for a base64-encoded frame."""
        return {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{self._encode(frame)}"}}

    def _build_message(self, frames_per_clip: Sequence[Any], prompt: str) -> list[dict[str, Any]]:
        """A single user message: the text prompt followed by every clip's frames.

        Each clip's frame stack is flattened into ``image_url`` parts; the model
        sees the prompt (numbered clip hooks) alongside the images so it can map a
        ranking back onto clip indices.
        """
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        for stack in frames_per_clip:
            for frame in stack:
                content.append(self._image_part(frame))
        return [{"role": "user", "content": content}]

    def rank_clips(self, frames_per_clip: Sequence[Any], prompt: str) -> list[float]:
        """Score each clip via the vision pool; higher = more relevant.

        Returns ``[]`` for no clips (the pool is never called). Otherwise builds
        the multimodal message, sends it through the vision-capable pool, parses
        the reply into a full index permutation, and converts that order into
        per-clip scores. A pool failure propagates (the reranker degrades to the
        input order); a malformed reply yields the identity order via the pure
        parser, which the reranker then treats as a no-op.
        """
        clips = list(frames_per_clip)
        n = len(clips)
        if n == 0:
            return []
        messages = self._build_message(clips, prompt)
        max_tokens = int(self._settings.get("visionMaxTokens") or VISION_MAX_TOKENS_DEFAULT)
        reply = self._pool.chat(messages, capability=self._capability, max_tokens=max_tokens)
        order = parse_rerank_order(str(reply), n)
        return _scores_from_order(order, n)


# --------------------------------------------------------------------------- #
# default heavy seams (lazy real impls; tests inject fakes)
# --------------------------------------------------------------------------- #
def _default_backend_factory(
    settings: Mapping[str, Any],
) -> SmolVlmBackend:  # pragma: no cover - prod seam (imports the heavy native stack)
    """Build the real SmolVLM2 backend (LAZY import inside the function)."""
    from .smolvlm2_backend import RealSmolVlmBackend  # noqa: PLC0415 - heavy seam

    return RealSmolVlmBackend(settings)


def _default_clip_frame_loader(
    media_path: str,
    spans: Sequence[tuple[float, float]],
) -> list[Any]:  # pragma: no cover - prod seam (decodes video frames with cv2)
    """Default per-clip frame sampler: ``FRAMES_PER_CLIP`` evenly-spaced frames.

    ``cv2`` is imported INSIDE the loader so importing this module never drags in
    OpenCV (mirrors ``vlm_backbone`` / ``scene_transnet``). Tests inject a fake
    loader returning synthetic frame stacks, so this body is runtime-only and
    coverage-excluded.
    """
    import cv2  # noqa: PLC0415 - job-time native (pre-imported by __main__)
    import numpy as np  # noqa: PLC0415

    cap = cv2.VideoCapture(media_path)
    stacks: list[Any] = []
    try:
        for start, end in spans:
            lo, hi = float(start), float(end)
            step = (hi - lo) / float(max(1, FRAMES_PER_CLIP))
            frames: list[Any] = []
            for k in range(FRAMES_PER_CLIP):
                cap.set(cv2.CAP_PROP_POS_MSEC, (lo + step * k) * 1000.0)
                ok, frame = cap.read()
                if ok and frame is not None:
                    frames.append(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            stacks.append(np.asarray(frames, dtype="uint8"))
    finally:
        cap.release()
    return stacks


def default_models_present(settings: Mapping[str, Any]) -> bool:
    """True when the SmolVLM2 weights are installed (no heavy import).

    Looks the asset up via the asset manager so an already-cached snapshot
    counts (that is what lets the model run offline once fetched). Any lookup
    failure (asset not yet registered, or the asset machinery missing) degrades
    to ``False`` — the re-rank is then skipped — and never raises.
    """
    try:
        from ..assets import manifest  # noqa: PLC0415 - lazy: avoids an import cycle
        from ..assets.manager import AssetManager  # noqa: PLC0415

        entry = manifest.get_asset(ASSET_NAME)
        if entry is None:
            return False
        mgr = AssetManager(settings_provider=lambda: dict(settings))
        return mgr.installed_path(entry) is not None
    except Exception:  # noqa: BLE001 - missing asset machinery -> skip the re-rank
        return False


# --------------------------------------------------------------------------- #
# the public re-ranker (implements the VlmReranker seam)
# --------------------------------------------------------------------------- #
class SmolVlmReranker:
    """Tier-2 video-LLM re-ranker (implements :class:`VlmReranker`).

    Constructed with the injectable seams (a backend factory, a clip-frame
    loader, a models-present probe). :meth:`rerank_top_k` slices the top ``top_k``
    candidates, samples each clip's frames, asks the SmolVLM2 backend to score
    them against a built prompt, reorders the top slice by those scores, and
    leaves the tail untouched. Every failure / degenerate input is a no-op (the
    input order is returned unchanged), so the re-rank can only improve order.

    The orchestrator guarantees this runs ALONE (all other GPU models unloaded);
    the backend owns the load -> infer -> unload lifecycle for the ~5.2 GB model.
    """

    def __init__(
        self,
        *,
        settings: Mapping[str, Any] | None = None,
        backend_factory: BackendFactory | None = None,
        clip_frame_loader: ClipFrameLoader | None = None,
        media_path: str | None = None,
        instruction: str | None = None,
    ) -> None:
        self._settings = dict(settings or {})
        self._factory = backend_factory or _default_backend_factory
        self._loader = clip_frame_loader or _default_clip_frame_loader
        self._media_path = media_path
        self._instruction = instruction

    def _spans(self, top: Sequence[Mapping[str, Any]]) -> list[tuple[float, float]]:
        """The ``(start, end)`` spans of the top slice (for the frame loader)."""
        return [(float(c.get("start", 0.0) or 0.0), float(c.get("end", 0.0) or 0.0)) for c in top]

    def rerank_top_k(
        self,
        cands: Sequence[Mapping[str, Any]],
        *,
        top_k: int = TOP_K_DEFAULT,
    ) -> list[dict[str, Any]]:
        """Reorder the top ``top_k`` candidates by the video-LLM; tail untouched.

        No-op (returns immutable copies in the input order) when there is nothing
        to reorder (empty input, ``top_k <= 1``, or only one candidate), when the
        backend cannot be built / raises, or when it returns the wrong number of
        scores (the n-mismatch guard). Otherwise the top slice is reordered
        best-first by the backend's per-clip scores and concatenated with the
        unchanged tail.
        """
        all_copies = [dict(c) for c in cands]
        k = min(int(top_k), len(all_copies))
        if k <= 1:
            return all_copies

        top = all_copies[:k]
        tail = all_copies[k:]
        prompt = build_rerank_prompt(top, instruction=self._instruction)
        try:
            frames = list(self._loader(self._media_path or "", self._spans(top)))
            backend = self._factory(self._settings)
            scores = list(backend.rank_clips(frames, prompt))
        except Exception:  # noqa: BLE001 - any backend/loader failure -> no-op re-rank
            log.warning("smolvlm2 re-rank failed; keeping input order", exc_info=True)
            return all_copies

        if len(scores) != k:
            log.info("smolvlm2 returned %d scores for %d clips; skipping re-rank", len(scores), k)
            return all_copies

        order = _order_from_scores(scores)
        reordered = reorder_by_indices(top, order, scores=scores)
        return reordered + tail


def build_reranker(
    *,
    settings: Mapping[str, Any] | None = None,
    media_path: str | None = None,
    backend_factory: BackendFactory | None = None,
    clip_frame_loader: ClipFrameLoader | None = None,
    models_present: ModelsPresent | None = None,
    instruction: str | None = None,
) -> SmolVlmReranker | None:
    """Build a :class:`SmolVlmReranker`, or ``None`` when the model is unavailable.

    The opt-in gate the orchestrator uses to decide whether to hand the unified
    scorer a ``vlm_reranker`` at all: returns ``None`` (re-rank skipped) when the
    SmolVLM2 weights are not installed AND we are offline (a download would need
    the network), so the heavy ~5.2 GB model is never loaded on a machine that
    cannot serve it. Otherwise returns a reranker wired with the given seams.
    """
    settings = dict(settings or {})
    present = models_present or default_models_present
    if not present(settings):
        from . import offline as _offline  # noqa: PLC0415 - lazy: keep import surface light

        if _offline.is_offline(settings):
            log.info("smolvlm2 weights unavailable offline; Tier-2 re-rank disabled")
            return None
    return SmolVlmReranker(
        settings=settings,
        backend_factory=backend_factory,
        clip_frame_loader=clip_frame_loader,
        media_path=media_path,
        instruction=instruction,
    )


# --------------------------------------------------------------------------- #
# asset registration (mirrors diarize / parakeet_asr / ctc_align)
# --------------------------------------------------------------------------- #
#: pinned SmolVLM2 revision (SOTA manifest #13; transformers ==4.49.0).
ASSET_REVISION = "482adb5"
ASSET_SIZE_MB = 4500


def register_smolvlm2_assets() -> None:
    """Register the SmolVLM2-2.2B video-LLM as an on-demand asset (idempotent).

    Apache-2.0 (commercial OK), ~4.5 GB on disk / ~5.2 GB bf16 resident — the
    Tier-2 re-ranker that runs ALONE (off by default). The asset name matches
    :data:`ASSET_NAME` (and ``system_advisor.ComponentSpec``'s ``smolvlm2`` lookup
    key) so :func:`default_models_present` detects an already-cached snapshot.
    Identical re-registration is a no-op (module re-import safe).
    """
    from ..assets import manifest  # noqa: PLC0415 - lazy: avoids an import cycle

    manifest.register_asset(
        manifest.AssetEntry(
            name=ASSET_NAME,
            kind="model",
            size_mb=ASSET_SIZE_MB,
            label="SmolVLM2-2.2B-Instruct (Tier-2 video-LLM, Apache-2.0)",
            installer="hf",
            hf_repo=MODEL_ID,
            hf_revision=ASSET_REVISION,
        )
    )


# Register the asset at import (mirrors diarize.register_diarize_assets()).
register_smolvlm2_assets()


__all__ = [
    "ASSET_NAME",
    "ASSET_REVISION",
    "ASSET_SIZE_MB",
    "FRAMES_PER_CLIP",
    "MODEL_ID",
    "SCORE_FIELD",
    "SMOLVLM_VRAM_MB",
    "TOP_K_DEFAULT",
    "VISION_MAX_TOKENS_DEFAULT",
    "BackendFactory",
    "ClipFrameLoader",
    "CloudVlmBackend",
    "FrameEncoder",
    "ModelsPresent",
    "SmolVlmBackend",
    "SmolVlmReranker",
    "VlmReranker",
    "build_rerank_prompt",
    "build_reranker",
    "default_models_present",
    "parse_rerank_order",
    "register_smolvlm2_assets",
    "reorder_by_indices",
]
