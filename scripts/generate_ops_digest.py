#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, parse_qs
from urllib.request import Request, urlopen


def _iso_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    v = value.replace("Z", "+00:00")
    return datetime.fromisoformat(v)


def _request_json(url: str, token: str) -> tuple[list[Any] | dict[str, Any], str | None]:
    req = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "reframe-ops-digest",
        },
        method="GET",
    )
    with urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        link = resp.headers.get("Link")
    return data, link


def _next_link(link_header: str | None) -> str | None:
    if not link_header:
        return None
    parts = [p.strip() for p in link_header.split(",")]
    for part in parts:
        if 'rel="next"' not in part:
            continue
        start = part.find("<")
        end = part.find(">")
        if start == -1 or end == -1:
            continue
        return part[start + 1 : end]
    return None


def _paginate(url: str, token: str, max_pages: int = 5) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    next_url: str | None = url
    pages = 0
    while next_url and pages < max_pages:
        payload, link = _request_json(next_url, token)
        if isinstance(payload, list):
            out.extend(payload)
        elif isinstance(payload, dict):
            # actions workflow-runs endpoint wraps in workflow_runs
            if "workflow_runs" in payload and isinstance(payload["workflow_runs"], list):
                out.extend(payload["workflow_runs"])
            else:
                break
        pages += 1
        next_url = _next_link(link)
    return out


def _in_window(value: datetime | None, start: datetime, end: datetime) -> bool:
    if value is None:
        return False
    return start <= value < end


def _window_metrics(
    *,
    start: datetime,
    end: datetime,
    pulls: list[dict[str, Any]],
    workflow_runs: list[dict[str, Any]],
) -> dict[str, float]:
    opened_prs = [pr for pr in pulls if _in_window(_parse_dt(pr.get("created_at")), start, end)]
    merged_prs = [pr for pr in pulls if _in_window(_parse_dt(pr.get("merged_at")), start, end)]
    runs_window = [
        r
        for r in workflow_runs
        if (r.get("head_branch") == "main") and _in_window(_parse_dt(r.get("created_at")), start, end)
    ]
    failed_runs = [r for r in runs_window if r.get("conclusion") == "failure"]
    ci_failure_rate = (len(failed_runs) / len(runs_window) * 100.0) if runs_window else 0.0
    return {
        "prs_opened": len(opened_prs),
        "prs_merged": len(merged_prs),
        "main_ci_runs": len(runs_window),
        "main_ci_failed_runs": len(failed_runs),
        "main_ci_failure_rate_pct": round(ci_failure_rate, 2),
    }


def compute_digest(
    *,
    now: datetime,
    window_days: int,
    pulls: list[dict[str, Any]],
    issues: list[dict[str, Any]],
    workflow_runs: list[dict[str, Any]],
) -> dict[str, Any]:
    window_end = now
    window_start = now - timedelta(days=window_days)
    previous_window_start = window_start - timedelta(days=window_days)
    previous_window_end = window_start

    open_non_pr_issues = [i for i in issues if not i.get("pull_request")]
    open_agent_issues = [
        i
        for i in open_non_pr_issues
        if any((lbl.get("name") or "") in {"agent:ready", "agent:in-progress", "agent:blocked"} for lbl in (i.get("labels") or []))
    ]

    current = _window_metrics(
        start=window_start,
        end=window_end,
        pulls=pulls,
        workflow_runs=workflow_runs,
    )
    previous = _window_metrics(
        start=previous_window_start,
        end=previous_window_end,
        pulls=pulls,
        workflow_runs=workflow_runs,
    )

    trends = {
        "prs_opened_delta": int(current["prs_opened"] - previous["prs_opened"]),
        "prs_merged_delta": int(current["prs_merged"] - previous["prs_merged"]),
        "main_ci_runs_delta": int(current["main_ci_runs"] - previous["main_ci_runs"]),
        "main_ci_failed_runs_delta": int(current["main_ci_failed_runs"] - previous["main_ci_failed_runs"]),
        "main_ci_failure_rate_pct_delta": round(
            current["main_ci_failure_rate_pct"] - previous["main_ci_failure_rate_pct"],
            2,
        ),
    }

    throughput_state = "ok" if current["prs_merged"] > 0 else "watch"
    failure_rate_state = "ok" if current["main_ci_failure_rate_pct"] <= 5.0 else "watch"
    if trends["main_ci_failure_rate_pct_delta"] > 0.25:
        trend_state = "worsening"
    elif trends["main_ci_failure_rate_pct_delta"] < -0.25:
        trend_state = "improving"
    else:
        trend_state = "stable"

    return {
        "timestamp_utc": now.isoformat(),
        "window_days": window_days,
        "window_start_utc": window_start.isoformat(),
        "window_end_utc": window_end.isoformat(),
        "previous_window_start_utc": previous_window_start.isoformat(),
        "previous_window_end_utc": previous_window_end.isoformat(),
        "metrics": {
            "prs_opened": int(current["prs_opened"]),
            "prs_merged": int(current["prs_merged"]),
            "open_issues": len(open_non_pr_issues),
            "open_agent_issues": len(open_agent_issues),
            "main_ci_runs": int(current["main_ci_runs"]),
            "main_ci_failed_runs": int(current["main_ci_failed_runs"]),
            "main_ci_failure_rate_pct": float(current["main_ci_failure_rate_pct"]),
        },
        "metrics_previous_window": {
            "prs_opened": int(previous["prs_opened"]),
            "prs_merged": int(previous["prs_merged"]),
            "main_ci_runs": int(previous["main_ci_runs"]),
            "main_ci_failed_runs": int(previous["main_ci_failed_runs"]),
            "main_ci_failure_rate_pct": float(previous["main_ci_failure_rate_pct"]),
        },
        "trends": trends,
        "health": {
            "main_ci_failure_rate": failure_rate_state,
            "main_ci_failure_rate_trend": trend_state,
            "delivery_throughput": throughput_state,
        },
    }


