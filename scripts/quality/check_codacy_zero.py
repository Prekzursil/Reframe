#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


TOTAL_KEYS = {"total", "totalItems", "total_items", "count", "hits", "open_issues"}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Assert Codacy has zero total open issues.")
    parser.add_argument("--api-base", default="https://api.codacy.com", help="Codacy API base")
    parser.add_argument("--provider", default="gh", help="Organization provider, for example gh")
    parser.add_argument("--owner", required=True, help="Repository owner")
    parser.add_argument("--repo", required=True, help="Repository name")
    parser.add_argument("--token", default="", help="Codacy API token (falls back to CODACY_API_TOKEN env)")
    parser.add_argument("--out-json", default="codacy-zero/codacy.json", help="Output JSON path")
    parser.add_argument("--out-md", default="codacy-zero/codacy.md", help="Output markdown path")
    return parser.parse_args()


def _request_json(url: str, token: str) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "api-token": token,
            "User-Agent": "reframe-codacy-zero-gate",
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def extract_total_open(payload: Any) -> int | None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in TOTAL_KEYS and isinstance(value, (int, float)):
                return int(value)

        # common pagination structures
        for key in ("pagination", "page", "meta"):
            nested = payload.get(key)
            total = extract_total_open(nested)
            if total is not None:
                return total

        for value in payload.values():
            total = extract_total_open(value)
            if total is not None:
                return total

    if isinstance(payload, list):
        for item in payload:
            total = extract_total_open(item)
            if total is not None:
                return total

    return None


def _render_md(payload: dict) -> str:
    lines = [
        "# Codacy Zero Gate",
        "",
        f"- Status: `{payload['status']}`",
        f"- Owner/repo: `{payload['owner']}/{payload['repo']}`",
        f"- Open issues: `{payload.get('open_issues')}`",
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


def main() -> int:
    import os

    args = _parse_args()
    token = (args.token or os.environ.get("CODACY_API_TOKEN", "")).strip()

    findings: list[str] = []
    open_issues: int | None = None

    if not token:
        findings.append("CODACY_API_TOKEN is missing.")
        status = "fail"
    else:
        query = urllib.parse.urlencode({"status": "Open", "limit": "1"})
        url = (
            f"{args.api_base.rstrip('/')}/api/v3/analysis/organizations/{args.provider}/"
            f"{args.owner}/repositories/{args.repo}/issues?{query}"
        )
        try:
            payload = _request_json(url, token)
            open_issues = extract_total_open(payload)
            if open_issues is None:
                findings.append("Codacy response did not include a parseable total issue count.")
            elif open_issues != 0:
                findings.append(f"Codacy reports {open_issues} open issues (expected 0).")
            status = "pass" if not findings else "fail"
        except Exception as exc:  # pragma: no cover - network/runtime surface
            findings.append(f"Codacy API request failed: {exc}")
            status = "fail"

    payload = {
        "status": status,
        "owner": args.owner,
        "repo": args.repo,
        "provider": args.provider,
        "open_issues": open_issues,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "findings": findings,
    }

    out_json = Path(args.out_json)
    out_md = Path(args.out_md)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    out_md.write_text(_render_md(payload), encoding="utf-8")
    print(out_md.read_text(encoding="utf-8"), end="")
    return 0 if status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
