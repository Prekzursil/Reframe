#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path


DEFAULT_CONFIG_PATH = Path("apps/desktop/src-tauri/tauri.conf.json")


def _fetch_bytes(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "reframe-updater-verify"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def _head(url: str) -> int:
    request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "reframe-updater-verify"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return getattr(response, "status", 200)


def _load_default_endpoint(config_path: Path) -> str:
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    endpoints = (((payload.get("plugins") or {}).get("updater") or {}).get("endpoints") or [])
    if not endpoints:
        raise ValueError(f"No updater endpoints found in {config_path}")
    if not isinstance(endpoints[0], str) or not endpoints[0]:
        raise ValueError(f"Invalid updater endpoint: {endpoints[0]!r}")
    return endpoints[0]


def _require_field(obj: dict, key: str) -> str:
    value = obj.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Missing/invalid field {key!r}: {value!r}")
    return value


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Verify Tauri updater 'latest.json' and asset URLs.")
    parser.add_argument("--endpoint", help="Updater JSON URL. Defaults to the first endpoint in tauri.conf.json.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to tauri.conf.json (default: %(default)s)")
    args = parser.parse_args(argv)

    config_path = Path(args.config)
    endpoint = args.endpoint
    if not endpoint:
        if not config_path.is_file():
            raise FileNotFoundError(config_path)
        endpoint = _load_default_endpoint(config_path)

    print(f"Fetching updater JSON: {endpoint}")
    latest_bytes = _fetch_bytes(endpoint)
    latest = json.loads(latest_bytes.decode("utf-8"))

    version = _require_field(latest, "version")
    pub_date = _require_field(latest, "pub_date")
    print(f"version={version} pub_date={pub_date}")

    platforms = latest.get("platforms")
    if not isinstance(platforms, dict) or not platforms:
        raise ValueError(f"Missing/invalid 'platforms': {platforms!r}")

    failures: list[str] = []
    for platform_key, platform_meta in platforms.items():
        if not isinstance(platform_key, str) or not platform_key:
            failures.append(f"Invalid platform key: {platform_key!r}")
            continue
        if not isinstance(platform_meta, dict):
            failures.append(f"{platform_key}: invalid platform object: {platform_meta!r}")
            continue
        try:
            url = _require_field(platform_meta, "url")
            signature = _require_field(platform_meta, "signature")
            if len(signature) < 20:
                failures.append(f"{platform_key}: signature looks too short")
            status = _head(url)
            if status >= 400:
                failures.append(f"{platform_key}: URL not accessible (status={status}): {url}")
            else:
                print(f"ok {platform_key}: {url}")
        except Exception as exc:  # noqa: BLE001 - report all validation failures
            failures.append(f"{platform_key}: {exc}")

    if failures:
        print("\nFAILURES:", file=sys.stderr)
        for line in failures:
            print(f"- {line}", file=sys.stderr)
        return 1

    print("\nOK: updater JSON looks valid and all platform URLs are reachable.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except urllib.error.HTTPError as exc:
        print(f"HTTP error: {exc.code} {exc.reason}", file=sys.stderr)
        raise SystemExit(2)
    except urllib.error.URLError as exc:
        print(f"Network error: {exc.reason}", file=sys.stderr)
        raise SystemExit(2)