def _render_markdown(repo: str, digest: dict[str, Any]) -> str:
    m = digest["metrics"]
    prev = digest["metrics_previous_window"]
    trends = digest["trends"]
    h = digest["health"]
    return (
        "# Weekly Ops Digest\n\n"
        f"- Repo: `{repo}`\n"
        f"- Window: `{digest['window_start_utc']}` -> `{digest['window_end_utc']}` ({digest['window_days']}d)\n\n"
        "## Metrics\n"
        f"- PRs opened: **{m['prs_opened']}**\n"
        f"- PRs merged: **{m['prs_merged']}**\n"
        f"- Open issues: **{m['open_issues']}**\n"
        f"- Open agent-tracked issues: **{m['open_agent_issues']}**\n"
        f"- Main CI runs: **{m['main_ci_runs']}**\n"
        f"- Main CI failures: **{m['main_ci_failed_runs']}**\n"
        f"- Main CI failure rate: **{m['main_ci_failure_rate_pct']}%**\n\n"
        "## Previous Window (baseline)\n"
        f"- PRs opened: **{prev['prs_opened']}**\n"
        f"- PRs merged: **{prev['prs_merged']}**\n"
        f"- Main CI runs: **{prev['main_ci_runs']}**\n"
        f"- Main CI failures: **{prev['main_ci_failed_runs']}**\n"
        f"- Main CI failure rate: **{prev['main_ci_failure_rate_pct']}%**\n\n"
        "## Trends (current - previous)\n"
        f"- PRs opened delta: **{trends['prs_opened_delta']}**\n"
        f"- PRs merged delta: **{trends['prs_merged_delta']}**\n"
        f"- Main CI runs delta: **{trends['main_ci_runs_delta']}**\n"
        f"- Main CI failures delta: **{trends['main_ci_failed_runs_delta']}**\n"
        f"- Main CI failure rate delta: **{trends['main_ci_failure_rate_pct_delta']}%**\n\n"
        "## Health\n"
        f"- Main CI failure rate: `{h['main_ci_failure_rate']}`\n"
        f"- Main CI failure rate trend: `{h['main_ci_failure_rate_trend']}`\n"
        f"- Delivery throughput: `{h['delivery_throughput']}`\n"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate weekly ops digest metrics from GitHub API.")
    parser.add_argument("--repo", required=True, help="owner/repo")
    parser.add_argument("--window-days", type=int, default=7)
    parser.add_argument("--out-json", required=True)
    parser.add_argument("--out-md", required=True)
    parser.add_argument("--api-base", default="https://api.github.com")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    token = (os.environ.get("GITHUB_TOKEN") or "").strip() or (os.environ.get("GH_TOKEN") or "").strip()
    if not token:
        raise SystemExit("GITHUB_TOKEN or GH_TOKEN is required")

    owner_repo = args.repo
    api = args.api_base.rstrip("/")

    pulls = _paginate(f"{api}/repos/{owner_repo}/pulls?state=all&sort=updated&direction=desc&per_page=100", token)
    issues = _paginate(f"{api}/repos/{owner_repo}/issues?state=open&per_page=100", token)
    runs = _paginate(f"{api}/repos/{owner_repo}/actions/runs?per_page=100", token)

    digest = compute_digest(now=_iso_now(), window_days=args.window_days, pulls=pulls, issues=issues, workflow_runs=runs)

    out_json = Path(args.out_json)
    out_md = Path(args.out_md)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_md.parent.mkdir(parents=True, exist_ok=True)

    out_json.write_text(json.dumps(digest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    out_md.write_text(_render_markdown(owner_repo, digest), encoding="utf-8")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
