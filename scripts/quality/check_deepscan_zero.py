#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
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

GITHUB_API_BASE = "https://api.github.com"
NEW_ISSUES_RE = re.compile(r"(\d+)\s+new", re.IGNORECASE)
FIXED_ISSUES_RE = re.compile(r"(\d+)\s+fixed", re.IGNORECASE)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Assert DeepScan check reports zero new issues.")
    parser.add_argument("--out-json", default="deepscan-zero/deepscan.json", help="Output JSON path")
    parser.add_argument("--out-md", default="deepscan-zero/deepscan.md", help="Output markdown path")
    return parser.parse_args()


def _request_json(url: str, token: str) -> dict[str, Any]:
    safe_url = normalize_https_url(url, allowed_hosts={"api.github.com"}).rstrip("/")
    req = urllib.request.Request(
        safe_url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
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
        f"- Repo: `{payload.get('repo') or 'n/a'}`",
        f"- SHA: `{payload.get('sha') or 'n/a'}`",
        f"- Source: `{payload.get('source') or 'n/a'}`",
        f"- Check conclusion: `{payload.get('check_conclusion') or 'n/a'}`",
        f"- New issues: `{payload.get('new_issues')}`",
        f"- Fixed issues: `{payload.get('fixed_issues')}`",
        f"- Details URL: `{payload.get('details_url') or 'n/a'}`",
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


def extract_new_fixed_counts(summary: str) -> tuple[int | None, int | None]:
    new_match = NEW_ISSUES_RE.search(summary or "")
    fixed_match = FIXED_ISSUES_RE.search(summary or "")
    new_issues = int(new_match.group(1)) if new_match else None
    fixed_issues = int(fixed_match.group(1)) if fixed_match else None
    return new_issues, fixed_issues


def _latest_deepscan_check_run(check_runs: Any) -> dict[str, Any] | None:
    if not isinstance(check_runs, list):
        return None
    deep_runs = [item for item in check_runs if isinstance(item, dict) and str(item.get("name") or "") == "DeepScan"]
    deep_runs.sort(
        key=lambda item: (
            str(item.get("completed_at") or ""),
            str(item.get("started_at") or ""),
            int(item.get("id") or 0),
        ),
        reverse=True,
    )
    return deep_runs[0] if deep_runs else None


def _latest_deepscan_status(statuses: Any) -> dict[str, Any] | None:
    if not isinstance(statuses, list):
        return None
    deep_statuses = [
        item
        for item in statuses
        if isinstance(item, dict) and str(item.get("context") or "") == "DeepScan"
    ]
    deep_statuses.sort(
        key=lambda item: (
            str(item.get("updated_at") or ""),
            str(item.get("created_at") or ""),
            int(item.get("id") or 0),
        ),
        reverse=True,
    )
    return deep_statuses[0] if deep_statuses else None


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

    token = (os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or "").strip()
    repo_slug = (os.environ.get("GITHUB_REPOSITORY") or "").strip()
    sha = (os.environ.get("GITHUB_SHA") or "").strip()

    findings: list[str] = []
    check_conclusion: str | None = None
    details_url: str | None = None
    new_issues: int | None = None
    fixed_issues: int | None = None
    source: str | None = None

    if not token:
        findings.append("GITHUB_TOKEN (or GH_TOKEN) is missing.")
    if not repo_slug or "/" not in repo_slug:
        findings.append("GITHUB_REPOSITORY is missing or invalid.")
    if not sha:
        findings.append("GITHUB_SHA is missing.")

    status = "fail"
    if not findings:
        owner_raw, repo_raw = repo_slug.split("/", 1)
        owner = urllib.parse.quote(owner_raw, safe="")
        repo = urllib.parse.quote(repo_raw, safe="")
        sha_safe = urllib.parse.quote(sha, safe="")
        api_base = normalize_https_url(GITHUB_API_BASE, allowed_hosts={"api.github.com"}).rstrip("/")

        try:
            check_payload = _request_json(f"{api_base}/repos/{owner}/{repo}/commits/{sha_safe}/check-runs", token)
            latest_check_run = _latest_deepscan_check_run(check_payload.get("check_runs"))

            if latest_check_run is not None:
                source = "check_run"
                check_conclusion = str(latest_check_run.get("conclusion") or "")
                details_url = str(latest_check_run.get("details_url") or "") or None
                if check_conclusion != "success":
                    findings.append(f"DeepScan check conclusion is {check_conclusion or 'unknown'} (expected success).")

                output = latest_check_run.get("output") if isinstance(latest_check_run.get("output"), dict) else {}
                summary = str(output.get("summary") or "")
                new_issues, fixed_issues = extract_new_fixed_counts(summary)
            else:
                status_payload = _request_json(f"{api_base}/repos/{owner}/{repo}/commits/{sha_safe}/status", token)
                latest_status = _latest_deepscan_status(status_payload.get("statuses"))
                if latest_status is None:
                    findings.append("DeepScan status context is missing for this commit.")
                else:
                    source = "status_context"
                    state = str(latest_status.get("state") or "")
                    check_conclusion = "success" if state == "success" else state
                    details_url = str(latest_status.get("target_url") or "") or None
                    if state != "success":
                        findings.append(f"DeepScan status is {state or 'unknown'} (expected success).")

                    summary = str(latest_status.get("description") or "")
                    new_issues, fixed_issues = extract_new_fixed_counts(summary)

            if new_issues is None:
                findings.append("DeepScan summary did not include a parseable 'new issues' count.")
            elif new_issues != 0:
                findings.append(f"DeepScan reports {new_issues} new issues (expected 0).")

            status = "pass" if not findings else "fail"
        except Exception as exc:  # pragma: no cover - network/runtime surface
            findings.append(f"GitHub API request failed: {exc}")
            status = "fail"

    payload = {
        "status": status,
        "repo": repo_slug,
        "sha": sha,
        "source": source,
        "check_conclusion": check_conclusion,
        "details_url": details_url,
        "new_issues": new_issues,
        "fixed_issues": fixed_issues,
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
