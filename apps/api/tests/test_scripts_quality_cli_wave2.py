from __future__ import annotations

import argparse
import json
import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest


def _expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _load_quality(name: str):
    script_path = _repo_root() / "scripts" / "quality" / f"{name}.py"
    spec = spec_from_file_location(f"quality_{name}_wave2", script_path)
    _expect(spec is not None and spec.loader is not None, f"Unable to load module spec for {name}")
    module = module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_script(name: str):
    script_path = _repo_root() / "scripts" / f"{name}.py"
    spec = spec_from_file_location(f"script_{name}_wave2", script_path)
    _expect(spec is not None and spec.loader is not None, f"Unable to load module spec for {name}")
    module = module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_check_quality_secrets_main_pass_and_fail(monkeypatch):
    module = _load_quality("check_quality_secrets")
    repo = _repo_root()

    out_json_rel = "tmp/quality-wave2/check-quality-secrets.json"
    out_md_rel = "tmp/quality-wave2/check-quality-secrets.md"
    out_json = repo / out_json_rel
    out_md = repo / out_md_rel

    monkeypatch.setattr(
        module,
        "_parse_args",
        lambda: argparse.Namespace(required_secret=[], required_var=[], out_json=out_json_rel, out_md=out_md_rel),
    )

    for name in module.DEFAULT_REQUIRED_SECRETS:
        monkeypatch.setenv(name, "x")
    for name in module.DEFAULT_REQUIRED_VARS:
        monkeypatch.setenv(name, "x")

    rc = module.main()
    _expect(rc == 0, "Expected pass when all secrets/vars are set")
    _expect(out_json.is_file(), "Expected JSON output file")
    _expect(out_md.is_file(), "Expected markdown output file")

    monkeypatch.delenv(module.DEFAULT_REQUIRED_SECRETS[0], raising=False)
    rc_fail = module.main()
    _expect(rc_fail == 1, "Expected fail when a required secret is missing")


def test_check_quality_secrets_safe_output_path_escape():
    module = _load_quality("check_quality_secrets")
    with pytest.raises(ValueError):
        module._safe_output_path("../escape.json", "fallback.json", base=Path.cwd())


def test_check_required_checks_main_success_and_missing_token(monkeypatch):
    module = _load_quality("check_required_checks")
    repo = _repo_root()

    out_json_rel = "tmp/quality-wave2/required-checks.json"
    out_md_rel = "tmp/quality-wave2/required-checks.md"
    out_json = repo / out_json_rel
    out_md = repo / out_md_rel

    calls = {"count": 0}

    def fake_api_get(_repo: str, path: str, _token: str):
        calls["count"] += 1
        if "check-runs" in path:
            if calls["count"] <= 2:
                return {"check_runs": [{"name": "Coverage 100 Gate", "status": "in_progress", "conclusion": None}]}
            return {"check_runs": [{"name": "Coverage 100 Gate", "status": "completed", "conclusion": "success"}]}
        return {"statuses": []}

    monkeypatch.setattr(module, "_api_get", fake_api_get)
    monkeypatch.setattr(module.time, "sleep", lambda _s: None)
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setattr(
        module,
        "_parse_args",
        lambda: argparse.Namespace(
            repo="Prekzursil/Reframe",
            sha="abc123",
            required_context=["Coverage 100 Gate"],
            timeout_seconds=5,
            poll_seconds=1,
            out_json=out_json_rel,
            out_md=out_md_rel,
        ),
    )

    rc = module.main()
    _expect(rc == 0, "Expected success after in-progress then successful check run")
    _expect(out_json.is_file(), "Expected required-check JSON artifact")
    _expect(out_md.is_file(), "Expected required-check markdown artifact")

    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    with pytest.raises(SystemExit):
        module.main()


