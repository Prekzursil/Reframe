#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Assert Percy/Applitools visual checks are zero-diff.")
    parser.add_argument("--provider", choices=["percy", "applitools"], required=True)
    parser.add_argument("--sha", default="", help="Commit SHA for Percy lookup (defaults to GITHUB_SHA)")
    parser.add_argument("--branch", default="", help="Optional branch for Percy filter")
    parser.add_argument("--percy-token", default="", help="Percy token (falls back to PERCY_TOKEN env)")
    parser.add_argument("--applitools-results", default="", help="Path to Applitools results JSON")
    parser.add_argument("--out-json", default="visual-zero/visual.json", help="Output JSON path")
    parser.add_argument("--out-md", default="visual-zero/visual.md", help="Output markdown path")
    return parser.parse_args()


def _percy_request(path: str, token: str, query: dict[str, str] | None = None) -> dict[str, Any]:
    suffix = ""
    if query:
        suffix = "?" + urllib.parse.urlencode(query)
    req = urllib.request.Request(
        f"https://percy.io/api/v1{path}{suffix}",
        headers={
            "Accept": "application/json",
            "Authorization": f"Token token={token}",
            "User-Agent": "reframe-visual-zero-gate",
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _select_latest_build(payload: dict[str, Any]) -> dict[str, Any] | None:
    data = payload.get("data")
    if not isinstance(data, list):
        return None
    builds = [item for item in data if isinstance(item, dict)]
    if not builds:
        return None
    builds.sort(key=lambda item: str((item.get("attributes") or {}).get("created-at") or ""), reverse=True)
    return builds[0]


def _parse_percy_diff_count(attrs: dict[str, Any]) -> int | None:
    for key in (
        "total-comparisons-unreviewed",
        "total-comparisons-diff",
        "total-comparisons-changed",
        "total-comparisons-with-diff",
    ):
        value = attrs.get(key)
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    return None


def _run_percy(args: argparse.Namespace) -> tuple[str, dict[str, Any], list[str]]:
    token = (args.percy_token or os.environ.get("PERCY_TOKEN", "")).strip()
    sha = (args.sha or os.environ.get("GITHUB_SHA", "")).strip()
    branch = (args.branch or os.environ.get("GITHUB_HEAD_REF") or os.environ.get("GITHUB_REF_NAME", "")).strip()

    findings: list[str] = []
    details: dict[str, Any] = {"sha": sha, "branch": branch, "build_id": None, "review_state": None, "diff_count": None}

    if not token:
        findings.append("PERCY_TOKEN is missing.")
        return "fail", details, findings
    if not sha:
        findings.append("Commit SHA is missing for Percy lookup.")
        return "fail", details, findings

    payload = _percy_request(
        "/builds",
        token,
        query={
            "filter[sha]": sha,
            "filter[state]": "finished",
            "filter[branch]": branch,
            "page[limit]": "25",
        },
    )
    build = _select_latest_build(payload)
    if not build:
        findings.append("Percy returned no finished build for the target SHA/branch.")
        return "fail", details, findings

    attrs = build.get("attributes") if isinstance(build.get("attributes"), dict) else {}
    review_state = str(attrs.get("review-state") or "unknown")
    diff_count = _parse_percy_diff_count(attrs)

    details["build_id"] = build.get("id")
    details["review_state"] = review_state
    details["diff_count"] = diff_count

    if review_state != "approved":
        findings.append(f"Percy review-state is {review_state} (expected approved).")
    if diff_count is None:
        findings.append("Percy build did not expose a parseable unresolved-diff count.")
    elif diff_count != 0:
        findings.append(f"Percy reports {diff_count} unresolved visual diffs (expected 0).")

    return ("pass" if not findings else "fail"), details, findings


def _run_applitools(args: argparse.Namespace) -> tuple[str, dict[str, Any], list[str]]:
    findings: list[str] = []
    results_path = Path(args.applitools_results or "").expanduser()
    details: dict[str, Any] = {
        "results_path": str(results_path) if args.applitools_results else "",
        "unresolved": None,
        "mismatches": None,
        "missing": None,
    }

    if not args.applitools_results:
        findings.append("--applitools-results is required for provider=applitools.")
        return "fail", details, findings
    if not results_path.exists():
        findings.append(f"Applitools results file not found: {results_path}")
        return "fail", details, findings

    payload = json.loads(results_path.read_text(encoding="utf-8"))
    unresolved = payload.get("unresolved")
    mismatches = payload.get("mismatches")
    missing = payload.get("missing")

    details["unresolved"] = unresolved
    details["mismatches"] = mismatches
    details["missing"] = missing

    for key, value in (("unresolved", unresolved), ("mismatches", mismatches), ("missing", missing)):
        if value is None:
            findings.append(f"Applitools results missing '{key}' field.")
        elif int(value) != 0:
            findings.append(f"Applitools reports {key}={value} (expected 0).")

    return ("pass" if not findings else "fail"), details, findings


def _render_md(payload: dict[str, Any]) -> str:
    lines = [
        "# Visual Zero Gate",
        "",
        f"- Provider: `{payload['provider']}`",
        f"- Status: `{payload['status']}`",
        f"- Timestamp (UTC): `{payload['timestamp_utc']}`",
        "",
        "## Details",
    ]

    for key, value in (payload.get("details") or {}).items():
        lines.append(f"- `{key}`: `{value}`")

    lines.extend(["", "## Findings"])
    findings = payload.get("findings") or []
    if findings:
        lines.extend(f"- {item}" for item in findings)
    else:
        lines.append("- None")

    return "\n".join(lines) + "\n"


def main() -> int:
    args = _parse_args()

    if args.provider == "percy":
        status, details, findings = _run_percy(args)
    else:
        status, details, findings = _run_applitools(args)

    payload = {
        "provider": args.provider,
        "status": status,
        "details": details,
        "findings": findings,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
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
