from __future__ import annotations

import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


def _expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _load_module():
    repo_root = Path(__file__).resolve().parents[3]
    module_path = repo_root / "scripts" / "strict23_preflight.py"
    spec = spec_from_file_location("strict23_preflight", module_path)
    _expect(spec is not None and spec.loader is not None, "Unable to load strict23_preflight module spec")
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

    _expect(result.status == "compliant", "Expected compliant status when all canonical contexts are present")
    _expect(result.findings == [], "Expected no findings for compliant context set")
    _expect(result.missing_in_branch_protection == [], "Expected no missing branch-protection contexts")
    _expect(result.missing_in_check_runs == [], "Expected no missing emitted contexts")
    _expect(result.ref_sha == "abc123", "Expected ref SHA to be carried into result payload")


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

    _expect(result.status == "non_compliant", "Expected non-compliant status when canonical contexts are missing")
    _expect(
        result.missing_in_branch_protection == ["CodeRabbit", "backend"],
        "Expected missing branch-protection contexts to be deterministic",
    )
    _expect(
        result.missing_in_check_runs == ["CodeRabbit"],
        "Expected emitted missing contexts to be deterministic",
    )
    _expect(
        any("missing from branch protection" in finding for finding in result.findings),
        "Expected branch-protection finding in result output",
    )
    _expect(
        any("missing from emitted checks" in finding for finding in result.findings),
        "Expected emitted-context finding in result output",
    )


def test_classify_http_status_maps_permission_codes_to_inconclusive():
    module = _load_module()

    _expect(module._classify_http_status(401) == "inconclusive_permissions", "401 should map to inconclusive_permissions")
    _expect(module._classify_http_status(403) == "inconclusive_permissions", "403 should map to inconclusive_permissions")
    _expect(module._classify_http_status(404) == "inconclusive_permissions", "404 should map to inconclusive_permissions")
    _expect(module._classify_http_status(500) == "api_error", "500 should map to api_error")
