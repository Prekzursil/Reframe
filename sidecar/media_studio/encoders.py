"""Encoder-capability gate: can the RESOLVED ffmpeg encode what we hardcode?

THE DEFECT THIS EXISTS TO PREVENT
---------------------------------
Reframe v1.4 shipped with a bundled ffmpeg (BtbN win64-**LGPL**, configured
``--disable-libx264 --disable-libx265``) that cannot encode H.264 -- while nine
sidecar modules pass the literal string ``libx264`` to ``-c:v``. On the shipped
product every export died with ``Unknown encoder 'libx264'`` and produced no
file. Measured on the installed build (same argv, same input, same binary, only
the encoder token changed): ``-c:v libx264`` -> ``Unknown encoder``;
``-c:v libopenh264`` -> output produced.

Every gate was green throughout, because CI installs ffmpeg from apt/choco --
a GPL build that HAS libx264. **The gates measured a binary the user never
runs.** Unit tests, 100% coverage, and a launching app cannot see this class of
defect: it lives in the gap between the toolchain CI installs and the toolchain
that ships.

WHAT THIS MODULE ADDS
---------------------
The cheap, deterministic half of the anti-recurrence net: ask the ffmpeg that
will ACTUALLY be invoked (:func:`media_studio.ffmpeg.resolve_binary` -- the same
resolution order the pipeline uses) which encoders it lists, and compare that
against every encoder the source tree hardcodes.

It follows the shape already proven by
:func:`media_studio.features.stabilize.vidstab_available`, which probes the same
binary for a missing *filter*. libx264 was the same class of gap with no probe.

Two independent halves, so neither can drift silently:

* :func:`available_encoders` -- what the binary CAN do (runtime probe).
* :func:`scan_source_encoders` -- what the code DEMANDS (static AST scan).

:data:`REQUIRED_ENCODERS` is the declared contract between them;
``tests/test_encoders.py`` fails if the tree hardcodes an encoder the contract
does not list, so a future ``-c:v libsvtav1`` cannot re-open the blind spot.

Runnable three ways, all identical in behaviour:

* ``python -m media_studio.encoders``                       (default resolution)
* ``python -m media_studio.encoders --ffmpeg <path>``       (a specific binary)
* imported, via :func:`missing_encoders`                    (in-process)

Exits non-zero with a ``FAILED:encoder-capability`` marker naming the missing
encoders, or zero with ``SUCCESS:encoder-capability`` (``ci-hygiene.md`` 1:
terminal marker, fail closed).
"""

from __future__ import annotations

import argparse
import ast
import re
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from . import ffmpeg
from .util import get_logger

log = get_logger("media_studio.encoders")

#: Root of the shipped Python package -- what :func:`scan_source_encoders` walks.
PACKAGE_ROOT = Path(__file__).resolve().parent

#: Bound the capability probe. ``ffmpeg -encoders`` is a pure metadata dump
#: (no input file is opened), so this is generous.
PROBE_TIMEOUT_SEC = 20.0

#: Every encoder the shipped pipeline passes to ffmpeg as a LITERAL argv token.
#: Kept in sync with the tree by ``test_required_encoders_covers_every_encoder_
#: hardcoded_in_the_tree``. Adding an encoder to the code without adding it here
#: fails that test; adding it here without the bundled ffmpeg supporting it fails
#: this gate against the package. Both directions are closed.
#:
#: Derived from :func:`scan_source_encoders` over the real tree, NOT from memory:
#:   aac       14 sites (shortmaker, reframe_*, audiomix, fillers, dub, ...)
#:   libx264   13 sites across 9 modules -- the encoder the LGPL build lacks
#:   pcm_s16le  2 sites (features/tts/align.py, features/tts/edgetts.py)
#: ``pcm_s16le`` is a NATIVE ffmpeg encoder (present even in the LGPL build --
#: verified against the shipped binary), so it is listed for completeness, not
#: because it is currently at risk.
REQUIRED_ENCODERS: tuple[str, ...] = ("aac", "libx264", "pcm_s16le")

