#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path

from security_helpers import normalize_https_url


ALLOWED_MODEL_HOSTS = {"huggingface.co", "www.huggingface.co"}


def _default_output_dir() -> Path:
    configured = (os.getenv("WHISPERCPP_MODEL_DIR") or "").strip()
    if configured:
        return Path(configured)

    media_root = (os.getenv("REFRAME_MEDIA_ROOT") or os.getenv("MEDIA_ROOT") or "").strip()
    if media_root:
        root_path = Path(media_root)
        if root_path.exists():
            return root_path / "models" / "whispercpp"

    repo_root = Path(__file__).resolve().parents[1]
    return repo_root / ".tools" / "models" / "whispercpp"


def _normalize_filename(model: str) -> str:
    name = (model or "").strip()
    if not name:
        return "ggml-large-v3.bin"

    if not name.endswith(".bin"):
        name = f"{name}.bin"
    if not name.startswith("ggml-"):
        name = f"ggml-{name}"
    name = Path(name).name
    if not re.fullmatch(r"[A-Za-z0-9._-]+", name):
        raise ValueError(f"Model filename contains unsupported characters: {model!r}")
    return name


def _download(url: str, dest_path: Path) -> None:
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest_path.with_suffix(dest_path.suffix + ".tmp")
    if tmp_path.exists():
        tmp_path.unlink()

    try:
        with urllib.request.urlopen(url) as resp, tmp_path.open("wb") as out:
            shutil.copyfileobj(resp, out)
    except (urllib.error.HTTPError, urllib.error.URLError) as exc:
        raise RuntimeError(f"Failed to download {url}: {exc}") from exc

    tmp_path.replace(dest_path)


def _resolve_output_dir(raw_output_dir: str) -> Path:
    if raw_output_dir:
        return Path(raw_output_dir).expanduser().resolve(strict=False)
    return _default_output_dir().expanduser().resolve(strict=False)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Download a whisper.cpp GGML model file into a predictable local cache directory."
    )
    parser.add_argument(
        "--model",
        default="large-v3",
        help="Model name (e.g. large-v3, base.en, ggml-large-v3.bin). Default: %(default)s",
    )
    parser.add_argument(
        "--output-dir",
        default="",
        help="Where to store the model file. Default: $WHISPERCPP_MODEL_DIR or $REFRAME_MEDIA_ROOT/models/whispercpp or .tools/models/whispercpp",
    )
    parser.add_argument(
        "--base-url",
        default="https://huggingface.co/ggerganov/whisper.cpp/resolve/main",
        help="Base URL for model downloads. Must be HTTPS and hosted on Hugging Face. Default: %(default)s",
    )
    parser.add_argument("--force", action="store_true", help="Re-download even if the file already exists.")
    args = parser.parse_args(argv)

    try:
        filename = _normalize_filename(args.model)
        output_dir = _resolve_output_dir(args.output_dir)
        base_url = normalize_https_url(args.base_url, allowed_hosts=ALLOWED_MODEL_HOSTS)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    dest_path = output_dir / filename
    url = f"{base_url.rstrip('/')}/{filename}"

    if dest_path.exists() and not args.force:
        print(f"Already present: {dest_path}")
        return 0

    print(f"Downloading whisper.cpp model: {filename}")
    print(f"  URL:  {url}")
    print(f"  Dest: {dest_path}")
    try:
        _download(url, dest_path)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print("Done.")
    print("")
    print("Tip:")
    print("  When using the whisper_cpp backend, set the model to the full path:")
    print(f"    {dest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
