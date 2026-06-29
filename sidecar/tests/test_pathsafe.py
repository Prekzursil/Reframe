"""Unit coverage for media_studio.pathsafe — the path-confinement + log-scrub
choke point. Exercises every branch: confined join, bare-base normalisation, the
filesystem-root prefix branch, ``..`` traversal, an absolute part on another
root, and the CR/LF/NUL log scrub.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from media_studio.pathsafe import PathTraversalError, clean_for_log, ensure_within


def test_ensure_within_joins_and_confines(tmp_path: Path) -> None:
    got = ensure_within(tmp_path, "sub", "file.txt")
    assert got == os.path.realpath(str(tmp_path / "sub" / "file.txt"))
    # The returned value is canonical and lives under the (real) base.
    assert got.startswith(os.path.realpath(str(tmp_path)) + os.sep)


def test_ensure_within_bare_base_returns_normalised_base(tmp_path: Path) -> None:
    # No parts -> the confined, normalised base itself (target == base_real branch).
    assert ensure_within(tmp_path) == os.path.realpath(str(tmp_path))


def test_ensure_within_at_filesystem_root_prefix_branch(tmp_path: Path) -> None:
    # ``anchor`` realpaths to something ending in os.sep ("/" or "C:\\"), which
    # exercises the ``base_real.endswith(os.sep)`` prefix branch.
    anchor = Path(tmp_path).anchor
    assert os.path.realpath(anchor).endswith(os.sep)
    got = ensure_within(anchor, "any-child")
    assert got == os.path.realpath(os.path.join(anchor, "any-child"))


def test_ensure_within_rejects_dotdot_traversal(tmp_path: Path) -> None:
    with pytest.raises(PathTraversalError) as exc:
        ensure_within(tmp_path / "base", "..", "escapee")
    assert "escapes allowed base" in str(exc.value)


def test_ensure_within_rejects_absolute_part_on_other_root(tmp_path: Path) -> None:
    base = tmp_path / "base"
    base.mkdir()
    outside = tmp_path / "outside" / "secret.txt"
    # An absolute part makes os.path.join discard the base -> escape -> raise.
    with pytest.raises(PathTraversalError):
        ensure_within(base, str(outside))


def test_clean_for_log_flattens_control_chars() -> None:
    assert clean_for_log("a\r\nb\x00c") == "a  b c"
    assert clean_for_log("plain") == "plain"
    # Accepts non-str values (stringified first).
    assert clean_for_log(123) == "123"
