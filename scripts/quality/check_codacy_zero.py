#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
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
REPO_PART_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Assert Codacy has zero actionable open issues.")
    parser.add_argument("--repo", default="", help="Repository slug owner/repo (defaults to GITHUB_REPOSITORY)")
    parser.add_argument("--pull-request", default="", help="Optional pull request number to scope issue count")
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
    scope = payload.get("scope", "repository")
    lines = [
        "# Codacy Zero Gate",
        "",
        f"- Status: `{payload['status']}`",
        f"- Owner/repo: `{payload['owner']}/{payload['repo']}`",
        f"- Scope: `{scope}`",
        f"- Pull request: `{payload.get('pull_request')}`",
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
    args = _parse_args()
    token = os.environ.get("CODACY_API_TOKEN", "").strip()
    api_base = normalize_https_url(CODACY_API_BASE, allowed_hosts={"api.codacy.com"}).rstrip("/")
    pull_request = (args.pull_request or "").strip()

    repo_slug = (args.repo or os.environ.get("GITHUB_REPOSITORY", "")).strip()
    if not repo_slug or "/" not in repo_slug:
        print("Repository slug is missing; pass --repo or set GITHUB_REPOSITORY.", file=sys.stderr)
        return 1
    owner_raw, repo_raw = repo_slug.split("/", 1)
    if not REPO_PART_RE.fullmatch(owner_raw) or not REPO_PART_RE.fullmatch(repo_raw):
        print(f"Invalid repository slug: {repo_slug}", file=sys.stderr)
        return 1

    owner = urllib.parse.quote(owner_raw, safe="")
    repo = urllib.parse.quote(repo_raw, safe="")
    provider = "gh"

    scope = "pull_request" if pull_request else "repository"
    findings: list[str] = []
    open_issues: int | None = None

    if not token:
        findings.append("CODACY_API_TOKEN is missing.")
        status = "fail"
    elif pull_request and not pull_request.isdigit():
        findings.append(f"Invalid pull request number: {pull_request!r}")
        status = "fail"
    else:
        query = urllib.parse.urlencode({"limit": "1", "page": "1"})
        try:
            if pull_request:
                url = (
                    f"{api_base}/api/v3/analysis/organizations/{provider}/"
                    f"{owner}/repositories/{repo}/pull-requests/{urllib.parse.quote(pull_request, safe='')}/issues?{query}"
                )
                payload: dict[str, Any] = {}
                for _ in range(30):
                    payload = _request_json(url, token, method="GET")
                    if payload.get("analyzed") is False:
                        time.sleep(5)
                        continue
                    break
                open_issues = int((payload.get("pagination") or {}).get("total") or 0)
                if payload.get("analyzed") is False:
                    findings.append(f"Codacy PR {pull_request} is not analyzed yet after waiting.")
            else:
                url = (
                    f"{api_base}/api/v3/analysis/organizations/{provider}/"
                    f"{owner}/repositories/{repo}/issues/search?{query}"
                )
                payload = _request_json(url, token, method="POST", data={})
                open_issues = extract_total_open(payload)
                if open_issues is None:
                    findings.append("Codacy response did not include a parseable total issue count.")

            if open_issues is not None and open_issues != 0:
                if pull_request:
                    findings.append(f"Codacy reports {open_issues} open issues on PR #{pull_request} (expected 0).")
                else:
                    findings.append(f"Codacy reports {open_issues} open issues (expected 0).")
            status = "pass" if not findings else "fail"
        except urllib.error.HTTPError as exc:
            if pull_request:
                findings.append(f"Codacy API request failed for PR #{pull_request}: HTTP {exc.code}")
            else:
                findings.append(f"Codacy API request failed: HTTP {exc.code}")
            findings.append(f"Last Codacy API error: {exc}")
            status = "fail"
        except Exception as exc:  # pragma: no cover - network/runtime surface
            if pull_request:
                findings.append(f"Codacy API request failed for PR #{pull_request}: {exc}")
            else:
                findings.append(f"Codacy API request failed: {exc}")
            status = "fail"

    payload = {
        "status": status,
        "owner": owner_raw,
        "repo": repo_raw,
        "provider": provider,
        "scope": scope,
        "pull_request": pull_request or None,
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
