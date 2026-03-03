#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import sys
import time
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

SONAR_API_BASE = "https://sonarcloud.io"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Assert SonarCloud has zero actionable open issues.")
    parser.add_argument("--project-key", required=True, help="Sonar project key")
    parser.add_argument("--token", default="", help="Sonar token (falls back to SONAR_TOKEN env)")
    parser.add_argument("--branch", default="", help="Optional branch scope")
    parser.add_argument("--pull-request", default="", help="Optional PR scope")
    parser.add_argument(
        "--wait-seconds",
        type=int,
        default=120,
        help="Maximum time to wait for Sonar PR issue counts to settle.",
    )
    parser.add_argument(
        "--require-quality-gate",
        action="store_true",
        help="Require Sonar quality gate status to be OK in addition to open issues == 0",
    )
    parser.add_argument(
        "--ignore-open-issues",
        action="store_true",
        help="Skip open-issue enforcement and evaluate quality gate only.",
    )
    parser.add_argument("--out-json", default="sonar-zero/sonar.json", help="Output JSON path")
    parser.add_argument("--out-md", default="sonar-zero/sonar.md", help="Output markdown path")
    return parser.parse_args()


def _auth_header(token: str) -> str:
    raw = f"{token}:".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("ascii")


def _request_json(url: str, auth_header: str) -> dict[str, Any]:
    safe_url = normalize_https_url(url, allowed_host_suffixes={"sonarcloud.io"}).rstrip("/")
    request = urllib.request.Request(
        safe_url,
        headers={
            "Accept": "application/json",
            "Authorization": auth_header,
            "User-Agent": "reframe-sonar-zero-gate",
        },
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _query_sonar_status(
    *,
    api_base: str,
    auth: str,
    project_key: str,
    branch: str,
    pull_request: str,
) -> tuple[int, str]:
    issues_query = {
        "componentKeys": project_key,
        "resolved": "false",
        "ps": "1",
    }
    if branch:
        issues_query["branch"] = branch
    if pull_request:
        issues_query["pullRequest"] = pull_request

    issues_url = f"{api_base}/api/issues/search?{urllib.parse.urlencode(issues_query)}"
    issues_payload = _request_json(issues_url, auth)
    paging = issues_payload.get("paging") or {}
    open_issues = int(paging.get("total") or 0)

    gate_query = {"projectKey": project_key}
    if branch:
        gate_query["branch"] = branch
    if pull_request:
        gate_query["pullRequest"] = pull_request
    gate_url = f"{api_base}/api/qualitygates/project_status?{urllib.parse.urlencode(gate_query)}"
    gate_payload = _request_json(gate_url, auth)
    project_status = (gate_payload.get("projectStatus") or {})
    quality_gate = str(project_status.get("status") or "UNKNOWN")
    return open_issues, quality_gate


def evaluate_status(
    *,
    open_issues: int,
    quality_gate: str,
    require_quality_gate: bool,
    ignore_open_issues: bool,
) -> list[str]:
    findings: list[str] = []
    if not ignore_open_issues and open_issues != 0:
        findings.append(f"Sonar reports {open_issues} open issues (expected 0).")
    if require_quality_gate and quality_gate != "OK":
        findings.append(f"Sonar quality gate status is {quality_gate} (expected OK).")
    return findings


def _render_md(payload: dict) -> str:
    scope = payload.get("scope", "project")
    lines = [
        "# Sonar Zero Gate",
        "",
        f"- Status: `{payload['status']}`",
        f"- Project: `{payload['project_key']}`",
        f"- Scope: `{scope}`",
        f"- Branch: `{payload.get('branch')}`",
        f"- Pull request: `{payload.get('pull_request')}`",
        f"- Open issues: `{payload.get('open_issues')}`",
        f"- Quality gate: `{payload.get('quality_gate')}`",
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
    token = (args.token or os.environ.get("SONAR_TOKEN", "")).strip()
    api_base = normalize_https_url(SONAR_API_BASE, allowed_hosts={"sonarcloud.io"}).rstrip("/")

    scope = "project"
    if args.pull_request:
        scope = "pull_request"
    elif args.branch:
        scope = "branch"
    findings: list[str] = []
    open_issues: int | None = None
    quality_gate: str | None = None

    if not token:
        findings.append("SONAR_TOKEN is missing.")
        status = "fail"
    else:
        auth = _auth_header(token)
        try:
            open_issues, quality_gate = _query_sonar_status(
                api_base=api_base,
                auth=auth,
                project_key=args.project_key,
                branch=args.branch,
                pull_request=args.pull_request,
            )
            quality_gate = quality_gate or "UNKNOWN"

            if args.pull_request and open_issues != 0 and args.wait_seconds > 0:
                deadline = time.time() + max(0, args.wait_seconds)
                while open_issues != 0 and time.time() < deadline:
                    time.sleep(10)
                    open_issues, quality_gate = _query_sonar_status(
                        api_base=api_base,
                        auth=auth,
                        project_key=args.project_key,
                        branch=args.branch,
                        pull_request=args.pull_request,
                    )
                    quality_gate = quality_gate or "UNKNOWN"

            findings.extend(
                evaluate_status(
                    open_issues=open_issues,
                    quality_gate=quality_gate,
                    require_quality_gate=args.require_quality_gate,
                    ignore_open_issues=args.ignore_open_issues,
                )
            )

            status = "pass" if not findings else "fail"
        except Exception as exc:  # pragma: no cover - network/runtime surface
            status = "fail"
            findings.append(f"Sonar API request failed: {exc}")

    payload = {
        "status": status,
        "project_key": args.project_key,
        "scope": scope,
        "branch": args.branch or None,
        "pull_request": args.pull_request or None,
        "open_issues": open_issues,
        "quality_gate": quality_gate,
        "ignore_open_issues": bool(args.ignore_open_issues),
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "findings": findings,
    }

    try:
        out_json = _safe_output_path(args.out_json, "sonar-zero/sonar.json")
        out_md = _safe_output_path(args.out_md, "sonar-zero/sonar.md")
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
