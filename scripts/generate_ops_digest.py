#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from security_helpers import normalize_https_url

DEFAULT_OPS_HEALTH_POLICY: dict[str, Any] = {
    "required_checks": [],
    "thresholds": {
        "main_ci_failure_rate_pct": {"ok_max": 5.0, "watch_max": 15.0},
        "required_check_pass_rate_pct": {"ok_min": 95.0, "watch_min": 85.0},
        "ci_duration_p95_seconds": {"ok_max": 1800.0, "watch_max": 3600.0},
        "delivery_throughput": {"ok_min_prs_merged": 1},
    },
}


def _iso_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _request_json(url: str, token: str) -> tuple[list[Any] | dict[str, Any], str | None]:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"Unsupported API URL: {url!r}")
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
    with urlopen(req, timeout=30) as resp:  # nosec B310 - URL scheme and host are validated above
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


def _count_items_in_window(
    items: list[dict[str, Any]],
    *,
    date_field: str,
    start: datetime,
    end: datetime,
) -> int:
    return sum(1 for item in items if _in_window(_parse_dt(item.get(date_field)), start, end))


def _main_runs_in_window(
    workflow_runs: list[dict[str, Any]],
    *,
    start: datetime,
    end: datetime,
) -> list[dict[str, Any]]:
    return [
        run
        for run in workflow_runs
        if run.get("head_branch") == "main" and _in_window(_parse_dt(run.get("created_at")), start, end)
    ]


def _count_failed_runs(runs: list[dict[str, Any]]) -> int:
    return sum(1 for run in runs if run.get("conclusion") == "failure")


def _failure_rate(failed_runs: int, total_runs: int) -> float:
    if total_runs == 0:
        return 0.0
    return failed_runs / total_runs * 100.0


def _run_duration_seconds(run: dict[str, Any]) -> float | None:
    start = _parse_dt(str(run.get("run_started_at") or run.get("created_at") or ""))
    end = _parse_dt(str(run.get("updated_at") or run.get("completed_at") or ""))
    if start is None or end is None or end < start:
        return None
    return (end - start).total_seconds()


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    if percentile <= 0:
        return float(sorted(values)[0])
    if percentile >= 1:
        return float(sorted(values)[-1])
    ordered = sorted(values)
    rank_index = max(0, min(len(ordered) - 1, math.ceil(percentile * len(ordered)) - 1))
    return float(ordered[rank_index])


def _as_check_name(value: Any) -> str:
    return str(value or "").strip()


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        name = _as_check_name(item)
        if not name or name in seen:
            continue
        seen.add(name)
        out.append(name)
    return out


def _required_checks(policy: dict[str, Any], workflow_runs: list[dict[str, Any]]) -> list[str]:
    explicit = _dedupe(
        [str(item) for item in (policy.get("required_checks") or policy.get("required_status_checks") or [])]
    )
    if explicit:
        return explicit

    discovered = sorted(
        {
            _as_check_name(run.get("name"))
            for run in workflow_runs
            if run.get("head_branch") == "main" and _as_check_name(run.get("name"))
        }
    )
    return discovered


def _required_check_metrics(runs_window: list[dict[str, Any]], required_checks: list[str]) -> tuple[float, list[dict[str, Any]]]:
    if not required_checks:
        return 100.0, []
    required_set = set(required_checks)
    total = 0
    passed = 0
    per_check_totals: dict[str, int] = {}
    per_check_failures: dict[str, int] = {}

    for run in runs_window:
        name = _as_check_name(run.get("name"))
        if name not in required_set:
            continue
        total += 1
        per_check_totals[name] = per_check_totals.get(name, 0) + 1
        conclusion = _as_check_name(run.get("conclusion")).lower()
        if conclusion == "success":
            passed += 1
            continue
        if conclusion in {"neutral", "skipped"}:
            continue
        per_check_failures[name] = per_check_failures.get(name, 0) + 1

    pass_rate = 100.0 if total == 0 else (passed / total * 100.0)
    top_failed = [
        {
            "name": check_name,
            "failed_runs": int(per_check_failures.get(check_name, 0)),
            "total_runs": int(per_check_totals.get(check_name, 0)),
        }
        for check_name in per_check_failures
    ]
    top_failed.sort(key=lambda item: (-item["failed_runs"], -item["total_runs"], item["name"]))
    return round(pass_rate, 2), top_failed[:5]


