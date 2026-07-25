"""Unit coverage for media_studio.pathsafe — the path-confinement + log-scrub
choke point. Exercises every branch: confined join, bare-base normalisation, the
filesystem-root prefix branch, ``..`` traversal, an absolute part on another
root, the prefix-sibling escape, and the CR/LF/NUL log scrub.

T5 additions: :func:`ensure_under` (containment for a candidate that is already a
full path), :func:`is_safe_store_id` (the opaque store-key grammar) and
:func:`ensure_local_media_input` (the ffmpeg media-input protocol/UNC guard).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from media_studio.pathsafe import (
    PathTraversalError,
    UnsafeMediaInputError,
    clean_for_log,
    ensure_local_media_input,
    ensure_under,
    ensure_within,
    is_safe_store_id,
)


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


def test_ensure_within_rejects_prefix_sibling_escape(tmp_path: Path) -> None:
    # A sibling dir that SHARES the base's name prefix (`base` vs `base_evil`)
    # must NOT be accepted — guards the classic str.startswith prefix bug.
    (tmp_path / "base").mkdir()
    (tmp_path / "base_evil").mkdir()
    with pytest.raises(PathTraversalError):
        ensure_within(tmp_path / "base", "..", "base_evil", "secret.txt")


def test_clean_for_log_flattens_control_chars() -> None:
    assert clean_for_log("a\r\nb\x00c") == "a  b c"
    assert clean_for_log("plain") == "plain"
    # Accepts non-str values (stringified first).
    assert clean_for_log(123) == "123"


# --------------------------------------------------------------------------- #
# ensure_under — containment for an ALREADY-FULL candidate path
# --------------------------------------------------------------------------- #
def test_ensure_under_accepts_child_and_canonicalises(tmp_path: Path) -> None:
    base = tmp_path / "base"
    base.mkdir()
    got = ensure_under(base, str(base / "sub" / "clip.mp4"))
    assert got == os.path.realpath(str(base / "sub" / "clip.mp4"))
    assert got.startswith(os.path.realpath(str(base)) + os.sep)


def test_ensure_under_accepts_the_base_itself(tmp_path: Path) -> None:
    # target == base_real -> the exact-length branch.
    assert ensure_under(tmp_path, str(tmp_path)) == os.path.realpath(str(tmp_path))


def test_ensure_under_at_filesystem_root_prefix_branch(tmp_path: Path) -> None:
    # ``anchor`` realpaths to something ending in os.sep ("/" or "C:\\") -> the
    # ``base_real.endswith(os.sep)`` prefix branch.
    anchor = Path(tmp_path).anchor
    assert os.path.realpath(anchor).endswith(os.sep)
    got = ensure_under(anchor, os.path.join(anchor, "any-child"))
    assert got == os.path.realpath(os.path.join(anchor, "any-child"))


def test_ensure_under_rejects_candidate_outside_base(tmp_path: Path) -> None:
    base = tmp_path / "base"
    base.mkdir()
    with pytest.raises(PathTraversalError) as exc:
        ensure_under(base, str(tmp_path / "outside" / "secret.txt"))
    assert "escapes allowed base" in str(exc.value)


def test_ensure_under_rejects_dotdot_candidate(tmp_path: Path) -> None:
    base = tmp_path / "base"
    base.mkdir()
    with pytest.raises(PathTraversalError):
        ensure_under(base, str(base / ".." / "escapee.txt"))


def test_ensure_under_rejects_prefix_sibling_escape(tmp_path: Path) -> None:
    # `…/base` must not admit `…/base_evil` (the classic str.startswith bug).
    (tmp_path / "base").mkdir()
    (tmp_path / "base_evil").mkdir()
    with pytest.raises(PathTraversalError):
        ensure_under(tmp_path / "base", str(tmp_path / "base_evil" / "secret.txt"))


# --------------------------------------------------------------------------- #
# is_safe_store_id — the opaque store-key grammar (one filename component)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "value",
    ["a", "0", "abc123", "9f2c1d4e5a6b", "fixed-id", "b_1", "a.b", "A" * 64],
)
def test_is_safe_store_id_accepts_opaque_ids(value: str) -> None:
    assert is_safe_store_id(value) is True


@pytest.mark.parametrize(
    "value",
    [
        "",  # empty
        "..",  # the traversal token itself
        ".",  # the current directory
        "../settings",  # POSIX traversal (the 8-slice finding's payload)
        "..\\..\\evil",  # Windows traversal
        "a/b",  # nested path
        "a\\b",
        "/etc/passwd",  # POSIX absolute
        "C:/Windows/win.ini",  # Windows absolute (drive colon)
        "C:x",  # drive-relative
        ".hidden",  # leading dot
        "-flag",  # leading dash (an option-looking id)
        "a b",  # whitespace
        "a\nb",  # CR/LF (log forging)
        "a\x00b",  # NUL byte (path truncation)
        "A" * 65,  # over the length cap
        "café",  # non-ASCII
        "%2e%2e%2fsettings",  # percent-encoded traversal
    ],
)
def test_is_safe_store_id_rejects_everything_else(value: str) -> None:
    assert is_safe_store_id(value) is False


@pytest.mark.parametrize("value", [None, 7, b"abc", Path("abc")])
def test_is_safe_store_id_rejects_non_str(value: object) -> None:
    assert is_safe_store_id(value) is False


# --------------------------------------------------------------------------- #
# ensure_local_media_input — the ffmpeg media-input guard (protocols + UNC)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "value",
    [
        "clip.mp4",
        "sub/dir/clip.mp4",
        "/home/user/clip.mp4",
        "C:/Users/me/clip.mp4",
        "C:\\Users\\me\\clip.mp4",
        "/a b/a clip.mov",
        "./relative.mp4",
    ],
)
def test_ensure_local_media_input_accepts_plain_local_paths(value: str) -> None:
    # The guard VALIDATES; it deliberately does not canonicalise (the value is an
    # ffmpeg argv element + the string echoed back to the UI).
    assert ensure_local_media_input(value) == value


def test_ensure_local_media_input_accepts_pathlike(tmp_path: Path) -> None:
    assert ensure_local_media_input(tmp_path / "clip.mp4") == str(tmp_path / "clip.mp4")


@pytest.mark.parametrize(
    "value",
    [
        "http://169.254.169.254/latest/meta-data",  # SSRF / cloud metadata
        "https://evil.example/x.mp4",
        "ftp://host/x.mp4",
        "rtmp://host/live",
        "tcp://127.0.0.1:6379",  # internal-service probe
        "udp://239.0.0.1:1234",
        "concat:/etc/passwd|/etc/shadow",  # arbitrary local read
        "file:///etc/passwd",
        "data:application/octet-stream,AAAA",
        "pipe:0",
        "cache:http://evil.example/x.mp4",
    ],
)
def test_ensure_local_media_input_rejects_protocols(value: str) -> None:
    with pytest.raises(UnsafeMediaInputError) as exc:
        ensure_local_media_input(value)
    assert "protocol" in str(exc.value)


@pytest.mark.parametrize(
    "value",
    ["\\\\attacker.example\\share\\a.mp4", "//attacker.example/share/a.mp4", "\\\\?\\C:\\x.mp4"],
)
def test_ensure_local_media_input_rejects_unc_and_device_paths(value: str) -> None:
    with pytest.raises(UnsafeMediaInputError) as exc:
        ensure_local_media_input(value)
    assert "UNC" in str(exc.value)


def test_ensure_local_media_input_rejects_option_bearing_protocol_spec() -> None:
    # ffmpeg splits on the FIRST ':' and reads the prefix as protocol+options, but
    # the comma makes it an INVALID urlparse scheme — so the residual colon rule,
    # not the scheme check, is what refuses this one.
    with pytest.raises(UnsafeMediaInputError) as exc:
        ensure_local_media_input("subfile,,start,0,end,64:/etc/passwd")
    assert "prefix" in str(exc.value)


def test_ensure_local_media_input_rejects_unparseable_url() -> None:
    # urlparse itself raises on a malformed IPv6 literal; a value it cannot parse
    # is not a local path either.
    with pytest.raises(UnsafeMediaInputError):
        ensure_local_media_input("http://[::1")


def test_ensure_local_media_input_rejects_empty() -> None:
    with pytest.raises(UnsafeMediaInputError):
        ensure_local_media_input("")


def test_ensure_local_media_input_scrubs_control_chars_from_the_message() -> None:
    # The rejected value is echoed in the error (and thus the log): CR/LF must be
    # flattened so a hostile input cannot forge log lines (py/log-injection).
    with pytest.raises(UnsafeMediaInputError) as exc:
        ensure_local_media_input("http://evil.example/a\nFAKE LOG LINE")
    assert "\n" not in str(exc.value)
