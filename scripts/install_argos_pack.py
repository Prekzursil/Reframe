#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys


def _ensure_argos():
    try:
        from argostranslate import package  # type: ignore
    except ImportError as exc:
        raise RuntimeError("argostranslate is not installed; install extras 'packages/media-core[translate-local]'") from exc
    return package


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Install an Argos Translate language pack (offline translation).")
    parser.add_argument("--src", default="", help="Source language code (e.g. en).")
    parser.add_argument("--tgt", default="", help="Target language code (e.g. es).")
    parser.add_argument("--list", action="store_true", help="List available language pairs and exit.")
    args = parser.parse_args(argv)

    try:
        package = _ensure_argos()
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print("Updating Argos package index...")
    package.update_package_index()

    available = package.get_available_packages()
    if args.list:
        pairs = sorted({f"{p.from_code}->{p.to_code}" for p in available})
        for pair in pairs:
            print(pair)
        return 0

    src = (args.src or "").strip().lower()
    tgt = (args.tgt or "").strip().lower()
    if not src or not tgt:
        print("ERROR: --src and --tgt are required (or use --list).", file=sys.stderr)
        return 2

    candidates = [p for p in available if p.from_code == src and p.to_code == tgt]
    if not candidates:
        pairs = sorted({f"{p.from_code}->{p.to_code}" for p in available})
        print(f"ERROR: No Argos pack found for {src}->{tgt}.", file=sys.stderr)
        print("Available pairs:", file=sys.stderr)
        for pair in pairs:
            print(f"  {pair}", file=sys.stderr)
        return 3

    selected = candidates[0]
    print(f"Downloading {selected.from_code}->{selected.to_code} ...")
    downloaded_path = selected.download()
    print(f"Installing from {downloaded_path} ...")
    package.install_from_path(downloaded_path)
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

