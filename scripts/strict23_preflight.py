#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from security_helpers import normalize_https_url

PERMISSION_HTTP_CODES = {401, 403, 404}
DEFAULT_CANONICAL_CONTEXTS = [
    "Python API & worker checks",
    "Web build",
    "Analyze (actions)",
    "Analyze (javascript-typescript)",
    "Analyze (python)",
    "CodeQL",
    "CodeRabbit",
    "Coverage 100 Gate",
    "Codecov Analytics",
    "Quality Zero Gate",
    "SonarCloud Code Analysis",
    "Codacy Static Code Analysis",
    "DeepScan",
    "Semgrep Zero",
    "Percy Visual",
    "Applitools Visual",
    "BrowserStack E2E",
    "Sentry Zero",
]


@dataclass
class PreflightResult:
    status: str
    findings: list[str]
    missing_in_branch_protection: list[str]
    missing_in_check_runs: list[str]
    missing_optional_contexts: list[str]
    ref_sha: str | None
    http_status: int | None = None
    http_error: str | None = None


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Strict-23 preflight: compare canonical contexts against branch protection and emitted check-runs."
    )
    parser.add_argument("--repo", required=True, help="GitHub repository in owner/repo format")
    parser.add_argument("--ref", default="main", help="Ref (branch/tag/SHA) used for emitted check context inventory")
    parser.add_argument("--branch", default="main", help="Branch used for branch-protection context inventory")
    parser.add_argument("--api-base", default="https://api.github.com", help="GitHub API base URL")
    parser.add_argument("--policy", default="docs/branch-protection-policy.json", help="Policy JSON path")
    parser.add_argument(
        "--canonical-contexts",
        default="",
        help="Optional comma-separated required context names; when set, overrides policy required contexts.",
    )
    parser.add_argument("--out-json", required=True, help="Output JSON path")
    parser.add_argument("--out-md", required=True, help="Output markdown path")
    return parser.parse_args()


def _classify_http_status(code: int) -> str:
    return "inconclusive_permissions" if code in PERMISSION_HTTP_CODES else "api_error"


def _api_get(api_base: str, repo: str, path: str, token: str) -> dict[str, Any]:
    validated_base = normalize_https_url(api_base, allowed_hosts={"api.github.com"}, strip_query=True).rstrip("/")
    url = f"{validated_base}/repos/{repo}/{path.lstrip('/')}"
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"Unsupported API URL: {url!r}")
    req = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "reframe-strict23-preflight",
        },
        method="GET",
    )
    with urlopen(req, timeout=30) as resp:  # nosec B310 - URL scheme and host are validated above
        return json.loads(resp.read().decode("utf-8"))


def _canonical_contexts(raw: str) -> list[str]:
    if not raw.strip():
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        name = str(item).strip()
        if not name or name in seen:
            continue
        seen.add(name)
        out.append(name)
    return out


def _context_sets_from_policy(policy: dict[str, Any]) -> tuple[list[str], list[str]]:
    required_checks = _dedupe([str(v).strip() for v in (policy.get("required_status_checks") or []) if str(v).strip()])
    supplemental = policy.get("strict23_supplemental_contexts")
    required_supplemental: list[str] = []
    optional_supplemental: list[str] = []
    if isinstance(supplemental, dict):
        required_supplemental = _dedupe([str(v).strip() for v in (supplemental.get("required") or []) if str(v).strip()])
        optional_supplemental = _dedupe([str(v).strip() for v in (supplemental.get("optional") or []) if str(v).strip()])
    required_contexts = _dedupe(required_checks + required_supplemental)
    optional_contexts = [item for item in optional_supplemental if item not in required_contexts]
    return required_contexts, optional_contexts


