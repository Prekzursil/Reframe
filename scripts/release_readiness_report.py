#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PYANNOTE_BLOCKER_ISSUE_URL = "https://github.com/Prekzursil/Reframe/issues/80"
PYANNOTE_BLOCKER_OWNER = "@Prekzursil"
PYANNOTE_BLOCKER_RECHECK_DATE = "2026-03-07"
LOCAL_GATE_NAMES = (
    "make verify",
    "smoke-hosted",
    "smoke-local",
    "smoke-security",
    "smoke-workflows",
    "smoke-perf-cost",
)
PERF_COST_GATE_NAME = "smoke-perf-cost"


@dataclass
class GateStatus:
    name: str
    exit_code: int

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


def _gate_lookup(gates: list[GateStatus]) -> dict[str, GateStatus]:
    return {gate.name: gate for gate in gates}


def _compute_local_ok(gates: list[GateStatus]) -> bool:
    lookup = _gate_lookup(gates)
    return all(name in lookup and lookup[name].ok for name in LOCAL_GATE_NAMES)


def _gate_ok(gates: list[GateStatus], gate_name: str) -> bool:
    gate = _gate_lookup(gates).get(gate_name)
    return bool(gate and gate.ok)


def _run_json(cmd: list[str], *, cwd: Path) -> dict[str, Any] | list[Any] | None:
    try:
        proc = subprocess.run(cmd, cwd=str(cwd), text=True, capture_output=True, check=False)
    except FileNotFoundError:
        return None
    if proc.returncode != 0:
        return None
    try:
        return json.loads(proc.stdout.strip())
    except json.JSONDecodeError:
        return None


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _load_latest_updater_result(plans: Path, platform: str) -> tuple[dict[str, Any] | None, Path | None]:
    candidates = sorted(plans.glob(f"*-updater-e2e-{platform}.json"), reverse=True)
    for candidate in candidates:
        payload = _load_json(candidate)
        if payload is not None:
            return payload, candidate
    return None, None


def _main_sha(repo: Path) -> str | None:
    proc = subprocess.run(["git", "rev-parse", "origin/main"], cwd=str(repo), text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def _collect_gh_status(repo: Path) -> dict[str, Any]:
    out: dict[str, Any] = {"ci": None, "codeql": None, "branch_protection": None}
    main_sha = _main_sha(repo)

    runs = _run_json(
        [
            "gh",
            "run",
            "list",
            "--limit",
            "20",
            "--json",
            "workflowName,status,conclusion,headSha,createdAt,url",
            "--repo",
            "Prekzursil/Reframe",
        ],
        cwd=repo,
    )
    if isinstance(runs, list):
        for wf_name, out_key in (("CI", "ci"), ("CodeQL", "codeql")):
            match = next((r for r in runs if r.get("workflowName") == wf_name and (not main_sha or r.get("headSha") == main_sha)), None)
            out[out_key] = match

    protection = _run_json(
        ["gh", "api", "repos/Prekzursil/Reframe/branches/main/protection"],
        cwd=repo,
    )
    if isinstance(protection, dict):
        checks = ((protection.get("required_status_checks") or {}).get("contexts") or [])
        out["branch_protection"] = {
            "required_reviews": ((protection.get("required_pull_request_reviews") or {}).get("required_approving_review_count")),
            "linear_history": ((protection.get("required_linear_history") or {}).get("enabled")),
            "required_checks": checks,
        }

    return out


def _display_path(path: Path, repo: Path) -> str:
    candidate = path if path.is_absolute() else (repo / path)
    try:
        return str(candidate.resolve().relative_to(repo.resolve()))
    except ValueError:
        return str(path)


def _safe_output_path(raw: str, fallback: Path, *, root: Path) -> Path:
    candidate = Path(raw).expanduser() if raw else fallback
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"Output path escapes repository root: {candidate}") from exc
    return resolved


