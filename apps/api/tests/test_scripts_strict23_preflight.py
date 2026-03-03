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
    required = ["CodeQL", "CodeRabbit", "backend"]
    optional = ["DeepScan"]
    emitted = ["CodeQL", "CodeRabbit", "backend", "another-context"]

    result = module.evaluate_contexts(
        required_contexts=required,
        optional_contexts=optional,
        branch_required_checks=required,
        emitted_contexts=emitted,
        ref_sha="abc123",
    )

    _expect(result.status == "compliant", "Expected compliant status when all canonical contexts are present")
    _expect(
        any("Optional contexts missing from emitted checks on ref" in finding for finding in result.findings),
        "Expected optional-missing finding for missing optional context",
    )
    _expect(result.missing_in_branch_protection == [], "Expected no missing branch-protection contexts")
    _expect(result.missing_in_check_runs == [], "Expected no missing emitted contexts")
    _expect(result.missing_optional_contexts == ["DeepScan"], "Expected missing optional contexts to be reported")
    _expect(result.ref_sha == "abc123", "Expected ref SHA to be carried into result payload")


def test_evaluate_contexts_non_compliant_when_contexts_missing():
    module = _load_module()
    required_contexts = ["CodeQL", "CodeRabbit", "backend"]
    required = ["CodeQL"]
    emitted = ["CodeQL", "backend"]

    result = module.evaluate_contexts(
        required_contexts=required_contexts,
        optional_contexts=[],
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


def test_context_sets_from_policy_reads_required_and_optional_supplemental():
    module = _load_module()
    policy = {
        "required_status_checks": ["CodeQL", "CodeRabbit"],
        "strict23_supplemental_contexts": {
            "required": ["backend"],
            "optional": ["DeepScan", "SonarCloud"],
        },
    }
    required, optional = module._context_sets_from_policy(policy)
    _expect(required == ["CodeQL", "CodeRabbit", "backend"], "Expected required list to include policy + required supplemental")
    _expect(optional == ["DeepScan", "SonarCloud"], "Expected optional supplemental contexts to be preserved")


def test_main_missing_token_is_inconclusive_permissions(tmp_path, monkeypatch):
    module = _load_module()
    policy_path = tmp_path / "policy.json"
    out_json = tmp_path / "preflight.json"
    out_md = tmp_path / "preflight.md"
    policy_path.write_text(
        '{"required_status_checks":["CodeQL"],"strict23_supplemental_contexts":{"required":[],"optional":["DeepScan"]}}',
        encoding="utf-8",
    )
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "strict23_preflight.py",
            "--repo",
            "Prekzursil/Reframe",
            "--branch",
            "main",
            "--ref",
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
    payload = module.json.loads(out_json.read_text(encoding="utf-8"))
    markdown = out_md.read_text(encoding="utf-8")

    _expect(exit_code == 0, "Missing token should be non-fatal as inconclusive permissions")
    _expect(payload["status"] == "inconclusive_permissions", "Expected inconclusive status in JSON payload")
    _expect(payload["required_contexts"] == ["CodeQL"], "Expected required contexts resolved from policy")
    _expect(payload["optional_contexts"] == ["DeepScan"], "Expected optional contexts resolved from policy")
    _expect("Status: `inconclusive_permissions`" in markdown, "Expected inconclusive status in markdown output")


def test_default_canonical_contexts_drop_vercel_and_include_current_core_checks():
    module = _load_module()
    defaults = module.DEFAULT_CANONICAL_CONTEXTS

    _expect("Vercel" not in defaults, "Vercel should not be part of strict canonical fallback contexts")
    _expect(
        "Vercel Preview Comments" not in defaults,
        "Vercel Preview Comments should not be part of strict canonical fallback contexts",
    )
    _expect("Analyze (actions)" in defaults, "Expected Analyze (actions) in strict canonical fallback contexts")
    _expect(
        "Analyze (javascript-typescript)" in defaults,
        "Expected Analyze (javascript-typescript) in strict canonical fallback contexts",
    )
    _expect("Analyze (python)" in defaults, "Expected Analyze (python) in strict canonical fallback contexts")
    _expect("SonarCloud Code Analysis" in defaults, "Expected SonarCloud Code Analysis in strict canonical fallback contexts")
    _expect("Coverage 100 Gate" in defaults, "Expected Coverage 100 Gate in strict canonical fallback contexts")
    _expect("Quality Zero Gate" in defaults, "Expected Quality Zero Gate in strict canonical fallback contexts")
