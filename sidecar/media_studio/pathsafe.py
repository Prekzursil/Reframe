"""Path-confinement + log-sanitisation helpers (the security choke point).

The sidecar resolves a relocatable data root and assorted file names from
*environment variables* and *RPC/settings values* (``MEDIA_STUDIO_CONFIG_DIR``,
``MEDIA_STUDIO_FFMPEG``, a manifest ``dest``, a ``video_id`` …). Those are
attacker-influenceable inputs as far as static analysis is concerned, so every
one that reaches a filesystem call must first be **canonicalised and proven to
stay inside an allowed base directory**. This module is the single shared
implementation of that control; callers use the RETURN VALUE at the sink.

CodeQL's ``py/path-injection`` recognises exactly one barrier shape (see
``semmle/python/security/dataflow/PathInjectionQuery.qll``): a value normalised
by ``os.path.realpath`` / ``os.path.normpath`` / ``os.path.abspath`` that is then
the receiver of a ``str.startswith`` check, with the protected use on the *True*
branch. ``ensure_within`` implements precisely that shape, so the taint is
neutralised inside this function and every caller that uses the returned path is
sanitised interprocedurally. ``Path.resolve()`` and ``os.path.commonpath`` are
deliberately NOT used — CodeQL does not model them as normalisation/guards.

``clean_for_log`` strips line breaks from user-derived values before they are
logged (``py/log-injection``); a ``str.replace`` of line breaks is the barrier
CodeQL recognises for that query.
"""

from __future__ import annotations

import os

__all__ = ["PathTraversalError", "ensure_within", "clean_for_log"]


class PathTraversalError(ValueError):
    """A candidate path escaped its allowed base directory."""


def _real(path: str | os.PathLike[str]) -> str:
    """Canonical real path of ``path`` as a string (symlinks + ``..`` resolved)."""
    return os.path.realpath(os.fspath(path))


def ensure_within(base: str | os.PathLike[str], *parts: str | os.PathLike[str]) -> str:
    """Return the canonical path of ``base`` joined with ``parts``, confined to ``base``.

    The result is ``os.path.realpath``-normalised and proven (via ``startswith``)
    to live inside the real path of ``base``; this is the exact barrier shape
    CodeQL's ``py/path-injection`` query recognises, so the returned value is
    safe to hand to ``open`` / ``Path`` / ``mkdir`` / ``os.replace`` / ``stat``.

    Raises :class:`PathTraversalError` when the resolved path escapes ``base``
    — an absolute ``part`` on another root, ``..`` traversal, or a symlink that
    points outside the tree. ``ensure_within(base)`` (no parts) simply returns
    the normalised, confined ``base`` itself.
    """
    base_real = _real(base)
    joined = os.path.join(base_real, *(os.fspath(p) for p in parts))
    target = os.path.realpath(joined)
    # CodeQL barrier: `target` is realpath-normalised and checked with startswith.
    prefix = base_real if base_real.endswith(os.sep) else base_real + os.sep
    if target == base_real or target.startswith(prefix):
        return target
    # Unreachable with no ``parts`` (``target == base_real`` holds), so the join
    # below always has at least one argument when this raise fires.
    rel = os.path.join(*(os.fspath(p) for p in parts))
    raise PathTraversalError(f"path {rel!r} escapes allowed base {base_real!r}")


def clean_for_log(value: object) -> str:
    """Return ``str(value)`` with CR/LF (and the NUL byte) flattened to spaces.

    Strips the control characters an attacker would use to forge extra log lines
    (``py/log-injection``). The ``str.replace`` of line breaks is the sanitiser
    CodeQL recognises for that query.
    """
    text = str(value)
    return text.replace("\r", " ").replace("\n", " ").replace("\x00", " ")
