"""``ocrExtractList`` engine — read on-screen list/Q&A text (WU-ocr, DESIGN §2.2/§3 #1).

The Director's first toolbox step that READS pixels: given a span of frames it
returns ``{text:[...], poster}`` — the ordered, de-duplicated on-screen text plus
the index of the richest frame (the natural poster). SmolVLM2 (``smolvlm2.py``)
only *reorders* candidates; it does NOT extract text, so this is a NEW engine
built over the **registered-but-unbuilt** RapidOCR asset
(``manifest.RAPIDOCR_ASSET_NAME``) and routed through the **existing** per-data-type
FRAME-consent vision gate (``models.consent``) — NO new AI path, NO new RPC (it
runs as the ``ocrExtractList`` op inside ``director.apply``, WU-apply).

Design follows the canonical Phase-8 seam pattern (mirrors ``smolvlm2.py``):

* **Pure half** (fully covered, no heavy import): :func:`order_boxes` turns a
  frame's OCR boxes into a top-to-bottom / left-to-right reading order;
  :func:`dedup_lines` collapses repeats across frames preserving first-seen order;
  :func:`extract_list` orchestrates them over an injected backend and picks the
  poster — all deterministic, testable with plain dicts.
* **Heavy half behind a Protocol seam** (:class:`OcrBackend`): the real
  RapidOCR/onnxruntime engine is built lazily by :func:`_default_backend_factory`
  (which imports the sibling heavy stack *inside* the function — coverage-excluded
  and version-agnostic: it loads whatever the manifest slot resolves, never a
  hardcoded PP-OCR version — DESIGN §9 F7). Tests inject a FAKE backend returning
  canned boxes, so no model, no weights, no network, no image decode.
* **Per-data-type FRAME consent (RAIL, DESIGN §6):** :func:`resolve_ocr_backend`
  picks the CLOUD vision backend ONLY when at least one vision provider has FRAME
  consent explicitly granted (``consent.perProvider[p].frames is True``); otherwise
  it returns the LOCAL backend, so a non-consented run NEVER reaches a cloud
  vision provider (the frame egress gate is evaluated FIRST, before any frame is
  sampled or encoded — a 429 failover can never reach a non-consented provider).
* **Typed failure**: any backend error is wrapped in :class:`OcrError`; blank /
  empty frames degrade to an empty list with ``poster=None`` — never a raise.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from ..util import get_logger

log = get_logger("media_studio.features.ocr_list")

# --------------------------------------------------------------------------- #
# pinned asset (manifest.RAPIDOCR_ASSET_NAME) — VERSION-AGNOSTIC. The engine
# references the manifest SLOT by name; it never encodes a PP-OCR version, so the
# DESIGN §9 F7 URL/label discrepancy (v4 file vs v5 label) cannot leak here.
# --------------------------------------------------------------------------- #
#: the on-demand asset name (registered in assets/manifest.py:_register_phase8_optional).
ASSET_NAME = "rapidocr-onnx"


# --------------------------------------------------------------------------- #
# public result types
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class OcrResult:
    """The ``ocrExtractList`` output: ordered text + the poster frame index.

    ``text`` is the de-duplicated, reading-ordered on-screen text across the
    sampled frames. ``poster`` is the index of the frame that produced the most
    text lines (the natural thumbnail), or ``None`` when no frame yielded any
    text (a blank span).
    """

    text: list[str]
    poster: int | None


class OcrError(RuntimeError):
    """Typed error raised when the OCR backend fails (test-strategy (d)).

    The engine wraps ANY backend exception in this so a caller catches a single
    typed failure rather than the underlying onnxruntime/native error. Carries no
    secret (frame pixels never appear in the message).
    """


# --------------------------------------------------------------------------- #
# the heavy backend seam (RapidOCR) — never imported at module load
# --------------------------------------------------------------------------- #
class OcrBackend(Protocol):
    """The slice of the OCR engine the pure extractor needs.

    A real impl is built lazily by :func:`_default_backend_factory` (never at
    import). Tests inject a FAKE whose :meth:`read_text` returns a canned list of
    boxes — no model, no weights, no onnxruntime, no image decode. Each box is a
    mapping with at least ``text`` and the ``top``/``left`` anchor used to order
    the line within the frame.
    """

    def read_text(self, frame: Any) -> list[dict[str, Any]]:
        """OCR one frame into a list of ``{text, top, left}`` boxes."""
        ...  # pragma: no cover - Protocol stub


#: Factory seam: ``settings -> OcrBackend`` (default = lazy real impl).
BackendFactory = Callable[[Mapping[str, Any]], OcrBackend]


# --------------------------------------------------------------------------- #
# pure: box ordering + cross-frame dedup + the engine (fully covered)
# --------------------------------------------------------------------------- #
def order_boxes(boxes: Sequence[Mapping[str, Any]]) -> list[str]:
    """Return a frame's box texts in reading order (top-to-bottom, then left).

    Blank / whitespace-only texts are dropped. Ordering is a stable sort on
    ``(top, left)`` so two boxes on the same line read left-to-right; missing
    anchors default to ``0.0``. PURE — no model, no mutation of the input.
    """
    rows = [
        (float(b.get("top", 0.0) or 0.0), float(b.get("left", 0.0) or 0.0), str(b.get("text") or "").strip())
        for b in boxes
    ]
    rows.sort(key=lambda r: (r[0], r[1]))
    return [text for _top, _left, text in rows if text]


def dedup_lines(lines: Sequence[str]) -> list[str]:
    """Collapse repeated lines across frames, preserving first-seen order.

    Each line is stripped; blanks are dropped; the first occurrence of each
    distinct line is kept in order (a scrolling list shows the same row in
    consecutive frames, so cross-frame dedup yields the logical list). PURE.
    """
    out: list[str] = []
    seen: set[str] = set()
    for line in lines:
        text = line.strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def extract_list(frames: Sequence[Any], *, backend: OcrBackend) -> OcrResult:
    """Read on-screen list/Q&A text from ``frames`` -> :class:`OcrResult`.

    For each frame, the injected ``backend`` OCRs it into boxes; the boxes are put
    in reading order (:func:`order_boxes`) and the per-frame line counts drive the
    poster choice (the richest frame, first-wins on ties). The flattened lines are
    de-duplicated across frames (:func:`dedup_lines`). An empty / blank span yields
    ``text=[]`` and ``poster=None`` (no raise). ANY backend failure is wrapped in
    :class:`OcrError`. PURE orchestration — the only impurity is the injected seam.
    """
    all_lines: list[str] = []
    best_count = 0
    poster: int | None = None
    try:
        for index, frame in enumerate(frames):
            lines = order_boxes(backend.read_text(frame))
            if lines:
                all_lines.extend(lines)
                if len(lines) > best_count:
                    best_count = len(lines)
                    poster = index
    except Exception as exc:  # noqa: BLE001 - any backend failure -> typed OcrError
        log.warning("ocrExtractList backend failed", exc_info=True)
        raise OcrError("OCR backend failed during extract_list") from exc
    return OcrResult(text=dedup_lines(all_lines), poster=poster)


# --------------------------------------------------------------------------- #
# per-data-type FRAME consent gate (DESIGN §6) — cloud ONLY when granted
# --------------------------------------------------------------------------- #
def _any_frame_consented_vision(settings: Mapping[str, Any]) -> bool:
    """True iff at least one vision-capable provider has FRAME consent granted.

    Mirrors ``handlers._frame_consented_vision_settings``: scans ``providers`` and
    returns ``True`` only when some entry's FRAME consent
    (``consent.perProvider[<provider>].frames``) is explicitly ``True`` (default-
    deny). When ``False``, the cloud OCR path is NEVER taken — no frame is prepared
    for egress to a non-consented provider. PURE (reads booleans only).
    """
    from ..models import consent as _consent  # noqa: PLC0415 - import-light pure gate

    providers = settings.get("providers")
    if not isinstance(providers, list):
        return False
    return any(
        isinstance(p, dict) and _consent.frame_consent_granted(settings, str(p.get("provider") or p.get("id") or ""))
        for p in providers
    )


def resolve_ocr_backend(
    settings: Mapping[str, Any],
    *,
    local_factory: BackendFactory | None = None,
    cloud_factory: BackendFactory | None = None,
) -> OcrBackend:
    """Pick the OCR backend honoring the FRAME-consent gate (DESIGN §6).

    The frame-egress consent gate is the FIRST decision: the CLOUD vision backend
    is constructed ONLY when a ``cloud_factory`` is supplied AND at least one
    vision provider has FRAME consent granted; otherwise the LOCAL backend is
    returned, so a non-consented run NEVER constructs — let alone calls — a cloud
    vision provider (acceptance (b): the cloud transport is never reached). The
    local factory defaults to the lazy real RapidOCR seam.
    """
    local = local_factory or _default_backend_factory
    if cloud_factory is not None and _any_frame_consented_vision(settings):
        return cloud_factory(settings)
    return local(settings)


# --------------------------------------------------------------------------- #
# default heavy seam (lazy real impl; tests inject fakes)
# --------------------------------------------------------------------------- #
def _default_backend_factory(
    settings: Mapping[str, Any],
) -> OcrBackend:  # pragma: no cover - prod seam (imports the heavy native OCR stack)
    """Build the real RapidOCR backend (LAZY import inside the function).

    ``rapidocr`` / ``onnxruntime`` are imported INSIDE the function so importing
    this module never drags in the native OCR stack (mirrors
    ``smolvlm2._default_backend_factory``). The model path resolves from the
    manifest SLOT (:data:`ASSET_NAME`) — VERSION-AGNOSTIC, never a hardcoded
    PP-OCR version (DESIGN §9 F7). Tests inject a fake, so this body is runtime-only
    and coverage-excluded.
    """
    from .ocr_list_backend import RealOcrBackend  # noqa: PLC0415 - heavy seam

    return RealOcrBackend(settings)


__all__ = [
    "ASSET_NAME",
    "BackendFactory",
    "OcrBackend",
    "OcrError",
    "OcrResult",
    "dedup_lines",
    "extract_list",
    "order_boxes",
    "resolve_ocr_backend",
]
