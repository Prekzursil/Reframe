from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest


def _expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _load_script(path: Path, module_name: str):
    spec = spec_from_file_location(module_name, path)
    _expect(spec is not None and spec.loader is not None, f"Unable to load module at {path}")
    module = module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_generate_ops_digest_helpers_cover_edge_cases(tmp_path):
    module = _load_script(_repo_root() / "scripts" / "generate_ops_digest.py", "generate_ops_digest_cov_wave")

    # Date parsing and windows
    now = datetime(2026, 3, 4, tzinfo=timezone.utc)
    start = datetime(2026, 3, 1, tzinfo=timezone.utc)
    end = datetime(2026, 3, 8, tzinfo=timezone.utc)
    _expect(module._parse_dt(None) is None, "Expected None datetime for missing value")
    _expect(module._parse_dt("bad-date") is None, "Expected None datetime for invalid value")
    _expect(module._in_window(now, start, end), "Expected datetime in window")
    _expect(not module._in_window(None, start, end), "Expected None datetime outside window")

    # Link header parsing
    link = '<https://api.example.test/page=2>; rel="next", <https://api.example.test/page=9>; rel="last"'
    _expect(module._next_link(link) == "https://api.example.test/page=2", "Expected next link parsing")
    _expect(module._next_link(None) is None, "Expected None next link for missing header")

    # Failure-rate and percentile helpers
    _expect(module._failure_rate(0, 0) == 0.0, "Expected 0 failure rate for no runs")
    _expect(module._failure_rate(1, 4) == 25.0, "Expected ratio failure rate")
    _expect(module._percentile([], 0.95) == 0.0, "Expected empty percentile fallback")
    _expect(module._percentile([10, 20, 30], 0) == 10.0, "Expected p0 percentile")
    _expect(module._percentile([10, 20, 30], 1) == 30.0, "Expected p1 percentile")

    # Duration helper
    run_ok = {
        "created_at": "2026-03-02T10:00:00Z",
        "run_started_at": "2026-03-02T10:00:00Z",
        "updated_at": "2026-03-02T10:05:00Z",
    }
    _expect(module._run_duration_seconds(run_ok) == 300.0, "Expected run duration computation")
    run_bad = {
        "run_started_at": "2026-03-02T10:05:00Z",
        "updated_at": "2026-03-02T10:00:00Z",
    }
    _expect(module._run_duration_seconds(run_bad) is None, "Expected invalid backwards duration to be None")

    # Required-check extraction
    workflow_runs = [
        {"head_branch": "main", "name": "CI"},
        {"head_branch": "main", "name": "CodeQL"},
        {"head_branch": "main", "name": "CI"},
    ]
    explicit_policy = {"required_checks": ["CI", "CI", "", "CodeQL"]}
    _expect(module._required_checks(explicit_policy, workflow_runs) == ["CI", "CodeQL"], "Expected deduped explicit checks")
    _expect(module._required_checks({}, workflow_runs) == ["CI", "CodeQL"], "Expected discovered checks fallback")

    pass_rate, top_failed = module._required_check_metrics(
        [
            {"name": "CI", "conclusion": "success"},
            {"name": "CI", "conclusion": "failure"},
            {"name": "CodeQL", "conclusion": "neutral"},
            {"name": "CodeQL", "conclusion": "cancelled"},
        ],
        ["CI", "CodeQL"],
    )
    _expect(pass_rate == 25.0, "Expected required-check pass-rate computation")
    _expect(top_failed and top_failed[0]["name"] in {"CI", "CodeQL"}, "Expected top failed checks list")

    # Deep merge and policy load paths
    base = {"a": {"x": 1}, "b": 2}
    merged = module._deep_merge(base, {"a": {"y": 3}, "c": 4})
    _expect(merged == {"a": {"x": 1, "y": 3}, "b": 2, "c": 4}, "Expected deep merge semantics")

    policy_path = tmp_path / "ops-policy.json"
    policy_path.write_text(json.dumps({"required_checks": ["CI"], "thresholds": {"main_ci_failure_rate_pct": {"ok_max": 1.0}}}), encoding="utf-8")
    loaded_policy, loaded = module._load_policy(policy_path)
    _expect(loaded is True, "Expected policy loaded flag")
    _expect(loaded_policy["required_checks"] == ["CI"], "Expected loaded required checks")

    # Safe path helper
    root = tmp_path / "workspace"
    root.mkdir(parents=True, exist_ok=True)
    safe = module._safe_workspace_path("docs/out.json", base=root)
    _expect(safe == root / "docs" / "out.json", "Expected relative output path under workspace")
    with pytest.raises(ValueError):
        module._safe_workspace_path("../escape.json", base=root)


