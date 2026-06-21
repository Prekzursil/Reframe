"""Deep, isolated COPY of a project manifest (DESIGN §5, WU-apply).

The Director's reversibility contract is: **apply writes to a project COPY, never
the source manifest** (DESIGN §5; today every handler mutates ``project.data`` in
place and ``project.save()``s — there is no copy, no undo, e.g. ``subtitles_edit``
``handlers.py:746-761``). :func:`copy_project` produces that COPY:

  * it **deep-copies** ``project.data`` so mutating the COPY can never reach the
    source (the immutability contract the in-place handlers lack);
  * it computes an **isolated** manifest path under a sibling director-copy
    folder, so the COPY's manifest is written away from the source;
  * the one real *filesystem write* is delegated to an injected ``writer`` — the
    default writer (real disk I/O) is the single ``# pragma: no cover`` seam, so
    the copy/merge/path logic stays a PURE, fully-tested function.

PURITY: stdlib only — NO ``Provider``/transport/heavy-ML import (the apply layer
is pure dispatch; the model call is WU-plan-rpc via ``_run_ai_job``).
"""

from __future__ import annotations

import copy as _copy
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

#: Folder name (sibling to the source manifest) the COPY's manifest is written
#: into, keeping the COPY isolated from the source on disk.
DIRECTOR_COPY_DIR = ".director-copy"
#: The COPY manifest filename inside :data:`DIRECTOR_COPY_DIR`.
COPY_MANIFEST_NAME = "project.json"

#: An injectable manifest writer ``(path, data) -> None`` (the disk seam).
Writer = Callable[[Path, dict[str, Any]], None]


class _ProjectLike(Protocol):
    """The minimal surface :func:`copy_project` needs (matches ``library.Project``)."""

    data: dict[str, Any]
    manifest_path: Path | None


@dataclass(frozen=True)
class ProjectCopy:
    """An isolated, deep COPY of a project's manifest data + its COPY path.

    ``data`` is a deep copy of the source ``project.data`` (mutating it never
    touches the source). ``manifest_path`` is where the COPY's manifest lives on
    disk (under :data:`DIRECTOR_COPY_DIR`). The apply engine (WU-apply) mutates
    ``data`` op-by-op and records an inverse so the whole plan has a one-shot undo.
    """

    data: dict[str, Any]
    manifest_path: Path


def _default_writer(path: Path, data: dict[str, Any]) -> None:  # pragma: no cover - disk I/O seam
    """Write the COPY manifest to disk (the only real-filesystem seam)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _copy_dest(source_manifest: Path | None) -> Path:
    """Resolve the isolated COPY manifest path for ``source_manifest``.

    The COPY lives in a :data:`DIRECTOR_COPY_DIR` folder beside the source
    manifest (or the cwd when the source has no manifest path yet).
    """
    base = source_manifest.parent if source_manifest is not None else Path.cwd()
    return base / DIRECTOR_COPY_DIR / COPY_MANIFEST_NAME


def copy_project(
    project: _ProjectLike,
    *,
    dest_dir: Path | None = None,
    writer: Writer | None = None,
) -> ProjectCopy:
    """Return a deep, isolated :class:`ProjectCopy` of ``project`` (DESIGN §5).

    ``data`` is deep-copied so the COPY is fully detached from the source. The
    COPY manifest path is ``dest_dir/project.json`` when ``dest_dir`` is given,
    else a director-copy folder derived from the source manifest path. The COPY
    is written via ``writer`` (default = real disk I/O, the pragma seam).
    """
    data = _copy.deepcopy(project.data)
    manifest_path = dest_dir / COPY_MANIFEST_NAME if dest_dir is not None else _copy_dest(project.manifest_path)
    write = writer if writer is not None else _default_writer
    write(manifest_path, data)
    return ProjectCopy(data=data, manifest_path=manifest_path)