#: ffmpeg flags whose NEXT argv element names an encoder.
_STREAM_CODEC_FLAGS = frozenset({"-c:v", "-c:a", "-vcodec", "-acodec"})

#: Option-dict keys whose value names an encoder (``build_convert_argv`` opts).
_CODEC_KEYS = frozenset({"vcodec", "acodec"})

#: Values that are directives, not encoders -- ``copy`` is a stream copy and
#: needs no encoder at all.
_NOT_AN_ENCODER = frozenset({"copy"})

#: Vendored third-party trees. Excluded for the same reason ruff excludes them
#: (pyproject ``extend-exclude``): they are kept byte-faithful to upstream and
#: are not part of THIS project's ffmpeg contract.
_VENDORED = ("_lightasd", "_vinet_s", "_transnetv2")

#: One row of ``ffmpeg -encoders``: six flag characters (``V....D``), the
#: encoder name, then a description. Anchored on the flag block so the legend
#: header (`` V..... = Video``) cannot be misread as an encoder named ``=``.
_ENCODER_ROW = re.compile(r"^\s*[VAS][.A-Z0-9]{5}\s+(?P<name>\S+)\s")

#: A subprocess-runner seam (``subprocess.run``-shaped), injected in tests.
ProbeRunner = Callable[..., Any]


def parse_encoders(text: str) -> frozenset[str]:
    """Encoder names listed in ``ffmpeg -encoders`` output.

    Rows are only read AFTER the ``------`` separator, so the flag legend above
    it can never be parsed as an encoder. Unrecognised output yields an empty
    set -- the gate then reports everything missing rather than waving it
    through (fail closed).
    """
    names: set[str] = set()
    past_separator = False
    for line in text.splitlines():
        stripped = line.strip()
        if not past_separator:
            past_separator = bool(stripped) and set(stripped) == {"-"}
            continue
        match = _ENCODER_ROW.match(line)
        if match:
            names.add(match.group("name"))
    return frozenset(names)


def build_encoders_probe_argv(settings: Mapping[str, Any] | None = None) -> list[str]:
    """argv for the capability probe against the RESOLVED ffmpeg binary."""
    return [ffmpeg.ffmpeg_path(settings), "-hide_banner", "-encoders"]


def available_encoders(
    settings: Mapping[str, Any] | None = None,
    probe_runner: ProbeRunner | None = None,
) -> frozenset[str]:
    """Encoders the resolved ffmpeg actually advertises.

    Any failure (no ffmpeg resolvable, spawn error, timeout) yields an EMPTY set
    so the caller reports the requirement as missing. A probe that cannot run is
    never evidence that the capability is present. ``probe_runner`` is injected
    in tests so no real ffmpeg is spawned.
    """
    runner = probe_runner if probe_runner is not None else subprocess.run
    try:
        argv = build_encoders_probe_argv(settings)
    except Exception:  # noqa: BLE001 - no ffmpeg resolvable -> nothing available
        log.warning("ffmpeg not found for the encoder-capability probe")
        return frozenset()
    try:
        completed = runner(argv, capture_output=True, text=True, check=False, timeout=PROBE_TIMEOUT_SEC)
    except Exception:  # noqa: BLE001 - any spawn failure -> nothing available
        log.warning("encoder-capability probe failed to spawn ffmpeg")
        return frozenset()
    out = (getattr(completed, "stdout", "") or "") + (getattr(completed, "stderr", "") or "")
    return parse_encoders(out)


def missing_encoders(
    required: Sequence[str] | None = None,
    settings: Mapping[str, Any] | None = None,
    probe_runner: ProbeRunner | None = None,
) -> tuple[str, ...]:
    """Required encoders the resolved ffmpeg does NOT provide (sorted).

    Empty tuple == the binary can encode everything the pipeline asks of it.
    """
    wanted = REQUIRED_ENCODERS if required is None else tuple(required)
    have = available_encoders(settings, probe_runner=probe_runner)
    return tuple(sorted(set(wanted) - have))


