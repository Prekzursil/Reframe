#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


@dataclass
class AuditResult:
    status: str
    findings: list[str]
    missing_status_checks: list[str]
    observed_reviews: int | None
    observed_linear_history: bool | None
    observed_conversation_resolution: bool | None
    http_status: int | None = None
    http_error: str | None = None


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _classify_http_status(status_code: int) -> str:
    if status_code in {401, 403, 404}:
        return "inconclusive_permissions"
    return "api_error"


def _evaluate_required_reviews(
    *,
    findings: list[str],
    reviews_payload: dict[str, Any],
    required_reviews: int,
) -> int | None:
    observed_reviews_raw = reviews_payload.get("required_approving_review_count")
    if observed_reviews_raw is None:
        findings.append(f"Required approving review count is below policy ({observed_reviews_raw!r} < {required_reviews}).")
        return None
    observed_reviews = int(observed_reviews_raw)
    if observed_reviews < required_reviews:
        findings.append(f"Required approving review count is below policy ({observed_reviews!r} < {required_reviews}).")
    return observed_reviews


def _evaluate_bool_control(
    *,
    findings: list[str],
    payload: dict[str, Any],
    required: bool,
    failure_message: str,
) -> bool | None:
    observed = bool(payload.get("enabled")) if payload else None
    if required and observed is not True:
        findings.append(failure_message)
    return observed


def evaluate_protection_payload(protection: dict[str, Any], policy: dict[str, Any]) -> AuditResult:
    findings: list[str] = []

    required_reviews = int(policy.get("required_approving_review_count", 1))
    required_checks = list(policy.get("required_status_checks", []))
    require_linear_history = bool(policy.get("require_linear_history", True))
    require_conversation_resolution = bool(policy.get("require_conversation_resolution", True))

    reviews = protection.get("required_pull_request_reviews") or {}
    checks = protection.get("required_status_checks") or {}
    linear_history = protection.get("required_linear_history") or {}
    conversation_resolution = protection.get("required_conversation_resolution") or {}

    observed_reviews = _evaluate_required_reviews(
        findings=findings,
        reviews_payload=reviews,
        required_reviews=required_reviews,
    )

    contexts = checks.get("contexts") or []
    missing_checks = [name for name in required_checks if name not in contexts]
    for check in missing_checks:
        findings.append(f"Missing required status check: {check}")

    observed_linear_history = _evaluate_bool_control(
        findings=findings,
        payload=linear_history,
        required=require_linear_history,
        failure_message="Linear history is disabled.",
    )
    observed_conversation_resolution = _evaluate_bool_control(
        findings=findings,
        payload=conversation_resolution,
        required=require_conversation_resolution,
        failure_message="Conversation resolution is disabled.",
    )

    status = "pass" if not findings else "fail"
    return AuditResult(
        status=status,
        findings=findings,
        missing_status_checks=missing_checks,
        observed_reviews=observed_reviews,
        observed_linear_history=observed_linear_history,
        observed_conversation_resolution=observed_conversation_resolution,
    )


def _fetch_protection(api_base: str, repo: str, branch: str, token: str) -> dict[str, Any]:
    url = f"{api_base.rstrip('/')}/repos/{repo}/branches/{branch}/protection"
    req = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "reframe-branch-protection-audit",
        },
        method="GET",
    )
    with urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _render_markdown(result_payload: dict[str, Any]) -> str:
    lines = [
        "# Branch Protection Audit",
        "",
        f"- Status: `{result_payload['status']}`",
        f"- Repo: `{result_payload['repo']}`",
        f"- Branch: `{result_payload['branch']}`",
        f"- Timestamp (UTC): `{result_payload['timestamp_utc']}`",
        "",
        "## Findings",
    ]

    findings = result_payload.get("findings") or []
    if findings:
        lines.extend(f"- {item}" for item in findings)
    else:
        lines.append("- None")

    if result_payload.get("http_status") is not None:
        lines.extend(
            [
                "",
                "## API Error",
                f"- HTTP status: `{result_payload['http_status']}`",
                f"- Message: `{result_payload.get('http_error') or ''}`",
            ]
        )

    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit GitHub main branch protection against policy.")
    parser.add_argument("--repo", required=True, help="GitHub repository in owner/repo format")
    parser.add_argument("--branch", default="main", help="Branch to audit (default: main)")
    parser.add_argument("--policy", default="docs/branch-protection-policy.json", help="Policy JSON path")
    parser.add_argument("--out-json", required=True, help="Output JSON file path")
    parser.add_argument("--out-md", required=True, help="Output markdown file path")
    parser.add_argument("--api-base", default="https://api.github.com", help="GitHub API base URL")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    policy_path = Path(args.policy)
    out_json_path = Path(args.out_json)
    out_md_path = Path(args.out_md)

    policy = _load_json(policy_path)

    token = (os.environ.get("GITHUB_TOKEN") or "").strip() or (os.environ.get("GH_TOKEN") or "").strip()

    now = datetime.now(timezone.utc).isoformat()

    if not token:
        result = AuditResult(
            status="inconclusive_permissions",
            findings=["GitHub token is missing; branch protection could not be audited."],
            missing_status_checks=[],
            observed_reviews=None,
            observed_linear_history=None,
            observed_conversation_resolution=None,
        )
    else:
        try:
            protection = _fetch_protection(args.api_base, args.repo, args.branch, token)
            result = evaluate_protection_payload(protection, policy)
        except HTTPError as exc:
            message = exc.read().decode("utf-8", errors="replace")[:1000]
            status = _classify_http_status(exc.code)
            if status == "inconclusive_permissions":
                findings = [
                    f"Branch protection API inaccessible for `{args.branch}` (HTTP {exc.code}); permission scope may be insufficient."
                ]
            else:
                findings = [
                    f"Branch protection API request failed for `{args.branch}` (HTTP {exc.code})."
                ]
            result = AuditResult(
                status=status,
                findings=findings,
                missing_status_checks=[],
                observed_reviews=None,
                observed_linear_history=None,
                observed_conversation_resolution=None,
                http_status=exc.code,
                http_error=message,
            )
        except URLError as exc:
            result = AuditResult(
                status="api_error",
                findings=["Network error while requesting branch protection API."],
                missing_status_checks=[],
                observed_reviews=None,
                observed_linear_history=None,
                observed_conversation_resolution=None,
                http_error=str(exc.reason),
            )

    payload = {
        "status": result.status,
        "repo": args.repo,
        "branch": args.branch,
        "timestamp_utc": now,
        "policy": {
            "required_approving_review_count": int(policy.get("required_approving_review_count", 1)),
            "required_status_checks": list(policy.get("required_status_checks", [])),
            "require_linear_history": bool(policy.get("require_linear_history", True)),
            "require_conversation_resolution": bool(policy.get("require_conversation_resolution", True)),
        },
        "findings": result.findings,
        "missing_status_checks": result.missing_status_checks,
        "observed": {
            "required_approving_review_count": result.observed_reviews,
            "linear_history": result.observed_linear_history,
            "conversation_resolution": result.observed_conversation_resolution,
        },
        "http_status": result.http_status,
        "http_error": result.http_error,
    }

    out_json_path.parent.mkdir(parents=True, exist_ok=True)
    out_md_path.parent.mkdir(parents=True, exist_ok=True)

    out_json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    out_md_path.write_text(_render_markdown(payload), encoding="utf-8")

    # fail only on deterministic policy non-compliance or hard API error
    if result.status in {"fail", "api_error"}:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
