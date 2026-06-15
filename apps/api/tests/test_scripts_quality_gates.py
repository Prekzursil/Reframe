from __future__ import annotations

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
