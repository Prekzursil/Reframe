"""Package-for-upload export — a ZIP bundle ready for manual posting.

Takes ONE produced short (the rendered ``<clip>.mp4`` + its sidecar metadata) and
bundles everything a creator needs to post by hand into a single ``.zip``:

  * the rendered short  (``short.mp4``)
  * a poster thumbnail  (``thumbnail.jpg`` — copied when present)
  * ``upload.json``     — a suggested title / description / tags + the source facts

The "suggested" copy is derived deterministically from the clip's own metadata
(the hook becomes the title, a short description is composed from the hook +
source title, tags are slugged from the hook words) so packaging needs NO model
call and is fully testable. A caller MAY pass an override ``suggestion`` (e.g. an
LLM-generated one) and it wins field-by-field.

Pure-ish: the only side effects are reading the input files and writing the zip.
Everything that shapes the bundle (the suggestion builder, the manifest, the file
list) is a pure function so tests assert the JSON + archive contents without a
model or network.

Public surface:
  - ``slugify_tags(text, *, max_tags)``         hook text -> tag list
  - ``build_suggestion(meta, *, override)``     metadata -> {title, description, tags}
  - ``build_manifest(meta, suggestion)``        the full ``upload.json`` payload
  - ``package(clip_path, out_path, *, meta, thumbnail_path, suggestion)`` -> {path, manifest}
"""

from __future__ import annotations

import json
import os
import re
import zipfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any

Meta = dict[str, Any]
Suggestion = dict[str, Any]

#: Arc-names inside the produced zip (frozen so consumers can rely on them).
ARC_VIDEO = "short.mp4"
ARC_THUMBNAIL = "thumbnail.jpg"
ARC_MANIFEST = "upload.json"

#: Defaults for the suggested copy when the clip metadata carries nothing usable.
DEFAULT_TITLE = "Untitled Short"
DEFAULT_DESCRIPTION = "Made with Media Studio."
MAX_TAGS = 12
MAX_TITLE_LEN = 100
MAX_DESCRIPTION_LEN = 500

# Common English stop-words dropped when slugging a hook into tags.
_STOP_WORDS = frozenset(
    {
        "the", "a", "an", "and", "or", "but", "if", "of", "to", "in", "on", "for",
        "with", "is", "are", "was", "were", "be", "this", "that", "it", "as", "at",
        "by", "from", "you", "your", "i", "me", "my", "we", "our", "they", "he",
        "she", "his", "her", "its",
    }
)


# --------------------------------------------------------------------------- #
# suggestion / manifest builders (pure)
# --------------------------------------------------------------------------- #
def slugify_tags(text: str, *, max_tags: int = MAX_TAGS) -> list[str]:
    """Derive lowercase hashtag-style tags from free text (no leading ``#``).

    Splits on non-word characters, lowercases, drops stop-words and very short
    tokens, and de-duplicates while preserving first-seen order. Returns at most
    ``max_tags`` tags. The result is a clean tag list a creator can paste.
    """
    seen: dict[str, None] = {}
    for raw in re.split(r"[^0-9A-Za-z]+", str(text or "")):
        token = raw.strip().lower()
        if len(token) < 3 or token in _STOP_WORDS:
            continue
        if token not in seen:
            seen[token] = None
        if len(seen) >= max_tags:
            break
    return list(seen.keys())


def _truncate(text: str, limit: int) -> str:
    """Trim ``text`` to ``limit`` chars on a word boundary where possible."""
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(cleaned) <= limit:
        return cleaned
    cut = cleaned[:limit].rstrip()
    space = cut.rfind(" ")
    if space > limit * 0.6:  # only word-trim when it doesn't gut the string
        cut = cut[:space].rstrip()
    return cut


