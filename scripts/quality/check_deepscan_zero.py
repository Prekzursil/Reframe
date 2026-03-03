#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SCRIPT_DIR = Path(__file__).resolve().parent
_HELPER_ROOT = _SCRIPT_DIR if (_SCRIPT_DIR / "security_helpers.py").exists() else _SCRIPT_DIR.parent
if str(_HELPER_ROOT) not in sys.path:
    sys.path.insert(0, str(_HELPER_ROOT))

from security_helpers import normalize_https_url

TOTAL_KEYS = {"total", "totalItems", "total_items", "count", "hits", "open_issues"}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Assert DeepScan has zero total open issues.")
    parser.add_argument("--token", default="", help="DeepScan API token (falls back to DEEPSCAN_API_TOKEN env)")
    parser.add_argument("--out-json", default="deepscan-zero/deepscan.json", help="Output JSON path")
    parser.add_argument("--out-md", default="deepscan-zero/deepscan.md", help="Output markdown path")
    return parser.parse_args()


def extract_total_open(payload: Any) -> int | None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in TOTAL_KEYS and isinstance(value, (int, float)):
                return int(value)
        for nested in payload.values():
            total = extract_total_open(nested)
            if total is not None:
                return total
    elif isinstance(payload, list):
        for nested in payload:
            total = extract_total_open(nested)
            if total is not None:
                return total
    return None


def _request_json(url: str, token: str) -> dict[str, Any]:
    safe_url = normalize_https_url(url, allowed_host_suffixes={"deepscan.io"})
    req = urllib.request.Request(
        safe_url,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "reframe-deepscan-zero-gate",
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _render_md(payload: dict) -> str:
    lines = [
        "# DeepScan Zero Gate",
        "",
        f"- Status: `{payload['status']}`",
        f"- Open issues: `{payload.get('open_issues')}`",
        f"- Source URL: `{payload.get('open_issues_url') or 'n/a'}`",
        f"- Timestamp (UTC): `{payload['timestamp_utc']}`",
        "",
        "## Findings",
    ]
    findings = payload.get("findings") or []
    if findings:
        lines.extend(f"- {item}" for item in findings)
    else:
        lines.append("- None")
    return "\n".join(lines) + "\n"


def _safe_output_path(raw: str, fallback: str, base: Path | None = None) -> Path:
    root = (base or Path.cwd()).resolve()
    candidate = Path((raw or "").strip() or fallback).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Output path escapes workspace root: {candidate}") from exc
    return resolved


def main() -> int:
    import os

    args = _parse_args()
    token = (args.token or os.environ.get("DEEPSCAN_API_TOKEN", "")).strip()
    open_issues_url = os.environ.get("DEEPSCAN_OPEN_ISSUES_URL", "").strip()

    findings: list[str] = []
    open_issues: int | None = None

    if not token:
        findings.append("DEEPSCAN_API_TOKEN is missing.")
    if not open_issues_url:
        findings.append("DEEPSCAN_OPEN_ISSUES_URL is missing.")
    else:
        try:
            open_issues_url = normalize_https_url(
                open_issues_url,
                allowed_host_suffixes={"deepscan.io"},
            )
        except ValueError as exc:
            findings.append(str(exc))

    status = "fail"
    if not findings:
        try:
            payload = _request_json(open_issues_url, token)
            open_issues = extract_total_open(payload)
            if open_issues is None:
                findings.append("DeepScan response did not include a parseable total issue count.")
            elif open_issues != 0:
                findings.append(f"DeepScan reports {open_issues} open issues (expected 0).")
            status = "pass" if not findings else "fail"
        except Exception as exc:  # pragma: no cover - network/runtime surface
            findings.append(f"DeepScan API request failed: {exc}")
            status = "fail"

    payload = {
        "status": status,
        "open_issues": open_issues,
        "open_issues_url": open_issues_url,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "findings": findings,
    }

    try:
        out_json = _safe_output_path(args.out_json, "deepscan-zero/deepscan.json")
        out_md = _safe_output_path(args.out_md, "deepscan-zero/deepscan.md")
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    out_md.write_text(_render_md(payload), encoding="utf-8")
    print(out_md.read_text(encoding="utf-8"), end="")
    return 0 if status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