def _literal(node: ast.AST | None) -> str | None:
    """The value of a string-literal AST node, else ``None`` (dynamic value)."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _encoders_in(node: ast.AST) -> list[str]:
    """Encoder names hardcoded in one AST node.

    Two shapes are recognised, matching how the tree actually spells them:
    an argv sequence (``[..., "-c:v", "libx264", ...]``) and an options dict
    (``{"vcodec": "libx264", "acodec": "aac"}``).
    """
    found: list[str] = []
    if isinstance(node, (ast.List, ast.Tuple)):
        for index, element in enumerate(node.elts[:-1]):
            flag = _literal(element)
            if flag in _STREAM_CODEC_FLAGS:
                value = _literal(node.elts[index + 1])
                if value:
                    found.append(value)
    elif isinstance(node, ast.Dict):
        for key, value_node in zip(node.keys, node.values, strict=True):
            if _literal(key) in _CODEC_KEYS:
                value = _literal(value_node)
                if value:
                    found.append(value)
    return [name for name in found if name not in _NOT_AN_ENCODER]


def scan_source_encoders(root: Path | str) -> dict[str, tuple[str, ...]]:
    """Map every hardcoded encoder name under ``root`` to the sites that use it.

    A STATIC scan (no import, no execution) so it is safe to run over the whole
    package. Only literal values are reported -- a dynamically-chosen encoder is
    invisible here by construction, which is a limitation worth stating rather
    than papering over: this catches the hardcoded case that actually shipped.
    """
    base = Path(root)
    found: dict[str, set[str]] = {}
    for path in sorted(base.rglob("*.py")):
        if any(part in _VENDORED for part in path.parts):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, ValueError, UnicodeDecodeError, OSError):
            # A malformed or unreadable file must not take the scan down; it
            # simply contributes nothing.
            log.warning("encoder scan skipped unparseable file: %s", path.name)
            continue
        for node in ast.walk(tree):
            for name in _encoders_in(node):
                site = f"{path.relative_to(base).as_posix()}:{getattr(node, 'lineno', 0)}"
                found.setdefault(name, set()).add(site)
    return {name: tuple(sorted(sites)) for name, sites in sorted(found.items())}


def main(argv: list[str] | None = None) -> int:
    """CLI gate. 0 == the resolved ffmpeg can encode everything we hardcode.

    Prints the binary it probed: a capability verdict that does not name the
    binary it measured is unfalsifiable -- and measuring the wrong binary is
    precisely how the libx264 defect reached users.
    """
    parser = argparse.ArgumentParser(
        prog="media_studio.encoders",
        description="Verify the resolved ffmpeg provides every encoder the pipeline hardcodes.",
    )
    parser.add_argument(
        "--ffmpeg",
        default=None,
        help="ffmpeg binary (or its directory) to probe; default: the app's own resolution order.",
    )
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    settings: dict[str, Any] = {"ffmpegPath": args.ffmpeg} if args.ffmpeg else {}
    try:
        resolved = ffmpeg.resolve_binary("ffmpeg", settings)
    except Exception as exc:  # noqa: BLE001 - unresolvable ffmpeg is a FAILED gate
        print(f"FAILED:encoder-capability could not resolve ffmpeg ({exc})")
        return 1

    print(f"encoder-capability: probed {resolved}")
    missing = missing_encoders(settings=settings)
    if missing:
        print(
            f"FAILED:encoder-capability missing={','.join(missing)} in {resolved} — "
            "the pipeline passes these as literal -c:v/-c:a tokens, so every affected "
            'export will die with "Unknown encoder". Bundle an ffmpeg built with them.'
        )
        return 1
    print(f"SUCCESS:encoder-capability {resolved} provides all of: {', '.join(REQUIRED_ENCODERS)}")
    return 0


if __name__ == "__main__":  # pragma: no cover — module CLI entry point
    raise SystemExit(main())
