"""captions.cues — WORD-level caption cues for the live preview overlay (P4 C7).

The renderer's live HTML/CSS caption overlay (PLAN-P4 §5) needs the spoken words
on a timeline so it can show the active line (and karaoke-highlight the active
word) as the candidate plays. No existing RPC returns cues, so this is the
NET-NEW ``captions.cues`` method (PLAN-P4 §2 / C6 / C7).

It is built on data that ALREADY exists:

  * the transcript is persisted with WORD timing (``transcribe.py``
    ``word_timestamps=True`` -> ``Segment.words`` of ``{text, start, end}``);
  * ``handlers.Services._shortmaker_context(videoId)`` exposes that transcript
    (plus the source path / title) — the same loader the short-maker uses.

``captions.cues({videoId})`` -> ``{cues: Cue[]}`` emits WORD-level cues in
**source-absolute seconds** (the overlay re-bases them to the preview window by
subtracting ``window.start``, §5). WORD-level (not segment-level) is required so
the overlay can karaoke-highlight the active word (PLAN-P4 C7).

Cue shape is the frozen contract ``{index, start, end, text}`` (rpc.ts:38 /
caption.CueLike). This module is pure + import-light: it only flattens the
persisted transcript; the heavy context loader is injected, so tests drive it
with a fake loader and no library/whisper import. Mirrors the
``shorts.register`` wiring pattern (a feature module owning its own
``register()`` — PLAN-P4 C6).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .. import protocol
from ..protocol import ErrorCode, RpcContext, RpcError
from ..util import get_logger

log = get_logger("media_studio.cues")

# A Cue is the contract's ``{index:int, start:float, end:float, text:str}``
# (rpc.ts:38). Plain dicts on the wire (mirrors shortmaker.Cue).
Cue = dict[str, Any]
Transcript = dict[str, Any]

# load_context(video_id) -> {"path", "transcript", ...} (Services._shortmaker_context).
ContextLoader = Callable[[str], dict[str, Any]]


def _invalid(message: str) -> RpcError:
    return RpcError(message, ErrorCode.INVALID_PARAMS)


def _require_str(params: dict[str, Any], key: str) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value:
        raise _invalid(f"{key} (str) is required")
    return value


def word_cues(transcript: Transcript | None) -> list[Cue]:
    """Flatten a persisted transcript into WORD-level cues (source-absolute time).

    Pure + deterministic. For every segment's ``words`` (the ``word_timestamps``
    output, normalized to ``{text, start, end}``) emit a contract Cue
    ``{index, start, end, text}`` whose times stay in ORIGINAL-video seconds (the
    overlay re-bases per window, §5). A segment WITHOUT word timing falls back to
    a single segment-span cue so a word-less transcript still drives the overlay.

    Skips blank-text and non-positive-length spans (they could never display);
    indexes are renumbered 1..N over the kept cues.
    """
    cues: list[Cue] = []
    if not transcript:
        return cues
    for seg in transcript.get("segments", []) or []:
        words = (seg or {}).get("words") or []
        if words:
            spans = [(_num(w.get("start")), _num(w.get("end")), str(w.get("text", "") or "")) for w in words]
        else:
            spans = [
                (
                    _num((seg or {}).get("start")),
                    _num((seg or {}).get("end")),
                    str((seg or {}).get("text", "") or ""),
                )
            ]
        for start, end, text in spans:
            if start is None or end is None:
                continue  # un-timed word/segment: cannot place it on the timeline
            if end <= start:
                continue  # zero/negative length: would never display
            if not text.strip():
                continue
            cues.append({"index": len(cues) + 1, "start": start, "end": end, "text": text})
    return cues


def _num(value: Any) -> float | None:
    """Coerce ``value`` to a float, or ``None`` when it is not numeric."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class Cues:
    """Owns ``captions.cues`` over an injected context loader.

    The loader (``Services._shortmaker_context`` in production) returns the
    video's persisted transcript under ``"transcript"``; we flatten it to
    word-level cues. Injectable so tests pass a fake loader (no library/whisper).
    """

    def __init__(self, *, load_context: ContextLoader) -> None:
        self._load_context = load_context

    def cues(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``captions.cues({videoId})`` -> ``{cues: Cue[]}`` (§2 / C7).

        Direct-return: loads the video's context, flattens its persisted
        transcript to WORD-level cues (source-absolute seconds), and returns
        them. An unknown video / missing transcript yields ``{"cues": []}``
        (the overlay simply shows no captions) rather than raising.
        """
        video_id = _require_str(params, "videoId")
        try:
            context = self._load_context(video_id) or {}
        except Exception as exc:  # noqa: BLE001 - a load miss != a crashed RPC
            log.warning("captions.cues context load failed for %s: %s", video_id, exc)
            return {"cues": []}
        transcript = context.get("transcript")
        return {"cues": word_cues(transcript)}


def register(
    *,
    load_context: ContextLoader,
    register_fn: Callable[[str, Any], None] | None = None,
) -> Cues:
    """Create a :class:`Cues` and register ``captions.cues`` (PLAN-P4 C6).

    ``register_fn`` defaults to :func:`protocol.register` (duplicate names fail
    loudly at startup); tests inject a fake registrar. Returns the service so the
    caller can hold/inspect it. Mirrors ``shorts.register`` / ``feedback.register``.
    """
    service = Cues(load_context=load_context)
    reg = register_fn if register_fn is not None else protocol.register
    reg("captions.cues", service.cues)
    return service


__all__ = [
    "Cue",
    "Cues",
    "register",
    "word_cues",
]
