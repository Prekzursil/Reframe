from __future__ import annotations

import json
import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


def _expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _load_module():
    repo_root = Path(__file__).resolve().parents[3]
    module_path = repo_root / "scripts" / "audit_branch_protection.py"
    spec = spec_from_file_location("audit_branch_protection", module_path)
    _expect(spec is not None and spec.loader is not None, "Unable to load audit_branch_protection module spec")
    module = module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _policy() -> dict:
    return {
        "required_approving_review_count": 1,
        "required_status_checks": [
            "Python API & worker checks",
            "Web build",
            "CodeQL",
            "CodeRabbit",
        ],
        "require_linear_history": True,
        "require_conversation_resolution": True,
    }


def test_evaluate_protection_payload_passes_when_policy_is_met():
    module = _load_module()
    payload = {
        "required_pull_request_reviews": {"required_approving_review_count": 1},
        "required_status_checks": {
            "contexts": [
                "Python API & worker checks",
                "Web build",
                "CodeQL",
                "CodeRabbit",
            ]
        },
        "required_linear_history": {"enabled": True},
        "required_conversation_resolution": {"enabled": True},
    }

    result = module.evaluate_protection_payload(payload, _policy())

    _expect(result.status == "pass", "Expected pass status when policy requirements are met")
    _expect(result.findings == [], "Expected no findings when policy requirements are met")
    _expect(result.missing_status_checks == [], "Expected no missing status checks")


def test_evaluate_protection_payload_reports_missing_controls():
    module = _load_module()
    payload = {
        "required_pull_request_reviews": {"required_approving_review_count": 0},
        "required_status_checks": {"contexts": ["Web build"]},
        "required_linear_history": {"enabled": False},
        "required_conversation_resolution": {"enabled": False},
    }

    result = module.evaluate_protection_payload(payload, _policy())

    _expect(result.status == "fail", "Expected fail status for policy drift payload")
    _expect(
        "Missing required status check: Python API & worker checks" in result.findings,
        "Expected finding for missing Python API & worker checks context",
    )
    _expect(
        "Missing required status check: CodeQL" in result.findings,
        "Expected finding for missing CodeQL context",
    )
    _expect(
        "Missing required status check: CodeRabbit" in result.findings,
        "Expected finding for missing CodeRabbit context",
    )
    _expect("Linear history is disabled." in result.findings, "Expected finding for disabled linear history")
    _expect(
        "Conversation resolution is disabled." in result.findings,
        "Expected finding for disabled conversation resolution",
    )


def test_classify_http_status_maps_permission_codes_to_inconclusive():
    module = _load_module()

    _expect(module._classify_http_status(401) == "inconclusive_permissions", "401 should map to inconclusive_permissions")
    _expect(module._classify_http_status(403) == "inconclusive_permissions", "403 should map to inconclusive_permissions")
    _expect(module._classify_http_status(404) == "inconclusive_permissions", "404 should map to inconclusive_permissions")
    _expect(module._classify_http_status(500) == "api_error", "500 should map to api_error")


def test_main_emits_inconclusive_permissions_when_token_missing(tmp_path, monkeypatch):
    module = _load_module()
    policy_path = tmp_path / "policy.json"
    out_json = tmp_path / "audit.json"
    out_md = tmp_path / "audit.md"
    policy_path.write_text(json.dumps(_policy()), encoding="utf-8")

    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "audit_branch_protection.py",
            "--repo",
            "Prekzursil/Reframe",
            "--branch",
            "main",
            "--policy",
            str(policy_path),
            "--out-json",
            str(out_json),
            "--out-md",
            str(out_md),
        ],
    )

    exit_code = module.main()
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    markdown = out_md.read_text(encoding="utf-8")

    _expect(exit_code == 0, "Missing-token path should be non-fatal (inconclusive_permissions)")
    _expect(payload["status"] == "inconclusive_permissions", "Expected inconclusive_permissions status in JSON payload")
    _expect(
        "GitHub token is missing" in (payload["findings"][0] if payload["findings"] else ""),
        "Expected missing-token finding in payload",
    )
    _expect("Status: `inconclusive_permissions`" in markdown, "Expected inconclusive status in markdown output")