def evaluate_contexts(
    *,
    required_contexts: list[str],
    optional_contexts: list[str],
    branch_required_checks: list[str],
    emitted_contexts: list[str],
    ref_sha: str | None,
) -> PreflightResult:
    missing_in_branch = [ctx for ctx in required_contexts if ctx not in branch_required_checks]
    missing_in_emitted = [ctx for ctx in required_contexts if ctx not in emitted_contexts]
    missing_optional_contexts = [ctx for ctx in optional_contexts if ctx not in emitted_contexts]

    findings: list[str] = []
    if missing_in_branch:
        findings.append("Required contexts missing from branch protection: " + ", ".join(missing_in_branch))
    if missing_in_emitted:
        findings.append("Required contexts missing from emitted checks on ref: " + ", ".join(missing_in_emitted))
    if missing_optional_contexts:
        findings.append("Optional contexts missing from emitted checks on ref: " + ", ".join(missing_optional_contexts))

    status = "compliant" if not (missing_in_branch or missing_in_emitted) else "non_compliant"
    return PreflightResult(
        status=status,
        findings=findings,
        missing_in_branch_protection=missing_in_branch,
        missing_in_check_runs=missing_in_emitted,
        missing_optional_contexts=missing_optional_contexts,
        ref_sha=ref_sha,
    )


def _collect_emitted_contexts(check_runs: dict[str, Any], status_payload: dict[str, Any]) -> list[str]:
    contexts: set[str] = set(_collect_named_values(check_runs.get("check_runs") or [], "name"))
    contexts.update(_collect_named_values(status_payload.get("statuses") or [], "context"))
    return sorted(contexts)


def _collect_named_values(items: list[dict[str, Any]], field: str) -> list[str]:
    values: list[str] = []
    for item in items:
        value = str(item.get(field) or "").strip()
        if value:
            values.append(value)
    return values


def _render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# strict-23 Preflight",
        "",
        f"- Status: `{payload['status']}`",
        f"- Repo: `{payload['repo']}`",
        f"- Branch policy target: `{payload['branch']}`",
        f"- Ref target: `{payload['ref']}`",
        f"- Resolved ref SHA: `{payload.get('ref_sha') or 'unknown'}`",
        f"- Timestamp (UTC): `{payload['timestamp_utc']}`",
        "",
        "## Findings",
    ]

    findings = payload.get("findings") or []
    if findings:
        lines.extend(f"- {item}" for item in findings)
    else:
        lines.append("- None")

    lines.extend(
        [
            "",
            "## Missing contexts",
            "",
            f"- required missing in branch protection: `{len(payload.get('missing_in_branch_protection') or [])}`",
            f"- required missing in emitted checks: `{len(payload.get('missing_in_check_runs') or [])}`",
            f"- optional missing in emitted checks: `{len(payload.get('missing_optional_contexts') or [])}`",
        ]
    )

    if payload.get("http_status") is not None:
        lines.extend(
            [
                "",
                "## API details",
                f"- HTTP status: `{payload['http_status']}`",
                f"- Message: `{payload.get('http_error') or ''}`",
            ]
        )

    return "\n".join(lines) + "\n"


def _missing_token_result() -> tuple[PreflightResult, list[str], list[str]]:
    result = PreflightResult(
        status="inconclusive_permissions",
        findings=["GitHub token missing; strict-23 preflight cannot query branch protection/check-runs."],
        missing_in_branch_protection=[],
        missing_in_check_runs=[],
        missing_optional_contexts=[],
        ref_sha=None,
    )
    return result, [], []


def _http_error_result(exc: HTTPError) -> tuple[PreflightResult, list[str], list[str]]:
    message = exc.read().decode("utf-8", errors="replace")[:1000]
    result = PreflightResult(
        status=_classify_http_status(exc.code),
        findings=[f"GitHub API request failed (HTTP {exc.code}) while running strict-23 preflight."],
        missing_in_branch_protection=[],
        missing_in_check_runs=[],
        missing_optional_contexts=[],
        ref_sha=None,
        http_status=exc.code,
        http_error=message,
    )
    return result, [], []


def _url_error_result(exc: URLError) -> tuple[PreflightResult, list[str], list[str]]:
    result = PreflightResult(
        status="api_error",
        findings=["Network error while requesting GitHub API for strict-23 preflight."],
        missing_in_branch_protection=[],
        missing_in_check_runs=[],
        missing_optional_contexts=[],
        ref_sha=None,
        http_error=str(exc.reason),
    )
    return result, [], []


