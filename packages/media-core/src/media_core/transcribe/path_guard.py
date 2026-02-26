from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable


def _normalize_roots(candidates: Iterable[Path]) -> list[Path]:
    roots: list[Path] = []
    for candidate in candidates:
        value = str(candidate).strip()
        if not value:
            continue
        try:
            roots.append(Path(value).expanduser().resolve(strict=False))
        except OSError:
            continue
    return roots


def _env_roots() -> list[Path]:
    return _normalize_roots(
        Path(raw)
        for env_name in ("REFRAME_MEDIA_ROOT", "MEDIA_ROOT")
        for raw in [os.getenv(env_name, "").strip()]
        if raw
    )


def validate_media_input_path(path: str | Path, *, allowed_roots: Iterable[str | Path] | None = None) -> Path:
    """Resolve and validate an on-disk media path before backend reads.

    Validation steps:
    - resolve to a canonical absolute path,
    - ensure the target exists and is a regular file,
    - when roots are configured, ensure the file stays inside an allowed root.
    """

    candidate = Path(path).expanduser()
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError as exc:
        raise FileNotFoundError(candidate) from exc

    if not resolved.is_file():
        if resolved.is_dir():
            raise IsADirectoryError(resolved)
        raise FileNotFoundError(resolved)

    roots = _normalize_roots(Path(root) for root in allowed_roots) if allowed_roots is not None else _env_roots()
    if roots and not any(resolved == root or root in resolved.parents for root in roots):
        roots_text = ", ".join(str(root) for root in roots)
        raise ValueError(f"Refusing to read path outside allowed roots ({roots_text}): {resolved}")

    return resolved
