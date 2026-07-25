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

Three T5 companions round the control out, because *canonicalising* a value is
NOT the same as *confining* it (``ensure_within(value)`` with no extra parts is a
canonicaliser: ``target == base_real``, so it always returns):

* ``ensure_under`` — containment for a candidate that is ALREADY a full path
  (an RPC-supplied absolute destination), where there is no base + relative part
  to join. Use ``ensure_within`` whenever you DO have the relative part.
* ``is_safe_store_id`` — the grammar for an opaque id that becomes ONE filename
  component (``<store dir>/<id>.json``). A grammar is what stops ``../settings``
  BEFORE any path arithmetic; containment via ``ensure_within`` is then the
  second, independent layer.
* ``ensure_local_media_input`` — the ffmpeg/ffprobe media-input guard. ffmpeg
  reads its input through a PROTOCOL layer, so an ``http://``/``concat:``/UNC
  value is not a path at all: it is SSRF, an arbitrary local read, or an
  outbound SMB authentication. This one deliberately does NOT canonicalise —
  the value is a subprocess argv element and the string echoed back to the UI,
  so it validates and returns the input verbatim (a *reject-or-pass* guard).
"""

from __future__ import annotations

import os
import re
from urllib.parse import urlparse

__all__ = [
    "PathTraversalError",
    "UnsafeMediaInputError",
    "ensure_within",
    "ensure_under",
    "is_safe_store_id",
    "ensure_local_media_input",
    "clean_for_log",
]

#: An opaque store key: ASCII alnum start, then alnum / ``.`` / ``_`` / ``-``, at
#: most 64 chars. Deliberately EXCLUDES every path-significant byte — ``/``,
#: ``\``, ``:``, NUL, CR/LF, whitespace, ``%`` — and the alnum-start requirement
#: alone rejects ``.``, ``..``, ``.hidden`` and ``-flag``. The id is treated as
#: OPAQUE: nothing is stripped or "sanitised", a non-conforming id is refused.
_SAFE_STORE_ID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")

#: Two leading separators = a UNC share (``\\host\share``) or a Windows device
#: namespace (``\\.\``, ``\\?\``). Mirrors ``settings_store._canonical_local_dir``.
_DOUBLE_SEP_RE = re.compile(r"[\\/]{2}")
#: ``urlparse("C:/x").scheme == "c"`` — a ONE-letter "scheme" is a Windows drive,
#: never an ffmpeg protocol (every ffmpeg protocol name is 3+ chars).
_DRIVE_SCHEME_RE = re.compile(r"[A-Za-z]")
#: The whole first path segment being exactly ``<letter>:`` is a drive root.
_DRIVE_SEGMENT_RE = re.compile(r"[A-Za-z]:")


class PathTraversalError(ValueError):
    """A candidate path escaped its allowed base directory."""


class UnsafeMediaInputError(ValueError):
    """A media input was not a plain LOCAL filesystem path (protocol/UNC/empty)."""


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
    # CodeQL py/path-injection barrier: the realpath-normalised `target` is the
    # DIRECT receiver of a `str.startswith` check against the real base, with the
    # protected use on the True branch. The second clause admits the base dir
    # itself (exact length) and a base that is a filesystem root (already ends in
    # a separator), while still rejecting the classic prefix-sibling escape
    # (`…/base` must not match `…/base2`). Keeping `target.startswith(base_real)`
    # as the outer guard — never an `== ` disjunct — is what makes the barrier
    # recognised even when there are no extra ``parts`` (a bare canonicalise).
    if target.startswith(base_real) and (
        base_real.endswith(os.sep)
        or len(target) == len(base_real)
        or target[len(base_real) : len(base_real) + 1] == os.sep
    ):
        return target
    # Unreachable with no ``parts`` (``target == base_real`` holds), so the join
    # below always has at least one argument when this raise fires.
    rel = os.path.join(*(os.fspath(p) for p in parts))
    raise PathTraversalError(f"path {rel!r} escapes allowed base {base_real!r}")


def ensure_under(base: str | os.PathLike[str], candidate: str | os.PathLike[str]) -> str:
    """Return the canonical ``candidate`` after proving it lives inside ``base``.

    The companion to :func:`ensure_within` for a candidate that is ALREADY a full
    (typically absolute) path — an RPC-supplied output destination — where there
    is no base + relative part to join. Prefer :func:`ensure_within` whenever the
    caller HAS the relative part; that is the real containment shape and this is
    the (rarer) "validate a full path against an allowed root" shape.

    Raises :class:`PathTraversalError` when the resolved candidate is outside
    ``base`` — another drive/root, a ``..`` escape, a symlink out of the tree, or
    the classic prefix-sibling (``…/base`` must not admit ``…/base_evil``).
    """
    base_real = _real(base)
    target = _real(candidate)
    # CodeQL py/path-injection barrier: same shape as `ensure_within` — the
    # realpath-normalised `target` is the DIRECT receiver of a `str.startswith`
    # against the real base, protected use on the True branch. The prefix test is
    # DELIBERATELY duplicated rather than factored into a shared helper: CodeQL
    # recognises this barrier syntactically, per function, so extracting it would
    # silently un-sanitise `ensure_within`'s existing callers across the sidecar.
    if target.startswith(base_real) and (
        base_real.endswith(os.sep)
        or len(target) == len(base_real)
        or target[len(base_real) : len(base_real) + 1] == os.sep
    ):
        return target
    raise PathTraversalError(f"path {os.fspath(candidate)!r} escapes allowed base {base_real!r}")


def is_safe_store_id(value: object) -> bool:
    """``True`` iff ``value`` is an opaque id safe to use as ONE filename component.

    The grammar (:data:`_SAFE_STORE_ID_RE`) is an ALLOWLIST, so a caller never has
    to enumerate attacks: ``../settings``, ``..\\..\\evil``, ``/etc/passwd``,
    ``C:/Windows/win.ini``, ``a/b``, ``.``/``..``, a CR/LF or NUL byte, and a
    percent-encoded traversal are all simply not the expected shape. Non-``str``
    input is refused rather than coerced.
    """
    return isinstance(value, str) and _SAFE_STORE_ID_RE.match(value) is not None


def ensure_local_media_input(value: str | os.PathLike[str]) -> str:
    """Return ``value`` VERBATIM once it is proven to be a plain local media path.

    ffmpeg/ffprobe resolve an input through a protocol layer, so a renderer string
    is not merely a path: ``http(s)``/``ftp``/``tcp``/``udp``/``rtmp`` reach the
    network (SSRF + internal-service probing), ``concat:``/``file:``/``subfile,,``
    read arbitrary local files, and a UNC ``\\\\host\\share`` triggers an outbound
    SMB authentication (NTLM credential leak). Four rejections, in order:

    1. an empty value (nothing to convert);
    2. two leading separators — UNC share or Windows device namespace;
    3. a :func:`urllib.parse.urlparse` scheme that is not a one-letter Windows
       drive (``urlparse("C:/x").scheme == "c"``, which must stay legal);
    4. any residual ``:`` in the first path segment — ffmpeg splits on the FIRST
       colon and reads the prefix as ``protocol,options``, and a comma makes that
       prefix an INVALID urlparse scheme (``subfile,,start,0,end,64:/etc/passwd``
       parses as scheme-less), so step 3 alone does not see it.

    Returns the input unchanged (stringified): this is a *reject-or-pass* guard,
    NOT a canonicaliser — the value is handed to a subprocess argv (never to a
    Python filesystem call here) and is surfaced back to the UI, so rewriting it
    would change observable behaviour. Confine a value bound for an ``open`` /
    ``mkdir`` / ``unlink`` sink with :func:`ensure_within` instead.

    Raises :class:`UnsafeMediaInputError` on every rejection; the offending value
    is scrubbed with :func:`clean_for_log` first so a hostile input cannot forge
    log lines through the error message.
    """
    text = os.fspath(value)
    if not text:
        raise UnsafeMediaInputError("media input is empty")
    safe = clean_for_log(text)
    if _DOUBLE_SEP_RE.match(text):
        raise UnsafeMediaInputError(f"media input {safe!r} is a UNC/device path, not a local file")
    try:
        scheme = urlparse(text).scheme
    except ValueError as exc:
        raise UnsafeMediaInputError(f"media input {safe!r} is not a parseable local path") from exc
    if scheme and _DRIVE_SCHEME_RE.fullmatch(scheme) is None:
        raise UnsafeMediaInputError(
            f"media input {safe!r} uses the {clean_for_log(scheme)!r} protocol, not a local file"
        )
    head = re.split(r"[\\/]", text, maxsplit=1)[0]
    if ":" in head and _DRIVE_SEGMENT_RE.fullmatch(head) is None:
        raise UnsafeMediaInputError(f"media input {safe!r} carries an ffmpeg protocol/option prefix, not a local file")
    return text


def clean_for_log(value: object) -> str:
    """Return ``str(value)`` with CR/LF (and the NUL byte) flattened to spaces.

    Strips the control characters an attacker would use to forge extra log lines
    (``py/log-injection``). The ``str.replace`` of line breaks is the sanitiser
    CodeQL recognises for that query.
    """
    text = str(value)
    return text.replace("\r", " ").replace("\n", " ").replace("\x00", " ")
