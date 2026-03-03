#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
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

SONAR_API_BASE = "https://sonarcloud.io"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Assert SonarCloud has zero open issues and a passing quality gate.")
    parser.add_argument("--project-key", required=True, help="Sonar project key")
    parser.add_argument("--token", default="", help="Sonar token (falls back to SONAR_TOKEN env)")
    parser.add_argument("--branch", default="", help="Optional branch scope")
    parser.add_argument("--pull-request", default="", help="Optional PR scope")
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


def _render_md(payload: dict) -> str:
    lines = [
        "# Sonar Zero Gate",
        "",
        f"- Status: `{payload['status']}`",
        f"- Project: `{payload['project_key']}`",
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

    findings: list[str] = []
    open_issues: int | None = None
    quality_gate: str | None = None

    if not token:
        findings.append("SONAR_TOKEN is missing.")
        status = "fail"
    else:
        auth = _auth_header(token)
        try:
            issues_query = {
                "componentKeys": args.project_key,
                "resolved": "false",
                "ps": "1",
            }
            if args.branch:
                issues_query["branch"] = args.branch
            if args.pull_request:
                issues_query["pullRequest"] = args.pull_request

            issues_url = f"{api_base}/api/issues/search?{urllib.parse.urlencode(issues_query)}"
            issues_payload = _request_json(issues_url, auth)
            paging = issues_payload.get("paging") or {}
            open_issues = int(paging.get("total") or 0)

            gate_query = {"projectKey": args.project_key}
            if args.branch:
                gate_query["branch"] = args.branch
            if args.pull_request:
                gate_query["pullRequest"] = args.pull_request
            gate_url = f"{api_base}/api/qualitygates/project_status?{urllib.parse.urlencode(gate_query)}"
            gate_payload = _request_json(gate_url, auth)
            project_status = (gate_payload.get("projectStatus") or {})
            quality_gate = str(project_status.get("status") or "UNKNOWN")

            if open_issues != 0:
                findings.append(f"Sonar reports {open_issues} open issues (expected 0).")
            if quality_gate != "OK":
                findings.append(f"Sonar quality gate status is {quality_gate} (expected OK).")

            status = "pass" if not findings else "fail"
        except Exception as exc:  # pragma: no cover - network/runtime surface
            status = "fail"
            findings.append(f"Sonar API request failed: {exc}")

    payload = {
        "status": status,
        "project_key": args.project_key,
        "open_issues": open_issues,
        "quality_gate": quality_gate,
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