def _window_metrics(
    *,
    start: datetime,
    end: datetime,
    pulls: list[dict[str, Any]],
    workflow_runs: list[dict[str, Any]],
    required_checks: list[str],
) -> dict[str, Any]:
    opened_prs = _count_items_in_window(pulls, date_field="created_at", start=start, end=end)
    merged_prs = _count_items_in_window(pulls, date_field="merged_at", start=start, end=end)
    runs_window = _main_runs_in_window(workflow_runs, start=start, end=end)
    failed_runs = _count_failed_runs(runs_window)
    ci_failure_rate = _failure_rate(failed_runs, len(runs_window))
    required_pass_rate, top_failed_checks = _required_check_metrics(runs_window, required_checks)

    durations = [seconds for run in runs_window if (seconds := _run_duration_seconds(run)) is not None]
    duration_median = float(sorted(durations)[len(durations) // 2]) if durations else 0.0
    if durations and len(durations) % 2 == 0:
        ordered = sorted(durations)
        midpoint = len(ordered) // 2
        duration_median = float((ordered[midpoint - 1] + ordered[midpoint]) / 2.0)
    duration_p95 = _percentile(durations, 0.95)

    return {
        "prs_opened": int(opened_prs),
        "prs_merged": int(merged_prs),
        "main_ci_runs": int(len(runs_window)),
        "main_ci_failed_runs": int(failed_runs),
        "main_ci_failure_rate_pct": round(ci_failure_rate, 2),
        "required_check_pass_rate_pct": float(required_pass_rate),
        "ci_duration_median_seconds": float(duration_median),
        "ci_duration_p95_seconds": float(duration_p95),
        "top_failed_checks": top_failed_checks,
    }


def _classify_min_threshold(value: float, ok_min: float, watch_min: float) -> str:
    if value >= ok_min:
        return "ok"
    if value >= watch_min:
        return "watch"
    return "alert"


def _classify_max_threshold(value: float, ok_max: float, watch_max: float) -> str:
    if value <= ok_max:
        return "ok"
    if value <= watch_max:
        return "watch"
    return "alert"


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            merged[key] = _deep_merge(base[key], value)
        else:
            merged[key] = value
    return merged


def _load_policy(path: Path) -> tuple[dict[str, Any], bool]:
    policy = json.loads(json.dumps(DEFAULT_OPS_HEALTH_POLICY))
    if not path.exists():
        return policy, False
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(loaded, dict):
        policy = _deep_merge(policy, loaded)
    return policy, True


def compute_digest(
    *,
    now: datetime,
    window_days: int,
    pulls: list[dict[str, Any]],
    issues: list[dict[str, Any]],
    workflow_runs: list[dict[str, Any]],
    policy: dict[str, Any] | None = None,
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

    policy_obj = policy or {}
    required_checks = _required_checks(policy_obj, workflow_runs)
    current = _window_metrics(
        start=window_start,
        end=window_end,
        pulls=pulls,
        workflow_runs=workflow_runs,
        required_checks=required_checks,
    )
    previous = _window_metrics(
        start=previous_window_start,
        end=previous_window_end,
        pulls=pulls,
        workflow_runs=workflow_runs,
        required_checks=required_checks,
    )

    trends = {
        "prs_opened_delta": int(current["prs_opened"] - previous["prs_opened"]),
        "prs_merged_delta": int(current["prs_merged"] - previous["prs_merged"]),
        "main_ci_runs_delta": int(current["main_ci_runs"] - previous["main_ci_runs"]),
        "main_ci_failed_runs_delta": int(current["main_ci_failed_runs"] - previous["main_ci_failed_runs"]),
        "main_ci_failure_rate_pct_delta": round(
            float(current["main_ci_failure_rate_pct"]) - float(previous["main_ci_failure_rate_pct"]),
            2,
        ),
        "required_check_pass_rate_pct_delta": round(
            float(current["required_check_pass_rate_pct"]) - float(previous["required_check_pass_rate_pct"]),
            2,
        ),
        "ci_duration_p95_seconds_delta": round(
            float(current["ci_duration_p95_seconds"]) - float(previous["ci_duration_p95_seconds"]),
            2,
        ),
    }

    thresholds = (policy_obj.get("thresholds") or {}) if isinstance(policy_obj, dict) else {}
    failure_policy = thresholds.get("main_ci_failure_rate_pct") or {}
    pass_policy = thresholds.get("required_check_pass_rate_pct") or {}
    duration_policy = thresholds.get("ci_duration_p95_seconds") or {}
    throughput_policy = thresholds.get("delivery_throughput") or {}

    throughput_ok_min = int(throughput_policy.get("ok_min_prs_merged", 1))
    throughput_state = "ok" if int(current["prs_merged"]) >= throughput_ok_min else "watch"
    failure_rate_state = _classify_max_threshold(
        float(current["main_ci_failure_rate_pct"]),
        float(failure_policy.get("ok_max", 5.0)),
        float(failure_policy.get("watch_max", 15.0)),
    )
    required_pass_state = _classify_min_threshold(
        float(current["required_check_pass_rate_pct"]),
        float(pass_policy.get("ok_min", 95.0)),
        float(pass_policy.get("watch_min", 85.0)),
    )
    duration_state = _classify_max_threshold(
        float(current["ci_duration_p95_seconds"]),
        float(duration_policy.get("ok_max", 1800.0)),
        float(duration_policy.get("watch_max", 3600.0)),
    )

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
        "policy": {
            "required_checks": required_checks,
            "thresholds": thresholds,
        },
        "metrics": {
            "prs_opened": int(current["prs_opened"]),
            "prs_merged": int(current["prs_merged"]),
            "open_issues": len(open_non_pr_issues),
            "open_agent_issues": len(open_agent_issues),
            "main_ci_runs": int(current["main_ci_runs"]),
            "main_ci_failed_runs": int(current["main_ci_failed_runs"]),
            "main_ci_failure_rate_pct": float(current["main_ci_failure_rate_pct"]),
            "required_check_pass_rate_pct": float(current["required_check_pass_rate_pct"]),
            "ci_duration_median_seconds": float(current["ci_duration_median_seconds"]),
            "ci_duration_p95_seconds": float(current["ci_duration_p95_seconds"]),
            "top_failed_checks": current["top_failed_checks"],
        },
        "metrics_previous_window": {
            "prs_opened": int(previous["prs_opened"]),
            "prs_merged": int(previous["prs_merged"]),
            "main_ci_runs": int(previous["main_ci_runs"]),
            "main_ci_failed_runs": int(previous["main_ci_failed_runs"]),
            "main_ci_failure_rate_pct": float(previous["main_ci_failure_rate_pct"]),
            "required_check_pass_rate_pct": float(previous["required_check_pass_rate_pct"]),
            "ci_duration_median_seconds": float(previous["ci_duration_median_seconds"]),
            "ci_duration_p95_seconds": float(previous["ci_duration_p95_seconds"]),
        },
        "trends": trends,
        "health": {
            "main_ci_failure_rate": failure_rate_state,
            "main_ci_failure_rate_trend": trend_state,
            "required_check_pass_rate": required_pass_state,
            "ci_duration_p95": duration_state,
            "delivery_throughput": throughput_state,
        },
    }


def _render_markdown(repo: str, digest: dict[str, Any]) -> str:
    m = digest["metrics"]
    prev = digest["metrics_previous_window"]
    trends = digest["trends"]
    h = digest["health"]
    top_failed = m.get("top_failed_checks") or []
    top_failed_lines = "\n".join(
        f"- `{entry['name']}`: failures={entry['failed_runs']}, total={entry['total_runs']}" for entry in top_failed
    )
    if not top_failed_lines:
        top_failed_lines = "- None"

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
        f"- Main CI failure rate: **{m['main_ci_failure_rate_pct']}%**\n"
        f"- Required check pass rate: **{m['required_check_pass_rate_pct']}%**\n"
        f"- CI median duration: **{m['ci_duration_median_seconds']}s**\n"
        f"- CI p95 duration: **{m['ci_duration_p95_seconds']}s**\n\n"
        "### Top failed checks\n"
        f"{top_failed_lines}\n\n"
        "## Previous Window (baseline)\n"
        f"- PRs opened: **{prev['prs_opened']}**\n"
        f"- PRs merged: **{prev['prs_merged']}**\n"
        f"- Main CI runs: **{prev['main_ci_runs']}**\n"
        f"- Main CI failures: **{prev['main_ci_failed_runs']}**\n"
        f"- Main CI failure rate: **{prev['main_ci_failure_rate_pct']}%**\n"
        f"- Required check pass rate: **{prev['required_check_pass_rate_pct']}%**\n"
        f"- CI p95 duration: **{prev['ci_duration_p95_seconds']}s**\n\n"
        "## Trends (current - previous)\n"
        f"- PRs opened delta: **{trends['prs_opened_delta']}**\n"
        f"- PRs merged delta: **{trends['prs_merged_delta']}**\n"
        f"- Main CI runs delta: **{trends['main_ci_runs_delta']}**\n"
        f"- Main CI failures delta: **{trends['main_ci_failed_runs_delta']}**\n"
        f"- Main CI failure rate delta: **{trends['main_ci_failure_rate_pct_delta']}%**\n"
        f"- Required check pass rate delta: **{trends['required_check_pass_rate_pct_delta']}%**\n"
        f"- CI p95 duration delta: **{trends['ci_duration_p95_seconds_delta']}s**\n\n"
        "## Health\n"
        f"- Main CI failure rate: `{h['main_ci_failure_rate']}`\n"
        f"- Main CI failure rate trend: `{h['main_ci_failure_rate_trend']}`\n"
        f"- Required check pass rate: `{h['required_check_pass_rate']}`\n"
        f"- CI p95 duration: `{h['ci_duration_p95']}`\n"
        f"- Delivery throughput: `{h['delivery_throughput']}`\n"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate weekly ops digest metrics from GitHub API.")
    parser.add_argument("--repo", required=True, help="owner/repo")
    parser.add_argument("--window-days", type=int, default=7)
    parser.add_argument("--out-json", required=True)
    parser.add_argument("--out-md", required=True)
    parser.add_argument("--policy", default="docs/ops-health-policy.json")
    parser.add_argument("--api-base", default="https://api.github.com")
    return parser.parse_args()


def _safe_workspace_path(raw: str, *, base: Path) -> Path:
    candidate = Path((raw or "").strip()).expanduser()
    if not candidate.is_absolute():
        candidate = base / candidate
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(base.resolve())
    except ValueError as exc:
        raise ValueError(f"Path escapes workspace root: {candidate}") from exc
    return resolved


def main() -> int:
    args = parse_args()
    root = Path.cwd().resolve()
    token = (os.environ.get("GITHUB_TOKEN") or "").strip() or (os.environ.get("GH_TOKEN") or "").strip()
    if not token:
        raise SystemExit("GITHUB_TOKEN or GH_TOKEN is required")

    owner_repo = args.repo
    api = normalize_https_url(args.api_base, allowed_hosts={"api.github.com"}, strip_query=True).rstrip("/")
    try:
        policy_path = _safe_workspace_path(args.policy, base=root)
        out_json = _safe_workspace_path(args.out_json, base=root)
        out_md = _safe_workspace_path(args.out_md, base=root)
    except ValueError as exc:
        raise SystemExit(str(exc))
    policy, policy_loaded = _load_policy(policy_path)

    pulls = _paginate(f"{api}/repos/{owner_repo}/pulls?state=all&sort=updated&direction=desc&per_page=100", token)
    issues = _paginate(f"{api}/repos/{owner_repo}/issues?state=open&per_page=100", token)
    runs = _paginate(f"{api}/repos/{owner_repo}/actions/runs?per_page=100", token)

    digest = compute_digest(
        now=_iso_now(),
        window_days=args.window_days,
        pulls=pulls,
        issues=issues,
        workflow_runs=runs,
        policy=policy,
    )
    digest["policy"]["path"] = str(policy_path)
    digest["policy"]["loaded_from_file"] = policy_loaded

    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_md.parent.mkdir(parents=True, exist_ok=True)

    out_json.write_text(json.dumps(digest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    out_md.write_text(_render_markdown(owner_repo, digest), encoding="utf-8")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
