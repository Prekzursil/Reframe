#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen


def _request_json(url: str, token: str, method: str = "GET", body: dict[str, Any] | None = None) -> Any:
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    req = Request(
        url,
        data=data,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "reframe-ops-digest-upsert",
            "Content-Type": "application/json",
        },
        method=method,
    )
    with urlopen(req, timeout=30) as resp:
        if resp.status == 204:
            return None
        return json.loads(resp.read().decode("utf-8"))


def _render_issue_body(repo: str, digest_md: str, digest_json: dict[str, Any], run_url: str | None) -> str:
    snapshot = {
        "metrics": digest_json.get("metrics", {}),
        "trends": digest_json.get("trends", {}),
        "health": digest_json.get("health", {}),
    }
    lines = [
        "## Weekly Ops Digest (rolling)",
        "",
        f"- Repo: `{repo}`",
        f"- Updated (UTC): `{datetime.now(timezone.utc).isoformat()}`",
    ]
    if run_url:
        lines.append(f"- Workflow run: {run_url}")

    lines.extend(
        [
            "",
            "### Snapshot",
            "```json",
            json.dumps(snapshot, indent=2, sort_keys=True),
            "```",
            "",
            "### Digest",
            digest_md.strip(),
            "",
            "### Notes",
            "- This issue is continuously updated by `ops-weekly-digest.yml`.",
            "- Historical artifacts are attached to each workflow run.",
        ]
    )
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Upsert rolling ops digest issue.")
    parser.add_argument("--repo", required=True, help="owner/repo")
    parser.add_argument("--digest-json", required=True)
    parser.add_argument("--digest-md", required=True)
    parser.add_argument("--out-json", required=True)
    parser.add_argument("--api-base", default="https://api.github.com")
    parser.add_argument("--title", default="Weekly Ops Digest (rolling)")
    return parser.parse_args()


def _safe_output_path(raw: str, *, base: Path) -> Path:
    candidate = Path((raw or "").strip()).expanduser()
    if not candidate.is_absolute():
        candidate = base / candidate
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(base.resolve())
    except ValueError as exc:
        raise ValueError(f"Output path escapes workspace root: {candidate}") from exc
    return resolved


def main() -> int:
    args = parse_args()
    token = (os.environ.get("GITHUB_TOKEN") or "").strip() or (os.environ.get("GH_TOKEN") or "").strip()
    if not token:
        raise SystemExit("GITHUB_TOKEN or GH_TOKEN is required")

    owner, repo = args.repo.split("/", 1)
    api = args.api_base.rstrip("/")

    digest_json = json.loads(Path(args.digest_json).read_text(encoding="utf-8"))
    digest_md = Path(args.digest_md).read_text(encoding="utf-8")

    run_url = os.environ.get("GITHUB_SERVER_URL") and os.environ.get("GITHUB_REPOSITORY") and os.environ.get("GITHUB_RUN_ID")
    if run_url:
        run_url = f"{os.environ['GITHUB_SERVER_URL']}/{os.environ['GITHUB_REPOSITORY']}/actions/runs/{os.environ['GITHUB_RUN_ID']}"

    body = _render_issue_body(args.repo, digest_md, digest_json, run_url)

    open_issues = _request_json(
        f"{api}/repos/{owner}/{repo}/issues?state=open&per_page=100&labels=area:infra",
        token,
        method="GET",
    )
    target = None
    for issue in open_issues:
        if issue.get("pull_request"):
            continue
        if (issue.get("title") or "") == args.title:
            target = issue
            break

    if target is None:
        created = _request_json(
            f"{api}/repos/{owner}/{repo}/issues",
            token,
            method="POST",
            body={
                "title": args.title,
                "body": body,
                "labels": ["area:infra", "risk:low"],
            },
        )
        result = {
            "action": "created",
            "issue_number": created["number"],
            "issue_url": created["html_url"],
        }
    else:
        updated = _request_json(
            f"{api}/repos/{owner}/{repo}/issues/{target['number']}",
            token,
            method="PATCH",
            body={"title": args.title, "body": body},
        )
        result = {
            "action": "updated",
            "issue_number": updated["number"],
            "issue_url": updated["html_url"],
        }

    try:
        out = _safe_output_path(args.out_json, base=Path.cwd().resolve())
    except ValueError as exc:
        raise SystemExit(str(exc))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
