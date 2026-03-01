from __future__ import annotations

import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


def _load_module():
    repo_root = Path(__file__).resolve().parents[3]
    module_path = repo_root / "scripts" / "release_readiness_report.py"
    spec = spec_from_file_location("release_readiness_report", module_path)
    assert spec and spec.loader
    module = module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_compute_local_ok_is_name_based_not_order_based():
    module = _load_module()
    gates = [
        module.GateStatus("smoke-workflows", 0),
        module.GateStatus("diarization-orchestrator", 1),
        module.GateStatus("smoke-perf-cost", 0),
        module.GateStatus("make verify", 0),
        module.GateStatus("smoke-security", 0),
        module.GateStatus("smoke-hosted", 0),
        module.GateStatus("smoke-local", 0),
    ]

    assert module._compute_local_ok(gates) is True


def test_compute_local_ok_is_false_when_required_local_gate_missing():
    module = _load_module()
    gates = [
        module.GateStatus("make verify", 0),
        module.GateStatus("smoke-local", 0),
        module.GateStatus("smoke-security", 0),
        module.GateStatus("smoke-workflows", 0),
        module.GateStatus("smoke-perf-cost", 0),
        module.GateStatus("diarization-orchestrator", 0),
    ]

    assert module._compute_local_ok(gates) is False


def test_gate_ok_lookup_uses_gate_name_not_index():
    module = _load_module()
    gates = [
        module.GateStatus("make verify", 0),
        module.GateStatus("smoke-hosted", 0),
        module.GateStatus("smoke-local", 0),
        module.GateStatus("smoke-security", 0),
        module.GateStatus("smoke-workflows", 0),
        module.GateStatus("diarization-orchestrator", 0),
        module.GateStatus("smoke-perf-cost", 1),
    ]

    assert module._gate_ok(gates, "smoke-perf-cost") is False
