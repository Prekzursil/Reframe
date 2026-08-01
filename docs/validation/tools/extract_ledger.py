"""Recover the Reframe v1.5 audit output from a workflow journal that FAILED at the
1000-agent cap before its synthesis step ran.

The orchestration ceiling failed, not the work: 1192 of 1237 agents recorded a result
(0 agent errors). Every audit agent returned a schema-validated {findings:[...]} object
and every verifier a {refuted, reason, corrected_claim?} object, so the ledger can be
rebuilt deterministically from the journal instead of re-spending 147M tokens.

Deliberately NOT an LLM pass: dedup, severity ranking and verdict-joining are mechanical.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

JOURNAL = Path(sys.argv[1])
OUT = Path(sys.argv[2])

results: list[dict] = []
with JOURNAL.open("r", encoding="utf-8", errors="replace") as fh:
    for line in fh:
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("type") == "result":
            results.append(rec)

findings: list[dict] = []      # audit agents
verdicts: list[dict] = []      # adversarial verifiers
prose: list[tuple[str, str]] = []  # ground / reconcile (plain text)

for rec in results:
    key = str(rec.get("key") or "")
    val = rec.get("result")
    if isinstance(val, dict) and isinstance(val.get("findings"), list):
        for f in val["findings"]:
            if isinstance(f, dict):
                f = dict(f)
                f["_key"] = key
                findings.append(f)
    elif isinstance(val, dict) and "refuted" in val:
        v = dict(val)
        v["_key"] = key
        verdicts.append(v)
    elif isinstance(val, str) and len(val) > 400:
        prose.append((key, val))

# ---- deterministic dedup (same rule the workflow used) ----
def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s).lower())[:60]

seen: set[str] = set()
deduped: list[dict] = []
for f in findings:
    k = f"{norm(f.get('surface'))}|{norm(f.get('title'))}"
    if k in seen:
        continue
    seen.add(k)
    deduped.append(f)

SEV = {"critical": 0, "high": 1, "medium": 2, "low": 3}
deduped.sort(key=lambda f: (SEV.get(str(f.get("severity", "low")).lower(), 9), str(f.get("surface", ""))))

sev_counts = Counter(str(f.get("severity", "?")).lower() for f in deduped)
raw_sev = Counter(str(f.get("severity", "?")).lower() for f in findings)
conf_counts = Counter(str(f.get("confidence", "?")).lower() for f in deduped)
by_surface: dict[str, int] = defaultdict(int)
by_lens: dict[str, int] = defaultdict(int)
for f in deduped:
    by_surface[str(f.get("surface", "?"))] += 1
    by_lens[str(f.get("lens", "?"))] += 1

refuted = sum(1 for v in verdicts if v.get("refuted") is True)
survived = sum(1 for v in verdicts if v.get("refuted") is False)
corrections = [v for v in verdicts if v.get("corrected_claim")]

print(f"result records      : {len(results)}")
print(f"raw findings        : {len(findings)}   {dict(raw_sev)}")
print(f"deduped findings    : {len(deduped)}   {dict(sev_counts)}")
print(f"confidence spread   : {dict(conf_counts)}")
print(f"verifier verdicts   : {len(verdicts)}  (refuted={refuted} survived={survived})")
print(f"scope corrections   : {len(corrections)}")
print(f"prose artifacts     : {len(prose)}")
print()
print("findings per lens (top 12):")
for lens, n in sorted(by_lens.items(), key=lambda kv: -kv[1])[:12]:
    print(f"  {n:4}  {lens}")
print()
print("SILENT lenses/surfaces (0 findings — suspicious vs genuinely clean):")
print(f"  surfaces reporting: {len(by_surface)}")

# ---- write the ledger ----
with OUT.open("w", encoding="utf-8") as fh:
    fh.write("# Reframe v1.5 — Recovered Audit Ledger\n\n")
    fh.write(
        "Rebuilt deterministically from `journal.jsonl` after the workflow hit the "
        "1000-agent cap and died BEFORE its synthesis step. The work succeeded "
        "(1192 results, 0 agent errors); only the orchestration ceiling failed. "
        "Dedup/ranking/verdict-joining here are mechanical, not an LLM re-read.\n\n"
    )
    fh.write("## Provenance\n\n")
    fh.write(f"- result records: **{len(results)}**\n")
    fh.write(f"- raw findings: **{len(findings)}** -> deduped **{len(deduped)}**\n")
    fh.write(f"- severity (deduped): {dict(sev_counts)}\n")
    fh.write(f"- confidence (deduped): {dict(conf_counts)}\n")
    fh.write(f"- verifier verdicts recorded: **{len(verdicts)}** (refuted {refuted} / survived {survived})\n")
    fh.write(
        "\n> ⚠️ **Verification is INCOMPLETE.** The cap hit mid-verify, so most findings below "
        "carry NO adversarial verdict. Treat every unverified item as a CLAIM, not a defect. "
        "Prior measured base rate on this program: ~5 of 8 refutations were OVERCLAIMS whose "
        "underlying code was fine.\n\n"
    )

    if corrections:
        fh.write("## Scope corrections issued by verifiers (highest signal)\n\n")
        for v in corrections[:40]:
            fh.write(f"- **{v.get('_key','?')}** — {v.get('corrected_claim')}\n")
        fh.write("\n")

    for sev in ("critical", "high", "medium", "low"):
        rows = [f for f in deduped if str(f.get("severity", "")).lower() == sev]
        if not rows:
            continue
        fh.write(f"## {sev.upper()} ({len(rows)})\n\n")
        for f in rows:
            fh.write(f"### {f.get('title','(untitled)')}\n")
            fh.write(f"- surface: `{f.get('surface','?')}` · lens: `{f.get('lens','?')}` · confidence: **{f.get('confidence','?')}**\n")
            fh.write(f"- evidence: {f.get('evidence','(none)')}\n")
            fh.write(f"- why: {f.get('why_it_matters','')}\n")
            fh.write(f"- fix: {f.get('proposed_fix','')}\n\n")

    fh.write("## Prose artifacts (ground + reconcile passes)\n\n")
    for key, text in prose:
        fh.write(f"### {key}\n\n{text}\n\n---\n\n")

print(f"\nwrote {OUT}  ({OUT.stat().st_size/1024:.0f} KB)")
