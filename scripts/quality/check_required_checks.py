#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Wait for required GitHub check contexts and assert they are successful.")
    parser.add_argument("--repo", required=True, help="owner/repo")
    parser.add_argument("--sha", required=True, help="commit SHA")
    parser.add_argument("--required-context", action="append", default=[], help="Required context name")
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument("--poll-seconds", type=int, default=20)
    parser.add_argument("--out-json", default="quality-zero-gate/required-checks.json")
    parser.add_argument("--out-md", default="quality-zero-gate/required-checks.md")
    return parser.parse_args()


def _api_get(repo: str, path: str, token: str) -> dict[str, Any]:
    url = f"https://api.github.com/repos/{repo}/{path.lstrip('/')}"
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "reframe-quality-zero-gate",
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _collect_contexts(check_runs_payload: dict[str, Any], status_payload: dict[str, Any]) -> dict[str, dict[str, str]]:
    contexts: dict[str, dict[str, str]] = {}

    for run in check_runs_payload.get("check_runs", []) or []:
        name = str(run.get("name") or "").strip()
        if not name:
            continue
        contexts[name] = {
            "state": str(run.get("status") or ""),
            "conclusion": str(run.get("conclusion") or ""),
            "source": "check_run",
        }

    for status in status_payload.get("statuses", []) or []:
        name = str(status.get("context") or "").strip()
        if not name:
            continue
        contexts[name] = {
            "state": str(status.get("state") or ""),
            "conclusion": str(status.get("state") or ""),
            "source": "status",
        }

    return contexts


def _evaluate(required: list[str], contexts: dict[str, dict[str, str]]) -> tuple[str, list[str], list[str]]:
    missing: list[str] = []
    failed: list[str] = []

    for context in required:
        observed = contexts.get(context)
        if not observed:
            missing.append(context)
            continue

        source = observed.get("source")
        if source == "check_run":
            state = observed.get("state")
            conclusion = observed.get("conclusion")
            if state != "completed":
                failed.append(f"{context}: status={state}")
            elif conclusion != "success":
                failed.append(f"{context}: conclusion={conclusion}")
        else:
            conclusion = observed.get("conclusion")
            if conclusion != "success":
                failed.append(f"{context}: state={conclusion}")

    status = "pass" if not missing and not failed else "fail"
    return status, missing, failed


def _render_md(payload: dict) -> str:
    lines = [
        "# Quality Zero Gate - Required Contexts",
        "",
        f"- Status: `{payload['status']}`",
        f"- Repo/SHA: `{payload['repo']}@{payload['sha']}`",
        f"- Timestamp (UTC): `{payload['timestamp_utc']}`",
        "",
        "## Missing contexts",
    ]

    missing = payload.get("missing") or []
    if missing:
        lines.extend(f"- `{name}`" for name in missing)
    else:
        lines.append("- None")

    lines.extend(["", "## Failed contexts"])
    failed = payload.get("failed") or []
    if failed:
        lines.extend(f"- {entry}" for entry in failed)
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
    token = (os.environ.get("GITHUB_TOKEN", "") or os.environ.get("GH_TOKEN", "")).strip()
    required = [item.strip() for item in args.required_context if item.strip()]

    if not required:
        raise SystemExit("At least one --required-context is required")
    if not token:
        raise SystemExit("GITHUB_TOKEN or GH_TOKEN is required")

    deadline = time.time() + max(args.timeout_seconds, 1)

    final_payload: dict[str, Any] | None = None
    while time.time() <= deadline:
        check_runs = _api_get(args.repo, f"commits/{args.sha}/check-runs?per_page=100", token)
        statuses = _api_get(args.repo, f"commits/{args.sha}/status", token)
        contexts = _collect_contexts(check_runs, statuses)
        status, missing, failed = _evaluate(required, contexts)

        final_payload = {
            "status": status,
            "repo": args.repo,
            "sha": args.sha,
            "required": required,
            "missing": missing,
            "failed": failed,
            "contexts": contexts,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        }

        if status == "pass":
            break

        # wait only while there are missing contexts or in-progress check-runs
        in_progress = any(v.get("state") != "completed" for v in contexts.values() if v.get("source") == "check_run")
        if not missing and not in_progress:
            break
        time.sleep(max(args.poll_seconds, 1))

    if final_payload is None:
        raise SystemExit("No payload collected")

    try:
        out_json = _safe_output_path(args.out_json, "quality-zero-gate/required-checks.json")
        out_md = _safe_output_path(args.out_md, "quality-zero-gate/required-checks.md")
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(final_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    out_md.write_text(_render_md(final_payload), encoding="utf-8")
    print(out_md.read_text(encoding="utf-8"), end="")

    return 0 if final_payload["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
