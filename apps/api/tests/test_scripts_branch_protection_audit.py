from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


def _load_module():
    repo_root = Path(__file__).resolve().parents[3]
    module_path = repo_root / "scripts" / "audit_branch_protection.py"
    spec = spec_from_file_location("audit_branch_protection", module_path)
    assert spec and spec.loader
    module = module_from_spec(spec)
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

    assert result.status == "pass"
    assert result.findings == []
    assert result.missing_status_checks == []


def test_evaluate_protection_payload_reports_missing_controls():
    module = _load_module()
    payload = {
        "required_pull_request_reviews": {"required_approving_review_count": 0},
        "required_status_checks": {"contexts": ["Web build"]},
        "required_linear_history": {"enabled": False},
        "required_conversation_resolution": {"enabled": False},
    }

    result = module.evaluate_protection_payload(payload, _policy())

    assert result.status == "fail"
    assert "Missing required status check: Python API & worker checks" in result.findings
    assert "Missing required status check: CodeQL" in result.findings
    assert "Missing required status check: CodeRabbit" in result.findings
    assert "Linear history is disabled." in result.findings
    assert "Conversation resolution is disabled." in result.findings


def test_classify_http_status_maps_permission_codes_to_inconclusive():
    module = _load_module()

    assert module._classify_http_status(401) == "inconclusive_permissions"
    assert module._classify_http_status(403) == "inconclusive_permissions"
    assert module._classify_http_status(404) == "inconclusive_permissions"
    assert module._classify_http_status(500) == "api_error"