def test_generate_ops_digest_main_paths(monkeypatch, tmp_path):
    module = _load_script(_repo_root() / "scripts" / "generate_ops_digest.py", "generate_ops_digest_main_cov_wave")

    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "docs").mkdir(parents=True, exist_ok=True)

    out_json = repo / "tmp" / "digest.json"
    out_md = repo / "tmp" / "digest.md"
    policy = repo / "docs" / "ops-health-policy.json"
    policy.write_text(json.dumps({"required_checks": ["CI"]}), encoding="utf-8")

    # Missing token path
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    def _parse_args_missing_token():
        return type(
            "Args",
            (),
            {
                "repo": "Prekzursil/Reframe",
                "window_days": 7,
                "out_json": str(out_json.relative_to(repo)),
                "out_md": str(out_md.relative_to(repo)),
                "policy": str(policy.relative_to(repo)),
                "api_base": "https://api.github.com",
            },
        )()

    monkeypatch.setattr(module, "parse_args", _parse_args_missing_token)

    prev = Path.cwd()
    os.chdir(repo)
    try:
        with pytest.raises(SystemExit):
            module.main()
    finally:
        os.chdir(prev)

    # Successful run path with fake pagination
    monkeypatch.setenv("GITHUB_TOKEN", "token")

    pulls = [{"created_at": "2026-03-03T00:00:00Z", "merged_at": "2026-03-03T00:00:00Z"}]
    issues = [{"labels": [{"name": "agent:ready"}]}]
    runs = [
        {
            "head_branch": "main",
            "name": "CI",
            "created_at": "2026-03-03T01:00:00Z",
            "run_started_at": "2026-03-03T01:00:00Z",
            "updated_at": "2026-03-03T01:10:00Z",
            "conclusion": "success",
        }
    ]
    seq = [pulls, issues, {"workflow_runs": runs}]
    monkeypatch.setattr(module, "_request_json", lambda _url, _token: (seq.pop(0), None))

    prev = Path.cwd()
    os.chdir(repo)
    try:
        rc = module.main()
    finally:
        os.chdir(prev)

    _expect(rc == 0, "Expected digest main success")
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    _expect(payload["metrics"]["main_ci_failed_runs"] == 0, "Expected successful CI metrics")
    _expect("Weekly Ops Digest" in out_md.read_text(encoding="utf-8"), "Expected markdown output")


def test_assert_coverage_inventory_and_cli_paths(tmp_path, monkeypatch, capsys):
    module = _load_script(_repo_root() / "scripts" / "quality" / "assert_coverage_100.py", "assert_coverage_cov_wave")

    root = tmp_path / "repo"
    root.mkdir(parents=True, exist_ok=True)

    # Build tracked inventory files.
    api_file = root / "apps" / "api" / "app" / "core.py"
    api_file.parent.mkdir(parents=True, exist_ok=True)
    api_file.write_text("VALUE = 1\n", encoding="utf-8")

    web_file = root / "apps" / "web" / "src" / "ui.ts"
    web_file.parent.mkdir(parents=True, exist_ok=True)
    web_file.write_text("export const VALUE = 1;\n", encoding="utf-8")

    rust_file = root / "apps" / "desktop" / "src-tauri" / "src" / "core.rs"
    rust_file.parent.mkdir(parents=True, exist_ok=True)
    rust_file.write_text("pub fn f() {}\n", encoding="utf-8")

    monkeypatch.setattr(
        module,
        "_load_git_tracked_files",
        lambda _root: [
            "apps/api/app/core.py",
            "apps/web/src/ui.ts",
            "apps/desktop/src-tauri/src/core.rs",
        ],
    )

    expected = module._collect_expected_inventory(root)
    _expect("apps/api/app/core.py" in expected, "Expected API file in inventory")
    _expect("apps/web/src/ui.ts" in expected, "Expected web file in inventory")
    _expect("apps/desktop/src-tauri/src/core.rs" in expected, "Expected rust file in inventory")

    # Provide LCOV with one uncovered line to verify findings formatting.
    lcov = root / "coverage" / "lcov.info"
    lcov.parent.mkdir(parents=True, exist_ok=True)
    lcov.write_text(
        "\n".join(
            [
                "TN:",
                f"SF:{web_file.as_posix()}",
                "DA:1,1",
                "DA:2,0",
                "end_of_record",
            ]
        ),
        encoding="utf-8",
    )

    stats = module.parse_lcov("web", lcov, base=root)
    status, findings, metrics = module.evaluate([stats], expected_inventory=expected)
    _expect(status == "fail", "Expected fail status for uncovered inventory")
    _expect(metrics["uncovered_files"] >= 1, "Expected uncovered file metric")
    _expect(any("coverage inventory" in item for item in findings), "Expected inventory findings")

    # Cover CLI success path with --no-inventory-check.
    json_out = root / "out" / "coverage.json"
    md_out = root / "out" / "coverage.md"
    rc = module.main.__wrapped__ if hasattr(module.main, "__wrapped__") else None
    _expect(rc is None, "No wrapper expected")

    def _parse_args_no_inventory():
        return type(
            "Args",
            (),
            {
                "xml": [],
                "lcov": [f"web={lcov}"],
                "out_json": str(json_out),
                "out_md": str(md_out),
                "inventory_root": str(root),
                "no_inventory_check": True,
            },
        )()

    monkeypatch.setattr(module, "_parse_args", _parse_args_no_inventory)
    exit_code = module.main()
    _expect(exit_code == 1, "Expected fail exit code when coverage is below 100")
    _expect(json_out.is_file(), "Expected JSON artifact output")
    _expect(md_out.is_file(), "Expected markdown artifact output")

    text = capsys.readouterr().out
    _expect("Coverage 100 Gate" in text, "Expected CLI markdown output")


def test_assert_coverage_path_helpers_and_named_path_parsing(tmp_path):
    module = _load_script(_repo_root() / "scripts" / "quality" / "assert_coverage_100.py", "assert_cov_helpers_wave")

    with pytest.raises(ValueError):
        module.parse_named_path("invalid")

    name, path = module.parse_named_path("web=coverage/lcov.info")
    _expect(name == "web", "Expected parsed name")
    _expect(path.as_posix() == "coverage/lcov.info", "Expected parsed path")

    root = tmp_path / "workspace"
    root.mkdir(parents=True, exist_ok=True)
    safe = module._safe_output_path("coverage/out.json", "fallback.json", base=root)
    _expect(safe == root / "coverage" / "out.json", "Expected safe path in workspace")

    with pytest.raises(ValueError):
        module._safe_output_path("../escape.json", "fallback.json", base=root)