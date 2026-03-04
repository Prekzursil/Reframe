from __future__ import annotations

import argparse
import os
import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


def _expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _load_quality(name: str):
    repo_root = Path(__file__).resolve().parents[3]
    script_dir = repo_root / "scripts" / "quality"
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))
    module_path = script_dir / f"{name}.py"
    spec = spec_from_file_location(name, module_path)
    _expect(spec is not None and spec.loader is not None, f"Unable to load module spec for {name}")
    module = module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_check_codacy_zero_main_paths(monkeypatch):
    module = _load_quality("check_codacy_zero")

    args = argparse.Namespace(repo="owner/repo", pull_request="", out_json="out/codacy.json", out_md="out/codacy.md")
    monkeypatch.setattr(module, "_parse_args", lambda: args)
    monkeypatch.delenv("CODACY_API_TOKEN", raising=False)
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")

    _expect(module.main() == 1, "Expected missing CODACY_API_TOKEN to fail")

    monkeypatch.setenv("CODACY_API_TOKEN", "token")
    bad_args = argparse.Namespace(repo="bad slug", pull_request="", out_json="out/codacy.json", out_md="out/codacy.md")
    monkeypatch.setattr(module, "_parse_args", lambda: bad_args)
    _expect(module.main() == 1, "Expected invalid repo slug to fail")

    calls = {"count": 0}

    def fake_request(url: str, token: str, *, method: str = "GET", data=None):
        _ = (url, token, method, data)
        calls["count"] += 1
        if calls["count"] == 1:
            return {"analyzed": False, "pagination": {"total": 0}}
        return {"analyzed": True, "pagination": {"total": 0}}

    pr_args = argparse.Namespace(repo="owner/repo", pull_request="107", out_json="out/codacy.json", out_md="out/codacy.md")
    monkeypatch.setattr(module, "_parse_args", lambda: pr_args)
    monkeypatch.setattr(module, "_request_json", fake_request)
    monkeypatch.setattr(module.time, "sleep", lambda _n: None)

    _expect(module.main() == 0, "Expected PR scope to pass when open issues are zero")


def test_check_deepscan_zero_main_paths(monkeypatch):
    module = _load_quality("check_deepscan_zero")

    args = argparse.Namespace(out_json="out/deepscan.json", out_md="out/deepscan.md")
    monkeypatch.setattr(module, "_parse_args", lambda: args)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    _expect(module.main() == 1, "Expected missing GitHub context to fail")

    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setenv("GITHUB_REPOSITORY", "Prekzursil/Reframe")
    monkeypatch.setenv("GITHUB_SHA", "abc123")

    payload = {
        "check_runs": [
            {
                "name": "DeepScan",
                "conclusion": "success",
                "details_url": "https://deepscan.io/analysis",
                "output": {"summary": "0 new and 2 fixed issues"},
                "completed_at": "2026-03-04T00:00:00Z",
            }
        ]
    }
    monkeypatch.setattr(module, "_request_json", lambda _url, _token: payload)

    _expect(module.main() == 0, "Expected DeepScan zero-main path to pass")




def test_check_deepscan_zero_status_context_fallback(monkeypatch):
    module = _load_quality("check_deepscan_zero")

    args = argparse.Namespace(out_json="out/deepscan-status.json", out_md="out/deepscan-status.md")
    monkeypatch.setattr(module, "_parse_args", lambda: args)
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setenv("GITHUB_REPOSITORY", "Prekzursil/Reframe")
    monkeypatch.setenv("GITHUB_SHA", "abc123")

    def fake_request(url: str, _token: str):
        if "check-runs" in url:
            return {"check_runs": []}
        return {
            "statuses": [
                {
                    "context": "DeepScan",
                    "state": "success",
                    "description": "0 new and 1 fixed issues",
                    "target_url": "https://deepscan.io/dashboard",
                    "updated_at": "2026-03-04T01:00:00Z",
                }
            ]
        }

    monkeypatch.setattr(module, "_request_json", fake_request)

    _expect(module.main() == 0, "Expected status-context fallback to pass when new issues are zero")


def test_check_sentry_zero_main_paths(monkeypatch):
    module = _load_quality("check_sentry_zero")
    args = argparse.Namespace(out_json="out/sentry.json", out_md="out/sentry.md")
    monkeypatch.setattr(module, "_parse_args", lambda: args)

    monkeypatch.delenv("SENTRY_AUTH_TOKEN", raising=False)
    monkeypatch.setenv("SENTRY_ORG", "andrei-visalon")
    monkeypatch.setenv("SENTRY_PROJECT_BACKEND", "reframe-backend")
    monkeypatch.setenv("SENTRY_PROJECT_WEB", "reframe-web")
    _expect(module.main() == 1, "Expected missing token to fail")

    monkeypatch.setenv("SENTRY_AUTH_TOKEN", "token")

    def fake_request(_url: str, _token: str):
        return [], {"x-hits": "0"}

    monkeypatch.setattr(module, "_request", fake_request)
    _expect(module.main() == 0, "Expected sentry zero check to pass when unresolved=0")


