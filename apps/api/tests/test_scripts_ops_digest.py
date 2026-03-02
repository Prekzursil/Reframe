from __future__ import annotations

from datetime import datetime, timedelta, timezone
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest


def _expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _load_module(name: str, relative_path: str):
    repo_root = Path(__file__).resolve().parents[3]
    module_path = repo_root / relative_path
    spec = spec_from_file_location(name, module_path)
    _expect(spec is not None and spec.loader is not None, f"Unable to load module spec for {relative_path}")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_compute_digest_counts_window_metrics():
    module = _load_module("generate_ops_digest", "scripts/generate_ops_digest.py")

    now = datetime(2026, 3, 1, tzinfo=timezone.utc)
    recent = (now - timedelta(days=2)).isoformat()
    previous = (now - timedelta(days=9)).isoformat()
    old = (now - timedelta(days=20)).isoformat()

    pulls = [
        {"created_at": recent, "merged_at": recent},
        {"created_at": recent, "merged_at": None},
        {"created_at": previous, "merged_at": previous},
        {"created_at": old, "merged_at": old},
    ]
    issues = [
        {"labels": [{"name": "agent:ready"}]},
        {"labels": [{"name": "area:infra"}]},
    ]
    workflow_runs = [
        {"head_branch": "main", "created_at": recent, "conclusion": "failure"},
        {"head_branch": "main", "created_at": recent, "conclusion": "success"},
        {"head_branch": "main", "created_at": previous, "conclusion": "success"},
        {"head_branch": "feature", "created_at": recent, "conclusion": "failure"},
    ]

    digest = module.compute_digest(
        now=now,
        window_days=7,
        pulls=pulls,
        issues=issues,
        workflow_runs=workflow_runs,
    )

    _expect(digest["metrics"]["prs_opened"] == 2, "Expected prs_opened metric for current window")
    _expect(digest["metrics"]["prs_merged"] == 1, "Expected prs_merged metric for current window")
    _expect(digest["metrics"]["open_issues"] == 2, "Expected open issue count")
    _expect(digest["metrics"]["open_agent_issues"] == 1, "Expected open agent issue count")
    _expect(digest["metrics"]["main_ci_runs"] == 2, "Expected main CI run count for current window")
    _expect(digest["metrics"]["main_ci_failed_runs"] == 1, "Expected failed main CI run count for current window")
    _expect(
        digest["metrics"]["main_ci_failure_rate_pct"] == pytest.approx(50.0),
        "Expected current window CI failure rate",
    )
    _expect(digest["metrics_previous_window"]["prs_merged"] == 1, "Expected previous-window merged PR count")
    _expect(digest["metrics_previous_window"]["main_ci_runs"] == 1, "Expected previous-window CI run count")
    _expect(digest["trends"]["prs_merged_delta"] == 0, "Expected merged PR delta to be zero")
    _expect(
        digest["trends"]["main_ci_failure_rate_pct_delta"] == pytest.approx(50.0),
        "Expected CI failure-rate delta between windows",
    )
    _expect(
        digest["health"]["main_ci_failure_rate_trend"] == "worsening",
        "Expected worsening trend classification for increased failure rate",
    )


def test_upsert_render_issue_body_contains_digest_markdown():
    module = _load_module("upsert_ops_digest_issue", "scripts/upsert_ops_digest_issue.py")

    body = module._render_issue_body(
        "Prekzursil/Reframe",
        "# Weekly Ops Digest\n\n- PRs merged: **3**\n",
        {
            "metrics": {"prs_merged": 3, "main_ci_failure_rate_pct": 0.0},
            "trends": {"prs_merged_delta": 1, "main_ci_failure_rate_pct_delta": -2.5},
        },
        "https://github.com/Prekzursil/Reframe/actions/runs/123",
    )

    _expect("Weekly Ops Digest (rolling)" in body, "Expected rolling digest header in issue body")
    _expect('"prs_merged": 3' in body, "Expected metrics snapshot in issue body")
    _expect('"prs_merged_delta": 1' in body, "Expected trends snapshot in issue body")
    _expect(
        "https://github.com/Prekzursil/Reframe/actions/runs/123" in body,
        "Expected workflow run URL in issue body",
    )
