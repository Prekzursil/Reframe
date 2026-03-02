from __future__ import annotations

import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


def _load_module():
    repo_root = Path(__file__).resolve().parents[3]
    module_path = repo_root / "scripts" / "strict23_preflight.py"
    spec = spec_from_file_location("strict23_preflight", module_path)
    assert spec and spec.loader
    module = module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_evaluate_contexts_compliant_when_all_canonical_present():
    module = _load_module()
    canonical = ["CodeQL", "CodeRabbit", "backend"]
    required = ["CodeQL", "CodeRabbit", "backend", "extra-context"]
    emitted = ["CodeQL", "CodeRabbit", "backend", "another-context"]

    result = module.evaluate_contexts(
        canonical_contexts=canonical,
        branch_required_checks=required,
        emitted_contexts=emitted,
        ref_sha="abc123",
    )

    assert result.status == "compliant"
    assert result.findings == []
    assert result.missing_in_branch_protection == []
    assert result.missing_in_check_runs == []
    assert result.ref_sha == "abc123"


def test_evaluate_contexts_non_compliant_when_contexts_missing():
    module = _load_module()
    canonical = ["CodeQL", "CodeRabbit", "backend"]
    required = ["CodeQL"]
    emitted = ["CodeQL", "backend"]

    result = module.evaluate_contexts(
        canonical_contexts=canonical,
        branch_required_checks=required,
        emitted_contexts=emitted,
        ref_sha="def456",
    )

    assert result.status == "non_compliant"
    assert result.missing_in_branch_protection == ["CodeRabbit", "backend"]
    assert result.missing_in_check_runs == ["CodeRabbit"]
    assert any("missing from branch protection" in finding for finding in result.findings)
    assert any("missing from emitted checks" in finding for finding in result.findings)


def test_classify_http_status_maps_permission_codes_to_inconclusive():
    module = _load_module()

    assert module._classify_http_status(401) == "inconclusive_permissions"
    assert module._classify_http_status(403) == "inconclusive_permissions"
    assert module._classify_http_status(404) == "inconclusive_permissions"
    assert module._classify_http_status(500) == "api_error"