def test_check_codacy_zero_main_paths(monkeypatch):
    module = _load_quality("check_codacy_zero")
    repo = _repo_root()

    out_json_rel = "tmp/quality-wave2/codacy.json"
    out_md_rel = "tmp/quality-wave2/codacy.md"
    out_json = repo / out_json_rel

    monkeypatch.delenv("CODACY_API_TOKEN", raising=False)
    monkeypatch.setattr(
        module,
        "_parse_args",
        lambda: argparse.Namespace(repo="Prekzursil/Reframe", pull_request="", out_json=out_json_rel, out_md=out_md_rel),
    )
    rc_missing = module.main()
    _expect(rc_missing == 1, "Expected fail when CODACY_API_TOKEN is missing")

    monkeypatch.setenv("CODACY_API_TOKEN", "token")

    def fake_request(url: str, token: str, *, method: str = "GET", data=None):
        _ = (url, token, method, data)
        return {"pagination": {"total": 0}}

    monkeypatch.setattr(module, "_request_json", fake_request)
    rc_repo = module.main()
    _expect(rc_repo == 0, "Expected pass when repository open issues == 0")
    _expect(out_json.is_file(), "Expected codacy JSON output")

    monkeypatch.setattr(
        module,
        "_parse_args",
        lambda: argparse.Namespace(repo="Prekzursil/Reframe", pull_request="abc", out_json=out_json_rel, out_md=out_md_rel),
    )
    rc_invalid_pr = module.main()
    _expect(rc_invalid_pr == 1, "Expected fail for invalid pull request number")


