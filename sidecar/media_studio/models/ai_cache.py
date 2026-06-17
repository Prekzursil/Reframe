"""AI-call content cache (WU-cache, PLAN §WU-cache).

A small on-disk JSON store keyed by the sha256 of a *canonicalized* AI request
``(messages, model, params)``. It exists so repeat / re-prompt AI calls are free:
the AI-Job envelope (``models/ai_job.py``, a LATER WU) consults this cache BEFORE
any provider call, making the free cloud tier usable and the budget honest.

Design contract (from the plan):
  * ``key(messages, model, params) -> str`` — PURE, deterministic content hash.
    Canonicalization sorts dict keys so logically-identical requests collide and
    any change to content, model, or a param yields a different key.
  * ``get(key)`` / ``put(key, result)`` — round-trip through an INJECTABLE store
    dir (tests pass a tmp path; real wiring passes ``data_dir/ai-cache``).

This module is deliberately import-light (stdlib only). The store dir is the ONLY
side effect, and a corrupt / unreadable entry is treated as a cache MISS so a bad
file can never crash the AI hot path.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

from ..util import get_logger

log = get_logger("media_studio.models.ai_cache")

#: Default sub-directory name under the app data dir (the data-dir wiring is a
#: LATER WU; this constant is the agreed name so that WU has a single source).
DEFAULT_CACHE_DIRNAME: Final[str] = "ai-cache"

#: A chat message is the OpenAI-style ``{"role": ..., "content": ...}`` dict.
Message = Mapping[str, str]


class AiCache:
    """Content-hash cache for AI requests, backed by a JSON-per-entry store dir.

    The store dir is injected so tests use a ``tmp_path`` and never touch the
    real data dir. The dir is created lazily on the first :meth:`put`.
    """

    def __init__(self, *, store_dir: str | os.PathLike[str]) -> None:
        self._store_dir = Path(store_dir)

    # --------------------------------------------------------------------- #
    # pure key derivation
    # --------------------------------------------------------------------- #
    def key(
        self,
        messages: Sequence[Message],
        model: str,
        params: Mapping[str, Any],
    ) -> str:
        """Return the sha256 hex digest of the canonicalized request.

        Canonicalization uses ``json.dumps(..., sort_keys=True)`` so dict /
        param ordering is irrelevant; any change to the messages, model, or a
        param value (including adding one) changes the digest.
        """
        canonical = json.dumps(
            {
                "messages": [dict(m) for m in messages],
                "model": model,
                "params": dict(params),
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    # --------------------------------------------------------------------- #
    # store layout
    # --------------------------------------------------------------------- #
    def path_for(self, key: str) -> Path:
        """Return the on-disk path backing ``key`` (one JSON file per entry)."""
        return self._store_dir / f"{key}.json"

    # --------------------------------------------------------------------- #
    # get / put
    # --------------------------------------------------------------------- #
    def get(self, key: str) -> Any | None:
        """Return the cached result for ``key``, or ``None`` on a miss.

        A missing, unreadable, or non-JSON entry is a MISS (never an exception):
        a corrupt cache file must not break the AI hot path.
        """
        path = self.path_for(key)
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            log.warning("ai_cache: discarding corrupt entry %s", key)
            return None

    def put(self, key: str, result: Any) -> None:
        """Store ``result`` (JSON-serializable) under ``key``, creating the dir."""
        self._store_dir.mkdir(parents=True, exist_ok=True)
        path = self.path_for(key)
        path.write_text(
            json.dumps(result, ensure_ascii=False),
            encoding="utf-8",
        )