def build_suggestion(meta: Meta, *, override: Suggestion | None = None) -> Suggestion:
    """Build the suggested ``{title, description, tags}`` from clip ``meta``.

    Derivation (deterministic, no model):
      * ``title``       = the hook (or sourceTitle, or the default), trimmed.
      * ``description`` = the hook + a "From <sourceTitle>" line when present.
      * ``tags``        = :func:`slugify_tags` over the hook + sourceTitle.

    ``override`` (e.g. an LLM-written suggestion) wins per-field when its value is
    truthy — so a caller can supply just a better title and keep derived tags.
    """
    override = override or {}
    hook = str(meta.get("hook") or "").strip()
    source_title = str(meta.get("sourceTitle") or "").strip()

    title = _truncate(str(override.get("title") or hook or source_title or DEFAULT_TITLE), MAX_TITLE_LEN)

    if override.get("description"):
        description = _truncate(str(override["description"]), MAX_DESCRIPTION_LEN)
    else:
        parts = [hook] if hook else []
        if source_title:
            parts.append(f"From: {source_title}")
        description = _truncate(" ".join(parts) or DEFAULT_DESCRIPTION, MAX_DESCRIPTION_LEN)

    tags = _normalize_tag_list(override["tags"]) if override.get("tags") else slugify_tags(f"{hook} {source_title}")

    return {"title": title, "description": description, "tags": tags}


def _normalize_tag_list(tags: Any) -> list[str]:
    """Coerce an override tag value (list or comma string) to a clean tag list."""
    if isinstance(tags, str):
        candidates: Iterable[str] = re.split(r"[,\s]+", tags)
    elif isinstance(tags, (list, tuple)):
        candidates = (str(t) for t in tags)
    else:
        return []
    out: dict[str, None] = {}
    for raw in candidates:
        token = str(raw).strip().lstrip("#").lower()
        if token and token not in out:
            out[token] = None
        if len(out) >= MAX_TAGS:
            break
    return list(out.keys())


def build_manifest(meta: Meta, suggestion: Suggestion) -> dict[str, Any]:
    """Assemble the full ``upload.json`` payload from clip ``meta`` + suggestion.

    Carries the suggested copy plus the source facts a creator/automation may
    want (source video id/title, the caption template, the virality score, and
    duration). Pure: builds a fresh dict, normalizing every value to a wire type.
    """
    pct = meta.get("viralityPct")
    return {
        "title": str(suggestion.get("title") or DEFAULT_TITLE),
        "description": str(suggestion.get("description") or DEFAULT_DESCRIPTION),
        "tags": list(suggestion.get("tags") or []),
        "source": {
            "videoId": str(meta.get("videoId") or ""),
            "sourceTitle": str(meta.get("sourceTitle") or ""),
            "template": str(meta.get("template") or ""),
            "viralityPct": pct if isinstance(pct, int) else None,
            "durationSec": float(meta.get("durationSec") or 0.0),
            "hook": str(meta.get("hook") or ""),
        },
    }


# --------------------------------------------------------------------------- #
# packaging (file I/O)
# --------------------------------------------------------------------------- #
def package(
    clip_path: str | os.PathLike,
    out_path: str | os.PathLike,
    *,
    meta: Meta | None = None,
    thumbnail_path: str | os.PathLike | None = None,
    suggestion: Suggestion | None = None,
) -> dict[str, Any]:
    """Bundle ``clip_path`` (+ thumbnail + ``upload.json``) into a ZIP at ``out_path``.

    Returns ``{"path": <zip>, "manifest": <upload.json dict>}``. The video is
    required (a missing clip raises ``FileNotFoundError``); the thumbnail is
    optional (skipped when absent). The manifest is built from ``meta`` (defaults
    to ``{}``) via :func:`build_suggestion` / :func:`build_manifest`, with an
    optional ``suggestion`` override winning per-field.

    The archive is written with ``ZIP_DEFLATED`` and deterministic arc-names
    (:data:`ARC_VIDEO` / :data:`ARC_THUMBNAIL` / :data:`ARC_MANIFEST`).
    """
    meta = dict(meta or {})
    clip = Path(clip_path)
    if not clip.exists():
        raise FileNotFoundError(f"short not found: {clip_path}")

    final_suggestion = build_suggestion(meta, override=suggestion)
    manifest = build_manifest(meta, final_suggestion)

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.write(clip, arcname=ARC_VIDEO)
        if thumbnail_path is not None:
            thumb = Path(thumbnail_path)
            if thumb.exists():
                zf.write(thumb, arcname=ARC_THUMBNAIL)
        zf.writestr(ARC_MANIFEST, json.dumps(manifest, ensure_ascii=False, indent=2))
    return {"path": str(out), "manifest": manifest}


__all__ = [
    "ARC_MANIFEST",
    "ARC_THUMBNAIL",
    "ARC_VIDEO",
    "DEFAULT_DESCRIPTION",
    "DEFAULT_TITLE",
    "MAX_TAGS",
    "build_manifest",
    "build_suggestion",
    "package",
    "slugify_tags",
]