def test_check_sonar_zero_main_paths(monkeypatch):
    module = _load_quality("check_sonar_zero")

    args = argparse.Namespace(
        project_key="Prekzursil_Reframe",
        token="",
        branch="",
        pull_request="107",
        wait_seconds=0,
        require_quality_gate=True,
        ignore_open_issues=False,
        out_json="out/sonar.json",
        out_md="out/sonar.md",
    )
    monkeypatch.setattr(module, "_parse_args", lambda: args)
    monkeypatch.delenv("SONAR_TOKEN", raising=False)
    _expect(module.main() == 1, "Expected missing SONAR_TOKEN to fail")

    monkeypatch.setenv("SONAR_TOKEN", "token")
    monkeypatch.setattr(module, "_query_sonar_status", lambda **_kwargs: (0, "OK"))
    _expect(module.main() == 0, "Expected sonar zero to pass with open issues 0 and gate OK")


def test_check_required_checks_main_paths(monkeypatch):
    module = _load_quality("check_required_checks")
    args = argparse.Namespace(
        repo="Prekzursil/Reframe",
        sha="1234",
        required_context=["CI", "Coverage 100 Gate"],
        timeout_seconds=1,
        poll_seconds=1,
        out_json="out/required.json",
        out_md="out/required.md",
    )
    monkeypatch.setattr(module, "_parse_args", lambda: args)

    monkeypatch.setenv("GITHUB_TOKEN", "token")

    def fake_api_get(repo: str, path: str, token: str):
        _ = (repo, token)
        if "check-runs" in path:
            return {
                "check_runs": [
                    {"name": "CI", "status": "completed", "conclusion": "success"},
                    {"name": "Coverage 100 Gate", "status": "completed", "conclusion": "success"},
                ]
            }
        return {"statuses": []}

    monkeypatch.setattr(module, "_api_get", fake_api_get)

    _expect(module.main() == 0, "Expected required-checks gate to pass with all contexts successful")


def test_check_visual_zero_percy_and_applitools(monkeypatch, tmp_path):
    module = _load_quality("check_visual_zero")

    percy_args = argparse.Namespace(
        provider="percy",
        sha="abc1234",
        branch="feat",
        percy_token="token",
        applitools_results="",
        out_json="tmp/percy.json",
        out_md="tmp/percy.md",
    )
    monkeypatch.setattr(module, "_parse_args", lambda: percy_args)

    payload = {
        "data": [
            {
                "id": "build-1",
                "attributes": {
                    "created-at": "2026-03-04T00:00:00Z",
                    "review-state": "approved",
                    "total-comparisons-diff": 0,
                },
            }
        ]
    }
    monkeypatch.setattr(module, "_percy_request", lambda *_args, **_kwargs: payload)
    monkeypatch.setattr(module.time, "sleep", lambda _n: None)

    _expect(module.main() == 0, "Expected Percy visual check to pass")

    applitools_json = Path("tmp/applitools-input.json")
    applitools_json.parent.mkdir(parents=True, exist_ok=True)
    applitools_json.write_text('{"unresolved":0,"mismatches":0,"missing":0}', encoding="utf-8")

    applitools_args = argparse.Namespace(
        provider="applitools",
        sha="",
        branch="",
        percy_token="",
        applitools_results=str(applitools_json),
        out_json="tmp/applitools-out.json",
        out_md="tmp/applitools-out.md",
    )
    monkeypatch.setattr(module, "_parse_args", lambda: applitools_args)
    _expect(module.main() == 0, "Expected Applitools visual check to pass")


def test_percy_auto_approve_paths(monkeypatch):
    module = _load_quality("percy_auto_approve")

    monkeypatch.delenv("PERCY_TOKEN", raising=False)
    _expect(module.main(["--sha", "abcdef1"]) == 1, "Expected missing token path to fail")

    monkeypatch.setenv("PERCY_TOKEN", "token")
    _expect(module.main(["--sha", "bad-sha"]) == 1, "Expected invalid SHA to fail")

    monkeypatch.setattr(module, "_query_builds", lambda **_kwargs: {"data": []})
    monkeypatch.setattr(module.time, "sleep", lambda _n: None)
    _expect(
        module.main(["--sha", "abcdef1", "--retry-attempts", "1", "--retry-delay-seconds", "1"]) == 0,
        "Expected no-unreviewed-build path to be informational pass",
    )

    posted = {"called": False}

    def fake_query(**_kwargs):
        return {
            "data": [
                {
                    "id": "b1",
                    "attributes": {"state": "finished", "review-state": "unreviewed", "created-at": "2026-03-04"},
                }
            ]
        }

    def fake_request_json(*, token, method, path, query=None, payload=None, basic_auth=None):
        _ = (token, query, basic_auth)
        if method == "POST":
            posted["called"] = True
            _expect(path == "/reviews", "Expected reviews endpoint for approval")
            _expect(payload is not None, "Expected review payload")
        return {"data": []}

    monkeypatch.setattr(module, "_query_builds", fake_query)
    monkeypatch.setattr(module, "_request_json", fake_request_json)

    rc = module.main(["--sha", "abcdef1", "--retry-attempts", "1", "--retry-delay-seconds", "1"])
    _expect(rc == 0, "Expected successful Percy auto-approval")
    _expect(posted["called"], "Expected approval POST to be executed")
