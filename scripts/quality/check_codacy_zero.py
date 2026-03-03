#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
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
CODACY_API_BASE = "https://api.codacy.com"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Assert Codacy has zero total open issues.")
    parser.add_argument("--provider", default="gh", help="Organization provider, for example gh")
    parser.add_argument("--owner", required=True, help="Repository owner")
    parser.add_argument("--repo", required=True, help="Repository name")
    parser.add_argument("--token", default="", help="Codacy API token (falls back to CODACY_API_TOKEN env)")
    parser.add_argument("--out-json", default="codacy-zero/codacy.json", help="Output JSON path")
    parser.add_argument("--out-md", default="codacy-zero/codacy.md", help="Output markdown path")
    return parser.parse_args()


def _request_json(url: str, token: str, *, method: str = "GET", data: dict[str, Any] | None = None) -> dict[str, Any]:
    safe_url = normalize_https_url(url, allowed_host_suffixes={"codacy.com"}).rstrip("/")
    body = None
    headers = {
        "Accept": "application/json",
        "api-token": token,
        "User-Agent": "reframe-codacy-zero-gate",
    }
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        safe_url,
        headers=headers,
        method=method,
        data=body,
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
    token = (args.token or os.environ.get("CODACY_API_TOKEN", "")).strip()
    api_base = normalize_https_url(CODACY_API_BASE, allowed_hosts={"api.codacy.com"}).rstrip("/")
    owner = urllib.parse.quote(args.owner.strip(), safe="")
    repo = urllib.parse.quote(args.repo.strip(), safe="")

    findings: list[str] = []
    open_issues: int | None = None

    if not token:
        findings.append("CODACY_API_TOKEN is missing.")
        status = "fail"
    else:
        query = urllib.parse.urlencode({"limit": "1"})
        provider_candidates = [args.provider, "gh", "github"]
        provider_candidates = list(dict.fromkeys(p for p in provider_candidates if p))

        last_exc: Exception | None = None
        for provider in provider_candidates:
            url = (
                f"{api_base}/api/v3/analysis/organizations/{provider}/"
                f"{owner}/repositories/{repo}/issues/search?{query}"
            )
            try:
                payload = _request_json(url, token, method="POST", data={})
                open_issues = extract_total_open(payload)
                if open_issues is None:
                    findings.append("Codacy response did not include a parseable total issue count.")
                elif open_issues != 0:
                    findings.append(f"Codacy reports {open_issues} open issues (expected 0).")
                status = "pass" if not findings else "fail"
                break
            except urllib.error.HTTPError as exc:
                last_exc = exc
                if exc.code == 404:
                    continue
                findings.append(f"Codacy API request failed: HTTP {exc.code}")
                status = "fail"
                break
            except Exception as exc:  # pragma: no cover - network/runtime surface
                last_exc = exc
                findings.append(f"Codacy API request failed: {exc}")
                status = "fail"
                break
        else:
            findings.append(
                f"Codacy API endpoint was not found for provider(s): {', '.join(provider_candidates)}."
            )
            if last_exc is not None:
                findings.append(f"Last Codacy API error: {last_exc}")
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

    try:
        out_json = _safe_output_path(args.out_json, "codacy-zero/codacy.json")
        out_md = _safe_output_path(args.out_md, "codacy-zero/codacy.md")
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
