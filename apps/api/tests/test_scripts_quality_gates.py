from __future__ import annotations

import os
import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


def _expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _load_module(name: str):
    repo_root = Path(__file__).resolve().parents[3]
    module_path = repo_root / "scripts" / "quality" / f"{name}.py"
    spec = spec_from_file_location(name, module_path)
    _expect(spec is not None and spec.loader is not None, f"Unable to load module spec for {name}")
    module = module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_quality_secrets_evaluate_env_reports_missing(monkeypatch):
    module = _load_module("check_quality_secrets")
    monkeypatch.setenv("SONAR_TOKEN", "x")
    monkeypatch.delenv("CODECOV_TOKEN", raising=False)

    result = module.evaluate_env(["SONAR_TOKEN", "CODECOV_TOKEN"], ["SENTRY_ORG"])

    _expect(result["missing_secrets"] == ["CODECOV_TOKEN"], "Expected CODECOV_TOKEN to be missing")
    _expect(result["present_secrets"] == ["SONAR_TOKEN"], "Expected SONAR_TOKEN to be present")
    _expect(result["missing_vars"] == ["SENTRY_ORG"], "Expected SENTRY_ORG variable to be missing")


def test_assert_coverage_100_parses_xml_and_lcov(tmp_path):
    module = _load_module("assert_coverage_100")

    xml_path = tmp_path / "coverage.xml"
    xml_path.write_text('<coverage lines-covered="50" lines-valid="50"/>', encoding="utf-8")

    lcov_path = tmp_path / "lcov.info"
    lcov_path.write_text("TN:\nSF:file.ts\nLF:10\nLH:10\nend_of_record\n", encoding="utf-8")

    xml_stats = module.parse_coverage_xml("api", xml_path)
    lcov_stats = module.parse_lcov("web", lcov_path)

    _expect(xml_stats.percent == 100.0, "Expected XML coverage percent to be 100")
    _expect(lcov_stats.percent == 100.0, "Expected LCOV coverage percent to be 100")

    status, findings = module.evaluate([xml_stats, lcov_stats])
    _expect(status == "pass", "Expected pass when all components are at 100%")
    _expect(findings == [], "Expected no findings for full coverage")


def test_assert_coverage_100_detects_below_target(tmp_path):
    module = _load_module("assert_coverage_100")

    lcov_path = tmp_path / "lcov.info"
    lcov_path.write_text("TN:\nSF:file.ts\nLF:4\nLH:3\nend_of_record\n", encoding="utf-8")
    stats = module.parse_lcov("web", lcov_path)

    status, findings = module.evaluate([stats])
    _expect(status == "fail", "Expected fail when a component is below 100%")
    _expect(any("below 100%" in item for item in findings), "Expected below-100 finding")


def test_codacy_extract_total_open_from_nested_payload():
    module = _load_module("check_codacy_zero")

    payload = {"data": [{"id": "x"}], "pagination": {"total": 7}}
    total = module.extract_total_open(payload)

    _expect(total == 7, "Expected nested pagination.total to be extracted")


def test_deepscan_extract_new_and_fixed_counts():
    module = _load_module("check_deepscan_zero")

    new_issues, fixed_issues = module.extract_new_fixed_counts("0 new and 7 fixed issues")

    _expect(new_issues == 0, "Expected new issues count to be parsed")
    _expect(fixed_issues == 7, "Expected fixed issues count to be parsed")


def test_required_context_evaluate_flags_missing_and_failed():
    module = _load_module("check_required_checks")

    status, missing, failed = module._evaluate(
        ["A", "B", "C"],
        {
            "A": {"source": "check_run", "state": "completed", "conclusion": "success"},
            "B": {"source": "check_run", "state": "completed", "conclusion": "failure"},
        },
    )

    _expect(status == "fail", "Expected fail status")
    _expect(missing == ["C"], "Expected C to be missing")
    _expect(any(item.startswith("B:") for item in failed), "Expected B to be reported as failed")


def test_visual_percy_diff_parser_reads_numeric_values():
    module = _load_module("check_visual_zero")

    diff = module._parse_percy_diff_count({"total-comparisons-diff": "2"})
    _expect(diff == 2, "Expected Percy diff parser to read string integer")


def test_sentry_hits_from_headers_parses_integer():
    module = _load_module("check_sentry_zero")

    hits = module._hits_from_headers({"x-hits": "11"})
    _expect(hits == 11, "Expected x-hits header value to be parsed")
