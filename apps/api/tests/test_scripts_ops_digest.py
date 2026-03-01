from __future__ import annotations

from datetime import datetime, timedelta, timezone
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest


def _load_module(name: str, relative_path: str):
    repo_root = Path(__file__).resolve().parents[3]
    module_path = repo_root / relative_path
    spec = spec_from_file_location(name, module_path)
    assert spec and spec.loader
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_compute_digest_counts_window_metrics():
    module = _load_module("generate_ops_digest", "scripts/generate_ops_digest.py")

    now = datetime(2026, 3, 1, tzinfo=timezone.utc)
    recent = (now - timedelta(days=2)).isoformat()
    old = (now - timedelta(days=20)).isoformat()

    pulls = [
        {"created_at": recent, "merged_at": recent},
        {"created_at": recent, "merged_at": None},
        {"created_at": old, "merged_at": old},
    ]
    issues = [
        {"labels": [{"name": "agent:ready"}]},
        {"labels": [{"name": "area:infra"}]},
    ]
    workflow_runs = [
        {"head_branch": "main", "created_at": recent, "conclusion": "failure"},
        {"head_branch": "main", "created_at": recent, "conclusion": "success"},
        {"head_branch": "feature", "created_at": recent, "conclusion": "failure"},
    ]

    digest = module.compute_digest(
        now=now,
        window_days=7,
        pulls=pulls,
        issues=issues,
        workflow_runs=workflow_runs,
    )

    assert digest["metrics"]["prs_opened"] == 2
    assert digest["metrics"]["prs_merged"] == 1
    assert digest["metrics"]["open_issues"] == 2
    assert digest["metrics"]["open_agent_issues"] == 1
    assert digest["metrics"]["main_ci_runs"] == 2
    assert digest["metrics"]["main_ci_failed_runs"] == 1
    assert digest["metrics"]["main_ci_failure_rate_pct"] == pytest.approx(50.0)


def test_upsert_render_issue_body_contains_digest_markdown():
    module = _load_module("upsert_ops_digest_issue", "scripts/upsert_ops_digest_issue.py")

    body = module._render_issue_body(
        "Prekzursil/Reframe",
        "# Weekly Ops Digest\n\n- PRs merged: **3**\n",
        {"metrics": {"prs_merged": 3, "main_ci_failure_rate_pct": 0.0}},
        "https://github.com/Prekzursil/Reframe/actions/runs/123",
    )

    assert "Weekly Ops Digest (rolling)" in body
    assert '"prs_merged": 3' in body
    assert "https://github.com/Prekzursil/Reframe/actions/runs/123" in body
