"""Pure helpers for the Director RPC spine (DESIGN §7.1, WU-plan-rpc).

The ``director.plan`` / ``director.previewCost`` / ``director.apply`` RPC methods
themselves live in ``handlers.py`` (registered ONLY in ``register_all`` — the one
composition root, DESIGN RAIL "no parallel AI path"). This module holds the
*pure*, fully-testable transforms those handlers compose, so the handler bodies
stay thin wiring over the shipped substrate (``_run_ai_job`` / ``ai.planJob`` /
``apply_plan``):

  * :func:`build_understanding` — turn a project manifest + probed duration into
    the validator's :class:`edit_validate.Understanding` (machine-known facts the
    plan is checked against) AND the media-derived ``understanding`` mapping the
    planner prompt fences as UNTRUSTED DATA (DESIGN §5 #1). Transcript / on-screen
    text live ONLY inside that mapping — never as instructions.
  * :func:`source_hash` — a deterministic content anchor (path + duration) so a
    plan correlates to the exact source it was planned against (the storyboard /
    cache anchor; mirrors ``edit_plan.to_json`` determinism).
  * :func:`new_plan_id` — a stable, unique plan id.

PURITY: stdlib + the pure ``edit_validate`` model only — NO ``Provider`` /
transport / heavy-ML import. The LLM call is the handler via ``_run_ai_job``.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from media_studio.features.edit_validate import Understanding

#: The manifest key holding the user-visible caption/overlay tracks an op may
#: target (``caption``/``overlayText``/... require an existing track).
_TRACKS_KEY = "tracks"
#: The manifest key holding the persisted transcript (optional; only after ASR).
_TRANSCRIPT_KEY = "transcript"


def new_plan_id() -> str:
    """Return a unique plan id (``plan-<hex>``) for a fresh ``director.plan``."""
    return f"plan-{uuid.uuid4().hex}"


def source_hash(video_path: str, duration_ms: int) -> str:
    """Return a deterministic source anchor for ``(video_path, duration_ms)``.

    A short SHA-256 hex digest over the path + duration so the same source always
    hashes identically (the plan-to-source correlation the storyboard relies on)
    and a different source / re-probe yields a different anchor. PURE — no I/O.
    """
    raw = f"{video_path}\x00{duration_ms}".encode()
    return hashlib.sha256(raw).hexdigest()[:16]


def _track_ids(project_data: Mapping[str, Any]) -> tuple[str, ...]:
    """Collect the ids of the project's existing tracks (for unknown-track gating)."""
    tracks = project_data.get(_TRACKS_KEY)
    if not isinstance(tracks, Sequence) or isinstance(tracks, (str, bytes)):
        return ()
    ids: list[str] = []
    for track in tracks:
        if isinstance(track, Mapping):
            track_id = track.get("id")
            if isinstance(track_id, str):
                ids.append(track_id)
    return tuple(ids)


def build_understanding(
    project_data: Mapping[str, Any],
    *,
    duration_ms: int,
) -> tuple[Understanding, dict[str, Any]]:
    """Build the validator facts + the fenced media-derived understanding mapping.

    Returns a 2-tuple:

      * an :class:`edit_validate.Understanding` (clip duration + existing track
        ids) the pure ``validate_and_reject`` pass checks each op against;
      * the ``understanding`` mapping handed to ``build_edit_plan_messages`` and
        fenced as UNTRUSTED DATA (DESIGN §5 #1) — the transcript + the known
        tracks + the duration, so the planner sees the source WITHOUT ever
        treating it as instructions.

    PURE: derives everything from the manifest + the probed duration; no I/O.
    """
    track_ids = _track_ids(project_data)
    understanding = Understanding(clip_duration_ms=duration_ms, tracks=track_ids)
    transcript = project_data.get(_TRANSCRIPT_KEY)
    media: dict[str, Any] = {
        "durationMs": duration_ms,
        "tracks": list(track_ids),
    }
    if transcript is not None:
        media[_TRANSCRIPT_KEY] = transcript
    return understanding, media