def test_check_sonar_zero_main_wait_and_exception(monkeypatch):
    module = _load_quality("check_sonar_zero")

    repo = _repo_root()
    out_json_rel = "tmp/quality-wave2/sonar.json"
    out_md_rel = "tmp/quality-wave2/sonar.md"
    _ = (repo / out_json_rel, repo / out_md_rel)

    sequence = iter([(2, "ERROR"), (0, "OK")])

    def fake_query(**_kwargs):
        return next(sequence)

    monkeypatch.setattr(module, "_query_sonar_status", fake_query)
    monkeypatch.setattr(module.time, "sleep", lambda _s: None)
    monkeypatch.setenv("SONAR_TOKEN", "token")
    monkeypatch.setattr(
        module,
        "_parse_args",
        lambda: argparse.Namespace(
            project_key="Prekzursil_Reframe",
            token="",
            branch="",
            pull_request="107",
            wait_seconds=15,
            require_quality_gate=True,
            ignore_open_issues=False,
            out_json=out_json_rel,
            out_md=out_md_rel,
        ),
    )

    rc_wait = module.main()
    _expect(rc_wait == 0, "Expected Sonar pass after wait loop resolves to zero")

    monkeypatch.setattr(module, "_query_sonar_status", lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
    rc_exc = module.main()
    _expect(rc_exc == 1, "Expected Sonar fail on query exception")


def test_check_visual_zero_percy_and_applitools_paths(monkeypatch, tmp_path):
    module = _load_quality("check_visual_zero")

    monkeypatch.setenv("PERCY_TOKEN", "token")
    monkeypatch.setenv("GITHUB_SHA", "abc1234")
    monkeypatch.setattr(module, "_percy_request", lambda _path, _token, query=None: {"data": []})
    clock = {"t": 0.0}
    monkeypatch.setattr(module.time, "monotonic", lambda: clock.__setitem__("t", clock["t"] + 301.0) or clock["t"])
    monkeypatch.setattr(module.time, "sleep", lambda _s: None)
    status, details, findings = module._run_percy(argparse.Namespace(percy_token="", sha="", branch="main"))
    _expect(status == "pass", "Expected pass when Percy build is unavailable")
    _expect(details.get("lookup_mode") == "unavailable", "Expected unavailable lookup mode")
    _expect(findings, "Expected informational finding")

    monkeypatch.setattr(
        module,
        "_percy_request",
        lambda _path, _token, query=None: {
            "data": [
                {
                    "id": "1",
                    "attributes": {
                        "created-at": "2026-03-04T00:00:00Z",
                        "review-state": "unreviewed",
                        "total-comparisons-diff": 2,
                    },
                }
            ]
        },
    )
    monkeypatch.setattr(module.time, "monotonic", lambda: 0.0)
    status_fail, _details_fail, findings_fail = module._run_percy(argparse.Namespace(percy_token="", sha="abc1234", branch="main"))
    _expect(status_fail == "fail", "Expected fail for unresolved Percy diffs")
    _expect(any("unresolved visual diffs" in item for item in findings_fail), "Expected unresolved diff finding")

    missing_status, _missing_details, _missing_findings = module._run_applitools(
        argparse.Namespace(applitools_results="", provider="applitools")
    )
    _expect(missing_status == "fail", "Expected fail when applitools results path is missing")

    results_path = _repo_root() / "tmp" / "quality-wave2" / "applitools.json"
    results_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.write_text(json.dumps({"unresolved": 0, "mismatches": 0, "missing": 0}), encoding="utf-8")
    ok_status, _ok_details, ok_findings = module._run_applitools(
        argparse.Namespace(applitools_results="tmp/quality-wave2/applitools.json", provider="applitools")
    )
    _expect(ok_status == "pass", "Expected pass when applitools metrics are zero")
    _expect(ok_findings == [], "Expected no findings for zero applitools metrics")


def test_percy_auto_approve_main_paths(monkeypatch, capsys):
    module = _load_quality("percy_auto_approve")

    monkeypatch.delenv("PERCY_TOKEN", raising=False)
    rc_missing = module.main(["--sha", "abc1234"])
    _expect(rc_missing == 1, "Expected missing token failure")

    monkeypatch.setenv("PERCY_TOKEN", "token")
    rc_bad_sha = module.main(["--sha", "not-sha"])
    _expect(rc_bad_sha == 1, "Expected invalid SHA failure")

    monkeypatch.setattr(module, "_query_builds", lambda **_kwargs: {"data": []})
    rc_no_build = module.main(["--sha", "abc1234", "--retry-attempts", "1"])
    _expect(rc_no_build == 0, "Expected no-build path to be informational success")

    requested = {"approved": False}

    def fake_request_json(**kwargs):
        if kwargs.get("method") == "POST" and kwargs.get("path") == "/reviews":
            requested["approved"] = True
            return {"ok": True}
        return {}

    monkeypatch.setattr(
        module,
        "_query_builds",
        lambda **_kwargs: {
            "data": [
                {
                    "id": "build-1",
                    "attributes": {
                        "created-at": "2026-03-04T00:00:00Z",
                        "state": "finished",
                        "review-state": "unreviewed",
                    },
                }
            ]
        },
    )
    monkeypatch.setattr(module, "_request_json", fake_request_json)

    rc_approve = module.main(["--sha", "abc1234", "--retry-attempts", "1"])
    _expect(rc_approve == 0, "Expected build approval path success")
    _expect(requested["approved"], "Expected Percy review approval POST")
    _expect("approved=true" in capsys.readouterr().out, "Expected approved output marker")


def test_upsert_ops_digest_main_error_paths(monkeypatch):
    module = _load_script("upsert_ops_digest_issue")
    repo = _repo_root()

    digest_json_rel = "tmp/quality-wave2/digest.json"
    digest_md_rel = "tmp/quality-wave2/digest.md"
    out_json_rel = "tmp/quality-wave2/digest-out.json"

    digest_json = repo / digest_json_rel
    digest_md = repo / digest_md_rel
    digest_json.parent.mkdir(parents=True, exist_ok=True)
    digest_json.write_text(json.dumps({"metrics": {}, "trends": {}, "health": {}}), encoding="utf-8")
    digest_md.write_text("# digest\n", encoding="utf-8")

    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.setattr(
        module,
        "parse_args",
        lambda: argparse.Namespace(
            repo="Prekzursil/Reframe",
            digest_json=digest_json_rel,
            digest_md=digest_md_rel,
            out_json=out_json_rel,
            title="Weekly Ops Digest (rolling)",
        ),
    )
    with pytest.raises(SystemExit):
        module.main()

    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setattr(
        module,
        "parse_args",
        lambda: argparse.Namespace(
            repo="invalid-repo",
            digest_json=digest_json_rel,
            digest_md=digest_md_rel,
            out_json=out_json_rel,
            title="Weekly Ops Digest (rolling)",
        ),
    )
    with pytest.raises(SystemExit):
        module.main()


def test_release_readiness_run_json_and_collect_status(monkeypatch, tmp_path):
    module = _load_script("release_readiness_report")

    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: (_ for _ in ()).throw(FileNotFoundError("missing")))
    _expect(module._run_json(["gh"], cwd=tmp_path) is None, "Expected None when subprocess binary is missing")

    monkeypatch.setattr(module, "_main_sha", lambda _repo: "abc")
    monkeypatch.setattr(module, "_run_json", lambda _cmd, cwd: {"unexpected": True})
    status = module._collect_gh_status(tmp_path)
    _expect(status["ci"] is None and status["codeql"] is None, "Expected null workflow snapshots for malformed runs payload")
    _expect(isinstance(status["branch_protection"], dict), "Expected branch protection payload dictionary")
    _expect(status["branch_protection"].get("required_reviews") is None, "Expected missing required_reviews for malformed payload")





