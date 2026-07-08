"""Generate a fully-hashed lockfile for a pip ``--target`` env (WU C4, F1 prep).

This is a BUILD-PREP tool, not a runtime path. Its OUTPUT (a lock whose every
requirement carries a ``--hash=`` over the full transitive closure) is staged
offline like the ffmpeg binary — real hashes require reaching PyPI (and, for the
chatterbox env, the cu128 torch index), so they are never generated inside a
hermetic test/build session. Once a lock is generated + staged next to its
requirements file (``requirements-sidecar.txt`` -> ``requirements-sidecar.lock
.txt``), :func:`runtime_setup.bootstrap.install_env` installs from it with
``pip install --require-hashes --only-binary=:all: --no-deps -r <lock>`` and
:func:`media_studio.assets.manager.validate_hashed_lock` gates it.

Usage (run at F1 build-prep, with network)::

    # sidecar env (plain PyPI)
    python -m runtime_setup.generate_hashed_lock \\
        runtime_setup/requirements-sidecar.txt \\
        runtime_setup/requirements-sidecar.lock.txt

    # chatterbox env — the cu128 torch index is a STILL-HASHED per-index
    # exception (custom index, wheels hash-verified all the same)
    python -m runtime_setup.generate_hashed_lock \\
        runtime_setup/requirements-chatterbox.txt \\
        runtime_setup/requirements-chatterbox.lock.txt \\
        --extra-index-url https://download.pytorch.org/whl/cu128

``uv pip compile --generate-hashes`` is the default backend (fast, deterministic,
and it emits the ``pkg==ver \\`` + indented ``--hash=`` shape the validator
expects). ``pip-compile --generate-hashes`` (pip-tools) produces an equivalent
lock; pass ``--tool pip-compile`` to use it. The ``--extra-index-url`` you pass
here MUST also appear inside the generated lock so pip can find the custom-index
wheels at install time (uv/pip-compile write it into the lock header).
"""

from __future__ import annotations

import argparse
import subprocess  # noqa: S404 - argv-list subprocess only, never shell=True
from collections.abc import Sequence

#: build-backend argv prefixes. Both emit hashed locks in the validator's shape.
_TOOL_PREFIXES: dict[str, tuple[str, ...]] = {
    "uv": ("uv", "pip", "compile"),
    "pip-compile": ("pip-compile",),
}


def build_lock_gen_argv(
    req_in: str,
    lock_out: str,
    *,
    tool: str = "uv",
    extra_index_urls: Sequence[str] = (),
) -> list[str]:
    """The argv that compiles ``req_in`` into a fully-hashed ``lock_out`` (pure).

    ``--generate-hashes`` is what turns every resolved requirement (incl. the
    full transitive closure) into a ``--hash=``-pinned line — the verify-before
    -exec guarantee. Each ``--extra-index-url`` is forwarded so a custom index
    (the cu128 torch wheels) resolves AND is recorded in the lock header.
    """
    if tool not in _TOOL_PREFIXES:
        raise ValueError(f"unknown lock-gen tool {tool!r} (expected one of {tuple(_TOOL_PREFIXES)})")
    argv = [*_TOOL_PREFIXES[tool], req_in, "--generate-hashes", "--output-file", lock_out]
    for url in extra_index_urls:
        argv += ["--extra-index-url", url]
    return argv


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="generate_hashed_lock",
        description="Compile a fully-hashed lockfile for a pip --target env (WU C4 / F1 build-prep).",
    )
    parser.add_argument("req_in", help="the pinned requirements file to lock")
    parser.add_argument("lock_out", help="the hashed lockfile to write")
    parser.add_argument(
        "--tool",
        choices=sorted(_TOOL_PREFIXES),
        default="uv",
        help="lock-gen backend (default: uv)",
    )
    parser.add_argument(
        "--extra-index-url",
        action="append",
        default=[],
        dest="extra_index_urls",
        help="an extra index (e.g. the cu128 torch index); repeatable",
    )
    parser.add_argument("--dry-run", action="store_true", help="print the argv and exit (no network)")
    return parser


def main(argv: Sequence[str] | None = None, *, run: object = None) -> int:
    """CLI entry: compile the hashed lock (or print the argv with ``--dry-run``).

    ``run`` is an injectable ``argv -> returncode`` seam so the subprocess call
    is testable without a real ``uv``/network.
    """
    args = build_arg_parser().parse_args(argv)
    cmd = build_lock_gen_argv(
        args.req_in,
        args.lock_out,
        tool=args.tool,
        extra_index_urls=args.extra_index_urls,
    )
    if args.dry_run:
        print("DRY-RUN " + " ".join(cmd))
        return 0
    runner = run if run is not None else _default_run
    code = runner(cmd)  # type: ignore[operator]
    if code != 0:
        print(f"FAILED:generate_hashed_lock exit {code}: {' '.join(cmd)}")
    else:
        print(f"SUCCESS:generate_hashed_lock wrote {args.lock_out}")
    return code


def _default_run(argv: Sequence[str]) -> int:
    proc = subprocess.run(list(argv))  # noqa: S603 - argv list, no shell
    return proc.returncode


if __name__ == "__main__":  # pragma: no cover - process entry
    raise SystemExit(main())