def _resolve_status(*, local_ok: bool, updater_ok: bool, pyannote_cpu_status: str) -> tuple[str, list[str], list[str]]:
    blocking: list[str] = []
    external: list[str] = []

    if not local_ok:
        blocking.append("Local verification gates failed (verify/smoke).")
    if not updater_ok:
        blocking.append("Desktop updater OS matrix evidence is incomplete or failing.")

    if pyannote_cpu_status == "failed":
        blocking.append("Pyannote CPU benchmark execution failed.")
    elif pyannote_cpu_status == "blocked_external":
        external.append("Pyannote gated-model access is blocked externally (Hugging Face authorization).")

    if not blocking:
        if external:
            return "READY_WITH_EXTERNAL_BLOCKER", blocking, external
        return "READY", blocking, external
    return "NOT_READY", blocking, external


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Aggregate release-readiness evidence into markdown/json summaries.")
    parser.add_argument("--stamp", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    parser.add_argument("--verify-exit", type=int, required=True)
    parser.add_argument("--smoke-hosted-exit", type=int, required=True)
    parser.add_argument("--smoke-local-exit", type=int, required=True)
    parser.add_argument("--smoke-security-exit", type=int, required=False, default=0)
    parser.add_argument("--smoke-workflows-exit", type=int, required=False, default=0)
    parser.add_argument("--smoke-perf-cost-exit", type=int, required=False, default=0)
    parser.add_argument("--diarization-exit", type=int, required=True)
    parser.add_argument("--out-md", default="")
    parser.add_argument("--out-json", default="")
    args = parser.parse_args(argv)

    repo = Path(__file__).resolve().parents[1]
    plans = repo / "docs" / "plans"
    plans.mkdir(parents=True, exist_ok=True)

    try:
        out_md = _safe_output_path(args.out_md, plans / f"{args.stamp}-release-confidence-report.md", root=repo)
        out_json = _safe_output_path(args.out_json, plans / f"{args.stamp}-release-readiness-summary.json", root=repo)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    gates = [
        GateStatus("make verify", args.verify_exit),
        GateStatus("smoke-hosted", args.smoke_hosted_exit),
        GateStatus("smoke-local", args.smoke_local_exit),
        GateStatus("smoke-security", args.smoke_security_exit),
        GateStatus("smoke-workflows", args.smoke_workflows_exit),
        GateStatus("smoke-perf-cost", args.smoke_perf_cost_exit),
        GateStatus("diarization-orchestrator", args.diarization_exit),
    ]

    updater_results: dict[str, dict[str, Any]] = {}
    updater_ok = True
    for platform in ("windows", "macos", "linux"):
        stamp_path = plans / f"{args.stamp}-updater-e2e-{platform}.json"
        payload = _load_json(stamp_path)
        source_path = stamp_path if payload else None

        if payload is None:
            payload, source_path = _load_latest_updater_result(plans, platform)

        if payload is None:
            updater_results[platform] = {"success": False, "missing": True}
            updater_ok = False
            continue

        result = dict(payload)
        if source_path:
            result["source_file"] = str(source_path.relative_to(plans))
        updater_results[platform] = result
        if not bool(result.get("success")):
            updater_ok = False

    pyannote = _load_json(plans / f"{args.stamp}-pyannote-benchmark-status.json") or {}
    pyannote_cpu_status = str(((pyannote.get("cpu") or {}).get("status") or "unknown"))

    local_ok = _compute_local_ok(gates)
    status, blocking, external = _resolve_status(
        local_ok=local_ok,
        updater_ok=updater_ok,
        pyannote_cpu_status=pyannote_cpu_status,
    )

    gh_status = _collect_gh_status(repo)

    payload = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "stamp": args.stamp,
        "status": status,
        "gates": [{"name": g.name, "exit_code": g.exit_code, "ok": g.ok} for g in gates],
        "updater": updater_results,
        "pyannote": pyannote,
        "blocking_reasons": blocking,
        "external_blockers": external,
        "github": gh_status,
    }
    if pyannote_cpu_status == "blocked_external":
        payload["external_blocker_tracking"] = {
            "issue_url": PYANNOTE_BLOCKER_ISSUE_URL,
            "owner": PYANNOTE_BLOCKER_OWNER,
            "recheck_date": PYANNOTE_BLOCKER_RECHECK_DATE,
        }
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    lines: list[str] = []
    lines.append(f"# Reframe Release Confidence Report ({args.stamp})")
    lines.append("")
    lines.append(f"- status: `{status}`")
    lines.append(f"- generated_utc: `{payload['timestamp_utc']}`")
    lines.append("")
    lines.append("## Local gates")
    lines.append("")
    for g in payload["gates"]:
        marker = "PASS" if g["ok"] else "FAIL"
        lines.append(f"- {g['name']}: `{marker}` (exit `{g['exit_code']}`)")

    lines.append("")
    lines.append("## Performance and cost readiness")
    lines.append("")
    perf_cost_ok = _gate_ok(gates, PERF_COST_GATE_NAME)
    lines.append(f"- smoke-perf-cost: `{'PASS' if perf_cost_ok else 'FAIL'}`")
    lines.append(f"- usage-cost endpoint gate: `{'ready' if perf_cost_ok else 'needs_attention'}`")

    lines.append("")
    lines.append("## Desktop updater matrix")
    lines.append("")
    for platform, result in updater_results.items():
        success = bool(result.get("success"))
        marker = "PASS" if success else "PENDING/FAIL"
        lines.append(f"- {platform}: `{marker}`")

    lines.append("")
    lines.append("## Pyannote benchmark")
    lines.append("")
    lines.append(f"- cpu_status: `{pyannote_cpu_status}`")
    gpu_status = str(((pyannote.get("gpu") or {}).get("status") or "unknown"))
    lines.append(f"- gpu_status: `{gpu_status}`")

    lines.append("")
    lines.append("## GitHub policy/check snapshot")
    lines.append("")
    ci = gh_status.get("ci")
    codeql = gh_status.get("codeql")
    bp = gh_status.get("branch_protection")
    lines.append(f"- ci: `{(ci or {}).get('conclusion', 'unknown')}`")
    lines.append(f"- codeql: `{(codeql or {}).get('conclusion', 'unknown')}`")
    lines.append(f"- required_reviews: `{(bp or {}).get('required_reviews', 'unknown')}`")
    lines.append(f"- linear_history: `{(bp or {}).get('linear_history', 'unknown')}`")

    if blocking:
        lines.append("")
        lines.append("## Blocking reasons")
        lines.append("")
        for item in blocking:
            lines.append(f"- {item}")

    if external:
        lines.append("")
        lines.append("## External blockers")
        lines.append("")
        for item in external:
            lines.append(f"- {item}")
        tracking = payload.get("external_blocker_tracking")
        if isinstance(tracking, dict):
            lines.append(
                "- Tracking issue: "
                f"{tracking.get('issue_url')} "
                f"(owner: {tracking.get('owner')}, recheck target: {tracking.get('recheck_date')})"
            )

    lines.append("")
    lines.append("## Evidence files")
    lines.append("")
    lines.append(f"- `{_display_path(out_json, repo)}`")
    lines.append(f"- `docs/plans/{args.stamp}-updater-e2e-*.json`")
    lines.append(f"- `docs/plans/{args.stamp}-pyannote-benchmark-status.json`")

    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return 0 if status in {"READY", "READY_WITH_EXTERNAL_BLOCKER"} else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