def _run_preflight(
    *,
    args: argparse.Namespace,
    required_contexts: list[str],
    optional_contexts: list[str],
    token: str,
) -> tuple[PreflightResult, list[str], list[str]]:
    try:
        protection = _api_get(args.api_base, args.repo, f"branches/{args.branch}/protection", token)
        ref_payload = _api_get(args.api_base, args.repo, f"commits/{args.ref}", token)
        ref_sha = str(ref_payload.get("sha") or "").strip() or None
        if ref_sha is None:
            raise RuntimeError(f"Unable to resolve SHA for ref {args.ref!r}")
        check_runs = _api_get(args.api_base, args.repo, f"commits/{ref_sha}/check-runs?per_page=100", token)
        status_payload = _api_get(args.api_base, args.repo, f"commits/{ref_sha}/status", token)

        branch_required_checks = sorted((protection.get("required_status_checks") or {}).get("contexts") or [])
        emitted_contexts = _collect_emitted_contexts(check_runs, status_payload)
        result = evaluate_contexts(
            required_contexts=required_contexts,
            optional_contexts=optional_contexts,
            branch_required_checks=branch_required_checks,
            emitted_contexts=emitted_contexts,
            ref_sha=ref_sha,
        )
        return result, branch_required_checks, emitted_contexts
    except HTTPError as exc:
        return _http_error_result(exc)
    except URLError as exc:
        return _url_error_result(exc)


def _safe_output_path(raw: str, *, base: Path) -> Path:
    candidate = Path((raw or "").strip()).expanduser()
    if candidate.is_absolute():
        return candidate.resolve(strict=False)
    if not candidate.is_absolute():
        candidate = base / candidate
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(base.resolve())
    except ValueError as exc:
        raise ValueError(f"Output path escapes workspace root: {candidate}") from exc
    return resolved


def _safe_policy_path(raw: str, *, base: Path) -> Path:
    candidate = Path((raw or "").strip()).expanduser()
    if candidate.is_absolute():
        return candidate.resolve(strict=False)
    if not candidate.is_absolute():
        candidate = base / candidate
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(base.resolve())
    except ValueError as exc:
        raise ValueError(f"Policy path escapes workspace root: {candidate}") from exc
    return resolved


def main() -> int:
    args = _parse_args()
    root = Path.cwd().resolve()
    try:
        out_json = _safe_output_path(args.out_json, base=root)
        out_md = _safe_output_path(args.out_md, base=root)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    policy: dict[str, Any] = {}
    try:
        policy_path = _safe_policy_path(args.policy, base=root)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if policy_path.exists():
        policy = json.loads(policy_path.read_text(encoding="utf-8"))

    policy_required_contexts, policy_optional_contexts = _context_sets_from_policy(policy)
    explicit_required_contexts = _canonical_contexts(args.canonical_contexts)
    required_contexts = explicit_required_contexts or policy_required_contexts or list(DEFAULT_CANONICAL_CONTEXTS)
    optional_contexts = policy_optional_contexts

    token = (os.environ.get("GITHUB_TOKEN") or "").strip() or (os.environ.get("GH_TOKEN") or "").strip()
    now = datetime.now(timezone.utc).isoformat()
    if not token:
        result, branch_required_checks, emitted_contexts = _missing_token_result()
    else:
        result, branch_required_checks, emitted_contexts = _run_preflight(
            args=args,
            required_contexts=required_contexts,
            optional_contexts=optional_contexts,
            token=token,
        )

    payload = {
        "status": result.status,
        "repo": args.repo,
        "branch": args.branch,
        "ref": args.ref,
        "ref_sha": result.ref_sha,
        "timestamp_utc": now,
        "policy_path": str(policy_path),
        "required_contexts": required_contexts,
        "optional_contexts": optional_contexts,
        "canonical_contexts": required_contexts,
        "branch_protection_required_checks": branch_required_checks,
        "emitted_contexts": emitted_contexts,
        "missing_in_branch_protection": result.missing_in_branch_protection,
        "missing_in_check_runs": result.missing_in_check_runs,
        "missing_optional_contexts": result.missing_optional_contexts,
        "findings": result.findings,
        "http_status": result.http_status,
        "http_error": result.http_error,
    }

    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    out_md.write_text(_render_markdown(payload), encoding="utf-8")

    if result.status in {"non_compliant", "api_error"}:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
